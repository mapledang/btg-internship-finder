"""Scan every company's job board, find new internships, post them to Slack.

    python scan.py              # normal run (needs SLACK_WEBHOOK_URL)
    python scan.py --dry-run    # print what would be posted, don't save anything
    python scan.py --limit 50   # only scan the first 50 boards (for testing)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import time

import yaml

from finder.companies import load_companies, load_manual
from finder.filters import Filter, classify
from finder.sources import FETCHERS, board_key, fetch_simplify
from finder.state import State, fingerprint
from finder import slack

ROOT = os.path.dirname(os.path.abspath(__file__))


def fetch_board(b):
    try:
        return b, FETCHERS[b["ats"]](b), None
    except Exception as e:  # noqa: BLE001 - one bad board must not stop the run
        return b, [], f"{type(e).__name__}: {str(e)[:120]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--test-post", type=int, default=0, metavar="N",
                    help="post N real current internships as a test; doesn't change saved state")
    args = ap.parse_args()

    with open(os.path.join(ROOT, "config.yaml")) as f:
        cfg = yaml.safe_load(f) or {}
    flt = Filter(cfg)
    state = State()
    boards = load_companies()
    if args.limit:
        boards = boards[: args.limit]
    _, bad_manual = load_manual()

    if not args.dry_run and not os.environ.get("SLACK_WEBHOOK_URL") and not (
            os.environ.get("SLACK_WEBHOOK_TECH") and os.environ.get("SLACK_WEBHOOK_BUSINESS")):
        sys.exit("SLACK_WEBHOOK_URL is not set (add it as a GitHub Actions secret).")

    t0 = time.time()
    results, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for b, jobs, err in ex.map(fetch_board, boards):
            k = board_key(b)
            if err:
                failed.append((b, err))
                state.board_failed(k)
            else:
                results.append((k, jobs))
    if cfg.get("use_simplify_feed", True):
        try:
            results.append(("simplify", fetch_simplify()))
        except Exception as e:  # noqa: BLE001
            failed.append(({"name": "Simplify feed", "ats": "simplify"}, str(e)[:120]))
    fetch_secs = time.time() - t0

    if args.test_post:
        return test_post(args, results, failed, flt, fetch_secs)

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
                state.mark(j.uid, fp)       # first scan of this board, or already posted elsewhere
                seeded += 1
                continue
            if fp in new:                   # same role at several locations / in several sources
                it = new[fp]
                it["uids"].append(j.uid)
                if j.location and j.location not in it["locations"]:
                    it["locations"].append(j.location)
                continue
            new[fp] = {"job": j, "category": classify(j), "uids": [j.uid], "fp": fp,
                       "locations": [j.location] if j.location else []}
        state.board_ok(k)

    items = sorted(new.values(), key=lambda it: -(it["job"].posted or time.time()))
    cap = int(cfg.get("max_posts_per_run", 120))
    to_post, waiting = items[:cap], items[cap:]

    # ---- post
    posted = 0
    by_hook = {}
    for it in to_post:
        by_hook.setdefault(slack.webhook_for(it["category"]) or "", []).append(it)
    for hook, its in by_hook.items():
        for payload, chunk in slack.build_messages(its):
            if args.dry_run:
                for it in chunk:
                    j = it["job"]
                    print(f"[{it['category']:8}] {j.company} — {j.title} — {'; '.join(it['locations'])[:60]}\n           {j.url}")
                posted += len(chunk)
                continue
            if slack.post(hook, payload):
                for it in chunk:
                    for uid in it["uids"]:
                        state.mark(uid, it["fp"])
                posted += len(chunk)
            time.sleep(1.1)   # Slack allows ~1 message/second per webhook

    if not args.dry_run:
        state.save()

    # ---- report
    stale = sorted(((k, n) for k, n in state.failures.items() if n >= 12), key=lambda x: -x[1])
    lines = [
        "## Internship scan",
        f"- Boards scanned: **{len(results)}** ok, **{len(failed)}** failed ({fetch_secs:.0f}s)",
        f"- Internship listings matched: {matched}",
        f"- New posted to Slack: **{posted}**" + (f" ({len(waiting)} queued for next run)" if waiting else ""),
        f"- Recorded silently (first scan of a board, or duplicate): {seeded}",
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
    report = "\n".join(lines)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(report + "\n")


def test_post(args, results, failed, flt, fetch_secs):
    """Post the N most recently posted internships (one per company) so you can see it working."""
    picked, companies = [], set()
    pool = [j for _, jobs in results for j in jobs if j.url and flt.accept(j)]
    pool.sort(key=lambda j: -(j.posted or 0))
    for j in pool:
        if j.company in companies:
            continue
        companies.add(j.company)
        picked.append({"job": j, "category": classify(j), "uids": [j.uid], "fp": "",
                       "locations": [j.location] if j.location else []})
        if len(picked) >= args.test_post:
            break
    header = (f"🧪 *Test post from the internship finder.* It scanned {len(results)} job boards "
              f"({len(failed)} failed) and matched {len(pool)} open internships. "
              f"Here are {len(picked)} recent ones. Real alerts will only include newly released roles.")
    sent = 0
    by_hook = {}
    for it in picked:
        by_hook.setdefault(slack.webhook_for(it["category"]) or "", []).append(it)
    for hook, its in by_hook.items():
        for i, (payload, chunk) in enumerate(slack.build_messages(its, header=header)):
            if args.dry_run:
                print(json.dumps(payload, indent=1)[:3000])
                sent += len(chunk)
            elif slack.post(hook, payload):
                sent += len(chunk)
            time.sleep(1.1)
    report = (f"## Test post\n- Boards scanned: **{len(results)}** ok, **{len(failed)}** failed "
              f"({fetch_secs:.0f}s)\n- Open internships matched: {len(pool)}\n"
              f"- Test jobs sent to Slack: **{sent}** of {len(picked)}\n- Saved state: unchanged")
    if failed:
        report += "\n\n<details><summary>Failed boards</summary>\n\n" + "\n".join(
            f"- {b['name']} (`{b['ats']}`): {e}" for b, e in failed[:200]) + "\n\n</details>"
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(report + "\n")
    if not args.dry_run and picked and sent == 0:
        sys.exit("Couldn't post to Slack. Check that the SLACK_WEBHOOK_URL secret is the full webhook URL.")


if __name__ == "__main__":
    main()
