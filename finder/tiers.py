"""Company size tiers and tech labels, from data/company_tiers.yaml."""
from __future__ import annotations

import functools
import os
import re

import yaml

from .sources import Job, parse_board_url

PATH = os.path.join(os.path.dirname(__file__), "..", "data", "company_tiers.yaml")
STARTUP_ATS = {"greenhouse", "lever", "ashby"}
TECHY_NAME = re.compile(r"\b(ai|labs?|software|robotics|technologies|tech|systems|semiconductors?|"
                        r"data|cloud|digital|computing|analytics|networks?|cyber\w*|security|"
                        r"\.io|\.ai|\.com|apps?|games|interactive)\b", re.I)


def norm(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    s = re.sub(r"\b(the|inc|corp|corporation|company|co|llc|plc|ltd|group|holdings)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


@functools.lru_cache(maxsize=1)
def _lists():
    if not os.path.exists(PATH):
        return set(), set(), set(), set()
    with open(PATH) as f:
        d = yaml.safe_load(f) or {}
    get = lambda k: {norm(x) for x in (d.get(k) or []) if x}  # noqa: E731
    return get("tier1"), get("tier2"), get("tech"), get("not_tech")


def tier(company: str) -> int:
    t1, t2, _, _ = _lists()
    n = norm(company)
    return 1 if n in t1 else 2 if n in t2 else 3


def is_tech_company(job: Job) -> bool:
    _, _, tech, not_tech = _lists()
    n = norm(job.company)
    if n in tech:
        return True
    if n in not_tech:
        return False
    if TECHY_NAME.search(job.company):
        return True
    ats = (job.cfg or {}).get("ats") if job.cfg else None
    if not ats and job.source == "simplify":
        b = parse_board_url(job.url)
        ats = b["ats"] if b else None
    return (ats or job.source) in STARTUP_ATS
