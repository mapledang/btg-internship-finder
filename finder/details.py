"""Fetch a job's full description and pull out grad year, season and degree level.

Only done for jobs that are about to be posted (a handful per run), so it's cheap.
"""
from __future__ import annotations

import html
import re
import time
from urllib.parse import urlparse, parse_qs

from . import sources as _src
from .sources import Job, parse_board_url


def _get(url, **kw):
    return _src._get(url, **kw)     # looked up at call time (lets tests swap in fakes)

# ------------------------------------------------------------------ fetching


def _strip_html(s: str) -> str:
    s = html.unescape(html.unescape(s or ""))
    s = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t\xa0]+", " ", s).strip()


def _job_ref(job: Job):
    """Work out (board config, job id) for a job, including Simplify jobs (from their link)."""
    if job.source != "simplify":
        return (job.cfg or _board_from_key(job)), job.job_id
    b = parse_board_url(job.url)
    if not b:
        return None, None
    p = urlparse(job.url)
    parts = [x for x in p.path.split("/") if x]
    q = parse_qs(p.query)
    jid = None
    if b["ats"] == "greenhouse":
        jid = (q.get("gh_jid") or q.get("token") or [None])[0]
        if not jid and "jobs" in parts:
            i = parts.index("jobs")
            jid = parts[i + 1] if i + 1 < len(parts) else None
    elif b["ats"] in ("lever", "ashby"):
        jid = parts[1] if len(parts) > 1 else None
    elif b["ats"] == "smartrecruiters":
        jid = parts[1].split("-")[0] if len(parts) > 1 else None
    elif b["ats"] == "workday":
        jid = p.path[p.path.find("/job/"):] if "/job/" in p.path else None
    elif b["ats"] == "oracle":
        jid = parts[parts.index("job") + 1] if "job" in parts and parts.index("job") + 1 < len(parts) else None
    return b, jid


def _board_from_key(job: Job):
    # board keys look like "greenhouse:stripe" or "workday:host/tenant/site"
    ats, _, rest = job.board.partition(":")
    if ats == "workday":
        host, tenant, site = rest.split("/", 2)
        # board keys are lower-cased; Workday site names are case-insensitive in the API
        return {"ats": ats, "host": host, "tenant": tenant, "site": site, "name": job.company}
    if ats == "oracle":
        host, site = rest.split("/", 1)
        return {"ats": ats, "host": host, "site": site.upper(), "name": job.company}
    return {"ats": ats, "slug": rest, "name": job.company}


_ashby_cache = {}


def fetch_description(job: Job) -> str:
    if job.description:
        return job.description
    b, jid = _job_ref(job)
    if not b or not jid:
        return ""
    a = b["ats"]
    try:
        if a == "greenhouse":
            d = _get(f"https://boards-api.greenhouse.io/v1/boards/{b['slug']}/jobs/{jid}")
            return _strip_html(d.get("content", ""))
        if a == "lever":
            host = "api.eu.lever.co" if b.get("region") == "eu" else "api.lever.co"
            d = _get(f"https://{host}/v0/postings/{b['slug']}/{jid}")
            lists = " ".join(f"{x.get('text', '')}: {_strip_html(x.get('content', ''))}" for x in d.get("lists") or [])
            return " ".join([d.get("descriptionPlain", ""), lists, d.get("additionalPlain", "")])
        if a == "ashby":
            if b["slug"] not in _ashby_cache:
                _ashby_cache[b["slug"]] = {j.job_id: j.description for j in _src.FETCHERS["ashby"](b)}
            return _ashby_cache[b["slug"]].get(jid, "")
        if a == "smartrecruiters":
            d = _get(f"https://api.smartrecruiters.com/v1/companies/{b['slug']}/postings/{jid}")
            secs = (d.get("jobAd") or {}).get("sections") or {}
            return " ".join(_strip_html((v or {}).get("text", "")) for v in secs.values())
        if a == "workday":
            d = _get(f"https://{b['host']}/wday/cxs/{b['tenant']}/{b['site']}{jid}")
            info = d.get("jobPostingInfo") or {}
            return _strip_html(info.get("jobDescription", "")) + " " + (info.get("startDate") or "")
        if a == "oracle":
            d = _get(f"https://{b['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails",
                     params={"expand": "all", "onlyData": "true",
                             "finder": f'ById;Id="{jid}",siteNumber={b["site"]}'})
            it = (d.get("items") or [{}])[0]
            return _strip_html(" ".join(str(it.get(k) or "") for k in (
                "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")))
    except Exception:  # noqa: BLE001 - a missing description just means "not listed"
        return ""
    return ""


# ------------------------------------------------------------------ extracting

SEASONS = ["summer", "fall", "winter", "spring"]
_SEASON_RE = re.compile(r"\b(summer|fall|autumn|winter|spring)\b[\s,\-–]*(?:of\s+)?'?(20\d\d|\d\d)?\b", re.I)
_YEAR_SEASON_RE = re.compile(r"\b(20\d\d)\s+(summer|fall|autumn|winter|spring)\b", re.I)
_COOP_RE = re.compile(r"\bco[\s\-]?op\b", re.I)


def _norm_season(s):
    s = s.lower()
    return "fall" if s == "autumn" else s


def _year(y):
    if not y:
        return None
    y = int(y)
    return y + 2000 if y < 100 else y


def detect_season(job: Job, text: str):
    """Return (season or None, year or None, is_coop)."""
    is_coop = bool(_COOP_RE.search(job.title))
    for src in [job.title]:
        m = _YEAR_SEASON_RE.search(src)
        if m:
            return _norm_season(m.group(2)), int(m.group(1)), is_coop
        m = _SEASON_RE.search(src)
        if m:
            return _norm_season(m.group(1)), _year(m.group(2)), is_coop
    for t in job.terms:
        m = re.match(r"(summer|fall|winter|spring)\s+(20\d\d)", t, re.I)
        if m:
            return m.group(1).lower(), int(m.group(2)), is_coop
    if text:
        # most-mentioned season+year in the description, e.g. "this 10-week Summer 2027 internship"
        counts = {}
        for m in _SEASON_RE.finditer(text):
            if m.group(2) and len(m.group(2)) == 4:
                k = (_norm_season(m.group(1)), int(m.group(2)))
                counts[k] = counts.get(k, 0) + 1
        for m in _YEAR_SEASON_RE.finditer(text):
            k = (_norm_season(m.group(2)), int(m.group(1)))
            counts[k] = counts.get(k, 0) + 1
        if counts:
            (s, y), _ = max(counts.items(), key=lambda kv: kv[1])
            return s, y, is_coop or bool(_COOP_RE.search(text[:400]))
        m = re.search(r"\b(\d{1,2}[\s\-]week\s+)?summer\s+(internship|program|analyst)", text, re.I)
        if m:
            return "summer", None, is_coop
    return None, None, is_coop


_GRAD_KW = re.compile(r"graduat\w*|class of|grad(?:uation)? date|grad year|degree completion|complet\w+ (?:your|their|a|the)? ?(?:degree|studies)", re.I)
_YEARS = re.compile(r"\b(202[5-9]|203[0-2])\b")
_STANDING = re.compile(r"\b(rising\s+)?(sophomores?|juniors?|seniors?|freshm[ae]n|first[\s-]year|second[\s-]year|third[\s-]year)\b", re.I)


def grad_years(text: str, title: str = ""):
    """Graduation years a posting asks for, e.g. {2027, 2028}."""
    years = set()
    for src in (title, text or ""):
        for m in _GRAD_KW.finditer(src):
            # same sentence only: from the previous sentence break to the next one
            pre = src[max(0, m.start() - 80): m.start()]
            pre = re.split(r"[.!?;]\s|\n", pre)[-1]
            post = re.split(r"[.!?;](?:\s|$)|\n", src[m.start(): m.end() + 160])[0]
            window = pre + post
            # ignore internship dates like "our Summer 2027 internship" in the same sentence
            window = re.sub(r"\b(?:(?:summer|fall|autumn|winter|spring)\s+20\d\d|20\d\d\s+(?:summer|fall|autumn|winter|spring))"
                            r"(?=\s+(?:intern\w*|program\w*|co-?op|analyst|term|session|cohort|class))",
                            " ", window, flags=re.I)
            found = [int(y) for y in _YEARS.findall(window)]
            if not found:
                continue
            if re.search(r"or later|or after|and beyond|onwards|or beyond", window, re.I):
                found += list(range(min(found), 2031))
            years.update(found)
        if years:
            break
    # "2027 graduates" / "2028 grads"
    for m in re.finditer(r"\b(202[6-9]|2030)\s+(?:grads?|graduates?)\b", (text or "") + " " + title, re.I):
        years.add(int(m.group(1)))
    return sorted(years)


def class_standing(text: str):
    """E.g. 'rising juniors & seniors' when a posting names class years instead of grad years."""
    found = []
    for m in _STANDING.finditer(text or ""):
        ctx = text[max(0, m.start() - 80): m.end() + 40].lower()
        if not re.search(r"student|undergrad|candidate|open to|eligible|currently|pursuing|year|rising", ctx):
            continue
        word = m.group(2).lower().rstrip("s").replace("freshmen", "freshman").replace("freshman", "freshman")
        word = {"first-year": "freshman", "first year": "freshman", "second-year": "sophomore",
                "second year": "sophomore", "third-year": "junior", "third year": "junior"}.get(word, word)
        label = ("rising " if m.group(1) else "") + word
        if label not in found:
            found.append(label)
    return found[:3]


_GRAD_LEVEL = re.compile(r"\b(mba|m\.b\.a|master'?s|masters|ph\.?\s?d|doctoral|doctorate|j\.?d\.?|law school|"
                         r"graduate (?:student|program|degree|school)|post-?doc)\b", re.I)
_UNDERGRAD = re.compile(r"\b(bachelor'?s?|undergrad\w*|b\.?s\.?|b\.?a\.?|college|sophomore|junior|senior|"
                        r"rising|freshm[ae]n|associate'?s degree)\b", re.I)


def is_grad_level_only(job: Job, text: str) -> bool:
    """True if the role is for MBA / Master's / PhD / law students and not undergrads."""
    if job.degrees:
        return not any(d.lower().startswith(("bachelor", "associate")) for d in job.degrees)
    if not text:
        return False
    return bool(_GRAD_LEVEL.search(text)) and not _UNDERGRAD.search(text)


def enrich(job: Job) -> dict:
    t0 = time.time()
    text = fetch_description(job)
    season, year, coop = detect_season(job, text)
    return {"text_found": bool(text), "season": season, "season_year": year, "coop": coop,
            "grad_years": grad_years(text, job.title), "standing": class_standing(text),
            "grad_only": is_grad_level_only(job, text), "secs": time.time() - t0}


# ------------------------------------------------------------------ labels

SEASON_ICON = {"summer": "☀️", "fall": "🍂", "winter": "❄️", "spring": "🌱"}


def season_label(info: dict) -> str:
    s, y, coop = info.get("season"), info.get("season_year"), info.get("coop")
    if s:
        out = f"{SEASON_ICON[s]} {s.capitalize()}{' ' + str(y) if y else ''}"
        return out + (" co-op" if coop else "")
    return "🔁 Co-op (dates not listed)" if coop else "🗓 Season not listed"


def grad_label(info: dict) -> str:
    ys = info.get("grad_years") or []
    if ys:
        if len(ys) > 1 and ys == list(range(ys[0], ys[-1] + 1)):
            txt = f"{ys[0]}–{ys[-1]}"
        else:
            txt = ", ".join(map(str, ys))
        return f"🎓 Grad {txt}"
    if info.get("standing"):
        return "🎓 " + " & ".join(x + "s" for x in info["standing"]).capitalize()
    return "🎓 Grad year not listed"
