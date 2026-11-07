"""Post the daily internship digest to Slack through an incoming webhook."""
from __future__ import annotations

import os
import time

import requests


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ago(ts):
    if not ts:
        return ""
    d = time.time() - ts
    if d < 0:
        return ""
    if d < 3600:
        return "posted <1h ago"
    if d < 86400:
        return f"posted {int(d // 3600)}h ago"
    if d < 86400 * 60:
        return f"posted {int(d // 86400)}d ago"
    return ""


def entry_block(e: dict) -> dict:
    """One role, from a queued digest entry (see finder/digest.make_entry)."""
    loc = "; ".join(e.get("locations") or []) or "Location not listed"
    if len(loc) > 90:
        loc = loc[:87] + "…"
    star = " ⭐" if e.get("tier") == 1 else ""
    line2 = [f"🏢 *{_esc(e['company'])}*{star}", f"📍 {_esc(loc)}"]
    line3 = [e.get("season", ""), e.get("grad", "")]
    ago = _ago(e.get("posted"))
    if ago:
        line3.append(ago)
    text = (f"*<{e['url']}|{_esc(e['title'])}>*\n" + "  ·  ".join(line2) + "\n"
            + "  ·  ".join(x for x in line3 if x))
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:2990]}}


def digest_messages(picked: dict, section_names: list, title: str, intro_extra: str = "") -> list:
    """Return a list of (payload, entries) pairs: an intro message, then one message per section."""
    have = [s for s in section_names if picked.get(s)]
    empty = [s for s in section_names if not picked.get(s)]
    total = sum(len(picked[s]) for s in have)
    intro = f"📬 *Internship roundup · {title}*\n{total} new undergrad summer internships"
    if have:
        intro += " across " + ", ".join(s.split(" ", 1)[-1] for s in have)
    intro += "."
    if empty:
        intro += "\n_Nothing new today in: " + ", ".join(s.split(" ", 1)[-1] for s in empty) + "_"
    if intro_extra:
        intro += "\n" + intro_extra
    msgs = [({"text": f"Internship roundup · {title}", "unfurl_links": False,
              "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": intro}}]}, [])]
    for s in have:
        entries = picked[s]
        blocks = [{"type": "header", "text": {"type": "plain_text", "text": s[:150], "emoji": True}}]
        for e in entries:
            blocks += [entry_block(e), {"type": "divider"}]
        fallback = s + ": " + "; ".join(f"{e['company']} – {e['title']}" for e in entries)
        msgs.append(({"text": fallback[:2900], "blocks": blocks[:-1],
                      "unfurl_links": False, "unfurl_media": False}, entries))
    return msgs


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
