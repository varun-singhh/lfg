"""When Headroom compressed what Claude Code sent.

Headroom writes one line per request to ~/.headroom/savings_events.jsonl (time, model, tokens before and after,
dollars saved). This adds them up per day, and per hour for today. Nothing here changes Headroom.
"""
import calendar
import json
import os
import time

from . import common as C

HR_HOME = os.path.join(C.HOME, ".headroom")


def _local_day_hour(ts):
    """ISO UTC timestamp -> local (day, hour)."""
    try:
        t = calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))  # UTC; localtime() handles daylight saving
    except ValueError:
        return None, None
    lt = time.localtime(t)
    return time.strftime("%Y-%m-%d", lt), lt.tm_hour


def when(days=30):
    """Saved tokens and dollars per day, and per hour for today, from Headroom's own event log."""
    path = os.path.join(HR_HOME, "savings_events.jsonl")
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
    today = time.strftime("%Y-%m-%d")
    per_day, per_hour, models = {}, {h: {"calls": 0, "saved": 0} for h in range(24)}, {}
    try:
        fh = open(path, "rb")
    except OSError:
        return {"available": False, "why": "Headroom has no savings log yet (%s)" % path}
    with fh:
        for ln in fh:
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            day, hour = _local_day_hour(e.get("ts") or "")
            if not day or day < since:
                continue
            d = per_day.setdefault(day, {"day": day, "calls": 0, "before": 0, "saved": 0, "usd": 0.0})
            d["calls"] += 1
            d["before"] += e.get("before") or 0
            d["saved"] += e.get("saved") or 0
            d["usd"] += e.get("cost_usd") or 0
            m = models.setdefault(e.get("model") or "?", {"model": e.get("model") or "?", "calls": 0, "saved": 0,
                                                          "usd": 0.0})
            m["calls"] += 1
            m["saved"] += e.get("saved") or 0
            m["usd"] += e.get("cost_usd") or 0
            if day == today:
                per_hour[hour]["calls"] += 1
                per_hour[hour]["saved"] += e.get("saved") or 0
    rows = [per_day[k] for k in sorted(per_day)]
    for r in rows:
        r["usd"] = round(r["usd"], 2)
        r["percent"] = round(100.0 * r["saved"] / r["before"], 1) if r["before"] else 0
    return {"available": True, "days": rows, "today_by_hour": [dict(v, hour=h) for h, v in per_hour.items()],
            "models": sorted(({**m, "usd": round(m["usd"], 2)} for m in models.values()), key=lambda m: -m["saved"])}


def summary(days=30):
    from . import headroom as HR
    return {"live": HR.live(timeout=1), "routed": HR.routed(), "scope": HR.scope(), "port": HR.port(),
            "when": when(days)}
