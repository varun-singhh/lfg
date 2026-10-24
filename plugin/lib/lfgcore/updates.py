"""Is a newer LFG out? Asks GitHub for the version number in plugin.json (and, when newer, the CHANGELOG), at most
once per `updates.check_interval_hours` while the dashboard is open, or on `lfg update`. Two plain GETs with a
User-Agent; nothing about the user or their code is sent. `updates.auto_check: false` stops the automatic check.
The result is cached in ~/.lfg/state/updates.json; a failed check keeps the last good answer. LFG never updates
itself: the user runs `git pull && ./install.sh` in their clone.
Author: Varun Singh.
"""
import datetime
import json
import re
import threading
import urllib.request

from . import common as C

REPO = "varun-singhh/lfg"
PLUGIN_JSON_URL = "https://raw.githubusercontent.com/%s/main/plugin/.claude-plugin/plugin.json" % REPO
CHANGELOG_URL = "https://raw.githubusercontent.com/%s/main/CHANGELOG.md" % REPO
NOTES_MAX = 4000
UPDATE_CMD = "git pull && ./install.sh"
_lock = threading.Lock()


def _path():
    return C.lfg_path("state", "updates.json")


def _fetch(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "lfg/%s" % C.VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URLs
        return r.read(1_000_000).decode("utf-8", "replace")


def version_tuple(v):
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", (v or "").strip())
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def newer(upstream, current):
    return bool(upstream) and version_tuple(upstream) > version_tuple(current)


def notes_since(changelog, current):
    """The CHANGELOG sections for versions newer than `current` (headings like `## 0.4.0 (date)`)."""
    out, keep = [], False
    for line in (changelog or "").splitlines():
        m = re.match(r"^##\s+\[?v?(\d+\.\d+(?:\.\d+)?)", line)
        if m:
            keep = newer(m.group(1), current)
        elif re.match(r"^##\s", line):
            keep = False  # "## Unreleased" and other non-version headings
        if keep:
            out.append(line)
    text = "\n".join(out).strip()
    return text if len(text) <= NOTES_MAX else text[:NOTES_MAX].rsplit("\n", 1)[0] + "\n…"


def _settings():
    u = C.config().get("updates") or {}
    return bool(u.get("auto_check", True)), float(u.get("check_interval_hours") or 24)


def status():
    """The cached answer, as the dashboard and `lfg update --json` show it."""
    st = C.read_json(_path(), {}) or {}
    auto, _ = _settings()
    cur = C.VERSION
    return {"current": cur, "upstream": st.get("upstream"), "update_available": newer(st.get("upstream"), cur),
            "notes": st.get("notes", "") if newer(st.get("upstream"), cur) else "", "checked_at": st.get("checked_at"),
            "error": st.get("error", ""), "auto_check": auto, "command": UPDATE_CMD}


def due(now=None):
    auto, hours = _settings()
    if not auto:
        return False
    last = (C.read_json(_path(), {}) or {}).get("tried_at")
    if not last:
        return True
    try:
        t = datetime.datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        now = now or datetime.datetime.now(t.tzinfo or datetime.timezone.utc)
        return (now - t).total_seconds() >= hours * 3600
    except (TypeError, ValueError):
        return True


def check(fetch=None):
    """Ask GitHub now. Never raises: on failure the last good answer stays and `error` says why."""
    fetch = fetch or _fetch
    with _lock:
        st = C.read_json(_path(), {}) or {}
        st["tried_at"] = C.now_iso()
        try:
            up = json.loads(fetch(PLUGIN_JSON_URL)).get("version")
            if not isinstance(up, str) or not re.match(r"^v?\d+\.\d+", up):
                raise ValueError("no version in plugin.json")
            st.update(upstream=up, checked_at=st["tried_at"], error="", notes="")
            if newer(up, C.VERSION):
                try:
                    st["notes"] = notes_since(fetch(CHANGELOG_URL), C.VERSION)
                except Exception:  # noqa: BLE001 - notes are optional
                    st["notes"] = ""
        except Exception as e:  # noqa: BLE001 - offline, rate-limited, bad JSON: keep the last good answer
            st["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        C.write_json(_path(), st)
    return status()


def status_and_maybe_check():
    """For the dashboard: answer from the cache at once; start a background check when one is due."""
    if due() and not _lock.locked():
        threading.Thread(target=check, daemon=True).start()
    return status()
