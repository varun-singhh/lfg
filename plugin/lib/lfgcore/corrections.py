"""Corrections: what you correct Claude on, queued for you to turn into rules.

Two ways in. The Preferences Stop hook (every session, not only LFG repos) reads only what a turn added to the
transcript and queues messages that read like a correction ("no, use X", "I told you"), a tool call you rejected with
a reason, and what you said right after rejecting or interrupting one. Most corrections are a feeling rather than a
keyword, so every session is also told to queue those itself with `lfg corrections add`.

Nothing in the queue is a rule. You approve an item (with the wording, a why and an example, for every repo or only
this one), merge it into a rule you have, keep it in your second-brain (background about you, not how Claude should
work), or discard it. Approved items become your own Preferences rules in the group "From your corrections", each
with its own switch. Approving, merging, saving, discarding and the on/off switch are yours: the Preferences hook and
the guard block Claude from running them.

Everything is in ~/.lfg/state/corrections.json (mode 600): {"enabled", "items": [...]}; transcript read positions
are in state/corrections-offsets.json.
"""
import contextlib
import difflib
import hashlib
import json
import os
import re

from . import common as C

GROUP = "From your corrections"
USER_ONLY = {"approve", "merge", "discard", "brain", "on", "off"}
KINDS = ("said", "rejected", "interrupted", "flagged")
MAX_SAID = 1200      # a longer message is a brief or a paste, not a correction
KEEP_TEXT = 600      # what is kept of each side
KEEP_DONE = 200      # resolved items kept for history
MAX_PENDING = 300
FIRST_READ = 300_000  # a session seen for the first time: only its last bytes

REJECTED = "The user doesn't want to proceed with this tool use."
SAID_AFTER_REJECT = "the user said:\n"
INTERRUPTED = "[Request interrupted by user"
NOT_A_REASON = ("The user wants to clarify these questions",)  # AskUserQuestion's own "chat about this"

# Read like a correction wherever they appear.
ANYWHERE = re.compile(
    r"\b(i (already )?told you|i (already )?said|as i said|i asked (you )?(to|for|not)|you keep|you always|"
    r"stop (doing|using|adding|asking|writing)|why (did|would|are|do) you|you (didn'?t|did not|forgot|missed|"
    r"ignored|shouldn'?t have|weren'?t supposed)|that'?s not what i|not what i (asked|meant|wanted|said)|"
    r"how many times|again\?|wrong (file|branch|repo|one))\b", re.I)
# Read like a correction at the start of a message.
OPENING = re.compile(r"^\W*(no|nope|nah|wrong|actually|stop|don'?t|do not|never|undo|revert|instead|wait|"
                     r"hold on|not that|that'?s wrong|that is wrong|incorrect)\b", re.I)
# "no, that's fine": agreement that opens like a correction.
AGREEING = re.compile(r"^\W*(no|nope|nah)\W+(it'?s|that'?s|that is|its|thats|you'?re|all)?\s*"
                      r"(ok|okay|fine|good|alright|all good|right|no problem|no worries|worries|problem|need)\b|"
                      r"^\W*no (problem|worries|need)\b", re.I)
CONTINUE = re.compile(r"^\W*(continue|go on|go ahead|carry on|resume|keep going|proceed|ok|okay|yes|y)\W*$", re.I)
WRAPPERS = re.compile(r"<(pasted_content|system-reminder|command-[a-z]+|local-command-[a-z]+)[^>]*>.*?"
                      r"</\1[^>]*>", re.S)

FLAG_NOTE = (
    "Corrections are on: when the user corrects you, pushes back, or sounds frustrated with how you worked (even "
    "without saying \"no\"), queue it once, at the end of your reply, with "
    "`lfg corrections add \"<what they said, in their words>\" --did \"<what you had done>\" --note \"<the lesson, "
    "one sentence>\"`. It only queues it for the user to review; it is never a rule until they approve it. Don't "
    "queue agreement, a new request, or anything already queued this session. Queuing replaces the \"Remember?\" "
    "offer for corrections; keep offering that for decisions, gotchas and root causes.")


# ---------------------------------------------------------------- storage

def _path():
    return C.lfg_path("state", "corrections.json")


def _offsets_path():
    return C.lfg_path("state", "corrections-offsets.json")


@contextlib.contextmanager
def _locked():
    """The hook and the dashboard both write the queue; one at a time."""
    import fcntl
    C.ensure_dir(C.lfg_path("state"))
    fd = os.open(_path() + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def load():
    d = C.read_json(_path(), {}) or {}
    return {"enabled": bool(d.get("enabled")), "items": list(d.get("items") or [])}


def _save(d):
    pending = [x for x in d["items"] if x.get("status") == "pending"][-MAX_PENDING:]
    done = [x for x in d["items"] if x.get("status") != "pending"][-KEEP_DONE:]
    keep = {id(x) for x in pending + done}
    d["items"] = [x for x in d["items"] if id(x) in keep]
    C.write_json(_path(), d)


def enabled():
    return load()["enabled"]


def set_enabled(on):
    with _locked():
        d = load()
        d["enabled"] = bool(on)
        _save(d)
    return {"enabled": bool(on)}


# ---------------------------------------------------------------- cleaning text

def _mask(text):
    from .hooks import SECRET_OUTPUT_RX
    for name, rx in SECRET_OUTPUT_RX:
        text = rx.sub("[%s removed]" % name, text)
    return text


def _clip(text, n=KEEP_TEXT):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def clean(text, n=KEEP_TEXT):
    return _clip(_mask(str(text or "")), n)


def own_words(text):
    """What the user typed, without pasted material, reminders and command wrappers."""
    return WRAPPERS.sub(" ", str(text or "")).strip()


def detect(text):
    """Why a message the user typed reads like a correction, or None."""
    t = own_words(text)
    if not t or len(t) > MAX_SAID or t.startswith(("<", "[")):
        return None
    if AGREEING.search(t):
        rest = AGREEING.sub("", t, count=1)
        m = ANYWHERE.search(rest)
        return ("says \"%s\"" % m.group(0).lower()) if m else None
    m = ANYWHERE.search(t)
    if m:
        return "says \"%s\"" % m.group(0).lower()
    m = OPENING.search(t)
    if m:
        return "opens with \"%s\"" % m.group(1).lower()
    return None


# ---------------------------------------------------------------- reading a transcript

def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _tool_line(block):
    name = block.get("name") or "tool"
    ti = block.get("input") or {}
    what = ti.get("command") or ti.get("file_path") or ti.get("url") or ti.get("pattern") or ti.get("description") \
        or ti.get("query") or ""
    return ("%s: %s" % (name, what)) if what else name


def _result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(b.get("text") or "" for b in c if isinstance(b, dict))
    return str(c or "")


def scan(lines, state=None):
    """Corrections in transcript lines (already parsed or raw JSON), with what Claude had done before each.
    state carries what is pending across turns: {"after": kind, "did": text} when the last thing seen was a rejection
    or interruption whose explanation hasn't come yet. Returns (items, state)."""
    state = dict(state or {})
    did_text, did_tool = state.get("did_text", ""), state.get("did_tool", "")
    out = []
    for line in lines:
        ev = line
        if not isinstance(ev, dict):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
        if not isinstance(ev, dict) or ev.get("isSidechain") or ev.get("isMeta"):
            continue
        msg = ev.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if ev.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and (b.get("text") or "").strip():
                    did_text, did_tool = b["text"], ""
                elif b.get("type") == "tool_use":
                    did_tool = _tool_line(b)
            continue
        if ev.get("type") != "user":
            continue
        did = " | ".join(x for x in (_clip(did_text, 300), did_tool) if x)
        results = [b for b in content or [] if isinstance(b, dict) and b.get("type") == "tool_result"] \
            if isinstance(content, list) else []
        for r in results:
            body = _result_text(r)
            if REJECTED not in body:
                continue
            reason = body.split(SAID_AFTER_REJECT, 1)[1].strip() if SAID_AFTER_REJECT in body else ""
            if reason and not reason.startswith(NOT_A_REASON):
                out.append({"kind": "rejected", "said": reason, "did": did,
                            "why": "you rejected a tool call and said why"})
                state.pop("after", None)
            elif not reason:
                state.update(after="rejected", did=did)
        if results:
            continue
        text = _text_of(content)
        if not text.strip():
            continue
        if text.strip().startswith(INTERRUPTED):
            state.setdefault("after", "interrupted")
            state.setdefault("did", did)
            continue
        words = own_words(text)
        if state.get("after"):
            kind, before = state.pop("after"), state.pop("did", did)
            if words and not CONTINUE.match(words) and len(words) <= MAX_SAID:
                out.append({"kind": kind, "said": words, "did": before,
                            "why": "what you said after %s" % ("rejecting a tool call" if kind == "rejected"
                                                               else "interrupting Claude")})
                did_text, did_tool = "", ""
                continue
        why = detect(text)
        if why:
            out.append({"kind": "said", "said": words, "did": did, "why": why})
        did_text, did_tool = "", ""
    state["did_text"], state["did_tool"] = _clip(did_text, 300), did_tool
    return out, state


def _read_new(path, session):
    """Whole lines the transcript gained since the last read, and the state carried for it."""
    offsets = C.read_json(_offsets_path(), {}) or {}
    st = offsets.get(session) or {}
    size = os.path.getsize(path)
    start = st.get("offset", max(0, size - FIRST_READ))
    if st.get("path") != path or start > size:
        start, st = max(0, size - FIRST_READ), {}
    with open(path, "rb") as f:
        f.seek(start)
        chunk = f.read()
    end = chunk.rfind(b"\n") + 1
    text = chunk[:end].decode("utf-8", "replace")
    lines = text.splitlines()
    if start and st.get("offset") is None and lines:
        lines = lines[1:]  # a first read starting mid-line
    return lines, st.get("state") or {}, (offsets, start + end)


def _save_offset(offsets, session, path, offset, state):
    import time
    week_ago = time.time() - 14 * 86400
    offsets = {k: v for k, v in offsets.items() if (v.get("at") or 0) > week_ago}
    offsets[session] = {"path": path, "offset": offset, "state": state, "at": time.time()}
    C.write_json(_offsets_path(), offsets)


def capture(data):
    """The Stop hook: queue what this turn added. Does nothing while corrections are off."""
    if not enabled():
        return []
    path, sid = data.get("transcript_path") or "", data.get("session_id") or ""
    if not path or not os.path.isfile(path):
        return []
    lines, state, (offsets, offset) = _read_new(path, sid or path)
    found, state = scan(lines, state)
    _save_offset(offsets, sid or path, path, offset, state)
    return [_queue(x, sid, data.get("cwd") or "") for x in found]


# ---------------------------------------------------------------- the queue

def _repo(cwd):
    root = C.git_main_root_fast(cwd) if cwd and os.path.isdir(cwd) else None
    return root or ""


def _queue(x, session, cwd):
    said, did = clean(x.get("said")), clean(x.get("did"))
    note = clean(x.get("note") or "", 300)
    root = _repo(cwd)
    key = hashlib.sha1(("%s\0%s" % (session, said.lower())).encode()).hexdigest()[:8]
    item = {"id": "c-" + key, "at": C.now_iso(), "kind": x.get("kind", "said"), "said": said, "did": did,
            "why": x.get("why", ""), "note": note, "session": session, "cwd": cwd, "repo": root,
            "repo_name": os.path.basename(root) if root else "", "status": "pending"}
    with _locked():
        d = load()
        if any(i["id"] == item["id"] for i in d["items"]):
            return None
        d["items"].append(item)
        _save(d)
    return item


def add(said, did="", note="", session="", cwd=None):
    """Queue one by hand, or from Claude when it reads a correction no pattern catches. Never a rule by itself."""
    said = str(said or "").strip()
    if not said:
        raise ValueError("say what the user said")
    if not enabled():
        raise ValueError("corrections are off (the user turns them on in lfg ui → Corrections)")
    item = _queue({"kind": "flagged", "said": said, "did": did, "note": note, "why": "Claude read it as a correction"},
                  session, cwd or os.getcwd())
    return item or {"queued": False, "why": "already queued"}


def items(status="pending"):
    d = load()
    xs = [x for x in d["items"] if status in (None, "all") or x.get("status") == status]
    return list(reversed(xs))


def get(cid):
    x = next((i for i in load()["items"] if i["id"] == cid), None)
    if not x:
        raise ValueError("no correction %r (see `lfg corrections`)" % cid)
    return x


def _resolve(cid, **fields):
    with _locked():
        d = load()
        x = next((i for i in d["items"] if i["id"] == cid), None)
        if not x:
            raise ValueError("no correction %r" % cid)
        if x.get("status") != "pending":
            raise ValueError("%s is already %s" % (cid, x["status"]))
        x.update(fields, done_at=C.now_iso())
        _save(d)
    return x


# ---------------------------------------------------------------- similar rules

def _words(t):
    return set(re.findall(r"[a-z0-9']{3,}", str(t or "").lower()))


def similarity(a, b):
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    overlap = len(wa & wb) / min(len(wa), len(wb))
    seq = difflib.SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()
    return round(max(overlap * 0.8, seq), 2)


def similar(text, limit=3, floor=0.45):
    """Your rules that already say much the same, closest first: candidates to merge into rather than add."""
    from . import prefs as P
    out = []
    for p in P.catalog():
        if p.get("kind") != "switch" or not (p.get("custom") or p.get("group") == P.STYLE):
            continue
        body = " ".join(x for x in (p.get("title"), p.get("text")) if x)
        s = similarity(text, body)
        if s >= floor:
            out.append({"id": p["id"], "title": p.get("title"), "text": p.get("text"), "score": s,
                        "repo": p.get("repo", "")})
    return sorted(out, key=lambda x: -x["score"])[:limit]


# ---------------------------------------------------------------- review: yours only

def _rule_id(title):
    slug = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")[:40] or "rule"
    return "cr-%s-%s" % (slug, hashlib.sha1(("%s%s" % (title, C.now_iso())).encode()).hexdigest()[:4])


def approve(cid, text, title="", why="", example="", scope="global"):
    """Turn a queued correction into one of your rules. scope: global (every session) or project (only sessions in
    the repo it was said in)."""
    from . import prefs as P
    x = get(cid)
    text = str(text or "").strip()
    if not text:
        raise ValueError("write the rule: what Claude should do from now on")
    if scope not in ("global", "project"):
        raise ValueError("scope is global or project")
    if scope == "project" and not x.get("repo"):
        raise ValueError("this was said outside a git repo, so it can only be a rule for every repo")
    title = str(title or "").strip() or _clip(text, 60)
    pid = _rule_id(title)
    P.add_custom(pid, GROUP, title, text, why=why, example=example,
                 repo=x["repo"] if scope == "project" else "", source=cid)
    _resolve(cid, status="approved", rule=pid)
    return {"id": cid, "rule": pid, "scope": scope}


def merge(cid, rule, text="", why="", example=""):
    """Fold a queued correction into a rule you already have; new wording replaces the rule's when given."""
    from . import prefs as P
    get(cid)
    p = next((p for p in P.catalog() if p["id"] == rule), None)
    if not p:
        raise ValueError("no rule %r" % rule)
    if p.get("custom"):
        P.update_custom(rule, text=text or None, why=why or None, example=example or None, add_source=cid)
    elif text:
        P.set_text(rule, text)
    _resolve(cid, status="merged", rule=rule)
    return {"id": cid, "rule": rule}


def to_brain(cid, title, text):
    """Keep a queued correction as a note in your second-brain instead of a rule: background about you that Claude
    looks up when it matters, rather than something every session is told."""
    from . import knowledge as KN
    x = get(cid)
    text = str(text or "").strip() or x.get("note") or x["said"]
    title = str(title or "").strip() or _clip(text, 80)
    saved = KN.add("note", title, text)
    _resolve(cid, status="to second-brain", note_slug=saved.get("slug", ""))
    return {"id": cid, **saved}


def discard(cids):
    out = []
    for cid in cids:
        _resolve(cid, status="discarded")
        out.append(cid)
    return {"discarded": out}


def rules():
    """Your rules that came from corrections, with how many corrections each holds."""
    from . import prefs as P
    d = P.load()
    vals = P.effective(None, d)
    return [dict(p, on=vals.get(p["id"]), sources=list(p.get("sources") or [])) for p in P.catalog(d)
            if p.get("group") == GROUP]


# ---------------------------------------------------------------- what sessions are told

def session_note(cwd, values=None):
    """For the Preferences hooks: this repo's own rules (if any) and, while corrections are on, how to queue one."""
    from . import prefs as P
    d = P.load()
    root = _repo(cwd)
    parts = []
    if root:
        text = P.render(values or P.effective(None, d), d, only={p["id"] for p in P.catalog(d)
                                                                 if p.get("repo") == root},
                        header="Your rules for this repo (%s)" % os.path.basename(root), repo=root)
        if text:
            parts.append(text)
    if enabled():
        parts.append(FLAG_NOTE)
    return "\n\n".join(parts)


def summary():
    d = load()
    pend = [x for x in d["items"] if x.get("status") == "pending"]
    return {"enabled": d["enabled"], "pending": len(pend), "rules": len(rules())}
