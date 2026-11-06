"""Remembers which jobs have already been posted (data/seen.json, committed back to the repo)."""
from __future__ import annotations

import json
import os
import re
import time

PATH = os.path.join(os.path.dirname(__file__), "..", "data", "seen.json")
KEEP_JOBS_DAYS = 300        # forget a job id after this long
KEEP_FINGERPRINT_DAYS = 30  # same company+title within this window = duplicate


def fingerprint(company: str, title: str) -> str:
    c = re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)|\b(the|inc|corp|llc)\b", "", company.lower()))
    t = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return f"{c}|{t}"


class State:
    def __init__(self, path=PATH):
        self.path = path
        data = {}
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
        self.jobs = data.get("jobs", {})
        self.fingerprints = data.get("fingerprints", {})
        self.boards = data.get("boards_initialized", {})
        self.failures = data.get("board_failures", {})
        self.now = int(time.time())

    def seen(self, uid):
        return uid in self.jobs

    def fp_recent(self, fp):
        ts = self.fingerprints.get(fp)
        return ts is not None and self.now - ts < KEEP_FINGERPRINT_DAYS * 86400

    def mark(self, uid, fp=None):
        self.jobs.setdefault(uid, self.now)
        if fp:
            self.fingerprints[fp] = self.now

    def board_ready(self, key):
        return key in self.boards

    def board_ok(self, key):
        self.boards.setdefault(key, self.now)
        self.failures.pop(key, None)

    def board_failed(self, key):
        self.failures[key] = self.failures.get(key, 0) + 1

    def save(self):
        cut_j = self.now - KEEP_JOBS_DAYS * 86400
        cut_f = self.now - KEEP_FINGERPRINT_DAYS * 86400
        data = {
            "version": 1,
            "jobs": {k: v for k, v in self.jobs.items() if v >= cut_j},
            "fingerprints": {k: v for k, v in self.fingerprints.items() if v >= cut_f},
            "boards_initialized": self.boards,
            "board_failures": self.failures,
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=0, sort_keys=True)
        os.replace(tmp, self.path)
