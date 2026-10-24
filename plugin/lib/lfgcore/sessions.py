"""Token usage and cost for every Claude Code session on this machine, read from the transcripts themselves.

Claude Code keeps each session's transcript under ~/.claude/projects, whatever folder it was started in, and every
reply in it carries its token counts. This adds them up per day and per model; the transcripts are only ever read.
"""
import calendar
import glob
import json
import os
import re
import time

from . import common as C

PROJECTS = os.path.join(C.HOME, ".claude", "projects")

# Dollars per million tokens: (input, output, cache read). Cache writes cost 1.25x input (5 minutes) or 2x (1 hour).
# Anthropic's first-party API list prices; on a Max or Team plan this is what the same work would cost at API rates.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25), "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 0.25), "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50), "claude-opus-4-7": (5.0, 25.0, 0.50), "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20), "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def cost(model, t):
    """Dollars for one model's token counts, or None for a model LFG has no price for."""
    p = PRICES.get(re.sub(r"-\d{8}$", "", model or ""))
    if not p:
        return None
    inp, out, read = p
    return (t["input"] * inp + t["output"] * out + t["cache_read"] * read + t["cache_write_5m"] * inp * 1.25
            + t["cache_write_1h"] * inp * 2) / 1e6


def _file_usage(path):
    """{day: {model: {field: tokens}}} for one transcript. A reply is logged once per content block with the same
    usage, so each message id counts once."""
    out, seen = {}, set()
    with open(path, "rb") as fh:
        for ln in fh:
            if b'"usage"' not in ln:
                continue
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            m = ev.get("message") if ev.get("type") == "assistant" else None
            u = (m or {}).get("usage")
            if not isinstance(u, dict) or m.get("model") in (None, "<synthetic>"):
                continue
            key = m.get("id") or ev.get("requestId") or ev.get("uuid")
            if key in seen:
                continue
            seen.add(key)
            cc = u.get("cache_creation") or {}
            w1h = cc.get("ephemeral_1h_input_tokens") or 0
            row = {"input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
                   "cache_read": u.get("cache_read_input_tokens") or 0, "cache_write_1h": w1h,
                   "cache_write_5m": max((u.get("cache_creation_input_tokens") or 0) - w1h, 0)}
            ts = ev.get("timestamp") or ""
            try:
                day = time.strftime("%Y-%m-%d", time.localtime(  # the timestamp is UTC; the day is the user's
                    calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))))
            except ValueError:
                continue
            d = out.setdefault(day, {}).setdefault(m["model"], dict.fromkeys(FIELDS, 0))
            for k in FIELDS:
                d[k] += row[k]
    return out


def _usage_index_path():
    return C.lfg_path("state", "usage-index.json")


def usage(days=30):
    """Tokens and dollars per day and per model for every Claude Code session (and its subagents), whether or not
    LFG is on there. Only transcripts that changed since last time are read again."""
    idx = C.read_json(_usage_index_path(), {}) or {}
    idx = idx if idx.get("v") == 1 else {"v": 1, "files": {}}
    old, new, changed = idx["files"], {}, False
    files = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")) + \
        glob.glob(os.path.join(PROJECTS, "*", "*", "subagents", "*.jsonl"))
    for p in files:
        try:
            st = os.stat(p)
        except OSError:
            continue
        hit = old.get(p)
        if hit and hit["size"] == st.st_size and hit["mtime"] == st.st_mtime:
            new[p] = hit
            continue
        try:
            new[p] = {"size": st.st_size, "mtime": st.st_mtime, "days": _file_usage(p)}
            changed = True
        except OSError:
            continue
    if changed or len(new) != len(old):
        C.ensure_dir(os.path.dirname(_usage_index_path()))
        C.write_json(_usage_index_path(), {"v": 1, "files": new})
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
    today = time.strftime("%Y-%m-%d")
    week = time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 86400))
    per_day, per_model, unpriced = {}, {}, set()
    spend = {"today": 0.0, "7d": 0.0, "30d": 0.0}
    for f in new.values():
        for day, models in f["days"].items():
            if day < since:
                continue
            for model, t in models.items():
                dd = per_day.setdefault(day, dict(dict.fromkeys(FIELDS + ("usd",), 0), models={}))
                dm = dd["models"].setdefault(model, dict.fromkeys(FIELDS + ("usd",), 0))
                mm = per_model.setdefault(model, dict.fromkeys(FIELDS + ("usd",), 0))
                usd = cost(model, t)
                if usd is None:
                    unpriced.add(model)
                    usd = 0.0
                for k in FIELDS:
                    dd[k] += t[k]
                    mm[k] += t[k]
                    dm[k] += t[k]
                dm["usd"] += usd
                dd["usd"] += usd
                mm["usd"] += usd
                spend["30d"] += usd
                spend["7d"] += usd if day >= week else 0
                spend["today"] += usd if day == today else 0
    for dd in per_day.values():
        dd["models"] = {m: dict(v, usd=round(v["usd"], 4)) for m, v in dd["models"].items()}
    as_rows = lambda d, k: [dict(v, **{k: n}) for n, v in sorted(d.items())]  # noqa: E731
    return {"days": [dict(r, cache_write=r["cache_write_5m"] + r["cache_write_1h"]) for r in as_rows(per_day, "day")],
            "models": sorted([dict(r, cache_write=r["cache_write_5m"] + r["cache_write_1h"])
                              for r in as_rows(per_model, "model")], key=lambda r: -r["usd"]),
            "spend": {k: round(v, 2) for k, v in spend.items()}, "unpriced": sorted(unpriced)}
