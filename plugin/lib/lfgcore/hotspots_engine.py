"""Where the code keeps hurting: files and areas that change a lot and keep needing fixes, from git history only.

A senior engineer's first question about an unfamiliar codebase is "where does it break?". The answer is in the
history: a file that changed 30 times in six months and needed 8 fixes will need more. This ranks files by those
signals (changes, fix commits, how many people touch it, size, whether any test covers it) and says why each one is
on the list in plain words. No predictions dressed up as percentages: just the evidence. Read-only git, no network.
Author: Varun Singh.
"""
import collections
import datetime
import os
import re

from . import common as C
from .explain5_engine import FIX_RX, TEST_FILE, related_tests

SKIP = re.compile(r"(^|/)(node_modules|vendor|dist|build|\.venv|venv|__pycache__|\.git|docs?)/|"
                  r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|go\.sum|uv\.lock)$|"
                  r"\.(md|mdx|txt|rst|json|ya?ml|toml|lock|svg|png|jpe?g|gif|ico|css|map|min\.js|csv)$", re.I)


def _log(root, days):
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    cp = C.run(["git", "log", "--no-merges", "--since=%s" % since, "--name-only", "--no-renames",
                "--format=%x01%H%x02%an%x02%ad%x02%s", "--date=short"], cwd=root, timeout=60)
    commits = []
    for block in cp.stdout.split("\x01") if cp.returncode == 0 else []:
        head, _, rest = block.partition("\n")
        parts = head.split("\x02")
        if len(parts) != 4:
            continue
        files = [f for f in rest.splitlines() if f.strip()]
        commits.append({"sha": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3], "files": files})
    return commits


def _lines(root, path):
    try:
        with open(os.path.join(root, path), "rb") as fh:
            return fh.read(2_000_000).count(b"\n")
    except OSError:
        return 0


def _area(path):
    return os.path.dirname(path) or "."


def hotspots(root, days=180, limit=25):
    """{files: [...], areas: [...], commits, days}. Each file: path, changes, fixes, authors, lines, tests, last,
    level (high | watch), reasons [plain sentences], recent_fixes [{sha, date, subject}]."""
    commits = _log(root, days)
    half = (datetime.date.today() - datetime.timedelta(days=days // 2)).isoformat()  # recent half vs the one before
    tracked = set(C.run(["git", "ls-files"], cwd=root, timeout=20).stdout.splitlines())
    per = collections.defaultdict(lambda: {"changes": 0, "fixes": 0, "recent": 0, "authors": set(), "last": "",
                                           "fix_list": []})
    for c in commits:
        is_fix = bool(FIX_RX.search(c["subject"]))
        for f in c["files"]:
            if f not in tracked or SKIP.search(f) or TEST_FILE.search(f):
                continue
            p = per[f]
            p["changes"] += 1
            p["authors"].add(c["author"])
            p["last"] = max(p["last"], c["date"])
            if is_fix:
                p["fixes"] += 1
                p["recent"] += c["date"] >= half
                if len(p["fix_list"]) < 5:
                    p["fix_list"].append({"sha": c["sha"][:12], "date": c["date"], "subject": c["subject"][:140]})
    ranked = sorted(per.items(), key=lambda kv: (kv[1]["fixes"] * 3 + kv[1]["changes"], kv[1]["last"]), reverse=True)
    out = []
    for path, p in ranked[:limit]:
        if p["changes"] < 2:
            continue
        tests = related_tests(path, root)
        lines = _lines(root, path)
        reasons = []
        if p["fixes"]:
            reasons.append("needed %d fix%s in %d days" % (p["fixes"], "es" if p["fixes"] != 1 else "", days))
        reasons.append("changed %d time%s" % (p["changes"], "s" if p["changes"] != 1 else ""))
        earlier = p["fixes"] - p["recent"]
        trend = "rising" if p["recent"] >= 2 and p["recent"] > earlier else \
            "falling" if earlier >= 2 and p["recent"] < earlier else "steady"
        if trend == "rising":
            reasons.append("fixes rising: %d in the last %d days, %d before" % (p["recent"], days // 2, earlier))
        if len(p["authors"]) >= 4:
            reasons.append("%d people change it" % len(p["authors"]))
        if lines >= 800:
            reasons.append("%d lines long" % lines)
        if not tests:
            reasons.append("no test file covers it")
        high = (p["fixes"] >= 3 and p["changes"] >= 6) or (p["fixes"] >= 2 and not tests) or \
            (p["changes"] >= 12 and not tests)
        out.append({"path": path, "area": _area(path), "changes": p["changes"], "fixes": p["fixes"],
                    "authors": len(p["authors"]), "lines": lines, "tests": tests, "last": p["last"],
                    "level": "high" if high else "watch", "reasons": reasons, "recent_fixes": p["fix_list"],
                    "trend": trend, "fixes_recent": p["recent"], "fixes_earlier": earlier})
    areas = collections.defaultdict(lambda: {"changes": 0, "fixes": 0, "files": 0, "high": 0, "fixes_recent": 0})
    for path, p in per.items():
        a = areas[_area(path)]
        a["changes"] += p["changes"]
        a["fixes"] += p["fixes"]
        a["fixes_recent"] += p["recent"]
        a["files"] += 1
    for a in areas.values():
        a["fixes_earlier"] = a["fixes"] - a["fixes_recent"]
        a["trend"] = "rising" if a["fixes_recent"] >= 2 and a["fixes_recent"] > a["fixes_earlier"] else \
            "falling" if a["fixes_earlier"] >= 2 and a["fixes_recent"] < a["fixes_earlier"] else "steady"
    for f in out:
        areas[f["area"]]["high"] += f["level"] == "high"
    area_list = sorted(({"area": k, **v} for k, v in areas.items() if v["changes"] >= 3),
                       key=lambda a: (a["fixes"] * 3 + a["changes"]), reverse=True)[:8]
    return {"days": days, "half": days // 2, "commits": len(commits), "files": out, "areas": area_list,
            "rising": [a["area"] for a in area_list if a["trend"] == "rising"]}
