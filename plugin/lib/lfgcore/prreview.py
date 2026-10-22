"""Reviewing other people's pull requests from the dashboard (the Reviews page).

Each review gets its own worktree next to the repo (`<repo>.worktrees/review-pr-<n>`, detached at the PR head, which
is fetched into `refs/lfg-review/pr-<n>`), so the user's checkout and branches are never touched. A background
`claude -p` session in that worktree runs the lfg:expert skill in PR mode (graphs + dev-graph + second-brain) and
returns a grilling review; the user then talks it through in the same session and edits a draft. Nothing reaches
GitHub until the user presses Post, which sends one review through `gh api`.

State lives in ~/.lfg/reviews/<repo-id>/pr-<n>/: meta.json, draft.json, chat.jsonl, job.json (a running AI turn)
and job-<k>.out (its raw output). Author: Varun Singh."""
import json
import os
import re
import subprocess
import time
import uuid

from . import common as C
from . import worktree as W

PR_FIELDS = "number,title,author,url,headRefName,baseRefName,headRefOid,updatedAt,isDraft,additions,deletions," \
            "changedFiles"
AREAS = ["Correctness", "Design", "Tests", "Security", "Readability", "Fits the codebase"]
EVENTS = ("COMMENT", "REQUEST_CHANGES", "APPROVE")
READ_TOOLS = ["Read", "Grep", "Glob", "Skill", "Agent", "Task", "TodoWrite",
              "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git status:*)",
              "Bash(git merge-base:*)", "Bash(git rev-parse:*)", "Bash(git blame:*)", "Bash(lfg graphs:*)",
              "Bash(lfg rule:*)", "Bash(lfg lane:*)", "Bash(graphify:*)", "Bash(gh pr view:*)", "Bash(gh pr diff:*)",
              "mcp__code-review-graph", "mcp__dev-graph", "mcp__second-brain",
              "mcp__plugin_lfg_code-review-graph", "mcp__plugin_lfg_dev-graph", "mcp__plugin_lfg_second-brain"]
NO_TOOLS = ["Edit", "Write", "MultiEdit", "NotebookEdit"]


class Invalid(ValueError):
    pass


def folder(rid, n=None):
    return C.lfg_path("reviews", rid, *(["pr-%d" % int(n)] if n is not None else []))


def _num(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise Invalid("not a pull request number") from None
    if not 0 < n < 10 ** 7:
        raise Invalid("not a pull request number")
    return n


def _gh(root, *args, timeout=60, input=None):
    if input is None:
        return C.run(["gh", *args], cwd=root, timeout=timeout)
    try:
        return subprocess.run(["gh", *args], cwd=root, timeout=timeout, input=input, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _git(path, *args, timeout=120):
    return C.run(["git", *args], cwd=path, timeout=timeout)


def worktree_path(root, n):
    return os.path.join(W.base_dir(root), "review-pr-%d" % n)


def _ref(n, base=False):
    return "refs/lfg-review/pr-%d%s" % (n, "-base" if base else "")


def _read(rid, n, name, default):
    return C.read_json(os.path.join(folder(rid, n), name), default)


def _write(rid, n, name, data):
    C.write_json(os.path.join(C.ensure_dir(folder(rid, n)), name), data)


def chat(rid, n):
    out = []
    for line in C.read_text(os.path.join(folder(rid, n), "chat.jsonl")).splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _say(rid, n, role, text, **extra):
    p = os.path.join(C.ensure_dir(folder(rid, n)), "chat.jsonl")
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(dict({"role": role, "text": text, "ts": C.now_iso()}, **extra)) + "\n")


# ---------------------------------------------------------------- the list

def pending(rid, root, fresh=False):
    """PRs waiting on the user's review (`gh pr list --search review-requested:@me`), plus PRs they already started
    reviewing here. Cached for 5 minutes; `fresh` asks GitHub again (the Refresh button)."""
    cache = os.path.join(C.ensure_dir(folder(rid)), "pending.json")
    hit = C.read_json(cache, None)
    if fresh or not isinstance(hit, dict) or time.time() - hit.get("at", 0) > 300:
        if not C.which("gh"):
            return {"available": False, "why": "the GitHub CLI (gh) isn't installed"}
        cp = _gh(root, "pr", "list", "--search", "review-requested:@me", "--json", PR_FIELDS, "--limit", "50")
        if cp.returncode:
            err = (cp.stderr or cp.stdout).strip()
            if "auth" in err.lower() or "login" in err.lower():
                err = "gh isn't signed in: run `gh auth login` in your terminal"
            return {"available": False, "why": err[-300:] or "gh pr list failed"}
        try:
            prs = json.loads(cp.stdout or "[]")
        except ValueError:
            return {"available": False, "why": "gh returned something unexpected"}
        hit = {"at": time.time(), "prs": prs}
        C.write_json(cache, hit)
    prs = {p["number"]: dict(p, requested=True) for p in hit.get("prs") or []}
    for d in sorted(os.listdir(folder(rid))) if os.path.isdir(folder(rid)) else []:
        m = re.match(r"^pr-(\d+)$", d)
        meta = _read(rid, int(m.group(1)), "meta.json", None) if m else None
        if isinstance(meta, dict) and meta.get("status") != "closed" and meta["number"] not in prs:
            prs[meta["number"]] = dict(meta.get("pr") or {}, number=meta["number"], requested=False,
                                       author=meta.get("author"))
    out = []
    for n, p in sorted(prs.items(), key=lambda kv: kv[1].get("updatedAt") or "", reverse=True):
        st = state(rid, n, root, p)
        out.append(dict(p, author=(p.get("author") or {}).get("login") if isinstance(p.get("author"), dict)
                        else p.get("author"), review=st))
    return {"available": True, "prs": out, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                                                       time.localtime(hit.get("at", 0)))}


def state(rid, n, root, pr=None):
    """Where this repo's review of PR n is: not started, reviewing (the AI is working), ready, posted, and whether
    new commits arrived after the commit being reviewed."""
    settle(rid, n)
    meta = _read(rid, n, "meta.json", None)
    if not isinstance(meta, dict):
        return {"status": "new"}
    job = _read(rid, n, "job.json", None)
    head = (pr or {}).get("headRefOid") or ""
    return {"status": "working" if job else meta.get("status", "ready"), "job": (job or {}).get("kind"),
            "worktree": meta.get("worktree"), "worktree_name": os.path.basename(meta.get("worktree") or ""),
            "reviewed_sha": meta.get("head"), "new_commits": bool(head and meta.get("head") and head != meta["head"]),
            "posted": meta.get("posted")}


# ---------------------------------------------------------------- starting a review

def _pr_view(root, n):
    cp = _gh(root, "pr", "view", str(n), "--json", PR_FIELDS + ",body,baseRefOid")
    if cp.returncode:
        raise Invalid("gh couldn't read PR #%d: %s" % (n, (cp.stderr or cp.stdout).strip()[-300:]))
    return json.loads(cp.stdout)


def _fetch(root, n, base, base_sha=None):
    """Fetch the PR head and its base into LFG's own refs (never a branch, never the user's checkout). When the
    base branch is gone (deleted after a merge), the base commit GitHub recorded for the PR is fetched instead."""
    cp = _git(root, "fetch", "--no-tags", "origin", "+refs/pull/%d/head:%s" % (n, _ref(n)), timeout=300)
    if cp.returncode:
        raise Invalid("git fetch failed: %s" % (cp.stderr or cp.stdout).strip()[-300:])
    cp = _git(root, "fetch", "--no-tags", "origin", "+refs/heads/%s:%s" % (base, _ref(n, True)), timeout=300)
    if cp.returncode and base_sha:
        cp = _git(root, "fetch", "--no-tags", "origin", "+%s:%s" % (base_sha, _ref(n, True)), timeout=300)
    if cp.returncode:
        raise Invalid("git fetch of the base %s failed: %s" % (base, (cp.stderr or cp.stdout).strip()[-300:]))
    sha = _git(root, "rev-parse", _ref(n)).stdout.strip()
    mb = _git(root, "merge-base", _ref(n, True), _ref(n)).stdout.strip()
    return sha, mb


def _prepare(rid, root, n, mode):
    """Fetch the PR and put its head in the review worktree (made once, reused). Returns (pr, meta)."""
    if _busy(rid, n):
        raise Invalid("the AI is already working on this pull request")
    pr = _pr_view(root, n)
    sha, mb = _fetch(root, n, pr["baseRefName"], pr.get("baseRefOid"))
    wt = worktree_path(root, n)
    if not os.path.isdir(wt):
        os.makedirs(W.base_dir(root), exist_ok=True)
        cp = _git(root, "worktree", "add", "--detach", wt, _ref(n), timeout=300)
        if cp.returncode:
            raise Invalid("git worktree add failed: %s" % (cp.stderr or cp.stdout).strip()[-300:])
    elif _git(wt, "status", "--porcelain").stdout.strip():
        raise Invalid("%s has local changes; LFG won't move it" % wt)
    else:
        _git(wt, "checkout", "--detach", _ref(n))
    meta = _read(rid, n, "meta.json", None) or {}
    if (chat(rid, n) or [{}])[-1].get("error"):  # the last AI run failed: start over in a fresh session
        meta.update(session=None, ai_started=False)
    session = meta.get("session") or str(uuid.uuid4())
    meta.update(number=n, worktree=wt, head=sha, merge_base=mb, base=pr["baseRefName"], session=session,
                base_sha=pr.get("baseRefOid"),
                url=pr.get("url"), started=meta.get("started") or C.now_iso(), status="working",
                pr={k: pr.get(k) for k in ("title", "url", "headRefName", "baseRefName", "headRefOid", "updatedAt",
                                           "additions", "deletions", "changedFiles", "isDraft")},
                author=(pr.get("author") or {}).get("login"))
    meta.pop("posted", None)
    meta["mode"] = mode
    _write(rid, n, "meta.json", meta)
    return pr, meta


def start(rid, root, n):
    """Make (or reuse) the review worktree at the PR head and start the AI's first pass in the background."""
    n = _num(n)
    pr, meta = _prepare(rid, root, n, "review")
    sha, mb = meta["head"], meta["merge_base"]
    if not _read(rid, n, "draft.json", None):
        _write(rid, n, "draft.json", {"summary": "", "event": "COMMENT", "include_ratings": True, "comments": [],
                                      "ratings": [{"area": a, "ai": None, "mine": None, "why": ""} for a in AREAS],
                                      "questions": []})
    _run(rid, root, n, "review", _first_prompt(pr, sha, mb), resume=bool(meta.get("ai_started")))
    meta["ai_started"] = True
    _write(rid, n, "meta.json", meta)
    return {"started": True, "worktree": meta["worktree"]}


SCHEMA = """```json
{"summary": "2-4 sentences for the PR author: what the change does and the main things to fix",
 "verdict": "approve | changes | block",
 "ratings": [{"area": "Correctness | Design | Tests | Security | Readability | Fits the codebase",
              "score": 1-5, "why": "one sentence, citing file:line or a dev-graph node"}],
 "questions": [{"id": "Q1", "ask": "a question for the reviewer to decide or to ask the author",
                "why": "what the answer changes"}],
 "comments": [{"id": "C1", "path": "repo/relative/file.ts", "line": 42,
               "body": "the comment as it would be posted: what, why, and the fix",
               "severity": "blocker | major | minor | nit", "source": "standard, spec line or dev-graph node"}],
 "context": ["each dev-graph / second-brain node or doc you relied on, one line each"]}
```"""


def _first_prompt(pr, sha, mb):
    body = (pr.get("body") or "").strip()[:6000] or "(no description)"
    return (
        "PR mode review for the dashboard. Review pull request #%d \"%s\" by @%s in this worktree: it is detached at "
        "the PR head %s; the base is %s and the change is `git diff %s..HEAD` (merge-base). Load the lfg:expert "
        "skill and follow its PR mode: review Standards, Spec (against the PR description below) and Blast radius "
        "with the code graphs, and check dev-graph (Principles, Invariants, Decisions, Gaps for the components it "
        "touches) and second-brain notes so no known context is missed.\n\n"
        "This is a grilling review for me, the human reviewer: rate each area 1-5 with the reason, ask me the "
        "questions a sharp reviewer would want answered before approving, and draft the comments I could post, "
        "each on a changed line where possible. Be specific and honest; no padding.\n\n"
        "Read only: don't edit files, don't start an LFG run, don't write to GitHub.\n\n"
        "PR description:\n%s\n\n"
        "End your reply with exactly one fenced json block in this shape:\n%s"
        % (pr["number"], pr.get("title", ""), (pr.get("author") or {}).get("login", "?"), sha[:12],
           pr.get("baseRefName"), mb[:12], body, SCHEMA))


def _chat_prompt(text, draft):
    keep = {k: draft.get(k) for k in ("summary", "comments", "ratings", "questions")}
    return (
        "%s\n\n---\nMy current draft (I may have edited it):\n```json\n%s\n```\n"
        "Stay read-only. If your answer changes the draft, end with one fenced json block holding only the keys "
        "you change (summary, verdict, ratings, questions, comments; comments is then the complete new list, "
        "keeping my edits unless I asked otherwise)." % (text, json.dumps(keep, indent=1)[:20000]))


def _claude_argv(root, session, resume):
    model = (C.config().get("models") or {}).get("expert-review") or "opus"
    argv = [C.which("claude") or "claude", "-p", "--output-format", "json", "--model", model,
            "--permission-mode", "default", "--max-turns", "80",
            "--allowedTools", ",".join(READ_TOOLS), "--disallowedTools", ",".join(NO_TOOLS)]
    argv += ["--resume", session] if resume else ["--session-id", session]
    local = os.path.join(C.main_root(root), ".claude", "settings.local.json")
    if os.path.exists(local):  # LFG's switch for this repo (plugin, brains, guard); a worktree has no copy
        argv += ["--settings", local]
    return argv


def _run(rid, root, n, kind, prompt, resume):
    if not C.which("claude"):
        raise Invalid("Claude Code (claude) isn't on PATH")
    meta = _read(rid, n, "meta.json", {})
    k = int(time.time())
    out = os.path.join(folder(rid, n), "job-%d.out" % k)
    ask_file = os.path.join(folder(rid, n), "job-%d.in" % k)
    C.write_text(ask_file, prompt)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh, open(ask_file, "rb") as fin:  # the prompt goes in on stdin, never on argv
        p = subprocess.Popen(_claude_argv(root, meta["session"], resume), cwd=meta["worktree"],
                             stdout=fh, stderr=subprocess.STDOUT, stdin=fin,
                             start_new_session=True, close_fds=True)
    _write(rid, n, "job.json", {"pid": p.pid, "kind": kind, "out": out, "started": C.now_iso()})


# ---------------------------------------------------------------- talking it through

def ask(rid, root, n, text):
    n = _num(n)
    text = str(text or "").strip()
    if not text:
        raise Invalid("write something first")
    if len(text) > 8000:
        raise Invalid("that message is too long")
    if not isinstance(_read(rid, n, "meta.json", None), dict):
        raise Invalid("start the review first")
    if _busy(rid, n):
        raise Invalid("wait for the AI to finish its current answer")
    _say(rid, n, "me", text)
    meta = _read(rid, n, "meta.json", {})
    prompt = _triage_chat_prompt(text, _read(rid, n, "triage.json", {})) if meta.get("mode") == "triage" \
        else _chat_prompt(text, _read(rid, n, "draft.json", {}))
    _run(rid, root, n, "chat", prompt, resume=True)
    meta["status"] = "working"
    _write(rid, n, "meta.json", meta)
    return {"started": True}


JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def _busy(rid, n):
    """Is the AI still working on this PR? A finished run is read in first (settle), so a result nobody has looked
    at yet never blocks the next action."""
    settle(rid, n)
    return bool(_read(rid, n, "job.json", None))


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def settle(rid, n):
    """If the AI's background turn has finished, read its answer into the chat and the draft."""
    job = _read(rid, n, "job.json", None)
    if not isinstance(job, dict) or _alive(job.get("pid")):
        return
    raw = C.read_text(job.get("out") or "")
    try:
        res = json.loads(raw[raw.index("{"):]) if "{" in raw else {}
    except ValueError:
        res = {}
    text = str(res.get("result") or "")
    meta = _read(rid, n, "meta.json", {})
    if not text or res.get("is_error"):
        why = text or raw.strip()[-600:] or "no output"
        if re.search(r"401|authenticat|token passed", why, re.I):
            why += ("\n\nThe API refused Claude Code's sign-in. LFG's reviews run as a terminal Claude Code session "
                    "would in this repo (through Headroom if it routes the repo), so check that `claude` works in a "
                    "terminal there, and Integrations → Headroom's destination.")
        _say(rid, n, "ai", "The AI run didn't finish: %s" % why, error=True)
        if job.get("kind") in ("review", "triage"):  # the first pass failed: Try again starts a fresh session
            meta.update(session=str(uuid.uuid4()), ai_started=False)
    else:
        blocks = JSON_BLOCK.findall(text)
        shown = JSON_BLOCK.sub("", text).strip()
        changed = []
        if blocks:
            try:
                changed = apply(rid, n, json.loads(blocks[-1]))
            except ValueError:
                shown += "\n\n(The draft update it sent wasn't valid JSON, so the draft is unchanged.)"
        _say(rid, n, "ai", shown or "Updated the draft.", changed=changed, cost=res.get("total_cost_usd"))
    meta["status"] = "ready"
    _write(rid, n, "meta.json", meta)
    try:
        os.remove(os.path.join(folder(rid, n), "job.json"))
    except OSError:
        pass


def apply(rid, n, upd):
    """Merge an AI update into the draft. The reviewer's own scores, answers and include switches are kept."""
    if not isinstance(upd, dict):
        return []
    if isinstance(upd.get("threads"), list):
        return apply_triage(rid, n, upd["threads"])
    d = _read(rid, n, "draft.json", {}) or {}
    changed = []
    if isinstance(upd.get("summary"), str):
        d["summary"], changed = upd["summary"].strip()[:20000], changed + ["summary"]
    if upd.get("verdict") in ("approve", "changes", "block"):
        d["ai_verdict"] = upd["verdict"]
        changed.append("verdict")
    if isinstance(upd.get("ratings"), list):
        mine = {r.get("area"): r for r in d.get("ratings") or []}
        for r in upd["ratings"]:
            if not isinstance(r, dict) or not r.get("area"):
                continue
            cur = mine.setdefault(r["area"], {"area": r["area"], "mine": None})
            score = r.get("score")
            cur.update(ai=score if isinstance(score, int) and 1 <= score <= 5 else None,
                       why=str(r.get("why") or "")[:1000])
        d["ratings"] = list(mine.values())
        changed.append("ratings")
    if isinstance(upd.get("questions"), list):
        old = {q.get("id"): q for q in d.get("questions") or []}
        d["questions"] = [dict(id=str(q.get("id") or "Q%d" % i), ask=str(q.get("ask") or "")[:2000],
                               why=str(q.get("why") or "")[:1000],
                               answer=(old.get(q.get("id")) or {}).get("answer", ""))
                          for i, q in enumerate(upd["questions"], 1) if isinstance(q, dict) and q.get("ask")]
        changed.append("questions")
    if isinstance(upd.get("comments"), list):
        old = {c.get("id"): c for c in d.get("comments") or []}
        d["comments"] = [_comment(c, old.get(c.get("id")), i) for i, c in enumerate(upd["comments"], 1)
                         if isinstance(c, dict) and c.get("body")]
        changed.append("comments")
    if isinstance(upd.get("context"), list):
        d["context"] = [str(x)[:500] for x in upd["context"][:40]]
    _write(rid, n, "draft.json", d)
    return changed


def _comment(c, old, i):
    line = c.get("line")
    return {"id": str(c.get("id") or "C%d" % i), "path": str(c.get("path") or "")[:500],
            "line": line if isinstance(line, int) and line > 0 else None, "body": str(c["body"])[:20000],
            "severity": str(c.get("severity") or "")[:20], "source": str(c.get("source") or "")[:300],
            "include": (old or {}).get("include", True)}


def save_draft(rid, n, draft):
    """The reviewer's own edits: summary, event, scores, answers, comment text and include switches."""
    n = _num(n)
    if not isinstance(draft, dict):
        raise Invalid("expected the draft")
    d = _read(rid, n, "draft.json", None)
    if not isinstance(d, dict):
        raise Invalid("start the review first")
    if isinstance(draft.get("summary"), str):
        d["summary"] = draft["summary"][:20000]
    if draft.get("event") in EVENTS:
        d["event"] = draft["event"]
    if isinstance(draft.get("include_ratings"), bool):
        d["include_ratings"] = draft["include_ratings"]
    if isinstance(draft.get("ratings"), list):
        mine = {r.get("area"): r.get("mine") for r in draft["ratings"] if isinstance(r, dict)}
        for r in d.get("ratings") or []:
            v = mine.get(r.get("area"), r.get("mine"))
            r["mine"] = v if isinstance(v, int) and 1 <= v <= 5 else None
    if isinstance(draft.get("questions"), list):
        ans = {q.get("id"): str(q.get("answer") or "")[:4000] for q in draft["questions"] if isinstance(q, dict)}
        for q in d.get("questions") or []:
            q["answer"] = ans.get(q.get("id"), q.get("answer", ""))
    if isinstance(draft.get("comments"), list):
        old = {c.get("id"): c for c in d.get("comments") or []}
        out = []
        for i, c in enumerate(draft["comments"], 1):
            if not isinstance(c, dict) or not str(c.get("body") or "").strip():
                continue
            base = dict(old.get(c.get("id")) or {})
            base.update(_comment(c, base, i), include=bool(c.get("include", True)))
            out.append(base)
        d["comments"] = out
    from . import settings as S
    kinds = S._secret_kinds(json.dumps(d))
    if kinds:
        raise Invalid("the draft looks like it contains a secret (%s); remove it first" % ", ".join(kinds))
    _write(rid, n, "draft.json", d)
    return {"saved": True}


# ---------------------------------------------------------------- new commits, posting, closing

def update(rid, root, n):
    """New commits on the PR: move the worktree to the new head and ask the AI to re-check what changed."""
    n = _num(n)
    meta = _read(rid, n, "meta.json", None)
    if not isinstance(meta, dict):
        raise Invalid("start the review first")
    if _busy(rid, n):
        raise Invalid("wait for the AI to finish its current answer")
    old = meta.get("head")
    sha, mb = _fetch(root, n, meta["base"], meta.get("base_sha"))
    if sha == old:
        return {"updated": False}
    if _git(meta["worktree"], "status", "--porcelain").stdout.strip():
        raise Invalid("%s has local changes; LFG won't move it" % meta["worktree"])
    cp = _git(meta["worktree"], "checkout", "--detach", _ref(n))
    if cp.returncode:
        raise Invalid("couldn't move the worktree: %s" % (cp.stderr or cp.stdout).strip()[-300:])
    meta.update(head=sha, merge_base=mb, status="working")
    _write(rid, n, "meta.json", meta)
    note = "New commits were pushed (%s..%s)." % ((old or "?")[:12], sha[:12])
    _say(rid, n, "me", note + " Re-check them.", auto=True)
    _run(rid, root, n, "chat", _chat_prompt(
        note + " Review `git diff %s..HEAD` and update the draft: drop comments the new commits resolved and add "
               "any new ones." % old, _read(rid, n, "draft.json", {})), resume=True)
    return {"updated": True, "head": sha}


def _diff_lines(meta):
    """{path: set(new-side line numbers)} GitHub accepts comments on: the lines of each diff hunk."""
    cp = _git(meta["worktree"], "diff", "--no-color", "-U3", "%s..%s" % (meta["merge_base"], meta["head"]),
              timeout=300)
    out, path = {}, None
    for line in (cp.stdout or "").splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                out.setdefault(path, set()).update(range(start, start + count))
    return out


def outgoing(rid, n):
    """Exactly what Post sends: the review body, its event, and which comments go inline or into the body."""
    n = _num(n)
    meta, d = _read(rid, n, "meta.json", None), _read(rid, n, "draft.json", None)
    if not isinstance(meta, dict) or not isinstance(d, dict):
        raise Invalid("start the review first")
    lines = _diff_lines(meta)
    inline, loose = [], []
    for c in d.get("comments") or []:
        if not c.get("include", True):
            continue
        if c.get("path") and c.get("line") and c["line"] in lines.get(c["path"], ()):
            inline.append({"path": c["path"], "line": c["line"], "side": "RIGHT", "body": c["body"]})
        else:
            loose.append(c)
    body = (d.get("summary") or "").strip()
    rated = [r for r in d.get("ratings") or [] if r.get("mine")]
    if d.get("include_ratings") and rated:
        body += "\n\n| Area | Rating |\n|---|---|\n" + "\n".join("| %s | %d/5 |" % (r["area"], r["mine"])
                                                              for r in rated)
    if loose:
        body += "\n\n" + "\n\n".join(("**%s%s**: " % (c["path"], ":%d" % c["line"] if c.get("line") else "")
                                      if c.get("path") else "") + c["body"] for c in loose)
    return {"event": d.get("event") if d.get("event") in EVENTS else "COMMENT", "body": body.strip(),
            "commit_id": meta["head"], "comments": inline, "in_body": len(loose)}


def post(rid, root, n):
    """Send the review to GitHub as one review. Only from the dashboard's Post button, after the user confirmed."""
    n = _num(n)
    meta = _read(rid, n, "meta.json", None)
    if not isinstance(meta, dict):
        raise Invalid("start the review first")
    if meta.get("posted"):
        raise Invalid("this review was already posted")
    out = outgoing(rid, n)
    if not out["body"] and not out["comments"]:
        raise Invalid("there is nothing to post yet")
    from . import settings as S
    kinds = S._secret_kinds(json.dumps(out))
    if kinds:
        raise Invalid("the review looks like it contains a secret (%s); remove it first" % ", ".join(kinds))
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/\d+", meta.get("url") or "")
    if not m:
        raise Invalid("couldn't tell which GitHub repo this PR is in")
    payload = {k: out[k] for k in ("event", "body", "commit_id", "comments")}
    cp = _gh(root, "api", "-X", "POST", "repos/%s/pulls/%d/reviews" % (m.group(1), n), "--input", "-",
             input=json.dumps(payload), timeout=120)
    if cp.returncode:
        raise Invalid("GitHub refused it: %s" % (cp.stdout or cp.stderr).strip()[-500:])
    try:
        url = json.loads(cp.stdout).get("html_url")
    except ValueError:
        url = None
    meta.update(posted={"at": C.now_iso(), "url": url, "event": out["event"], "inline": len(out["comments"])},
                status="posted")
    _write(rid, n, "meta.json", meta)
    C.audit("review-posted", {"repo": rid, "pr": n, "event": out["event"], "comments": len(out["comments"])})
    return {"posted": True, "url": url}


def close(rid, root, n):
    """Done with this review: remove its worktree and refs. The chat and draft stay in ~/.lfg/reviews."""
    n = _num(n)
    meta = _read(rid, n, "meta.json", None)
    if not isinstance(meta, dict):
        raise Invalid("no review here")
    if _busy(rid, n):
        raise Invalid("wait for the AI to finish its current answer")
    wt = meta.get("worktree")
    if wt and os.path.isdir(wt):
        if _git(wt, "status", "--porcelain").stdout.strip():
            raise Invalid("%s has local changes; LFG won't remove it" % wt)
        cp = _git(root, "worktree", "remove", wt)
        if cp.returncode:
            raise Invalid((cp.stderr or cp.stdout).strip()[-300:])
    for ref in (_ref(n), _ref(n, True)):
        _git(root, "update-ref", "-d", ref)
    meta["status"] = "closed"
    _write(rid, n, "meta.json", meta)
    return {"closed": True}


def detail(rid, root, n):
    n = _num(n)
    settle(rid, n)
    meta = _read(rid, n, "meta.json", None)
    pr = None
    for p in (C.read_json(os.path.join(folder(rid), "pending.json"), {}) or {}).get("prs") or []:
        if p.get("number") == n:
            pr = dict(p, author=(p.get("author") or {}).get("login") if isinstance(p.get("author"), dict)
                      else p.get("author"))
    if not isinstance(meta, dict):
        return {"number": n, "pr": pr, "review": {"status": "new"}, "worktree_to_be": worktree_path(root, n)}
    job = _read(rid, n, "job.json", None)
    draft = _read(rid, n, "draft.json", {}) or {}
    if meta.get("worktree") and os.path.isdir(meta["worktree"]):
        lines = _diff_lines(meta)
        for c in draft.get("comments") or []:
            c["inline"] = bool(c.get("path") and c.get("line") and c["line"] in lines.get(c["path"], ()))
        draft["files"] = sorted(lines)
    return {"number": n, "pr": pr or dict(meta.get("pr") or {}, number=n, author=meta.get("author")),
            "review": state(rid, n, root, pr), "meta": {k: meta.get(k) for k in ("head", "merge_base", "base",
                                                                              "worktree", "started", "posted")},
            "draft": draft, "chat": chat(rid, n),
            "working_since": (job or {}).get("started")}


# ---------------------------------------------------------------- your own PRs: triage the comments you got

THREADS_Q = """query($o: String!, $r: String!, $n: Int!) { repository(owner: $o, name: $r) { pullRequest(number: $n) {
  reviewThreads(first: 100) { nodes { id isResolved isOutdated path line originalLine
    comments(first: 50) { nodes { databaseId author { login __typename } body url createdAt } } } }
  reviews(first: 60) { nodes { databaseId author { login __typename } body state url } }
  comments(first: 100) { nodes { databaseId author { login __typename } body url } } } } }"""


def me(root):
    """The signed-in GitHub login (cached a day)."""
    p = C.lfg_path("state", "gh-user.json")
    hit = C.read_json(p, None)
    if isinstance(hit, dict) and time.time() - hit.get("at", 0) < 86400 and hit.get("login"):
        return hit["login"]
    cp = _gh(root, "api", "user", "--jq", ".login")
    login = (cp.stdout or "").strip() if cp.returncode == 0 else ""
    if login:
        C.write_json(p, {"at": time.time(), "login": login})
    return login


def mine(rid, root, fresh=False):
    """Your open pull requests in this repo, newest first (the "Your pull requests" tab)."""
    cache = os.path.join(C.ensure_dir(folder(rid)), "mine.json")
    hit = C.read_json(cache, None)
    if fresh or not isinstance(hit, dict) or time.time() - hit.get("at", 0) > 300:
        cp = _gh(root, "pr", "list", "--author", "@me", "--json", PR_FIELDS + ",reviewDecision", "--limit", "50")
        if cp.returncode:
            return {"available": False, "why": (cp.stderr or cp.stdout).strip()[-300:] or "gh pr list failed"}
        hit = {"at": time.time(), "prs": json.loads(cp.stdout or "[]")}
        C.write_json(cache, hit)
    out = []
    for p in hit.get("prs") or []:
        tri = _read(rid, p["number"], "triage.json", None) or {}
        th = tri.get("threads") or {}
        live = [t for t in th.values() if not t.get("resolved") and not t.get("posted")]
        out.append(dict(p, author=(p.get("author") or {}).get("login"), review=state(rid, p["number"], root, p),
                        open_threads=len(live),
                        worth_open=sum(1 for t in live if (t.get("worth") or 0) >= 30),
                        low_open=sum(1 for t in live if t.get("worth") is not None and t["worth"] < 30),
                        decided=sum(1 for t in th.values() if t.get("decision") and not t.get("posted"))))
    return {"available": True, "prs": out, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                                                       time.localtime(hit.get("at", 0)))}


def _clean(body):
    """A comment as a person reads it: no hidden HTML comments (bots stash state there), no "Prompt for AI Agents"
    block (instructions aimed at whoever reads the comment, which the AI reviewer must not take as orders),
    `<summary>` titles as bold lines and the rest of the HTML tags dropped. Code blocks stay."""
    body = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    body = re.sub(r"<details>\s*<summary>[^<]*Prompt for AI[^<]*</summary>.*?</details>", "", body, flags=re.S | re.I)
    body = re.sub(r"<summary>\s*(.*?)\s*</summary>", r"\n**\1**\n", body, flags=re.S | re.I)
    body = re.sub(r"</?(details|summary|br|p|div|span|sub|sup|b|i|em|strong)\b[^>]*>", "", body, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", body).strip()[:8000]


def _bot(a):
    return (a or {}).get("__typename") == "Bot" or (a or {}).get("login", "").endswith("[bot]")


def threads(root, url, n):
    """Every comment thread on the PR that someone else started: inline review threads (with resolved/outdated),
    review summaries and general comments from people. Bots' inline comments count; their summaries and notices
    don't."""
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/\d+", url or "")
    if not m:
        raise Invalid("couldn't tell which GitHub repo this PR is in")
    cp = _gh(root, "api", "graphql", "-f", "query=" + THREADS_Q, "-f", "o=" + m.group(1), "-f", "r=" + m.group(2),
             "-F", "n=%d" % n, timeout=120)
    if cp.returncode:
        raise Invalid("gh couldn't read the comments: %s" % (cp.stderr or cp.stdout).strip()[-300:])
    pr = (((json.loads(cp.stdout).get("data") or {}).get("repository") or {}).get("pullRequest")) or {}
    who = me(root)
    out = []
    for t in (pr.get("reviewThreads") or {}).get("nodes") or []:
        cs = (t.get("comments") or {}).get("nodes") or []
        if not cs or (cs[0].get("author") or {}).get("login") == who:
            continue
        out.append({"id": "t-%s" % cs[0]["databaseId"], "kind": "inline", "reply_to": cs[0]["databaseId"],
                    "author": (cs[0].get("author") or {}).get("login"), "bot": _bot(cs[0].get("author")),
                    "path": t.get("path"), "line": t.get("line") or t.get("originalLine"), "url": cs[0].get("url"),
                    "body": _clean(cs[0].get("body")), "resolved": bool(t.get("isResolved")),
                    "outdated": bool(t.get("isOutdated")),
                    "replies": [{"author": (c.get("author") or {}).get("login"), "body": _clean(c.get("body"))[:2000]}
                                for c in cs[1:]],
                    "you_replied": any((c.get("author") or {}).get("login") == who for c in cs[1:])})
    for kind, key in (("review", "reviews"), ("comment", "comments")):
        for c in (pr.get(key) or {}).get("nodes") or []:
            a = c.get("author") or {}
            body = _clean(c.get("body"))
            if not body or _bot(a) or a.get("login") == who:
                continue
            out.append({"id": "%s-%s" % (kind[0], c["databaseId"]), "kind": kind, "author": a.get("login"),
                        "bot": False, "url": c.get("url"), "body": body, "state": c.get("state"),
                        "resolved": False, "replies": []})
    return out


TRIAGE_SCHEMA = """```json
{"threads": [{"id": "t-123", "worth": 0-100,
  "why": "one or two sentences: is the reviewer right, checked against the code, the brains and the PR's intent",
  "fix": "what the fix would be, concretely (file:line), or empty if not worth it",
  "reply_fix": "the reply to post if I fix it: short, specific, says what changed",
  "reply_wont": "the reply to post if I don't fix it: polite, gives the real reason",
  "wont_reasons": ["2-4 short reasons I could pick instead, each a complete reply on its own"]}]}
```"""


def _triage_prompt(pr, meta, ths):
    listed = [{k: t.get(k) for k in ("id", "kind", "author", "bot", "path", "line", "outdated", "body", "replies")}
              for t in ths]
    return (
        "Comment triage mode for the dashboard. This is my own pull request #%d \"%s\"; the worktree is detached "
        "at its head %s and the change is `git diff %s..HEAD`. Load the lfg:expert skill and follow its comment "
        "triage mode. For each comment thread below, check the comment against the actual code, the code graphs "
        "and what dev-graph and second-brain know (Principles, Invariants, Decisions for the touched components), "
        "then say how likely it is worth fixing (0-100) and why, and draft the replies I would post either way. "
        "Bots are often wrong or noisy, so judge them on the code, not their confidence. Read only: don't edit "
        "files and don't write to GitHub.\n\nThreads:\n```json\n%s\n```\n\nEnd your reply with exactly one "
        "fenced json block in this shape, one entry per thread id:\n%s"
        % (pr["number"], pr.get("title", ""), meta["head"][:12], meta["merge_base"][:12],
           json.dumps(listed, indent=1)[:60000], TRIAGE_SCHEMA))


def _triage_chat_prompt(text, tri):
    keep = {i: {k: t.get(k) for k in ("worth", "decision", "reply")} for i, t in (tri.get("threads") or {}).items()
            if not t.get("posted")}
    return ("%s\n\n---\nWhere I am (decision and the reply I have now, per thread):\n```json\n%s\n```\n"
            "Stay read-only. If your answer changes any thread's analysis or replies, end with one fenced json "
            "block {\"threads\": [...]} holding only those threads, with the keys you change (worth, why, fix, "
            "reply_fix, reply_wont, wont_reasons)." % (text, json.dumps(keep, indent=1)[:20000]))


def triage(rid, root, n):
    """Read the comments on your PR and start the AI's triage of them in the background."""
    n = _num(n)
    pr, meta = _prepare(rid, root, n, "triage")
    ths = threads(root, meta.get("url"), n)
    old = (_read(rid, n, "triage.json", None) or {}).get("threads") or {}
    tri = {"threads": {}, "at": C.now_iso()}
    for t in ths:
        keep = {k: v for k, v in (old.get(t["id"]) or {}).items()
                if k in ("worth", "why", "fix", "reply_fix", "reply_wont", "wont_reasons", "decision", "reply",
                         "posted")}
        tri["threads"][t["id"]] = dict(t, **keep)
    _write(rid, n, "triage.json", tri)
    todo = [t for t in ths if not t["resolved"] and not (old.get(t["id"]) or {}).get("worth")]
    if todo:
        _run(rid, root, n, "triage", _triage_prompt(pr, meta, todo), resume=bool(meta.get("ai_started")))
        meta["ai_started"] = True
    else:
        meta["status"] = "ready"
    _write(rid, n, "meta.json", meta)
    return {"started": bool(todo), "threads": len(ths), "worktree": meta["worktree"]}


def apply_triage(rid, n, items):
    tri = _read(rid, n, "triage.json", {}) or {}
    th = tri.setdefault("threads", {})
    changed = []
    for it in items:
        if not isinstance(it, dict) or it.get("id") not in th:
            continue
        t = th[it["id"]]
        w = it.get("worth")
        if isinstance(w, (int, float)) and 0 <= w <= 100:
            t["worth"] = int(w)
        for k in ("why", "fix", "reply_fix", "reply_wont"):
            if isinstance(it.get(k), str):
                t[k] = it[k].strip()[:6000]
        if isinstance(it.get("wont_reasons"), list):
            t["wont_reasons"] = [str(x).strip()[:2000] for x in it["wont_reasons"] if str(x).strip()][:5]
        changed.append(it["id"])
    _write(rid, n, "triage.json", tri)
    return ["%d thread(s)" % len(changed)] if changed else []


def decide(rid, n, decisions):
    """Your call per thread: fix / wont / skip, and the reply text to post (edited or picked from the reasons)."""
    n = _num(n)
    tri = _read(rid, n, "triage.json", None)
    if not isinstance(tri, dict) or not isinstance(decisions, dict):
        raise Invalid("read the comments first")
    th = tri.get("threads") or {}
    for i, dcs in decisions.items():
        if i not in th or not isinstance(dcs, dict) or th[i].get("posted"):
            continue
        if dcs.get("decision") in ("fix", "wont", "skip", None):
            th[i]["decision"] = dcs.get("decision")
        if isinstance(dcs.get("reply"), str):
            th[i]["reply"] = dcs["reply"][:8000]
    from . import settings as S
    kinds = S._secret_kinds(json.dumps(tri))
    if kinds:
        raise Invalid("a reply looks like it contains a secret (%s); remove it first" % ", ".join(kinds))
    _write(rid, n, "triage.json", tri)
    return {"saved": True}


def replies_out(rid, n):
    """Exactly what Post replies sends: one reply per decided thread that has text and wasn't posted yet."""
    n = _num(n)
    tri = _read(rid, n, "triage.json", None) or {}
    out = []
    for i, t in (tri.get("threads") or {}).items():
        if t.get("decision") in ("fix", "wont") and (t.get("reply") or "").strip() and not t.get("posted"):
            quote = "" if t["kind"] == "inline" else "> @%s: %s\n\n" % (t.get("author"), (t.get("body") or "")
                                                                         .splitlines()[0][:200] if t.get("body")
                                                                         else "")
            out.append({"id": i, "kind": t["kind"], "decision": t["decision"], "author": t.get("author"),
                        "path": t.get("path"), "line": t.get("line"), "reply_to": t.get("reply_to"),
                        "body": quote + t["reply"].strip()})
    return {"replies": out}


def post_replies(rid, root, n):
    """Send the decided replies, one by one; each is marked posted so it never goes twice."""
    n = _num(n)
    meta = _read(rid, n, "meta.json", None)
    if not isinstance(meta, dict):
        raise Invalid("read the comments first")
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/\d+", meta.get("url") or "")
    if not m:
        raise Invalid("couldn't tell which GitHub repo this PR is in")
    todo = replies_out(rid, n)["replies"]
    if not todo:
        raise Invalid("no replies to post: pick Fix or Won't fix on a thread first")
    from . import settings as S
    kinds = S._secret_kinds(json.dumps(todo))
    if kinds:
        raise Invalid("a reply looks like it contains a secret (%s); remove it first" % ", ".join(kinds))
    done = []
    for r in todo:
        path = ("repos/%s/pulls/%d/comments/%s/replies" % (m.group(1), n, r["reply_to"]) if r["kind"] == "inline"
                else "repos/%s/issues/%d/comments" % (m.group(1), n))
        cp = _gh(root, "api", "-X", "POST", path, "--input", "-", input=json.dumps({"body": r["body"]}), timeout=60)
        if cp.returncode:
            raise Invalid("GitHub refused the reply to %s after %d posted: %s"
                          % (r["id"], len(done), (cp.stdout or cp.stderr).strip()[-300:]))
        tri = _read(rid, n, "triage.json", {})
        tri["threads"][r["id"]]["posted"] = {"at": C.now_iso(), "decision": r["decision"]}
        _write(rid, n, "triage.json", tri)
        done.append(r["id"])
    C.audit("review-replies-posted", {"repo": rid, "pr": n, "replies": len(done)})
    return {"posted": len(done)}


def triage_detail(rid, root, n):
    n = _num(n)
    settle(rid, n)
    meta = _read(rid, n, "meta.json", None) or {}
    job = _read(rid, n, "job.json", None)
    pr = None
    for p in (C.read_json(os.path.join(folder(rid), "mine.json"), {}) or {}).get("prs") or []:
        if p.get("number") == n:
            pr = dict(p, author=(p.get("author") or {}).get("login"))
    return {"number": n, "mode": "triage", "pr": pr or dict(meta.get("pr") or {}, number=n, author=meta.get("author")),
            "review": state(rid, n, root, pr) if meta else {"status": "new"},
            "meta": {k: meta.get(k) for k in ("head", "worktree", "started")} if meta else {},
            "worktree_to_be": worktree_path(root, n), "triage": _read(rid, n, "triage.json", {}) or {},
            "chat": chat(rid, n), "working_since": (job or {}).get("started")}

