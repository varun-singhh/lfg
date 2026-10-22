"""Install, turn on per repo, add packs, uninstall: without touching anything that isn't LFG's.

`lfg setup` looks first (read-only), shows the exact plan, and applies it only after you say yes. Everything it changes
outside ~/.lfg goes through claudecfg (backed up, in the change ledger), so `lfg uninstall` can put it all back.

LFG is off everywhere until you turn it on: the plugin is installed with `defaultEnabled: false`, and `lfg enable`
switches it on for one repo (Claude Code's own per-repo plugin setting in .claude/settings.local.json). The hooks also
check ~/.lfg/enabled.json and do nothing in other repos.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys

from . import claudecfg as CC
from . import common as C

EXTRA_PATH = [os.path.join(C.HOME, ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin"]
PLUGIN_ID = "lfg@lfg"
EXCLUDE_ENTRIES = ["graphify-out/", ".code-review-graph/", ".lfg/", "strix_runs/", ".headroom/", ".scratch/",
                   ".out-of-scope/"]

# Deny rules for "hardened mode" (a second layer behind the guard hook, written to each LFG repo's
# .claude/settings.local.json, never to your user settings). Older LFG versions wrote exactly these to
# ~/.claude/settings.json; `lfg setup` offers to take them back out.
HARDENED_DENY = [
    "Read(**/.env)", "Read(**/.env.local)", "Read(**/.env.development)", "Read(**/.env.production)",
    "Read(**/.env.staging)", "Read(**/.env.test)", "Read(**/.envrc)", "Read(**/*.pem)", "Read(**/*.key)",
    "Read(**/id_rsa)", "Read(**/id_ed25519)", "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(~/.config/gh/**)",
    "Read(~/.docker/config.json)", "Read(~/.kube/**)", "Read(~/.gnupg/**)",
    "Bash(git push:*)", "Bash(git commit:*)", "Bash(git merge:*)", "Bash(git rebase:*)",
    "Bash(git reset --hard:*)", "Bash(gh pr create:*)", "Bash(gh pr merge:*)", "Bash(gh release:*)",
    "Bash(gh secret set:*)", "Bash(docker push:*)", "Bash(docker login:*)", "Bash(printenv:*)",
    "Bash(env)", "Bash(npm publish:*)", "Bash(sudo:*)"]

def hardened_rules():
    """The deny rules hardened mode writes: all of them, minus `git commit` while Commit approval is on (a deny rule
    would override the approval prompt)."""
    allow = C.config()["guard"].get("allow_commits", True)
    return [r for r in HARDENED_DENY if not (allow and r == "Bash(git commit:*)")]


# Optional packs. Core is what every LFG repo needs; the rest are only installed when you ask for them.
PACKS = {
    "core": {"title": "Core", "about": "Plugin, guard, code graphs, runs and the dashboard.",
             "brew": ["uv", "gh"], "uv": ["code-review-graph", "graphifyy"]},
    "security": {"title": "Security", "about": "Scanners for /lfg:secure and the green gate.",
                 "brew": ["gitleaks", "semgrep", "osv-scanner", "trivy", "hadolint", "actionlint", "zizmor"],
                 "uv": ["picklescan"]},
    "shipcheck": {"title": "Ship check", "about": "Builds, runs and smoke-tests your container (needs Docker).",
                  "cask": ["docker"], "needs_cmd": ["docker"]},
    "pentest": {"title": "Pentest (experimental)",
                "about": "Offline Strix attack with a local Ollama model (needs Ship check). Installs about 10 GB "
                         "(Ollama + a model, LuLu firewall) and asks before running Strix's curl | bash installer.",
                "brew": ["ollama"], "cask": ["lulu"], "script": "strix", "requires": ["shipcheck"]},
    "knowledge": {"title": "Knowledge graphs", "about": "dev-graph and second-brain (local Omnigraph servers).",
                  "tap": "ModernRelay/tap", "brew": ["ModernRelay/tap/omnigraph", "node"]},
    "linear": {"title": "Linear", "about": "Read Linear issues (/lfg:inbox); you sign in with /mcp.", "mcp": "linear"},
    "headroom": {"title": "Headroom (experimental)",
                 "about": "Third-party local proxy that rewrites Claude Code's context to compress it; only LFG "
                          "repos unless you choose everywhere.",
                 "uv": ["headroom-ai"]},
    "sonarqube": {"title": "SonarQube (local)",
                  "about": "Runs SonarQube on 127.0.0.1:9000 so you can find and fix what SonarCloud would fail before "
                           "you push (`lfg sonar scan`). Needs Docker; downloads about 1.5 GB of images. Sets the "
                           "admin login to a generated password (`lfg sonar login`).",
                  "cask": ["docker"], "needs_cmd": ["docker"], "custom": "sonarqube"},
    "dictate": {"title": "Dictate",
                "about": "Hold Option+Space anywhere on your Mac to dictate; on-device speech-to-text (Whistle), "
                         "audio never leaves the Mac. Clean up with Claude (text only) is on by default. "
                         "Downloads about 90 MB when turned on.", "custom": "dictate"},
}
UV_BIN = {"graphifyy": "graphify", "headroom-ai": "headroom"}
CASK_CHECK = {"docker": ("/Applications/Docker.app", "docker"), "lulu": ("/Applications/LuLu.app", None)}
LINEAR_URL = "https://mcp.linear.app/mcp"
STRIX_INSTALLER = "https://strix.ai/install"


def which(name):
    return shutil.which(name, path=os.environ.get("PATH", "") + os.pathsep + os.pathsep.join(EXTRA_PATH))


def claude(args, cwd=None, timeout=120):
    exe = which("claude")
    if not exe:
        return subprocess.CompletedProcess(args, 127, "", "claude not found")
    try:
        return subprocess.run([exe] + args, cwd=cwd or C.HOME, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")


def _user_settings():
    return os.path.join(C.HOME, ".claude", "settings.json")


def _claude_json():
    return os.path.join(C.HOME, ".claude.json")


# ---------------------------------------------------------------- packs

def _packs_state():
    return C.read_json(C.lfg_path("state", "packs.json"), {}) or {}


def pack_on(name):
    return name == "core" or bool((_packs_state().get(name) or {}).get("on"))


def _set_pack(name, on, installed=None):
    st = _packs_state()
    cur = st.get(name) or {}
    cur.update(on=on, at=C.now_iso())
    if installed:
        cur["installed_by_lfg"] = sorted(set(cur.get("installed_by_lfg", [])) | set(installed))
    st[name] = cur
    C.write_json(C.lfg_path("state", "packs.json"), st)


def _have_cask(c):
    app, cmd = CASK_CHECK.get(c, (None, None))
    return bool((app and os.path.isdir(app)) or (cmd and which(cmd)))


def pack_missing(name):
    p = PACKS[name]
    miss = []
    for f in p.get("brew", []):
        if not which(f.split("/")[-1]):
            miss.append("brew:" + f)
    for c in p.get("cask", []):
        if not _have_cask(c):
            miss.append("cask:" + c)
    for t in p.get("uv", []):
        if not which(UV_BIN.get(t, t)):
            miss.append("uv:" + t)
    if p.get("script") == "strix" and not which("strix"):
        miss.append("script:strix")
    if p.get("mcp") == "linear" and not _mcp_user_server("linear"):
        miss.append("mcp:linear")
    if p.get("custom") == "dictate":
        from . import dictate
        if not dictate.installed():
            miss.append("dictate:model")
    if p.get("custom") == "sonarqube":
        from . import sonar
        if not sonar.creds().get("token"):
            miss.append("sonarqube:server")
    return miss


def packs_view():
    out = [{"name": n, "title": p["title"], "about": p["about"], "on": pack_on(n), "missing": pack_missing(n),
            "requires": p.get("requires", []), "experimental": "(experimental)" in p["title"]}
           for n, p in PACKS.items()]
    for r in out:
        if r["name"] == "dictate":  # its controls show even while it's off (greyed), so people see what it offers
            from . import dictate
            st = dictate.settings()
            r["settings"] = {"shortcut": st["shortcut"], "insert": st["insert"], "cleanup": st["cleanup"],
                             "shortcuts": [[k, v["label"]] for k, v in dictate.SHORTCUTS.items()],
                             "preview": not r["on"]}
        if r["name"] == "dictate" and r["on"]:
            from . import dictate
            st = dictate.status()
            r["detail"] = ("%s to talk · %s%s%s" % (st["shortcut_label"], "running" if st["agent"] else "not running",
                                                    " · %d today" % st["today"] if st["today"] else "",
                                                    " · %s" % st["error"] if st["error"] else ""))
    return out


def add_pack(name, yes=False, log=print, allow_scripts=True):
    """Install a pack's tools and switch it on. Homebrew and uv installs are not undone by `lfg uninstall` (other
    tools may use them); they are listed so you can remove them yourself."""
    if name not in PACKS:
        raise ValueError("unknown pack %r (one of %s)" % (name, ", ".join(PACKS)))
    for req in PACKS[name].get("requires", []):
        if not pack_on(req):
            add_pack(req, yes=yes, log=log, allow_scripts=allow_scripts)
    p, installed, notes = PACKS[name], [], []
    brew = which("brew")
    need_brew = [m for m in pack_missing(name) if m.startswith(("brew:", "cask:"))]
    if need_brew and not brew:
        raise RuntimeError("Homebrew is needed for: %s. Install it from https://brew.sh, then re-run."
                           % ", ".join(m.split(":", 1)[1] for m in need_brew))
    if p.get("tap") and any(m.startswith("brew:" + p["tap"]) for m in need_brew):
        _step(log, [brew, "tap", p["tap"]])
    formulas = [m[5:] for m in need_brew if m.startswith("brew:")]
    if formulas:
        _step(log, [brew, "install"] + formulas)
        installed += formulas
    for c in [m[5:] for m in need_brew if m.startswith("cask:")]:
        _step(log, [brew, "install", "--cask", c])
        installed.append(c + " (cask)")
    uv = which("uv")
    for t in [m[3:] for m in pack_missing(name) if m.startswith("uv:")]:
        if not uv:
            raise RuntimeError("uv is needed to install %s (it comes with Core)" % t)
        _step(log, [uv, "tool", "install", t])
        installed.append(t + " (uv)")
    if p.get("script") == "strix" and not which("strix"):
        if allow_scripts and (yes or _ask("Strix's official installer is a curl | bash script from %s. Run it now?"
                                          % STRIX_INSTALLER)):
            _step(log, ["/bin/bash", "-c", "curl -fsSL %s | bash" % STRIX_INSTALLER])
            installed.append("strix")
        else:
            notes.append("Strix not installed: run `curl -fsSL %s | bash` yourself when you want /lfg:pentest."
                         % STRIX_INSTALLER)
    if name == "knowledge":
        from . import omnigraph as OG
        log("    setting up dev-graph and second-brain (local Omnigraph servers)")
        OG.setup(launchd=True, mcp=False)
    if name == "linear":
        notes.append(_add_linear())
    if name == "dictate":
        from . import dictate
        notes += dictate.install(log)
    if name == "sonarqube":
        from . import sonar
        res = sonar.setup(log)
        notes.append("SonarQube is %s at %s; `lfg sonar login` shows the admin password, `lfg sonar scan` checks a "
                     "repo." % (res["state"], res["url"]))
    if name == "headroom":
        from . import headroom as HR
        res = HR.setup(new_scope=C.config()["headroom"].get("scope") if C.config()["headroom"].get("scope")
                       in ("repos", "everywhere") else "repos")
        notes.append("Headroom %s (scope: %s)." % ("is routing" if res.get("live") else "did not start", res["scope"]))
    _set_pack(name, True, installed)
    if name == "pentest":
        notes.append("Open LuLu once and approve its system extension; /lfg:pentest refuses to run without a firewall.")
    return {"pack": name, "installed": installed, "notes": [n for n in notes if n]}


def remove_pack(name):
    """Switch a pack off and stop what it runs (servers, proxy, MCP it registered). Its tools stay installed."""
    if name == "core":
        raise ValueError("Core can't be removed; use `lfg uninstall`")
    if name == "headroom":
        from . import headroom as HR
        HR.off()
    if name == "knowledge":
        CC.undo_where(tag="omnigraph-agent")
    if name == "linear":
        CC.undo_where(tag="mcp-linear")
    if name == "dictate":
        from . import dictate
        dictate.uninstall()
    if name == "sonarqube":
        from . import sonar
        sonar.remove(volumes=False)  # the analysis data stays in its volumes; `lfg sonar remove --data` drops it
    _set_pack(name, False)
    return {"pack": name, "on": False}


def _add_linear():
    if _mcp_user_server("linear"):
        return "Linear: using the `linear` MCP server you already have."
    argv = ["mcp", "add", "--transport", "http", "--scope", "user", "linear", LINEAR_URL]
    cp = claude(argv)
    if cp.returncode:
        return "Linear MCP not added: %s" % (cp.stderr or cp.stdout).strip()[-200:]
    CC.cmd_done(["claude"] + argv, [which("claude") or "claude", "mcp", "remove", "--scope", "user", "linear"],
                "Linear MCP server (user scope)", "linear", tag="mcp-linear")
    return "Linear MCP added; sign in once with /mcp inside Claude Code."


def _step(log, argv):
    log("    $ " + " ".join(os.path.basename(argv[0]) if i == 0 else a for i, a in enumerate(argv)))
    stream = log is print  # in a terminal the tool's own output shows; from the dashboard it goes to the job log
    cp = C.run(argv, timeout=3600, capture=not stream)
    if not stream:
        for line in ((cp.stdout or "") + (cp.stderr or "")).splitlines()[-15:]:
            log("      " + line)
    if cp.returncode:
        raise RuntimeError("`%s` failed (exit %d)" % (" ".join(argv[:4]), cp.returncode))


def _ask(q):
    if not sys.stdin.isatty():
        return False
    try:
        return input("%s [y/N] " % q).strip().lower() in ("y", "yes")
    except EOFError:
        return False


# ---------------------------------------------------------------- per-repo on/off

def _repo_main(path):
    root = C.repo_root(path)
    if not root:
        raise ValueError("%s is not inside a git repository" % path)
    return os.path.realpath(C.main_root(root))


def _set_enabled(root=None, on=True, everywhere=None):
    st = C.enabled_state()
    if everywhere is not None:
        st["everywhere"] = everywhere
    if root:
        if on:
            st["repos"][root] = {"since": C.now_iso()}
        else:
            st["repos"].pop(root, None)
    C.write_json(C.lfg_path("enabled.json"), st)


def _local_settings(root):
    return os.path.join(root, ".claude", "settings.local.json")


def enable(path, hardened=None, build=True):
    """Turn LFG on for the repo containing path. Returns what was done."""
    root = _repo_main(path)
    done = []
    if which("claude"):
        claude_dir_existed = os.path.isdir(os.path.join(root, ".claude"))
        if not CC.find(tag="plugin-local", repo=root):
            inst = claude(["plugin", "install", PLUGIN_ID, "--scope", "local"], cwd=root)
            if inst.returncode and "already" not in (inst.stdout + inst.stderr).lower():
                raise RuntimeError("claude plugin install failed: %s" % (inst.stderr or inst.stdout).strip()[-300:])
            en = claude(["plugin", "enable", PLUGIN_ID, "--scope", "local"], cwd=root)
            if en.returncode and "already" not in (en.stdout + en.stderr).lower():
                raise RuntimeError("claude plugin enable failed: %s" % (en.stderr or en.stdout).strip()[-300:])
            CC.cmd_done(["claude", "plugin", "install", PLUGIN_ID, "--scope", "local"],
                        [which("claude"), "plugin", "uninstall", PLUGIN_ID, "--scope", "local"],
                        "LFG plugin on in this repo", "repo", tag="plugin-local", cwd=root, target=root, repo=root,
                        cleanup_json=[[_local_settings(root), ["enabledPlugins"]]],
                        remove_dir_if_empty=None if claude_dir_existed else os.path.join(root, ".claude"))
            done.append("plugin on (.claude/settings.local.json)")
    else:
        done.append("Claude Code not found: only the hooks' switch was set")
    exclude = os.path.join(root, ".git", "info", "exclude")
    if os.path.isdir(os.path.join(root, ".git")) and CC.lines_add(
            exclude, EXCLUDE_ENTRIES, "Keep LFG's graph folders out of git status", "repo", tag="exclude", repo=root):
        done.append("graph folders ignored in .git/info/exclude")
    _set_enabled(root, True)
    if hardened if hardened is not None else C.config()["guard"].get("hardened"):
        if CC.json_list_add(_local_settings(root), ["permissions", "deny"], hardened_rules(),
                            "Hardened mode: deny rules behind the guard", "repo", tag="hardened", repo=root):
            done.append("hardened deny rules")
    from . import headroom as HR
    if HR.route_repo(root):
        done.append("Headroom routing")
    if build:
        from . import graphs as G
        G.spawn_background(root)
        done.append("code graphs building in the background")
    C.audit("enable", {"repo": root})
    return {"repo": root, "enabled": True, "done": done}


def disable(path=None, root=None):
    """Turn LFG off for a repo and undo exactly what `enable` changed there. Its graphs and runs stay."""
    root = root or _repo_main(path)
    res = CC.undo_where(repo=root)
    _set_enabled(root, False)
    C.audit("disable", {"repo": root})
    return {"repo": root, "enabled": False, "undone": res}


def enable_everywhere(on=True):
    if on:
        for args in (["plugin", "install", PLUGIN_ID, "--scope", "user"],
                     ["plugin", "enable", PLUGIN_ID, "--scope", "user"]):
            cp = claude(args)
            if cp.returncode and "already" not in (cp.stdout + cp.stderr).lower():
                raise RuntimeError("claude %s failed: %s" % (" ".join(args[:2]), (cp.stderr or cp.stdout)[-300:]))
        if not CC.find(tag="plugin-user"):
            CC.cmd_done(["claude", "plugin", "install", PLUGIN_ID, "--scope", "user"],
                        [which("claude") or "claude", "plugin", "uninstall", PLUGIN_ID, "--scope", "user"],
                        "LFG plugin on in every repo", "core", tag="plugin-user")
    else:
        CC.undo_where(tag="plugin-user")
    _set_enabled(everywhere=on)
    return {"everywhere": on}


def repos_view():
    st = C.enabled_state()
    out = []
    from . import dash
    known = {}
    for rid in dash.repo_ids():
        r = dash.repo_root(rid)
        if r:
            known[os.path.realpath(r)] = rid
    for root in sorted(set(st["repos"]) | set(known)):
        out.append({"root": root, "name": os.path.basename(root), "enabled": st["everywhere"] or root in st["repos"],
                    "exists": os.path.isdir(root), "repo_id": known.get(root),
                    "hardened": bool(CC.find(tag="hardened", repo=root)),
                    "headroom": bool(CC.find(tag="headroom-route", repo=root))})
    return {"everywhere": st["everywhere"], "repos": out}


# ---------------------------------------------------------------- scan (read-only)

def _mcp_user_servers():
    d = C.read_json(_claude_json(), {}) or {}
    return d.get("mcpServers") if isinstance(d.get("mcpServers"), dict) else {}


def _mcp_user_server(name):
    return _mcp_user_servers().get(name)


def _claude_version():
    cp = claude(["--version"], timeout=20)
    return (cp.stdout or "").strip().split(" ")[0] if cp.returncode == 0 else None


def _personal_skills():
    d = os.path.join(C.HOME, ".claude", "skills")
    return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))) if os.path.isdir(d) else []


def _lfg_skills():
    d = os.path.join(C.PLUGIN_ROOT, "skills")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def _port_busy(port):
    import socket
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _managed_settings():
    return next((p for p in ("/Library/Application Support/ClaudeCode/managed-settings.json",)
                 if os.path.exists(p)), None)


def scan():
    from . import headroom as HR
    us = C.read_json(_user_settings(), {}) or {}
    env = us.get("env") if isinstance(us.get("env"), dict) else {}
    base = str(env.get("ANTHROPIC_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or "")
    collisions = sorted(set(_personal_skills()) & set(_lfg_skills()))
    hooks = us.get("hooks") if isinstance(us.get("hooks"), dict) else {}
    free = shutil.disk_usage(C.HOME).free // (1 << 30)
    return {
        "claude": {"found": bool(which("claude")), "version": _claude_version() if which("claude") else None},
        "managed_settings": _managed_settings(),
        "cloud_provider": HR.cloud_provider(),
        "base_url_host": re.sub(r"^https?://([^/]+).*$", r"\1", base) if base else None,
        "user_hooks": sorted(hooks),
        "user_mcp_servers": sorted(_mcp_user_servers()),
        "skill_collisions": collisions,
        "ports_busy": [p for p in (C.config()["ui"]["port"], C.config()["headroom"]["port"]) if _port_busy(p)],
        "disk_free_gb": free,
        "brew": bool(which("brew")),
        "python": sys.version.split()[0],
        "installed": os.path.isdir(C.lfg_path("plugin")),
        "legacy": [{k: v for k, v in item.items() if k != "apply"} for item in legacy_items()],
    }


# ---------------------------------------------------------------- older installs (before the change ledger)

def legacy_items(uninstalling=False):
    """Machine-wide changes older LFG versions made, each with a fix. Detected exactly; nothing else is touched."""
    from . import headroom as HR
    from . import settings as S
    out = []
    us = C.read_json(_user_settings(), {}) or {}
    if (us.get("enabledPlugins") or {}).get(PLUGIN_ID) and not C.enabled_state()["everywhere"] \
            and not CC.find(tag="plugin-user"):
        out.append({"id": "plugin-everywhere", "default": True,
                    "title": "LFG plugin is on in every repo (older install)",
                    "fix": "Turn it off machine-wide; it stays on in the repos you enable.",
                    "apply": _legacy_plugin_user})
    deny = ((us.get("permissions") or {}).get("deny") or []) if isinstance(us.get("permissions"), dict) else []
    ours = [d for d in deny if d in HARDENED_DENY]
    if len(ours) >= 10:  # the old installer added all of them; a handful could be the user's own
        out.append({"id": "deny-rules", "default": True,
                    "title": "%d LFG deny rules in ~/.claude/settings.json block git commit/push everywhere"
                             % len(ours),
                    "fix": "Remove exactly those rules (the guard still protects LFG repos).",
                    "apply": lambda: CC.json_list_remove(_user_settings(), ["permissions", "deny"], HARDENED_DENY)})
    md = S.claude_md()
    if md["has_lfg_section"]:
        edited = S.legacy_section_edited()
        out.append({"id": "claude-md", "default": not edited,
                    "title": "LFG block in ~/.claude/CLAUDE.md" + (" (you edited it)" if edited else ""),
                    "fix": "Remove the block (LFG now adds it as session context in LFG repos only)."
                    if not edited else "Left as is because you edited it; remove it by hand if you like.",
                    "apply": S.remove_claude_md_section if not edited else None})
    for name, srv in sorted(_mcp_user_servers().items()):
        cmd = " ".join([str(srv.get("command", ""))] + [str(a) for a in srv.get("args") or []])
        if (name in ("dev-graph", "second-brain") and "omnigraph mcp" in cmd) or \
                (name == "headroom" and "headroom mcp serve" in cmd) or \
                (name == "code-review-graph" and cmd.strip().endswith("code-review-graph serve")):
            out.append({"id": "mcp-" + name, "default": True,
                        "title": "MCP server `%s` registered for every session (older install)" % name,
                        "fix": "Remove it; the plugin brings its own, only in LFG repos.",
                        "apply": (lambda n=name: claude(["mcp", "remove", "--scope", "user", n]))})
    if HR.routed() and not CC.find(tag=HR.ROUTE_TAG):
        out.append({"id": "headroom-everywhere", "default": True,
                    "title": "All Claude Code traffic goes through the Headroom proxy (older install)",
                    "fix": "Restore your previous API endpoint; turn Headroom back on from Settings if you want it.",
                    "apply": HR.off})
    if not uninstalling:
        repos = [r for r in _repos_with_graphs() if r not in C.enabled_state()["repos"]]
        if repos and not C.enabled_state()["repos"]:
            out.append({"id": "repos", "default": True,
                        "title": "%d repo(s) you used LFG in: %s" % (len(repos), ", ".join(
                            os.path.basename(r) for r in repos[:5]) + (" …" if len(repos) > 5 else "")),
                        "fix": "Turn LFG on for them, so they keep working as before.",
                        "apply": lambda: [enable(r, build=False) for r in repos]})
    return out


def _legacy_plugin_user():
    cp = claude(["plugin", "uninstall", PLUGIN_ID, "--scope", "user"])
    if cp.returncode:  # enabled but not recorded as a user install: just switch it off there
        CC.json_set_raw(_user_settings(), ["enabledPlugins", PLUGIN_ID], CC.MISSING)


def _repos_with_graphs():
    out = []
    for p in sorted(__import__("glob").glob(C.lfg_path("graphs", "*", "state.json"))):
        r = (C.read_json(p, {}) or {}).get("repo_root")
        if r and os.path.exists(os.path.join(r, ".git")):
            out.append(os.path.realpath(r))
    return sorted(set(out))


# ---------------------------------------------------------------- what's new (printed once after an update)

WHATS_NEW = {
    "0.3.0": ["LFG Dictate: hold Option+Space anywhere on your Mac to dictate, on-device. Off until you turn it on: "
              "`lfg add dictate`. Open `lfg ui` for a 1-minute tour.",
              "Commit approval: Claude can commit when you ask, after you approve each commit (Settings → Safety).",
              "Pentest and Headroom are now labelled Experimental."],
}


def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])


def whats_new(mark_seen=True):
    """Lines for every version newer than the last one this machine saw (nothing on a first install, which gets the
    dashboard's tour instead). Remembered in ~/.lfg/state/version.json."""
    p = C.lfg_path("state", "version.json")
    seen = (C.read_json(p, {}) or {}).get("seen")
    if not seen and (os.path.exists(C.lfg_path("state", "ledger.json")) or os.path.exists(C.lfg_path("enabled.json"))):
        seen = "0.2.0"  # installed before LFG kept track of versions
    lines = [] if not seen else [line for v in sorted(WHATS_NEW, key=_ver) if _ver(seen) < _ver(v) <= _ver(C.VERSION)
                                 for line in WHATS_NEW[v]]
    if mark_seen and seen != C.VERSION:
        C.write_json(p, {"seen": C.VERSION})
    return lines


# ---------------------------------------------------------------- plan + apply

def _install_files_needed():
    src, dst = C.PLUGIN_ROOT, C.lfg_path("plugin")
    if os.path.realpath(src) == os.path.realpath(dst):
        return False
    return _tree_hash(src) != _tree_hash(dst)


def _tree_hash(d):
    if not os.path.isdir(d):
        return None
    h = hashlib.sha256()
    for root, dirs, files in os.walk(d):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in sorted(files):
            if f.endswith(".pyc") or f == ".DS_Store":
                continue
            p = os.path.join(root, f)
            h.update(os.path.relpath(p, d).encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def install_files(log=print):
    """Copy plugin/, docs/ and CONTRACT.md from this checkout into ~/.lfg (swap in place), keep your skill edits."""
    src_root = C.LFG_ROOT
    C.ensure_dir(C.LFG_HOME)
    os.chmod(C.LFG_HOME, 0o700)
    for name in ("plugin", "docs"):
        src, dst = os.path.join(src_root, name), C.lfg_path(name)
        if not os.path.isdir(src):
            continue
        tmp = dst + ".new"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        shutil.rmtree(dst, ignore_errors=True)
        os.replace(tmp, dst)
    if os.path.isfile(os.path.join(src_root, "CONTRACT.md")):
        shutil.copy2(os.path.join(src_root, "CONTRACT.md"), C.lfg_path("CONTRACT.md"))
    defaults = C.lfg_path("defaults", "skills")
    shutil.rmtree(defaults, ignore_errors=True)
    shutil.copytree(os.path.join(src_root, "plugin", "skills"), defaults)
    for f in sorted(__import__("glob").glob(C.lfg_path("overrides", "skills", "*", "SKILL.md"))):
        n = os.path.basename(os.path.dirname(f))
        if os.path.isdir(C.lfg_path("plugin", "skills", n)):
            shutil.copy2(f, C.lfg_path("plugin", "skills", n, "SKILL.md"))
            log("    kept your dashboard edit of /lfg:%s" % n)
    os.chmod(C.lfg_path("plugin", "bin", "lfg"), 0o755)
    for d in ("graphs", "repos", "runs", "secintel", "strix", "feedback", "playbooks", "ui/static", "vendor",
              "state"):
        C.ensure_dir(C.lfg_path(d))
    if not os.path.exists(C.lfg_path("config.json")):
        C.write_json(C.lfg_path("config.json"), {"pentest": {"model": "", "require_firewall": True},
                                                 "secure": {"company_domains": [], "private_scopes": []},
                                                 "linear": {"team": ""}})


def _marketplace_known():
    d = C.read_json(os.path.join(C.HOME, ".claude", "plugins", "known_marketplaces.json"), {}) or {}
    return "lfg" in d


def plan(packs=("core",), here=None, everywhere=False, legacy=True):
    """The steps `apply` would run, each with what it changes. Read-only."""
    steps = []
    if _install_files_needed() or not os.path.isdir(C.lfg_path("plugin")):
        steps.append({"id": "files", "title": "Install LFG %s into %s" % (C.VERSION, C.LFG_HOME),
                      "changes": ["copy plugin/, docs/ and CONTRACT.md (your skill edits are kept)"], "where": "lfg"})
    shim = os.path.join(C.HOME, ".local", "bin", "lfg")
    target = C.lfg_path("plugin", "bin", "lfg")
    if not (os.path.islink(shim) and os.readlink(shim) == target):
        conflict = None if not os.path.lexists(shim) or os.path.islink(shim) else \
            "%s exists and isn't LFG's; skipped (add %s to PATH yourself)" % (shim, os.path.dirname(target))
        steps.append({"id": "shim", "title": "Put `lfg` on your PATH", "changes": ["symlink %s" % shim],
                      "where": "home", "conflict": conflict})
    for name in packs:
        miss = pack_missing(name)
        if miss or not pack_on(name):
            steps.append({"id": "pack:" + name, "title": "%s pack: %s" % (PACKS[name]["title"], PACKS[name]["about"]),
                          "changes": ["install " + m.replace(":", " ", 1) for m in miss] or ["switch on"],
                          "where": "system"})
    if not _marketplace_known():
        steps.append({"id": "marketplace", "title": "Register LFG with Claude Code (installed, but off)",
                      "changes": ["claude plugin marketplace add %s (Claude Code adds it to "
                                  "extraKnownMarketplaces in ~/.claude/settings.json)" % C.lfg_path("plugin")],
                      "where": "claude"})
    if everywhere:
        steps.append({"id": "everywhere", "title": "Turn LFG on in every repo",
                      "changes": ["claude plugin install lfg@lfg --scope user (enabledPlugins in "
                                  "~/.claude/settings.json)"], "where": "claude"})
    elif here:
        root = _repo_main(here)
        if root not in C.enabled_state()["repos"]:
            steps.append({"id": "enable:" + root, "title": "Turn LFG on in %s" % os.path.basename(root),
                          "changes": ["enabledPlugins in %s" % _local_settings(root),
                                      "graph folders in %s/.git/info/exclude" % root], "where": "repo"})
    if legacy:
        for item in legacy_items():
            steps.append({"id": "legacy:" + item["id"], "title": item["title"], "changes": [item["fix"]],
                          "where": "migrate", "default": item["default"], "manual": item.get("apply") is None})
    for s in steps:
        s.setdefault("default", True)
    return steps


def apply(steps, packs=("core",), here=None, yes=False, log=print):
    """Run the selected steps. If one fails, the changes this run made outside ~/.lfg are undone."""
    start = CC._load()["next"]
    results = []
    legacy = {i["id"]: i for i in legacy_items()}
    for s in steps:
        if s.get("conflict") or s.get("manual") or not s.get("default", True):
            results.append({"id": s["id"], "status": "skipped", "note": s.get("conflict") or ""})
            continue
        log("==> " + s["title"])
        try:
            note = _apply_one(s, legacy, yes, log)
            results.append({"id": s["id"], "status": "done", "note": note or ""})
        except Exception as e:
            log("!!  %s: %s" % (s["id"], e))
            rolled = [CC.undo(x["id"]) for x in sorted(CC.entries(), key=lambda x: -x["id"]) if x["id"] >= start]
            results.append({"id": s["id"], "status": "failed", "note": str(e), "rolled_back": len(rolled)})
            return {"ok": False, "results": results}
    C.audit("setup", {"steps": [r["id"] for r in results if r["status"] == "done"]})
    return {"ok": True, "results": results}


def _apply_one(s, legacy, yes, log):
    sid = s["id"]
    if sid == "files":
        install_files(log)
    elif sid == "shim":
        CC.link(os.path.join(C.HOME, ".local", "bin", "lfg"), C.lfg_path("plugin", "bin", "lfg"),
                "`lfg` on your PATH", "core", tag="shim")
        if os.path.join(C.HOME, ".local", "bin") not in os.environ.get("PATH", "").split(os.pathsep):
            return "add ~/.local/bin to PATH (e.g. in ~/.zshrc) to type `lfg` in your terminal"
    elif sid.startswith("pack:"):
        r = add_pack(sid[5:], yes=yes, log=log)
        return " ".join(r["notes"])
    elif sid == "marketplace":
        argv = ["plugin", "marketplace", "add", C.lfg_path("plugin")]
        cp = claude(argv)
        if cp.returncode and "already" not in (cp.stdout + cp.stderr).lower():
            raise RuntimeError("claude plugin marketplace add failed: %s" % (cp.stderr or cp.stdout).strip()[-300:])
        CC.cmd_done(["claude"] + argv, [which("claude") or "claude", "plugin", "marketplace", "remove", "lfg"],
                    "LFG's local marketplace", "core", tag="marketplace",
                    cleanup_json=[[_user_settings(), ["extraKnownMarketplaces"]]])
    elif sid == "everywhere":
        enable_everywhere(True)
    elif sid.startswith("enable:"):
        return "; ".join(enable(sid[7:])["done"])
    elif sid.startswith("legacy:"):
        item = legacy.get(sid[7:])
        if item and item.get("apply"):
            item["apply"]()
    return None


# ---------------------------------------------------------------- uninstall

def uninstall(dry_run=False, keep_data=False, log=print):
    """Undo every recorded change (newest first), clean up what older versions did, then remove ~/.lfg."""
    out = {"undone": [], "kept": [], "legacy": [], "removed": None, "tools_left": [],
           "graph_dirs_left": [os.path.join(r, d) for r in _repos_with_graphs()
                               for d in (".code-review-graph", "graphify-out") if os.path.isdir(os.path.join(r, d))]}
    for r in CC.undo_all(dry_run=dry_run):
        (out["kept"] if r["status"] == "kept" else out["undone"]).append(r)
    for item in legacy_items(uninstalling=True):
        if item.get("apply") and item["default"]:
            if not dry_run:
                item["apply"]()
            out["legacy"].append(item["title"])
    for p in sorted(__import__("glob").glob(os.path.join(C.HOME, "Library", "LaunchAgents", "dev.lfg.*.plist"))):
        label = os.path.basename(p)[:-6]
        if not dry_run:
            C.run(["launchctl", "bootout", "gui/%d/%s" % (os.getuid(), label)])
            os.remove(p)
        out["legacy"].append("login agent %s" % label)
    for st in _packs_state().values():
        out["tools_left"] += st.get("installed_by_lfg", [])
    if not dry_run and not keep_data and os.path.isdir(C.LFG_HOME):
        shutil.rmtree(C.LFG_HOME)
        out["removed"] = C.LFG_HOME
    elif keep_data:
        out["removed"] = None
    else:
        out["removed"] = "(would remove %s)" % C.LFG_HOME
    return out
