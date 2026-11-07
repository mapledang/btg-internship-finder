"""Fetchers for the public job-board APIs used by most large companies.

Each fetcher takes a board config (a dict from data/companies.json) and returns
a list of Job objects. Only Workday, Oracle and SmartRecruiters support a server
side keyword search; for the others we download the full board and filter
locally (they are fast, single-request APIs).
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse, parse_qs

import requests

TIMEOUT = (6, 15)   # seconds to connect, seconds to wait for data
USER_AGENT = "internship-finder/1.0 (+https://github.com)"
STOP = threading.Event()   # set when the run's time limit is reached

# Server-side search terms for boards that support keyword search.
SEARCH_TERMS = ["intern", "summer", "co-op"]


@dataclass
class Job:
    source: str          # ats name, e.g. "greenhouse" or "simplify"
    board: str           # unique board key, e.g. "greenhouse:stripe"
    company: str
    title: str
    url: str
    job_id: str          # unique within the board
    location: str = ""
    posted: float | None = None   # unix seconds, when known
    category_hint: str = ""       # e.g. Simplify's category
    terms: list = field(default_factory=list)
    degrees: list = field(default_factory=list)   # Simplify: e.g. ["Bachelor's", "Master's"]
    description: str = ""         # plain text, filled in for new jobs only
    cfg: dict = field(default=None, repr=False)   # the board config this job came from

    @property
    def uid(self) -> str:
        return f"{self.board}|{self.job_id}"


_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64,
                                                max_retries=requests.adapters.Retry(
                                                    total=1, connect=1, read=0, backoff_factor=1,
                                                    status_forcelist=[429, 502, 503, 504],
                                                    respect_retry_after_header=False,
                                                    allowed_methods=["GET", "POST"]))
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _session = s
    return _session


def _get(url, **kw):
    if STOP.is_set():
        raise TimeoutError("run time limit reached")
    r = session().get(url, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r.json()


def _post(url, payload, **kw):
    if STOP.is_set():
        raise TimeoutError("run time limit reached")
    r = session().post(url, json=payload, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r.json()


def _iso_to_ts(s):
    if not s:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ---------------------------------------------------------------- board keys

def board_key(b: dict) -> str:
    a = b["ats"]
    if a == "workday":
        return f"workday:{b['host']}/{b['tenant']}/{b['site']}".lower()
    if a == "oracle":
        return f"oracle:{b['host']}/{b['site']}".lower()
    return f"{a}:{b['slug']}".lower()


# ---------------------------------------------------------------- fetchers

def fetch_greenhouse(b):
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{b['slug']}/jobs")
    out = []
    for j in data.get("jobs", []):
        out.append(Job("greenhouse", board_key(b), b["name"], j.get("title", ""),
                       j.get("absolute_url", ""), str(j.get("id")),
                       (j.get("location") or {}).get("name", ""),
                       _iso_to_ts(j.get("first_published") or j.get("updated_at"))))
    return out


def fetch_lever(b):
    host = "api.eu.lever.co" if b.get("region") == "eu" else "api.lever.co"
    data = _get(f"https://{host}/v0/postings/{b['slug']}?mode=json")
    out = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        created = j.get("createdAt")
        out.append(Job("lever", board_key(b), b["name"], j.get("text", ""),
                       j.get("hostedUrl", ""), str(j.get("id")), loc or "",
                       created / 1000 if created else None))
    return out


def fetch_ashby(b):
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{b['slug']}")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location") or ""
        extra = [x.get("location", "") for x in (j.get("secondaryLocations") or []) if isinstance(x, dict)]
        if extra:
            loc = "; ".join([loc] + extra)
        job = Job("ashby", board_key(b), b["name"], j.get("title", ""),
                  j.get("jobUrl") or j.get("applyUrl", ""), str(j.get("id")), loc,
                  _iso_to_ts(j.get("publishedAt")))
        job.description = j.get("descriptionPlain") or ""
        out.append(job)
    return out


def fetch_smartrecruiters(b):
    out, seen = [], set()
    for term in SEARCH_TERMS:
        offset = 0
        while offset < 500:
            data = _get(f"https://api.smartrecruiters.com/v1/companies/{b['slug']}/postings",
                        params={"q": term, "limit": 100, "offset": offset})
            content = data.get("content", [])
            for j in content:
                jid = str(j.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                l = j.get("location") or {}
                loc = ", ".join(x for x in [l.get("city"), l.get("region"), l.get("country", "").upper()] if x)
                if l.get("remote"):
                    loc = (loc + " (Remote)").strip()
                out.append(Job("smartrecruiters", board_key(b), b["name"], j.get("name", ""),
                               f"https://jobs.smartrecruiters.com/{b['slug']}/{jid}", jid, loc,
                               _iso_to_ts(j.get("releasedDate"))))
            if len(content) < 100:
                break
            offset += 100
    return out


def _workday_base(b):
    """Return (api_url, public_prefix) for a Workday board."""
    host, tenant, site = b["host"], b["tenant"], b["site"]
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    if host.endswith("myworkdaysite.com"):
        public = f"https://{host}/recruiting/{tenant}/{site}"
    else:
        public = f"https://{host}/{site}"
    return api, public


def fetch_workday(b):
    api, public = _workday_base(b)
    out, seen = [], set()
    for term in SEARCH_TERMS:
        offset = 0
        while offset < 400:
            data = _post(api, {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term})
            posts = data.get("jobPostings") or []
            for j in posts:
                path = j.get("externalPath") or ""
                if not path or path in seen:
                    continue
                seen.add(path)
                out.append(Job("workday", board_key(b), b["name"], j.get("title", ""),
                               public + path, path, j.get("locationsText", "") or ""))
            if len(posts) < 20:
                break
            offset += 20
            time.sleep(0.2)
    return out


def fetch_oracle(b):
    host, site = b["host"], b["site"]
    out, seen = [], set()
    for term in SEARCH_TERMS:
        offset = 0
        while offset < 300:
            finder = (f'findReqs;siteNumber={site},facetsList=NONE,limit=25,offset={offset},'
                      f'keyword="{term}",sortBy=POSTING_DATES_DESC')
            data = _get(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                        params={"onlyData": "true", "expand": "requisitionList.secondaryLocations",
                                "finder": finder})
            items = data.get("items") or [{}]
            reqs = items[0].get("requisitionList") or []
            for j in reqs:
                jid = str(j.get("Id"))
                if jid in seen:
                    continue
                seen.add(jid)
                out.append(Job("oracle", board_key(b), b["name"], j.get("Title", ""),
                               f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}",
                               jid, j.get("PrimaryLocation", "") or "",
                               _iso_to_ts(j.get("PostedDate"))))
            if len(reqs) < 25:
                break
            offset += 25
    return out


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "workday": fetch_workday,
    "oracle": fetch_oracle,
}


# ---------------------------------------------------------------- Simplify feed

SIMPLIFY_FEEDS = {
    "internships": "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
}


def fetch_simplify(url=SIMPLIFY_FEEDS["internships"]):
    r = session().get(url, timeout=60)
    r.raise_for_status()
    out = []
    for j in r.json():
        if not j.get("active") or not j.get("is_visible", True):
            continue
        out.append(Job("simplify", "simplify", j.get("company_name", ""), j.get("title", ""),
                       j.get("url", ""), str(j.get("id")), "; ".join(j.get("locations") or []),
                       j.get("date_posted"), j.get("category", ""), j.get("terms") or [],
                       j.get("degrees") or []))
    return out


# ---------------------------------------------------------------- URL parsing

_WD_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def parse_board_url(url: str) -> dict | None:
    """Turn any job or careers URL into a board config, if it's a supported ATS.

    >>> parse_board_url("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/x")
    {'ats': 'workday', 'host': 'nvidia.wd5.myworkdayjobs.com', 'tenant': 'nvidia', 'site': 'NVIDIAExternalCareerSite'}
    """
    try:
        p = urlparse(url.strip())
    except Exception:
        return None
    host = (p.netloc or "").lower().split(":")[0]
    parts = [x for x in p.path.split("/") if x]
    q = parse_qs(p.query)

    if host.endswith(".myworkdayjobs.com"):
        tenant = host.split(".")[0]
        if parts and _WD_LOCALE.match(parts[0]):
            parts = parts[1:]
        if parts and parts[0] == "wday" and len(parts) >= 4:   # API url
            return {"ats": "workday", "host": host, "tenant": parts[2], "site": parts[3]}
        if parts and parts[0] not in ("job", "details"):
            return {"ats": "workday", "host": host, "tenant": tenant, "site": parts[0]}
        return None
    if host.endswith("myworkdaysite.com"):
        if len(parts) >= 3 and parts[0] == "recruiting":
            return {"ats": "workday", "host": host, "tenant": parts[1], "site": parts[2]}
        if parts and _WD_LOCALE.match(parts[0]) and len(parts) >= 4 and parts[1] == "recruiting":
            return {"ats": "workday", "host": host, "tenant": parts[2], "site": parts[3]}
        return None
    if "greenhouse.io" in host:
        if "for" in q:
            return {"ats": "greenhouse", "slug": q["for"][0].lower()}
        if host.startswith("boards-api.") and len(parts) >= 3:
            return {"ats": "greenhouse", "slug": parts[2].lower()}
        if parts and parts[0] not in ("embed", "v1"):
            return {"ats": "greenhouse", "slug": parts[0].lower()}
        return None
    if host in ("jobs.lever.co", "jobs.eu.lever.co"):
        if parts:
            b = {"ats": "lever", "slug": parts[0].lower()}
            if ".eu." in host:
                b["region"] = "eu"
            return b
        return None
    if host == "jobs.ashbyhq.com" and parts:
        return {"ats": "ashby", "slug": parts[0]}
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com") and parts:
        return {"ats": "smartrecruiters", "slug": parts[0]}
    if host.endswith("oraclecloud.com") and "CandidateExperience" in p.path:
        try:
            i = parts.index("sites")
            return {"ats": "oracle", "host": host, "site": parts[i + 1]}
        except (ValueError, IndexError):
            return None
    return None
