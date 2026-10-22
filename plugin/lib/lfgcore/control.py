"""The dashboard's control center: the Claude Code settings that matter for LFG, and every skill Claude Code loads.

Read-only views build on setup.scan(); every write goes through setup / headroom / claudecfg, so a change made in the
dashboard is recorded and undoable exactly like the same change made with the CLI. Writes need the edit key (ui.py).
"""
import contextlib
import glob
import io
import os
import re
import threading

from . import claudecfg as CC
from . import common as C
from .settings import Invalid

JOBS = {}  # pack installs started from the dashboard: name -> {status, log, started, ended}; lives in `lfg ui`


def _quiet(fn, *a, **kw):
    """Run a CLI-oriented function; turn its C.die() (SystemExit + a message on stderr) into Invalid."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return fn(*a, **kw)
    except SystemExit:
        raise Invalid((err.getvalue().strip().replace("lfg: ", "", 1) or "failed")) from None
    except (ValueError, RuntimeError) as e:
        raise Invalid(str(e)) from None


# ---------------------------------------------------------------- Settings → Claude Code

def claude_view():
    from . import headroom as HR
    from . import mcp as M
    from . import setup as SU
    sc = SU.scan()
    hr = HR.status()
    blocked = []
    for line in C.read_text(C.lfg_path("audit.log")).splitlines()[-400:]:
        if '"blocked"' in line:
            try:
                blocked.append(__import__("json").loads(line))
            except ValueError:
                pass
    mcp = []
    for name in M.SERVERS:
        try:
            why = M.why_not(name)
        except Exception as e:  # a broken pack must not take the page down
            why = "check failed (%s)" % type(e).__name__
        mcp.append({"name": name, "ready": why is None, "why": why or ""})
    return {
        "repos": SU.repos_view(), "packs": SU.packs_view(), "jobs": JOBS,
        "headroom": {k: hr[k] for k in ("installed", "live", "scope", "routes", "upstream", "mode", "cloud_provider")},
        "hardened": bool(C.config()["guard"].get("hardened")),
        "allow_commits": bool(C.config()["guard"].get("allow_commits", True)),
        "changes": [{"id": e["id"], "ts": e["ts"], "group": e.get("group") or "", "why": e.get("why") or "",
                     "text": CC.describe(e), "repo": e.get("repo") or ""} for e in CC.entries()],
        "legacy": sc["legacy"], "mcp": mcp, "blocked": blocked[-15:][::-1],
        "scan": {k: sc[k] for k in ("claude", "managed_settings", "cloud_provider", "base_url_host", "user_hooks",
                                    "user_mcp_servers", "skill_collisions", "disk_free_gb")},
    }


# ---------------------------------------------------------------- the Integrations page

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # one broken integration must never take the page down
        return default


def _status_core(SU):
    miss = [t for t in ("code-review-graph", "graphify") if not SU.which(t)]
    return ("bad", "Missing: %s" % ", ".join(miss)) if miss else ("ok", "code-review-graph and graphify installed")


def _status_knowledge(SU):
    from . import omnigraph as OG
    gs = _safe(lambda: OG.status()["graphs"], {}) or {}
    if not gs:
        return "", "Not set up"
    down = [n for n, g in gs.items() if not g.get("ready")]
    loose = [n for n, g in gs.items() if g.get("ready") and not g.get("launchd")]
    if down:
        return "bad", "Not answering: %s" % ", ".join(down)
    if loose:
        return "warn", "Running, but not kept up by its login agent: %s (Restart fixes it)" % ", ".join(loose)
    return "ok", "dev-graph and second-brain running"


def _status_headroom(SU):
    from . import headroom as HR
    hr = _safe(HR.status, {}) or {}
    if hr.get("live"):
        return "ok", "Running, forwarding to %s" % hr.get("upstream")
    if hr.get("scope") not in (None, "off"):
        return "warn", "Set to route %s, but the proxy is down" % hr.get("scope")
    return "", "Installed; not routing"


def _status_sonarqube(SU):
    from . import sonar as SQ
    st = _safe(SQ.server_state, "missing")
    if st != "up":
        return ("warn" if st != "missing" else ""), "Server %s" % st
    priv = _safe(SQ.privacy_applied)
    shares = (C.config().get("sonarqube") or {}).get("telemetry")
    if priv is False:
        return "warn", "Running at %s; the stats setting changed and needs a restart to apply" % SQ.URL
    return "ok", "Running at %s%s" % (SQ.URL, "; shares usage stats" if shares else "; fully local")


def _status_dictate(SU):
    from . import dictate
    st = _safe(dictate.status, {}) or {}
    return ("ok" if st.get("agent") else "warn"), "%s to talk · %s%s" % (
        st.get("shortcut_label", "?"), "running" if st.get("agent") else "not running",
        " · %s" % st["error"] if st.get("error") else "")


def _status_pentest(SU):
    from . import settings as S
    o = _safe(S.ollama_models, {}) or {}
    model = C.config()["pentest"].get("model") or ""
    bits = ["Strix %s" % ("installed" if SU.which("strix") else "not installed"),
            "Ollama %s" % ("running" if o.get("running") else "not running"),
            "model: %s" % (model or "none chosen")]
    ok = SU.which("strix") and o.get("running") and model
    return ("ok" if ok else "warn"), " · ".join(bits)


def _status_tools(name):
    def f(SU):
        miss = SU.pack_missing(name)
        return ("warn", "Missing: %s" % ", ".join(m.split(":", 1)[-1] for m in miss)) if miss else ("ok", "Installed")
    return f


def _status_shipcheck(SU):
    if not SU.which("docker"):
        return "bad", "Docker isn't installed"
    up = C.run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)
    return ("ok", "Docker %s running" % up.stdout.strip()) if up.returncode == 0 else ("warn", "Docker isn't running")


def _status_linear(SU):
    return ("ok", "Connected through /mcp") if not SU.pack_missing("linear") else \
        ("warn", "Not signed in: run /mcp in Claude Code and sign in to Linear")


STATUS = {"core": _status_core, "knowledge": _status_knowledge, "headroom": _status_headroom,
          "sonarqube": _status_sonarqube, "dictate": _status_dictate, "pentest": _status_pentest,
          "security": _status_tools("security"), "shipcheck": _status_shipcheck, "linear": _status_linear}
ORDER = ["core", "knowledge", "headroom", "sonarqube", "dictate", "pentest", "security", "shipcheck", "linear"]


def integrations_view():
    """Every integration on one page: what it is, whether it's on, how it's doing, and its settings."""
    from . import settings as S
    from . import setup as SU
    fields = S.config_view()["fields"]
    packs = {p["name"]: p for p in SU.packs_view()}
    out = []
    for name in ORDER + [n for n in packs if n not in ORDER]:
        p = packs.get(name)
        if not p:
            continue
        fn = STATUS.get(name) if p["on"] else None
        tone, line = _safe(lambda f=fn: f(SU), ("", "")) if fn else ("", "")
        out.append(dict(p, tone=tone, status=line, fields=[f for f in fields if f.get("owner") == name]))
    from . import hooks as H
    gh = _safe(H._gh_signed_in)
    out.append({"name": "github", "title": "GitHub", "about": "Pull requests, CI status and reviews, through the gh "
                "CLI. Read-only, except the review replies you post yourself from the Reviews page.",
                "on": True, "fixed": True, "missing": [] if SU.which("gh") else ["gh"],
                "tone": "ok" if gh else "warn", "status": "Signed in" if gh else "Not signed in: run `gh auth login`",
                "fields": []})
    return {"integrations": out, "jobs": JOBS}


def omnigraph_restart():
    from . import omnigraph as OG
    return {"restarted": [n for n in OG.cfg()["graphs"] if OG.restart(n)]}


def sonar_apply():
    from . import sonar as SQ
    try:
        return SQ.apply_privacy(log=lambda m: None)
    except SQ.Problem as e:
        raise Invalid(str(e)) from None


def _known_root(root):
    from . import setup as SU
    roots = {r["root"] for r in SU.repos_view()["repos"]}
    if root not in roots:
        raise Invalid("LFG doesn't know that folder; run `lfg enable` in it once")
    return root


def repo_on(root):
    from . import setup as SU
    return _quiet(SU.enable, _known_root(root))


def repo_off(root):
    from . import setup as SU
    return _quiet(SU.disable, root=_known_root(root))


def everywhere(on):
    from . import setup as SU
    return _quiet(SU.enable_everywhere, bool(on))


def headroom_scope(scope):
    from . import headroom as HR
    from . import setup as SU
    if scope not in HR.SCOPES:
        raise Invalid("scope must be off, repos or everywhere")
    if scope == "off":
        return _quiet(HR.off)
    if not SU.pack_on("headroom") or not SU.which("headroom"):
        raise Invalid("add the Headroom pack first (Feature packs above)")
    return _quiet(HR.setup, None, scope)


def hardened(on):
    """Hardened mode: deny rules behind the guard, in each LFG repo's .claude/settings.local.json."""
    from . import setup as SU
    raw = C.read_json(C.lfg_path("config.json"), {}) or {}
    raw.setdefault("guard", {})["hardened"] = bool(on)
    C.write_json(C.lfg_path("config.json"), raw)
    n = 0
    if on:
        for root in C.enabled_state()["repos"]:
            if os.path.isdir(root) and CC.json_list_add(
                    os.path.join(root, ".claude", "settings.local.json"), ["permissions", "deny"], SU.hardened_rules(),
                    "Hardened mode: deny rules behind the guard", "repo", tag="hardened", repo=root):
                n += 1
    else:
        n = len(CC.undo_where(tag="hardened"))
    return {"hardened": bool(on), "repos": n}


def pack_add(name):
    from . import setup as SU
    if name not in SU.PACKS:
        raise Invalid("unknown pack")
    if (JOBS.get(name) or {}).get("status") == "running":
        return {"started": name}
    job = JOBS[name] = {"status": "running", "log": [], "started": C.now_iso()}

    def log(line):
        job["log"] = (job["log"] + [str(line)])[-200:]

    def work():
        try:
            res = SU.add_pack(name, yes=True, log=log, allow_scripts=False)
            for note in res.get("notes", []):
                log(note)
            job["status"] = "done"
        except BaseException as e:  # SystemExit from C.die included
            log("failed: %s" % (e if not isinstance(e, SystemExit) else "see the terminal running `lfg ui`"))
            log("You can also run `lfg add %s` in your terminal." % name)
            job["status"] = "failed"
        job["ended"] = C.now_iso()
        C.audit("pack-add", {"pack": name, "status": job["status"]})
    threading.Thread(target=work, daemon=True).start()
    return {"started": name, "note": "Installing in the background; progress shows below."}


def pack_remove(name):
    from . import setup as SU
    return _quiet(SU.remove_pack, name)


def change_undo(eid):
    try:
        return CC.undo(int(eid))
    except (TypeError, ValueError) as e:
        raise Invalid(str(e)) from None


def legacy_fix(item_id):
    from . import setup as SU
    item = next((i for i in SU.legacy_items() if i["id"] == item_id), None)
    if not item or not item.get("apply"):
        raise Invalid("nothing to fix for %r (reload the page)" % item_id)
    _quiet(item["apply"])
    return {"fixed": item_id}


# ---------------------------------------------------------------- guided tours (shown once, skippable)

TOURS = ("dictate", "dictate-intro", "dictate-banner")


def tours_view():
    """What to offer, once each, on a fresh install or after an update alike: the Dictate intro while Dictate is off
    (what it is, how to turn it on), the controls tour once it is on. Finished or skipped is remembered."""
    from . import dictate as DI
    from . import setup as SU
    done = C.read_json(C.lfg_path("state", "tours.json"), {}) or {}
    on = SU.pack_on("dictate") and DI.installed()
    full = bool(done.get("dictate")) or (done.get("dictate-intro") or {}).get("how") == "finished"  # saw every control
    return {"dictate": {"ready": on, "on": on, "done": full,
                        "intro_done": bool(done.get("dictate-intro") or done.get("dictate")),
                        "banner_closed": bool(done.get("dictate-banner"))}}


def tour_done(name, how="finished"):
    if name not in TOURS:
        raise Invalid("unknown tour")
    p = C.lfg_path("state", "tours.json")
    d = C.read_json(p, {}) or {}
    d[name] = {"how": "skipped" if how == "skipped" else "finished", "at": C.now_iso()}
    C.write_json(p, d)
    return {"tour": name, "done": True}


# ---------------------------------------------------------------- Skills: everything Claude Code loads

def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n?", text or "", re.S)
    out = {}
    if not m:
        return out
    key = None
    for line in m.group(1).split("\n"):
        mm = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if mm:
            key, val = mm.group(1), mm.group(2).strip()
            out[key] = "" if val in (">", "|", ">-", "|-") else val.strip("\"'")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def _plugin_skill_dirs():
    """(plugin id, skills dir, enabled?) for every installed plugin Claude Code knows about."""
    out, seen = [], set()
    user = C.read_json(os.path.join(C.HOME, ".claude", "settings.json"), {}) or {}
    enabled = user.get("enabledPlugins") if isinstance(user.get("enabledPlugins"), dict) else {}
    inst = C.read_json(os.path.join(C.HOME, ".claude", "plugins", "installed_plugins.json"), {}) or {}
    for pid, recs in sorted((inst.get("plugins") or {}).items()):
        if pid in seen:
            continue
        seen.add(pid)
        if pid == "lfg@lfg":
            path = C.PLUGIN_DIR
        else:
            path = next((r.get("installPath") for r in (recs if isinstance(recs, list) else [recs])
                         if isinstance(r, dict) and r.get("installPath") and os.path.isdir(r["installPath"])), None)
        if path:
            out.append((pid, os.path.join(path, "skills"), enabled.get(pid)))
    if "lfg@lfg" not in seen and os.path.isdir(os.path.join(C.PLUGIN_DIR, "skills")):
        out.append(("lfg@lfg", os.path.join(C.PLUGIN_DIR, "skills"), None))
    return out


def _items(rid=None):
    items = []

    def add(source, path, name, invoke, editable, plugin=None, enabled=None):
        text = C.read_text(path)[:20000]
        fm = _frontmatter(text)
        desc = fm.get("description", "")
        items.append({"id": "%s:%s" % (plugin or source, name), "name": fm.get("name") or name, "source": source,
                      "plugin": plugin, "invoke": invoke, "path": path, "editable": editable,
                      "description": desc, "chars": len(desc),
                      "auto": str(fm.get("disable-model-invocation", "")).lower() != "true",
                      "user_invocable": str(fm.get("user-invocable", "")).lower() != "false",
                      "enabled": enabled})
    for p in sorted(glob.glob(os.path.join(C.HOME, ".claude", "skills", "*", "SKILL.md"))):
        n = os.path.basename(os.path.dirname(p))
        add("personal", p, n, "/" + n, True)
    for p in sorted(glob.glob(os.path.join(C.HOME, ".claude", "commands", "*.md"))):
        n = os.path.basename(p)[:-3]
        add("personal command", p, n, "/" + n, False)
    if rid:
        from . import dash
        root = dash.repo_root(rid)
        for p in sorted(glob.glob(os.path.join(root or "/nonexistent", ".claude", "skills", "*", "SKILL.md"))):
            n = os.path.basename(os.path.dirname(p))
            add("project", p, n, "/" + n, False)
    for pid, sdir, en in _plugin_skill_dirs():
        pname = pid.split("@")[0]
        for p in sorted(glob.glob(os.path.join(sdir, "*", "SKILL.md"))):
            n = os.path.basename(os.path.dirname(p))
            add("plugin", p, n, "/%s:%s" % (pname, n), pid == "lfg@lfg", plugin=pid, enabled=en)
    return items


def skills_inventory(rid=None):
    items = _items(rid)
    bare = {}
    for it in items:
        bare.setdefault(it["name"], []).append(it)
    for it in items:
        same = bare[it["name"]]
        it["collides_with"] = [x["invoke"] for x in same if x is not it]
        # the short /name goes to a personal skill first, then a project one; plugins keep their /plugin:name
        it["shadowed"] = it["source"] == "plugin" and any(x["source"] != "plugin" for x in same)
        it.pop("path")
    auto = [i for i in items if i["auto"]]
    return {"skills": items,
            "summary": {"total": len(items), "auto": len(auto), "auto_chars": sum(i["chars"] for i in auto),
                        "approx_tokens": sum(i["chars"] + len(i["name"]) + 8 for i in auto) // 4,
                        "collisions": sum(1 for i in items if i["collides_with"]),
                        "sources": sorted({i["source"] for i in items})}}


def _set_frontmatter_key(text, key, value):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise Invalid("this skill has no front matter header")
    lines = [ln for ln in m.group(1).split("\n") if not re.match(r"^%s:" % re.escape(key), ln)]
    if value is not None:
        lines.append("%s: %s" % (key, value))
    return "---\n%s\n---\n%s" % ("\n".join(lines), text[m.end():])


def skill_auto(skill_id, auto):
    """Let Claude use a skill on its own (auto) or only when you type it. Personal skills are edited in place (a
    backup is kept); LFG skills are saved as your override, which survives updates. Other plugins' skills are theirs."""
    from . import settings as S
    it = next((i for i in _items() if i["id"] == skill_id), None)
    if not it or not it["editable"]:
        raise Invalid("only your personal skills and LFG's skills can be changed here")
    text = C.read_text(it["path"])
    new = _set_frontmatter_key(text, "disable-model-invocation", None if auto else "true")
    if new == text:
        return {"id": skill_id, "auto": bool(auto)}
    if it["source"] == "plugin":  # LFG: keep its own `auto-trigger` note in step with Claude Code's setting
        if re.search(r"^auto-trigger:", new, re.M):
            new = _set_frontmatter_key(new, "auto-trigger", "true" if auto else "false")
        S.save_skill(os.path.basename(os.path.dirname(it["path"])), new)
    else:
        CC.backup(it["path"], "skills-personal")
        with open(it["path"], "w") as f:
            f.write(new)
        C.audit("skill-auto", {"skill": skill_id, "auto": bool(auto)})
    return {"id": skill_id, "auto": bool(auto), "note": "New Claude Code sessions (or /reload-plugins) use it."}


def skill_text(skill_id, rid=None):
    it = next((i for i in _items(rid) if i["id"] == skill_id), None)
    if not it:
        return {"available": False, "why": "skill not found"}
    return {"id": skill_id, "invoke": it["invoke"], "source": it["source"], "text": C.read_text(it["path"])[:200000],
            "lfg_name": os.path.basename(os.path.dirname(it["path"])) if it["plugin"] == "lfg@lfg" else None}
