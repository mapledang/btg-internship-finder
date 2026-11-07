"""Scan company job boards for new internships, queue them by section, and post a daily digest.

    python scan.py                  # normal run: scan, queue new roles, post the digest if it's due
    python scan.py --digest-now     # also post the digest right away
    python scan.py --test-post 2    # post a sample digest (2 current roles per section); saves nothing
    python scan.py --dry-run        # print instead of posting; saves nothing
    python scan.py --limit 50       # only scan the first 50 boards (for testing)
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import os
import re
import sys
import time

import yaml

from finder import digest, slack
from finder.companies import load_companies, load_manual
from finder.details import enrich
from finder.filters import Filter, classify
from finder.sources import FETCHERS, STOP, board_key, fetch_simplify
from finder.state import State, fingerprint
from finder.tiers import tier

ROOT = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(msg, flush=True)


def fetch_board(b):
    try:
        jobs = FETCHERS[b["ats"]](b)
        for j in jobs:
            j.cfg = b
        return b, jobs, None
    except Exception as e:  # noqa: BLE001 - one bad board must not stop the run
        return b, [], f"{type(e).__name__}: {str(e)[:120]}"


def enrich_and_check(items, flt, secs, want_per_section=None):
    """Read descriptions in parallel, apply the undergrad / summer / US checks, assign sections.

    Returns (items that pass, Counter of skip reasons). Every item gets it["info"],
    it["reject"] (reason or None) and it["section"].
    """
    STOP.clear()
    keep, reasons, per = [], collections.Counter(), collections.Counter()
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for it, info in zip(items, ex.map(lambda it: enrich(it["job"]), items)):
            it["info"] = info
            it["reject"] = flt.reject_reason(info, it["job"], "; ".join(it["locations"]))
            it["section"] = None if it["reject"] else digest.section_for(it, secs)
            if not it["reject"] and not it["section"]:
                it["reject"] = "not in a digest section"
            if it["reject"]:
                reasons[re.sub(r"\s*[\(\[].*?[\)\]]", "", it["reject"])] += 1
                continue
            if want_per_section and per[it["section"]] >= want_per_section:
                continue
            per[it["section"]] += 1
            keep.append(it)
    return keep, reasons


def scan_boards(boards, cfg, args, state):
    t0 = time.time()
    STOP.clear()
    results, failed, skipped = [], [], 0
    if cfg.get("use_simplify_feed", True):
        try:
            results.append(("simplify", fetch_simplify()))
            log(f"Simplify feed: {len(results[0][1])} open listings")
        except Exception as e:  # noqa: BLE001
            failed.append(({"name": "Simplify feed", "ats": "simplify"}, str(e)[:120]))

    # Scan company boards in parallel, with progress updates and an overall time limit
    # so one slow site can never hold up the run.
    limit_secs = float(cfg.get("max_scan_minutes", 15)) * 60
    log(f"Scanning {len(boards)} company job boards ({args.workers} at a time, "
        f"time limit {limit_secs / 60:.0f} min)...")
    ex = cf.ThreadPoolExecutor(max_workers=args.workers)
    futures = [ex.submit(fetch_board, b) for b in boards]
    done = 0
    try:
        for fut in cf.as_completed(futures, timeout=limit_secs):
            b, jobs, err = fut.result()
            k = board_key(b)
            if err:
                failed.append((b, err))
                state.board_failed(k)
            else:
                results.append((k, jobs))
            done += 1
            if done % 100 == 0 or done == len(boards):
                log(f"  {done}/{len(boards)} boards done ({len(failed)} failed, {time.time() - t0:.0f}s)")
    except cf.TimeoutError:
        skipped = len(boards) - done
        log(f"  Time limit reached: skipping {skipped} slow boards this run.")
    finally:
        STOP.set()                      # tell any still-running fetches to give up
        ex.shutdown(wait=True, cancel_futures=True)
    return results, failed, skipped, time.time() - t0


def post_digest(picked, secs, title, args, extra=""):
    """Post intro + one message per section. Returns entries that were posted."""
    names = [s["name"] for s in secs]
    hook = slack.webhook()
    sent = []
    for payload, entries in slack.digest_messages(picked, names, title, extra):
        if args.dry_run:
            log("\n" + payload["text"][:200])
            for b in payload["blocks"]:
                if b["type"] == "section":
                    log("   " + b["text"]["text"].replace("\n", "\n   "))
            sent += entries
            continue
        if slack.post(hook, payload):
            sent += entries
        time.sleep(1.1)   # Slack allows ~1 message/second per webhook
    return sent


def write_report(lines):
    report = "\n".join(lines)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(report + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--digest-now", action="store_true", help="post the digest now, even if not due")
    ap.add_argument("--test-post", type=int, default=0, metavar="N",
                    help="post a sample digest with N current roles per section; saves nothing")
    args = ap.parse_args()

    with open(os.path.join(ROOT, "config.yaml")) as f:
        cfg = yaml.safe_load(f) or {}
    flt = Filter(cfg)
    secs = digest.sections(cfg)
    state = State()
    boards = sorted(load_companies(), key=lambda b: tier(b["name"]))   # Fortune 100 / big tech first
    if args.limit:
        boards = boards[: args.limit]
    if args.test_post and not args.limit:
        # Test mode only needs a quick sample: one board in every ~15, so it finishes in a few minutes.
        boards = boards[::15]
        cfg["max_scan_minutes"] = min(float(cfg.get("max_scan_minutes", 15)), 4)
    _, bad_manual = load_manual()

    if not args.dry_run and not slack.webhook():
        sys.exit("SLACK_WEBHOOK_URL is not set (add it as a GitHub Actions secret).")

    results, failed, skipped, fetch_secs = scan_boards(boards, cfg, args, state)

    if args.test_post:
        return test_post(args, cfg, results, failed, skipped, flt, secs, fetch_secs)

    # ---- find new internships
    new = {}            # fingerprint -> item
    seeded = matched = 0
    for k, jobs in results:
        ready = state.board_ready(k)
        for j in jobs:
            if not j.url or not flt.accept(j):
                continue
            matched += 1
            if state.seen(j.uid):
                continue
            fp = fingerprint(j.company, j.title)
            if not ready or state.fp_recent(fp):
                state.mark(j.uid, fp)       # first scan of this board, or already queued/posted
                seeded += 1
                continue
            if fp in new:                   # same role at several locations / in several sources
                it = new[fp]
                it["uids"].append(j.uid)
                if it["job"].source == "simplify" and j.source != "simplify":
                    it["job"] = j           # prefer the company's own job link
                if j.location and j.location not in it["locations"]:
                    it["locations"].append(j.location)
                continue
            new[fp] = {"job": j, "category": classify(j), "uids": [j.uid], "fp": fp,
                       "locations": [j.location] if j.location else []}
        state.board_ok(k)

    # biggest companies first, then newest
    items = sorted(new.values(), key=lambda it: (tier(it["job"].company), -(it["job"].posted or time.time())))
    cap = int(cfg.get("max_posts_per_run", 120))
    to_check, waiting = items[:cap], items[cap:]

    # ---- read descriptions, then queue what passes
    keep, rejected = enrich_and_check(to_check, flt, secs)
    for it in to_check:
        for uid in it["uids"]:
            state.mark(uid, it["fp"])       # checked: never re-check or re-queue it
    for it in keep:
        state.queue.append(digest.make_entry(it, it["section"]))
    queued = collections.Counter(it["section"] for it in keep)

    # ---- daily digest
    digest_line = "not due yet"
    if args.digest_now or digest.due(state, cfg):
        picked, rest = digest.pick(state.queue, cfg)
        n = sum(len(v) for v in picked.values())
        if n:
            sent = post_digest(picked, secs, digest.date_title(cfg), args)
            sent_ids = {id(e) for e in sent}
            unsent = [e for v in picked.values() for e in v if id(e) not in sent_ids]
            state.queue = unsent + rest
            digest_line = f"posted {len(sent)} roles"
        else:
            state.queue = rest
            digest_line = "nothing queued, skipped"
        state.last_digest = digest.today(cfg)

    if not args.dry_run:
        state.save()

    # ---- report
    stale = sorted(((k, n) for k, n in state.failures.items() if n >= 12), key=lambda x: -x[1])
    in_queue = collections.Counter(e["section"] for e in state.queue)
    lines = [
        "## Internship scan",
        f"- Boards scanned: **{len(results)}** ok, **{len(failed)}** failed"
        + (f", **{skipped}** skipped (time limit)" if skipped else "") + f" ({fetch_secs:.0f}s)",
        f"- Internship listings matched: {matched}",
        f"- New roles queued for the digest: **{sum(queued.values())}**"
        + (f" ({len(waiting)} more to check next run)" if waiting else ""),
        "- Skipped after reading descriptions: "
        + (", ".join(f"{n} {r}" for r, n in rejected.most_common()) if rejected else "none"),
        f"- Recorded silently (first scan of a board, or duplicate): {seeded}",
        f"- Daily digest: {digest_line}",
        "- Waiting in queue: " + (", ".join(f"{s}: {n}" for s, n in in_queue.items()) or "empty"),
    ]
    if bad_manual:
        lines.append("\n### Lines in companies_manual.txt that couldn't be read")
        lines += [f"- `{l}`" for l in bad_manual]
    if stale:
        lines.append("\n### Boards failing for 12+ runs in a row (consider removing)")
        lines += [f"- `{k}` ({n} runs)" for k, n in stale[:40]]
    if failed:
        lines.append("\n<details><summary>Failed this run</summary>\n")
        lines += [f"- {b['name']} (`{b['ats']}`): {e}" for b, e in failed[:200]]
        lines.append("\n</details>")
    write_report(lines)


def test_post(args, cfg, results, failed, skipped, flt, secs, fetch_secs):
    """Post a sample digest from currently open roles so you can see the format. Saves nothing."""
    candidates, seen_fp = [], set()
    pool = [j for _, jobs in results for j in jobs if j.url and flt.accept(j)]
    pool.sort(key=lambda j: (tier(j.company), j.source == "simplify", -(j.posted or time.time())))
    per_cat = collections.Counter()
    for j in pool:
        fp = fingerprint(j.company, j.title)
        cat = classify(j)
        if fp in seen_fp or per_cat[cat] >= args.test_post * 6:
            continue
        seen_fp.add(fp)
        per_cat[cat] += 1
        candidates.append({"job": j, "category": cat, "uids": [j.uid], "fp": fp,
                           "locations": [j.location] if j.location else []})
    keep, _ = enrich_and_check(candidates, flt, secs, want_per_section=args.test_post)
    picked = collections.defaultdict(list)
    for it in keep:
        picked[it["section"]].append(digest.make_entry(it, it["section"]))
    extra = ("🧪 _Test post: a sample from roles open right now. Real digests only include newly "
             "released roles, up to " + str((cfg.get('digest') or {}).get('per_section', 5)) + " per section._")
    sent = post_digest(picked, secs, digest.date_title(cfg), args, extra)
    write_report([
        "## Test digest",
        f"- Boards scanned (sample): **{len(results)}** ok, **{len(failed)}** failed, {skipped} skipped ({fetch_secs:.0f}s)",
        f"- Open internships matched: {len(pool)}",
        f"- Sample roles sent to Slack: **{len(sent)}**",
        "- Saved state: unchanged",
    ])
    if not args.dry_run and keep and not sent:
        sys.exit("Couldn't post to Slack. Check that the SLACK_WEBHOOK_URL secret is the full webhook URL.")


if __name__ == "__main__":
    main()
