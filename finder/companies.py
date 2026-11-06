"""Load the list of job boards to scan."""
from __future__ import annotations

import json
import os
import re

from .sources import board_key, parse_board_url

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def norm_name(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", s.lower())
    s = re.sub(r"\b(the|inc|corp|corporation|company|co|llc|plc|ltd|group|holdings)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def _load_json(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def load_manual():
    """data/companies_manual.txt: lines of 'Company Name | <any job link>'."""
    path = os.path.join(DATA, "companies_manual.txt")
    out, bad = [], []
    if not os.path.exists(path):
        return out, bad
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, url = (x.strip() for x in line.partition("|"))
            b = parse_board_url(url) if url else None
            if b:
                b.update({"name": name, "origin": "manual"})
                out.append(b)
            else:
                bad.append(line)
    return out, bad


def load_companies(include_discovered=True):
    boards = []
    manual, _ = load_manual()
    boards += manual
    if include_discovered:
        boards += _load_json("companies_discovered.json")
    boards += _load_json("companies.json")
    exclude = set()
    ex_path = os.path.join(DATA, "companies_exclude.txt")
    if os.path.exists(ex_path):
        with open(ex_path) as f:
            exclude = {norm_name(l) for l in f if l.strip() and not l.startswith("#")}
    seen, out = set(), []
    for b in boards:
        k = board_key(b)
        if k in seen or norm_name(b["name"]) in exclude:
            continue
        seen.add(k)
        out.append(b)
    return out
