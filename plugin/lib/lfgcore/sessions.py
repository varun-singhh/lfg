"""Every Claude Code session on this machine, whatever folder it was started in.

Claude Code keeps a session under the folder it started in, so `/resume` only lists that folder's sessions. This reads
all of them from ~/.claude/projects, works out each one's repo, worktree, branch, ticket and a name, and gives the
command that resumes it from the right folder. Names and folders you set are kept in ~/.lfg/state/sessions.json; the
transcripts themselves are only ever read.
"""
import calendar
import glob
import json
import os
import re
import shlex
import time

from . import common as C

PROJECTS = os.path.join(C.HOME, ".claude", "projects")
TICKET = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")
NOT_TICKETS = {"UTF-8", "SHA-1", "SHA-256", "ISO-8601", "HTTP-2"}
# Head and tail are enough for everything but the first prompt; big transcripts aren't read whole.
HEAD, TAIL = 256 * 1024, 512 * 1024


def _index_path():
    return C.lfg_path("state", "sessions-index.json")


def _prefs_path():
    return C.lfg_path("state", "sessions.json")


def prefs():
    p = C.read_json(_prefs_path(), {}) or {}
    return {"names": dict(p.get("names") or {}), "folders": dict(p.get("folders") or {}),
            "hidden": list(p.get("hidden") or []), "starred": list(p.get("starred") or []),
            # a group can follow PRs ("owner/repo#12"): every session that mentions one joins it, unless taken out
            "group_prs": dict(p.get("group_prs") or {}), "left_out": dict(p.get("left_out") or {}),
            # groups that exist on purpose (even empty), {child: parent} for nesting, tickets a group follows,
            # labels per session id, and the colour of each label (by lower-case name)
            "groups": list(p.get("groups") or []), "group_parent": dict(p.get("group_parent") or {}),
            "group_tickets": dict(p.get("group_tickets") or {}), "labels": dict(p.get("labels") or {}),
            "label_colors": dict(p.get("label_colors") or {})}


def _save_prefs(p):
    C.ensure_dir(os.path.dirname(_prefs_path()))
    C.write_json(_prefs_path(), p)


def _chunks(path, size):
    with open(path, "rb") as fh:
        if size <= HEAD + TAIL:
            return [fh.read()]
        head = fh.read(HEAD)
        fh.seek(size - TAIL)
        return [head, fh.read()]


def _prompt_text(content):
    if isinstance(content, str):
        return content
    for part in content or []:
        if isinstance(part, dict) and part.get("type") == "text":
            return part.get("text") or ""
    return ""


CMD = re.compile(r"<command-name>\s*(/?[^<]+?)\s*</command-name>")
CMD_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
BASH_IN = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)
QUIET_CMDS = ("/rename", "/color", "/clear", "/compact", "/model", "/config", "/status", "/cost", "/help", "/exit")
PASTED = re.compile(r"<pasted_content[^>]*>(.*?)(?:</pasted_content[^>]*>|$)", re.S)


def _prompt_of(text):
    """What you typed, as you'd recognize it: a message, a slash command with its arguments ("/review-pr 1759"), or a
    `!` shell command. None for what Claude Code adds itself (command output, caveats, interrupts). Pasted text
    counts as typed, without its wrapper: a session can be nothing but pastes."""
    t = PASTED.sub(lambda m: m.group(1).strip(), (text or "")).strip()
    if not t or t.startswith(("[Request interrupted", "Caveat:", "<local-command", "<bash-stdout", "<bash-stderr",
                              "<task-notification", "<system-reminder")):
        return None
    m = CMD.search(t)
    if m:
        name = m.group(1) if m.group(1).startswith("/") else "/" + m.group(1)
        if name in QUIET_CMDS:
            return None
        a = CMD_ARGS.search(t)
        return (name + " " + (a.group(1).strip() if a else "")).strip()
    m = BASH_IN.search(t)
    if m:
        return "! " + m.group(1).strip()
    return None if t.startswith("<") else t


def parse(path):
    """One transcript's facts. Unreadable lines are skipped: transcripts are written while sessions run."""
    st = os.stat(path)
    out = {"id": os.path.basename(path)[:-6], "path": path, "size": st.st_size, "mtime": st.st_mtime,
           "cwd": "", "branch": "", "title": "", "ai_title": "", "first": "", "last": "", "started": "", "ended": "",
           "prompts": 0, "cost": None, "sidechain_only": True, "entrypoint": "", "worked_in": ""}
    for chunk in _chunks(path, st.st_size):
        for ln in chunk.splitlines():
            if not ln.startswith(b"{"):
                continue  # a line cut by the head/tail split
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "custom-title":
                out["title"] = ev.get("customTitle") or out["title"]
            elif t == "ai-title":
                out["ai_title"] = ev.get("aiTitle") or out["ai_title"]
            elif t == "last-prompt":
                out["last"] = ev.get("lastPrompt") or out["last"]
            elif t == "cost-state":
                out["cost"] = ev.get("totalCostUSD", out["cost"])
            if t not in ("user", "assistant"):
                continue
            if not ev.get("isSidechain"):
                out["sidechain_only"] = False
            out["cwd"] = out["cwd"] or ev.get("cwd") or ""
            out["entrypoint"] = out["entrypoint"] or ev.get("entrypoint") or ""
            out["branch"] = ev.get("gitBranch") or out["branch"]
            # a session started in the main checkout that works in a worktree: the last one it used
            if t == "assistant":
                for part in (ev.get("message") or {}).get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "tool_use":
                        for m in WORKTREE_PATH.finditer(json.dumps(part.get("input") or {})):
                            out["worked_in"] = m.group(1)
            ts = ev.get("timestamp") or ""
            out["started"] = out["started"] or ts
            out["ended"] = ts or out["ended"]
            if t == "user" and not ev.get("isMeta") and not ev.get("isSidechain"):
                text = _prompt_of(_prompt_text((ev.get("message") or {}).get("content")))
                if text:
                    out["prompts"] += 1
                    out["first"] = out["first"] or text[:300]
    return out


def _load_index():
    d = C.read_json(_index_path(), {}) or {}
    return d if d.get("v") == 5 else {"v": 5, "sessions": {}}


def scan():
    """Every session, parsing only transcripts that changed since last time."""
    idx = _load_index()
    old, new, changed = idx["sessions"], {}, False
    for p in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        try:
            st = os.stat(p)
        except OSError:
            continue
        hit = old.get(p)
        if hit and hit["size"] == st.st_size and hit["mtime"] == st.st_mtime:
            new[p] = hit
            continue
        try:
            new[p] = parse(p)
            changed = True
        except OSError:
            continue
    if changed or len(new) != len(old):
        C.ensure_dir(os.path.dirname(_index_path()))
        C.write_json(_index_path(), {"v": 5, "sessions": new})
    return [s for s in new.values() if not s["sidechain_only"] and s["prompts"]]


def _ticket(branch, *texts):
    """A Linear-style id: from the branch first (any case, as in `lee/ato-3574-fix`), then from titles and the first
    prompt (upper case only, so prose like "gpt-4" doesn't count)."""
    for m in re.findall(r"(?:^|[/_-])([a-z][a-z0-9]{1,9}-\d{1,6})(?=$|[/_-])", branch or "", re.I):
        if m.upper() not in NOT_TICKETS:
            return m.upper()
    for t in texts:
        for m in TICKET.findall(t or ""):
            if m not in NOT_TICKETS:
                return m
    return ""


# <parent>/<repo>.worktrees/<name>, where `lfg worktree new` puts worktrees
WORKTREE_PATH = re.compile(r"(/[^\s\"'`;|&]+?\.worktrees/[^/\s\"'`;|&]+)")


def _where(cwd):
    """(repo name, main checkout, worktree name or "") for a session's folder."""
    if not cwd:
        return "", "", ""
    root = C.git_main_root_fast(cwd) if os.path.isdir(cwd) else None
    if not root:  # folder gone (a removed worktree) or not a repo: guess from the path
        m = re.match(r"^(.*?)/([^/]+)\.worktrees/([^/]+)", cwd)
        if m:
            return m.group(2), os.path.join(m.group(1), m.group(2)), m.group(3)
        return os.path.basename(cwd.rstrip("/")) or cwd, "", ""
    wt = "" if os.path.realpath(cwd) == os.path.realpath(root) else os.path.basename(cwd.rstrip("/"))
    return os.path.basename(root), root, wt


def name_for(s, own=""):
    """Your name for it, else the /rename title, else the ticket and what the session was about, else the branch,
    else Claude Code's own title, else the first thing you asked."""
    run = REVIEW_RUN.search(s["first"] or "")
    about = "Review run from the dashboard · " + run.group(1) if run else s["ai_title"] or s["first"][:70]
    if own or s["title"]:
        return own or s["title"]
    if s["ticket"]:
        return "%s · %s" % (s["ticket"], about) if about else s["ticket"]
    if s["branch"] and s["branch"] not in ("main", "master", "HEAD", "qa", "prod", "dev"):
        return "%s · %s" % (s["branch"], about) if about else s["branch"]
    return about or "(untitled)"


def resume_command(s):
    return "cd %s && claude --resume %s" % (shlex.quote(s["cwd"] or C.HOME), s["id"])


_MENTIONS = {}  # transcript path -> (size, mtime, {pr: mentions it?})


def _following(group_prs):
    """{session id: group} for sessions that mention a PR a group follows; the first group listed wins."""
    from . import review as R
    want = [(g, pr) for g, prs in sorted(group_prs.items()) for pr in prs]
    out = {}
    if not want:
        return out
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        try:
            st = os.stat(path)
        except OSError:
            continue
        size, mtime, seen = _MENTIONS.get(path, (None, None, {}))
        if (size, mtime) != (st.st_size, st.st_mtime):
            seen = {}
        todo = [pr for _, pr in want if pr not in seen]
        if todo:
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
            except OSError:
                continue
            for pr in todo:
                repo, _, n = pr.partition("#")
                seen[pr] = R.mentions(raw, repo, int(n))
            _MENTIONS[path] = (st.st_size, st.st_mtime, seen)
        sid = os.path.basename(path)[:-6]
        for g, pr in want:
            if seen.get(pr) and sid not in out:
                out[sid] = g
    return out


def _group_set(p):
    """Every group that exists: listed on purpose, or with a member, a child, a followed PR or a followed ticket."""
    return (set(p["groups"]) | set(p["folders"]) | set(p["group_prs"]) | set(p["group_tickets"])
            | set(p["group_parent"]) | set(p["group_parent"].values())) - {""}


def group_names():
    """Every group's name, as listing() gives them, without reading a single transcript."""
    return sorted(_group_set(prefs()))


def group_info():
    """{group: {"parent", "prs", "tickets"}} for every group that exists."""
    p = prefs()
    return {g: {"parent": p["group_parent"].get(g, ""), "prs": list(p["group_prs"].get(g, [])),
                "tickets": list(p["group_tickets"].get(g, []))} for g in sorted(_group_set(p))}


def listing(days=None, scripted=False, hidden=False, only=None, loose=False):
    """Sessions newest first, each with repo, ticket, group, name, folder and the resume command. Sessions started
    by a script (`claude -p`, e.g. the dashboard's review runs) are left out unless `scripted`. `only`: a main
    checkout; keeps the sessions that ran in it or one of its worktrees. `loose`: only the sessions started outside
    any git repo (your home folder, ~/code, a scratch folder), whatever `only` says. `loose_count` counts those."""
    p = prefs()
    want = os.path.realpath(only) if only else ""
    scanned = scan()
    placed = placements(scanned)
    starred = set(p["starred"])
    hid = set(p["hidden"])
    cut = time.time() - days * 86400 if days else 0
    rows, loose_count = [], 0
    for s in scanned:
        # a script's session (`claude -p`, e.g. a dashboard review run) shows when it joined a group through its PR
        by_pr = placed.get(s["id"], {}).get("via") == "pr"
        if s["mtime"] < cut or (s["entrypoint"] == "sdk-cli" and not scripted and not by_pr) or \
                (s["id"] in hid and not hidden):
            continue
        repo, root, wt = _where(s["cwd"])
        if not wt and s.get("worked_in"):
            _, w_root, wt = _where(s["worked_in"])
            if root and w_root and os.path.realpath(w_root) != os.path.realpath(root):
                wt = ""  # a worktree of another repo: not where this session's own work is
        loose_count += not root
        if loose and root or not loose and want and (not root or os.path.realpath(root) != want):
            continue
        r = dict(s, repo=repo, root=root, worktree=wt, loose=not root,
                 ticket=_ticket(s["branch"], s["title"], s["ai_title"], s["first"]),
                 folder_exists=bool(s["cwd"]) and os.path.isdir(s["cwd"]),
                 app="desktop" if s["entrypoint"] == "claude-desktop" else "")
        r["name"] = name_for(r, p["names"].get(s["id"], ""))
        r["auto_name"] = name_for(r)
        r["named"] = bool(p["names"].get(s["id"]) or s["title"])
        where = placed.get(s["id"], {"folder": "", "via": ""})
        r["folder"] = where["folder"]
        r["via_pr"] = where["via"] == "pr"
        r["via_ticket"] = where["via"] == "ticket"
        r["labels"] = [{"name": n, "color": p["label_colors"].get(n.lower(), "gray")}
                       for n in p["labels"].get(s["id"], [])]
        r["starred"] = s["id"] in starred
        r["hidden"] = s["id"] in hid
        r["group"] = r["folder"] or r["ticket"] or (r["branch"] if r["branch"] not in ("", "HEAD") else "") \
            or ("(no branch)" if r["root"] else "Not in a repo")
        r["resume"] = resume_command(r)
        r["modified"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(s["mtime"]))
        for k in ("path", "size", "mtime", "sidechain_only"):
            r.pop(k, None)
        rows.append(r)
    rows.sort(key=lambda r: r["modified"], reverse=True)
    return {"sessions": rows, "folders": group_names(), "group_prs": p["group_prs"],
            "label_list": label_list({s["id"] for s in scanned}), "group_info": group_info(),
            "projects_dir": PROJECTS, "hidden_count": len(hid), "loose_count": loose_count}


def _known(sid):
    if not re.match(r"^[0-9a-f-]{36}$", str(sid or "")):
        raise ValueError("not a session id: %r" % sid)
    if not glob.glob(os.path.join(PROJECTS, "*", sid + ".jsonl")):
        raise ValueError("no session %s on this machine" % sid)
    return sid


def recent(sid, n=4):
    """The last n turns of a session, oldest first, so you can tell which chat it is: what you typed and the start of
    what Claude wrote back. Read on demand from the transcript; nothing is indexed."""
    sid = _known(sid)
    path = glob.glob(os.path.join(PROJECTS, "*", sid + ".jsonl"))[0]
    turns = []
    with open(path, "rb") as fh:
        for ln in fh:
            if b'"user"' not in ln and b'"assistant"' not in ln:
                continue
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if ev.get("type") not in ("user", "assistant") or ev.get("isMeta") or ev.get("isSidechain"):
                continue
            content = (ev.get("message") or {}).get("content")
            text = _prompt_text(content)
            if ev.get("type") == "assistant":  # its own words, not reminders Claude Code put in the same message
                text = next((x.get("text") or "" for x in content if isinstance(x, dict) and x.get("type") == "text"
                             and not (x.get("text") or "").lstrip().startswith("<")), "") \
                    if isinstance(content, list) else text
            if ev.get("type") == "user":
                said = _prompt_of(text)
                if said:
                    turns.append({"who": "you", "text": said[:400], "at": ev.get("timestamp") or ""})
            elif text.strip() and turns and turns[-1]["who"] == "you":  # Claude's first words after your message
                turns.append({"who": "claude", "text": text.strip()[:400], "at": ev.get("timestamp") or ""})
            turns = turns[-2 * n:]
    return {"id": sid, "turns": turns}


SLASH = re.compile(r"<command-name>/?([\w:.-]+)</command-name>")
BUILTIN_SLASH = {"clear", "compact", "model", "usage", "cost", "config", "resume", "rename", "color", "help", "login",
                 "logout", "exit", "status", "context", "memory", "permissions", "hooks", "mcp", "plugin", "agents",
                 "reload-plugins", "fast", "effort", "doctor", "ide", "init", "add-dir", "export", "vim", "theme"}


LFG_CMD = re.compile(r"^\s*(?:\S*/)?lfg\s+([a-z][\w-]*)(?:\s+([a-z][\w-]*))?")


def used(path):
    """What a session or review log used: the models, skills (by the Skill tool or a slash command), subagents, MCP
    servers and claude.ai connectors, the plugins those came from, Claude Code's own tools and the `lfg` commands it
    ran, each with a count.
    Works on a transcript and on a `claude -p` stream-json log alike; read on demand, nothing is indexed."""
    models, skills, agents, mcp, tools, lfg = {}, {}, {}, {}, {}, {}

    def bump(d, k, **extra):
        d.setdefault(k, dict(extra, name=k, count=0))["count"] += 1

    try:
        fh = open(path, "rb")
    except OSError:
        return None
    with fh:
        for ln in fh:
            if b"tool_use" not in ln and b'"model"' not in ln and b"command-name" not in ln:
                continue
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            m = msg.get("model") or (ev.get("model") if ev.get("subtype") == "init" else None)
            if ev.get("type") == "assistant" and m and m != "<synthetic>":
                models[m] = models.get(m, 0) + 1
            content = msg.get("content")
            if ev.get("type") == "user":
                for name in SLASH.findall(content if isinstance(content, str) else _prompt_text(content) or ""):
                    if name not in BUILTIN_SLASH:
                        bump(skills, name, plugin=name.split(":")[0] if ":" in name else "")
                continue
            for b in content if ev.get("type") == "assistant" and isinstance(content, list) else []:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                name, inp = str(b.get("name") or ""), b.get("input") if isinstance(b.get("input"), dict) else {}
                if name == "Skill" and inp.get("skill"):
                    sk = str(inp["skill"]).lstrip("/")
                    bump(skills, sk, plugin=sk.split(":")[0] if ":" in sk else "")
                elif name in ("Task", "Agent"):
                    ag = str(inp.get("subagent_type") or "general-purpose")
                    bump(agents, ag, plugin=ag.split(":")[0] if ":" in ag else "")
                elif name.startswith("mcp__"):
                    server = name.split("__")[1] if name.count("__") >= 2 else name[5:]
                    if server.startswith("plugin_") and server.count("_") >= 2:
                        _, plugin, server = server.split("_", 2)
                        bump(mcp, server, kind="plugin", plugin=plugin)
                    elif server.startswith("claude_ai_"):
                        bump(mcp, server[10:].replace("_", " "), kind="connector", plugin="")
                    else:
                        bump(mcp, server, kind="server", plugin="")
                elif name:
                    bump(tools, name)
                    cm = LFG_CMD.match(str(inp.get("command") or "")) if name == "Bash" else None
                    if cm:
                        bump(lfg, " ".join(x for x in cm.groups() if x))
    by_count = lambda d: sorted(d.values(), key=lambda x: (-x["count"], x["name"]))  # noqa: E731
    plugins = sorted({x["plugin"] for d in (skills, agents, mcp) for x in d.values() if x.get("plugin")})
    return {"models": [k for k, _ in sorted(models.items(), key=lambda kv: -kv[1])], "skills": by_count(skills),
            "agents": by_count(agents), "mcp": by_count(mcp), "plugins": plugins, "tools": by_count(tools),
            "lfg": by_count(lfg)}


def usage_of(sid):
    """used() for a session on this machine, by its id."""
    return dict(used(glob.glob(os.path.join(PROJECTS, "*", _known(sid) + ".jsonl"))[0]) or {}, id=sid)


def star(sid, on=True):
    """Star a session you still care about: starred ones come first in their group, and are never folded away."""
    sid, p = _known(sid), prefs()
    p["starred"] = sorted(set(p["starred"]) | {sid} if on else set(p["starred"]) - {sid})
    _save_prefs(p)
    return {"id": sid, "starred": bool(on)}


PR_KEY = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)$")


def follow_pr(group, pr, on=True):
    """Have a group follow a PR: every session that mentions it joins the group (dashboard review runs included).
    off: stop following it; sessions that joined only through it go back where they were."""
    group, pr = _group_name(group), str(pr or "").strip()
    if len(group) < 2:
        raise ValueError("give the group a name of at least 2 characters")
    if not PR_KEY.match(pr):
        raise ValueError("not a PR: %r (owner/repo#12)" % pr)
    p = prefs()
    prs = [x for x in p["group_prs"].get(group, []) if x != pr] + ([pr] if on else [])
    if prs:
        p["group_prs"][group] = prs
    else:
        p["group_prs"].pop(group, None)
        if not p["group_tickets"].get(group):
            p["left_out"].pop(group, None)
    _save_prefs(p)
    return {"group": group, "prs": prs}


def follow_ticket(group, ticket, on=True):
    """Have a group follow a ticket (ATO-7): every session whose branch, title or first message names it joins the
    group, unless it was filed by hand or taken out. off: stop following it."""
    group, ticket = _valid_group(group), str(ticket or "").strip()
    m = TICKET.fullmatch(ticket)
    if not m or ticket in NOT_TICKETS:
        raise ValueError("not a ticket: %r (like ATO-7)" % ticket)
    p = prefs()
    tickets = [x for x in p["group_tickets"].get(group, []) if x != ticket] + ([ticket] if on else [])
    if tickets:
        p["group_tickets"][group] = tickets
        if group not in p["groups"]:
            p["groups"].append(group)
    else:
        p["group_tickets"].pop(group, None)
        if not p["group_prs"].get(group):
            p["left_out"].pop(group, None)
    _save_prefs(p)
    return {"group": group, "tickets": tickets}


_BRANCH_TICKET = re.compile(r"(?:^|[/_-])([a-z][a-z0-9]{1,9}-\d{1,6})(?=$|[/_-])", re.I)


def _tickets_in(*texts, branch=""):
    """Every ticket id named in the texts (upper case only, so prose like "gpt-4" doesn't count) and in a branch
    name (any case, as in `lee/ato-3574-fix`)."""
    out = {m.upper() for m in _BRANCH_TICKET.findall(branch or "")}
    for t in texts:
        out.update(TICKET.findall(t or ""))
    return out - NOT_TICKETS


def _depth(p, group):
    n, seen = 0, set()
    while group in p["group_parent"] and group not in seen:
        seen.add(group)
        group = p["group_parent"][group]
        n += 1
    return n


def placements(sessions=None):
    """{session id: {"folder": group, "via": "" | "pr" | "ticket"}} for every session that is in a group. By hand
    first (a session filed or taken out by hand is never moved), then a group following a PR it mentions, then a
    group following a ticket its branch, title or first message names: the deepest such group, then the first by
    name."""
    p = prefs()
    out = {sid: {"folder": f, "via": ""} for f, ids in p["folders"].items() for sid in ids}
    for sid, g in _following(p["group_prs"]).items():
        if sid not in out and sid not in (p["left_out"].get(g) or []):
            out[sid] = {"folder": g, "via": "pr"}
    wants = sorted(((-_depth(p, g), g, set(ts)) for g, ts in p["group_tickets"].items() if ts))
    if wants:
        for s in sessions if sessions is not None else scan():
            if s["id"] in out:
                continue
            named = _tickets_in(s["title"], s["ai_title"], s["first"], branch=s["branch"])
            out_of = set()  # taken out of a group: also out of the groups above it
            for h, ids in p["left_out"].items():
                if s["id"] in ids:
                    while h and h not in out_of:
                        out_of.add(h)
                        h = p["group_parent"].get(h, "")
            for _, g, ts in wants:
                if ts & named and g not in out_of:
                    out[s["id"]] = {"folder": g, "via": "ticket"}
                    break
    return out


def groups_of(pr):
    """The groups that follow a PR."""
    return sorted(g for g, prs in prefs()["group_prs"].items() if pr in prs)


def rename(sid, name):
    """Your own name for a session, shown in LFG only (Claude Code's /rename title is left alone). Empty clears it."""
    sid, p = _known(sid), prefs()
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:120]
    if name:
        p["names"][sid] = name
    else:
        p["names"].pop(sid, None)
    _save_prefs(p)
    return {"id": sid, "name": name}


def _group_name(name):
    return re.sub(r"\s+", " ", str(name or "")).strip()[:80]


def file_into(sid, folder, came_from=""):
    """Put a session in one of your groups (stored as "folders"; a label in LFG only, nothing on disk moves). A
    session is in at most one. Empty takes it out; `came_from` a group it joined through a PR keeps it out of that
    group from then on."""
    sid, p = _known(sid), prefs()
    folder, came_from = _group_name(folder), _group_name(came_from)
    if folder:
        folder = _valid_group(folder)
    if (came_from in p["group_prs"] or came_from in p["group_tickets"]) and folder != came_from:
        p["left_out"][came_from] = sorted(set(p["left_out"].get(came_from) or []) | {sid})
    for f in list(p["folders"]):
        p["folders"][f] = [x for x in p["folders"][f] if x != sid]
        if not p["folders"][f]:
            del p["folders"][f]
    if folder:
        p["folders"].setdefault(folder, []).append(sid)
        if folder not in p["groups"]:
            p["groups"].append(folder)
    _save_prefs(p)
    return {"id": sid, "folder": folder}


def _valid_group(name):
    name = _group_name(name)
    if len(name) < 2:
        raise ValueError("give the group a name of at least 2 characters")
    return name


def _under(p, start, name):
    """True when `start` is `name` or sits somewhere below it."""
    seen = set()
    while start and start not in seen:
        if start == name:
            return True
        seen.add(start)
        start = p["group_parent"].get(start, "")
    return False


def make_group(name, parent=""):
    """Create a group on purpose, so it stays while it is empty. `parent` nests it inside another group."""
    name, parent = _valid_group(name), _group_name(parent)
    p = prefs()
    known = _group_set(p)
    if name in known:
        raise ValueError("there is already a group called %r" % name)
    if parent and parent not in known:
        raise ValueError("there is no group called %r" % parent)
    p["groups"] = sorted(set(p["groups"]) | {name})
    if parent:
        p["group_parent"][name] = parent
    _save_prefs(p)
    return {"group": name, "parent": parent}


def rename_group(old, new):
    """Rename a group everywhere it is stored. Refused when the new name is taken, so nothing changes."""
    old, new = _group_name(old), _valid_group(new)
    p = prefs()
    known = _group_set(p)
    if old not in known:
        raise ValueError("there is no group called %r" % old)
    if new != old and new in known:
        raise ValueError("there is already a group called %r" % new)
    p["groups"] = sorted({new if g == old else g for g in p["groups"]} | {new})
    for key in ("folders", "group_prs", "group_tickets", "left_out"):
        if old in p[key]:
            p[key][new] = p[key].pop(old)
    parent = {}
    for child, par in p["group_parent"].items():
        parent[new if child == old else child] = new if par == old else par
    p["group_parent"] = parent
    _save_prefs(p)
    return {"group": new, "old": old}


def move_group(name, parent):
    """Put a group inside another one (empty: top level). Refused when that would put it inside itself."""
    name, parent = _group_name(name), _group_name(parent)
    p = prefs()
    known = _group_set(p)
    if name not in known:
        raise ValueError("there is no group called %r" % name)
    if parent and parent not in known:
        raise ValueError("there is no group called %r" % parent)
    if _under(p, parent, name):
        raise ValueError("a group can't go inside itself or one of its own groups")
    if parent:
        p["group_parent"][name] = parent
    else:
        p["group_parent"].pop(name, None)
    p["groups"] = sorted(set(p["groups"]) | {name})
    _save_prefs(p)
    return {"group": name, "parent": parent}


def delete_group(name):
    """Delete a group. Its sessions and its groups move up to its parent (or to Unsorted / the top level);
    nothing is hidden or deleted."""
    name = _group_name(name)
    p = prefs()
    if name not in _group_set(p):
        raise ValueError("there is no group called %r" % name)
    parent = p["group_parent"].get(name, "")
    members = p["folders"].pop(name, [])
    if parent and members:
        p["folders"][parent] = list(dict.fromkeys(p["folders"].get(parent, []) + members))
        if parent not in p["groups"]:
            p["groups"].append(parent)
    for child, par in list(p["group_parent"].items()):
        if par == name:
            if parent:
                p["group_parent"][child] = parent
            else:
                del p["group_parent"][child]
    p["group_parent"].pop(name, None)
    p["groups"] = [g for g in p["groups"] if g != name]
    for key in ("group_prs", "group_tickets", "left_out"):
        p[key].pop(name, None)
    _save_prefs(p)
    return {"group": name, "moved_to": parent}


# ---------------------------------------------------------------- labels

LABEL_COLORS = ("gray", "green", "yellow", "red", "blue", "purple", "pink", "orange")
# the order new labels get colours in: blue first, because gray reads as having no colour
NEW_LABEL_ORDER = ("blue", "green", "purple", "orange", "pink", "yellow", "red", "gray")


def _label(name):
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if len(name) > 30:
        raise ValueError("a label can be at most 30 characters")
    return name


def _label_names(p):
    """{lower-case name: the spelling first typed} over every session's labels."""
    out = {}
    for sid in sorted(p["labels"]):
        for n in p["labels"][sid]:
            out.setdefault(n.lower(), n)
    return out


def _existing_ids():
    return {os.path.basename(f)[:-6] for f in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))}


def set_labels(sid, names):
    """Replace a session's labels (a studio's too: the same id). Names are case-insensitive: the first spelling typed
    is kept. A new label gets the next colour not yet used."""
    sid, p = _known(sid), prefs()
    shown = _label_names(p)
    mine = {}
    for n in names or []:
        n = _label(n)
        if n:
            mine.setdefault(n.lower(), shown.get(n.lower(), n))
    for key in mine:
        if key not in p["label_colors"]:
            used = set(p["label_colors"].values())
            p["label_colors"][key] = next((c for c in NEW_LABEL_ORDER if c not in used),
                                          NEW_LABEL_ORDER[len(p["label_colors"]) % len(NEW_LABEL_ORDER)])
    if mine:
        p["labels"][sid] = list(mine.values())
    else:
        p["labels"].pop(sid, None)
    _save_prefs(p)
    return {"id": sid, "labels": list(mine.values())}


def label_list(ids=None):
    """[{name, color, count}] for the labels on sessions that still exist, by name."""
    p = prefs()
    ids = _existing_ids() if ids is None else ids
    counts, shown = {}, _label_names(p)
    for sid, names in p["labels"].items():
        if sid in ids:
            for n in names:
                counts[n.lower()] = counts.get(n.lower(), 0) + 1
    return [{"name": shown[k], "color": p["label_colors"].get(k, "gray"), "count": c}
            for k, c in sorted(counts.items(), key=lambda kv: shown[kv[0]].lower())]


def edit_label(name, new_name="", color=""):
    """Rename a label (into an existing one: they merge) and/or give it another colour, on every item at once."""
    key, p = _label(name).lower(), prefs()
    shown = _label_names(p)
    if key not in shown:
        raise ValueError("there is no label called %r" % name)
    if color and color not in LABEL_COLORS:
        raise ValueError("colour must be one of: " + ", ".join(LABEL_COLORS))
    new = _label(new_name)
    final = key
    if new and new.lower() != key:
        final, display = new.lower(), shown.get(new.lower(), new)
        for sid, names in list(p["labels"].items()):
            out = []
            for n in names:
                n = display if n.lower() in (key, final) else n
                if n not in out:
                    out.append(n)
            p["labels"][sid] = out
        old_color = p["label_colors"].pop(key, "")
        if final not in p["label_colors"]:
            p["label_colors"][final] = old_color or "gray"
    elif new and new != shown[key]:  # only the capitalisation changes
        for sid, names in p["labels"].items():
            p["labels"][sid] = [new if n.lower() == key else n for n in names]
    if color:
        p["label_colors"][final] = color
    _save_prefs(p)
    return {"label": shown.get(final, new or shown[key])}


def delete_label(name):
    """Remove a label from every session."""
    key, p = _label(name).lower(), prefs()
    if key not in _label_names(p):
        raise ValueError("there is no label called %r" % name)
    for sid in list(p["labels"]):
        p["labels"][sid] = [n for n in p["labels"][sid] if n.lower() != key]
        if not p["labels"][sid]:
            del p["labels"][sid]
    p["label_colors"].pop(key, None)
    _save_prefs(p)
    return {"label": name}


# ---------------------------------------------------------------- usage, from the transcripts themselves

# Dollars per million tokens: (input, output, cache read). Cache writes cost 1.25x input (5 minutes) or 2x (1 hour).
# Anthropic's first-party API list prices; on a Max or Team plan this is what the same work would cost at API rates.
# Requests are priced as transcripts are read and the dollars kept in the usage index: after changing a price, bump
# USAGE_V so every transcript is priced again.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25), "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.00), "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50), "claude-opus-4-7": (5.0, 25.0, 0.50), "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20), "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
# Models whose price goes up when one request's prompt (input + cache read + cache write) is over a size.
LONG_PROMPT = {"claude-haiku-5-5": (100_000, (0.50, 2.50, 0.05))}
FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
USAGE_V = 4


def cost(model, t):
    """Dollars for one request's token counts, or None for a model LFG has no price for. Per request, because a
    model in LONG_PROMPT is priced by the size of each prompt, not of a day's total."""
    name = re.sub(r"-\d{8}$", "", model or "")
    p = PRICES.get(name)
    if not p:
        return None
    if name in LONG_PROMPT and t["input"] + t["cache_read"] + t["cache_write_5m"] + t["cache_write_1h"] > \
            LONG_PROMPT[name][0]:
        p = LONG_PROMPT[name][1]
    inp, out, read = p
    return (t["input"] * inp + t["output"] * out + t["cache_read"] * read + t["cache_write_5m"] * inp * 1.25
            + t["cache_write_1h"] * inp * 2) / 1e6


def _file_usage(path):
    """{day: {model: {field: tokens, "usd": dollars or None if unpriced}}} for one transcript. A reply is logged once
    per content block with the same usage, so each message id counts once."""
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
            d = out.setdefault(day, {}).setdefault(m["model"], dict(dict.fromkeys(FIELDS, 0), usd=0.0))
            for k in FIELDS:
                d[k] += row[k]
            usd = cost(m["model"], row)
            d["usd"] = None if usd is None or d["usd"] is None else d["usd"] + usd
    return out


REVIEW_CMD = re.compile(r"^/(?:lfg:)?review(?:-pr)?(?:\s+(.*))?$")
REVIEW_RUN = re.compile(r"follow it to review (\S+#\d+)")  # the dashboard's unattended review (review.run)


def review_of(path):
    """What PR a session reviews, from its first prompt: "/review-pr 1759", "/lfg:review 12", or the dashboard's
    Review button ("owner/repo#12"). "PR review" when it names none; "" for any other session."""
    with open(path, "rb") as fh:
        for i, ln in enumerate(fh):
            if i > 200:
                return ""
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if ev.get("type") != "user" or ev.get("isMeta") or ev.get("isSidechain"):
                continue
            text = _prompt_text((ev.get("message") or {}).get("content"))
            m = REVIEW_RUN.search(text or "")
            if m:
                return m.group(1)
            first = _prompt_of(text)
            if first is None:
                continue
            m = REVIEW_CMD.match(first)
            return ((m.group(1) or "").strip()[:60] or "PR review") if m else ""
    return ""


def _usage_index_path():
    return C.lfg_path("state", "usage-index.json")


def usage(days=30):
    """Tokens and dollars per day and per model for every Claude Code session (and its subagents), whether or not
    LFG is on there. Only transcripts that changed since last time are read again."""
    idx = C.read_json(_usage_index_path(), {}) or {}
    idx = idx if idx.get("v") == USAGE_V else {"v": USAGE_V, "files": {}}
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
            # a subagent's file sits under its session's folder: it counts as that session's work
            main = p if os.path.basename(os.path.dirname(p)) != "subagents" else \
                os.path.dirname(os.path.dirname(p)) + ".jsonl"
            try:
                rv = review_of(main)
            except OSError:
                rv = ""
            new[p] = {"size": st.st_size, "mtime": st.st_mtime, "days": _file_usage(p), "review": rv,
                      "session": os.path.basename(main)[:-6]}
            changed = True
        except OSError:
            continue
    if changed or len(new) != len(old):
        C.ensure_dir(os.path.dirname(_usage_index_path()))
        C.write_json(_usage_index_path(), {"v": USAGE_V, "files": new})
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
    today = time.strftime("%Y-%m-%d")
    week = time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 86400))
    month = time.strftime("%Y-%m-%d", time.localtime(time.time() - 29 * 86400))
    per_day, per_model, unpriced, reviews = {}, {}, set(), {}
    spend = {"today": 0.0, "7d": 0.0, "30d": 0.0, "range": 0.0}  # range: all `days` asked for
    for f in new.values():
        rv = f.get("review") or ""
        for day, models in f["days"].items():
            if day < since:
                continue
            for model, t in models.items():
                dd = per_day.setdefault(day, dict(dict.fromkeys(FIELDS + ("usd", "review_usd", "review_tokens"), 0),
                                                  models={}))
                dm = dd["models"].setdefault(model, dict.fromkeys(FIELDS + ("usd",), 0))
                mm = per_model.setdefault(model, dict.fromkeys(FIELDS + ("usd",), 0))
                usd = t["usd"]
                if usd is None:
                    unpriced.add(model)
                    usd = 0.0
                for k in FIELDS:
                    dd[k] += t[k]
                    mm[k] += t[k]
                    dm[k] += t[k]
                dm["usd"] += usd
                dd["usd"] += usd
                if rv:
                    dd["review_usd"] += usd
                    dd["review_tokens"] += sum(t[k] for k in FIELDS)
                    r = reviews.setdefault(f.get("session") or "", {"session": f.get("session") or "", "pr": rv,
                                                                    "usd": 0.0, "tokens": 0, "last": day})
                    r["usd"] += usd
                    r["tokens"] += sum(t[k] for k in FIELDS)
                    r["last"] = max(r["last"], day)
                mm["usd"] += usd
                spend["range"] += usd
                spend["30d"] += usd if day >= month else 0
                spend["7d"] += usd if day >= week else 0
                spend["today"] += usd if day == today else 0
    for dd in per_day.values():
        dd["models"] = {m: dict(v, usd=round(v["usd"], 4)) for m, v in dd["models"].items()}
        dd["review_usd"] = round(dd["review_usd"], 4)
    as_rows = lambda d, k: [dict(v, **{k: n}) for n, v in sorted(d.items())]  # noqa: E731
    return {"days": [dict(r, cache_write=r["cache_write_5m"] + r["cache_write_1h"]) for r in as_rows(per_day, "day")],
            "models": sorted([dict(r, cache_write=r["cache_write_5m"] + r["cache_write_1h"])
                              for r in as_rows(per_model, "model")], key=lambda r: -r["usd"]),
            "spend": {k: round(v, 2) for k, v in spend.items()}, "unpriced": sorted(unpriced),
            "reviews": sorted([dict(r, usd=round(r["usd"], 2)) for r in reviews.values()], key=lambda r: r["last"],
                              reverse=True)}


# ---------------------------------------------------------------- done with a ticket: hide, trash, worktrees

def hide(ids, on=True):
    """Hide sessions from the Sessions page (or show them again). Their files are untouched, so /resume still works."""
    ids = [_known(i) for i in ids]
    p = prefs()
    hidden = set(p.get("hidden") or [])
    hidden = hidden | set(ids) if on else hidden - set(ids)
    p["hidden"] = sorted(hidden)
    _save_prefs(p)
    return {"hidden": len(ids) if on else 0, "shown": 0 if on else len(ids)}


def trash(sid):
    """Move a session's transcript (and its subagents' folder) to the macOS Trash. Refused while it looks in use."""
    sid = _known(sid)
    paths = glob.glob(os.path.join(PROJECTS, "*", sid + ".jsonl"))
    if any(time.time() - os.path.getmtime(p) < 300 for p in paths):
        raise ValueError("that session was used in the last 5 minutes; close it in Claude Code first")
    bin_ = os.path.join(C.HOME, ".Trash")
    moved = []
    for p in paths + [d for d in glob.glob(os.path.join(PROJECTS, "*", sid)) if os.path.isdir(d)]:
        dest = os.path.join(bin_, "%s %s" % (os.path.basename(os.path.dirname(p)), os.path.basename(p)))
        if os.path.exists(dest):
            dest += " %d" % int(time.time())
        os.rename(p, dest)
        moved.append(dest)
    p = prefs()
    p["hidden"] = [x for x in p.get("hidden") or [] if x != sid]
    p["names"].pop(sid, None)
    p["labels"].pop(sid, None)
    for f in list(p["folders"]):
        p["folders"][f] = [x for x in p["folders"][f] if x != sid]
        if not p["folders"][f]:
            del p["folders"][f]
    _save_prefs(p)
    return {"id": sid, "moved_to_trash": moved}


def _git(cwd, *args):
    return C.run(["git", *args], cwd=cwd, timeout=30)


def worktree_state(path):
    """What would be lost by removing this worktree: uncommitted files and commits no remote has."""
    if not os.path.isdir(path):
        return {"path": path, "exists": False, "safe": False, "why": "already gone"}
    top = _git(path, "rev-parse", "--show-toplevel").stdout.strip()
    common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    if not top or os.path.realpath(top) != os.path.realpath(path):
        return {"path": path, "exists": True, "safe": False, "why": "not the top of a git worktree"}
    if os.path.realpath(os.path.join(path, ".git")) == os.path.realpath(common):
        return {"path": path, "exists": True, "safe": False, "why": "this is the main checkout, not a worktree"}
    branch = _git(path, "branch", "--show-current").stdout.strip()
    dirty = [ln for ln in _git(path, "status", "--porcelain").stdout.splitlines() if ln.strip()]
    unpushed = [ln for ln in _git(path, "log", "--oneline", "HEAD", "--not", "--remotes").stdout.splitlines() if ln]
    why = "; ".join(x for x in (
        "%d uncommitted file(s)" % len(dirty) if dirty else "",
        "%d commit(s) not pushed anywhere" % len(unpushed) if unpushed else "") if x)
    return {"path": path, "exists": True, "branch": branch, "dirty": dirty[:20], "unpushed": unpushed[:20],
            "safe": not why, "why": why}


def remove_worktree(path):
    """Remove a worktree only if nothing would be lost. Never forces; the branch is kept."""
    st = worktree_state(path)
    if not st["safe"]:
        raise ValueError("kept %s: %s" % (path, st["why"]))
    main = os.path.dirname(_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    cp = _git(main, "worktree", "remove", path)
    if cp.returncode:
        raise ValueError((cp.stderr or cp.stdout).strip())
    return {"path": path, "branch": st["branch"]}


def group_cleanup(repo, group):
    """For "Done with this": the group's sessions and the worktrees they ran in, each with what removing it loses."""
    rows = [r for r in listing(hidden=True)["sessions"] if r["repo"] == repo and r["group"] == group]
    paths = sorted({r["cwd"] for r in rows if r["worktree"] and r["cwd"]})
    return {"sessions": [r["id"] for r in rows if not r["hidden"]], "worktrees": [worktree_state(p) for p in paths]}
