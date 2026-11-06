"""Build data/companies.json by mining real job-board URLs out of Simplify's
public internship and new-grad listings.

Every link in those feeds points at a company's actual job board (Workday,
Greenhouse, ...), so this gives verified board names instead of guesses.
Companies are ranked by how many postings they've had (a decent proxy for
size/hiring volume) and the top N are kept.

Entries you add by hand (data/companies_manual.txt) and entries found by
tools/discover.py are kept separately and always included.

Usage:  python tools/build_companies.py [--top 1000]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from finder.sources import parse_board_url, board_key, session  # noqa: E402

FEEDS = [
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
]
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "companies.json")


def load_feed(src):
    if os.path.exists(src):
        with open(src) as f:
            return json.load(f)
    r = session().get(src, timeout=120)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=1000, help="how many companies to keep")
    ap.add_argument("--feeds", nargs="*", default=FEEDS, help="feed URLs or local files")
    args = ap.parse_args()

    per_company = collections.defaultdict(collections.Counter)   # name -> board_key -> count
    boards = {}
    totals = collections.Counter()
    recent = collections.Counter()
    max_ts = 0
    rows = []
    for src in args.feeds:
        rows += load_feed(src)
    max_ts = max((r.get("date_posted") or 0) for r in rows)
    for r in rows:
        name = (r.get("company_name") or "").strip()
        if not name:
            continue
        b = parse_board_url(r.get("url", ""))
        if not b:
            totals[name] += 1        # still counts toward size, even if unsupported ATS
            continue
        b["name"] = name
        k = board_key(b)
        boards.setdefault(k, b)
        per_company[name][k] += 1
        totals[name] += 1
        if (r.get("date_posted") or 0) > max_ts - 400 * 86400:
            recent[name] += 1

    # rank companies with a supported board by total postings (recent ones count double)
    score = {n: totals[n] + recent[n] for n in per_company}
    ranked = sorted(score, key=lambda n: -score[n])[: args.top]

    out, used = [], set()
    for name in ranked:
        # keep the main board, plus any other board with a meaningful share
        counts = per_company[name].most_common()
        top_count = counts[0][1]
        for k, c in counts[:3]:
            if k in used:      # e.g. "Boeing" and "The Boeing Company" share a board
                continue
            if c == top_count or c >= max(3, top_count * 0.25):
                used.add(k)
                b = dict(boards[k])
                b["name"] = name
                b["postings_seen"] = c
                b["origin"] = "simplify"
                out.append(b)

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    by_ats = collections.Counter(b["ats"] for b in out)
    unsupported = sorted((n for n in totals if n not in per_company), key=lambda n: -totals[n])[:25]
    print(f"Wrote {len(out)} boards for {len(ranked)} companies -> {OUT}")
    print("By job system:", dict(by_ats))
    print("Big companies on unsupported/custom sites (still covered via the Simplify feed):")
    print("  " + ", ".join(unsupported))


if __name__ == "__main__":
    main()
