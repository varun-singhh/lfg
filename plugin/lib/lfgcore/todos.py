"""Todos: one list across every project, kept in ~/.lfg/todos.json (the dashboard's Todos page).

A todo is a line of text, optional notes, the project it was written in, and a status: todo, in progress, cancelled
or done. A todo becomes a Linear issue only when the user presses "Create Linear ticket" and confirms the exact
title and description: a small background Claude Code run files that one issue through the Linear MCP (the same
sign-in as /mcp; through Headroom when Claude Code is routed there), and the todo is then tagged with the issue's
id and link. Nothing else ever writes to Linear from here. Author: Varun Singh."""
import json
import os
import re
import subprocess
import time
import uuid

from . import common as C
from . import notify as N

MAX_TEXT, MAX_NOTES = 300, 8000
STATUSES = ("todo", "in_progress", "cancelled", "done")
LINEAR_URL = re.compile(r"^https://linear\.app/[\w-]+/issue/([A-Z][A-Z0-9]*-\d+)(?:/[\w%.-]*)?/?$")
LINEAR_KEY = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
TEAM_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,9}$")
JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
# The Linear MCP's create tools (the `linear` server LFG adds, or the claude.ai connector; newer servers call it
# save_issue) and the team lookup it may need. Nothing that comments on or deletes an issue.
LINEAR_TOOLS = ["mcp__%s__%s" % (srv, tool) for srv in ("linear", "claude_ai_Linear", "plugin_linear_linear")
                for tool in ("create_issue", "save_issue", "list_teams", "get_team")]
WRITE_TOOLS = [x for x in LINEAR_TOOLS if x.endswith(("create_issue", "save_issue"))]
NO_TOOLS = ["Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep", "WebFetch", "WebSearch",
            "Task", "Agent"] + ["mcp__%s__%s" % (srv, tool) for srv in ("linear", "claude_ai_Linear",
                                                                       "plugin_linear_linear")
                                for tool in ("update_issue", "create_comment", "delete_issue", "delete_comment")]
# Only the Linear MCP, no built-in tools, no skills and none of the user's plugins or hooks (project settings only,
# and ~/.lfg has none): a full session loads every MCP server and skill, which can be more than the model's window.
# The OAuth sign-in is Claude Code's own, so the `linear` server added by `lfg setup` works as is.
LEAN = ["--strict-mcp-config", "--mcp-config", json.dumps({"mcpServers": {"linear": {
    "type": "http", "url": "https://mcp.linear.app/mcp"}}}), "--disable-slash-commands", "--tools", "",
    "--setting-sources", "project"]
SIGN_IN = ("Linear isn't signed in for Claude Code: run `claude` in a terminal, type /mcp, pick linear and sign in, "
           "then press Create Linear ticket again.")


class Invalid(ValueError):
    pass


def _path():
    return C.lfg_path("todos.json")


def _load():
    d = C.read_json(_path(), None)
    d = d if isinstance(d, dict) and isinstance(d.get("todos"), list) else {"todos": []}
    for t in d["todos"]:  # lists written before statuses had a done flag
        if t.get("status") not in STATUSES:
            t["status"] = "done" if t.get("done") else "todo"
        t.pop("done", None)
    return d


def _store(d):
    from . import settings as S
    kinds = S._secret_kinds(json.dumps(d))
    if kinds:
        raise Invalid("that looks like it contains a secret (%s); leave it out" % ", ".join(kinds))
    C.ensure_dir(C.LFG_HOME)
    C.write_json(_path(), d)


def _find(d, tid):
    t = next((t for t in d["todos"] if t.get("id") == tid), None)
    if not t:
        raise Invalid("that todo is gone")
    return t


def _text(v):
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    if not v:
        raise Invalid("write the todo first")
    if len(v) > MAX_TEXT:
        raise Invalid("keep a todo under %d characters; put the rest in its notes" % MAX_TEXT)
    return v


def listing():
    """Every todo, newest first, with the status of any Linear ticket being created (finished runs read in)."""
    with N.SETTLE:
        d = _load()
        if any(_settle(t) for t in d["todos"] if t.get("linear_job")):
            _store(d)
    order = {id(t): i for i, t in enumerate(d["todos"])}  # added later = further down the file: a same-second tie
    todos = sorted(d["todos"], key=lambda t: (t.get("created") or "", order[id(t)]), reverse=True)
    lin = C.config().get("linear") or {}
    return {"available": True, "todos": todos, "statuses": list(STATUSES),
            "counts": {s: sum(1 for t in todos if t["status"] == s) for s in STATUSES},
            "linear": {"workspace": lin.get("workspace") or "", "team": lin.get("team") or ""}}


def add(text, repo=None, notes=""):
    d = _load()
    t = {"id": uuid.uuid4().hex[:10], "text": _text(text), "notes": str(notes or "")[:MAX_NOTES],
         "repo": str(repo or "")[:120], "created": C.now_iso(), "status": "todo"}
    d["todos"].append(t)
    _store(d)
    return {"saved": True, "id": t["id"]}


def update(tid, text=None, notes=None, status=None):
    d = _load()
    t = _find(d, tid)
    if text is not None:
        t["text"] = _text(text)
    if notes is not None:
        t["notes"] = str(notes)[:MAX_NOTES]
    if status is not None:
        if status not in STATUSES:
            raise Invalid("a todo is todo, in progress, cancelled or done")
        if status != t["status"]:
            t["status"], t["status_at"] = status, C.now_iso()
    _store(d)
    return {"saved": True}


def delete(tid):
    d = _load()
    _find(d, tid)
    d["todos"] = [t for t in d["todos"] if t.get("id") != tid]
    _store(d)
    return {"deleted": True}


# ---------------------------------------------------------------- Linear

def _env():
    """Claude Code's environment for the run, kept on Headroom when the user's settings route it there."""
    from . import headroom as H
    env = dict(os.environ)
    target = H.base_url(None, use_env=False)
    if target and target.rstrip("/") == H.local_url():
        env["ANTHROPIC_BASE_URL"] = target
    return env


def _prompt(title, description, team, project="", assignee=""):
    return (
        "Create exactly one new Linear issue with save_issue (no id: a new issue, never an existing one), and nothing "
        "else: no other issue, no update, no comment. The user wrote and approved this text and picked these fields; "
        "use them exactly as given.\n\n"
        "Team: %s\nProject: %s\nAssignee: %s\nTitle: %s\nDescription (markdown):\n%s\n\n"
        "Set only the fields above. Where a field says (none), leave it unset: never pick a project, assignee, label "
        "or status from the description or on your own. If Linear isn't available or signed in, or it refuses a "
        "field, create nothing and say why. Don't retry a failed create.\n\n"
        "End your reply with exactly one fenced json block: {\"identifier\": \"ABC-123\", \"url\": "
        "\"https://linear.app/...\"} when the issue was created, else {\"error\": \"one sentence\"}."
        % (team, project or "(none)", assignee or "(none)", title, description or "(none)"))


OPTIONS_TTL = 86400
OPTION_TOOLS = ["mcp__linear__list_teams", "mcp__linear__list_projects", "mcp__linear__list_users"]
OPTIONS_PROMPT = (
    "Read only. Call list_teams with limit 250, list_users with limit 250, and list_projects with limit 50 and fields "
    "[\"id\", \"name\", \"teams\", \"status\"]; whenever a result says hasNextPage is true, call the same tool again "
    "with its cursor until it is false. Don't create or change anything, and don't summarise the results: reply "
    "with just the word done.")


def _opt_path(name):
    return os.path.join(C.ensure_dir(C.lfg_path("todos")), name)


def _tool_results(raw):
    """{tool name: [parsed JSON result, ...]} from a `claude -p --output-format stream-json --verbose` transcript:
    Linear's own answers, read as they came back, so nothing in them is retyped (or dropped) by the model."""
    names, out, final = {}, {}, {}
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            final = ev
        for c in ((ev.get("message") or {}).get("content") or []) if isinstance(ev.get("message"), dict) else []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                names[c.get("id")] = str(c.get("name") or "").rsplit("__", 1)[-1]
            elif c.get("type") == "tool_result" and not c.get("is_error"):
                body = c.get("content")
                text = body if isinstance(body, str) else "".join(
                    x.get("text", "") for x in body or [] if isinstance(x, dict))
                try:
                    out.setdefault(names.get(c.get("tool_use_id"), ""), []).append(json.loads(text))
                except ValueError:
                    continue
    return out, final


def _options_from(results):
    """Teams, open projects (not completed or canceled) and active people, straight from Linear's list results."""
    def name(v, n=200):
        v = re.sub(r"\s+", " ", str(v or "")).strip()
        return v[:n] if v and not re.search(r"[\x00-\x1f]", v) else ""
    teams, projects, users = {}, {}, {}
    for r in results.get("list_teams", []):
        for t in r.get("teams") or []:
            if isinstance(t, dict) and TEAM_KEY.match(str(t.get("key") or "")) and not t.get("archivedAt"):
                teams[t["key"].upper()] = {"key": t["key"].upper(), "name": name(t.get("name")),
                                           "retired": bool(t.get("retiredAt"))}
    for r in results.get("list_projects", []):
        for p in r.get("projects") or []:
            st = str(((p.get("status") or {}) if isinstance(p, dict) else {}).get("type") or "")
            if isinstance(p, dict) and name(p.get("name")) and st not in ("completed", "canceled"):
                projects[p.get("id") or p["name"]] = {
                    "name": name(p.get("name")),
                    "teams": [str(x.get("key")).upper() for x in p.get("teams") or [] if isinstance(x, dict)
                              and str(x.get("key") or "").upper() in teams]}
    for r in results.get("list_users", []):
        for u in r.get("users") or []:
            if isinstance(u, dict) and u.get("isActive") and name(u.get("name")):
                users[u.get("id") or u["name"]] = {"name": name(u.get("name")),
                                                   "display": name(u.get("displayName"))}
    return {"teams": sorted(teams.values(), key=lambda t: (t["retired"], t["key"])),
            "projects": sorted(projects.values(), key=lambda x: x["name"].lower()),
            "users": sorted(users.values(), key=lambda x: x["name"].lower())}


def linear_options(fresh=False):
    """Linear's teams, open projects and people for the Create sheet, cached a day. Fetching is one small read-only
    background run; while it runs the answer says loading (with the last list, if any)."""
    cache, job_p = _opt_path("linear-options.json"), _opt_path("linear-options.job.json")
    hit, job = C.read_json(cache, None), C.read_json(job_p, None)
    if isinstance(job, dict) and not _alive(job.get("pid")):  # a fetch finished: read it in
        results, res = _tool_results(C.read_text(job.get("out") or ""))
        got = _options_from(results)
        if got["teams"]:
            hit = dict(got, at=time.time())
            C.write_json(cache, hit)
        else:
            why = str(res.get("result") or "")
            hit = dict(hit or {}, error=(SIGN_IN if re.search(r"auth|sign.?in|not connected", why, re.I)
                                         else "Couldn't read Linear: %s" % (why[-200:] or "no answer")))
            C.write_json(cache, hit)
        os.remove(job_p)
        job = None
    stale = not isinstance(hit, dict) or not hit.get("teams") or time.time() - hit.get("at", 0) > OPTIONS_TTL
    if (fresh or (stale and not (hit or {}).get("error"))) and not job:
        claude = C.which("claude")
        if not claude:
            raise Invalid("Claude Code (claude) isn't on PATH")
        out = _opt_path("linear-options.out")
        argv = [claude, "-p", "--output-format", "stream-json", "--verbose", "--model", (C.config().get(
            "models") or {}).get("lane-triage") or "haiku", "--max-turns", "20", "--permission-mode", "default",
            "--allowedTools", ",".join(OPTION_TOOLS),
            "--disallowedTools", ",".join(NO_TOOLS + WRITE_TOOLS)] + LEAN
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            p = subprocess.Popen(argv, cwd=C.LFG_HOME, stdin=subprocess.PIPE, stdout=fh, stderr=subprocess.STDOUT,
                                 env=_env(), start_new_session=True, close_fds=True)
        p.stdin.write(OPTIONS_PROMPT.encode())
        p.stdin.close()
        C.write_json(job_p, {"pid": p.pid, "out": out, "started": C.now_iso()})
        if isinstance(hit, dict):
            hit.pop("error", None)
        job = True
    out = {k: (hit or {}).get(k) or [] for k in ("teams", "projects", "users")}
    lin = C.config().get("linear") or {}
    return dict(out, loading=bool(job), error=(hit or {}).get("error"), default_team=lin.get("team") or "",
                at=(hit or {}).get("at"))


def create_linear(tid, title, description="", team="", project="", assignee=""):
    """The user pressed Create Linear ticket and confirmed this exact title, description, team, project and assignee
    (picked from Linear's own lists): start the one background run that files it. The todo is tagged with the
    issue's id and link when the run finishes."""
    d = _load()
    t = _find(d, tid)
    if (t.get("linear") or {}).get("key"):
        raise Invalid("this todo already has a Linear ticket, %s" % t["linear"]["key"])
    if t.get("linear_job"):
        raise Invalid("its Linear ticket is being created")
    team = (team or (C.config().get("linear") or {}).get("team") or "").strip()
    if not TEAM_KEY.match(team):
        raise Invalid("pick the Linear team for it (its key, like ATO); set a default in Settings → Linear")
    title, description = _text(title), str(description or "")[:MAX_NOTES]
    project, assignee = str(project or "").strip(), str(assignee or "").strip()
    opts = C.read_json(_opt_path("linear-options.json"), {}) or {}
    if project and not any(p.get("name") == project and (not p.get("teams") or team in p["teams"])
                           for p in opts.get("projects") or []):
        raise Invalid("%s isn't one of team %s's projects in Linear; pick one from the list" % (project, team))
    if assignee and assignee != "me" and not any(u.get("name") == assignee for u in opts.get("users") or []):
        raise Invalid("%s isn't someone in your Linear workspace; pick from the list" % assignee)
    claude = C.which("claude")
    if not claude:
        raise Invalid("Claude Code (claude) isn't on PATH")
    model = (C.config().get("models") or {}).get("lane-triage") or "haiku"
    out = os.path.join(C.ensure_dir(C.lfg_path("todos")), "linear-%s.out" % t["id"])
    argv = [claude, "-p", "--output-format", "json", "--model", model, "--max-turns", "6",
            "--permission-mode", "default", "--allowedTools", ",".join(LINEAR_TOOLS),
            "--disallowedTools", ",".join(NO_TOOLS)] + LEAN
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        p = subprocess.Popen(argv, cwd=C.LFG_HOME, stdin=subprocess.PIPE, stdout=fh, stderr=subprocess.STDOUT,
                             env=_env(), start_new_session=True, close_fds=True)
    p.stdin.write(_prompt(title, description, team, project, assignee).encode())
    p.stdin.close()
    t["linear_job"] = {"pid": p.pid, "out": out, "started": C.now_iso(), "title": title, "team": team,
                       "project": project, "assignee": assignee}
    t.pop("linear_error", None)
    _store(d)
    C.audit("todo-linear-create", {"todo": t["id"], "team": team})
    return {"started": True}


def _alive(pid):
    return N.alive(pid)


def _settle(t):
    """If the todo's Linear run finished, tag the todo with the issue (or keep why it failed). True when changed."""
    job = t.get("linear_job") or {}
    if _alive(job.get("pid")):
        return False
    raw = C.read_text(job.get("out") or "")
    try:
        res = json.loads(raw[raw.index("{"):]) if "{" in raw else {}
    except ValueError:
        res = {}
    text = str(res.get("result") or "")
    blocks = JSON_BLOCK.findall(text)
    try:
        got = json.loads(blocks[-1]) if blocks else {}
    except ValueError:
        got = {}
    key, url = str(got.get("identifier") or "").strip().upper(), str(got.get("url") or "").strip()
    m = LINEAR_URL.match(url)
    if LINEAR_KEY.match(key) and m and m.group(1) == key:
        t["linear"] = {"key": key, "url": url, "created": C.now_iso(), "team": job.get("team"),
                       "project": job.get("project") or None, "assignee": job.get("assignee") or None}
        t.pop("linear_error", None)
        N.add("linear", "%s created in Linear" % key, t.get("text", ""), "#todos", t.get("repo") or "")
    else:
        why = str(got.get("error") or "") or text.strip()[-300:] or raw.strip()[-300:] or "the run gave no answer"
        if re.search(r"auth|sign.?in|not connected|unavailable|no such tool|not available", why, re.I):
            why = SIGN_IN
        elif re.search(r"prompt is too long|context", why, re.I):
            why = "The ticket run ran out of room (%s). Nothing was created; press Try again." % why
        t["linear_error"] = why[:600]
        N.add("linear", "Linear ticket not created", "%s: %s" % (t.get("text", "")[:80], why[:200]), "#todos",
              t.get("repo") or "", ok=False)
    t.pop("linear_job", None)
    return True
