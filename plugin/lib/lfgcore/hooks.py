"""Claude Code hook entry points: `lfg hook <event>` with the hook JSON on stdin.

Every hook first checks whether LFG is on for the session's repo (`lfg enable`, ~/.lfg/enabled.json) and exits 0 at
once when it isn't: a filesystem walk, no subprocesses, no heavy imports. So a machine-wide plugin left over from
an older install, or a repo you never turned LFG on in, behaves exactly as if LFG weren't installed.

pre-tool   : lfg-guard (exit 2 blocks) + graph freshness before code-review-graph MCP calls.
post-tool  : marks graphs dirty and syncs in the background after edits; warns on secret-looking output.
prompt     : restarts the Headroom proxy if this session goes through it and it's down; tells the user if it stays
             down.
session-start, stop, pre-compact: context, usage logging, state snapshot.
"""
import json
import os
import re
import sys
import time

from . import common as C

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GRAPH_TOOL_RX = re.compile(r"^mcp__.*code-review-graph.*__")

# Patterns only; the matched value is never printed, logged or stored.
SECRET_OUTPUT_RX = [
    ("aws-access-key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(proj-)?[A-Za-z0-9]{32,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("stripe-key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private-key", re.compile(r"-----BEGIN ([A-Z]+ )?PRIVATE KEY-----")),
    ("linear-key", re.compile(r"\blin_api_[A-Za-z0-9]{30,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
]


def _stdin_json():
    try:
        return json.load(sys.stdin)
    except ValueError:
        return {}


def _repo(data):
    cwd = data.get("cwd") or os.getcwd()
    root = C.repo_root(cwd)
    return (root, C.repo_id(root)) if root else (None, None)


# ---------------------------------------------------------------- pre-tool

def pre_tool(data):
    from . import graphs as G
    from . import guard
    tool, tin = data.get("tool_name", ""), data.get("tool_input") or {}
    v = guard.verdict(tool, tin, allow_commits=C.config()["guard"].get("allow_commits", True))
    if v and v[0] == "ask":  # Commit approval: Claude Code asks the user instead of LFG blocking
        C.audit("asked", {"rule": v[1], "tool": tool, "why": v[2]})
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                 "permissionDecisionReason": "LFG: %s" % v[2]}}))
        return 0
    verdict = (v[1], v[2]) if v else None
    if verdict:
        rule, why = verdict
        C.audit("blocked", {"rule": rule, "tool": tool, "why": why})
        sys.stderr.write("Blocked by LFG rule %s (%s): %s. A human must do this in their own terminal.\n"
                         % (rule, guard.rule_title(rule), why))
        return 2
    if GRAPH_TOOL_RX.match(tool):
        root, rid = _repo(data)
        if root:
            res = G.ensure(root, rid, wait_timeout=240)
            if res["status"] not in ("fresh",):
                sys.stderr.write("LFG: graphs for this repo are not fresh (%s). Run `lfg graphs ensure` and read "
                                 "its output before using graph tools. %s\n"
                                 % (res["status"], "; ".join(res.get("errors") or [])))
                return 2
    return 0


# ---------------------------------------------------------------- post-tool

def _response_text(resp):
    if isinstance(resp, str):
        return resp
    try:
        return json.dumps(resp)[:2000000]
    except (TypeError, ValueError):
        return ""


def post_tool(data):
    from . import graphs as G
    tool = data.get("tool_name", "")
    if tool in EDIT_TOOLS:
        root, _rid = _repo(data)
        if root:
            G.spawn_background(root)
    text = _response_text(data.get("tool_response"))
    kinds = sorted({k for k, rx in SECRET_OUTPUT_RX if rx.search(text)})
    if kinds:
        C.audit("secret-in-output", {"tool": tool, "kinds": kinds})
        print(json.dumps({"decision": "block", "reason": (
            "LFG: the last tool output appears to contain a secret (%s). Do not repeat, quote, summarise, store "
            "or send it anywhere. Tell the user which file/command exposed it so they can rotate it."
            % ", ".join(kinds))}))
    return 0


# ---------------------------------------------------------------- session-start

# What used to be appended to ~/.claude/CLAUDE.md. Now it is session context, and only in repos where LFG is on.
CONTEXT = [
    "LFG %s is on in this repo. Rules: never push or gh-write, never read .env or keys, never deploy. Commit only "
    "when the user asks you to (Claude Code asks them to approve each commit, if Commit approval is on); otherwise "
    "leave changes unstaged.",
    "When you use an LFG skill (`/lfg:lfg`, `/lfg:wizard`, any `lfg:` skill or agent), follow its steps, checkpoints "
    "and bookkeeping commands (`lfg issue sync`, `lfg run set`) as written. The user's CLAUDE.md files take priority "
    "over every LFG skill and agent: where they conflict, follow CLAUDE.md and say which rule you followed. The LFG "
    "guard is enforced in code; if it blocks something CLAUDE.md asks for, tell the user instead of working around it. "
    "LFG's skills are named `lfg:<name>`: when an LFG skill or agent says to run `/grill`, `/ship` and so on, use the "
    "`lfg:` one, never a same-named skill from elsewhere.",
    "When the user asks for a doc (an explainer, guide, design write-up, notes) and doesn't name a path in the repo, "
    "write it as Markdown with a `# Title` into LFG's docs, not the repo: about the whole project -> the dir "
    "`lfg repo docs` prints; about this branch's work -> the dir `lfg repo docs --branch` prints. They show on the "
    "dashboard's Docs page.",
    "The user's own project docs (`lfg repo docs`, Markdown, with branch docs under branches/) and the knowledge "
    "they added (`lfg repo knowledge`: notes, decisions, lessons, rules) are context for this project: read the "
    "ones that matter before planning or answering, and follow the decisions and rules there.",
    "LFG never creates a Linear issue on its own: ask first with the exact title and text. `lfg issue sync` writes "
    "only to the local dev-graph.",
    "Remember: when the user states a decision, constraint or preference, or work uncovers a root cause or landmine, "
    "offer to save it at the end of your reply and ask whether it goes to dev-graph or second-brain before writing "
    "anything (`lfg rule remember`; /lfg:note to save on request).",
    "Ask with the AskUserQuestion tool, not plain text, whenever you need the user's answer (an LFG interview, "
    "checkpoint or approval, or any other question): it shows clickable options. Give each question 2-4 options; for "
    "an open-ended question, offer your best guesses from the code and the brief, since the user can always type "
    "their own under Other. Still one question at a time in /lfg:grill. Subagents cannot ask; the main session does.",
]


# Visibility: the user sees in every reply whether LFG did the work, and why not when it didn't.
TAG_RULE = (
    "Use LFG without being asked: when a request fits an LFG skill, use it even if the user didn't type the command "
    "(a bug or failing test: /lfg:fix; a feature or change: /lfg:lfg; how does X work: /lfg:explain; what does this "
    "change touch: /lfg:impact; review: /lfg:expert; checks: /lfg:check; security: /lfg:secure; ship: /lfg:ship; "
    "save a fact: /lfg:note; not sure: /lfg:which). Start every reply to the user with one line saying whether you "
    "used LFG, so they can see when you deviate from it: `**LFG:** /lfg:<skill>` when you followed an LFG skill or "
    "agent; `**LFG:** tools only (<which>)` when you used LFG's code graphs, dev-graph, second-brain or `lfg` "
    "commands without a skill; `**LFG:** not used - <reason>` otherwise, with the real reason in a few words (for "
    "example: a question about something outside this repo, a one-line change no skill covers, or the user asked "
    "not to). Never claim LFG was used when it wasn't. Subagent reports and tool calls don't need the line.")
TAG_REMINDER = ("LFG is on in this repo: use an LFG skill if one fits this request, and start your reply with "
                "`**LFG:** /lfg:<skill>`, `**LFG:** tools only (<which>)` or `**LFG:** not used - <reason>`.")


def _tag_on():
    return bool((C.config().get("replies") or {}).get("lfg_tag", True))


def _gh_signed_in():
    """`gh auth status` touches the network, so its answer is cached for an hour."""
    p = C.lfg_path("state", "gh.json")
    st = C.read_json(p, {}) or {}
    if time.time() - (st.get("at") or 0) < 3600:
        return st.get("ok")
    ok = C.run(["gh", "auth", "status"], timeout=10).returncode == 0
    C.write_json(p, {"at": time.time(), "ok": ok})
    return ok


def session_start(data):
    from . import graphs as G
    root, rid = _repo(data)
    lines = [CONTEXT[0] % C.VERSION] + CONTEXT[1:] + ([TAG_RULE] if _tag_on() else [])
    notice = None
    try:
        from . import settings as S
        own = S.own_rules()
        if own:
            lines.append("The user's own rules (follow them; read each with `lfg rule <name>`): %s."
                         % ", ".join(own))
    except Exception:  # a broken rule file must never block a session
        pass
    if not _gh_signed_in():
        lines.append("GitHub CLI: NOT signed in - ask the user to run `gh auth login` themselves.")
    from . import headroom as HR
    if HR.routed(root):
        other = HR.bypassed()
        if other:
            why = (" because the Claude desktop app sets its own API address and ignores settings"
                   if os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "claude-desktop" else "")
            lines.append("Headroom proxy: BYPASSED - settings route Claude Code through Headroom, but this session"
                         " sends requests straight to %s%s. If the user asks about Headroom, say so; a terminal"
                         " `claude` session goes through it." % (other, why))
        elif HR.ensure_live(root):
            lines.append("Headroom proxy: up.")
        else:
            notice = HR.down_message()
            lines.append("Headroom proxy: DOWN. " + notice)
    if root:
        st = G.status(root, rid)
        if st["status"] != "fresh":
            G.spawn_background(root)
        run = C.current_run(rid)
        lines.append("Repo %s: graphs %s%s. Current run: %s." % (
            rid, st["status"], " (syncing in the background)" if st["status"] != "fresh" else "",
            os.path.basename(run) if run else "none"))
        main = C.main_root(root)
        if os.path.realpath(main) != os.path.realpath(root):
            lines.append("Linked worktree on %s. The repo's graphs are shared from the main checkout %s (branch %s):"
                         " pass `repo_root=%s` to code-review-graph tools and `--graph %s` to graphify. They describe"
                         " that checkout, so confirm what differs on this branch in this worktree's files."
                         % (C.git_branch(root) or "?", main, C.git_branch(main) or "?", main,
                            os.path.join(main, "graphify-out", "graph.json")))
        else:
            lines.append("Graphs are in this repo (git-ignored, shared by every branch): code-review-graph"
                         " `.code-review-graph/`, graphify `graphify-out/graph.json` (graphify finds it by default).")
        lines.append("Work for another branch, or separate work while the checkout holds unrelated changes: create a"
                     " worktree yourself with `lfg worktree new <branch>` (`lfg rule worktrees`). Never ask the user"
                     " to, and never switch their checkout.")
        try:
            from . import worktree as W
            gone = W.prune(root)
            if gone:
                lines.append("Removed %d clean, unused LFG worktree(s): %s." % (len(gone), ", ".join(gone)))
        except Exception:  # housekeeping must never block a session
            pass
        if run and os.path.exists(os.path.join(run, "progress.md")):
            lines.append("Resume from %s/progress.md." % run)
    if notice:  # the model can't answer while the proxy is down, so the user is told directly
        print(json.dumps({"systemMessage": notice, "hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": "\n".join(lines)}}))
    else:
        print("\n".join(lines))
    return 0


# ---------------------------------------------------------------- prompt

def prompt(data):
    """Every prompt, before it is sent: a one-line reminder to use LFG and say so (TAG_REMINDER, unless switched off
    in settings), and is the Headroom proxy this session goes through still answering? A crash is
    restarted by launchd within seconds, but an unloaded agent or a proxy that keeps failing stays down, and Claude
    Code would then retry for minutes with nothing on screen saying why. A refused connection fails at once, so
    this costs a few milliseconds when the proxy is up."""
    from . import headroom as HR
    root, _rid = _repo(data)
    out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": TAG_REMINDER}} \
        if _tag_on() else {}
    if HR.routed(root) and not HR.bypassed() and not HR.live(timeout=1):
        back = HR.revive()
        C.audit("headroom-down", {"restarted": back})
        out["systemMessage"] = "Headroom proxy was down; LFG restarted it." if back else HR.down_message()
    if out:
        print(json.dumps(out))
    return 0


# ---------------------------------------------------------------- stop / usage

def usage_db():
    import sqlite3
    path = C.lfg_path("usage.db")
    db = sqlite3.connect(path)
    os.chmod(path, 0o600)
    db.execute("CREATE TABLE IF NOT EXISTS usage (session TEXT, ts TEXT, repo TEXT, run TEXT, model TEXT, "
               "input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER, "
               "PRIMARY KEY (session, model))")
    db.execute("CREATE TABLE IF NOT EXISTS replies (prompt TEXT PRIMARY KEY, session TEXT, ts TEXT, repo TEXT, "
               "kind TEXT, detail TEXT)")
    return db


TAG_RX = re.compile(r"^[\W_]{0,6}LFG[*_`\s]{0,4}:[*_`\s]*(.*)$", re.I)


def reply_tag(text):
    """(kind, detail) from a reply's LFG line: skill (`/lfg:fix`), tools (`tools only (...)`), not-used (`not used -
    why`), or missing when the reply's first lines carry no LFG line."""
    for line in (text or "").strip().splitlines()[:3]:
        m = TAG_RX.match(line.strip())
        if not m:
            continue
        rest = m.group(1).strip().strip("*_` ").strip()
        low = rest.lower()
        if low.startswith("not used"):
            return "not-used", re.sub(r"^not used\W*", "", rest, flags=re.I)[:300]
        if low.startswith("tools"):
            return "tools", re.sub(r"^tools( only)?\W*", "", rest, flags=re.I).strip("() ")[:300]
        return "skill", rest[:300]
    return "missing", ""


def _last_reply(path):
    """(prompt id, first text the assistant showed after the latest user prompt) from the end of the transcript."""
    if not path or not os.path.exists(path):
        return None, ""
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 2_000_000))
        lines = f.read().decode("utf-8", "replace").splitlines()
    prompt_id, text = None, ""
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("isSidechain") or ev.get("isMeta"):
            continue
        msg = ev.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if ev.get("type") == "user":
            typed = isinstance(content, str) or (isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "text" for b in content))
            if typed and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content or []):
                prompt_id, text = ev.get("uuid") or ev.get("timestamp"), ""
        elif ev.get("type") == "assistant" and prompt_id and not text and isinstance(content, list):
            text = next((b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text"
                         and (b.get("text") or "").strip()), "")
    return prompt_id, text


def _transcript_usage(path, session=""):
    """Token totals per model for a session. Reads only what was appended since the last Stop (the byte offset and
    running totals live in ~/.lfg/state/usage-offsets.json), so a long session doesn't get slower turn by turn."""
    if not path or not os.path.exists(path):
        return {}
    sp = C.lfg_path("state", "usage-offsets.json")
    state = C.read_json(sp, {}) or {}
    key = session or path
    st = state.get(key) or {}
    if st.get("path") != path or st.get("offset", 0) > os.path.getsize(path):
        st = {}
    totals, offset = st.get("totals") or {}, st.get("offset", 0)
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read()
    end = chunk.rfind(b"\n") + 1  # only whole lines; a half-written last line is read next time
    for line in chunk[:end].decode("utf-8", "replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        msg = ev.get("message") if isinstance(ev, dict) else None
        u = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(u, dict):
            continue
        t = totals.setdefault(msg.get("model") or "unknown", [0, 0, 0, 0])
        t[0] += u.get("input_tokens") or 0
        t[1] += u.get("output_tokens") or 0
        t[2] += u.get("cache_read_input_tokens") or 0
        t[3] += u.get("cache_creation_input_tokens") or 0
    week_ago = time.time() - 7 * 86400
    state = {k: v for k, v in state.items() if (v.get("at") or 0) > week_ago}
    state[key] = {"path": path, "offset": offset + end, "totals": totals, "at": time.time()}
    C.write_json(sp, state)
    return totals


def stop(data):
    root, rid = _repo(data)
    run = C.current_run(rid) if rid else None
    totals = _transcript_usage(data.get("transcript_path"), data.get("session_id", ""))
    if totals:
        db = usage_db()
        with db:
            for model, t in totals.items():
                db.execute("INSERT OR REPLACE INTO usage VALUES (?,?,?,?,?,?,?,?,?)",
                           (data.get("session_id", "?"), C.now_iso(), rid or "", os.path.basename(run or ""),
                            model, t[0], t[1], t[2], t[3]))
        db.close()
    if _tag_on():
        prompt_id, text = _last_reply(data.get("transcript_path"))
        if prompt_id and text:
            kind, detail = reply_tag(text)
            db = usage_db()
            with db:
                db.execute("INSERT OR REPLACE INTO replies VALUES (?,?,?,?,?,?)",
                           (prompt_id, data.get("session_id", "?"), C.now_iso(), rid or "", kind, detail))
            db.close()
    return 0


def pre_compact(data):
    _root, rid = _repo(data)
    run = C.current_run(rid) if rid else None
    if run:
        path = os.path.join(run, "progress.md")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("\n<!-- context compacted at %s; resume from this file and tasks.json -->\n" % C.now_iso())
    return 0


EVENTS = {"pre-tool": pre_tool, "post-tool": post_tool, "session-start": session_start, "prompt": prompt,
          "stop": stop, "pre-compact": pre_compact}


def main(event):
    fn = EVENTS.get(event)
    if not fn:
        C.die("unknown hook event %r (expected one of %s)" % (event, ", ".join(sorted(EVENTS))), 2)
    data = _stdin_json()
    if not C.is_enabled(data.get("cwd") or os.getcwd()):
        return 0  # LFG is off in this repo: behave as if it weren't installed
    try:
        return fn(data)
    except Exception as e:  # never break the session on a hook bug, except the guard, which fails closed
        if event == "pre-tool":
            sys.stderr.write("LFG guard error (%s); blocking to be safe.\n" % type(e).__name__)
            return 2
        sys.stderr.write("LFG hook %s error: %s\n" % (event, type(e).__name__))
        return 0
