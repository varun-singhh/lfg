"""Notifications: one line per finished long job (an AI review, an answer, a fix run, a Linear ticket, a scan, the
checks) in ~/.lfg/notifications.jsonl, each with where to look (a dashboard link and its project). The dashboard
shows them as toasts and in its bell list. When no dashboard tab is in front of the user (another tab, another app,
or the dashboard closed), `lfg ui` also posts a macOS notification: terminal-notifier when it's installed, so a
click opens the page; else osascript's banner, which can't open anything. Nothing here leaves the computer.
Author: Varun Singh."""
import json
import os
import subprocess
import threading
import time
import urllib.parse

from . import common as C

KEEP = 200
_LOCK = threading.Lock()
# Held while a finished job is read in (settled), so the background watcher and a page load never settle, and so
# announce, the same job twice.
SETTLE = threading.RLock()


def _path():
    return C.lfg_path("notifications.jsonl")


def add(kind, title, body="", href="", repo="", ok=True):
    """Record one finished job. `href` is a dashboard hash (#review/34), `repo` the project it belongs to."""
    ev = {"id": "%d" % time.time_ns(), "ts": C.now_iso(), "kind": kind, "title": str(title)[:200],
          "body": str(body or "")[:400], "href": str(href or "")[:300], "repo": str(repo or "")[:120], "ok": bool(ok)}
    with _LOCK:
        C.ensure_dir(C.LFG_HOME)
        fd = os.open(_path(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(json.dumps(ev) + "\n")
        _trim()
    if DESK["port"] and not watched():
        desktop(ev)
    return ev


# ---------------------------------------------------------------- macOS notifications from `lfg ui`

DESK = {"port": 0, "seen": 0.0, "visible": False}   # set by `lfg ui`; seen/visible from the page's polls
FRESH = 12  # seconds: a page in front polls every 5; a hidden tab is throttled well past this


def page_seen(visible):
    """The dashboard page checked for news; `visible` is whether it's the tab in front, in the app in front."""
    DESK["seen"], DESK["visible"] = time.time(), bool(visible)


def watched():
    """Is a dashboard tab in front of the user right now? Then its toast is enough."""
    return DESK["visible"] and time.time() - DESK["seen"] < FRESH


def notifier():
    """'terminal-notifier' (clickable), 'osascript' (a banner only) or '' (not a Mac)."""
    if C.which("terminal-notifier"):
        return "terminal-notifier"
    return "osascript" if C.which("osascript") else ""


def desktop(ev):
    """Post one macOS notification for `ev`; with terminal-notifier a click opens its page in the dashboard."""
    tool = notifier()
    if not tool:
        return None
    url = "http://127.0.0.1:%d/%s%s" % (DESK["port"], "?repo=%s" % urllib.parse.quote(ev["repo"]) if ev.get("repo")
                                       else "", ev.get("href") or "")
    title, body = ("LFG" if ev.get("ok", True) else "LFG · needs a look"), ev.get("body") or ""
    if tool == "terminal-notifier":
        argv = [C.which(tool), "-title", title, "-subtitle", ev["title"], "-message", body or " ", "-open", url,
                "-group", "lfg-" + ev["id"]]
    else:  # text goes in as arguments, never into the script
        argv = [C.which(tool), "-e", "on run argv", "-e",
                "display notification (item 2 of argv) with title (item 3 of argv) subtitle (item 1 of argv)",
                "-e", "end run", ev["title"], body, title]
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError:
        return None
    return argv


def _trim():
    try:
        lines = C.read_text(_path()).splitlines()
    except OSError:
        return
    if len(lines) > KEEP * 2:
        C.write_text(_path(), "\n".join(lines[-KEEP:]) + "\n")


def recent(since="", limit=50):
    """The newest notifications, newest first; with `since` (an id), only the ones after it."""
    out = []
    for line in C.read_text(_path()).splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and (not since or str(ev.get("id", "")) > str(since)):
            out.append(ev)
    out = out[-limit:][::-1]
    return {"events": out, "latest": out[0]["id"] if out else since or "",
            "desktop": notifier() if DESK["port"] else ""}


def alive(pid):
    """Is this background job still running? Reaps our own finished child first (a zombie answers kill -0)."""
    try:
        if os.waitpid(int(pid), os.WNOHANG)[0]:
            return False
    except (ChildProcessError, OSError, TypeError, ValueError):
        pass
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True
