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
from finder import sources, digest  # noqa: E402
from finder.state import State  # noqa: E402
from finder.slack import _EMOJI as slack_emoji_re  # noqa: E402


def slack_emoji(text):
    return slack_emoji_re.search(text)

# ------------------------------------------------------------- fake Slack
received = []


class Hook(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Hook)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["SLACK_WEBHOOK_URL"] = f"http://127.0.0.1:{srv.server_port}/all"
scan.time.sleep = lambda s: None
sources.time.sleep = lambda s: None

# ------------------------------------------------------------- fake boards
BOARDS = [
    {"ats": "greenhouse", "slug": "acme", "name": "Databricks"},        # Tier 2, tech
    {"ats": "lever", "slug": "leverco", "name": "Palantir"},            # Tier 2, tech
    {"ats": "smartrecruiters", "slug": "SRCorp", "name": "Visa"},       # Tier 1, tech
    {"ats": "workday", "host": "bigbank.wd5.myworkdayjobs.com", "tenant": "bigbank", "site": "External",
     "name": "Goldman Sachs"},                                          # Tier 1, not tech
    {"ats": "ashby", "slug": "tinyco", "name": "TinyCo"},               # small company: skipped
    {"ats": "greenhouse", "slug": "broken", "name": "Broken Inc"},
]
WORLD = {"round": 1}

GH_DESC = {
    "5": "Candidates must be currently pursuing an MBA. Summer 2027.",
    "6": "Our Fall 2027 internship for students graduating in 2028.",
    "10": "This Summer 2027 role is based in our Toronto office.",
}


def gh(i, title, loc="New York, NY"):
    return {"id": i, "title": title, "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{i}",
            "location": {"name": loc}, "first_published": f"2026-11-0{1 + i % 6}T09:00:00-05:00"}


def gh_jobs():
    jobs = [gh(1, "Product Manager Intern"), {"id": 2, "title": "Senior Software Engineer",
                                              "absolute_url": "https://x/2", "location": {"name": "NYC"}}]
    if WORLD["round"] >= 2:
        jobs += [gh(20 + i, f"Strategy & Operations Intern - Team {i}") for i in range(17)]  # main section cap is 15
        jobs += [gh(3, "Growth Marketing Intern - Summer 2027", "Austin, TX"),
                 gh(4, "Marketing Intern", "London, United Kingdom"),           # non-US
                 gh(5, "Strategy Intern"),                                      # MBA-only description
                 gh(6, "Finance Intern"),                                       # fall internship
                 gh(7, "MBA Summer Intern - Brand"),                            # MBA in title
                 gh(8, "Software Engineering Intern"),                          # engineering: not a section
                 gh(9, "Product Manager Intern", "Baku, Azerbaijan"),           # non-US
                 gh(10, "Product Analyst Intern", "Remote"),                    # description says Toronto
                 gh(11, "Sophomore Explore Program - Business", "Seattle, WA"),  # underclass program
                 gh(12, "Strategy & Operations Intern", "San Francisco, CA")]
    return {"jobs": jobs}


def wd_jobs(term, offset):
    posts = [{"title": "2027 Summer Analyst - Investment Banking", "externalPath": "/job/NY/Summer-Analyst_R1",
              "locationsText": "New York, NY"}]
    if WORLD["round"] >= 2:
        posts += [{"title": "Data Analytics Summer Intern", "externalPath": f"/job/{c}/Data-Intern_R{n}", "locationsText": c}
                  for n, c in [(2, "Charlotte, NC"), (3, "Dallas, TX")]]            # same role, 2 cities -> 1 entry
        posts += [{"title": f"Operations Intern {i}", "externalPath": f"/job/x/Ops_{i}", "locationsText": "Remote"}
                  for i in range(25)]                                                # not a section category
        posts += [{"title": "Real Estate Investment Intern", "externalPath": "/job/NY/RE_R9", "locationsText": "New York, NY"}]
        posts += [{"title": "Business Analyst Summer Intern", "externalPath": "/job/NY/BA_R10", "locationsText": "New York, NY"}]
    if term not in ("intern", "summer"):
        return {"jobPostings": []}
    return {"jobPostings": posts[offset:offset + 20], "total": len(posts)}


def fake_get(url, **kw):
    p = kw.get("params") or {}
    if "ashbyhq" in url:
        jobs = [{"id": "t1", "title": "Product Manager Intern", "location": "Austin, TX", "isListed": True,
                 "jobUrl": "https://jobs.ashbyhq.com/tinyco/t1", "descriptionPlain": "Undergraduates. Summer 2027."}]
        if WORLD["round"] >= 2:
            jobs.append({"id": "t2", "title": "Product Manager Intern II", "location": "Austin, TX", "isListed": True,
                         "jobUrl": "https://jobs.ashbyhq.com/tinyco/t2", "descriptionPlain": "Undergraduates. Summer 2027."})
        return {"jobs": jobs}
    if "greenhouse" in url:
        if "/broken/" in url:
            raise sources.requests.HTTPError("404 Not Found")
        if "/jobs/" in url:
            jid = url.rsplit("/", 1)[1]
            return {"content": "&lt;p&gt;" + GH_DESC.get(jid, "Undergraduates graduating between December 2027 "
                                                          "and June 2028. Summer 2027 internship.") + "&lt;/p&gt;"}
        return gh_jobs()
    if "lever.co" in url and url.rstrip("/").split("/")[-1] in ("a1", "a2"):
        return {"descriptionPlain": "Open to rising juniors and seniors pursuing a bachelor's degree.", "lists": []}
    if "lever.co" in url:
        out = [{"id": "a1", "text": "Corporate Strategy Intern", "hostedUrl": "https://jobs.lever.co/leverco/a1",
                "categories": {"location": "Chicago, IL"}, "createdAt": 1793900000000}]
        if WORLD["round"] >= 2:
            out.append({"id": "a2", "text": "Venture Capital Intern (Summer 2027)", "hostedUrl": "https://jobs.lever.co/leverco/a2",
                        "categories": {"location": "Boston, MA"}, "createdAt": 1793990000000})
        return out
    if "smartrecruiters" in url and "/postings/" in url:
        return {"jobAd": {"sections": {"qualifications": {"text": "<p>Class of 2029 students.</p>"}}}}
    if "smartrecruiters" in url:
        c = [{"id": "s1", "name": "Accounting Intern", "location": {"city": "Denver", "region": "CO", "country": "us"},
              "releasedDate": "2026-11-05T12:00:00.000Z"}]
        if WORLD["round"] >= 2 and p.get("q") == "intern":
            c.append({"id": "s2", "name": "Treasury Analyst Intern", "location": {"city": "Atlanta", "region": "GA", "country": "us"}})
        return {"content": c if p.get("offset", 0) == 0 else []}
    if "myworkdayjobs" in url and "/job/" in url:
        return {"jobPostingInfo": {"jobDescription": "<p>Summer 2027 program for undergraduates.</p>",
                                   "location": "New York, NY"}}
    raise AssertionError("unexpected GET " + url)


def fake_post(url, payload, **kw):
    assert "/wday/cxs/bigbank/External/jobs" in url, url
    return wd_jobs(payload["searchText"], payload["offset"])


sources._get, sources._post = fake_get, fake_post
sources._wd_post = fake_post
simplify_file = sys.argv[1] if len(sys.argv) > 1 else None
_simplify_rows = json.load(open(simplify_file)) if simplify_file else []


def fake_simplify():
    rows = [r for r in _simplify_rows if r.get("active")][:300]
    if WORLD["round"] >= 2:
        rows = rows + [
            {"company_name": "Databricks", "title": "Growth Marketing Intern - Summer 2027", "url": "https://simplify/acme",
             "id": "dup1", "active": True, "locations": ["Austin, TX"], "category": "Product"},       # duplicate
            {"company_name": "Google", "title": "Product Strategy Intern", "url": "https://careers.google.com/y",
             "id": "g2", "active": True, "locations": ["New York, NY"], "category": "Product",
             "terms": ["Summer 2027"], "degrees": ["Master's", "PhD"]},                               # grad-only
            {"company_name": "Google", "title": "Associate Product Manager Intern", "url": "https://careers.google.com/x",
             "id": "g1", "active": True, "locations": ["Mountain View, CA"], "category": "Product",
             "terms": ["Summer 2027"], "date_posted": 1793990000},
        ]
    return [sources.Job("simplify", "simplify", j["company_name"], j["title"], j["url"], str(j["id"]),
                        "; ".join(j.get("locations") or []), j.get("date_posted"), j.get("category", ""),
                        j.get("terms") or [], j.get("degrees") or []) for j in rows]


tmp = tempfile.mkdtemp()
STATE = os.path.join(tmp, "seen.json")
scan.State = lambda: State(STATE)
scan.load_companies = lambda: BOARDS
scan.fetch_simplify = fake_simplify
DUE = {"v": False}
digest.due = lambda state, cfg: DUE["v"]


def run(r, *extra):
    WORLD["round"] = r
    received.clear()
    sys.argv = ["scan.py", *extra]
    scan.main()
    sections, cur = {}, None
    for p in received:
        for b in p["blocks"]:
            if b["type"] == "section":
                parts = b["text"]["text"].split("\n\n")
                if parts[0].startswith("*") and "\n" not in parts[0]:
                    cur = parts[0].strip("*")
                    parts = parts[1:]
                sections.setdefault(cur, []).extend(parts)
    return received[:], sections


def queue():
    return json.load(open(STATE))["queue"]


print("\n========== RUN 1: first scan: record what's open, post nothing ==========")
msgs, _ = run(1)
assert msgs == [] and queue() == []

print("\n========== RUN 2: new roles appear: queued, digest not due yet ==========")
msgs, _ = run(2)
assert msgs == [], "nothing posted before digest time"
q = queue()
by = {}
for e in q:
    by.setdefault(e["section"], []).append(e["title"])
print(json.dumps(by, indent=1, ensure_ascii=False))
main, other = (s["name"] for s in digest.DEFAULT_SECTIONS)
# 18 Databricks strategy roles (tech) + Goldman's business analyst + 25 Goldman operations roles (big, non-tech)
assert len(by[main]) == 18 + 1 + 25, len(by[main])
assert "Business Analyst Summer Intern" in by[main]
assert set(by[other]) >= {"Associate Product Manager Intern", "Venture Capital Intern (Summer 2027)",
                          "Real Estate Investment Intern", "Data Analytics Summer Intern",
                          "Growth Marketing Intern - Summer 2027", "Sophomore Explore Program - Business",
                          "Treasury Analyst Intern"}, by[other]
assert by[other].count("Data Analytics Summer Intern") == 1, "two cities merged into one entry"
flat = " ".join(e["title"] + " " + e["url"] for e in q)
for bad in ["Strategy Intern ", "Finance Intern", "MBA Summer", "Software Engineering",
            "Product Analyst Intern", "Product Strategy Intern", "London", "Product Manager Intern II"]:
    assert bad not in flat + " ", bad
assert all("Baku" not in "; ".join(e["locations"]) for e in q), "non-US"
assert "boards.greenhouse.io/acme/jobs/3" in flat, "company link preferred over Simplify"

print("\n========== RUN 3: digest time: 15 business/strategy + 5 other, in ONE message ==========")
DUE["v"] = True
msgs, sections = run(3)
print("SECTIONS:", {k: len(v) for k, v in sections.items()})
main_e, other_e = main.replace("&", "&amp;"), other
assert len(msgs) == 1, "whole digest is one Slack message"
assert all(len(b.get("text", {}).get("text", "")) < 3000 for b in msgs[0]["blocks"]), "Slack block size limit"
assert len(msgs[0]["blocks"]) <= 50
assert msgs[0]["blocks"][0]["type"] == "header" and msgs[0]["blocks"][0]["text"]["text"].startswith("Internship Roundup")
assert len(sections[main_e]) == 15 and len(sections[other_e]) == 5, sections.keys()
assert all("Goldman" not in r for r in sections[main_e]), "tech companies listed before non-tech ones"
assert any(r.split("\n")[1].startswith(("Product", "Finance", "Data", "Marketing", "Freshman")) for r in sections[other_e]), \
    "role type shown in the mixed section"
allroles = " ".join(" ".join(v) for v in sections.values())
assert "Class of 2027–2028" in allroles and "Summer 2027" in allroles
assert not slack_emoji(json.dumps(msgs[0], ensure_ascii=False)), "no emojis"
left = queue()
print("carried over:", [e["title"] for e in left])
assert len(left) == 44 - 15 + 7 - 5 and any("Goldman" in e["company"] for e in left), "leftovers carry to tomorrow"

print("\n========== RUN 4: same day again: no second digest ==========")
DUE["v"] = False
msgs, _ = run(4)
assert msgs == []

print("\n========== RUN 5: next day: leftovers posted ==========")
DUE["v"] = True
msgs, sections = run(5)
assert len(sections[main_e]) == 15 and len(sections[other_e]) == 2 and len(queue()) == 14
assert sum("Databricks" in r for r in sections[main_e]) == 3, "remaining tech-company roles first"
before = open(STATE).read()

print("\n========== TEST MODE: sample digest, save nothing ==========")
DUE["v"] = False
msgs, sections = run(5, "--test-post", "2")
assert sections and all(len(v) <= 2 for v in sections.values()), sections
assert len(msgs) == 1 and "Test post" in json.dumps(msgs[0])
assert open(STATE).read() == before, "test mode must not change state"
assert json.load(open(STATE))["board_failures"].get("greenhouse:broken") == 5
print("\nSAMPLE DIGEST (as plain text):")
for b in msgs[0]["blocks"]:
    t = b.get("text", {}).get("text") or " ".join(x["text"] for x in b.get("elements", []))
    print(t if t else "-" * 50)
print("\nALL CHECKS PASSED ✅")
