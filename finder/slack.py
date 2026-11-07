"""Post the daily internship digest to Slack as a single message."""
from __future__ import annotations

import os
import re
import time
from datetime import datetime

import requests

# strips emoji / pictographs left over in older queued entries or section names
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]+")


def plain(s: str) -> str:
    return re.sub(r"\s{2,}", " ", _EMOJI.sub("", s or "")).strip()


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _posted(ts) -> str:
    if not ts:
        return ""
    try:
        from zoneinfo import ZoneInfo
        d = datetime.fromtimestamp(ts, ZoneInfo("America/Los_Angeles"))
    except (OverflowError, OSError, ValueError, ImportError):
        return ""
    return f"Posted {d.strftime('%b')} {d.day}"


def role_text(e: dict) -> str:
    """Two lines per role:  *Title* — Company  /  Location | Summer 2027 | Class of 2028 | Posted Nov 5"""
    locs = e.get("locations") or []
    loc = locs[0] if locs else "Location not listed"
    if len(locs) > 1:
        loc += f" (+{len(locs) - 1} more)"
    if len(loc) > 60:
        loc = loc[:57] + "..."
    details = [loc, plain(e.get("season", "")), plain(e.get("grad", "")), _posted(e.get("posted"))]
    return (f"*<{e['url']}|{_esc(plain(e['title']))}>*  —  {_esc(plain(e['company']))}\n"
            + "  |  ".join(_esc(x) for x in details if x))


def digest_message(picked: dict, section_names: list, title: str, note: str = "") -> dict:
    """The whole digest as one Slack message (header, summary, one block per section, footer)."""
    names = [plain(s) for s in section_names]
    by = {plain(k): v for k, v in picked.items()}
    have = [s for s in names if by.get(s)]
    empty = [s for s in names if not by.get(s)]
    total = sum(len(by[s]) for s in have)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Internship Roundup  |  {title}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
            f"{total} new undergraduate summer internship{'s' if total != 1 else ''} in the US, "
            "listed by company size and posting date."}]},
    ]
    if note:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": note}]})
    for s in have:
        body = f"*{_esc(s)}*\n\n" + "\n\n".join(role_text(e) for e in by[s])
        blocks += [{"type": "divider"}, {"type": "section", "text": {"type": "mrkdwn", "text": body[:2990]}}]
    blocks.append({"type": "divider"})
    footer = "Sourced from company career sites and the Simplify internship list."
    if empty:
        footer = "No new roles today in " + ", ".join(empty) + ".  " + footer
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})

    fallback = f"Internship Roundup | {title}: " + "; ".join(
        f"{plain(e['company'])} - {plain(e['title'])}" for s in have for e in by[s])
    return {"text": fallback[:2900], "blocks": blocks, "unfurl_links": False, "unfurl_media": False}


def webhook() -> str | None:
    return (os.environ.get("SLACK_WEBHOOK_URL") or os.environ.get("SLACK_WEBHOOK_BUSINESS")
            or os.environ.get("SLACK_WEBHOOK_TECH"))


def post(url, payload) -> bool:
    for _ in range(4):
        try:
            r = requests.post(url, json=payload, timeout=20)
        except requests.RequestException as e:
            print(f"  slack error: {e}")
            time.sleep(3)
            continue
        if r.status_code == 200:
            return True
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "5")) + 1)
            continue
        print(f"  slack HTTP {r.status_code}: {r.text[:200]}")
        return False
    return False
