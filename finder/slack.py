"""Post jobs to Slack through incoming webhooks."""
from __future__ import annotations

import os
import time

import requests

from .filters import LABELS, is_tech
from .details import season_label, grad_label
from .tiers import tier
PER_MESSAGE = 8   # jobs per Slack message


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


def job_block(item):
    j, cat, locations = item["job"], item["category"], item["locations"]
    info = item.get("info") or {}
    loc = "; ".join(locations) if locations else "Location not listed"
    if len(loc) > 90:
        loc = loc[:87] + "…"
    star = " ⭐" if tier(j.company) == 1 else ""
    line2 = [f"🏢 *{_esc(j.company)}*{star}", f"📍 {_esc(loc)}"]
    line3 = [LABELS.get(cat, cat), season_label(info), grad_label(info)]
    ago = _ago(j.posted)
    if ago:
        line3.append(ago)
    text = f"*<{j.url}|{_esc(j.title)}>*\n" + "  ·  ".join(line2) + "\n" + "  ·  ".join(line3)
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_messages(items, header=None):
    msgs = []
    for i in range(0, len(items), PER_MESSAGE):
        chunk = items[i:i + PER_MESSAGE]
        blocks = []
        if header and i == 0:
            blocks += [{"type": "section", "text": {"type": "mrkdwn", "text": header}}, {"type": "divider"}]
        for it in chunk:
            blocks.append(job_block(it))
            blocks.append({"type": "divider"})
        fallback = "New internships: " + "; ".join(f"{it['job'].company} – {it['job'].title}" for it in chunk)
        msgs.append(({"text": fallback[:2900], "blocks": blocks[:-1],
                      "unfurl_links": False, "unfurl_media": False}, chunk))
    return msgs


def webhook_for(category: str) -> str | None:
    specific = os.environ.get("SLACK_WEBHOOK_TECH" if is_tech(category) else "SLACK_WEBHOOK_BUSINESS")
    return specific or os.environ.get("SLACK_WEBHOOK_URL")


def post(url, payload) -> bool:
    for attempt in range(4):
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
