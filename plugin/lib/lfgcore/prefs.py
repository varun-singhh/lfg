"""Your rules for Claude: defaults for every session, changes for one session, and the hard ones enforced in code.

Each preference is a switch or a pick-one choice. Defaults go into ~/.claude/lfg-preferences.md, which your CLAUDE.md
imports (`@~/.claude/lfg-preferences.md`), so every session reads them the normal way. A session can differ from the
defaults: its changes are kept here and told to it by two hooks in ~/.claude/settings.json, on SessionStart and on each
message. Preferences marked `enforce` are also checked by a PreToolUse hook before every command, so a session can't
break them by mistake. A Stop hook queues what you correct Claude on, while corrections are on
(corrections.py).

Only you can loosen a rule. `lfg prefs set` run by Claude may only make a session stricter; loosening is the
dashboard's (with its edit key) or yours in your own terminal (`! lfg prefs set …`, which runs without hooks).
Everything is in ~/.lfg/state/prefs.json.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

from . import common as C
from . import guard as G

PREFS_MD = os.path.join(C.HOME, ".claude", "lfg-preferences.md")
IMPORT_LINE = "@~/.claude/lfg-preferences.md"
PROTECTED_BRANCHES = G.PROTECTED_BRANCHES

STYLE = "How Claude talks to you"
# Built in. Options are listed strictest first: a change to a later option loosens the rule.
BUILTIN = [
    {"id": "commits", "group": "Git", "title": "Commits", "kind": "choice", "default": "ask", "enforce": True,
     "options": [
         {"value": "never", "label": "Never: I make every commit", "text": "Never run `git commit`. Leave changes "
          "uncommitted and give me the commit message to use."},
         {"value": "ask", "label": "When I say so", "text": "Commit only when I ask you to in this session."},
         {"value": "auto", "label": "On its own, once tests pass", "text": "Commit on your own when a change is "
          "complete and its tests and checks pass, one commit per logical change, without asking."}]},
    {"id": "rewrite", "group": "Git", "title": "Amend and force-push", "kind": "choice", "default": "never",
     "enforce": True, "options": [
         {"value": "never", "label": "Never",
          "text": "Never amend a commit or force-push. Every change is a new commit."},
         {"value": "review", "label": "Small fixes while I review my PR",
          "text": "Amend the last commit and force-push it (`--force-with-lease`) only to fold in a small fix, at most "
                  "{rewrite_lines} changed lines, that I found while reviewing my own open PR on this branch. "
                  "Anything bigger is a new commit. Never on main, master, qa or prod."},
         {"value": "anytime", "label": "Any time on my branches",
          "text": "You may amend and force-push (`--force-with-lease`) my own branches whenever it keeps history "
                  "clean. Never main, master, qa or prod."}]},
    {"id": "rewrite_lines", "group": "Git", "title": "A small fix is at most", "kind": "number", "default": 20,
     "min": 1, "max": 500, "unit": "changed lines", "enforce": True, "shown_if": ["rewrite", "review"],
     "about": "For \"Small fixes while I review my PR\": LFG counts the lines an amend changes (added plus removed) "
              "and blocks it, or the force-push that follows, above this."},
    {"id": "push", "group": "Git", "title": "Push", "kind": "choice", "default": "ask", "enforce": True,
     "options": [
         {"value": "never", "label": "Never: I push", "text": "Never run `git push`."},
         {"value": "ask", "label": "When I say so", "text": "Push only when I ask you to in this session."},
         {"value": "auto", "label": "After every commit", "text": "Push right after each commit, to the branch "
          "you're on."}]},
    {"id": "open_pr", "group": "GitHub", "title": "Opening PRs", "kind": "choice", "default": "never",
     "enforce": True, "options": [
         {"value": "never", "label": "Never: I open them", "text": "Never open a pull request."},
         {"value": "ask", "label": "When I say so", "text": "Open a pull request (`gh pr create`) only when I ask "
          "you to in this session."},
         {"value": "auto", "label": "On its own, after the first push", "text": "Open a pull request (`gh pr "
          "create`) on your own after the first push of a branch that has none, never from main, master, qa or "
          "prod."}]},
    {"id": "merge_pr", "group": "GitHub", "title": "Merging PRs", "kind": "choice", "default": "never",
     "enforce": True, "options": [
         {"value": "never", "label": "Never: I merge", "text": "Never merge a pull request."},
         {"value": "squash", "label": "When I say so, squashed",
          "text": "Merge a PR only when I ask, and always as one squashed commit (`gh pr merge --squash`)."}]},
    {"id": "delete_merged", "group": "GitHub", "title": "Delete the branch after merging", "kind": "switch",
     "default": False, "enforce": True, "shown_if": ["merge_pr", "squash"],
     "about": "On: when Claude merges a PR, it also deletes the PR's branch, on GitHub and on this computer "
              "(`gh pr merge --delete-branch`). LFG looks up the PR's branch first and never deletes main, master, "
              "qa or prod. Off: the branch stays.",
     "text": "When you merge a PR, delete its branch too: `gh pr merge --squash --delete-branch`. Never when the PR's "
             "branch is main, master, qa or prod.",
     "off_text": "When you merge a PR, leave its branch: no `--delete-branch`."},
    {"id": "gh_default_branch", "group": "GitHub", "title": "Default branch of your repos", "kind": "switch",
     "default": False, "enforce": True,
     "about": "On: Claude may change which branch is the default on a GitHub repo you own "
              "(`gh repo edit --default-branch`), and nothing else about the repo. LFG asks GitHub that the repo is "
              "yours first. Off: blocked by safety rule 2.",
     "text": "You may change the default branch of a GitHub repo I own with `gh repo edit <repo> --default-branch "
             "<branch>`, and no other repo setting.",
     "off_text": ""},
    {"id": "coauthor", "group": "Git", "title": "Claude as co-author", "kind": "switch", "default": False,
     "about": "On: Claude's commits and PRs credit Claude as co-author. Off: you're the only author.",
     "text": "End commit messages with a Co-Authored-By line for Claude, and PR bodies with the Claude Code line.",
     "off_text": "I am the only author: no Co-Authored-By line for Claude in commits and no \"Generated with Claude "
     "Code\" line in PR bodies."},
] + [
    # How Claude talks to you: instructions only, never enforced. Condensed from Lee's answering rules.
    {"id": pid, "group": STYLE, "title": title, "kind": "switch",
     "default": pid in ("style_paste_blocks", "style_ticket_titles"),
     "about": about, "text": text, "off_text": ""} for pid, title, about, text in (
        ("style_answer_first", "Lead with the answer",
         "Replies open with two or three sentences that are the answer, saying who, what, where and when. A fix says "
         "what happened before and what happens now.",
         "Open every reply and explanation with two or three sentences that are the answer, not a preamble to it: "
         "cover who, what, where and when, and for a fix say the old behavior and the new. Detail goes below, only "
         "if it changes what I do."),
        ("style_breaks_first", "Say what breaks for a person first",
         "A problem starts with what someone sees or can't do; how the code causes it comes second. Questions to you "
         "are about outcomes, not code.",
         "When something is wrong, first say what a person sees or can't do, in plain words with no identifiers; "
         "the mechanism comes after, only if needed. Put any question to me as one sentence about what someone will "
         "see or be able to do."),
        ("style_paste_blocks", "Put anything to paste in markers",
         "Anything you need to copy (a command, a query, a prompt for another session, a PR body) comes in a code "
         "block between PASTE START and PASTE END, with only that inside and a line saying where it goes. A long "
         "command is split over lines with a trailing \\, so it pastes into a terminal as one command.",
         "Anything I have to paste (a command, query, prompt for another session, PR body or message) goes inside a "
         "fenced code block between `--- PASTE START ---` and `--- PASTE END ---`, with nothing else between the "
         "markers. Say where it goes. A shell command too long for one line is split with a ` \\` at the end of every "
         "line but its last (nothing after the backslash, not even a space or a comment), so it pastes into a "
         "terminal as one command; never break a command across lines without one, since every line then runs on "
         "its own. Several separate commands each start on their own line."),
        ("style_risky_blocks", "Say what SQL and risky commands do",
         "The PASTE START line of a query or a command that changes things names where it runs and whether it only "
         "reads or what it writes. Writes come with the row count to expect, a way to check them, and a dry run.",
         "For SQL and for commands that change or delete things, the PASTE START marker names where it runs (system "
         "and environment) and what it does: `READ ONLY`, or `WRITE - ` followed by every kind of write in it. Before "
         "a write, say how many rows it should touch, add RETURNING or a check query, name any precondition, and "
         "offer a dry run (BEGIN ... ROLLBACK) for a write to several tables."),
        ("style_steps", "Give steps you run one at a time",
         "When you have to do something yourself (run a command, set a secret, click through a page), Claude shows "
         "the outline once, then one step per message and waits for you.",
         "When I have to run steps myself (commands, queries, secrets, clicks), show the outline once, then give one "
         "step per message: a one-line status (\"step 2 of 5: ...\"), the step in paste markers, what to report "
         "back, then wait for me."),
        ("style_handoff_prompts", "Open prompts for another session with what it is",
         "A prompt Claude writes for a new session opens by saying what that session is, then the task, then the "
         "branch and base.",
         "A prompt for another session opens by saying what that session is (\"This is a fresh session on ...\"), "
         "then the task, then the constraints, naming the branch and the base explicitly."),
        ("style_labels", "Re-name findings and shorthand each time",
         "Claude re-names a finding or shorthand every time it comes back, and explains without code names or jargon.",
         "Don't make me hold your labels: re-name a numbered finding or invented shorthand every time it comes back "
         "(\"finding 3, the one where ...\"). Explain without code identifiers or borrowed jargon when a plain word "
         "works."),
        ("style_hold_position", "Answer pushback on the evidence",
         "When you push back, Claude checks again and answers on the evidence instead of giving in, and says what is "
         "proven and what is not.",
         "A question is not a correction: when I push back, re-check the claim and answer on the evidence, changing "
         "position only if the evidence does, and say what changed. Say what is proven and what is only reasoned, and "
         "name the assumption a claim rests on."),
        ("style_one_note", "End with at most one note",
         "At most one extra note at the end of a reply, and only one that changes what you do next.",
         "End with at most one trailing note, and only if it changes what I do next, decide, or believe about the "
         "current state."),
        ("style_recommend", "Recommend one option",
         "Claude says which option it recommends and why, and skips padding and follow-ups you didn't ask for.",
         "Give a recommendation, not a menu: name alternatives only when they are real, and say which one and why. "
         "No padding, no speculative follow-ups, no work I didn't ask for."),
        ("style_no_em_dash", "Use hyphens instead of em dashes", "No em dashes anywhere, in replies or in code.",
         "Never use em dashes, in prose or code. Use a hyphen, a colon, or restructure the sentence."),
        ("style_ticket_titles", "Name tickets by ID and title",
         "A Linear ticket is named by its ID and its title, e.g. ATO-4212 (Fix the export timeout), not the ID "
         "alone.",
         "When you mention a Linear ticket, give its ID and its title together, e.g. ATO-4212 (Fix the export "
         "timeout), never the ID alone. Look the title up if you don't have it."),
        ("style_us_spelling", "Use US spelling", "US spelling in replies and in code.",
         "Use US spelling, in code and prose."),
        ("style_shortest", "Shortest version that is still exact",
         "Replies use the fewest words that stay exact: no hedging, restating or background you already have, and no "
         "qualifying what needs no qualifier.",
         "Use the fewest words that keep full clarity and zero ambiguity; never trade precision for word count. Cut "
         "hedging, restatement, background I already have and reasoning I didn't ask for. Don't qualify a claim that "
         "needs no qualifier."),
        ("style_command_labels", "Label every command and link",
         "Each command or link to open says in its PASTE START line where it runs, the strongest thing it does (read "
         "only, writes files, GitHub, installs, a cloud environment) and one plain sentence of what changes.",
         "Every command and link I'm handed carries, in its PASTE START line, where it runs (\"Terminal: <folder>\" or "
         "\"any folder\", \"Browser: <site>\"), the strongest thing it does (READ ONLY, WRITES, DELETES, GITHUB, "
         "INSTALLS, or the cloud and environment it changes), and one plain sentence of at most 20 words saying what "
         "changes for me. Say when it can't be undone."),
        ("style_pr_comments", "Write PR comments in my voice",
         "Review comments Claude drafts for someone else's PR sound like you: one or two short sentences, a question "
         "when the author has to answer, hedged only when truly unsure, no exclamation marks or corporate phrasing.",
         "Draft PR review comments in my voice: one or two short sentences, no preamble or sign-off; lowercase "
         "sentence starts are fine. Ask a question when the author has to answer (\"what about using X here?\"), not a "
         "demand. Hedge only real uncertainty (\"prob\", \"i think\", \"just calling it out\"); verify what can be "
         "checked instead of hedging. Prefix small or subjective ones with `nitpick:`. Backtick identifiers and "
         "files. Say when the same issue is elsewhere too. No exclamation marks, emoji or corporate hedge-speak."),
        ("style_tables", "Use tables only to compare",
         "A table only when several things are compared across the same points.",
         "Use a table only to compare several things across the same dimensions; never for two items or one "
         "dimension."))
] + [
    {"id": "style_point_words", "group": STYLE, "title": "Length of each point", "kind": "choice",
     "default": "none", "options": [
         {"value": "20", "label": "20 words", "text": "Keep each point, bullet or sentence to at most 20 words."},
         {"value": "40", "label": "40 words", "text": "Keep each point, bullet or sentence to at most 40 words."},
         {"value": "none", "label": "No limit", "text": ""}]},
]
# What each choice does, said to you (the page shows this; "text" is what Claude is told).
ABOUT = {
    ("merge_pr", "squash"):
        "Claude merges a PR only when you say so, always squashed into one commit; any other merge is blocked.",
    ("commits", "never"):
        "Claude leaves its changes uncommitted and gives you a commit message. It is blocked from committing, even "
        "if you ask.",
    ("commits", "ask"):
        "Claude leaves its changes uncommitted until you say \"commit\", then commits.",
    ("commits", "auto"):
        "Claude commits by itself after each finished change whose tests pass, without asking you.",
    ("rewrite", "never"):
        "Claude always adds a new commit. Amending and force-pushing are blocked.",
    ("rewrite", "review"):
        "Claude may fold a small fix into your last commit and force-push it, but only on a branch with your own open "
        "PR, only if the fix is small (the size below), and never on main, master, qa or prod. LFG checks all of this "
        "before the command runs.",
    ("rewrite", "anytime"):
        "Claude may amend and force-push your branches whenever it wants to keep history clean. Never main, master, "
        "qa or prod.",
    ("push", "never"):
        "Claude is blocked from pushing; you push.",
    ("push", "ask"):
        "Claude pushes only when you say \"push\".",
    ("push", "auto"):
        "Claude pushes right after each of its commits, to the branch it is on.",
    ("open_pr", "never"):
        "Claude is blocked from opening pull requests; you open them.",
    ("open_pr", "ask"):
        "Claude opens a PR only when you say so. Whether it may run the command at all is \"Open a PR\" under Git "
        "and GitHub actions.",
    ("open_pr", "auto"):
        "Claude opens a PR by itself after it first pushes a branch that has none. Whether it may run the command at "
        "all is \"Open a PR\" under Git and GitHub actions.",
    ("merge_pr", "never"):
        "Claude is blocked from merging pull requests; you merge.",
    ("style_point_words", "20"): "Each point, bullet or sentence is at most 20 words.",
    ("style_point_words", "40"): "Each point, bullet or sentence is at most 40 words.",
    ("style_point_words", "none"): "No limit on how long a point is.",
}
for _p in BUILTIN:
    if (_p["id"], None) in ABOUT:
        _p["about"] = ABOUT[(_p["id"], None)]
    for _o in _p.get("options") or []:
        _o["about"] = ABOUT.get((_p["id"], _o["value"]), "")

# What Claude may run, one row per git or GitHub write (guard.ACTIONS). The rows above say when Claude does something;
# these say whether the command runs, asks you first, or is blocked.
ACTS = "Git and GitHub actions"
for _id, _title, _default, _covers in G.ACTIONS:
    _spares = _id in G.SPARES_WORK
    BUILTIN.append({
        "id": _id, "group": ACTS, "title": _title, "kind": "choice", "default": _default, "enforce": True,
        "about": _covers, "options": [
            {"value": "block", "label": "Block", "text": "LFG blocks %s (%s)." % (_title.lower(), _covers),
             "about": "LFG blocks it, even if you ask."},
            {"value": "ask", "label": "Ask", "text": "",
             "about": "Claude Code asks you to approve each one before it runs."},
            {"value": "allow", "label": "Allow when nothing is lost" if _spares else "Allow", "text": "",
             "about": "It runs without asking when no uncommitted work would be lost; otherwise Claude Code asks "
                      "you first." if _spares else "It runs without asking."}]})

# The guard's safety rules (guard.RULES), one choice each. "ask" lifts the block; Claude is still told the rule.
STAYS_BLOCKED = {
    "4": " LFG's own dashboard key stays blocked.",
    "13": " Changing LFG itself (its files, hooks, on/off switch and these rules) stays blocked.",
}
for _r, (_title, _means, _how) in G.RULES.items():
    if not _how.startswith("guard"):
        continue
    BUILTIN.append({
        "id": "rule_" + _r, "group": "Safety rules", "title": "%s. %s" % (_r, _title), "kind": "choice",
        "default": "block", "enforce": True, "options": [
            {"value": "block", "label": "Blocked", "text": "",
             "about": "LFG blocks any command that breaks it, even if you ask. " + _means},
            {"value": "ask", "label": "Only when I ask",
             "text": "LFG no longer blocks safety rule %s (%s). Keep to it unless I ask you otherwise in this "
                     "session: %s" % (_r, _title, _means),
             "about": "LFG stops blocking it. Claude still keeps to it, and does it only when you ask."
                      + STAYS_BLOCKED.get(_r, "")}]})


def _state_path():
    return C.lfg_path("state", "prefs.json")


def _seen_path():
    return C.lfg_path("state", "prefs-seen.json")


def _remind_path():
    return C.lfg_path("state", "prefs-remind.json")


def style_ids(d=None):
    return {p["id"] for p in catalog(d) if p["group"] == STYLE}


def remind(session):
    """Flag a session so its next message carries the "How Claude talks to you" rules again. Only adds
    instructions, so Claude may run it too."""
    if not re.match(r"^[0-9a-f-]{36}$", str(session or "")):
        raise ValueError("not a session id: %r" % session)
    ids = [s for s in C.read_json(_remind_path(), []) or [] if s != session][-200:] + [session]
    C.write_json(_remind_path(), ids)
    return {"session": session, "reminded": True}


def _take_reminder(sid, d):
    """The style rules on for sid if it was flagged, clearing the flag; else ""."""
    ids = C.read_json(_remind_path(), []) or []
    if not sid or sid not in ids:
        return ""
    C.write_json(_remind_path(), [s for s in ids if s != sid])
    text = render(effective(sid, d), d, only=style_ids(d), header=STYLE)
    return text and (text + "\nThe user asked you to follow these again; your recent replies drifted from them.")


def _migrate(vals):
    """The old amend and force_push switches became one `rewrite` choice: either one on means review-sized fixes.
    The edit_pr and git_ff_sync switches became the action rows act_edit_pr and act_ff_sync: on is Allow, off Block."""
    for old, new in (("edit_pr", "act_edit_pr"), ("git_ff_sync", "act_ff_sync")):
        if old in vals:
            on = vals.pop(old)
            vals.setdefault(new, "allow" if on else "block")
    if "amend" in vals or "force_push" in vals:
        on = vals.pop("amend", False) or vals.pop("force_push", False)
        vals.pop("force_push", None)
        if on and "rewrite" not in vals:
            vals["rewrite"] = "review"
    return vals


def load():
    d = C.read_json(_state_path(), {}) or {}
    return {"catalog": list(d.get("catalog") or []), "texts": dict(d.get("texts") or {}),
            "defaults": _migrate(dict(d.get("defaults") or {})),
            "sessions": {k: _migrate(dict(v)) for k, v in (d.get("sessions") or {}).items()}}


def _save(d):
    C.ensure_dir(os.path.dirname(_state_path()))
    C.write_json(_state_path(), d)


def catalog(d=None):
    """Every rule. A built-in instruction you reworded carries your wording, with LFG's kept as `lfg_text`."""
    d = d or load()
    texts = d.get("texts") or {}
    own = [dict(p, text=texts[p["id"]], lfg_text=p["text"]) if p["id"] in texts else p for p in BUILTIN]
    return own + [p for p in d["catalog"] if p.get("id") not in {b["id"] for b in BUILTIN}]


def set_text(pid, text):
    """Your wording for a "How Claude talks to you" rule: what Claude is told when it's on. Empty puts LFG's back.
    Your own rules are reworded in place."""
    p = _pref(pid)
    if p["group"] != STYLE or p["kind"] != "switch":
        raise ValueError("only the switches under \"%s\" can be reworded" % STYLE)
    text = str(text or "").strip()
    if len(text) > 4000:
        raise ValueError("keep a rule under 4000 characters")
    d = load()
    if p.get("custom"):
        if not text:
            raise ValueError("a rule of your own needs some wording")
        for x in d["catalog"]:
            if x.get("id") == pid:
                x["text"] = text
    else:
        texts = dict(d.get("texts") or {})
        if text and text != next(b["text"] for b in BUILTIN if b["id"] == pid):
            texts[pid] = text
        else:
            texts.pop(pid, None)
        d["texts"] = texts
    _save(d)
    write_defaults_file(d)
    return {"id": pid, "text": text}


def _pref(pid, d=None):
    p = next((x for x in catalog(d) if x["id"] == pid), None)
    if not p:
        raise ValueError("no preference %r (see `lfg prefs`)" % pid)
    return p


def _coerce(p, value):
    if p["kind"] == "number":
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValueError("%s is a whole number" % p["id"]) from None
        if not p.get("min", 0) <= v <= p.get("max", 10 ** 6):
            raise ValueError("%s is between %s and %s" % (p["id"], p.get("min", 0), p.get("max")))
        return v
    if p["kind"] == "switch":
        if isinstance(value, bool):
            return value
        v = str(value).lower()
        if v in ("on", "true", "yes", "1"):
            return True
        if v in ("off", "false", "no", "0"):
            return False
        raise ValueError("%s is on or off" % p["id"])
    vals = [o["value"] for o in p["options"]]
    if value not in vals:
        raise ValueError("%s is one of %s" % (p["id"], ", ".join(vals)))
    return value


def _rank(p, value):
    """Higher is looser. Switches: on is looser for enforced rules (they allow something). Numbers: bigger."""
    if p["kind"] == "number":
        return value
    if p["kind"] == "switch":
        return 1 if value else 0
    return [o["value"] for o in p["options"]].index(value)


def effective(session_id=None, d=None):
    d = d or load()
    out = {}
    over = d["sessions"].get(session_id or "", {})
    for p in catalog(d):
        out[p["id"]] = over.get(p["id"], d["defaults"].get(p["id"], p["default"]))
    return out


def _text(p, value, values=None):
    if p["kind"] == "number":
        return None  # shown inside the choice it belongs to
    if p["kind"] == "switch":
        if not value:
            return p.get("off_text")
        t = p.get("text")
        if t and p.get("why"):
            t += " Why: %s" % p["why"]
        if t and p.get("example"):
            t += " For example: %s" % p["example"]
        return t
    o = next((o for o in p["options"] if o["value"] == value), None)
    t = o and o["text"]
    return t.format(**(values or {})) if t and "{" in t else t


def set_pref(pid, value, session=None, by_agent=False):
    """Set a default (session=None) or one session's value. by_agent: refuse anything that loosens a rule."""
    d = load()
    p = _pref(pid, d)
    value = _coerce(p, value)
    if session is not None and not re.match(r"^[0-9a-f-]{36}$", session):
        raise ValueError("not a session id: %r" % session)
    cur = effective(session, d)[pid]
    if by_agent and _rank(p, value) > _rank(p, cur):
        raise PermissionError("loosening %s is yours to do: lfg ui → Sessions → Rules, or `! lfg prefs set` in your "
                              "own terminal" % pid)
    if session is None:
        if value == p["default"]:
            d["defaults"].pop(pid, None)
        else:
            d["defaults"][pid] = value
    else:
        s = d["sessions"].setdefault(session, {})
        if value == d["defaults"].get(pid, p["default"]):
            s.pop(pid, None)
        else:
            s[pid] = value
        if not s:
            d["sessions"].pop(session, None)
    _save(d)
    if session is None:
        write_defaults_file(d)
    return {"id": pid, "value": value, "session": session}


def clear_session(session):
    d = load()
    d["sessions"].pop(session, None)
    _save(d)
    return {"session": session, "cleared": True}


def add_custom(pid, group, title, text, off_text="", default=True, why="", example="", repo="", source=""):
    """One of your own rules as a switch (e.g. split out of CLAUDE.md, or approved from a correction). Instruction
    only, never enforced. why and example are told to Claude with it; repo limits it to that repo's sessions."""
    if not re.match(r"^[a-z0-9][a-z0-9_-]{1,60}$", pid or ""):
        raise ValueError("id is lowercase letters, digits, - and _")
    if pid in {b["id"] for b in BUILTIN}:
        raise ValueError("%s is a built-in preference" % pid)
    d = load()
    d["catalog"] = [x for x in d["catalog"] if x.get("id") != pid] + [
        {"id": pid, "group": group or "Yours", "title": title, "kind": "switch", "default": bool(default),
         "text": text.strip(), "off_text": (off_text or "").strip(), "custom": True,
         **{k: v for k, v in (("why", str(why or "").strip()), ("example", str(example or "").strip()),
                              ("repo", str(repo or "")), ("sources", [source] if source else [])) if v}}]
    _save(d)
    write_defaults_file(d)
    return {"id": pid}


def update_custom(pid, text=None, why=None, example=None, title=None, add_source=""):
    """Change one of your own rules: None leaves a part as it is, "" clears why or example."""
    d = load()
    x = next((x for x in d["catalog"] if x.get("id") == pid), None)
    if not x:
        raise ValueError("%s is not one of your own rules" % pid)
    if text is not None:
        if not str(text).strip():
            raise ValueError("a rule of your own needs some wording")
        if len(str(text)) > 4000:
            raise ValueError("keep a rule under 4000 characters")
        x["text"] = str(text).strip()
    if title is not None and str(title).strip():
        x["title"] = str(title).strip()
    for k, v in (("why", why), ("example", example)):
        if v is not None:
            if str(v).strip():
                x[k] = str(v).strip()
            else:
                x.pop(k, None)
    if add_source and add_source not in (x.get("sources") or []):
        x["sources"] = list(x.get("sources") or []) + [add_source]
    _save(d)
    write_defaults_file(d)
    return {"id": pid}


def remove_custom(pid):
    d = load()
    d["catalog"] = [x for x in d["catalog"] if x.get("id") != pid]
    d["defaults"].pop(pid, None)
    for s in d["sessions"].values():
        s.pop(pid, None)
    _save(d)
    write_defaults_file(d)
    return {"removed": pid}


# ---------------------------------------------------------------- what Claude reads

def render(values, d, only=None, header="Your rules", repo=None):
    """Rules limited to one repo are left out unless repo is that repo."""
    groups = {}
    if only is not None and "rewrite_lines" in only:
        only = set(only) | {"rewrite"}
    for p in catalog(d):
        if only is not None and p["id"] not in only:
            continue
        if p.get("repo") and p["repo"] != repo:
            continue
        t = _text(p, values[p["id"]], values)
        if t:
            groups.setdefault(p["group"], []).append("- %s" % t)
    if not groups:
        return ""
    body = "\n\n".join("## %s\n%s" % (g, "\n".join(ls)) for g, ls in groups.items())
    return "# %s\n\n%s\n" % (header, body)


def write_defaults_file(d=None):
    d = d or load()
    text = ("<!-- Written by LFG from your preferences (lfg ui → Preferences). Edit them there, not here. -->\n"
            + render(effective(None, d), d, header="Your rules (defaults for every session)"))
    if C.read_text(PREFS_MD) != text:
        C.ensure_dir(os.path.dirname(PREFS_MD))
        C.write_text(PREFS_MD, text, mode=0o644)
    return PREFS_MD


def session_note(session_id, d=None):
    """What's different for this session, for the hooks to tell it. Empty if nothing is."""
    d = d or load()
    over = d["sessions"].get(session_id or "", {})
    if not over:
        return ""
    values = effective(session_id, d)
    text = render(values, d, only=set(over), header="Rules changed for this session only")
    return (text + "\nThese replace the matching defaults from lfg-preferences.md for the rest of this session. "
            "Changing them back is the user's, in lfg ui → Sessions → Rules.")


# ---------------------------------------------------------------- hooks

HEREDOC = re.compile(r"<<-?\s*(['\"])(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?=\n|$)", re.S)


def _commands(cmd, depth=0):
    """(argv) for every simple command in a shell string, including `sh -c "…"` and $(…). The bodies of quoted
    heredocs (<<'EOF') are left out: the shell passes them on as text without running anything in them."""
    from . import guard as G
    if depth > 6 or not cmd or not cmd.strip():
        return
    cmd = HEREDOC.sub("<<HEREDOC", cmd)
    lines = [ln for ln in re.split(r"(?<!\\)\n", cmd) if ln.strip()]
    if len(lines) > 1:  # a newline separates commands, like ;
        for ln in lines:
            yield from _commands(ln, depth + 1)
        return
    for inner in G._substitutions(cmd):
        yield from _commands(inner, depth + 1)
    segs, _ = G._segments(G._tokens(cmd))
    for seg in segs:
        try:
            _, argv = G._strip_wrappers(seg)
        except Exception:  # noqa: BLE001 - a wrapper the guard refuses: nothing for us to check
            continue
        if not argv:
            continue
        base = os.path.basename(argv[0])
        if base in ("sh", "bash", "zsh", "dash") and len(argv) >= 3 and argv[1] in ("-c", "-lc", "-ic", "-ec"):
            yield from _commands(argv[2], depth + 1)
            continue
        yield argv


def _git_sub(argv):
    i, args = 1, argv
    while i < len(args):
        a = args[i]
        if a in ("-C", "-c", "--git-dir", "--work-tree") and i + 1 < len(args):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a, args[i + 1:]
    return None, []


def _git_dir(argv, cwd):
    """The folder a git command runs in: cwd, moved by each `-C <dir>`."""
    i = 1
    while i < len(argv) - 1 and argv[i].startswith("-"):
        if argv[i] == "-C":
            cwd = os.path.join(cwd or os.getcwd(), os.path.expanduser(argv[i + 1]))
        i += 2 if argv[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    return cwd


def _branch(cwd):
    try:
        cp = subprocess.run(["git", "branch", "--show-current"], cwd=cwd or None, capture_output=True, text=True,
                            timeout=5)
        return cp.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_out(cwd, *args):
    try:
        cp = subprocess.run(["git", *args], cwd=cwd or None, capture_output=True, text=True, timeout=10)
        return cp.stdout.strip() if cp.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _lines(numstat):
    n = 0
    for ln in (numstat or "").splitlines():
        a, _, rest = ln.partition("\t")
        b = rest.partition("\t")[0]
        n += (int(a) if a.isdigit() else 0) + (int(b) if b.isdigit() else 0)
    return n


def _my_open_pr(cwd, branch):
    """True if this branch has an open PR that you opened (asked of GitHub with your gh login)."""
    try:
        cp = subprocess.run(["gh", "pr", "view", branch, "--json", "state,author"], cwd=cwd or None,
                            capture_output=True, text=True, timeout=20)
        pr = json.loads(cp.stdout) if cp.returncode == 0 else {}
        me = subprocess.run(["gh", "api", "user", "-q", ".login"], cwd=cwd or None, capture_output=True, text=True,
                            timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return pr.get("state") == "OPEN" and bool(me) and (pr.get("author") or {}).get("login") == me


MERGE_VALUE_FLAGS = {"-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--subject", "-A",
                     "--author-email", "--match-head-commit"}


def _merge_target(argv):
    """(PR selector or None, ["-R", repo] or [], deletes the branch?) for `gh pr merge ...`."""
    pr, repo, delete, i = None, [], False, 3
    while i < len(argv):
        a = argv[i]
        if a in MERGE_VALUE_FLAGS:
            if a in ("-R", "--repo") and i + 1 < len(argv):
                repo = ["-R", argv[i + 1]]
            i += 2
            continue
        if a.startswith("--repo="):
            repo = ["-R", a.split("=", 1)[1]]
        elif a in ("-d", "--delete-branch") or (a.startswith("-") and not a.startswith("--") and "d" in a[1:]
                                                 and a[1:].isalpha()):
            delete = True
        elif not a.startswith("-") and pr is None:
            pr = a
        i += 1
    return pr, repo, delete


def _pr_head(cwd, pr, repo):
    """The branch a PR comes from, asked of GitHub ("" if gh can't say)."""
    try:
        cp = subprocess.run(["gh", "pr", "view"] + ([pr] if pr else []) + repo + ["--json", "headRefName", "-q",
                                                                                  ".headRefName"],
                            cwd=cwd or None, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return cp.stdout.strip() if cp.returncode == 0 else ""


def _rewrite_allowed(values, cwd, amend_all=False, push=False, branch=None, local="HEAD"):
    """None if amending (or force-pushing the amend) is within your rule here, else why not. A force-push that names
    its branch (`git push -f origin feat`, `feat:feat`) is judged on that branch and its local commit `local`, not on
    whatever the checkout it runs from has checked out."""
    mode = values.get("rewrite", "never")
    if mode == "never":
        return '"Amend and force-push" (Git) is "Never"'
    branch = branch or _branch(cwd)
    if branch in PROTECTED_BRANCHES:
        return "rewriting main, master, qa or prod is never allowed"
    if mode == "anytime":
        return None
    limit = int(values.get("rewrite_lines") or 20)
    if not branch or not _my_open_pr(cwd, branch):
        return "amending is only for small fixes on a branch with your own open PR, and %s has none" % (
            branch or "this checkout")
    if push:
        remote = (local == "HEAD" and _git_out(cwd, "rev-parse", "--verify", "-q", "@{upstream}")) or \
            _git_out(cwd, "rev-parse", "--verify", "-q", "origin/" + branch)
        if not remote:
            return "can't tell what the force-push would replace (no upstream for %s)" % branch
        if _git_out(cwd, "rev-parse", remote + "^") != _git_out(cwd, "rev-parse", local + "^"):
            return "this force-push would replace more than the last commit; only an amended last commit may go"
        n = _lines(_git_out(cwd, "diff", "--numstat", remote, local))
    else:
        n = _lines(_git_out(cwd, "diff", "--cached", "--numstat"))
        if amend_all:
            n += _lines(_git_out(cwd, "diff", "--numstat"))
    if n > limit:
        return "this changes %d lines; amending is for small fixes of at most %d (make a new commit, or raise the " \
               "limit in Preferences)" % (n, limit)
    return None


def check_command(cmd, values, cwd=None):
    """Why this shell command breaks a rule, or None."""
    for argv in _commands(cmd):
        base = os.path.basename(argv[0])
        if base == "cd" and len(argv) > 1 and not argv[1].startswith("-"):  # `cd <worktree> && git commit --amend`
            cwd = os.path.join(cwd or os.getcwd(), os.path.expanduser(argv[1]))
            continue
        if base == "git":
            here = _git_dir(argv, cwd)  # -C moves only this command, unlike cd
            sub, rest = _git_sub(argv)
            if sub == "commit":
                if values["commits"] == "never":
                    return '"Commits" (Git) is "Never: I make every commit"'
                if "--amend" in rest:
                    why = _rewrite_allowed(values, here, amend_all=any(a in ("-a", "--all") or
                                                                      (a.startswith("-") and not a.startswith("--")
                                                                       and "a" in a) for a in rest))
                    if why:
                        return why
            if sub == "push":
                if values["push"] == "never":
                    return '"Push" (Git) is "Never: I push"'
                force = any(a in ("-f", "--force", "--force-with-lease", "--force-if-includes") or
                            a.startswith("--force-with-lease=") for a in rest) or \
                    any(a.startswith("+") for a in rest if not a.startswith("-"))
                if force:
                    if values["rewrite"] == "never":
                        return 'force-pushing is off: "Amend and force-push" (Git) is "Never"'
                    specs = [a.lstrip("+") for a in rest if not a.startswith("-")][1:]  # after the remote
                    # each refspec is local:remote (or one name for both); none means this checkout's branch
                    pairs = [(sp.split(":")[0] or "HEAD", sp.split(":")[-1].replace("refs/heads/", "")) for sp in specs]
                    pairs = pairs or [("HEAD", _branch(here))]
                    if any(dst in PROTECTED_BRANCHES for _, dst in pairs if dst):
                        return "force-pushing main, master, qa or prod is never allowed"
                    if values["rewrite"] == "review":
                        for src, dst in pairs:
                            why = _rewrite_allowed(values, here, push=True, branch=dst or None,
                                                   local=src.replace("refs/heads/", "") if specs else "HEAD")
                            if why:
                                return why
        if base == "gh" and argv[1:3] == ["pr", "create"] and values.get("open_pr", "never") == "never":
            return '"Opening PRs" (GitHub) is "Never: I open them"'
        if base == "gh" and argv[1:3] == ["pr", "merge"]:
            if values["merge_pr"] == "never":
                return '"Merging PRs" (GitHub) is "Never: I merge"'
            if "--squash" not in argv and "-s" not in argv:
                return 'PRs are merged as one squashed commit ("Merging PRs", GitHub): add --squash'
            pr, repo, delete = _merge_target(argv)
            if delete or values.get("delete_merged"):
                head = _pr_head(cwd, pr, repo)
                if not head:
                    return "LFG couldn't ask GitHub which branch this PR comes from, so it can't check the delete"
                if head in PROTECTED_BRANCHES:
                    if delete:
                        return "this PR comes from %s, which is never deleted: drop --delete-branch" % head
                elif delete and not values.get("delete_merged"):
                    return '"Delete the branch after merging" (GitHub) is off: drop --delete-branch'
                elif not delete:
                    return "your rule is to delete the PR's branch (%s) after merging: add --delete-branch" % head
        if base == "lfg" and argv[1:3] == ["prefs", "set"] and "--by-user" in argv:
            return "--by-user is only for your own terminal"
        if base == "lfg" and argv[1:2] == ["corrections"] and len(argv) > 2:
            from . import corrections as CR
            if argv[2] in CR.USER_ONLY:
                return "`lfg corrections %s` is yours: you decide what becomes a rule (lfg ui → Corrections, or " \
                       "`! lfg corrections %s` in Claude Code)" % (argv[2], argv[2])
    return None


def _hook_input():
    try:
        return json.load(sys.stdin)
    except ValueError:
        return {}


def _seen():
    return C.read_json(_seen_path(), {}) or {}


def hook(event):
    """Entry for the four hooks. Never breaks a session: on an internal error it lets the tool run."""
    data = _hook_input()
    sid = data.get("session_id") or ""
    try:
        d = load()
        if event == "stop":
            from . import corrections as CR
            CR.capture(data)
            return 0
        if event in ("session-start", "prompt"):
            # A session read the defaults file when it started. Tell it again only when something changed since:
            # its own rules (from Sessions → Rules), the defaults (from Preferences) or which of the user's own
            # named rules exist (from Settings → Rules; their text is read on demand with `lfg rule`).
            note = session_note(sid, d)
            dflt = render(effective(None, d), d, header="Your rules (defaults)")
            try:
                from . import settings as S
                own = sorted(S.own_rules())
            except Exception:  # noqa: BLE001  a broken rule file must never block a session
                own = []
            try:
                from . import corrections as CR
                extra = CR.session_note(data.get("cwd") or "", effective(sid, d))
            except Exception:  # noqa: BLE001  never block a session over it
                extra = ""
            h = lambda t: hashlib.sha1(t.encode()).hexdigest()[:12]  # noqa: E731
            cur = {"digest": h(note + "\0" + dflt + "\0" + ",".join(own) + "\0" + extra), "defaults": h(dflt),
                   "note": h(note), "own": own, "extra": h(extra)}
            seen = _seen()
            prev = seen.get(sid)
            seen[sid] = cur
            C.write_json(_seen_path(), dict(list(seen.items())[-500:]))
            if event == "session-start":
                out = "\n\n".join(x for x in (note, extra) if x)
            else:
                parts = []
                if not isinstance(prev, dict) or prev.get("digest") == cur["digest"]:
                    prev = cur  # nothing changed since the session last heard
                prev = dict(cur, **prev)  # a session seen before a key was recorded: that part counts as unchanged
                if prev["defaults"] != cur["defaults"]:
                    parts.append(dflt + "\nThe user changed their default rules while this session was open; these "
                                 "replace lfg-preferences.md as you read it at the start.")
                if prev["note"] != cur["note"] or parts:
                    parts.append(note or "This session now follows the user's default rules, with no session "
                                 "changes.")
                if prev.get("extra", cur["extra"]) != cur["extra"]:
                    parts.append(extra or "The user's rules for this repo and the corrections queue no longer apply; "
                                 "stop queuing corrections.")
                added = [n for n in own if n not in prev["own"]]
                gone = [n for n in prev["own"] if n not in own]
                if added:
                    parts.append("The user added rules of their own while this session was open (follow them; read "
                                 "each with `lfg rule <name>`): %s." % ", ".join(added))
                if gone:
                    parts.append("The user removed these rules of their own; stop following them: %s."
                                 % ", ".join(gone))
                parts.append(_take_reminder(sid, d))  # "Remind it of my style", once
                out = "\n\n".join(x for x in parts if x)
            if out:
                print(json.dumps({"hookSpecificOutput": {
                    "hookEventName": "SessionStart" if event == "session-start" else "UserPromptSubmit",
                    "additionalContext": out}}))
            return 0
        if event == "pre-tool":
            tool, ti = data.get("tool_name"), data.get("tool_input") or {}
            if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                p = os.path.realpath(os.path.expanduser(str(ti.get("file_path") or "")))
                from . import corrections as CR
                if p in (os.path.realpath(_state_path()), os.path.realpath(PREFS_MD),
                         os.path.realpath(CR._path())):
                    sys.stderr.write("Blocked by your rules: %s holds your rules; change them in lfg ui → "
                                     "Preferences.\n" % p)
                    return 2
            if tool == "Bash":
                why = check_command(str(ti.get("command") or ""), effective(sid, d), cwd=data.get("cwd"))
                if why:
                    sys.stderr.write("Blocked by your rules: %s. Change it in lfg ui → Preferences (every session) "
                                     "or Sessions → Rules (this session only) if you meant to.\n" % why)
                    return 2
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("lfg prefs hook error: %s\n" % type(e).__name__)
    return 0


# ---------------------------------------------------------------- installing into Claude Code

HOOKS = (("SessionStart", "startup|resume|clear|compact", "session-start"), ("UserPromptSubmit", None, "prompt"),
         ("PreToolUse", "Bash|Edit|Write|MultiEdit|NotebookEdit", "pre-tool"), ("Stop", None, "stop"))


def _hook_cmd(event):
    return "%s prefs hook %s" % (C.lfg_bin(), event)


def installed():
    from . import claudecfg as CC
    s = C.read_json(os.path.join(C.HOME, ".claude", "settings.json"), {}) or {}
    have = json.dumps(s.get("hooks") or {})
    md = C.read_text(os.path.join(C.HOME, ".claude", "CLAUDE.md"))
    return {"hooks": all(_hook_cmd(e) in have for _, _, e in HOOKS), "import": IMPORT_LINE in md,
            "file": os.path.isfile(PREFS_MD), "ledger": len(CC.find(tag="prefs-hook"))}


def install():
    """Add the four hooks to ~/.claude/settings.json and the import line to ~/.claude/CLAUDE.md, through the change
    ledger (backed up, undone by `lfg changes undo` / `lfg uninstall`)."""
    from . import claudecfg as CC
    write_defaults_file()
    settings = os.path.join(C.HOME, ".claude", "settings.json")
    done = []
    for ev, matcher, name in HOOKS:
        entry = {"hooks": [{"type": "command", "command": _hook_cmd(name), "timeout": 10}]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        if CC.json_list_add(settings, ["hooks", ev], [entry], "your rules: %s hook" % ev, "prefs", tag="prefs-hook"):
            done.append(ev)
    md = os.path.join(C.HOME, ".claude", "CLAUDE.md")
    if IMPORT_LINE not in C.read_text(md):
        CC.lines_add(md, ["", "# Your rules", IMPORT_LINE], "your rules: CLAUDE.md imports lfg-preferences.md",
                     "prefs", tag="prefs-import")
        done.append("CLAUDE.md import")
    return {"added": done, **installed()}
