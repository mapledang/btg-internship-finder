"""Find job boards for companies that aren't in data/companies.json yet.

Reads company names from data/business_seed.txt (one per line; optionally
"Name | https://careers-page-or-any-job-link"). For each company it:

  1. parses the URL you gave, if it's a job link on a supported system;
  2. scrapes the careers page you gave (or www.<name>.com/careers) for links
     to Workday / Greenhouse / Lever / Ashby / SmartRecruiters / Oracle;
  3. guesses board names on Greenhouse, SmartRecruiters and Workday and keeps
     the ones that respond and whose company name matches.

Results are written to data/companies_discovered.json (merged into the scan
automatically), and anything not found is listed in data/discover_report.md so
you can add it by hand in data/companies_manual.txt.

This needs internet access to the job boards, so run it from the
"Discover companies" GitHub Action (or locally).
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from finder.sources import (parse_board_url, board_key, session, FETCHERS,  # noqa: E402
                            TIMEOUT)
from finder.companies import load_companies, norm_name  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
SEED = os.path.join(ROOT, "data", "business_seed.txt")
OUT = os.path.join(ROOT, "data", "companies_discovered.json")
REPORT = os.path.join(ROOT, "data", "discover_report.md")

ATS_LINK = re.compile(
    r"https?://[a-zA-Z0-9.-]*(?:myworkdayjobs\.com|myworkdaysite\.com|greenhouse\.io|lever\.co|"
    r"ashbyhq\.com|smartrecruiters\.com|oraclecloud\.com)[^\s\"'<>)]*")
SUFFIXES = re.compile(r"\b(inc|corp|corporation|company|co|group|holdings|llc|plc|ltd|the|&)\b", re.I)
WD_HOSTS = ["wd1", "wd5", "wd3", "wd12", "wd2", "wd10"]
WD_SITES = ["External", "Careers", "{T}Careers", "External_Careers", "ExternalCareers",
            "{T}_Careers", "{T}", "careers", "Search"]


def slugs_for(name):
    base = SUFFIXES.sub(" ", name.lower())
    words = re.findall(r"[a-z0-9]+", base)
    if not words:
        return []
    out = ["".join(words), "-".join(words)]
    if len(words) > 1 and len(words[0]) > 3:
        out.append(words[0])
    return list(dict.fromkeys(out))


def similar(a, b):
    a, b = norm_name(a), norm_name(b)
    return bool(a) and bool(b) and (a in b or b in a)


def try_board(b):
    """Return number of jobs if the board answers, else None."""
    try:
        return len(FETCHERS[b["ats"]](b))
    except Exception:
        return None


def check_greenhouse(slug, name):
    try:
        r = session().get(f"https://boards-api.greenhouse.io/v1/boards/{slug}", timeout=TIMEOUT)
        if r.status_code == 200 and similar(r.json().get("name", ""), name):
            return {"ats": "greenhouse", "slug": slug}
    except Exception:
        pass
    return None


def check_smartrecruiters(slug, name):
    try:
        r = session().get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                          params={"limit": 1}, timeout=TIMEOUT)
        c = r.json().get("content") or []
        if r.status_code == 200 and c and similar((c[0].get("company") or {}).get("name", ""), name):
            return {"ats": "smartrecruiters", "slug": slug}
    except Exception:
        pass
    return None


def check_workday(tenant):
    for wd in WD_HOSTS:
        host = f"{tenant}.{wd}.myworkdayjobs.com"
        for site in WD_SITES:
            site = site.replace("{T}", tenant.capitalize()) if "{T}" in site else site
            b = {"ats": "workday", "host": host, "tenant": tenant, "site": site}
            try:
                r = session().post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                                   json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                                   timeout=10)
                if r.status_code == 200 and "jobPostings" in r.text:
                    return b
            except (requests.ConnectionError, requests.Timeout):
                break   # host doesn't resolve / refuses: try the next wdN
    return None


def scrape_links(url):
    try:
        r = session().get(url, timeout=15, headers={"Accept": "text/html"})
        if r.status_code != 200:
            return []
        found = []
        for m in ATS_LINK.findall(r.text):
            b = parse_board_url(m)
            if b and b not in found:
                found.append(b)
        return found
    except Exception:
        return []


def discover(line):
    name, _, url = (x.strip() for x in line.partition("|"))
    found = []
    if url:
        b = parse_board_url(url)
        if b:
            found.append(b)
        else:
            found += scrape_links(url)
    slugs = slugs_for(name)
    if not found and slugs:
        for u in (f"https://www.{slugs[0]}.com/careers", f"https://careers.{slugs[0]}.com"):
            found += scrape_links(u)
            if found:
                break
    if not found:
        for s in slugs:
            b = check_greenhouse(s, name) or check_smartrecruiters(s, name)
            if b:
                found.append(b)
                break
    if not found:
        for s in slugs[:2]:
            if "-" in s:
                continue
            b = check_workday(s)
            if b:
                found.append(b)
                break
    good = []
    for b in found[:3]:
        n = try_board(b)
        if n is not None:
            b.update({"name": name, "origin": "discovered"})
            good.append(b)
    return name, good


def main():
    existing = {norm_name(b["name"]) for b in load_companies(include_discovered=False)}
    lines = []
    with open(SEED) as f:
        for raw in f:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            if norm_name(raw.partition("|")[0]) in existing and "|" not in raw:
                continue
            lines.append(raw)
    print(f"Discovering {len(lines)} companies...")
    results, missing = [], []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for name, boards in ex.map(discover, lines):
            if boards:
                results += boards
                print(f"  found  {name}: " + ", ".join(board_key(b) for b in boards))
            else:
                missing.append(name)
                print(f"  ----   {name}")
    seen, uniq = set(), []
    for b in results:
        k = board_key(b)
        if k not in seen:
            seen.add(k)
            uniq.append(b)
    with open(OUT, "w") as f:
        json.dump(uniq, f, indent=1, sort_keys=True)
    with open(REPORT, "w") as f:
        f.write(f"# Discovery report\n\nFound boards for {len(lines) - len(missing)} of {len(lines)} companies.\n\n")
        f.write("## Not found automatically\n\nThese probably use a custom careers site or an unsupported "
                "system (iCIMS, Taleo, Eightfold...). To add one, open its careers site, click any job, and "
                "paste `Company Name | <job link>` into `data/companies_manual.txt`. If the link isn't on a "
                "supported system, the company can't be scanned directly.\n\n")
        f.writelines(f"- {m}\n" for m in sorted(missing))
    print(f"\nFound {len(uniq)} boards; {len(missing)} not found (see {REPORT})")


if __name__ == "__main__":
    main()
