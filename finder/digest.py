"""Daily digest: new roles are queued by section; once a day the top N per section are posted."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from .filters import is_underclass
from .details import season_label, grad_label
from .tiers import tier, is_tech_company
from .filters import LABELS

DEFAULT_SECTIONS = [
    {"name": "Business, Strategy & Consulting", "categories": ["consulting", "business"],
     "limit": 15, "prefer_tech": True},
    {"name": "Other Notable Roles", "categories": ["product", "finance", "data", "marketing"],
     "underclass": True, "limit": 5, "show_category": True},
]


def sections(cfg):
    return (cfg.get("digest") or {}).get("sections") or DEFAULT_SECTIONS


def section_for(item, secs) -> str | None:
    """Which section a role belongs in (underclass programs win over their function)."""
    job, cat, info = item["job"], item["category"], item.get("info") or {}
    if is_underclass(job, info):
        for s in secs:
            if s.get("underclass"):
                return s["name"]
    for s in secs:
        if cat in (s.get("categories") or []):
            return s["name"]
    return None


def make_entry(item, section) -> dict:
    j, info = item["job"], item.get("info") or {}
    return {
        "section": section, "category": item["category"], "title": j.title, "company": j.company,
        "url": j.url, "locations": item["locations"], "season": season_label(info),
        "grad": grad_label(info), "posted": j.posted, "tier": tier(j.company),
        "tech": is_tech_company(j),
        "label": "Freshman & Sophomore Program" if is_underclass(j, info) else LABELS.get(item["category"], ""),
        "queued": int(time.time()), "uids": item["uids"], "fp": item["fp"],
    }


def _now_local(cfg):
    tz = (cfg.get("digest") or {}).get("timezone", "America/Los_Angeles")
    return datetime.now(ZoneInfo(tz)) if ZoneInfo else datetime.utcnow() - timedelta(hours=8)


def due(state, cfg) -> bool:
    now = _now_local(cfg)
    hh, mm = map(int, str((cfg.get("digest") or {}).get("time", "09:00")).split(":"))
    return state.last_digest != now.date().isoformat() and (now.hour, now.minute) >= (hh, mm)


def today(cfg) -> str:
    return _now_local(cfg).date().isoformat()


def big_enough(company: str, cfg) -> bool:
    """Tier 1-2 companies always; smaller ones only if fill_with_smaller_companies is on."""
    d = cfg.get("digest") or {}
    return tier(company) <= int(d.get("max_company_tier", 2)) or bool(d.get("fill_with_smaller_companies", False))


def pick(queue, cfg, per_section=None):
    """Return ({section: [entries]}, entries left in the queue).

    Each section takes up to its `limit` roles: tech companies first where the section has
    prefer_tech, then biggest companies, then newest.
    """
    from .slack import plain
    d = cfg.get("digest") or {}
    default_n = per_section or int(d.get("per_section", 5))
    secs = {plain(s["name"]): s for s in sections(cfg)}
    keep_after = time.time() - float(d.get("keep_days", 7)) * 86400
    fresh = [e for e in queue if e.get("queued", 0) >= keep_after]
    for e in fresh:
        e["tier"] = tier(e["company"])          # tiers file may have been edited since queuing
        e["section"] = plain(e["section"])
    picked, rest = {}, []
    for e in fresh:
        if e["section"] not in secs:            # sections were renamed: re-file by role type
            under = "Freshman" in (e.get("label") or "") or "Freshman" in e["section"]
            e["section"] = next((n for n, sc in secs.items()
                                 if (under and sc.get("underclass")) or
                                 (not under and e.get("category") in (sc.get("categories") or []))), None)
            if not e["section"]:
                continue
        picked.setdefault(e["section"], []).append(e)
    out = {}
    for name, lst in picked.items():
        sec = secs[name]
        n = per_section or int(sec.get("limit", default_n))
        lst.sort(key=lambda e: ((not e.get("tech", True)) if sec.get("prefer_tech") else 0, e["tier"],
                                -(e.get("posted") or e.get("queued") or 0)))
        out[name], extra = lst[:n], lst[n:]
        rest += extra
    return {k: v for k, v in out.items() if v}, rest


def date_title(cfg) -> str:
    now = _now_local(cfg)
    return now.strftime("%A, %B ") + str(now.day)
