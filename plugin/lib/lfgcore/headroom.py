"""Headroom: an optional local proxy that compresses Claude Code's context. Off unless you turn it on.

Claude Code -> Headroom on 127.0.0.1:<port> (launchd agent dev.lfg.headroom) -> the upstream it used before (a company
gateway in ANTHROPIC_BASE_URL, else api.anthropic.com). `headroom.scope` decides where Claude Code is pointed at it:
  repos       only in repos where LFG is on (env.ANTHROPIC_BASE_URL in each repo's .claude/settings.local.json)
  everywhere  every session (env.ANTHROPIC_BASE_URL in ~/.claude/settings.json)
Routing is set only after the proxy answers, every change goes through claudecfg (backed up, in the change ledger),
and `lfg headroom off` undoes exactly those changes. Refused on Bedrock/Vertex, which don't use ANTHROPIC_BASE_URL."""
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request

from . import claudecfg as CC
from . import common as C

LABEL = "dev.lfg.headroom"
EXTRA_PATH = [os.path.join(C.HOME, ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin"]
DEFAULT_UPSTREAM = "https://api.anthropic.com"
MODES = ("token", "cache")
SCOPES = ("off", "repos", "everywhere")
ROUTE_TAG = "headroom-route"
# `token` (default) compresses earlier turns too; `cache` keeps them byte-identical for the provider's prompt cache,
# but then Claude Code's prefix is frozen and almost nothing gets compressed. Headroom's own rate limit
# (60 rpm / 100k tpm) and semantic response cache are off so it never throttles or replays answers.
PROXY_FLAGS = ["--no-rate-limit", "--no-cache", "--no-telemetry", "--no-subscription-tracking"]


def mode():
    m = cfg().get("mode") or "token"
    return m if m in MODES else "token"


def cfg():
    return C.config()["headroom"]


def port():
    return int(cfg()["port"])


def local_url():
    return "http://127.0.0.1:%d" % port()


def _settings_path():
    return os.path.join(C.HOME, ".claude", "settings.json")


def _state_path():
    return C.lfg_path("headroom", "state.json")


def _which(name):
    return shutil.which(name, path=os.environ.get("PATH", "") + os.pathsep + os.pathsep.join(EXTRA_PATH))


def _is_local(url):
    return bool(re.match(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?/?$", url or ""))


def valid_upstream(url):
    """https anywhere, or http on loopback only; no credentials, query or fragment in the URL."""
    u = urllib.parse.urlparse(url or "")
    if u.username or u.password or u.query or u.fragment or not u.hostname:
        return False
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"))


def scope():
    sc = cfg().get("scope") or "off"
    return sc if sc in SCOPES else "off"


def _local_settings(root):
    return os.path.join(root, ".claude", "settings.local.json")


def in_desktop_app():
    """True inside the Claude desktop app, whose environment carries its own API address and sign-in that terminal
    Claude Code sessions never get."""
    return os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "claude-desktop" or bool(
        os.environ.get("CLAUDE_CODE_DESKTOP_APP_VERSION"))


def base_url(root=None, use_env=True):
    """The ANTHROPIC_BASE_URL Claude Code uses in `root` (repo local settings first), else user settings, else the
    process environment (unless `use_env` is off). Only this one value is ever read out of the settings files."""
    for p in ([_local_settings(root)] if root else []) + [_settings_path()]:
        env = (C.read_json(p, {}) or {}).get("env") or {}
        if isinstance(env, dict) and env.get("ANTHROPIC_BASE_URL"):
            return str(env["ANTHROPIC_BASE_URL"])
    return str(os.environ.get("ANTHROPIC_BASE_URL") or "") if use_env else ""


def routed(root=None):
    return base_url(root).rstrip("/") == local_url()


def bypassed():
    """The API address this session really uses, when it isn't the proxy. Settings can say Headroom while whatever
    started Claude Code sets its own ANTHROPIC_BASE_URL (the Claude desktop app does, and ignores settings). None when
    the session goes through the proxy, or when the variable is unset and there's no way to tell."""
    actual = str(os.environ.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
    return actual if actual and actual != local_url() else None


def cloud_provider():
    """Bedrock / Vertex / Foundry sessions don't go through ANTHROPIC_BASE_URL, so Headroom can't sit in front."""
    env = dict(os.environ)
    env.update((C.read_json(_settings_path(), {}) or {}).get("env") or {})
    for var, name in (("CLAUDE_CODE_USE_BEDROCK", "Amazon Bedrock"), ("CLAUDE_CODE_USE_VERTEX", "Google Vertex"),
                      ("CLAUDE_CODE_USE_FOUNDRY", "Microsoft Foundry")):
        if str(env.get(var) or "").lower() in ("1", "true", "yes"):
            return name
    return None


def live(timeout=2):
    try:
        with urllib.request.urlopen(local_url() + "/livez", timeout=timeout) as r:
            return r.status == 200 and bool(json.loads(r.read()).get("alive"))
    except Exception:
        return False


def _plist():
    lfg = C.lfg_bin()
    log = C.lfg_path("headroom", "proxy.log")
    args = "".join("<string>%s</string>" % x for x in (sys.executable, lfg, "headroom", "serve"))
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key><array>%s</array>
  <key>EnvironmentVariables</key><dict><key>LFG_HOME</key><string>%s</string></dict>
  <key>WorkingDirectory</key><string>%s</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>%s</string>
  <key>StandardErrorPath</key><string>%s</string>
</dict></plist>
""" % (LABEL, args, C.LFG_HOME, C.lfg_path("headroom"), log, log)


def _plist_path():
    return os.path.join(C.HOME, "Library", "LaunchAgents", LABEL + ".plist")


def _target():
    return "gui/%d/%s" % (os.getuid(), LABEL)


def _agent_loaded():
    return C.run(["launchctl", "print", _target()]).returncode == 0


def install_agent():
    p = _plist_path()
    want = _plist()
    C.ensure_dir(os.path.dirname(p), 0o755)
    if C.read_text(p) != want:
        C.run(["launchctl", "bootout", _target()])
        C.write_text(p, want, mode=0o644)
        CC.file_created(p, "Headroom proxy login agent", "headroom", tag="headroom-agent",
                        undo=["launchctl", "bootout", _target()])
    if not _agent_loaded():
        cp = C.run(["launchctl", "bootstrap", "gui/%d" % os.getuid(), p])
        if cp.returncode:
            C.die("launchctl bootstrap failed for %s: %s" % (LABEL, cp.stderr.strip()))


def wait_live(timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if live():
            return True
        time.sleep(1)
    return False


def restart():
    return C.run(["launchctl", "kickstart", "-k", _target()]).returncode == 0


def _route_targets(sc):
    if sc == "everywhere":
        return [_settings_path()]
    if sc == "repos":
        return [_local_settings(r) for r in sorted(C.enabled_state()["repos"]) if os.path.isdir(r)]
    return []


def route_repo(root):
    """Point one repo at the proxy (scope `repos`, called by `lfg enable`). No-op unless the proxy is up."""
    if scope() != "repos" or not live():
        return None
    return CC.json_set(_local_settings(root), ["env", "ANTHROPIC_BASE_URL"], local_url(),
                       "Route this repo's Claude Code traffic through Headroom", "headroom", tag=ROUTE_TAG,
                       repo=root)


def setup(upstream=None, new_scope=None):
    """Start the proxy, then point Claude Code at it where `scope` says. Never routes to a proxy that isn't up."""
    if not _which("headroom"):
        C.die("headroom not installed (lfg add headroom)", 2)
    cloud = cloud_provider()
    if cloud:
        C.die("Claude Code uses %s here, which doesn't go through ANTHROPIC_BASE_URL; Headroom can't help." % cloud, 2)
    sc = new_scope or (scope() if scope() != "off" else "repos")
    if sc not in SCOPES[1:]:
        C.die("scope must be repos or everywhere", 2)
    C.ensure_dir(C.lfg_path("headroom"))
    state = C.read_json(_state_path(), {}) or {}
    # what terminal Claude Code used before: the desktop app's own address is not it (its gateway takes the app's
    # sign-in, not the claude.ai login a terminal session sends), so it's never adopted as the upstream
    current = base_url(use_env=not in_desktop_app())
    if not routed():  # forward to what Claude Code used before (a company gateway), else Anthropic
        state["previous"] = current or None
        state["upstream"] = current if current and not _is_local(current) else DEFAULT_UPSTREAM
    if upstream:
        state["upstream"] = upstream
    up = state.get("upstream") or DEFAULT_UPSTREAM
    if not valid_upstream(up):
        C.die("refusing upstream %r: use https://host (or http://127.0.0.1)" % up, 2)
    state["upstream"] = up
    C.write_json(_state_path(), state)
    _save_scope(sc)
    install_agent()
    if upstream or state.get("mode") != mode():  # new upstream or mode (serve records the mode it runs): restart
        restart()
    if not wait_live():
        return {"live": False, "routed": routed(), "upstream": up, "scope": sc,
                "hint": "proxy did not start; see %s. Claude Code was left unchanged." % C.lfg_path("headroom",
                                                                                                  "proxy.log")}
    try:
        _unroute(keep=sc)
        for p in _route_targets(sc):
            CC.json_set(p, ["env", "ANTHROPIC_BASE_URL"], local_url(), "Route Claude Code through Headroom (%s)" % sc,
                        "headroom", tag=ROUTE_TAG)
    except ValueError as e:  # a settings file that isn't valid JSON: left exactly as it was
        C.die(str(e))
    return {"live": True, "routed_where": sc, "upstream": up, "proxy": local_url(), "scope": sc}


def _save_scope(sc):
    p = C.lfg_path("config.json")
    raw = C.read_json(p, {}) or {}
    raw.setdefault("headroom", {})["scope"] = sc
    C.write_json(p, raw)


def _unroute(keep=None):
    """Undo routing LFG recorded; with keep, only the routes that don't belong to that scope."""
    targets = set(_route_targets(keep)) if keep else set()
    out = []
    for e in CC.find(tag=ROUTE_TAG):
        if e["target"] not in targets:
            out.append(CC.undo(e["id"]))
    return out


def off():
    """Stop routing through Headroom (undo exactly what LFG changed) and unload the proxy."""
    undone = _unroute()
    if routed() and not CC.find(tag=ROUTE_TAG):  # routed by an older LFG that kept no change ledger
        state = C.read_json(_state_path(), {}) or {}
        prev = state.get("previous")
        CC.json_set_raw(_settings_path(), ["env", "ANTHROPIC_BASE_URL"],
                        prev if prev and not _is_local(prev) else CC.MISSING)
    C.run(["launchctl", "bootout", _target()])
    for e in CC.find(tag="headroom-agent"):
        CC.undo(e["id"])
    if os.path.exists(_plist_path()):
        os.remove(_plist_path())
    if scope() != "off":
        _save_scope("off")
    return {"routed": routed(), "undone": len(undone), "scope": "off"}


def status():
    state = C.read_json(_state_path(), {}) or {}
    return {"installed": bool(_which("headroom")), "agent": _agent_loaded(), "live": live(), "routed": routed(),
            "scope": scope(), "routes": len(CC.find(tag=ROUTE_TAG)), "proxy": local_url(),
            "upstream": state.get("upstream") or "", "mode": mode(), "running_mode": state.get("mode") or "",
            "cloud_provider": cloud_provider()}


def revive(timeout=8):
    """Bring the proxy back: reload the login agent if something unloaded it, else restart it. True once it answers."""
    if not _agent_loaded() and os.path.exists(_plist_path()):
        C.run(["launchctl", "bootstrap", "gui/%d" % os.getuid(), _plist_path()])
    else:
        restart()
    return wait_live(timeout=timeout)


def ensure_live(root=None):
    """Session start and every prompt: if Claude Code is routed through the proxy but it's down, restart it."""
    if not routed(root) or live(timeout=1):
        return True
    return revive()


def down_message():
    """What the user reads when the proxy is down and restarting it didn't help."""
    return ("Headroom proxy is down, so this session can't reach Claude: it sends every request to %s and nothing "
            "answers there (Claude Code retries for about 3 minutes, then fails with \"Connection refused\"). LFG "
            "tried to restart it and it didn't come back. In a terminal, run `lfg headroom restart`; if that fails, "
            "see %s, or run `lfg headroom off` and start `claude` again to go straight to Anthropic."
            % (local_url(), C.lfg_path("headroom", "proxy.log")))


def serve():
    """launchd entry point: the proxy on loopback, forwarding to the saved upstream."""
    exe = _which("headroom")
    if not exe:
        C.die("headroom not found", 2)
    up = (C.read_json(_state_path(), {}) or {}).get("upstream") or DEFAULT_UPSTREAM
    if not valid_upstream(up):
        C.die("invalid upstream in %s" % _state_path(), 2)
    env = dict(os.environ, HEADROOM_TELEMETRY="off")
    state = C.read_json(_state_path(), {}) or {}
    if state.get("mode") != mode():
        state["mode"] = mode()
        C.write_json(_state_path(), state)
    argv = [exe, "proxy", "--host", "127.0.0.1", "--port", str(port()), "--anthropic-api-url", up,
            "--mode", mode()] + PROXY_FLAGS
    os.execvpe(argv[0], argv, env)
