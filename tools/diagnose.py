"""Temporary: test failing Workday boards a few different ways and record what each returns."""
import json
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from finder.companies import load_companies  # noqa: E402
from finder.sources import board_key  # noqa: E402

state = json.load(open("data/seen.json"))
fail = state.get("board_failures", {})
boards = {board_key(b): b for b in load_companies()}
targets = [boards[k] for k in fail if k.startswith("workday:") and k in boards][:25]
ok_ones = [b for k, b in boards.items() if k.startswith("workday:") and k not in fail][:3]

UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
out = []
for b in ok_ones + targets:
    api = f"https://{b['host']}/wday/cxs/{b['tenant']}/{b['site']}/jobs"
    line = [f"{'OK-BOARD' if b in ok_ones else 'FAILING '} {b['name']} {api}"]
    for label, headers, payload in [
        ("bot-ua+search", {"User-Agent": "internship-finder/1.0", "Accept": "application/json"},
         {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}),
        ("browser-ua+search", {"User-Agent": UA_BROWSER, "Accept": "application/json",
                               "Content-Type": "application/json", "Accept-Language": "en-US"},
         {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}),
        ("browser-ua+nosearch", {"User-Agent": UA_BROWSER, "Accept": "application/json"},
         {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}),
    ]:
        try:
            r = requests.post(api, json=payload, headers=headers, timeout=20, allow_redirects=False)
            body = r.text[:160].replace("\n", " ")
            n = len(r.json().get("jobPostings", [])) if r.headers.get("content-type", "").startswith("application/json") and r.status_code == 200 else "-"
            line.append(f"   {label:20} HTTP {r.status_code} jobs={n} loc={r.headers.get('location', '')[:80]} body={body}")
        except Exception as e:  # noqa: BLE001
            line.append(f"   {label:20} ERROR {type(e).__name__}: {str(e)[:150]}")
    try:
        r = requests.get(f"https://{b['host']}/{b['site']}", headers={"User-Agent": UA_BROWSER}, timeout=20, allow_redirects=False)
        line.append(f"   public-page          HTTP {r.status_code} loc={r.headers.get('location', '')[:120]}")
    except Exception as e:  # noqa: BLE001
        line.append(f"   public-page          ERROR {type(e).__name__}: {str(e)[:150]}")
    out.append("\n".join(line))

open("data/diagnose.txt", "w").write("\n\n".join(out) + "\n")
print("\n\n".join(out))
