"""Claude Code plugins from LFG: see the ones you have, install more from your marketplaces, turn each on or off, and
remove them. Integrations → Plugins.

Everything goes through Claude Code's own `claude plugin` command, for every repo (`--scope user`): nothing here
copies or edits a plugin's files. Each change is in LFG's change list (Settings → Claude Code), so it can be undone
there and by `lfg uninstall`. LFG itself isn't listed; it has its own switches. A plugin turned on for one repo only
is shown, but changed in that repo's Claude Code.

Installing adds someone else's code to every Claude Code session, so only you do it: the dashboard with its edit key,
or `lfg plugins` in your own terminal. The guard blocks agents from both, and from `claude plugin` writes.
"""
import json
import re
import time

from . import claudecfg as CC
from . import common as C

ID_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}@[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
OWN = "lfg@lfg"
# Suggested on the page, with what each is for. Only plugins in Anthropic's official marketplace.
SUGGESTED = {
    "superpowers@claude-plugins-official":
        "Skills for planning, test-first work, debugging and code review. Its review skill can be one of your PR "
        "review methods.",
}
WRITES = {"install", "i", "uninstall", "remove", "enable", "disable", "update", "configure", "prune", "autoremove"}
_CACHE = {"ts": 0, "data": None}


def _claude():
    return C.which("claude") or "claude"


def _list(fresh=False):
    if not fresh and _CACHE["data"] and time.time() - _CACHE["ts"] < 120:
        return _CACHE["data"]
    cp = C.run([_claude(), "plugin", "list", "--json", "--available"], timeout=60)
    try:
        d = json.loads(cp.stdout or "")
    except ValueError:
        raise ValueError("Claude Code didn't list its plugins: %s" % ((cp.stderr or cp.stdout or "").strip()[-200:]
                                                                      or "is the claude command installed?")) from None
    data = {"installed": [x for x in d.get("installed") or [] if isinstance(x, dict) and x.get("id")],
            "available": [x for x in d.get("available") or [] if isinstance(x, dict) and x.get("pluginId")]}
    _CACHE.update(ts=time.time(), data=data)
    return data


def view(q="", fresh=False):
    """What's installed (yours to switch for every repo when scope is user), what's suggested, and the marketplace
    plugins matching q (at most 40, most installed first)."""
    d = _list(fresh)
    about = {a["pluginId"]: a for a in d["available"]}
    inst = []
    for x in d["installed"]:
        if x["id"] == OWN:
            continue
        a = about.get(x["id"]) or {}
        inst.append({"id": x["id"], "name": x["id"].split("@")[0], "marketplace": x["id"].split("@")[1],
                     "version": x.get("version") or "", "scope": x.get("scope") or "",
                     "enabled": bool(x.get("enabled")), "project": x.get("projectPath") or "",
                     "about": (a.get("description") or "")[:400], "yours": x.get("scope") == "user",
                     "suggested": SUGGESTED.get(x["id"], "")})
    have = {x["id"] for x in inst} | {OWN}
    sugg = [{"id": k, "name": k.split("@")[0], "why": v, "about": (about.get(k, {}).get("description") or "")[:400],
             "available": k in about} for k, v in SUGGESTED.items() if k not in have]
    words = [w for w in re.split(r"\s+", str(q or "").lower().strip()) if w][:6]
    found = []
    if words:
        for a in d["available"]:
            hay = ("%s %s %s" % (a["pluginId"], a.get("name") or "", a.get("description") or "")).lower()
            if a["pluginId"] not in have and all(w in hay for w in words):
                found.append({"id": a["pluginId"], "name": a.get("name") or a["pluginId"].split("@")[0],
                              "marketplace": a.get("marketplaceName") or "",
                              "about": (a.get("description") or "")[:400],
                              "installs": a.get("installCount") or 0})
        found.sort(key=lambda x: (-x["installs"], x["id"]))
    return {"installed": sorted(inst, key=lambda x: (not x["yours"], x["id"])), "suggested": sugg,
            "found": found[:40], "found_total": len(found), "searched": " ".join(words),
            "available_total": len(d["available"])}


def _check_id(pid):
    pid = str(pid or "").strip()
    if not ID_RX.match(pid):
        raise ValueError("a plugin is named name@marketplace")
    if pid == OWN:
        raise ValueError("LFG is turned on and off in Settings → Claude Code")
    return pid


def _do(verb, pid):
    cp = C.run([_claude(), "plugin", verb, pid, "--scope", "user"], timeout=300)
    _CACHE["data"] = None
    if cp.returncode:
        raise ValueError("Claude Code couldn't %s %s: %s" % (verb, pid, (cp.stderr or cp.stdout or "").strip()[-300:]))


def install(pid):
    pid = _check_id(pid)
    d = _list()
    if any(x["id"] == pid for x in d["installed"]):
        raise ValueError("%s is already installed" % pid)
    if not any(a["pluginId"] == pid for a in d["available"]):
        raise ValueError("%s isn't in any marketplace Claude Code knows" % pid)
    _do("install", pid)
    CC.cmd_done(["claude", "plugin", "install", pid, "--scope", "user"],
                [_claude(), "plugin", "uninstall", pid, "--scope", "user"],
                "Claude Code plugin %s, for every repo" % pid, "plugins", tag="plugin-extra", target=pid)
    return {"installed": pid}


def set_enabled(pid, on):
    pid = _check_id(pid)
    x = next((x for x in _list()["installed"] if x["id"] == pid), None)
    if not x:
        raise ValueError("%s isn't installed" % pid)
    if x.get("scope") != "user":
        raise ValueError("%s is installed for one repo only; switch it in that repo's Claude Code" % pid)
    if bool(x.get("enabled")) == bool(on):
        return {"id": pid, "enabled": bool(on)}
    _do("enable" if on else "disable", pid)
    return {"id": pid, "enabled": bool(on)}


def uninstall(pid):
    pid = _check_id(pid)
    x = next((x for x in _list()["installed"] if x["id"] == pid), None)
    if not x:
        raise ValueError("%s isn't installed" % pid)
    if x.get("scope") != "user":
        raise ValueError("%s is installed for one repo only; remove it in that repo's Claude Code" % pid)
    _do("uninstall", pid)
    for e in CC.find(kind="cmd", tag="plugin-extra", target=pid):
        CC._mark_undone(e["id"], "removed in Integrations → Plugins")
    return {"removed": pid}
