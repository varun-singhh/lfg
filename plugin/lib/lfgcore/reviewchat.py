"""The chat on a PR review page. It is Studio's chat (claudesess.Live) pointed at a review: it opens on the session
that did the review, and can move to any Studio session or terminal session (a terminal one is forked first, so the
terminal's stays as it was). Each message carries the review in an <lfg-review> tag the page hides; when a turn ends,
the reply's ```json block is applied to the review (review.apply_changes) and what it changed is kept by the reply's
message id, as the chips under it."""
import os

from . import claudesess as CS
from . import common as C
from . import review as R

TAG = "<lfg-review"


def _pass(rec, n):
    p = next((x for x in rec["passes"] if x["n"] == int(n or 0)), None)
    if not p:
        raise R.ReviewError("no review %s on %s" % (n, R.ref(rec["repo"], rec["number"])))
    return p


def own_session(p):
    """The session that did this review pass, when it was run from the dashboard (an imported review has none)."""
    return (p.get("run") or {}).get("session_id") or None


def _is_studio(sid):
    return bool((CS._index().get(sid) or {}).get("lfg"))


def _shown(rec, p, sid):
    """The session whose conversation the chat shows when you point it at `sid` (default: the review's own, else the
    one made for this review). A terminal session shows its fork once there is one, else nothing yet."""
    own = own_session(p)
    sid = sid or own or rec.get("chat_session") or ""
    if not sid or sid in (own, rec.get("chat_session")) or _is_studio(sid):
        return sid or None
    return (rec.get("session_forks") or {}).get(sid)


def target(repo, number, n, sid=""):
    """Where the chat is pointed: {"session": the id whose transcript it shows (None before the first message),
    "to": the session you chose, "own": the review's own session, "forked": a terminal session shown as its fork}."""
    rec = R.need(repo, number)
    p = _pass(rec, n)
    shown = _shown(rec, p, sid)
    to = sid or own_session(p) or rec.get("chat_session") or None
    return {"session": shown, "to": to, "own": own_session(p), "forked": bool(shown and to and shown != to)}


def _context(rec, p, fid, edits):
    """What Claude needs to know about the review to answer, inside the <lfg-review> tag the page hides."""
    about = ""
    if fid:
        f = R.find(rec, fid)
        said = "".join("\n\nEarlier, Lee: %s\nYou: %s" % (x["q"], x["a"]) for x in f.get("chat") or [])
        about = R.FINDING_ABOUT % (fid, f.get("title") or f.get("issue") or "", f.get("file") or "the PR as a whole",
                                   f.get("line") or "-", f.get("issue") or "", f.get("fix") or "", f.get("body") or "",
                                   said) + "\n\n" + (R.FINDING_RULE if edits else "")
    saved = R.saved_note(rec)
    about = (about + "\n\n" if about else "") + (saved + "\n\n" if saved else "") + \
        "Lee's message is the text above this note."
    if edits:
        return R.ASK % (R._review_now(rec, p), about)
    return R.ASK_SESSION % (R.ref(rec["repo"], rec["number"]), about)


def _open(rid, root, rec, p, chosen, review):
    """Make sure the session this message goes to is running, and is this review's chat. Returns (id, edits): whether
    its replies may change the review (only the review's own session, or the one made for it)."""
    own = own_session(p)
    try:
        if not chosen:
            cwd = (p.get("run") or {}).get("cwd")
            where = cwd if cwd and os.path.isdir(cwd) else R.local_checkout(rec["repo"]) or root
            return CS.create(rid, where, "Review chat: %s" % (rec.get("title") or R.ref(rec["repo"], rec["number"])),
                             review=review), True
        if chosen in (own, rec.get("chat_session")):
            CS.resume(rid, (p.get("run") or {}).get("cwd") or root, chosen, review=review)
            return chosen, True
        if _is_studio(chosen):
            CS.resume(rid, root, chosen, review=review)
            return chosen, False
        fork = (rec.get("session_forks") or {}).get(chosen)
        if fork and CS.transcript(fork, root):
            CS.resume(rid, root, fork, review=review)
            return fork, False
        return CS.fork_open(rid, root, chosen, review=review), False
    except CS.Invalid as e:
        raise R.ReviewError(str(e)) from None


def say(rid, root, repo, number, n, text, fid="", qid="", sid="", attachments=None):
    """Send a message into the review's chat: to the session you chose (default: the review's own), about the whole
    review or one finding. Returns {"session": where it runs, "to": what you chose, "status": sent or queued}; the
    reply streams into the session and is applied to the review when the turn ends."""
    try:
        text = CS._check(text, attachments)
    except CS.Invalid as e:
        raise R.ReviewError(str(e)) from None
    rec = R.need(repo, number)
    p = _pass(rec, n)
    if fid:
        R.find(rec, fid)
    chosen = sid or own_session(p) or rec.get("chat_session") or ""
    review = {"pr": R.ref(repo, number), "n": p["n"]}
    live_id, edits = _open(rid, root, rec, p, chosen, review)
    rec = R.need(repo, number)  # starting a session took a while: read the record again
    if not chosen:
        rec["chat_session"] = live_id
    elif live_id != chosen and not _is_studio(chosen):
        rec.setdefault("session_forks", {})[chosen] = live_id
    R.store(rec)
    context = _context(rec, p, fid, edits)
    files = "".join("\n[%s: %s]" % ("image" if (a or {}).get("type", "").startswith("image/") else "file",
                                    (a or {}).get("path")) for a in attachments or [])
    turn = {"pr": review["pr"], "n": p["n"], "fid": fid, "qid": qid, "q": (text + files).strip(), "edits": edits}
    tag = '%s pass="%d"%s%s>' % (TAG, p["n"], ' finding="%s"' % fid if fid else "",
                                 ' question="%s"' % qid if qid else "")
    try:
        status = CS.live(live_id).say("%s\n\n%s\n%s\n</lfg-review>" % (text, tag, context), attachments, turn)
    except CS.Invalid as e:
        raise R.ReviewError(str(e)) from None
    return {"session": live_id, "to": chosen or live_id, "status": status}


def answer(rid, root, repo, number, n, qid, text):
    """Your answer to a question the review couldn't settle: kept on the question, then sent to the review's own
    session, which can change the review to match."""
    qq = R.record_answer(repo, number, n, qid, text)
    return say(rid, root, repo, number, n, "You asked: %s\nMy answer: %s" % (qq["ask"], qq["answer"]), qid=qid)


def finish(live, turn, mid, said):
    """A turn about a review ended with `said` as its last reply (message id `mid`): apply the changes it settled,
    keep the exchange on the finding, question or review it was about, and keep the chips by message id."""
    repo, number = R.parse_pr(turn["pr"])
    shown, out = R._reply_text(said)
    changed = R.apply_changes(repo, number, turn["n"], out) if out and turn.get("edits") else []
    rec = R.need(repo, number)  # read again: the changes and the page may have saved meanwhile
    p = _pass(rec, turn["n"])
    entry = {"q": turn["q"], "a": shown, "at": C.now_iso(), "changed": changed, "session": live.title,
             "session_id": live.sid, "studio": True}  # "studio": said in this chat (the page shows older ones apart)
    if turn.get("fid"):
        R.find(rec, turn["fid"]).setdefault("chat", []).append(entry)
    else:
        p.setdefault("chat", []).append(dict(entry, **({"qid": turn["qid"]} if turn.get("qid") else {})))
    qq = next((x for x in p.get("questions") or [] if x["id"] == turn.get("qid")), None) if turn.get("qid") else None
    if qq:
        qq.update(reply=shown, changed=changed)
    R.store(rec)
    if mid and changed:
        CS.add_chips(live.sid, mid, changed)

