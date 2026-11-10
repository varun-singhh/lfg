"""Sessions: Claude Code, run from the dashboard (the Sessions page).

A live session is a `claude -p` process that `lfg ui` keeps open, talking Claude Code's stream-json protocol: your
messages go in on stdin, everything Claude does comes back on stdout, and permission prompts come back as
`can_use_tool` requests (`--permission-prompt-tool stdio`) that the page answers with Allow or Deny. It runs in the
project's checkout with the project's own settings (LFG's plugin, skills and guard), and through Headroom whenever
Claude Code is routed there (pinned here, like every LFG run).

What a session says is read back from Claude Code's own transcript (~/.claude/projects/<folder>/<id>.jsonl), the
same file a terminal or desktop session writes. So the list shows every session for the project, wherever it was
started, and any of them can be continued here (`--resume`). Live state (working, waiting for you, the pending
permission prompts) comes from the running process. Nothing here leaves the computer except Claude Code's own API
calls. Author: Varun Singh."""
import base64
import binascii
import collections
import glob
import json
import os
import re
import subprocess
import time
import threading
import uuid

from . import common as C
from . import notify as N
from . import sessions as US

PROJECTS = os.path.join(C.HOME, ".claude", "projects")
MODES = {"default": "Ask before edits", "acceptEdits": "Accept edits", "plan": "Plan only"}
MODELS = ("opus", "sonnet", "haiku")
MAX_ITEMS = 600
SUMMARY_VERSION = 7
_LIVE, _LOCK = {}, threading.RLock()


class Invalid(ValueError):
    pass


def _index_path():
    return C.lfg_path("sessions", "index.json")


def _index():
    d = C.read_json(_index_path(), None)
    return d if isinstance(d, dict) else {}


def _remember(sid, **kv):
    with _LOCK:
        d = _index()
        d[sid] = dict(d.get(sid) or {}, **kv)
        C.ensure_dir(os.path.dirname(_index_path()))
        C.write_json(_index_path(), d)


def folder_for(path):
    """Claude Code's transcript folder for a working directory: every character but letters and digits becomes -."""
    return os.path.join(PROJECTS, re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path)))


def transcript(sid, cwd=None):
    """Path of a session's transcript: in its working directory's folder, else wherever it is."""
    if cwd:
        p = os.path.join(folder_for(cwd), sid + ".jsonl")
        if os.path.exists(p):
            return p
    hits = glob.glob(os.path.join(PROJECTS, "*", sid + ".jsonl"))
    return hits[0] if hits else None


# ---------------------------------------------------------------- reading a transcript

REVIEW_NOTE = re.compile(r"\s*<lfg-review\b[^>]*>[\s\S]*?</lfg-review>\s*")  # what a review's chat adds to a message
COMMAND = re.compile(r"<command-name>/?([^<]+)</command-name>")
ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
NOISE = re.compile(r"^\s*<(local-command-stdout|local-command-caveat|system-reminder|bash-input|bash-stdout|"
                   r"bash-stderr|user-prompt-submit-hook|task-notification)", re.S)
AGENT_TOOLS = ("Agent", "Task")
INTERACTIVE = {"AskUserQuestion": "question", "ExitPlanMode": "plan"}  # prompts that want an answer, not an OK


def _check_answers(inp, answers):
    """Your answers to AskUserQuestion, keyed by each question's text as Claude Code expects: a chosen label, several
    joined with ", " (multiSelect), or your own words. Every question needs one."""
    qs = (inp or {}).get("questions") or []
    if not isinstance(answers, dict):
        raise Invalid("answers missing")
    out = {}
    for q in qs:
        text = str(q.get("question") or "")
        a = answers.get(text)
        if isinstance(a, list):
            a = ", ".join(str(x).strip() for x in a if str(x).strip())
        a = str(a or "").strip()
        if not a:
            raise Invalid("answer every question (%s)" % (q.get("header") or text[:40]))
        out[text] = a[:4000]
    return out
NOTE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
TASK_ID = re.compile(r"\b(?:ID|id|agentId|task_id)[:=]\s*`?([A-Za-z0-9_-]{5,})")
DONE = {"completed": "done", "success": "done", "failed": "failed", "error": "failed", "killed": "stopped",
        "stopped": "stopped", "cancelled": "stopped"}


def _text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text")


def _result_text(c):
    body = c.get("content")
    if isinstance(body, list):
        body = "\n".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in body)
    return str(body or "")


BUILTIN = {"compact", "clear", "context", "cost", "model", "rewind", "resume", "help", "init", "memory", "config",
           "status", "permissions", "agents", "mcp", "hooks", "login", "logout", "doctor", "export", "branch"}


def _human(ev):
    """Is this user line a prompt somebody typed (text or an image), not a tool result or Claude Code's own?"""
    c = (ev.get("message") or {}).get("content")
    if ev.get("isMeta") or ev.get("isCompactSummary"):
        return False
    return isinstance(c, str) or any(isinstance(x, dict) and x.get("type") in ("text", "image") for x in c or [])


def read(path, limit=MAX_ITEMS):
    """A transcript as display items, oldest first: me / ai / tool (with its result) / skill / note. Subagent
    (sidechain) lines and Claude Code's own bookkeeping are left out.

    A rewind leaves the turns it undid in the file: the next prompt then continues from an earlier line (its
    parentUuid), or Claude Code writes a `rewound` marker. Either way the undone turns are dropped here, as Claude
    Code drops them. (Following parentUuid for the whole file isn't safe: parallel tool calls branch it too.)"""
    items, tools, meta = [], {}, {"title": None, "branch": None, "entry": None, "cwd": None, "model": None,
                                   "first": None, "updated": None, "skills": [], "files": [], "issues": []}
    if not path or not os.path.exists(path):
        return items, meta
    pos = {}  # each line's uuid -> how many items there were once it was read
    acts, stops = {}, set()  # subagents and background work: tool_use id -> what it is and how it's doing
    with open(path, "rb") as fh:
        for raw in fh:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "custom-title" and ev.get("customTitle"):
                meta["title"] = ev["customTitle"]
                continue
            if t == "last-prompt" and ev.get("rewound") and ev.get("leafUuid") in pos:
                del items[pos[ev["leafUuid"]]:]
                continue
            if ev.get("isSidechain"):
                continue
            # written by another window (a terminal, the desktop app), not by a `claude -p` like the studio's own
            if t in ("user", "assistant", "system") and ev.get("entrypoint") not in (None, "sdk-cli") and \
                    ev.get("timestamp"):
                meta["outside"] = {"ts": ev["timestamp"], "entry": ev["entrypoint"]}
                if ev.get("subtype") == "compact_boundary":
                    meta["outside_compact"] = ev["timestamp"]
            if t == "system" and ev.get("subtype") == "compact_boundary":
                items.append({"k": "note", "text": "Conversation compacted", "ts": ev.get("timestamp")})
            if t not in ("user", "assistant"):
                if ev.get("uuid"):
                    pos[ev["uuid"]] = len(items)
                continue
            if t == "user" and _human(ev) and pos.get(ev.get("parentUuid"), len(items)) < len(items):
                del items[pos[ev["parentUuid"]]:]  # rewound: this prompt continues from before those turns
            meta["branch"] = ev.get("gitBranch") or meta["branch"]
            meta["entry"] = meta["entry"] or ev.get("entrypoint")
            meta["cwd"] = meta["cwd"] or ev.get("cwd")
            meta["updated"] = ev.get("timestamp") or meta["updated"]
            msg = ev.get("message") or {}
            ts = ev.get("timestamp")
            if t == "user":
                content = msg.get("content")
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in tools:
                            tool = tools[c["tool_use_id"]]
                            tool.update(result=_result_text(c)[:20000], error=bool(c.get("is_error")))
                        if (isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in tools
                                and isinstance(ev.get("toolUseResult"), dict)):
                            tools[c["tool_use_id"]].update(_line_counts(ev["toolUseResult"]))
                        if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in acts:
                            _act_result(acts[c["tool_use_id"]], _result_text(c), bool(c.get("is_error")), ts)
                for m in NOTE.finditer(_text_of(content)):
                    _act_note(acts, m.group(1), ts)
                if not _human(ev):
                    pos[ev.get("uuid")] = len(items)
                    continue
                text = _text_of(content).strip()
                images = [{"u": ev.get("uuid"), "i": i} for i, c in enumerate(content)
                          if isinstance(c, dict) and c.get("type") == "image"] if isinstance(content, list) else []
                if (not text and not images) or NOISE.match(text):
                    pos[ev.get("uuid")] = len(items)
                    continue
                cmd = COMMAND.search(text)
                if cmd:  # a slash command: /lfg:fix and its arguments
                    args = ARGS.search(text)
                    name = cmd.group(1).strip()
                    items.append({"k": "skill", "name": name, "args": (args.group(1).strip() if args else ""),
                                  "ts": ts, "u": ev.get("uuid"), "p": ev.get("parentUuid")})
                    if name not in meta["skills"] and name not in BUILTIN:
                        meta["skills"].append(name)
                    meta["first"] = meta["first"] or "/" + name + (" " + args.group(1).strip() if args else "")
                    pos[ev.get("uuid")] = len(items)
                    continue
                items.append({"k": "me", "text": text[:20000], "ts": ts, "u": ev.get("uuid"), "p": ev.get("parentUuid"),
                              "images": images})
                meta["first"] = meta["first"] or REVIEW_NOTE.sub("", text) or "(image)"
            else:
                meta["model"] = msg.get("model") if msg.get("model") not in (None, "<synthetic>") else meta["model"]
                for c in msg.get("content") or []:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "text" and c.get("text", "").strip():
                        items.append({"k": "ai", "text": c["text"], "ts": ts, "u": ev.get("uuid"),
                                      "mid": msg.get("id")})
                    elif c.get("type") == "tool_use":
                        it = {"k": "tool", "id": c.get("id"), "name": c.get("name"), "input": c.get("input") or {},
                              "ts": ts}
                        if c.get("name") == "Skill":
                            sk = str((c.get("input") or {}).get("skill") or (c.get("input") or {}).get("name") or "")
                            if sk and sk not in meta["skills"]:
                                meta["skills"].append(sk)
                        tools[c.get("id")] = it
                        items.append(it)
                        inp = c.get("input") or {}
                        if c.get("name") in AGENT_TOOLS or inp.get("run_in_background"):
                            acts[c.get("id")] = {
                                "id": c.get("id"), "kind": "agent" if c.get("name") in AGENT_TOOLS else
                                ("command" if c.get("name") == "Bash" else "task"), "tool": c.get("name"),
                                "label": _one_line(str(inp.get("description") or inp.get("command") or
                                                       c.get("name")))[:120],
                                "type": inp.get("subagent_type"), "background": bool(inp.get("run_in_background")),
                                "status": "running", "started": ts}
                        if c.get("name") in ("TaskStop", "KillShell", "KillBash"):
                            stops.add(str(inp.get("task_id") or inp.get("shell_id") or inp.get("id") or ""))
                        fp = (c.get("input") or {}).get("file_path") or (c.get("input") or {}).get("notebook_path")
                        if c.get("name") in ("Edit", "MultiEdit", "Write", "NotebookEdit") and fp:
                            it["changes"] = fp
            pos[ev.get("uuid")] = len(items)
    meta["additions"] = meta["deletions"] = 0
    for it in items:  # a file counts as changed once its edit went through (and wasn't rewound)
        fp = it.get("changes")
        if fp and "result" in it and not it.get("error"):
            if fp not in meta["files"]:
                meta["files"].append(fp)
            meta["additions"] += it.pop("adds", 0)
            meta["deletions"] += it.pop("dels", 0)
    meta["issues"] = _issues(" ".join(str(x or "") for x in (meta["branch"], meta["title"], meta["first"])))
    for a in acts.values():
        if a["status"] == "running" and a.get("task") and a["task"] in stops:
            a["status"] = "stopped"
    meta["activity"] = list(acts.values())
    meta["total"] = len(items)
    return items[-limit:], meta


def _line_counts(r):
    """Lines an edit added and removed, from Claude Code's record of it (its patch, or a new file's content)."""
    patch = r.get("structuredPatch") or []
    if not patch and r.get("type") == "create":
        return {"adds": len(str(r.get("content") or "").split("\n")), "dels": 0}
    lines = [ln for h in patch for ln in (h.get("lines") or [])]
    return {"adds": sum(1 for ln in lines if ln[:1] == "+"), "dels": sum(1 for ln in lines if ln[:1] == "-")}


def _act_result(a, text, error, ts):
    """A tool result for a subagent or background job: a foreground one is finished; a background one only started
    (its result carries the id that its later notification and any TaskStop refer to)."""
    if a["background"]:
        m = TASK_ID.search(text or "")
        a["task"] = m.group(1) if m else a.get("task")
        if error:
            a.update(status="failed", ended=ts)
    else:
        a.update(status="failed" if error else "done", ended=ts)


def _act_note(acts, body, ts):
    """<task-notification>: Claude Code's word that background work finished (or failed, or was stopped)."""
    def f(tag):
        m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), body, re.S)
        return m.group(1).strip() if m else ""
    tid, task = f("tool-use-id"), f("task-id")
    a = acts.get(tid) or next((x for x in acts.values() if task and x.get("task") == task), None)
    st = DONE.get(f("status").lower())
    if a and st:
        a.update(status=st, ended=ts, summary=_one_line(f("summary"))[:200] or a.get("summary"))


def _short_input(name, inp):
    """What a tool call was about, in a few words: the file, the command, the search."""
    inp = inp or {}
    for k in ("file_path", "notebook_path", "path"):
        if inp.get(k):
            return "%s %s" % (name, os.path.basename(str(inp[k]).rstrip("/")))
    for k in ("description", "command", "pattern", "query", "url", "skill", "prompt"):
        if inp.get(k):
            return "%s: %s" % (name, _one_line(str(inp[k]))[:70])
    return name


def _epoch(ts):
    try:
        import datetime
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def activity(path, acts, live):
    """What this session has running besides the conversation: subagents and background commands, each with what
    it's doing now (from the subagent's own transcript in <session>/subagents/). Running work, plus what finished in
    the last 20 minutes. When LFG isn't running the session and nothing has been written for 15 minutes, running is
    only what the transcript last said, so it's reported as "quiet" instead of claimed as running."""
    subs = {}
    sub_dir = os.path.join(path[:-len(".jsonl")], "subagents") if path and path.endswith(".jsonl") else ""
    for mp in glob.glob(os.path.join(sub_dir, "agent-*.meta.json")) if sub_dir else []:
        m = C.read_json(mp, {}) or {}
        if m.get("toolUseId"):
            subs[m["toolUseId"]] = mp[:-len(".meta.json")] + ".jsonl"
    newest = os.path.getmtime(path) if path and os.path.exists(path) else 0
    out = []
    for a in acts:
        a = dict(a)
        jp = subs.get(a["id"])
        if jp and os.path.exists(jp):
            steps, last = 0, None
            with open(jp, "rb") as fh:
                for raw in fh:
                    try:
                        ev = json.loads(raw)
                    except ValueError:
                        continue
                    for c in ((ev.get("message") or {}).get("content") or []) if ev.get("type") == "assistant" else []:
                        if isinstance(c, dict) and c.get("type") == "tool_use":
                            steps, last = steps + 1, _short_input(c.get("name"), c.get("input"))
            a.update(steps=steps, now=last, touched=os.path.getmtime(jp))
            newest = max(newest, a["touched"])
        out.append(a)
    quiet = not live and newest and time.time() - newest > 900
    keep, cutoff = [], time.time() - 1200
    for a in out:
        if a["status"] == "running":
            if quiet:
                a["status"] = "quiet"
            keep.append(a)
        elif (_epoch(a.get("ended")) or 0) > cutoff:
            keep.append(a)
    return keep[-12:]


ISSUE = re.compile(r"\b([A-Z]{2,10}-\d{1,6})\b")


def _issues(text):
    """Linear-style keys a session mentions (ATO-4251), from its branch (ato-4251-...), title or first message."""
    found = []
    for k in ISSUE.findall(str(text or "").upper()):
        if k not in found and not k.startswith(("UTF-", "SHA-", "ISO-", "HTTP-")) and int(k.split("-")[1]):
            found.append(k)
    return found[:3]


def _wt_name(root, cwd):
    """The worktree folder a session works in, or None for the project's own checkout."""
    if not cwd or not root or os.path.realpath(cwd) == os.path.realpath(root):
        return None
    return os.path.basename(cwd.rstrip("/"))


def where(rid, root):
    """For the new-session screen: the branch checked out right now, the default branch, local branches, and every
    worktree with where it stands (see worktree.status)."""
    from . import worktree as W
    if not root or not os.path.isdir(root):
        return {"branch": "", "worktrees": [], "branches": []}
    sessions = {}
    for s in listing(rid, root)["sessions"]:
        if s.get("worktree_name"):
            sessions[s["worktree_name"]] = sessions.get(s["worktree_name"], 0) + 1
    wts = [dict(w, sessions=sessions.get(w["name"], 0)) for w in W.status(root) if w["kind"] != "review"]
    branches = C.run(["git", "for-each-ref", "refs/heads", "--format=%(refname:short)"], cwd=root,
                     timeout=10).stdout.split()
    return {"branch": C.git_branch(root), "default": W.default_branch(root), "worktrees": wts,
            "branches": branches[:300]}


def _pr_for(rid, branch):
    if not branch or branch in ("HEAD", "main", "master"):
        return None
    try:
        from . import dash
        pr = dash.pr_states(rid)[1].get(branch)
    except Exception:
        return None
    return {"number": pr["number"], "state": pr.get("state"), "url": pr.get("url")} if pr else None


def _cost(path):
    total = 0.0
    try:
        for models in US._file_usage(path).values():
            for model, t in models.items():
                total += US.cost(model, t) or 0
    except OSError:
        return None
    return round(total, 4)


# ---------------------------------------------------------------- the list

def _summary_cache():
    return C.read_json(C.lfg_path("sessions", "list-cache.json"), {}) or {}


def listing(rid, root):
    """Every Claude Code session for this project (its checkout and LFG's worktrees of it), newest first, with what
    each is about, where it came from, its branch, cost, and whether it's live here right now."""
    if not root:
        return {"sessions": []}
    base = folder_for(root)
    files = glob.glob(os.path.join(base, "*.jsonl")) + glob.glob(os.path.join(base + "-worktrees-*", "*.jsonl"))
    from . import sessions as SS
    placed = SS.placements()
    cache, idx, changed, out = _summary_cache(), _index(), False, []
    prefs = SS.prefs()
    labels = {sid: [{"name": n, "color": prefs["label_colors"].get(n.lower(), "gray")} for n in names]
              for sid, names in prefs["labels"].items()}
    for p in sorted(files, key=lambda p: -os.path.getmtime(p))[:200]:
        st = os.stat(p)
        key = "v%d:%s:%d:%d" % (SUMMARY_VERSION, p, st.st_mtime, st.st_size)  # a new version rebuilds them all
        s = cache.get(p)
        if not s or s.get("key") != key:
            items, meta = read(p, limit=1)
            s = {"key": key, "title": meta["title"] or _title(meta["first"]) or "Untitled session",
                 "worktree_name": _wt_name(root, meta["cwd"]),
                 "branch": meta["branch"], "entry": meta["entry"], "model": meta["model"], "skills": meta["skills"],
                 "updated": meta["updated"], "cost": _cost(p), "worktree": "-worktrees-" in os.path.dirname(p),
                 "files": len(meta["files"]), "issues": meta["issues"]}
            cache[p], changed = s, True
        sid = os.path.basename(p)[:-6]
        live = _LIVE.get(sid)
        mine = idx.get(sid) or {}
        out.append(dict({k: v for k, v in s.items() if k != "key"}, id=sid,
                        source="lfg" if mine.get("lfg") else
                        {"claude-desktop": "desktop", "cli": "terminal"}.get(s.get("entry"), "background"),
                        state=live.state if live else "saved", title=mine.get("title") or s["title"],
                        mode=(live.mode if live else mine.get("mode")), pr=_pr_for(rid, s.get("branch")),
                        folder=(placed.get(sid) or {}).get("folder", ""), via=(placed.get(sid) or {}).get("via", ""),
                        labels=labels.get(sid, [])))
    for sid, live in list(_LIVE.items()):  # a live session whose transcript isn't written yet
        if live.rid == rid and not any(x["id"] == sid for x in out):
            out.insert(0, {"id": sid, "title": live.title, "branch": live.branch, "source": "lfg", "state": live.state,
                           "model": live.model, "mode": live.mode, "updated": live.started, "cost": None,
                           "skills": [], "folder": (placed.get(sid) or {}).get("folder", ""),
                           "via": (placed.get(sid) or {}).get("via", ""), "labels": labels.get(sid, [])})
    if changed:
        C.ensure_dir(C.lfg_path("sessions"))
        C.write_json(C.lfg_path("sessions", "list-cache.json"), {k: v for k, v in cache.items() if os.path.exists(k)})
    return {"sessions": out, "modes": MODES, "models": list(MODELS), "group_info": SS.group_info(),
            "label_list": SS.label_list()}


LFG_PROMPTS = [  # LFG's own background runs, by how their prompt starts: a readable title instead
    (re.compile(r"^PR mode review for the dashboard\. Review pull request #(\d+)"), "AI review of PR #%s"),
    (re.compile(r"^Comment triage mode for the dashboard\. This is my own pull request #(\d+)"),
     "Comments read on PR #%s"),
    (re.compile(r"^You are answering a reviewer's question about pull request #(\d+)"), "Diff question on PR #%s"),
    (re.compile(r"^Fix mode, started from the LFG dashboard's fix list for my pull request #(\d+)"),
     "Fix run for PR #%s"),
    (re.compile(r"^Create exactly one new Linear issue"), "Linear ticket"),
    (re.compile(r"^Read only\. Call list_teams"), "Linear lists"),
]


def _title(text):
    for rx, fmt in LFG_PROMPTS:
        m = rx.match(str(text or ""))
        if m:
            return fmt % m.group(1) if "%s" in fmt else fmt
    return _one_line(text)


def _one_line(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:90] + "…" if len(text) > 90 else text


# ---------------------------------------------------------------- a live session

class Live:
    """One running `claude -p` in stream-json mode, kept open by `lfg ui` between your messages."""

    def __init__(self, sid, rid, root, model, mode, title, resume, fork_of=None, fork_at=None, review=None):
        self.sid, self.rid, self.root, self.model, self.mode, self.title = sid, rid, root, model, mode, title
        self.state, self.pending, self.allowed = "starting", {}, set()
        self.started, self.cost, self.error, self.queued = C.now_iso(), None, None, []
        self.born = time.time()  # when it read the transcript: what other windows write after this, it doesn't see
        self._branch, self._replies = (0, ""), {}
        # a PR review this session is the chat of ({"pr", "n"}): its messages carry the review (reviewchat.py), and
        # each turn's reply is read for changes to it when the turn ends. _turns: what each sent message was, in order.
        self.review, self._turns, self._qmeta, self._last = review, collections.deque(), [], (None, "")
        from . import prreview as PR
        env, self.via = PR._child_env(root)
        env["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] = "1"  # so Rewind can put files back, as in the terminal
        if fork_of:  # a copy of another session (up to one of its lines), under a new id
            where = ["--resume", fork_of, "--fork-session", "--session-id", sid] + \
                (["--resume-session-at", fork_at] if fork_at else [])
        else:
            where = ["--resume", sid] if resume else ["--session-id", sid]
        argv = [C.which("claude") or "claude", "-p", "--input-format", "stream-json", "--output-format",
                "stream-json", "--verbose", "--permission-prompt-tool", "stdio", "--permission-mode", mode] + \
            (["--model", model] if model else []) + where
        if review:  # a review's chat may look at anything, but never write to GitHub
            from . import review as RV
            argv += ["--disallowedTools", ",".join(RV.RUN_DENY)]
        self.log = open(os.path.join(C.ensure_dir(C.lfg_path("sessions")), sid + ".stderr"), "ab")
        self.proc = subprocess.Popen(argv, cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.log, start_new_session=True, close_fds=True)
        self._write({"type": "control_request", "request_id": "init-" + sid[:8], "request": {"subtype": "initialize"}})
        threading.Thread(target=self._read, daemon=True).start()

    @property
    def branch(self):
        """The branch checked out where the session works, read again every few seconds (it can change)."""
        if time.time() - self._branch[0] > 3:
            self._branch = (time.time(), C.git_branch(self.root))
        return self._branch[1]

    def _write(self, obj):
        try:
            self.proc.stdin.write((json.dumps(obj) + "\n").encode())
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def _read(self):
        for raw in self.proc.stdout:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "control_request" and (ev.get("request") or {}).get("subtype") == "can_use_tool":
                self._ask(ev)
            elif t == "control_response":
                r = ev.get("response") or {}
                if str(r.get("request_id")).startswith("init-") and self.state == "starting":
                    self.state = "idle"  # ready for messages and control requests
                box = self._replies.get(r.get("request_id"))
                if box:
                    box.append(r)
                    box[0].set()
            elif t == "system" and ev.get("subtype") == "init":
                self.model = ev.get("model") or self.model
                if self.state == "starting":
                    self.state = "idle"
            elif t == "assistant" and self.state in ("starting", "idle"):
                self.state = "working"
            if t == "assistant" and not ev.get("parent_tool_use_id"):  # the last thing said this turn, and its id
                msg = ev.get("message") or {}
                said = "".join(c.get("text") or "" for c in msg.get("content") or [] if isinstance(c, dict)
                               and c.get("type") == "text")
                if said.strip():
                    self._last = (msg.get("id"), said)
            if t == "result":
                self._turn_done(ev)
                self.cost = ev.get("total_cost_usd") if ev.get("total_cost_usd") is not None else self.cost
                if ev.get("is_error"):
                    self.error = str(ev.get("result") or ev.get("subtype") or "the turn failed")[:400]
                self.state = "idle" if not self.pending else "needs-you"
                if self.queued:  # a message sent while Claude was busy goes in now
                    self._send_queued(self.queued.pop(0))
                else:
                    path = transcript(self.sid, self.root)
                    spent = _cost(path) if path else None
                    N.add("session", "Claude finished in “%s”" % _one_line(self.title)[:60],
                          "Done" + (" · $%.2f so far" % spent if spent else ""), "#studio/" + self.sid,
                          self.rid, ok=not ev.get("is_error"))
        self.state = "ended"
        for box in list(self._replies.values()):  # nobody waits on a reply that can't come now
            box[0].set()
        self.proc.stdout.close()
        self.log.close()
        try:
            self.proc.wait(timeout=5)  # reap it
        except subprocess.TimeoutExpired:
            pass

    def _turn_done(self, ev):
        """A turn ended: when it answered a message about a review, apply what the reply settled to the review, before
        the session shows as idle, so the page that sees it idle also sees the changes."""
        turn = self._turns.popleft() if self._turns else None
        mid, said = self._last
        self._last = (None, "")
        if not (turn and self.review and said and not ev.get("is_error")):
            return
        try:
            from . import reviewchat as RC
            RC.finish(self, turn, mid, said)
        except Exception as e:  # a review that can't be updated must not take the session down with it
            self.error = "the review couldn't be updated from that reply: %s" % str(e)[:200]

    def _ask(self, ev):
        req = ev.get("request") or {}
        tool = req.get("tool_name") or "?"
        kind = INTERACTIVE.get(tool, "permission")
        if kind == "permission" and tool in self.allowed:  # "Allow for this session" earlier
            self._answer(ev["request_id"], req, True)
            return
        self.pending[ev["request_id"]] = {"id": ev["request_id"], "tool": tool, "kind": kind,
                                          "input": req.get("input") or {},
                                          "description": req.get("description") or "", "at": C.now_iso(),
                                          "can_remember": kind == "permission"
                                          and bool(req.get("permission_suggestions")),
                                          "raw": req}
        self.state = "needs-you"
        qs = (req.get("input") or {}).get("questions") or []
        head, body = {
            "question": ("Claude has %s for you in “%s”" % ("a question" if len(qs) < 2 else "%d questions" % len(qs),
                                                           _one_line(self.title)[:60]),
                         _one_line(str((qs[0] if qs else {}).get("question") or ""))[:140]),
            "plan": ("Claude's plan is ready in “%s”" % _one_line(self.title)[:60],
                     "Approve it, or say what to change"),
        }.get(kind, ("Claude needs your OK in “%s”" % _one_line(self.title)[:60], "%s: %s" % (
            tool, _one_line(req.get("description") or json.dumps(req.get("input") or {}))[:120])))
        N.add("session", head, body, "#studio/" + self.sid, self.rid)

    def _answer(self, rid_, req, allow, message="", remember=False):
        resp = {"behavior": "allow", "updatedInput": req.get("input") or {}} if allow else \
            {"behavior": "deny", "message": message or "The user said no to this. Ask before trying another way."}
        if allow and remember and req.get("permission_suggestions"):  # saved like the terminal's "don't ask again"
            resp["updatedPermissions"] = req["permission_suggestions"]
        self._write({"type": "control_response", "response": {"subtype": "success", "request_id": rid_,
                                                                "response": resp}})

    def decide(self, request_id, decision, answers=None, message=""):
        """Answer a prompt. A permission: once / session / always / deny. Claude's questions (AskUserQuestion):
        "answer" with {question text: chosen label(s) or your own words}, which goes back as the tool's input, the way
        Claude Code's own picker answers; or "skip". A plan (ExitPlanMode): "approve", or "revise" with what to
        change. Questions and plans are never remembered: each one needs its own answer."""
        p = self.pending.get(request_id)
        if not p:
            raise Invalid("that request was already answered")
        kind, raw = p.get("kind", "permission"), p["raw"]
        if kind == "question":
            if decision == "answer":
                resp = {"behavior": "allow", "updatedInput": dict(raw.get("input") or {},
                                                                  answers=_check_answers(raw.get("input"), answers))}
            elif decision == "skip":
                resp = {"behavior": "deny", "message": "The user skipped these questions without answering. Carry on "
                        "with your best judgement and say which assumptions you made, or ask again later if it "
                        "matters."}
            else:
                raise Invalid("answer the questions, or skip them")
            self._respond(request_id, resp)
        elif kind == "plan":
            if decision == "approve":
                self._respond(request_id, {"behavior": "allow", "updatedInput": raw.get("input") or {}})
            elif decision == "revise":
                self._respond(request_id, {"behavior": "deny", "message": "The user wants changes to the plan before "
                              "you start: %s\nRevise the plan and present it again." % (str(message or "").strip()
                                                                                       or "(no details given)")})
            else:
                raise Invalid("approve the plan, or say what to change")
        else:
            if decision in ("always", "session"):
                self.allowed.add(p["tool"])
            self._answer(request_id, raw, decision in ("once", "always", "session"), remember=decision == "always")
        self.pending.pop(request_id, None)
        self.state = "needs-you" if self.pending else "working"

    def _respond(self, rid_, resp):
        self._write({"type": "control_response", "response": {"subtype": "success", "request_id": rid_,
                                                                "response": resp}})

    def control(self, request, timeout=30):
        """Ask Claude Code something on its control channel and wait for the answer (rewind, context usage)."""
        rid_ = "%s-%s" % (request.get("subtype", "req")[:12], uuid.uuid4().hex[:8])
        box = self._replies[rid_] = [threading.Event()]
        try:
            if not self._write({"type": "control_request", "request_id": rid_, "request": request}) or \
                    not box[0].wait(timeout) or len(box) < 2:
                raise Invalid("Claude Code didn't answer; continue the session and try again")
        finally:
            self._replies.pop(rid_, None)
        r = box[1]
        if r.get("subtype") != "success":
            raise Invalid(str(r.get("error") or "Claude Code said no")[:300])
        return r.get("response") or {}

    def say(self, text, attachments=None, turn=None):
        """`turn`: what a message about a review is ({"pr", "n", "fid", "qid", "q", "edits"}), kept until its reply."""
        content = _content(text, attachments)
        if self.state in ("working", "needs-you") or self.pending:
            self.queued.append(content)  # Claude is mid-turn or waiting on you: it goes in when this turn ends
            self._qmeta.append(turn)
            return "queued"
        self.error = None
        if not self._write({"type": "user", "message": {"role": "user", "content": content}}):
            self.state = "ended"
            raise Invalid("this session has ended; continue it to start it again")
        self._turns.append(turn)
        self.state = "working"
        return "sent"

    def _idle(self):
        if self.state in ("working", "needs-you", "starting") or self.pending:
            raise Invalid("wait for Claude to finish (or press Stop) first")

    def rewind_preview(self, message):
        """What rewinding the code to before `message` would change: files and lines, or why it can't."""
        self._idle()
        r = self.control({"subtype": "rewind_files", "user_message_id": message, "dry_run": True})
        return {"can": bool(r.get("canRewind")), "why": r.get("error") or "", "files": r.get("filesChanged") or [],
                "insertions": r.get("insertions") or 0, "deletions": r.get("deletions") or 0}

    def rewind(self, message, what):
        """Claude Code's Rewind: undo the conversation from `message` on, the files Claude changed since, or both.
        The rewound prompt comes back so it can be edited and sent again."""
        self._idle()
        if what not in ("both", "chat", "code"):
            raise Invalid("rewind the conversation, the code, or both")
        out = {}
        if what in ("both", "code"):
            r = self.control({"subtype": "rewind_files", "user_message_id": message})
            if not r.get("canRewind", True):
                raise Invalid(r.get("error") or "there's no saved copy of the files from then")
            out["code"] = True
        if what in ("both", "chat"):
            r = self.control({"subtype": "rewind_conversation", "target_message_uuid": message})
            out.update(chat=bool(r.get("rewound", True)), prefill=r.get("prefillText") or "")
        return out

    def context(self):
        """How full the context window is, from Claude Code (/context's summary, no extra API calls)."""
        r = self.control({"subtype": "get_context_usage", "detail": "summary"}, timeout=15)
        return {"percent": r.get("percentage"), "used": r.get("totalTokens"), "max": r.get("maxTokens"),
                "auto_compact_at": r.get("autoCompactThreshold") if r.get("isAutoCompactEnabled") else None,
                "parts": [{"name": c.get("name"), "tokens": c.get("tokens")} for c in r.get("categories") or []
                          if c.get("kind") == "used" and c.get("tokens")],
                # what is left, and what Claude Code keeps back for compacting: the rest of the window in the grid
                "free": sum(c.get("tokens") or 0 for c in r.get("categories") or [] if c.get("kind") == "free"),
                "reserved": sum(c.get("tokens") or 0 for c in r.get("categories") or []
                                if c.get("kind") not in ("used", "free"))}

    def set_mode(self, mode):
        if mode not in MODES:
            raise Invalid("not a permission mode")
        self._write({"type": "control_request", "request_id": "mode-" + uuid.uuid4().hex[:8],
                     "request": {"subtype": "set_permission_mode", "mode": mode}})
        self.mode = mode
        _remember(self.sid, mode=mode)

    def _send_queued(self, content):
        self.error = None
        turn = self._qmeta.pop(0) if self._qmeta else None
        if self._write({"type": "user", "message": {"role": "user", "content": content}}):
            self._turns.append(turn)
            self.state = "working"

    def interrupt(self):
        self.queued, self._qmeta = [], []
        self._write({"type": "control_request", "request_id": "stop-" + uuid.uuid4().hex[:8],
                     "request": {"subtype": "interrupt"}})

    def stop(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
        self.state = "ended"


def _check(text, attachments=None):
    text = str(text or "").strip()
    if not text and not attachments:
        raise Invalid("write a message first")
    if len(text) > 50000:
        raise Invalid("that message is too long")
    return text


def workdir(root, where):
    """Where a new session works: this checkout ("here"), an existing worktree of the repo ("worktree", its path),
    or a new worktree on a new branch forked from `base` ("new"). Never switches anybody's checkout."""
    from . import worktree as W
    where = where if isinstance(where, dict) else {}
    kind = where.get("kind") or "here"
    if kind == "here":
        return root
    if kind == "worktree":
        path = os.path.realpath(str(where.get("path") or ""))
        if not any(os.path.realpath(w["path"]) == path for w in W.listing(root)) or not os.path.isdir(path):
            raise Invalid("that worktree isn't part of this project any more")
        return path
    if kind == "branch":  # an existing branch, in a worktree of its own (or the one it already has)
        branch = str(where.get("branch") or "").strip()
        have = next((w["path"] for w in W.listing(root) if w["branch"] == branch), None)
        if have:
            return have
        try:
            return W.new(root, branch)["path"]
        except (ValueError, RuntimeError) as e:
            raise Invalid("couldn't make the worktree: %s" % e) from None
    if kind == "new":
        branch = str(where.get("branch") or "").strip()
        try:
            return W.new(root, branch, (str(where.get("base") or "").strip() or None))["path"]
        except (ValueError, RuntimeError) as e:
            raise Invalid("couldn't make the worktree: %s" % e) from None
    raise Invalid("unknown place to work")


# ---------------------------------------------------------------- attachments (drag and drop, paste, upload)

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_IMAGE, MAX_FILE, MAX_ATTACH = 5 * 1024 * 1024, 20 * 1024 * 1024, 10


def upload(name, mime, data_b64):
    """Keep a file dropped on the composer in ~/.lfg/uploads (only readable by you) and say where it is."""
    try:
        data = base64.b64decode(str(data_b64 or ""), validate=True)
    except (binascii.Error, ValueError):
        raise Invalid("that file didn't arrive whole") from None
    image = mime in IMAGE_TYPES
    if not data or len(data) > (MAX_IMAGE if image else MAX_FILE):
        raise Invalid("files can be up to %d MB (images %d MB)" % (MAX_FILE >> 20, MAX_IMAGE >> 20))
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(str(name or "file"))).strip(".-")[:80] or "file"
    top = C.lfg_path("uploads")
    folder = C.ensure_dir(os.path.join(top, time.strftime("%Y%m%d")))
    os.chmod(top, 0o700)
    path = os.path.join(os.path.realpath(folder), "%s-%s" % (uuid.uuid4().hex[:8], base))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return {"path": path, "name": base, "image": image, "type": mime if image else "", "size": len(data)}


def _content(text, attachments):
    """A message as Claude Code takes it: images as image blocks (like a pasted screenshot, [Image #1] in the text)
    and any other file as an @path mention, which Claude Code reads in for the model."""
    text = str(text or "").strip()
    if not attachments:
        return text
    if not isinstance(attachments, list) or len(attachments) > MAX_ATTACH:
        raise Invalid("attach up to %d files at a time" % MAX_ATTACH)
    root, blocks, mentions = os.path.realpath(C.lfg_path("uploads")) + os.sep, [], []
    for a in attachments:
        path = os.path.realpath(str((a or {}).get("path") or ""))
        if not path.startswith(root) or not os.path.isfile(path):
            raise Invalid("an attachment is gone; add it again")
        mime = str((a or {}).get("type") or "")
        if mime in IMAGE_TYPES:
            with open(path, "rb") as fh:
                data = fh.read()
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": mime,
                                                       "data": base64.b64encode(data).decode()}})
        else:
            mentions.append("@" + path)
    tags = " ".join("[Image #%d]" % (i + 1) for i in range(len(blocks)))
    body = "\n".join(x for x in (" ".join(filter(None, (tags, text))), " ".join(mentions)) if x)
    return blocks + [{"type": "text", "text": body}] if blocks else body


def image(sid, root, line, index):
    """One image from a session's transcript (a message's image block), as a data: URL for the page."""
    path = transcript(sid, root) if re.match(r"^[0-9a-f-]{36}$", str(sid or "")) else None
    if not path:
        raise Invalid("that session's transcript is gone")
    with open(path, "rb") as fh:
        for raw in fh:
            if line.encode() not in raw:
                continue
            ev = json.loads(raw)
            if ev.get("uuid") != line:
                continue
            content = (ev.get("message") or {}).get("content")
            c = content[int(index)] if isinstance(content, list) and 0 <= int(index) < len(content) else {}
            src = c.get("source") or {} if isinstance(c, dict) and c.get("type") == "image" else {}
            if src.get("type") == "base64" and src.get("media_type") in IMAGE_TYPES and \
                    len(src.get("data") or "") < 12_000_000:
                return {"src": "data:%s;base64,%s" % (src["media_type"], src["data"])}
            break
    raise Invalid("that image isn't in the transcript")


def start(rid, root, text, model=None, mode="default", title="", where=None, attachments=None):
    """A new session, starting with `text`, in this checkout or a worktree of it (see workdir)."""
    if not root or not os.path.isdir(root):
        raise Invalid("LFG doesn't know where this project is on disk")
    if not C.which("claude"):
        raise Invalid("Claude Code (claude) isn't on PATH")
    text = _check(text, attachments)
    model = model if model in MODELS else None  # none: Claude Code's own default, as the project's setup decides
    mode = mode if mode in MODES else "default"
    sid = str(uuid.uuid4())
    title = _one_line(title or text or "Image")[:90]
    cwd = workdir(root, where)
    with _LOCK:
        live = _LIVE[sid] = Live(sid, rid, cwd, model, mode, title, resume=False)
    _remember(sid, lfg=True, rid=rid, title=title, mode=mode, model=model, created=live.started, root=root, cwd=cwd)
    live.say(text, attachments)
    return {"id": sid}


def fork_open(rid, root, sid, at=None, review=None):
    """Claude Code's fork, without a first message: a new session with this one's conversation (up to line `at`, else
    all of it). The original stays as it was. It works in the same folder. Returns the new id."""
    if not re.match(r"^[0-9a-f-]{36}$", str(sid or "")) or (at and not re.match(r"^[0-9a-f-]{36}$", str(at))):
        raise Invalid("not a session id")
    path = transcript(sid, root)
    if not path:
        raise Invalid("that session's transcript is gone")
    _items, meta = read(path, limit=1)
    mine = _index().get(sid) or {}
    cwd = meta["cwd"] if meta["cwd"] and os.path.isdir(meta["cwd"]) else root
    new = str(uuid.uuid4())
    title = "Fork: " + _one_line(mine.get("title") or meta["title"] or meta["first"] or "session")[:80]
    mode = mine.get("mode") or "default"
    with _LOCK:
        live = _LIVE[new] = Live(new, rid, cwd, mine.get("model"), mode, title, resume=False, fork_of=sid,
                                 fork_at=at or None, review=review)
    _remember(new, lfg=True, rid=rid, title=title, mode=mode, created=live.started, root=root, cwd=cwd,
              forked_from=sid, **({"review": review} if review else {}))
    return new


def fork(rid, root, sid, at, text, attachments=None):
    """A fork (see fork_open), carried on with `text`."""
    text = _check(text, attachments)
    new = fork_open(rid, root, sid, at)
    live(new).say(text, attachments)
    return {"id": new}


def create(rid, root, title, review=None):
    """A new, empty session, ready for its first message (the chat of a review that has no session of its own)."""
    if not root or not os.path.isdir(root):
        raise Invalid("LFG doesn't know where this project is on disk")
    if not C.which("claude"):
        raise Invalid("Claude Code (claude) isn't on PATH")
    sid, title = str(uuid.uuid4()), _one_line(title or "New session")[:90]
    with _LOCK:
        live = _LIVE[sid] = Live(sid, rid, root, None, "default", title, resume=False, review=review)
    _remember(sid, lfg=True, rid=rid, title=title, mode="default", created=live.started, root=root, cwd=root,
              **({"review": review} if review else {}))
    return sid


def resume(rid, root, sid, review=None):
    """Continue a saved session (from the terminal, the desktop app or an earlier LFG session) here. `review`: make
    it the chat of that PR review ({"pr", "n"}); a session that already is one stays so."""
    if not re.match(r"^[0-9a-f-]{36}$", str(sid or "")):
        raise Invalid("not a session id")
    with _LOCK:
        live = _LIVE.get(sid)
        if live and live.state != "ended":
            if review:
                live.review = review
                _remember(sid, review=review)
            return {"id": sid, "live": True}
        path = transcript(sid, root)
        if not path:
            raise Invalid("that session's transcript is gone")
        _items, meta = read(path, limit=1)
        cwd = meta["cwd"] if meta["cwd"] and os.path.isdir(meta["cwd"]) else root
        mine = _index().get(sid) or {}
        review = review or mine.get("review")
        _LIVE[sid] = Live(sid, rid, cwd, mine.get("model"), mine.get("mode") or "default",
                          mine.get("title") or meta["title"] or _one_line(meta["first"]) or "Session", resume=True,
                          review=review)
    _remember(sid, lfg=True, rid=rid, resumed=C.now_iso(), **({"review": review} if review else {}))
    return {"id": sid, "live": True}


def outside(l_, meta):
    """What another window (a terminal, the desktop app) wrote to this session since its process here read it, or
    None. The process here only reads the transcript when it starts, so it would carry on from its older copy and
    split the session in two (each window then sees only its own half): see `fresh`."""
    o = (meta or {}).get("outside")
    if not (l_ and o and l_.state != "ended") or (_epoch(o["ts"]) or 0) <= l_.born:
        return None
    return {"ts": o["ts"], "where": {"claude-desktop": "the desktop app", "cli": "a terminal"}.get(o["entry"],
                                                                                                 "another window"),
            "compacted": (_epoch(meta.get("outside_compact")) or 0) > l_.born}


def reload(rid, root, sid):
    """Start this session's process again, so it reads what other windows added (a /compact, messages) from disk."""
    l_ = live(sid)
    l_._idle()
    l_.stop()
    resume(rid, root, sid)
    new = live(sid)
    for _ in range(100):  # ready once Claude Code has answered `initialize`
        if new.state != "starting":
            break
        time.sleep(0.1)
    return new


def fresh(rid, root, sid):
    """The live session, reloaded first when another window wrote to it since it started and it is free to restart.
    Returns it and whether it was reloaded."""
    l_ = live(sid)
    if l_.state != "idle" or l_.pending or l_.queued:
        return l_, False
    _items, meta = read(transcript(sid, l_.root), limit=1)
    if not outside(l_, meta):
        return l_, False
    return reload(rid, root, sid), True


def live(sid):
    l_ = _LIVE.get(sid)
    if not l_:
        raise Invalid("this session isn't running here; press Continue to start it again")
    return l_


REVIEW_BLOCK = re.compile(r"```json\s*\{[\s\S]*?\}\s*```\s*$")


def add_chips(sid, mid, changed):
    """What the reply with message id `mid` changed in the review this session is the chat of, kept by that id."""
    with _LOCK:
        d = _index()
        mine = dict(d.get(sid) or {})
        mine["chips"] = dict(mine.get("chips") or {}, **{mid: changed})
        d[sid] = mine
        C.ensure_dir(os.path.dirname(_index_path()))
        C.write_json(_index_path(), d)


def _review_items(items, chips):
    """In a review's chat, Claude's closing ```json block (the changes LFG applied) isn't shown: its replies show what
    they changed as chips instead."""
    out = []
    for it in items:
        if it.get("k") == "ai":
            shown = REVIEW_BLOCK.sub("", it["text"]).strip() if '"changes"' in it["text"] or '"new"' in it["text"] \
                else it["text"]
            it = dict(it, text=shown, **({"changed": chips[it["mid"]]} if chips.get(it.get("mid")) else {}))
            if not shown and not it.get("changed"):
                continue
        out.append(it)
    return out


def detail(rid, root, sid, limit=None):
    """One session: what was said and done (from its transcript), plus its live state and open permission prompts.
    `limit`: only the last that many items (a review's chat shows the recent part; `earlier` says how many it left)."""
    if not re.match(r"^[0-9a-f-]{36}$", str(sid or "")):
        return {"available": False, "why": "not a session id"}
    l_ = _LIVE.get(sid)
    path = transcript(sid, l_.root if l_ else root)
    items, meta = read(path, limit=max(1, min(int(limit), MAX_ITEMS)) if limit else MAX_ITEMS)
    mine = _index().get(sid) or {}
    earlier = max(0, meta.get("total", 0) - len(items))
    if mine.get("review") or mine.get("chips"):
        items = _review_items(items, mine.get("chips") or {})
    from . import headroom as H
    via = l_.via if l_ else ("headroom" if H.base_url(root, use_env=False).rstrip("/") == H.local_url() else "direct")
    return {"available": True, "id": sid, "items": items, "title": mine.get("title") or meta["title"] or
            _one_line(meta["first"]) or "New session",
            "branch": (l_.branch if l_ else None) or meta["branch"], "model": (l_.model if l_ else None) or
            meta["model"] or mine.get("model"), "mode": (l_.mode if l_ else mine.get("mode")) or "default",
            "modes": MODES, "source": "lfg" if mine.get("lfg") else
            {"claude-desktop": "desktop", "cli": "terminal"}.get(meta["entry"], "background"),
            "state": l_.state if l_ else "saved", "pending": [{k: v for k, v in p.items() if k != "raw"}
                                                              for p in (l_.pending.values() if l_ else [])],
            "queued": [REVIEW_NOTE.sub("", _text_of(q) if isinstance(q, list) else q) for q in l_.queued] if l_ else [],
            "error": l_.error if l_ else None, "forked_from": mine.get("forked_from"),
            "outside": outside(l_, meta),
            "review": mine.get("review"), "earlier": earlier,
            "cost": _cost(path) if path else None, "additions": meta.get("additions", 0),
            "deletions": meta.get("deletions", 0),
            "skills": meta["skills"], "via": via, "updated": meta["updated"], "files": meta["files"],
            "issues": meta["issues"], "pr": _pr_for(rid, (l_.branch if l_ else None) or meta["branch"]),
            "worktree_name": _wt_name(root, l_.root if l_ else meta["cwd"]),
            "activity": activity(path, meta.get("activity") or [], bool(l_ and l_.state not in ("ended", "saved")))}


EDIT_TOOLS = ("Edit", "MultiEdit", "Write", "NotebookEdit")


def changes(rid, root, sid):
    """Every file this session changed, as diffs: Claude Code keeps the exact patch of each Edit and the content of
    each new file in its transcript, so this is what the session itself did (not what git shows now, which can mix in
    other sessions and your own edits). Edits that were denied, failed or rewound are left out. One file's edits stay
    separate hunks, in order, each with when it was made. Changes made by shell commands (sed, a script, a
    formatter) aren't recorded as edits; they're listed as commands to look at."""
    if not re.match(r"^[0-9a-f-]{36}$", str(sid or "")):
        return {"available": False, "why": "not a session id"}
    l_ = _LIVE.get(sid)
    path = transcript(sid, l_.root if l_ else root)
    if not path:
        return {"available": False, "why": "This session's transcript isn't on this computer."}
    items, meta = read(path, limit=10 ** 6)
    kept = {it["id"] for it in items if it.get("k") == "tool" and it.get("name") in EDIT_TOOLS
            and "result" in it and not it.get("error")}
    shells = [{"command": _one_line(str((it.get("input") or {}).get("command") or ""))[:240], "ts": it.get("ts")}
              for it in items if it.get("k") == "tool" and it.get("name") == "Bash" and "result" in it
              and SHELL_WRITES.search(QUIET.sub(" ", str((it.get("input") or {}).get("command") or "")))]
    base = meta.get("cwd") or root or ""
    # a file in one of the project's worktrees is the project's own, under its path in that worktree
    from . import worktree as W
    trees = sorted(((os.path.realpath(t["path"]), os.path.basename(t["path"]))
                    for t in (W.listing(root) if root and os.path.isdir(root) else [])), key=lambda x: -len(x[0]))
    files, order = {}, []
    with open(path, "rb") as fh:
        for raw in fh:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            r = ev.get("toolUseResult")
            if ev.get("type") != "user" or ev.get("isSidechain") or not isinstance(r, dict) or not r.get("filePath"):
                continue
            ids = [c.get("tool_use_id") for c in (ev.get("message") or {}).get("content") or []
                   if isinstance(c, dict) and c.get("type") == "tool_result"]
            if not any(i in kept for i in ids):
                continue
            fp = r["filePath"]
            rel, tree = os.path.relpath(fp, base) if base and fp.startswith(base.rstrip("/") + "/") else fp, ""
            if rel == fp:
                real = os.path.realpath(fp)
                hit = next(((p, n) for p, n in trees if real.startswith(p + "/")), None)
                if hit:
                    rel, tree = os.path.relpath(real, hit[0]), hit[1]
            f = files.get(rel)
            if f is None:
                f = files[rel] = {"path": rel, "old_path": "", "status": "added" if r.get("type") == "create" else
                                  "modified", "additions": 0, "deletions": 0, "binary": False, "too_big": False,
                                  "hunks": [], "edits": 0, "first": ev.get("timestamp"), "last": None,
                                  "outside": rel == fp, "worktree": tree}  # outside: a scratch file or another repo
                order.append(rel)
            f["edits"] += 1
            f["last"] = ev.get("timestamp")
            when = _clock(ev.get("timestamp"))
            patch = r.get("structuredPatch") or []
            if not patch and r.get("type") == "create":
                body = str(r.get("content") or "").split("\n")
                patch = [{"oldStart": 0, "oldLines": 0, "newStart": 1, "newLines": len(body),
                          "lines": ["+" + x for x in body]}]
            for h in patch:
                old, new = int(h.get("oldStart") or 0), int(h.get("newStart") or 0)
                lines = []
                for ln in h.get("lines") or []:
                    t = ln[:1] if ln[:1] in ("+", "-", " ") else " "
                    lines.append({"t": t, "old": old if t != "+" else None, "new": new if t != "-" else None,
                                  "text": ln[1:] if ln[:1] in ("+", "-", " ") else ln})
                    old += t != "+"
                    new += t != "-"
                    f["additions"] += t == "+"
                    f["deletions"] += t == "-"
                f["hunks"].append({"header": "@@ -%s,%s +%s,%s @@%s" % (h.get("oldStart"), h.get("oldLines"),
                                   h.get("newStart"), h.get("newLines"), "  ·  edited " + when if when else ""),
                                   "lines": lines})
    out = sorted((files[k] for k in order), key=lambda f: f["outside"])  # the project's files first
    for f in out:
        if sum(len(h["lines"]) for h in f["hunks"]) > 6000:
            f["too_big"], f["hunks"] = True, []
    return {"available": True, "id": sid, "files": out, "shell": shells[-30:],
            "additions": sum(f["additions"] for f in out), "deletions": sum(f["deletions"] for f in out)}


QUIET = re.compile(r"\d?>>?\s*/dev/null|\d?>&\d")  # output thrown away, not a file written
SHELL_WRITES = re.compile(r"(\bsed\s+-i|>\s*[^&|\s]|\btee\b|\bmv\b|\bcp\b|\brm\b|\bpatch\b|"
                          r"\bgit\s+(apply|checkout|restore|"
                          r"stash|reset|mv|rm)\b|python3?\s+-\s*<<|\bprettier\b.*--write|\bruff\b.*(format|--fix)|"
                          r"\bblack\b|\bgofmt\b.*-w|\bnpm\s+(install|i)\b|\bpip\s+install\b)")


def _clock(ts):
    """An ISO timestamp as local "Oct 24, 21:05", for a hunk's edited-at label."""
    e = _epoch(ts)
    return time.strftime("%b %d, %H:%M", time.localtime(e)) if e else ""


def stop_all():
    for l_ in list(_LIVE.values()):
        if l_.state != "ended":
            l_.stop()


# ---------------------------------------------------------------- suggestions and @files for the composer

def suggestions(rid, root):
    """What to start a session on, from where this project actually is: your PR's open review comments, failing
    checks, runs in progress, your todos, uncommitted changes. Each is a ready prompt with the LFG skill for it."""
    out = []

    def add(title, prompt, skill, why, tone=""):
        if len(out) < 8 and not any(x["prompt"] == prompt for x in out):
            out.append({"title": title, "prompt": prompt, "skill": skill, "why": why, "tone": tone})
    branch = C.git_branch(root) if root else ""
    try:
        from . import prreview as PR
        for p in (C.read_json(os.path.join(PR.folder(rid), "mine.json"), {}) or {}).get("prs") or []:
            tri = PR._read(rid, p["number"], "triage.json", None) or {}
            worth = [t for t in (tri.get("threads") or {}).values() if not t.get("resolved") and not t.get("posted")
                     and (t.get("worth") or 0) >= 60]
            if worth:
                add("Fix %d review comment%s on PR #%d" % (len(worth), "" if len(worth) == 1 else "s", p["number"]),
                    "/lfg:fix the review comments worth fixing on PR #%d (%s): %s" % (
                        p["number"], p.get("headRefName"), "; ".join(_one_line(t.get("why") or t.get("body"))[:90]
                                                                    for t in worth[:4])),
                    "/lfg:fix", "%s on your PR" % ("Comments" if len(worth) > 1 else "A comment"), "warn")
    except Exception:
        pass
    try:
        from . import dash
        for r in (dash.runs(rid).get("runs") or [])[:20]:
            name = r.get("title") or r.get("slug") or r["run"]
            if r.get("ready") == "red":
                add("Fix the failing checks in “%s”" % _one_line(name)[:50],
                    "/lfg:fix the failing checks of run %s (%s)" % (r["run"], name), "/lfg:fix", "Checks failed",
                    "bad")
            elif r.get("life") == "active" and not r.get("owner"):
                add("Continue “%s”" % _one_line(name)[:56], "/lfg:lfg continue run %s: %s" % (r["run"], name),
                    "/lfg:lfg", "Run in progress" + (" on %s" % r["branch"] if r.get("branch") else ""), "on")
    except Exception:
        pass
    try:
        from . import todos as T
        for t in [t for t in T.listing()["todos"] if t.get("status") in ("in_progress", "todo")
                  and t.get("repo") in ("", rid)][:3]:
            add("Do: %s" % _one_line(t["text"])[:60], "/lfg:lfg %s" % t["text"] + ("\n\n%s" % t["notes"]
                                                                                  if t.get("notes") else ""),
                "/lfg:lfg", "From your todos" + (" (in progress)" if t["status"] == "in_progress" else ""))
    except Exception:
        pass
    if root:
        dirty = [x for x in C.run(["git", "status", "--porcelain"], cwd=root, timeout=10).stdout.splitlines() if x]
        if dirty:
            add("Check your %d uncommitted change%s" % (len(dirty), "" if len(dirty) == 1 else "s"),
                "/lfg:check the uncommitted changes on %s" % branch, "/lfg:check", "Lint, types, tests, build")
            add("Review your changes before you commit",
                "/lfg:review-coach review my uncommitted changes on %s" % branch, "/lfg:review-coach",
                "Standards, spec, blast radius")
    add("Explain how this project fits together", "/lfg:explain the architecture of this project: the main parts "
        "and how a request flows through them", "/lfg:explain", "A map of the code")
    return {"suggestions": out, "branch": branch}


_FILES = {}


def files(root, q, limit=60):
    """Tracked files and folders matching `q` for @-mentions, best first: every word of `q` in the path, matches on
    the name before matches deeper in the path, folders (ending in /) with them. Anything under a hidden folder or
    named with a leading dot (.github, .env.example, .claude) is left out."""
    if not root or not os.path.isdir(root):
        return {"files": []}
    hit = _FILES.get(root)
    if not hit or hit[0] < time.time() - 60:
        cp = C.run(["git", "ls-files"], cwd=root, timeout=20)
        paths = [p for p in (cp.stdout.splitlines() if cp.returncode == 0 else [])
                 if not any(part.startswith(".") for part in p.split("/"))]
        dirs = sorted({"/".join(p.split("/")[:i]) + "/" for p in paths for i in range(1, p.count("/") + 1)})
        hit = _FILES[root] = (time.time(), dirs + paths)
    words = [w for w in re.split(r"\s+", str(q or "").lower()) if w][:4]
    paths = hit[1]
    if words:
        paths = [p for p in paths if all(w in p.lower() for w in words)]

        def rank(p):
            name = p.rstrip("/").rsplit("/", 1)[-1].lower()
            return (not all(w in name for w in words), not name.startswith(words[0]), p.count("/"), len(p))
        paths = sorted(paths, key=rank)
    else:
        paths = [p for p in paths if p.endswith("/") and p.count("/") == 1] + \
            [p for p in paths if "/" not in p]  # nothing typed yet: the top folders and files
    return {"files": paths[:limit], "total": len(paths)}
