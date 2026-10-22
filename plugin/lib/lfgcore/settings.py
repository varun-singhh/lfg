"""Editable settings for the dashboard: ~/.lfg/config.json, the LFG skills and the global ~/.claude/CLAUDE.md.

Writes are only accepted with the local edit key (~/.lfg/ui/edit.key, 0600). `lfg ui` hands it to the browser in
the URL fragment and never prints it; the guard treats *.key files as secrets, so an agent can't read it and
can't use the dashboard to get around guard rule 13. Every save is validated, refused if it looks like it
contains a secret, and backed up first.
"""
import glob
import hashlib
import hmac
import os
import re
import secrets
import shutil
import time

from . import common as C

# ---------------------------------------------------------------- edit key

def _key_path():
    return C.lfg_path("ui", "edit.key")


def edit_key():
    p = _key_path()
    k = C.read_text(p).strip()
    if len(k) < 32:
        k = secrets.token_urlsafe(32)
        C.write_text(p, k + "\n", mode=0o600)
    return k


def key_ok(given):
    return bool(given) and hmac.compare_digest(str(given), edit_key())


def _secret_kinds(text):
    from .hooks import SECRET_OUTPUT_RX
    return sorted({k for k, rx in SECRET_OUTPUT_RX if rx.search(text or "")})


def _backup(path, kind):
    if os.path.isfile(path):
        dst = C.lfg_path("backups", kind, "%s.%s" % (os.path.basename(path), time.strftime("%Y%m%d%H%M%S")))
        C.ensure_dir(os.path.dirname(dst))
        shutil.copy2(path, dst)
        os.chmod(dst, 0o600)


class Invalid(ValueError):
    pass


# ---------------------------------------------------------------- config.json

MODELS = ("haiku", "sonnet", "opus")
LOOPBACK_URL = re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d{1,5})?/?$")
# (dotted key, label, type, help, extra). Types: str, int (min, max), bool, choice (options), list, url.
FIELDS = [
    ("linear.team", "Linear team key", "str", "Team /inbox reads, e.g. ACME.", None),
    ("linear.workspace", "Linear workspace slug", "slug", "From linear.app/<slug>/; used for issue links.", None),
    ("headroom.mode", "Headroom mode", "choice", "token compresses the whole conversation (saves more); cache "
                                                 "keeps earlier turns byte-identical for prompt caching.",
     ("token", "cache")),
    ("headroom.port", "Headroom port", "int", "Local proxy port (restart Claude Code after changing).",
     (1024, 65535)),
    ("ui.port", "Dashboard port", "int", "Used the next time you run lfg ui.", (1024, 65535)),
    ("replies.lfg_tag", "Say whether LFG was used", "bool", "In LFG repos, Claude starts each reply with the LFG "
                                                           "skill or tools it used, or why it didn't use LFG.", None),
    ("storage.limit_mb", "Disk space limit (MB)", "int", "Above this, Settings → Disk space offers to delete old "
                                                          "branches' runs and unused graphs.", (50, 100000)),
    ("storage.idle_graph_days", "Unused graph age (days)", "int", "Graphs not synced for this long are offered "
                                                                   "for deletion; they rebuild on the next session.",
     (1, 3650)),
    ("lanes.express_max_files", "Express: max files", "int", "Larger changes leave the Express lane.", (1, 100)),
    ("lanes.express_max_lines", "Express: max changed lines", "int", "", (1, 5000)),
    ("lanes.full_impact_nodes", "Full lane: impact radius", "int", "Graph nodes affected before a change is Full.",
     (1, 10000)),
    ("graphs.docs", "Generate graph docs", "bool", "Wiki, call-flow and playbooks after each sync.", None),
    ("graphs.sync_timeout_s", "Graph sync timeout (s)", "int", "", (60, 7200)),
    ("pentest.model", "Pentest model (Ollama)", "str", "A local Ollama model with tool calling.", None),
    ("pentest.ollama_url", "Ollama URL", "url", "Local only: http://127.0.0.1 or localhost.", None),
    ("pentest.max_turns", "Pentest max turns", "int", "", (1, 500)),
    ("secure.company_domains", "Company domains", "list", "Comma separated; never sent to vuln-intel APIs.", None),
    ("secure.private_scopes", "Private package scopes", "list", "Comma separated, e.g. @acme.", None),
    ("shipcheck.memory", "Ship check container memory", "str", "Docker --memory, e.g. 1g.", None),
    ("shipcheck.cpus", "Ship check container CPUs", "str", "Docker --cpus, e.g. 1.5.", None),
    ("shipcheck.health_timeout_s", "Ship check health timeout (s)", "int", "", (5, 1800)),
    ("shipcheck.prune_build_cache", "Ship check: prune Docker build cache", "bool", "After each ship check, delete "
     "the build cache it made (slower next build, less disk).", None),
    ("sonarqube.telemetry", "SonarQube: share usage stats with SonarSource", "bool", "Off keeps SonarQube fully "
     "local: no usage statistics and no update checks. Applying a change restarts SonarQube; your login and "
     "results are kept.", None),
    ("guard.allow_commits", "Let Claude commit when I ask", "bool", "Commits become an approval prompt instead of "
     "a block. Pushing, merging, rebasing, PRs, secrets and deploys stay blocked.", None),
    ("dictate.shortcut", "Dictate shortcut", "choice", "Hold to talk, double-tap for hands-free.",
     ("option+space", "right_option", "fn", "ctrl+space", "cmd+shift+space")),
    ("dictate.insert", "Dictate: put text in by", "choice", "paste (fast) or type (for apps that block pasting). "
     "Either way the text also stays on your clipboard.", ("paste", "type")),
    ("dictate.cleanup", "Dictate: clean up with Claude", "bool", "Removes filler words and fixes punctuation. Sends "
     "the text (never audio) to Claude. On by default; off keeps everything on this Mac.", None),
] + [("models.%s" % a, "Model: %s" % a, "choice", "", MODELS) for a in C.DEFAULT_CONFIG["models"]]


def _get(d, dotted):
    for k in dotted.split("."):
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _set(d, dotted, value):
    ks = dotted.split(".")
    for k in ks[:-1]:
        d = d.setdefault(k, {})
    d[ks[-1]] = value


def _coerce(field, raw):
    key, label, typ, _help, extra = field
    if typ == "bool":
        if isinstance(raw, bool):
            return raw
        raise Invalid("%s must be true or false" % label)
    if typ == "int":
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise Invalid("%s must be a whole number" % label) from None
        if not extra[0] <= v <= extra[1]:
            raise Invalid("%s must be between %d and %d" % (label, extra[0], extra[1]))
        return v
    if typ == "list":
        items = raw if isinstance(raw, list) else str(raw or "").split(",")
        items = [str(x).strip() for x in items if str(x).strip()]
        if any(not re.match(r"^[A-Za-z0-9@._/*-]{1,200}$", x) for x in items):
            raise Invalid("%s: use names like example.com or @scope, separated by commas" % label)
        return items
    v = str(raw if raw is not None else "").strip()
    if len(v) > 200 or "\n" in v:
        raise Invalid("%s is too long" % label)
    if typ == "choice" and v not in extra:
        raise Invalid("%s must be one of %s" % (label, ", ".join(extra)))
    if typ == "slug" and v and not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", v):
        raise Invalid("%s: lowercase letters, digits and dashes only (the part after linear.app/)" % label)
    if typ == "url" and not LOOPBACK_URL.match(v):
        raise Invalid("%s must be a local URL (http://127.0.0.1:<port>); pentests never use remote models" % label)
    return v


# Which integration (pack) a setting belongs to: it shows on that integration's card, not in Settings → General.
FIELD_OWNER = {"linear.": "linear", "headroom.": "headroom", "graphs.": "core", "pentest.": "pentest",
               "secure.": "security", "shipcheck.": "shipcheck", "dictate.": "dictate", "sonarqube.": "sonarqube"}


def field_owner(key):
    return next((v for k, v in FIELD_OWNER.items() if key.startswith(k)), None)


def config_view():
    cfg = C.config()
    return {"fields": [{"key": k, "label": lb, "type": t, "help": h, "owner": field_owner(k),
                        "options": list(x) if t == "choice" else None,
                        "min": x[0] if t == "int" else None, "max": x[1] if t == "int" else None,
                        "value": _get(cfg, k)} for k, lb, t, h, x in FIELDS],
            "path": C.lfg_path("config.json")}


def save_config(values):
    """Update only the given keys of ~/.lfg/config.json (unknown keys are refused). Returns what changed."""
    if not isinstance(values, dict):
        raise Invalid("expected an object of settings")
    by_key = {f[0]: f for f in FIELDS}
    unknown = sorted(set(values) - set(by_key))
    if unknown:
        raise Invalid("not editable here: %s" % ", ".join(unknown))
    clean = {k: _coerce(by_key[k], v) for k, v in values.items()}
    if _secret_kinds(repr(clean)):
        raise Invalid("a value looks like a secret; secrets never go in config.json")
    path = C.lfg_path("config.json")
    raw = C.read_json(path, {}) or {}
    if not isinstance(raw, dict):
        raise Invalid("%s is not valid JSON; fix it by hand first" % path)
    before = C.config()
    changed = [k for k, v in clean.items() if _get(before, k) != v]
    if not changed:
        return {"changed": [], "notes": []}
    _backup(path, "config")
    for k in changed:
        _set(raw, k, clean[k])
    C.write_json(path, raw)
    notes = []
    if "headroom.mode" in changed or "headroom.port" in changed:
        from . import headroom as HR
        if HR._agent_loaded():
            if "headroom.port" in changed:
                notes.append("Headroom port changed: run `lfg headroom setup` so Claude Code uses the new port.")
            else:
                notes.append("Headroom restarted in %s mode." % HR.mode() if HR.restart()
                             else "Headroom restart failed: run `lfg headroom restart`.")
    if any(k.startswith("dictate.") for k in changed):
        from . import dictate as DI
        if DI.restart():
            notes.append("Dictate restarted with the new settings.")
        if "dictate.shortcut" in changed and DI.conflicts(clean["dictate.shortcut"]):
            alt = DI.suggestion(clean["dictate.shortcut"])
            notes.append("%s may also use that shortcut%s." % (", ".join(DI.conflicts(clean["dictate.shortcut"])),
                                                              "; try %s" % DI.SHORTCUTS[alt]["label"] if alt else ""))
    if "ui.port" in changed:
        notes.append("The new dashboard port applies the next time you run `lfg ui`.")
    return {"changed": changed, "notes": notes}


# ---------------------------------------------------------------- skills

SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
MAX_DOC = 400_000


def _plugin_skill(name):
    return os.path.join(C.PLUGIN_DIR, "skills", name, "SKILL.md")


def _override(name):
    return C.lfg_path("overrides", "skills", name, "SKILL.md")


def _default(name):
    p = C.lfg_path("defaults", "skills", name, "SKILL.md")
    return p if os.path.isfile(p) else _plugin_skill(name)


def _check_name(name):
    if not SKILL_NAME.match(name or "") or not os.path.isfile(_plugin_skill(name)):
        raise Invalid("unknown skill %r" % name)


def skills():
    out = []
    for p in sorted(glob.glob(os.path.join(C.PLUGIN_DIR, "skills", "*", "SKILL.md"))):
        name = os.path.basename(os.path.dirname(p))
        desc = re.search(r"^description:\s*>?\s*\n?((?:[ \t]+.*\n?)+|.*)$", C.read_text(p), re.M)
        out.append({"name": name, "edited": os.path.isfile(_override(name)),
                    "description": " ".join((desc.group(1) if desc else "").split())[:300]})
    return {"skills": out, "path": os.path.join(C.PLUGIN_DIR, "skills")}


def skill(name):
    _check_name(name)
    edited = os.path.isfile(_override(name))
    return {"name": name, "text": C.read_text(_plugin_skill(name)), "edited": edited,
            "default": C.read_text(_default(name)) if edited else None}


def _install_skill(name, text):
    """Claude Code loads the plugin in place from LFG's local marketplace (~/.lfg/plugin), so writing the file there
    is all it takes: new sessions (or /reload-plugins) pick it up. Nothing in Claude Code's own folders is touched."""
    C.write_text(_plugin_skill(name), text, mode=0o644)


def save_skill(name, text):
    _check_name(name)
    text = (text or "").replace("\r\n", "\n")
    if not text.strip() or len(text) > MAX_DOC:
        raise Invalid("the skill is empty or too large")
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not fm or not re.search(r"^name:\s*%s\s*$" % re.escape(name), fm.group(1), re.M) \
            or not re.search(r"^description:", fm.group(1), re.M):
        raise Invalid("keep the front matter: it must start with --- and include `name: %s` and a description"
                      % name)
    kinds = _secret_kinds(text)
    if kinds:
        raise Invalid("the text looks like it contains a secret (%s); not saved" % ", ".join(kinds))
    _backup(_plugin_skill(name), "skills-" + name)
    C.write_text(_override(name), text, mode=0o600)
    _install_skill(name, text)
    return {"saved": name, "note": "Saved. New Claude Code sessions (or /reload-plugins) use it; updates keep your "
                                   "edit."}


def reset_skill(name):
    _check_name(name)
    default = C.read_text(_default(name))
    if os.path.isfile(_override(name)):
        os.remove(_override(name))
    if default.strip():
        _install_skill(name, default)
    return {"reset": name}


# ---------------------------------------------------------------- rules

RULE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
MAX_RULE = 40_000


def _plugin_rule(name):
    return os.path.join(C.PLUGIN_DIR, "rules", name + ".md")


def _rule_override(name):
    return C.lfg_path("overrides", "rules", name + ".md")


def rule_text(name):
    """What `lfg rule <name>` prints: your version if you changed or added it, else the shipped one."""
    for p in (_rule_override(name), _plugin_rule(name)):
        if RULE_NAME.match(name or "") and os.path.isfile(p):
            return C.read_text(p)
    return None


def rule_names():
    names = set()
    for d in (os.path.join(C.PLUGIN_DIR, "rules"), C.lfg_path("overrides", "rules")):
        names.update(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(d, "*.md")))
    return sorted(n for n in names if RULE_NAME.match(n))


def own_rules():
    """Rules the user added (no shipped file of that name)."""
    return [n for n in rule_names() if not os.path.isfile(_plugin_rule(n))]


def _rule_summary(text):
    h1 = re.search(r"^# [^:\n]+:\s*(.+)$", text, re.M)  # "# name: summary", else the first sentence after it
    lead = re.search(r"^# .*\n+([^#\n].*)$", text, re.M)
    first = re.search(r"^\s*([^#\s-].*)$", text, re.M)
    lead = lead or first
    return (h1.group(1) if h1 else (re.split(r"(?<=\.)\s", lead.group(1))[0] if lead else "")).strip()


def rules():
    """The numbered standing rules the guard enforces (read-only), and the rule modules agents load with
    `lfg rule <name>` (shipped ones can be changed, and you can add your own)."""
    from . import guard
    out = [{"id": k, "title": t, "summary": w, "enforced_by": e} for k, (t, w, e) in guard.RULES.items()]
    mods = []
    for name in rule_names():
        text = rule_text(name) or ""
        shipped = os.path.isfile(_plugin_rule(name))
        edited = os.path.isfile(_rule_override(name))
        mods.append({"name": name, "summary": _rule_summary(text), "text": text, "yours": not shipped,
                     "edited": shipped and edited,
                     "default": C.read_text(_plugin_rule(name)) if shipped and edited else None})
    return {"rules": out, "modules": mods}


def save_rule(name, text):
    name = (name or "").strip().lower()
    if not RULE_NAME.match(name):
        raise Invalid("use a short name of lowercase letters, numbers and dashes, like `api-style`")
    text = (text or "").replace("\r\n", "\n")
    if not text.strip() or len(text) > MAX_RULE:
        raise Invalid("the rule is empty or too large (max %d characters)" % MAX_RULE)
    kinds = _secret_kinds(text)
    if kinds:
        raise Invalid("the text looks like it contains a secret (%s); not saved" % ", ".join(kinds))
    p = _rule_override(name)
    _backup(p, "rules-" + name)
    C.write_text(p, text if text.endswith("\n") else text + "\n", mode=0o600)
    new = not os.path.isfile(_plugin_rule(name))
    return {"saved": name, "note": "Saved. Agents read it with `lfg rule %s`%s." % (
        name, "; new Claude Code sessions are told about it at start" if new else "")}


def reset_rule(name):
    """Undo your change to a shipped rule, or delete a rule you added (a backup is kept either way)."""
    if not RULE_NAME.match(name or "") or not os.path.isfile(_rule_override(name)):
        raise Invalid("nothing to undo for rule %r" % name)
    _backup(_rule_override(name), "rules-" + name)
    os.remove(_rule_override(name))
    return {"reset": name, "deleted": not os.path.isfile(_plugin_rule(name))}


# ---------------------------------------------------------------- storage (~/.lfg disk use)

def _du(path):
    """Bytes under path (symlinks are not followed)."""
    if os.path.islink(path) or not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _mb(n):
    return round(n / 1048576, 1)


def _repo_paths(rid):
    """Everything LFG keeps for one repo."""
    return [C.lfg_path(*p) for p in (("graphs", rid), ("runs", rid), ("repos", rid), ("playbooks", rid),
                                     ("feedback", rid + ".json"), ("ui", "static", "arch-health", rid + ".html"))]


def _repo_graph_dirs(rid):
    """The repo's own graph data dirs (`.code-review-graph/`, `graphify-out/` in its main checkout) that exist."""
    from . import graphs as G
    return [d for d in (G.data_dir(rid, k) for k in G.DATA) if d and os.path.isdir(d)]


def _name(rid):
    """A project's folder name (`billing-service`), not its id (`billing-service-939ccc54`)."""
    root = (C.read_json(C.lfg_path("graphs", rid, "state.json"), {}) or {}).get("repo_root") or ""
    return os.path.basename(root.rstrip("/")) or re.sub(r"-[0-9a-f]{8}$", "", rid)


def _candidates():
    """What can be deleted safely, with the exact paths. Never the current run, a checked-out branch's runs, or
    anything outside ~/.lfg except a repo's own graph data dirs. Recomputed on every cleanup, so the browser only
    ever names candidate ids."""
    from . import dash
    cfg = C.config()["storage"]
    idle = cfg["idle_graph_days"] * 86400
    out = []
    for rid in dash.repo_ids():
        root = dash.repo_root(rid)
        if not root or not os.path.isdir(root):
            paths = [p for p in _repo_paths(rid) if os.path.exists(p)]
            out.append({"id": "repo:" + rid, "kind": "repo", "repo": rid, "label": "Everything for %s" % _name(rid),
                        "reason": "its folder %s no longer exists" % (root or "(unknown)"), "paths": paths})
            continue
        current = os.path.basename(C.current_run(rid) or "")
        gb = dash.git_branches(root) or {}
        by_branch = {}
        for d in dash._run_files(rid, ""):
            b = dash.run_branch(d)
            if b and os.path.basename(d) != current:
                by_branch.setdefault(b, []).append(d)
        for b, dirs in sorted(by_branch.items()):
            if b == gb.get("current") or b == gb.get("default"):
                continue
            why = "merged into %s" % gb["default"] if b in gb.get("merged", ()) else \
                "branch deleted" if b not in gb.get("local", ()) else None
            if why:
                out.append({"id": "runs:%s:%s" % (rid, b), "kind": "runs", "repo": rid, "branch": b,
                            "label": "%d run(s) on %s" % (len(dirs), b), "reason": why, "paths": dirs})
        st = C.read_json(C.lfg_path("graphs", rid, "state.json"), {}) or {}
        gdir = C.lfg_path("graphs", rid)
        synced = os.path.getmtime(C.lfg_path("graphs", rid, "state.json")) if st else None
        if os.path.isdir(gdir) and synced is not None and time.time() - synced > idle:
            out.append({"id": "graphs:" + rid, "kind": "graphs", "repo": rid,
                        "label": "Graphs for %s (in the repo)" % _name(rid), "paths": [gdir] + _repo_graph_dirs(rid),
                        "reason": "not synced for %d+ days; rebuilt automatically next time you work in it"
                                  % cfg["idle_graph_days"]})
            continue
        from . import graphs as G
        views = [p for kind, pat in (("crg", "*.html"), ("crg", "*.js"), ("graphify", "graph.html"))
                 if G.data_dir(rid, kind) for p in glob.glob(os.path.join(G.data_dir(rid, kind), pat))
                 if os.path.isfile(p)]
        if sum(_du(p) for p in views) > 5 * 1048576:
            out.append({"id": "views:" + rid, "kind": "views", "repo": rid, "paths": views,
                        "label": "Graph visualisations for %s" % _name(rid),
                        "reason": "generated pages only; rebuilt the next time you open Code or Architecture graph"})
    for c in out:
        c["mb"] = _mb(sum(_du(p) for p in c["paths"]))
    return out


def storage():
    from . import dash
    parts = []
    for name in sorted(os.listdir(C.LFG_HOME)) if os.path.isdir(C.LFG_HOME) else []:
        size = _du(C.lfg_path(name))
        if size:
            parts.append({"name": name, "mb": _mb(size)})
    parts.sort(key=lambda p: -p["mb"])
    total = round(sum(p["mb"] for p in parts), 1)
    limit = C.config()["storage"]["limit_mb"]
    repos = [{"repo": rid, "root": dash.repo_root(rid), "graphs_mb": _mb(_du(C.lfg_path("graphs", rid))),
              "runs_mb": _mb(_du(C.lfg_path("runs", rid))),
              "repo_graphs_mb": _mb(sum(_du(d) for d in _repo_graph_dirs(rid)))} for rid in dash.repo_ids()]
    repos.sort(key=lambda r: -(r["repo_graphs_mb"] + r["graphs_mb"] + r["runs_mb"]))
    cands = [{k: v for k, v in c.items() if k != "paths"} for c in _candidates()]
    return {"path": C.LFG_HOME, "total_mb": total, "limit_mb": limit, "over": total > limit, "parts": parts,
            "repos": repos, "in_repos_mb": round(sum(r["repo_graphs_mb"] for r in repos), 1), "candidates": cands}


def cleanup(ids):
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise Invalid("pick at least one item to delete")
    cands = {c["id"]: c for c in _candidates()}
    unknown = [i for i in ids if i not in cands]
    if unknown:
        raise Invalid("not deletable (anymore): %s. Reload the page." % ", ".join(unknown))
    home = os.path.realpath(C.LFG_HOME) + os.sep
    from . import dash
    repo_graphs = {os.path.realpath(d) for rid in dash.repo_ids() for d in _repo_graph_dirs(rid)}
    freed = 0
    for i in ids:
        for p in cands[i]["paths"]:
            rp = os.path.realpath(p)
            in_graph = any(rp == g or rp.startswith(g + os.sep) for g in repo_graphs)
            if not in_graph and (not rp.startswith(home) or rp == home.rstrip(os.sep)):
                raise Invalid("refusing to delete outside %s and the repos' graph folders" % C.LFG_HOME)
            freed += _du(p)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            elif os.path.lexists(p):
                os.remove(p)
    C.audit("storage-cleanup", {"items": ids, "freed_mb": _mb(freed)})
    return {"ok": True, "freed_mb": _mb(freed), "note": "Freed %s MB." % _mb(freed)}


# ---------------------------------------------------------------- global CLAUDE.md

# Older LFG versions appended this marked block to ~/.claude/CLAUDE.md. LFG now gives the same guidance as session
# context, only in repos where it is on, so `lfg setup` offers to take an unedited block back out.
BEGIN = "<!-- lfg:begin (added by LFG; everything outside this block is yours and LFG never changes it) -->"
END = "<!-- lfg:end -->"
# sha256 of every block LFG ever shipped: a block still equal to one of them was not edited by you.
SHIPPED_SECTIONS = {"165878205f0d4cb747199bf84f3285db60aa271d7d16d08711ee3bd04a380f35",
                    "67bb15b151be026a1c9c5a842a2500185391c6c2b8bfa3b932f9e8f46bd279ce",
                    "e6795baa900927b258f400e963f46a7a6c74d5ea4e9a8d58789b9996ee2e6154",
                    "35381f3a525104dbe5a8029150abb1be670f54b3cbd68d9d2ee1cb9cf9fa4959"}


def claude_md_path():
    return os.path.join(C.HOME, ".claude", "CLAUDE.md")


def claude_md():
    p = claude_md_path()
    text = C.read_text(p)
    return {"path": p, "exists": os.path.isfile(p), "text": text, "has_lfg_section": BEGIN in text}


def save_claude_md(text):
    text = (text or "").replace("\r\n", "\n")
    if len(text) > MAX_DOC:
        raise Invalid("CLAUDE.md is too large")
    kinds = _secret_kinds(text)
    if kinds:
        raise Invalid("the text looks like it contains a secret (%s); not saved" % ", ".join(kinds))
    p = claude_md_path()
    _backup(p, "claude-md")
    C.ensure_dir(os.path.dirname(p), 0o755)
    C.write_text(p, text, mode=0o644)
    return {"saved": p, "note": "Saved (previous version backed up in ~/.lfg/backups/claude-md). New sessions "
                                "read it."}


def _legacy_block(text):
    head, _, rest = text.partition(BEGIN)
    body, sep, tail = rest.partition(END)
    return head, body, sep, tail


def legacy_section_edited():
    text = C.read_text(claude_md_path())
    if BEGIN not in text:
        return False
    body = _legacy_block(text)[1]
    return hashlib.sha256(body.strip().encode()).hexdigest() not in SHIPPED_SECTIONS


def remove_claude_md_section():
    """Remove the block an older LFG appended, only if you never edited it. Everything else stays byte for byte."""
    p = claude_md_path()
    text = C.read_text(p)
    if BEGIN not in text:
        return {"path": p, "removed": False}
    if legacy_section_edited():
        return {"path": p, "removed": False, "edited": True}
    head, _body, sep, tail = _legacy_block(text)
    if not sep:
        return {"path": p, "removed": False}
    _backup(p, "claude-md")
    new = head.rstrip("\n") + ("\n" if head.strip() else "") + tail.lstrip("\n")
    C.write_text(p, new, mode=0o644)
    return {"path": p, "removed": True}


# ---------------------------------------------------------------- local Ollama models (for /pentest)

# Local (not cloud) Ollama models with tool calling, which Strix needs. Sizes are the default q4 downloads
# listed on ollama.com/library (checked 2026-10-13); anything else can be pulled by name.
OLLAMA_CATALOG = [
    ("qwen3:8b", 5.2, "40K", "Qwen3 8B: the LFG default for 16 GB Macs."),
    ("qwen3:14b", 9.3, "40K", "Qwen3 14B: the LFG default for 24-32 GB Macs."),
    ("qwen3:32b", 20, "40K", "Qwen3 32B: the LFG default for 48 GB+ Macs."),
    ("qwen3.8:27b", 18, "256K", "Qwen3.8 27B: newer, strong at coding and long agentic tasks."),
    ("ornith:9b", 5.6, "256K", "Ornith 9B: open model for agentic coding."),
    ("ornith:35b", 21, "256K", "Ornith 35B: larger agentic-coding model."),
    ("granite4.1:8b", 5.3, "128K", "IBM Granite 4.1 8B: tool use and structured JSON, Apache 2.0."),
    ("granite4.1:30b", 17, "128K", "IBM Granite 4.1 30B."),
    ("muse-glimmer:30b", 18, "128K", "Meta Muse Glimmer 30B: tuned for tool use and long tasks, Apache 2.0."),
    ("nemotron-3.5-lightning:30b", 25, "1M", "NVIDIA Nemotron 3.5 Lightning: 30B MoE, 3B active."),
]
MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,80}(:[a-z0-9._-]{1,60})?$")
PULLS = {}  # name -> {"status", "completed", "total", "error", "done"}; lives in the `lfg ui` process


def _ollama_url():
    url = C.config()["pentest"]["ollama_url"]
    if not LOOPBACK_URL.match(url or ""):
        raise Invalid("pentest.ollama_url must be a local URL")
    return url.rstrip("/")


def _ollama_json(path, body=None, timeout=5):
    import json
    import urllib.request
    req = urllib.request.Request(_ollama_url() + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _ram_gb():
    try:
        return int(C.run(["sysctl", "-n", "hw.memsize"]).stdout.strip()) // (1 << 30)
    except ValueError:
        return 0


def _fit(size_gb, ram):
    if not ram:
        return ""
    return "fits" if size_gb <= ram * 0.6 else "tight" if size_gb <= ram * 0.85 else "too big"


def ollama_models():
    ram, current = _ram_gb(), C.config()["pentest"].get("model") or ""
    out = {"ram_gb": ram, "current": current, "url": C.config()["pentest"]["ollama_url"], "running": False,
           "installed": [], "pulls": dict(PULLS), "library": "https://ollama.com/search?c=tools"}
    try:
        tags = _ollama_json("/api/tags").get("models", [])
        out["running"] = True
    except Invalid as e:
        out["why"] = str(e)
        tags = []
    except Exception:
        out["why"] = "Ollama isn't running: open the Ollama app (or run `ollama serve`)."
        tags = []
    for m in tags:
        try:
            caps = _ollama_json("/api/show", {"model": m["name"]}).get("capabilities") or []
        except Exception:
            caps = []
        size = round((m.get("size") or 0) / 1e9, 1)
        out["installed"].append({"name": m["name"], "size_gb": size, "tools": "tools" in caps,
                                 "cloud": "cloud" in m["name"], "modified": m.get("modified_at", "")[:10],
                                 "params": (m.get("details") or {}).get("parameter_size", "")})
    have = {m["name"] for m in out["installed"]} | {m["name"].replace(":latest", "") for m in out["installed"]}
    out["catalog"] = [{"name": n, "size_gb": s, "context": ctx, "note": note, "fit": _fit(s, ram),
                       "installed": n in have} for n, s, ctx, note in OLLAMA_CATALOG]
    return out


def _pull_worker(name):
    import json
    import urllib.request
    st = PULLS[name]
    try:
        req = urllib.request.Request(_ollama_url() + "/api/pull", data=json.dumps({"model": name}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            for line in r:
                ev = json.loads(line.decode() or "{}")
                if ev.get("error"):
                    st["error"] = str(ev["error"])[:300]
                    break
                st["status"] = str(ev.get("status", ""))[:120]
                if ev.get("total"):
                    st["total"], st["completed"] = ev["total"], ev.get("completed", 0)
    except Exception as e:
        st["error"] = "pull failed (%s)" % type(e).__name__
    st["done"] = True
    C.audit("ollama-pull", {"model": name, "ok": not st.get("error")})


def pull_model(name):
    """Start `ollama pull` for a local model through the local Ollama API (never a cloud model)."""
    import threading
    name = (name or "").strip()
    if not MODEL_NAME.match(name):
        raise Invalid("not a model name (e.g. qwen3:14b)")
    if "cloud" in name:
        raise Invalid("cloud models are not allowed: pentests only use local models")
    if name in PULLS and not PULLS[name].get("done"):
        return {"pulling": name}
    _ollama_url()  # refuses a non-local URL
    try:
        _ollama_json("/api/version")
    except Exception:
        raise Invalid("Ollama isn't running: open the Ollama app first") from None
    PULLS[name] = {"status": "starting", "completed": 0, "total": 0, "error": "", "done": False}
    threading.Thread(target=_pull_worker, args=(name,), daemon=True).start()
    return {"pulling": name, "note": "Downloading %s from the Ollama library in the background." % name}
