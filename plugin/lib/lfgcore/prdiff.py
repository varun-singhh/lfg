"""The Diff tab of a review: a pull request's diff, GitHub style, where you select a line or a range and talk it through
with an AI, thread by thread, the way you would in review comments. It is all local: nothing here ever goes to GitHub.

The diff is `git diff <merge-base>..<head>` of the PR, fetched into LFG's own refs (prreview._fetch), so the user's
checkout is never touched. Each thread is its own background `claude -p` conversation, read only, in the review
worktree (made when the first question is asked), so the AI can read the code around the lines; follow-ups resume
it. Only reading tools are loaded, which keeps each question to cents. Threads live in
~/.lfg/reviews/<repo-id>/pr-<n>/diffchat.json. Author: Varun Singh."""
import json
import os
import re
import subprocess
import time
import uuid

from . import common as C
from . import notify as N
from . import prreview as PR

MAX_FILE_LINES = 4000       # a bigger file's diff is listed but not shown (a lockfile, a generated bundle)
MAX_SNIPPET = 200           # selected lines handed to the AI with the question
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")


class Invalid(ValueError):
    pass


# ---------------------------------------------------------------- the diff

def _parse(text):
    """Unified diff -> [{path, old_path, status, additions, deletions, binary, too_big, hunks: [{header, lines:
    [{t: "+"|"-"|" ", old, new, text}]}]}]."""
    files, f, h, old, new = [], None, None, 0, 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"^diff --git a/(.*) b/(.*)$", line)
            f = {"path": m.group(2) if m else line[11:], "old_path": m.group(1) if m else "", "status": "modified",
                 "additions": 0, "deletions": 0, "binary": False, "too_big": False, "hunks": []}
            files.append(f)
            h = None
        elif f is None:
            continue
        elif line.startswith("new file mode"):
            f["status"] = "added"
        elif line.startswith("deleted file mode"):
            f["status"] = "deleted"
        elif line.startswith("rename from "):
            f["status"], f["old_path"] = "renamed", line[12:]
        elif line.startswith("rename to "):
            f["path"] = line[10:]
        elif line.startswith("Binary files "):
            f["binary"] = True
        elif line.startswith("@@"):
            m = HUNK.match(line)
            if m:
                old, new = int(m.group(1)), int(m.group(2))
                h = {"header": line, "lines": []}
                f["hunks"].append(h)
        elif h is not None and line[:1] in ("+", "-", " ") and not line.startswith(("+++ ", "--- ")):
            t = line[0]
            h["lines"].append({"t": t, "old": old if t != "+" else None, "new": new if t != "-" else None,
                               "text": line[1:]})
            if t != "+":
                old += 1
            if t != "-":
                new += 1
            if t == "+":
                f["additions"] += 1
            elif t == "-":
                f["deletions"] += 1
    for f in files:
        if sum(len(h["lines"]) for h in f["hunks"]) > MAX_FILE_LINES:
            f["too_big"], f["hunks"] = True, []
    return files


def _refs(rid, root, n, fresh=False):
    """(head, merge_base) the Diff tab shows: the commit the review is on when one was started (so the AI's
    worktree matches the lines), else the PR as GitHub has it now, fetched into LFG's own refs."""
    meta = PR._read(rid, n, "meta.json", None)
    if isinstance(meta, dict) and meta.get("head") and meta.get("merge_base") and not fresh:
        return meta["head"], meta["merge_base"], meta.get("base")
    chat = _load(rid, n)
    if chat.get("head") and chat.get("merge_base") and not fresh:
        return chat["head"], chat["merge_base"], chat.get("base")
    pr = PR._pr_view(root, n)
    sha, mb = PR._fetch(root, n, pr["baseRefName"], pr.get("baseRefOid"))
    chat.update(head=sha, merge_base=mb, base=pr["baseRefName"], title=pr.get("title"), url=pr.get("url"),
                pr_author=(pr.get("author") or {}).get("login"))
    _store(rid, n, chat)
    return sha, mb, pr["baseRefName"]


def _files(rid, root, n, head, mb):
    cache = os.path.join(C.ensure_dir(PR.folder(rid, n)), "diff-%s.json" % head[:12])
    files = C.read_json(cache, None)
    if not isinstance(files, list):
        cp = PR._git(root, "diff", "--no-color", "--no-ext-diff", "-M", "-U3", "%s..%s" % (mb, head), timeout=300)
        if cp.returncode:
            raise Invalid("git diff failed: %s" % (cp.stderr or cp.stdout).strip()[-300:])
        files = _parse(cp.stdout)
        C.write_json(cache, files)
    return files


def diff(rid, root, n, fresh=False):
    """The PR's diff as files and lines, plus the local AI threads on it."""
    n = PR._num(n)
    head, mb, base = _refs(rid, root, n, fresh)
    files = _files(rid, root, n, head, mb)
    chat = settle(rid, n)
    for t in chat["threads"]:
        t["outdated"] = bool(t.get("head") and t["head"] != head)
        t["start"], t["end"] = _key(t["start"], t.get("side")), _key(t["end"], t.get("side"))
    return {"available": True, "number": n, "head": head, "merge_base": mb, "base": base, "files": files,
            "threads": chat["threads"], "worktree": os.path.isdir(PR.worktree_path(root, n))}


# ---------------------------------------------------------------- threads

def _path(rid, n):
    return os.path.join(C.ensure_dir(PR.folder(rid, n)), "diffchat.json")


def _load(rid, n):
    d = C.read_json(_path(rid, n), None)
    return d if isinstance(d, dict) and isinstance(d.get("threads"), list) else {"threads": []}


def _store(rid, n, d):
    C.write_json(_path(rid, n), d)


def _worktree(rid, root, n, head):
    """The review worktree at `head`, made if needed (the same folder a review uses), never moved off a review's
    commit and never touched when it has local changes."""
    wt = PR.worktree_path(root, n)
    if not os.path.isdir(wt):
        os.makedirs(os.path.dirname(wt), exist_ok=True)
        cp = PR._git(root, "worktree", "add", "--detach", wt, head, timeout=300)
        if cp.returncode:
            raise Invalid("git worktree add failed: %s" % (cp.stderr or cp.stdout).strip()[-300:])
    return wt


def row_key(line):
    """A diff row's name, as GitHub writes it: R<new line> for added and unchanged lines, L<old line> for removed."""
    return "R%d" % line["new"] if line["new"] is not None else "L%d" % line["old"]


def _key(v, side="new"):
    """A selection end as a row key: "R131", "L88", or a bare line number on `side` (older threads, the API)."""
    v = str(v if v is not None else "").strip().upper()
    if re.match(r"^[LR]\d+$", v):
        return v
    if v.isdigit():
        return ("L" if side == "old" else "R") + v
    raise Invalid("pick the lines first")


def _selected(files, path, a, b):
    """The rows from `a` to `b` (either order, across removed and added lines, like a drag in GitHub's diff) as
    (first key, last key, the lines marked +/-/space for the AI)."""
    f = next((f for f in files if f["path"] == path), None)
    if not f:
        raise Invalid("%s isn't in this diff" % path)
    rows = [ln for h in f["hunks"] for ln in h["lines"]]
    keys = [row_key(ln) for ln in rows]
    if a not in keys or b not in keys:
        raise Invalid("those lines aren't in the diff")
    i, j = sorted((keys.index(a), keys.index(b)))
    pick = rows[i:j + 1]
    return keys[i], keys[j], "\n".join("%s %s" % (ln["t"], ln["text"]) for ln in pick[:MAX_SNIPPET])


def where(t):
    """"lines R131 to R133" / "line L88" for a thread (older threads kept side + numbers)."""
    a, b = _key(t["start"], t.get("side")), _key(t["end"], t.get("side"))
    return "%s, %s" % (t["path"], "line %s" % a if a == b else "lines %s to %s" % (a, b))


def _prompt(n, head, mb, thread, text, first):
    at = where(thread)
    if not first:
        return "%s\n\n(Same lines: %s. Stay read only; answer briefly.)" % (text, at)
    return (
        "You are answering a reviewer's question about pull request #%d, in a worktree detached at its head %s; the "
        "change is `git diff %s..HEAD`. This is a local conversation about the code, like a review comment thread: "
        "nothing goes to GitHub. Read the code around the lines and anything they touch as needed; stay read only "
        "(no edits, no commands that change anything). Answer the question directly and briefly, cite file:line, "
        "and say plainly when something is a real problem.\n\n"
        "Selected lines (%s; R = new file line, L = old file line), as they read in the diff (+ added, - removed):"
        "\n```\n%s\n```\n\nQuestion: %s" % (n, head[:12], mb[:12], at, thread["snippet"], text))


# A question about a few lines needs the code, not every MCP server, skill and plugin a full session loads (about
# 200k tokens a turn, written to the cache again on each turn): read, search and read-only git only, which starts at
# about 9k. The repo's own CLAUDE.md still loads (project settings).
DIFF_TOOLS = ["Read", "Grep", "Glob", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git blame:*)",
              "Bash(git grep:*)", "Bash(git status:*)"]
LEAN = ["--strict-mcp-config", "--mcp-config", json.dumps({"mcpServers": {}}), "--disable-slash-commands",
        "--setting-sources", "project", "--tools", "Read,Grep,Glob,Bash"]


def _argv(root, session, resume):
    model = (C.config().get("models") or {}).get("diff-chat") or "sonnet"
    argv = [C.which("claude") or "claude", "-p", "--output-format", "json", "--model", model, "--max-turns", "30",
            "--permission-mode", "default", "--allowedTools", ",".join(DIFF_TOOLS),
            "--disallowedTools", ",".join(PR.NO_TOOLS)] + LEAN
    argv += ["--resume", session] if resume else ["--session-id", session]
    return argv


def ask(rid, root, n, text, thread=None, path=None, side="new", start=None, end=None):
    """A question on selected lines (a new thread), or a follow-up in a thread. Starts the AI in the background."""
    n = PR._num(n)
    text = str(text or "").strip()
    if not text:
        raise Invalid("write a question first")
    if len(text) > 8000:
        raise Invalid("that question is too long")
    if not C.which("claude"):
        raise Invalid("Claude Code (claude) isn't on PATH")
    from . import settings as S
    if S._secret_kinds(text):
        raise Invalid("that looks like it contains a secret; leave it out")
    head, mb, _base = _refs(rid, root, n)
    files = None if thread else _files(rid, root, n, head, mb)
    chat = settle(rid, n)  # an answer that came in meanwhile
    if thread:
        t = next((x for x in chat["threads"] if x.get("id") == thread), None)
        if not t:
            raise Invalid("that thread is gone")
        if t.get("job"):
            raise Invalid("wait for the AI's answer first")
        first = False
    else:
        a = _key(start, side)
        b = _key(end if end is not None else start, side)
        first_key, last_key, snippet = _selected(files, str(path or ""), a, b)
        t = {"id": uuid.uuid4().hex[:10], "path": str(path or ""), "start": first_key, "end": last_key,
             "snippet": snippet, "head": head, "created": C.now_iso(), "messages": [],
             "session": str(uuid.uuid4()), "resolved": False}
        chat["threads"].append(t)
        first = True
    wt = _worktree(rid, root, n, head)
    t["messages"].append({"role": "me", "text": text, "ts": C.now_iso()})
    out = os.path.join(PR.folder(rid, n), "diffchat-%s-%d.out" % (t["id"], len(t["messages"])))
    env, via = PR._child_env(root)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        p = subprocess.Popen(_argv(root, t["session"], not first), cwd=wt, stdin=subprocess.PIPE, stdout=fh,
                             stderr=subprocess.STDOUT, env=env, start_new_session=True, close_fds=True)
    p.stdin.write(_prompt(n, head, mb, t, text, first).encode())
    p.stdin.close()
    t["job"] = {"pid": p.pid, "out": out, "started": C.now_iso(), "via": via, "first": first}
    t["resolved"] = False
    _store(rid, n, chat)
    return {"started": True, "thread": t["id"]}


def settle(rid, n):
    """Read in every thread answer that came back, announce each, and return the threads."""
    with N.SETTLE:
        chat = _load(rid, n)
        if any(_settle(rid, n, t) for t in chat["threads"] if t.get("job")):
            _store(rid, n, chat)
        return chat


def _alive(pid):
    return N.alive(pid)


def _settle(rid, n, t):
    """If the thread's AI answered, add the answer (or why it didn't). True when the thread changed."""
    job = t.get("job") or {}
    if _alive(job.get("pid")):
        return False
    raw = C.read_text(job.get("out") or "")
    try:
        res = json.loads(raw[raw.index("{"):]) if "{" in raw else {}
    except ValueError:
        res = {}
    text = str(res.get("result") or "").strip()
    if text and not res.get("is_error"):
        t["messages"].append({"role": "ai", "text": text, "ts": C.now_iso(), "cost": res.get("total_cost_usd"),
                              "via": job.get("via")})
    else:
        t["messages"].append({"role": "ai", "error": True, "ts": C.now_iso(),
                              "text": "The AI didn't answer: %s" % (text or raw.strip()[-400:] or "no output")})
        if job.get("first"):  # the conversation never started: a follow-up starts it again
            t["session"] = str(uuid.uuid4())
    t.pop("job", None)
    meta = PR._read(rid, n, "meta.json", None)
    last = t["messages"][-1]
    N.add("diff", ("The AI didn't answer on #%d" if last.get("error") else "The AI answered on #%d") % n,
          "%s: %s" % (where(t), last["text"].replace("\n", " ")[:160]), PR._href(meta, n, "/diff"), rid,
          ok=not last.get("error"))
    return True


def thread_action(rid, n, thread, action):
    """Resolve or reopen a thread (it folds away), or delete it. Local only, like everything here."""
    n = PR._num(n)
    chat = _load(rid, n)
    t = next((x for x in chat["threads"] if x.get("id") == thread), None)
    if not t:
        raise Invalid("that thread is gone")
    if action in ("resolve", "reopen"):
        t["resolved"] = action == "resolve"
    elif action == "delete":
        chat["threads"] = [x for x in chat["threads"] if x.get("id") != thread]
    else:
        raise Invalid("unknown action")
    _store(rid, n, chat)
    return {"saved": True, "at": time.time()}
