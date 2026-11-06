"""End-to-end test with mocked job-board APIs and a fake Slack webhook.

Run:  python tests/test_e2e.py [path/to/simplify_listings.json]
"""
import http.server
import json
import os
import sys
import tempfile
import threading

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import scan  # noqa: E402
from finder import sources  # noqa: E402
from finder.state import State  # noqa: E402

# ------------------------------------------------------------- fake Slack
received = []


class Hook(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        received.append((self.path, json.loads(body)))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Hook)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
os.environ["SLACK_WEBHOOK_URL"] = base + "/all"
os.environ["SLACK_WEBHOOK_BUSINESS"] = base + "/business"
scan.time.sleep = lambda s: None          # don't wait between Slack messages in tests
sources.time.sleep = lambda s: None

# ------------------------------------------------------------- fake boards
BOARDS = [
    {"ats": "greenhouse", "slug": "acme", "name": "Acme"},
    {"ats": "lever", "slug": "leverco", "name": "LeverCo"},
    {"ats": "ashby", "slug": "AshCo", "name": "AshCo"},
    {"ats": "smartrecruiters", "slug": "SRCorp", "name": "SR Corp"},
    {"ats": "workday", "host": "bigbank.wd5.myworkdayjobs.com", "tenant": "bigbank", "site": "External", "name": "BigBank"},
    {"ats": "oracle", "host": "abcd.fa.us2.oraclecloud.com", "site": "CX_1", "name": "OraCorp"},
    {"ats": "greenhouse", "slug": "broken", "name": "Broken Inc"},
]
WORLD = {"round": 1}


def gh_jobs():
    jobs = [{"id": 1, "title": "Software Engineering Intern", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
             "location": {"name": "New York, NY"}, "first_published": "2026-11-01T09:00:00-05:00"},
            {"id": 2, "title": "Senior Software Engineer", "absolute_url": "https://x/2", "location": {"name": "NYC"}}]
    if WORLD["round"] >= 2:
        jobs.append({"id": 3, "title": "Marketing Intern - Summer 2027", "absolute_url": "https://boards.greenhouse.io/acme/jobs/3",
                     "location": {"name": "Austin, TX"}, "first_published": "2026-11-06T09:00:00-05:00"})
        jobs.append({"id": 4, "title": "Software Engineering Intern", "absolute_url": "https://boards.greenhouse.io/acme/jobs/4",
                     "location": {"name": "London, United Kingdom"}})   # non-US: should be dropped
    return {"jobs": jobs}


def wd_jobs(term, offset):
    posts = [{"title": "2027 Summer Analyst - Investment Banking", "externalPath": "/job/NY/Summer-Analyst_R1",
              "locationsText": "New York, NY"}]
    if WORLD["round"] >= 2:
        posts += [{"title": "Technology Summer Intern", "externalPath": f"/job/{c}/Tech-Intern_R{n}", "locationsText": c}
                  for n, c in [(2, "Charlotte, NC"), (3, "Dallas, TX")]]            # same role, 2 cities -> 1 post
        posts += [{"title": f"Operations Intern {i}", "externalPath": f"/job/x/Ops_{i}", "locationsText": "Remote"}
                  for i in range(25)]                                                # forces pagination
    if term != "intern" and term != "summer":
        return {"jobPostings": []}
    return {"jobPostings": posts[offset:offset + 20], "total": len(posts)}


def fake_get(url, **kw):
    p = kw.get("params") or {}
    if "greenhouse" in url:
        if "/broken/" in url:
            raise sources.requests.HTTPError("404 Not Found")
        return gh_jobs()
    if "lever.co" in url:
        out = [{"id": "a1", "text": "Finance Intern", "hostedUrl": "https://jobs.lever.co/leverco/a1",
                "categories": {"location": "Chicago, IL"}, "createdAt": 1793900000000}]
        if WORLD["round"] >= 2:
            out.append({"id": "a2", "text": "Data Science Co-op (Fall 2027)", "hostedUrl": "https://jobs.lever.co/leverco/a2",
                        "categories": {"location": "Boston, MA"}, "createdAt": 1793990000000})
        return out
    if "ashbyhq" in url:
        jobs = [{"id": "z1", "title": "Product Design Intern", "location": "San Francisco", "jobUrl": "https://jobs.ashbyhq.com/AshCo/z1", "isListed": True},
                {"id": "z2", "title": "Hidden Intern", "location": "SF", "jobUrl": "https://x", "isListed": False}]
        return {"jobs": jobs}
    if "smartrecruiters" in url:
        c = [{"id": "s1", "name": "Accounting Intern", "location": {"city": "Denver", "region": "CO", "country": "us"},
              "releasedDate": "2026-11-05T12:00:00.000Z"}]
        if WORLD["round"] >= 2 and p.get("q") == "intern":
            c.append({"id": "s2", "name": "Supply Chain Intern", "location": {"city": "Atlanta", "region": "GA", "country": "us"}})
        return {"content": c if p.get("offset", 0) == 0 else []}
    if "oraclecloud" in url:
        reqs = [{"Id": "900", "Title": "Treasury Intern", "PrimaryLocation": "Columbus, OH, United States",
                 "PostedDate": "2026-11-02"}]
        if WORLD["round"] >= 2:
            reqs.append({"Id": "901", "Title": "IT Intern", "PrimaryLocation": "Toronto, ON, Canada"})  # dropped
        return {"items": [{"requisitionList": reqs}]}
    raise AssertionError("unexpected GET " + url)


def fake_post(url, payload, **kw):
    assert "/wday/cxs/bigbank/External/jobs" in url, url
    return wd_jobs(payload["searchText"], payload["offset"])


sources._get, sources._post = fake_get, fake_post

simplify_file = sys.argv[1] if len(sys.argv) > 1 else None
_simplify_rows = json.load(open(simplify_file)) if simplify_file else []


def fake_simplify():
    rows = [r for r in _simplify_rows if r.get("active")][:300]
    if WORLD["round"] >= 2:
        rows = rows + [
            # same role Acme already has on Greenhouse -> must not be posted twice
            {"company_name": "Acme", "title": "Marketing Intern - Summer 2027", "url": "https://simplify/acme",
             "id": "dup1", "active": True, "locations": ["Austin, TX"], "category": "Software"},
            {"company_name": "Google", "title": "Student Researcher, 2027", "url": "https://careers.google.com/x",
             "id": "g1", "active": True, "locations": ["Mountain View, CA"], "category": "AI/ML/Data",
             "terms": ["Summer 2027"], "date_posted": 1793990000},
        ]
    out = []
    for j in rows:
        out.append(sources.Job("simplify", "simplify", j["company_name"], j["title"], j["url"], str(j["id"]),
                               "; ".join(j.get("locations") or []), j.get("date_posted"), j.get("category", ""),
                               j.get("terms") or []))
    return out


tmp = tempfile.mkdtemp()
scan.State = lambda: State(os.path.join(tmp, "seen.json"))
scan.load_companies = lambda: BOARDS
scan.fetch_simplify = fake_simplify


def run(r, extra=()):
    WORLD["round"] = r
    received.clear()
    sys.argv = ["scan.py", *extra]
    scan.main()
    titles = [b["text"]["text"] for _, p in received for b in p["blocks"] if b["type"] == "section"]
    return titles, [path for path, _ in received]


print("\n========== RUN 1: first scan, should post nothing ==========")
t, _ = run(1)
assert t == [], t

print("\n========== RUN 2: new jobs appear ==========")
t, paths = run(2)
print("\nPOSTED:")
for x in t:
    print(" •", x.split("\n")[0])
joined = "\n".join(t)
assert len(t) == 30, len(t)    # 1 GH + 1 Lever + 1 SR + 1 WD tech + 25 WD ops + 1 Google (Acme dup collapses)
assert "Marketing Intern" in joined and joined.count("Marketing Intern") == 1, "cross-source dedupe"
assert joined.count("Technology Summer Intern") == 1 and "Charlotte, NC; Dallas, TX" in joined, "multi-location merge"
assert "London" not in joined and "IT Intern" not in joined, "non-US filtered"
assert "Senior Software Engineer" not in joined and "Hidden Intern" not in joined
assert "Student Researcher, 2027" in joined, "Simplify feed"
assert "/business" in paths and "/all" in paths, "routing by category"

print("\n========== RUN 3: nothing new ==========")
t, _ = run(3)
assert t == [], t

before = open(os.path.join(tmp, "seen.json")).read()
print("\n========== TEST MODE: post 3 current jobs, save nothing ==========")
t, _ = run(3, ["--test-post", "3"])
heads = [b["text"]["text"] for _, p in received for b in p["blocks"] if b["type"] == "section"]
assert any("Test post" in h for h in heads), "test header"
assert len(t) - sum("Test post" in x for x in t) == 3, t
assert open(os.path.join(tmp, "seen.json")).read() == before, "test mode must not change state"

state = json.load(open(os.path.join(tmp, "seen.json")))
assert state["board_failures"].get("greenhouse:broken") == 3
print("\nALL CHECKS PASSED ✅")
