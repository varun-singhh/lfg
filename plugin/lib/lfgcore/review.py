"""PR reviews, of other people's work or your own open PRs: the review record, triage, posting and re-review state.
Stdlib only.

One record per PR in ~/.lfg/reviews/<owner>__<repo>/<number>.json. Each review of the PR is a pass that remembers the
commit it read, so a re-review can tell what changed since. Findings keep the GitHub comment id they were posted as,
so a re-review can tell which ones were fixed, answered or ignored.

Posting (`lfg review post`) writes to GitHub, so the guard keeps it for the user (terminal or dashboard)."""
import glob
import hashlib
import json
import os
import re
import time

from . import common as C
from . import sessions as SS

SEVERITIES = ("blocker", "major", "minor", "nitpick", "note")
ORIGINS = ("introduced", "exposed", "pre-existing")      # who the bug belongs to
SINCE = ("first", "new", "missed")                      # re-review: in new commits, or missed by an earlier pass
ABOUT = ("code", "ticket", "description")               # what a finding is about: the diff, the ticket, the PR body
DELIVERS = ("all", "most", "part", "unclear")           # how much of the ticket's ask the PR does
BUILTIN = "builtin"                                     # review.sources: LFG's own method, next to your own sources
PRIOR_STATES = ("fixed", "replied", "ignored", "resolved-unchanged", "open", "withdrawn")
STATUSES = ("pending", "keep", "drop")
EVENTS = {"approve": "APPROVE", "request-changes": "REQUEST_CHANGES", "comment": "COMMENT"}
PR_URL = re.compile(r"^https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
PR_REF = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)$")
MAX_BODY = 20_000


class ReviewError(Exception):
    pass


# ---------------------------------------------------------------- PR identity and GitHub reads

def parse_pr(ref, cwd=None):
    """`owner/repo#12`, a PR URL, or a bare number (repo from the checkout in cwd) -> ("owner/repo", 12)."""
    ref = (ref or "").strip()
    m = PR_URL.match(ref) or PR_REF.match(ref)
    if m:
        return m.group(1), int(m.group(2))
    if ref.lstrip("#").isdigit():
        cp = C.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=cwd, timeout=30)
        if cp.returncode or not cp.stdout.strip():
            raise ReviewError("can't tell which repo PR %s is in: run this inside its checkout or use owner/repo#%s"
                              % (ref, ref.lstrip("#")))
        return cp.stdout.strip(), int(ref.lstrip("#"))
    raise ReviewError("not a PR: %r (use a number, owner/repo#12 or a PR URL)" % ref)


def gh_json(args, stdin=None, timeout=60):
    cp = _gh(args, stdin, timeout)
    if cp.returncode:
        raise ReviewError("gh %s: %s" % (" ".join(args[:3]), (cp.stderr or cp.stdout).strip()[-500:]))
    return json.loads(cp.stdout or "null")


def _gh(args, stdin=None, timeout=60):
    import subprocess
    try:
        return subprocess.run(["gh"] + args, input=stdin, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise ReviewError("gh is not installed") from None
    except subprocess.TimeoutExpired:
        raise ReviewError("gh %s timed out" % " ".join(args[:3])) from None


def pr_meta(repo, number):
    j = gh_json(["pr", "view", str(number), "-R", repo, "--json",
                 "number,title,url,author,headRefOid,baseRefName,headRefName,state,isDraft,body"])
    return {"title": j["title"], "url": j["url"], "author": (j.get("author") or {}).get("login", ""),
            "body": j.get("body") or "",
            "head_sha": j["headRefOid"], "base": j["baseRefName"], "branch": j["headRefName"], "state": j["state"]}


_STATUS, _REFRESHING = {}, set()


def gh_status(repo, number, max_age=300, wait=True):
    """Where the PR stands on GitHub: open/merged, approved or changes asked for, each reviewer's latest verdict,
    who still has to review, and checks. An answer older than max_age is still returned at once and asked again in
    the background, so a page waits on GitHub only for a PR it has never asked about, or on Refresh (max_age=0).
    wait=False never waits: a PR never asked about is asked in the background and {"pending": True} comes back."""
    import threading
    key = (repo, number)
    if not _STATUS:  # a restarted dashboard starts from what the last one knew
        _STATUS.update({tuple(k.rsplit("#", 1)[:1]) + (int(k.rsplit("#", 1)[1]),): tuple(v)
                        for k, v in (C.read_json(_status_path(), {}) or {}).items() if "#" in k})
    hit = _STATUS.get(key)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    if (hit and max_age > 0) or not wait:
        if key not in _REFRESHING:
            _REFRESHING.add(key)
            threading.Thread(target=_refresh_status, args=key, daemon=True).start()
        return hit[1] if hit else {"available": False, "pending": True}
    return _ask_status(repo, number)


def _status_path():
    return C.lfg_path("reviews", "gh-status.json")


def _refresh_status(repo, number):
    try:
        _ask_status(repo, number)
    finally:
        _REFRESHING.discard((repo, number))


def _ask_status(repo, number):
    key = (repo, number)
    try:
        j = gh_json(["pr", "view", str(number), "-R", repo, "--json",
                     "state,isDraft,reviewDecision,mergeable,reviews,reviewRequests,statusCheckRollup,headRefOid,"
                     "headRefName,additions,deletions,changedFiles"])
    except ReviewError as e:
        return {"available": False, "why": str(e)}
    latest = {}
    for r in j.get("reviews") or []:
        who = (r.get("author") or {}).get("login") or "?"
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED") or who not in latest:
            latest[who] = {"who": who, "state": r.get("state"), "at": r.get("submittedAt")}
    checks = {}
    for c in j.get("statusCheckRollup") or []:
        k = (c.get("conclusion") or c.get("state") or "PENDING").upper()
        checks[k] = checks.get(k, 0) + 1
    out = {"available": True, "state": j.get("state"), "draft": j.get("isDraft"),
           "decision": j.get("reviewDecision") or "", "mergeable": j.get("mergeable"),
           "additions": j.get("additions") or 0, "deletions": j.get("deletions") or 0,
           "files": j.get("changedFiles") or 0,
           "reviewers": sorted(latest.values(), key=lambda r: r["at"] or ""),
           "waiting_on": [(r.get("login") or r.get("name") or "") for r in j.get("reviewRequests") or []],
           "checks": checks, "head_sha": j.get("headRefOid"), "branch": j.get("headRefName") or "", "me": me()}
    _STATUS[key] = (time.time(), out)
    try:
        C.write_json(_status_path(), {"%s#%d" % k: list(v) for k, v in list(_STATUS.items())})
    except OSError:
        pass
    return out


REWRITE = ("Rewrite this code review comment as asked. Keep it accurate to the finding, in the same voice. Reply "
           "with only the new comment, no preamble.\n\nWhat was asked: %s\n\nThe finding (for context, not "
           "posted):\n%s\n\nThe comment as it is now:\n%s%s")
STYLE_FILE = re.compile(r"(comment|voice|style|tone)[\w-]*\.md$", re.I)


def comment_style(rec, f):
    """How comments should read, from the method the finding's review used: its style files (comment-style.md and
    the like) under ~/.claude/skills, else the saved method's. "" for LFG's built-in method."""
    p = next((x for x in rec["passes"] if f in x["findings"]), {})
    root = os.path.join(C.HOME, ".claude", "skills")
    files = [os.path.join(root, x) for x in ((p.get("run") or {}).get("used") or {}).get("method_files") or []]
    files = [x for x in files if STYLE_FILE.search(x)] or [x for x in sources()["files"] if STYLE_FILE.search(x)]
    return "\n\n".join(C.read_text(x)[:8000] for x in files[:2] if os.path.isfile(x))


def rewrite(repo, number, fid, instruction):
    """Ask Claude, with no tools, to change one comment ("shorter", "less blunt", "add the line number"). Returns the
    new text without saving it: you look at it, then save it like any edit."""
    import subprocess
    if not str(instruction or "").strip():
        raise ReviewError("say how to change it, e.g. \"make it two sentences\"")
    if not C.which("claude"):
        raise ReviewError("Claude Code (`claude`) is not on PATH")
    rec = need(repo, number)
    f = find(rec, fid)
    style = comment_style(rec, f)
    ctx = "\n".join(x for x in ("Title: " + (f.get("title") or ""), "Issue: " + (f.get("issue") or ""),
                                 "Fix: " + (f.get("fix") or ""), "Where: %s:%s" % (f.get("file") or "-", f.get("line")
                                                                                   or "-")) if x)
    cp = subprocess.run(["claude", "-p", "--output-format", "json", "--permission-mode", "dontAsk"] + C.CLAUDE_BARE
                        + _model() + _direct(),
                        input=REWRITE % (_text(instruction, "instruction", 2000), ctx, f["body"],
                                         "\n\nWrite it the way this style guide says:\n" + style if style else ""),
                        capture_output=True, text=True, timeout=300)
    try:
        text = (json.loads(cp.stdout).get("result") or "").strip()
    except ValueError:
        text = ""
    if not text:
        raise ReviewError("Claude didn't return a comment: %s" % (cp.stderr or cp.stdout or "")[-300:].strip())
    return {"id": fid, "body": re.sub(r"^```\w*\n|\n```$", "", text)}


_ME = {}


def me():
    """Your GitHub login, asked once per dashboard (it was asked once for every PR on the page)."""
    if not _ME.get("login"):
        cp = _gh(["api", "user", "-q", ".login"], timeout=30)
        _ME["login"] = cp.stdout.strip() if cp.returncode == 0 else ""
    return _ME["login"]


def diff_lines(repo, base, head):
    """{path: set(right-side line numbers GitHub accepts a comment on)} for the PR diff as of `head`."""
    j = gh_json(["api", "repos/%s/compare/%s...%s" % (repo, base, head)], timeout=120)
    out = {}
    for f in j.get("files") or []:
        out[f["filename"]] = commentable(f.get("patch") or "")
    return out


def commentable(patch):
    lines, new = set(), 0
    for ln in patch.splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
        if m:
            new = int(m.group(1))
            continue
        if ln.startswith("-") or ln.startswith("\\"):
            continue
        lines.add(new)
        new += 1
    return lines


# ---------------------------------------------------------------- the record

def reviews_dir():
    return C.lfg_path("reviews")


def record_path(repo, number):
    return os.path.join(reviews_dir(), repo.replace("/", "__"), "%d.json" % number)


def load(repo, number):
    rec = C.read_json(record_path(repo, number))
    return rescore(rec) if rec else rec  # records saved under an older score rule read the same as new ones


POINTS = {"blocker": 25, "major": 12, "minor": 4, "nitpick": 1, "note": 0}  # the rubric's cost of each severity


def checked_fixed(f):
    """Fixed: "Is it fixed?" said so, or LFG's own fix pass committed a fix for it."""
    return (f.get("check") or {}).get("state") == "fixed" or bool((f.get("fixed") or {}).get("commit"))


def undecided(p):
    """Findings of a pass still waiting for keep or drop (Fix or Pass). One that "Is it fixed?" found fixed is
    settled already."""
    return [f["id"] for f in p["findings"] if f["status"] == "pending" and not checked_fixed(f)]


def rescore(rec):
    """Each review's score as things stand: 100 minus the points of what it counted that is still open, its findings
    and earlier ones it still listed as open, plus its unanswered questions that cost points. The number the review
    picked itself is never used (`score_given` keeps it), so nothing comes off without a finding or question behind
    it. Nitpicks cost once per kind. `credits` names what came back since it ran (passed, fixed or answered) and
    `score_at_review` the score before that."""
    by_id = {f["id"]: f for p in rec.get("passes") or [] for f in p.get("findings") or []}
    settled = lambda f: f["status"] == "drop" or checked_fixed(f)  # noqa: E731
    for p in rec.get("passes") or []:
        for k in ("cleared", "score_said"):  # from when the review's own number counted
            p.pop(k, None)
        counted = list(p.get("findings") or []) + [
            by_id[x["id"]] for x in p.get("prior") or []
            if x.get("state") not in ("fixed", "withdrawn") and x.get("id") in by_id]
        costed, nits = [], {}
        for f in counted:
            if f["severity"] == "nitpick":
                nits.setdefault(f.get("title") or f["id"], []).append(f)
            elif POINTS.get(f["severity"]):
                costed.append(f)
        costed += [next((f for f in fs if not settled(f)), fs[0]) for fs in nits.values()]
        costed.sort(key=lambda f: [int(x) for x in f["id"].split(".") if x.isdigit()])
        still = [f for f in costed if not settled(f)]
        credits = [{"id": f["id"], "points": POINTS[f["severity"]], "why": "passed" if f["status"] == "drop" else
                    "fixed"} for f in costed if settled(f)]
        asks = [q for q in p.get("questions") or [] if q.get("costs")]
        credits += [{"id": q["id"], "points": q["costs"], "why": "answered"} for q in asks if q.get("answer")]
        own = {f["id"] for f in p.get("findings") or []}
        p["open_points"] = {  # what the score is made of, so the page can add it up
            "findings": sum(POINTS[f["severity"]] for f in still if f["id"] in own),
            "earlier": sum(POINTS[f["severity"]] for f in still if f["id"] not in own),
            "questions": sum(q["costs"] for q in asks if not q.get("answer"))}
        p.pop("earlier_points", None)
        p.setdefault("score_given", p.get("score_at_review", p.get("score")))  # the review's own number, unused
        p["score"] = max(0, 100 - sum(p["open_points"].values()))
        if credits:
            p["credits"] = credits
            p["score_at_review"] = max(0, p["score"] - sum(c["points"] for c in credits))
        else:
            p.pop("credits", None)
            p.pop("score_at_review", None)
        # what it held against the PR got fixed or passed: its verdict follows what is still open (a major left: not
        # mergeable; only minors: almost; nothing: mergeable), never worse than it said. An open question that costs
        # points keeps the verdict as it was.
        now = "not" if any(f["severity"] in ("blocker", "major") for f in still) else \
            "almost" if any(f["severity"] == "minor" for f in still) else "mergeable"
        rank = {"mergeable": 0, "almost": 1, "not": 2}
        if credits and p.get("verdict") in ("almost", "not") and rank[now] < rank[p["verdict"]] \
                and not any(not q.get("answer") for q in asks):
            p["verdict_now"] = now
        else:
            p.pop("verdict_now", None)
    return rec


def store(rec):
    rescore(rec)
    rec["updated"] = C.now_iso()
    C.write_json(record_path(rec["repo"], rec["number"]), rec)


def need(repo, number):
    rec = load(repo, number)
    if not rec or not rec.get("passes"):
        raise ReviewError("no review saved for %s#%d yet" % (repo, number))
    return rec


def all_records():
    out = []
    for p in sorted(glob.glob(os.path.join(reviews_dir(), "*", "*.json"))):
        r = C.read_json(p)
        if r and r.get("passes"):
            out.append(rescore(r))
    return sorted(out, key=lambda r: r.get("updated", ""), reverse=True)


def findings(rec):
    return [f for p in rec["passes"] for f in p["findings"]]


def find(rec, fid):
    for f in findings(rec):
        if f["id"] == fid:
            return f
    raise ReviewError("no finding %s on %s#%d" % (fid, rec["repo"], rec["number"]))


def _text(v, name, limit=MAX_BODY):
    v = "" if v is None else str(v)
    if len(v) > limit:
        raise ReviewError("%s is longer than %d characters" % (name, limit))
    return v


def _clean_finding(f, i):
    if not isinstance(f, dict):
        raise ReviewError("finding %d is not an object" % i)
    sev = str(f.get("severity", "")).lower()
    if sev not in SEVERITIES:
        raise ReviewError("finding %d: severity must be one of %s" % (i, ", ".join(SEVERITIES)))
    body = _text(f.get("body"), "finding %d body" % i)
    if not body.strip():
        raise ReviewError("finding %d has no body (the comment the author will read)" % i)
    line = f.get("line")
    if line is not None and (not isinstance(line, int) or line < 1):
        raise ReviewError("finding %d: line must be a positive integer or null" % i)
    origin = f.get("origin") or "introduced"
    since = f.get("since") or "first"
    about = f.get("about") or "code"
    if origin not in ORIGINS or since not in SINCE or about not in ABOUT:
        raise ReviewError("finding %d: origin is one of %s; since is one of %s; about is one of %s"
                          % (i, ", ".join(ORIGINS), ", ".join(SINCE), ", ".join(ABOUT)))
    return {"title": _text(f.get("title"), "title", 200), "severity": sev, "file": f.get("file") or None,
            "line": line, "issue": _text(f.get("issue"), "issue", 1000), "fix": _text(f.get("fix"), "fix", 1000),
            "detail": _text(f.get("detail"), "detail"), "body": body, "origin": origin, "since": since, "about": about,
            "echoes": _echoes(f.get("echoes"), i), "status": "pending", "comment_id": None, "comment_url": None,
            **_raised(f, i)}


WORTH = ("fix", "maybe", "skip")


def _raised(f, i):
    """Your own PR: a finding that is someone else's comment (CodeRabbit, Sonar, a teammate), with Claude's read on
    whether it's worth fixing and the reply to send if you pass on it."""
    rb = f.get("raised_by")
    if not rb:
        return {}
    if not isinstance(rb, dict) or not str(rb.get("who") or "").strip():
        raise ReviewError("finding %d: raised_by is {who, url, comment_id, kind}" % i)
    worth = f.get("worth") or "maybe"
    if worth not in WORTH:
        raise ReviewError("finding %d: worth is one of %s" % (i, ", ".join(WORTH)))
    cid = rb.get("comment_id")
    return {"raised_by": {"who": _text(rb.get("who"), "raised_by.who", 100), "url": _text(rb.get("url"), "url", 500),
                          "comment_id": cid if isinstance(cid, int) else None,
                          "kind": rb.get("kind") if rb.get("kind") in ("inline", "review", "comment") else "comment",
                          "bot": bool(rb.get("bot"))},
            "worth": worth, "reply": _text(f.get("reply"), "reply", 4000), "replied": None}


def _echoes(raw, i):
    """Other reviewers (people, CodeRabbit, other bots) who already raised this: [{who, url, said, bot}]."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ReviewError("finding %d: echoes is a list of {who, url, said}" % i)
    out = []
    for e in raw[:10]:
        if not isinstance(e, dict) or not str(e.get("who") or "").strip():
            raise ReviewError("finding %d: each echo needs who (their GitHub login)" % i)
        url = str(e.get("url") or "")
        out.append({"who": str(e["who"]).strip().lstrip("@")[:80],
                    "url": url if url.startswith("https://github.com/") else "",
                    "said": _text(e.get("said"), "echo", 600), "bot": bool(e.get("bot"))})
    return out


def others(repo, number):
    """What other reviewers already said on a PR: inline comments (with file and line), review summaries and
    conversation comments, from people and bots (CodeRabbit, Sonar, other agents). LFG's own posted comments are
    left out. Read-only."""
    _not_in_fresh_eyes("other reviewers' comments")
    rec = load(repo, number) or {}
    mine = {f.get("comment_id") for f in findings(rec) if f.get("comment_id")} if rec.get("passes") else set()
    out = []

    def add(c, kind, file=None, line=None):
        u = c.get("user") or {}
        body = (c.get("body") or "").strip()
        if not body or c.get("id") in mine:
            return
        out.append({"who": u.get("login") or "", "bot": u.get("type") == "Bot" or (u.get("login") or "").endswith(
            "[bot]"), "kind": kind, "file": file, "line": line, "said": body[:1500], "url": c.get("html_url") or "",
            "at": c.get("submitted_at") or c.get("created_at") or "", "comment_id": c.get("id"),
            "reply_to": c.get("in_reply_to_id")})
    for c in gh_json(["api", "--paginate", "repos/%s/pulls/%d/comments" % (repo, number)], timeout=120) or []:
        add(c, "inline", c.get("path"), c.get("line") or c.get("original_line"))
    for c in gh_json(["api", "--paginate", "repos/%s/pulls/%d/reviews" % (repo, number)], timeout=120) or []:
        add(c, "review")
    for c in gh_json(["api", "--paginate", "repos/%s/issues/%d/comments" % (repo, number)], timeout=120) or []:
        add(c, "comment")
    return out


NEAR = 3  # lines: another reviewer's inline comment this close to a finding is about the same spot


def mark_repeats(repo, number):
    """After a Fresh eyes review: tag each new finding that an earlier LFG review already raised (same file within
    NEAR lines, or the same title), with what you decided about it then. The review never saw them; posting says so."""
    rec = load(repo, number)
    if not rec or len(rec.get("passes") or []) < 2:
        return 0
    *old, p = rec["passes"]
    n = 0
    for f in p["findings"]:
        hits = [{"pass": q["n"], "id": g["id"], "status": g["status"], "posted": bool(g.get("comment_url")),
                 "url": g.get("comment_url") or ""}
                for q in old for g in q["findings"]
                if (f.get("file") and f["file"] == g.get("file") and f.get("line") and g.get("line")
                    and abs(int(f["line"]) - int(g["line"])) <= NEAR)
                or (f.get("title") and f["title"].strip().lower() == (g.get("title") or "").strip().lower())]
        if hits:
            f["repeats"] = hits
            n += 1
    if n:
        store(rec)
    return n


def already_said(f):
    """Who raised a finding before: other reviewers (echoes) and earlier LFG reviews (repeats), in words."""
    said = {"drop": ", you dropped it", "keep": ", you kept it"}
    return ["%s%s" % ("" if e.get("bot") else "@", e["who"]) for e in f.get("echoes") or []] + [
        "LFG review %d (%s%s%s)" % (r["pass"], r["id"], said.get(r["status"], ""), ", posted" if r["posted"] else "")
        for r in f.get("repeats") or []]


def mark_echoes(repo, number, said=None):
    """Tag the latest review's findings with other reviewers' inline comments on the same file within NEAR lines,
    on top of the ones the review itself named. Never fails a review: if GitHub can't be asked, nothing changes."""
    rec = load(repo, number)
    if not rec or not rec.get("passes"):
        return 0
    try:
        said = others(repo, number) if said is None else said
    except ReviewError:
        return 0
    n = 0
    for f in rec["passes"][-1]["findings"]:
        have = {e["url"] for e in f.get("echoes") or [] if e.get("url")} | {e["who"] for e in f.get("echoes") or []}
        for c in said:
            if c["kind"] != "inline" or not f.get("file") or c["file"] != f["file"] or not f.get("line") \
                    or not c.get("line") or abs(int(c["line"]) - int(f["line"])) > NEAR:
                continue
            if c["url"] in have or c["who"] in have:
                continue
            f.setdefault("echoes", []).append({"who": c["who"], "url": c["url"], "said": c["said"][:600],
                                               "bot": c["bot"], "near": True})
            have |= {c["url"], c["who"]}
            n += 1
    if n:
        store(rec)
    return n


def save(repo, number, data, ticket=None, meta=None):
    """Add a pass from the agent's JSON: {summary, score, approach_notes, findings: [...], prior: [...]}.
    `meta` is pr_meta() (passed in tests); `head_sha` in data wins over the PR's current head."""
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise ReviewError("expected a JSON object with a findings list")
    meta = meta or pr_meta(repo, number)
    rec = load(repo, number) or {"repo": repo, "number": number, "created": C.now_iso(), "passes": []}
    rec.update({k: meta[k] for k in ("title", "url", "author", "base", "branch", "state")})
    if ticket:
        rec["ticket"] = ticket
    n = len(rec["passes"]) + 1
    found = [_clean_finding(f, i) for i, f in enumerate(data["findings"], 1)]
    for i, f in enumerate(found, 1):
        f["id"] = "%d.%d" % (n, i)
    known = {f["id"] for f in findings(rec)}
    prior = []
    for p in data.get("prior") or []:
        if p.get("id") not in known or p.get("state") not in PRIOR_STATES:
            raise ReviewError("prior entries need an earlier finding id (%s) and a state in %s"
                              % (", ".join(sorted(known)) or "none yet", ", ".join(PRIOR_STATES)))
        prior.append({"id": p["id"], "state": p["state"], "note": _text(p.get("note"), "prior note", 2000)})
    score = data.get("score")
    if score is not None and not (isinstance(score, int) and 0 <= score <= 100):
        raise ReviewError("score must be an integer 0-100 or null")
    verdict = data.get("verdict") or None
    if verdict not in (None,) + VERDICTS:
        raise ReviewError("verdict must be one of %s, or left out" % ", ".join(VERDICTS))
    intent = _intent(data.get("intent"))
    rec["passes"].append({
        "n": n, "kind": "first" if n == 1 else "re-review", "ts": C.now_iso(), "reviewer": data.get("reviewer") or "",
        "head_sha": data.get("head_sha") or meta["head_sha"], "base": meta["base"],
        "summary": _text(data.get("summary"), "summary"), "score_given": score, "verdict": verdict,
        "verdict_why": _text(data.get("verdict_why"), "verdict_why", 400) if verdict else "",
        "approach_notes": [_text(x, "approach note", 4000) for x in data.get("approach_notes") or []],
        "questions": [{"id": "q%d" % k, "ask": _text(q.get("ask"), "question", 1000), "why": _text(q.get("why"), "why",
                                                                                                    1000),
                       "answer": None, "costs": q["costs"] if q.get("costs") in (4, 12, 25) else 0,
                       **_where(q)}
                      for k, q in enumerate([q for q in data.get("questions") or []
                                                               if isinstance(q, dict) and q.get("ask")][:10], 1)],
        "findings": found, "prior": prior, "posted": None, **({"intent": intent} if intent else {})})
    if intent and intent["ticket"] and not rec.get("ticket"):
        rec["ticket"] = intent["ticket"]
    store(rec)
    C.audit("review_save", {"pr": "%s#%d" % (repo, number), "pass": n, "findings": len(found)})
    return rec


def _intent(raw):
    """What the PR was meant to do, as the review read it: the Linear ticket (or none found), whether it and the PR's
    description could be read, how much of the ticket's ask the diff delivers, and one line saying so."""
    if raw in (None, {}):
        return None
    if not isinstance(raw, dict):
        raise ReviewError("intent is {ticket, ticket_title, read_ticket, read_description, delivers, note}")
    delivers = raw.get("delivers") or "unclear"
    if delivers not in DELIVERS:
        raise ReviewError("intent.delivers is one of %s" % ", ".join(DELIVERS))
    ticket = str(raw.get("ticket") or "").strip().upper()
    if ticket and not re.match(r"^[A-Z][A-Z0-9]{1,9}-\d{1,6}$", ticket):
        raise ReviewError("intent.ticket is a Linear id like ATO-4223, or empty when there is none")
    return {"ticket": ticket, "ticket_title": _text(raw.get("ticket_title"), "intent.ticket_title", 300),
            "read_ticket": bool(raw.get("read_ticket")), "read_description": bool(raw.get("read_description")),
            "delivers": delivers, "note": _text(raw.get("note"), "intent.note", 1000)}


def discard(repo, number, n):
    """Throw away one review pass that was never posted. Only the latest can go, so later passes never point at a
    missing one; discarding the only pass removes the record."""
    rec = need(repo, number)
    last = rec["passes"][-1]
    if int(n) != last["n"]:
        raise ReviewError("only the latest review (%d) can be discarded" % last["n"])
    if last.get("posted"):
        raise ReviewError("review %d is already on GitHub; it can't be discarded here" % last["n"])
    rec["passes"].pop()
    if rec["passes"]:
        store(rec)
    else:
        os.remove(record_path(repo, number))
    C.audit("review_discard", {"pr": "%s#%d" % (repo, number), "pass": int(n)})
    return {"discarded": int(n), "left": len(rec["passes"])}


def mark(repo, number, ids, status=None, body=None):
    if status is not None and status not in STATUSES:
        raise ReviewError("status must be one of %s" % ", ".join(STATUSES))
    rec = need(repo, number)
    for fid in ids:
        f = find(rec, fid)
        if f.get("comment_id") and (status == "drop" or body is not None):
            raise ReviewError("%s is already posted on GitHub; change it there" % fid)
        if status:
            f["status"] = status
            f.pop("dropped_by", None)  # your own decision now
        if body is not None:
            if not body.strip():
                raise ReviewError("the comment can't be empty")
            f["body"] = _text(body, "comment")
    store(rec)
    return rec


# ---------------------------------------------------------------- posting (user-only: the guard blocks agents)

def plan_post(rec, event, body="", lines=None):
    """What `post` would send: kept, unposted findings of the latest pass. Findings whose line GitHub can't take a
    comment on (outside the diff, or no line) go into the review body with their file:line instead."""
    if event not in EVENTS:
        raise ReviewError("event must be one of %s" % ", ".join(EVENTS))
    p = rec["passes"][-1]
    if p.get("posted"):
        raise ReviewError("pass %d was already posted (%s); run a re-review first" % (p["n"], p["posted"]["url"]))
    pending = undecided(p)
    if pending:
        raise ReviewError("decide keep or drop first: %s" % ", ".join(pending))
    kept = [f for f in p["findings"] if f["status"] == "keep" and not f["comment_id"]]
    if lines is None:
        lines = diff_lines(rec["repo"], rec["base"], p["head_sha"]) if any(f["file"] for f in kept) else {}
    inline, general = [], []
    for f in kept:
        if f["file"] and f["line"] and f["line"] in lines.get(f["file"], ()):
            inline.append({"id": f["id"], "path": f["file"], "line": f["line"], "side": "RIGHT", "body": f["body"]})
        else:
            general.append(f)
    parts = [body.strip()] if body.strip() else []
    for f in general:
        where = "`%s%s`: " % (f["file"], ":%d" % f["line"] if f["line"] else "") if f["file"] else ""
        parts.append(where + f["body"])
    if event == "request-changes" and not inline and not parts:
        raise ReviewError("request changes needs at least one kept finding or a body")
    return {"pass": p["n"], "event": EVENTS[event], "commit_id": p["head_sha"], "body": "\n\n".join(parts),
            "comments": inline, "in_body": [f["id"] for f in general],
            "already": [{"id": f["id"], "who": already_said(f)} for f in kept if already_said(f)]}


def post(repo, number, event, body="", dry_run=False):
    rec = need(repo, number)
    if event != "comment" and rec.get("author") and rec["author"] == me():
        raise ReviewError("this is your own PR: GitHub only takes a comment on it, not approve or request changes")
    plan = plan_post(rec, event, body)
    if dry_run:
        return dict(plan, dry_run=True)
    payload = {"commit_id": plan["commit_id"], "event": plan["event"], "body": plan["body"],
               "comments": [{k: c[k] for k in ("path", "line", "side", "body")} for c in plan["comments"]]}
    out = gh_json(["api", "-X", "POST", "repos/%s/pulls/%d/reviews" % (repo, number), "--input", "-"],
                  stdin=json.dumps(payload), timeout=120)
    posted = gh_json(["api", "--paginate", "repos/%s/pulls/%d/reviews/%d/comments" % (repo, number, out["id"])])
    p = rec["passes"][plan["pass"] - 1]
    for c, g in match_comments(plan["comments"], posted or []):
        f = find(rec, c["id"])
        f["comment_id"], f["comment_url"] = (g["id"], g["html_url"]) if g else (None, out.get("html_url"))
    for fid in plan["in_body"]:
        find(rec, fid)["comment_url"] = out.get("html_url")
    p["posted"] = {"review_id": out["id"], "event": plan["event"], "url": out.get("html_url"), "ts": C.now_iso()}
    store(rec)
    C.audit("review_post", {"pr": "%s#%d" % (repo, number), "event": plan["event"], "comments": len(plan["comments"])})
    return dict(plan, posted=p["posted"])


def match_comments(sent, posted):
    """Pair each comment we sent with the one GitHub created: same file and text, else same file and line (GitHub
    may normalise whitespace). Unmatched ones pair with None."""
    left, out = list(posted), []
    for c in sent:
        g = next((x for x in left if x["path"] == c["path"] and x["body"].strip() == c["body"].strip()), None) \
            or next((x for x in left if x["path"] == c["path"] and x.get("line") == c["line"]), None)
        if g:
            left.remove(g)
        out.append((c, g))
    return out


# ---------------------------------------------------------------- re-review inputs

THREADS_Q = """query($o:String!,$r:String!,$n:Int!,$c:String){repository(owner:$o,name:$r){pullRequest(number:$n){
reviewThreads(first:100,after:$c){pageInfo{hasNextPage endCursor}nodes{isResolved isOutdated path line
comments(first:50){nodes{databaseId author{login} body createdAt}}}}}}}"""


def _threads(repo, number):
    o, r = repo.split("/", 1)
    out, cursor = [], None
    while True:
        args = ["api", "graphql", "-f", "query=" + THREADS_Q, "-F", "o=" + o, "-F", "r=" + r, "-F", "n=%d" % number]
        if cursor:
            args += ["-F", "c=" + cursor]
        page = gh_json(args)["data"]["repository"]["pullRequest"]["reviewThreads"]
        out += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        cursor = page["pageInfo"]["endCursor"]


def threads(repo, number):
    """For each posted finding: resolved, outdated, the author's replies, and whether its file changed since the
    pass that posted it. Plus the commits since the last pass. Read-only; the agent judges what it means."""
    _not_in_fresh_eyes("earlier reviews")
    rec = need(repo, number)
    meta = pr_meta(repo, number)
    last = rec["passes"][-1]
    by_comment = {}
    for t in _threads(repo, number):
        nodes = t["comments"]["nodes"]
        if nodes:
            by_comment[nodes[0]["databaseId"]] = t
    changed = {}
    for p in rec["passes"]:
        if p["head_sha"] != meta["head_sha"]:
            try:
                j = gh_json(["api", "repos/%s/compare/%s...%s" % (repo, p["head_sha"], meta["head_sha"])],
                            timeout=120)
                changed[p["n"]] = {f["filename"] for f in j.get("files") or []}
            except ReviewError:
                changed[p["n"]] = None      # force-pushed away: the old commit is gone
    rows, unposted, settled = [], [], []
    last_state = {x["id"]: x["state"] for p in rec["passes"] for x in p.get("prior") or []}  # later passes win
    for p in rec["passes"]:
        for f in p["findings"]:
            files = changed.get(p["n"], set())
            where = {"id": f["id"], "title": f["title"], "file": f["file"], "line": f["line"]}
            if f["status"] == "drop":  # you decided against it: never raised again unless it got worse
                settled.append(where)
                continue
            if last_state.get(f["id"]) in ("fixed", "withdrawn"):  # kept or never decided: still followed up
                continue
            if not f.get("comment_url"):  # kept but never posted (your own PR): check it like a posted one
                unposted.append(dict(where, fixed_in=(f.get("fixed") or {}).get("commit") or None,
                                     file_changed=None if files is None else (
                                         f["file"] in files if f["file"] else None)))
                continue
            t = by_comment.get(f["comment_id"]) if f["comment_id"] else None
            replies = [{"by": (c.get("author") or {}).get("login", ""), "body": c["body"][:1500], "at": c["createdAt"]}
                       for c in (t["comments"]["nodes"][1:] if t else [])]
            rows.append({"id": f["id"], "title": f["title"], "file": f["file"], "line": f["line"],
                         "inline": bool(t), "resolved": bool(t and t["isResolved"]),
                         "outdated": bool(t and t["isOutdated"]), "replies": replies,
                         "file_changed": None if files is None else (f["file"] in files if f["file"] else None)})
    try:
        rec = question_replies(repo, number, max_age=0)
    except ReviewError:
        pass  # GitHub didn't answer: the replies read last time
    asked = [{"pass": p["n"], "id": q["id"], "ask": q["ask"], "asked": q["asked"].get("body"),
              "url": q["asked"].get("url"), "answer": q.get("answer"), "replies": q.get("replies") or []}
             for p, q in asked_questions(rec)]
    return {"repo": repo, "number": number, "head_sha": meta["head_sha"], "last_reviewed_sha": last["head_sha"],
            "new_commits": meta["head_sha"] != last["head_sha"], "posted": rows, "unposted": unposted,
            "settled": settled, "asked": asked}


# ---------------------------------------------------------------- what the review reads

PLUGIN_KEY = re.compile(r"^plugin:([^/\s]+)/([^/\s]+)$")  # plugin:<plugin>@<marketplace>/<skill>


def _plugin_skills():
    """Skills from the Claude Code plugins you installed (not LFG's own), {key: SKILL.md path}. A key names the plugin
    and skill, not the folder, so it keeps working when the plugin updates to a new version's folder."""
    d = C.read_json(os.path.join(C.HOME, ".claude", "plugins", "installed_plugins.json"), {}) or {}
    out = {}
    for name, installs in sorted(((d.get("plugins") if isinstance(d.get("plugins"), dict) else d) or {}).items()):
        if not isinstance(installs, list) or name.split("@")[0] == "lfg":
            continue
        # the install for every repo first, else the newest
        for i in sorted((x for x in installs if isinstance(x, dict) and x.get("installPath")),
                        key=lambda x: (x.get("scope") == "user", x.get("lastUpdated") or ""), reverse=True)[:1]:
            for f in sorted(glob.glob(os.path.join(i["installPath"], "skills", "*", "SKILL.md"))):
                out["plugin:%s/%s" % (name, os.path.basename(os.path.dirname(f)))] = f
    return out


def _expand(path):
    if path == BUILTIN:  # LFG's own method, listed with your sources so the two are read together
        path = default_dir()
    elif PLUGIN_KEY.match(str(path)):  # a plugin's skill: its folder in the version installed now
        f = _plugin_skills().get(path)
        if not f:
            return []
        path = os.path.dirname(f)
    path = os.path.expanduser(path)
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, "**", "*.md"), recursive=True))
    return [path] if os.path.isfile(path) else []


def default_dir():
    return os.path.join(C.PLUGIN_ROOT, "review")


def override_dir():
    return C.lfg_path("overrides", "review")


def sources():
    """Method and knowledge files, in the order to read them. `review.sources` in config.json replaces the shipped
    defaults (point it at your own skill and references, read in place); ~/.lfg/overrides/review/ always comes last
    and wins on conflict."""
    cfg = C.config().get("review") or {}
    run_own = os.environ.get("LFG_REVIEW_SOURCES")  # one run's method, picked on the PR page (JSON list)
    if run_own:
        try:
            cfg = dict(cfg, sources=[x for x in json.loads(run_own) if isinstance(x, str)])
        except ValueError:
            pass
    base = cfg.get("sources") or [default_dir()]
    out, missing = [], []
    for s in base:
        got = _expand(s)
        (out.extend(got) if got else missing.append(s))
    out += _expand(override_dir())
    return {"files": out, "missing": missing, "own": bool(cfg.get("sources"))}


def method():
    """What a review reads: the files and folders a review reads, in order, each with whether it is
    there and how many files it holds; then your overrides, read last."""
    cfg = C.config().get("review") or {}
    own = list(cfg.get("sources") or [])
    rows = [{"path": x, "found": len(_expand(x)), "missing": not _expand(x)} for x in own or [default_dir()]]
    return {"own": bool(own), "sources": rows, "builtin": default_dir(), "overrides": override_dir(),
            "override_files": _expand(override_dir())}


def set_sources(paths):
    """Your review method: the files and folders /lfg:review reads instead of LFG's built-in one, in order (later
    ones win). An empty list goes back to the built-in method. Each must exist."""
    from . import settings as ST
    if not isinstance(paths, list) or not all(isinstance(x, str) for x in paths):
        raise ReviewError("expected a list of paths")
    clean = []
    for x in (p.strip() for p in paths):
        if x and x not in clean:
            if not _expand(x):
                raise ReviewError("%s isn't a file or a folder with Markdown in it" % x)
            clean.append(x)
    path = C.lfg_path("config.json")
    raw = C.read_json(path, {}) or {}
    if not isinstance(raw, dict):
        raise ReviewError("%s is not valid JSON; fix it by hand first" % path)
    ST._backup(path, "config")
    rv = dict(raw.get("review") or {})
    if clean:
        rv["sources"] = clean
    else:
        rv.pop("sources", None)
    if rv:
        raw["review"] = rv
    else:
        raw.pop("review", None)
    C.write_json(path, raw)
    return method()


def agents_md(repo, head_sha, files):
    """AGENTS.md files as of the PR's head that govern the changed files: the root one plus any in a folder above a
    changed file."""
    tree = gh_json(["api", "repos/%s/git/trees/%s?recursive=1" % (repo, head_sha)], timeout=120)
    have = {t["path"] for t in tree.get("tree") or [] if os.path.basename(t["path"]) in ("AGENTS.md", "CLAUDE.md")}
    want = set()
    for f in files:
        d = os.path.dirname(f)
        while True:
            for name in ("AGENTS.md", "CLAUDE.md"):
                p = os.path.join(d, name) if d else name
                if p in have:
                    want.add(p)
            if not d:
                break
            d = os.path.dirname(d)
    return sorted(want, key=lambda p: (p.count("/"), p))


def fresh_eyes():
    """A Fresh eyes run: the review sees only the code, never earlier reviews or what anyone else said."""
    return os.environ.get("LFG_REVIEW_FRESH_EYES") == "1"


def _not_in_fresh_eyes(what):
    if fresh_eyes():
        raise ReviewError("this is a Fresh eyes review: %s stay hidden; review only the code" % what)


def context(repo, number):
    meta = pr_meta(repo, number)
    files = [f["path"] for f in gh_json(["pr", "view", str(number), "-R", repo, "--json", "files"])["files"]]
    rec = None if fresh_eyes() else load(repo, number)
    src = sources()
    return {"repo": repo, "number": number, "head_sha": meta["head_sha"], "author": meta["author"],
            "mine": meta["author"] == me(), "re_review": bool(rec and rec.get("passes")), "fresh_eyes": fresh_eyes(),
            "last_pass": rec["passes"][-1]["n"] if rec and rec.get("passes") else None,
            "record": record_path(repo, number), "sources": src["files"], "missing_sources": src["missing"],
            "agents_md": agents_md(repo, meta["head_sha"], files),
            "read_agents_md": "gh api repos/%s/contents/<path>?ref=%s -H 'Accept: application/vnd.github.raw'"
                              % (repo, meta["head_sha"]),
            "changed_files": len(files), "answered": answered(repo, number), "settled": memory(repo),
            # what the PR was meant to do: its description, and the Linear ticket its branch, title or description
            # names (a ticket the user named for this review wins; `lfg review run --ticket` passes it on)
            "title": meta["title"], "branch": meta["branch"], "description": meta.get("body") or "",
            "ticket": os.environ.get("LFG_REVIEW_TICKET") or ticket_of(meta["title"], meta.get("body"), meta["branch"])}


def answered(repo, number):
    """Every question about this PR you already answered, from any of its reviews. Given to every new review, Fresh
    eyes too: they're facts from you, not an earlier review's opinion, so no review asks them again."""
    out, seen = [], set()
    for p in (load(repo, number) or {}).get("passes") or []:
        for q in p.get("questions") or []:
            key = re.sub(r"\W+", " ", str(q.get("ask") or "")).strip().lower()
            if q.get("answer") and key not in seen:
                seen.add(key)
                out.append({"ask": q["ask"], "answer": q["answer"]})
    return out


# ---------------------------------------------------------------- the dashboard: queue, checkouts, background runs

_QUEUE = {}
SEARCHES = {"requested": "--review-requested=@me", "mine": "--author=@me"}


def queue(max_age=120, which="requested"):
    """Open PRs where GitHub has you as a requested reviewer ("requested") or that you opened ("mine"), each search
    cached for max_age seconds. GitHub never asks you to review your own PR, so "mine" is the only way to see them."""
    import threading
    hit = _QUEUE.get(which)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    if hit and max_age > 0:  # shown at once, asked again behind the page; Refresh (max_age=0) waits
        if which not in _REFRESHING:
            _REFRESHING.add(which)
            threading.Thread(target=_refresh_queue, args=(which,), daemon=True).start()
        return hit[1]
    data = _search([SEARCHES[which]], 50)
    _QUEUE[which] = (time.time(), data)
    return data


def _refresh_queue(which):
    try:
        _QUEUE[which] = (time.time(), _search([SEARCHES[which]], 50))
    except ReviewError:
        pass
    finally:
        _REFRESHING.discard(which)


def _search(terms, limit):
    rows = gh_json(["search", "prs"] + terms + ["--state=open", "--limit", str(limit),
                    "--json", "repository,number,title,author,url,updatedAt,isDraft,body"])
    return [{"repo": r["repository"]["nameWithOwner"], "number": r["number"], "title": r["title"],
             "author": (r.get("author") or {}).get("login", ""), "url": r["url"], "updated": r["updatedAt"],
             "draft": r.get("isDraft", False), "ticket": ticket_of(r.get("title"), r.get("body"))}
            for r in rows or []]


# ---------------------------------------------------------------- Linear tickets a PR belongs to
# Read from the PR's branch (Linear's "lee/ato-4223-..."), title or description. Look-alikes that aren't tickets:
NOT_TICKETS = {"cve", "cwe", "iso", "utf", "sha", "rfc", "nist", "sp", "cmmc", "http", "tls", "aes", "rsa", "gpt",
               "fips", "pr", "v", "rc", "release", "hotfix", "bump", "python", "node", "es", "ie", "win", "x"}


def ticket_of(title="", body="", branch=""):
    """The Linear ticket id a PR is for ("ATO-4223"), or "": the branch's, else the title's (any case), else the
    description's when it names only one (a sync PR's lists many). Only config linear.team's prefix when set."""
    team = (C.config()["linear"].get("team") or "").upper()

    def ok(ids):
        return list(dict.fromkeys(t.upper() for t in ids if (t.split("-")[0].upper() == team if team else
                                                              t.split("-")[0].lower() not in NOT_TICKETS)))
    in_branch = r"(?:^|[/_-])([a-z][a-z0-9]{1,9}-\d{1,6})(?=$|[-_/])"
    for ids in (ok(re.findall(in_branch, str(branch or "").lower())),
                ok(re.findall(r"(?<![\w-])([A-Za-z][A-Za-z0-9]{1,9}-\d{1,6})(?![\w-])", str(title or ""))),
                ok(re.findall(in_branch, str(title or "").lower().split(" ")[0]))):  # titled by its branch name
        if ids:
            return ids[0]
    ids = ok(re.findall(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b", str(body or "")[:4000]))
    return ids[0] if len(ids) == 1 else ""


def ticket_prs(ticket):
    """Every open PR on a ticket, in any repo you can see: GitHub's search for its id, kept when the PR names it."""
    t = str(ticket or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}-\d{1,6}", t):
        raise ReviewError("a Linear ticket id looks like ATO-4223")
    return [x for x in _search([t], 30) if x["ticket"] == t]


REMOTE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$")


def github_names(root):
    """owner/repo of every GitHub remote of the checkout at root, lowercased. All remotes, not `gh repo view`: in a
    fork gh picks upstream, which would leave out your own PRs on the fork."""
    names = set()
    for line in C.run(["git", "remote", "-v"], cwd=root, timeout=5).stdout.splitlines():
        m = REMOTE.search(line.split()[1] if len(line.split()) > 1 else "")
        if m:
            names.add(m.group(1).lower())
    return names


def local_checkout(repo):
    """A checkout of owner/repo on this machine: the repos LFG knows, and their sibling folders."""
    roots = set((C.enabled_state()["repos"] or {}).keys())
    for st in glob.glob(C.lfg_path("graphs", "*", "state.json")):
        r = (C.read_json(st, {}) or {}).get("repo_root")
        if r:
            roots.add(r)
    cand = []
    for r in sorted(roots):
        cand.append(r)
        parent = os.path.dirname(r.rstrip("/"))
        try:
            cand += sorted(os.path.join(parent, d) for d in os.listdir(parent))
        except OSError:
            continue
    seen = set()
    for d in cand:
        if d in seen or not os.path.isdir(os.path.join(d, ".git")):
            continue
        seen.add(d)
        url = C.run(["git", "config", "--get", "remote.origin.url"], cwd=d, timeout=5).stdout.strip()
        m = REMOTE.search(url)
        if m and m.group(1).lower() == repo.lower():
            return d
    return None


# Unattended runs may read anything and run any command: a review that can't run the tests, query a database or try
# the code isn't much of a review. What they must not do is change anything: GitHub writes, git writes, posting the
# review and editing files are denied here, and the guard blocks git and GitHub writes in them too (LFG_REVIEWER).
RUN_ALLOW = ["Read", "Grep", "Glob", "Bash", "mcp__linear__get_issue", "mcp__linear__list_comments",
             "mcp__plugin_lfg_code-review-graph",
             # Headroom shortens long tool output (the review skill itself); this reads it back in full
             "mcp__plugin_lfg_headroom__headroom_retrieve", "mcp__headroom__headroom_retrieve"]
GH_WRITE_DENY = ["Bash(gh api * -X *)", "Bash(gh api * --method *)", "Bash(gh api * -f *)", "Bash(gh api * -F *)",
                 "Bash(gh api * --field *)", "Bash(gh api * --raw-field *)", "Bash(gh api * --input *)",
                 "Bash(gh api -X *)", "Bash(gh api --method *)", "Bash(lfg review post *)"]
RUN_DENY = GH_WRITE_DENY + [
    "Bash(gh pr create*)", "Bash(gh pr merge*)", "Bash(gh pr comment*)", "Bash(gh pr review*)", "Bash(gh pr edit*)",
    "Bash(gh pr close*)", "Bash(gh pr ready*)", "Bash(gh issue create*)", "Bash(gh issue comment*)",
    "Bash(gh issue edit*)", "Bash(gh issue close*)", "Bash(git push*)", "Bash(git commit*)", "Bash(git merge*)",
    "Bash(git rebase*)", "Bash(git reset*)", "Bash(git checkout*)", "Bash(git switch*)", "Bash(git stash*)",
    "Bash(git restore*)", "Bash(git clean*)", "Bash(git tag*)", "Bash(git branch -*)",
    # what to remember and what to leave alone is your call, never an unattended review's
    "Bash(lfg review remember *)", "Bash(lfg review pass *)", "Bash(lfg review passes*--remove*)",
    "Edit", "Write", "NotebookEdit"]
# Fresh eyes: nothing that shows earlier reviews or what anyone else said on the PR
FRESH_DENY = ["Read(~/.lfg/reviews/**)", "Grep(~/.lfg/reviews/**)", "Bash(gh pr view *comments*)",
              "Bash(gh pr view *reviews*)", "Bash(gh api repos/*/pulls/*/comments*)",
              "Bash(gh api repos/*/pulls/*/reviews*)", "Bash(gh api repos/*/issues/*/comments*)",
              "Bash(gh api graphql*)", "Bash(lfg review show *)", "Bash(lfg review threads *)",
              "Bash(lfg review others *)"]


def run_tools(fresh_eyes=False):
    """(allowed, denied) tools for an unattended review run."""
    if not fresh_eyes:
        return RUN_ALLOW, RUN_DENY
    hidden = ("lfg review show", "lfg review threads", "lfg review others")
    return [x for x in RUN_ALLOW if not any(h in x for h in hidden)], RUN_DENY + FRESH_DENY


def together(p):
    """The other PRs' reviews from the same session as pass p (reviewed together): what each PR's page shows so the
    whole review reads in one place."""
    run_ = p.get("run") or {}
    out = []
    for other in run_.get("with") or []:
        try:
            rec = load(*parse_pr(other))
        except ReviewError:
            rec = None
        q = next((x for x in reversed((rec or {}).get("passes") or [])
                  if run_.get("session_id") and (x.get("run") or {}).get("session_id") == run_["session_id"]), None)
        out.append({"pr": other, "title": (rec or {}).get("title") or "", "url": (rec or {}).get("url") or "",
                    "author": (rec or {}).get("author") or "",
                    "pass": q, "live": bool(q) and q is rec["passes"][-1] and not q.get("posted")})
    return out


def job_path(repo, number):
    return os.path.join(reviews_dir(), "jobs", "%s__%d.json" % (repo.replace("/", "__"), number))


def job(repo, number):
    j = C.read_json(job_path(repo, number))
    if j and j.get("status") == "running" and not _alive(j.get("pid")):
        j["status"] = "failed"
        j["why"] = "the review stopped without finishing"
    return j


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


MODELS = [("claude-fable-5-1", "Fable 5.1"), ("claude-opus-5-5", "Opus 5.5"), ("claude-sonnet-5-5", "Sonnet 5.5"),
          ("claude-haiku-5-5", "Haiku 5.5")]


def models():
    """The models a review can run on, with names a person knows. "" is Claude Code's own default (its settings)."""
    own = (C.read_json(os.path.join(C.HOME, ".claude", "settings.json"), {}) or {}).get("model") or ""
    return [{"id": "", "label": "Claude Code default" + (" (%s)" % own if own else "")}] + [
        {"id": i, "label": lb} for i, lb in MODELS]


def chosen_model():
    """The model reviews, chats and fixes run on: Settings → Model for reviews. "" leaves it to Claude Code."""
    return str((C.config().get("review") or {}).get("model") or "")


def _direct():
    """Settings that send this one call straight to Anthropic, past the Headroom proxy, when Claude Code goes through
    it. Its compression drops small words, which mangled short chat messages ("i can merge this" arrived as "i
    merge"), so a conversation from the dashboard skips it. Long review runs still use it."""
    from . import headroom as HR
    try:
        if not HR.routed():
            return []
        up = (C.read_json(HR._state_path(), {}) or {}).get("upstream") or "https://api.anthropic.com"
    except Exception:  # noqa: BLE001 - if in doubt, leave the call as it was
        return []
    return ["--settings", json.dumps({"env": {"ANTHROPIC_BASE_URL": up}})]


def _model(m=None):
    m = chosen_model() if m is None else m
    return ["--model", m] if m else []


def method_key(path):
    """One method's key: `builtin` for LFG's own, ~/.claude/skills/<name> for anything inside one of your skills (its
    SKILL.md or a checklist in it: the whole skill is one method), else the file or folder as given."""
    if path == BUILTIN or PLUGIN_KEY.match(str(path)):
        return str(path)
    full = os.path.realpath(os.path.expanduser(str(path)))
    skills = os.path.realpath(os.path.join(C.HOME, ".claude", "skills"))
    if full.startswith(skills + os.sep):
        return "~/.claude/skills/" + full[len(skills) + 1:].split(os.sep)[0]
    return str(path)


def method_saved():
    """Your default methods, as keys in the order they're read (later ones win). None saved: LFG's own."""
    return list(dict.fromkeys(method_key(x) for x in (C.config().get("review") or {}).get("sources") or [])) \
        or [BUILTIN]


def method_choices():
    """Every method the picker offers: LFG's built-in one, each of your own skills, and any other file or folder in
    your default. `fits`: a skill whose job is reviewing (its description starts "Review" or "Audit") or one you use;
    the picker shows those and keeps the rest behind "Show every skill". `saved`: part of your default."""
    from . import control as K
    saved = method_saved()
    out = [{"key": BUILTIN, "label": "LFG's built-in method", "fits": True, "saved": BUILTIN in saved,
            "about": "LFG's own checklist: intent, bugs the PR introduces or exposes, severity and score."}]
    for d in sorted(glob.glob(os.path.join(C.HOME, ".claude", "skills", "*", "SKILL.md"))):
        key = "~/.claude/skills/%s" % os.path.basename(os.path.dirname(d))
        about = str(K._frontmatter(C.read_text(d)[:20000]).get("description") or "").lstrip(">- \n").strip()
        out.append({"key": key, "label": _skill_name(key), "about": about[:300], "saved": key in saved,
                    "fits": key in saved or bool(re.match(r"(review|audit)\b", about, re.I))})
    for key, f in _plugin_skills().items():
        about = str(K._frontmatter(C.read_text(f)[:20000]).get("description") or "").lstrip(">- \n").strip()
        out.append({"key": key, "label": _skill_name(key), "about": about[:300], "saved": key in saved,
                    "plugin": key.split("/")[0][7:].split("@")[0],
                    "fits": key in saved or bool(re.match(r"(review|audit)\b", about, re.I)
                                                 or re.search(r"review", key.split("/")[-1], re.I))})
    have = {m["key"] for m in out}
    out += [{"key": k, "label": _skill_name(k), "about": k, "fits": True, "saved": True, "file": True}
            for k in saved if k not in have]
    return out


def combos():
    """Your saved combos of methods, [{"name", "methods": [keys]}], in the order you saved them."""
    raw = (C.config().get("review") or {}).get("combos") or []
    return [{"name": str(c["name"]), "methods": [str(k) for k in c["methods"]]} for c in raw
            if isinstance(c, dict) and c.get("name") and isinstance(c.get("methods"), list) and c["methods"]]


def _write_review(fn):
    """Change the "review" part of config.json with fn(review_dict), backed up first."""
    from . import settings as ST
    path = C.lfg_path("config.json")
    raw = C.read_json(path, {}) or {}
    if not isinstance(raw, dict):
        raise ReviewError("%s is not valid JSON; fix it by hand first" % path)
    ST._backup(path, "config")
    rv = dict(raw.get("review") or {})
    fn(rv)
    if rv:
        raw["review"] = rv
    else:
        raw.pop("review", None)
    C.write_json(path, raw)


def save_combo(name, keys, old_name=""):
    """Save the ticked methods under a name (replacing a combo of that name, or renaming old_name)."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name or len(name) > 40:
        raise ReviewError("give the combo a name, up to 40 characters")
    srcs = method_sources(keys)
    keys = srcs or [BUILTIN]
    have = combos()
    gone = {name.lower(), str(old_name or "").strip().lower()}
    at = next((i for i, c in enumerate(have) if c["name"].lower() in gone), len(have))
    rest = [c for c in have if c["name"].lower() not in gone]
    rest.insert(min(at, len(rest)), {"name": name, "methods": keys})
    if len(rest) > 20:
        raise ReviewError("keep it to 20 combos")
    _write_review(lambda rv: rv.__setitem__("combos", rest))
    return {"combos": combos()}


def delete_combo(name):
    left = [c for c in combos() if c["name"].lower() != str(name or "").strip().lower()]
    _write_review(lambda rv: rv.__setitem__("combos", left) if left else rv.pop("combos", None))
    return {"combos": combos()}


def method_sources(keys):
    """What a review reads for these picked methods: LFG's own alone is the default ([]); otherwise the keys, LFG's
    own first so your own methods win where they disagree. Each must exist."""
    if not isinstance(keys, list) or not keys or not all(isinstance(x, str) and x.strip() for x in keys):
        raise ReviewError("pick at least one review method")
    keys = list(dict.fromkeys(method_key(x.strip()) for x in keys))
    for k in keys:
        if not _expand(k):
            raise ReviewError("%s isn't a file or a folder with Markdown in it" % k)
    keys = sorted(keys, key=lambda k: k != BUILTIN)
    return [] if keys == [BUILTIN] else keys


def method_label(srcs):
    """A method's name for people: the skill folder's name, or LFG's built-in method."""
    if not srcs:
        return "LFG's built-in method"
    return " + ".join(dict.fromkeys("LFG's built-in method" if x == BUILTIN else _skill_name(x) for x in srcs))


def _skill_name(path):
    """A source's name for people: the skill it belongs to (…/skills/review-pr/SKILL.md is review-pr), else the file
    or folder's own name."""
    p = PLUGIN_KEY.match(str(path))
    if p:  # superpowers:requesting-code-review
        return "%s:%s" % (p.group(1).split("@")[0], p.group(2))
    m = re.search(r"/skills/([^/]+)", str(path))
    return m.group(1) if m else (os.path.basename(str(path).rstrip("/")) or str(path))


def start(repo, number, ticket=None, fresh=False, together=(), model=None, method=None, fresh_eyes=False, notes=None,
          sources=None):
    """Start `lfg review run` detached (the dashboard's Review / Re-review / Review together buttons). together: more
    (repo, number) PRs to review in the same session. notes: what you want this one review to look into."""
    import subprocess
    import sys
    prs = [(repo, number)] + [tuple(x) for x in together if tuple(x) != (repo, number)]
    busy = [ref(*x) for x in prs if (job(*x) or {}).get("status") == "running"]
    if busy:
        return {"started": False, "note": "A review of %s is already running." % ", ".join(busy)}
    args = [sys.executable, os.path.join(C.PLUGIN_ROOT, "bin", "lfg"), "review", "run", ref(repo, number)]
    for x in prs[1:]:
        args += ["--with", ref(*x)]
    args += ["--ticket", ticket] if ticket else []
    args += ["--fresh"] if fresh or fresh_eyes else []
    args += ["--fresh-eyes"] if fresh_eyes else []
    args += ["--model", model] if model else []
    if sources is not None:  # the methods picked for this review (method_choices keys)
        args += ["--method", json.dumps(method_sources(sources))]
    elif method:  # one method by name: "builtin" or a skill folder's name
        key = BUILTIN if method == BUILTIN else "~/.claude/skills/%s" % method
        if key not in {m["key"] for m in method_choices()}:
            raise ReviewError("no review method %r" % method)
        args += ["--method", json.dumps(method_sources([key]))]
    notes = str(notes or "").strip()
    args += ["--notes", _text(notes, "notes", 4000)] if notes else []
    with open(os.devnull, "wb") as dn:
        subprocess.Popen(args, stdout=dn, stderr=dn, stdin=subprocess.DEVNULL, start_new_session=True,
                         close_fds=True)
    return {"started": True}


def cancel(repo, number):
    """Stop a running review: the `lfg review run` process and the Claude session under it (the dashboard starts it
    as its own process group). Every PR reviewed in that session is marked cancelled; nothing is saved."""
    import signal
    j = job(repo, number) or {}
    if j.get("status") != "running":
        raise ReviewError("no review of %s is running" % ref(repo, number))
    pid = int(j["pid"])
    mine = [ref(repo, number)] + list(j.get("with") or [])
    for r in mine:
        o, _, n = r.rpartition("#")
        x = job(o, int(n)) or {}
        if x.get("status") == "running" and x.get("pid") == j["pid"]:
            C.write_json(job_path(o, int(n)), dict(x, status="cancelled", ended=C.now_iso()))
    try:
        # its own group only when the dashboard started it; one run from a terminal stops alone
        os.killpg(pid, signal.SIGTERM) if os.getpgid(pid) == pid else os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    C.audit("review_cancel", {"pr": ref(repo, number), "with": len(mine) - 1})
    return {"cancelled": mine}


def ref(repo, number):
    return "%s#%d" % (repo, number)


def _passes(repo, number):
    return len((load(repo, number) or {}).get("passes") or [])


REVIEW_NOTES = (" Lee's notes for this review, on top of the method: look into these as well, and say in the summary "
                "what you found about each: %s")


def run(repo, number, ticket=None, fresh=False, together=(), model=None, method=None, fresh_eyes=False, notes=None):
    """Review one PR with Claude Code in print mode, on your own login, and wait for it. together: more PRs reviewed
    in the same session as one change (a backend and the frontend that calls it): each gets its own review, and the
    session also checks they agree with each other. Every review it saves remembers the session, so you can resume it,
    and its log, so the page can show what it did."""
    import shutil
    import subprocess
    if not C.which("claude"):
        raise ReviewError("Claude Code (`claude`) is not on PATH")
    prs = [(repo, number)] + [tuple(x) for x in together if tuple(x) != (repo, number)]
    before = {x: _passes(*x) for x in prs}
    label = method_label(json.loads(method) if method else (C.config().get("review") or {}).get("sources"))
    cwd = local_checkout(repo) or C.ensure_dir(reviews_dir())
    log = job_path(repo, number)[:-5] + ".log"
    refs = [ref(*x) for x in prs]
    for x in prs:
        C.write_json(job_path(*x), {
            "repo": x[0], "number": x[1], "status": "running", "pid": os.getpid(), "started": C.now_iso(),
            "cwd": cwd, "log": log, "re_review": before[x] > 0 and not fresh, "fresh": bool(fresh),
            "with": [r for r in refs if r != ref(*x)], "ticket": ticket or "", "model": model or chosen_model(),
            "method": label, "fresh_eyes": bool(fresh_eyes), "notes": notes or ""})
    skill = os.path.join(C.PLUGIN_ROOT, "skills", "review", "SKILL.md")
    if len(prs) == 1:
        what = "to review %s" % refs[0]
        out = "end your last message with the Output JSON in one ```json block"
    else:
        what = ("to review these PRs together, as one change: %s. They are meant to work together (for example a "
                "backend and the frontend that calls it). Review each one as the skill says, and also check that they "
                "agree with each other (API shapes, field names, error cases, which has to ship first); put a problem "
                "between them on the PR whose code should change, and say in each summary how it fits the others"
                % ", ".join(refs))
        out = ("end your last message with one ```json block {\"reviews\": [{\"pr\": \"owner/repo#number\", ...the "
               "Output JSON for that PR}]}, one entry per PR")
    prompt = ("Read %s and follow it %s%s. You are running unattended from the LFG dashboard: nobody can answer "
              "questions, so put anything you would have asked in the summary. Run each shell command on its own, "
              "never chained with ; or &&. Don't run `lfg review save` and don't write files: %s, and LFG saves it. "
              "Skip the steps after saving (showing the table, triage, the post command).%s"
              % (skill, what, " (Linear ticket %s)" % ticket if ticket else "", out,
                 " This is a new full review: review the whole PR from scratch, every new finding with since "
                 "\"first\". Where there are earlier reviews, still check each earlier finding still open and "
                 "fill `prior`, and never raise a settled one, as the skill's New full review step says."
                 if fresh and not fresh_eyes else
                 " This is a Fresh eyes review: review the whole PR as if nobody had reviewed it. `lfg review "
                 "context` says re_review false; skip the Re-review and Other reviewers steps, leave `prior` and "
                 "`echoes` empty, and never look for earlier reviews or other people's comments. Every finding has "
                 "since \"first\"." if fresh_eyes else ""))
    prompt += REVIEW_NOTES % notes if notes else ""
    allow, deny = run_tools(fresh_eyes)
    cmd = ["claude", "-p", prompt, "--permission-mode", "dontAsk", "--output-format", "stream-json", "--verbose",
           "--allowedTools", ",".join(allow), "--disallowedTools", ",".join(deny)] + _model(model)
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        # this code's own `lfg` first on PATH, so the session saves with the same version that started it
        env = dict(os.environ, PATH=os.path.join(C.PLUGIN_ROOT, "bin") + os.pathsep + os.environ.get("PATH", ""))
        if method:
            env["LFG_REVIEW_SOURCES"] = method  # `lfg review context` in that session reads this run's method
        if ticket and len(prs) == 1:
            env["LFG_REVIEW_TICKET"] = ticket  # the ticket you named wins over the one the PR's branch names
        if fresh_eyes:
            env["LFG_REVIEW_FRESH_EYES"] = "1"  # its `lfg review` commands hide earlier reviews and others' comments
        env["LFG_REVIEWER"] = "1"  # the guard blocks every git and GitHub write in it, whatever your Preferences
        cp = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
    sid = session_id(log)
    first = None
    for x in prs:
        why = ""
        if _passes(*x) == before[x]:
            why = _save_from_log(x[0], x[1], log, ticket, many=len(prs) > 1)
        ok = _passes(*x) > before[x]
        if ok:
            mark_echoes(*x)
            if fresh_eyes:
                mark_repeats(*x)
            rec = load(*x)
            p = rec["passes"][-1]
            kept = record_path(*x)[:-5] + ".pass%d.log" % p["n"]
            shutil.copyfile(log, kept)
            p["run"] = {"session_id": sid, "cwd": cwd, "log": kept, "with": [r for r in refs if r != ref(*x)],
                        "used": used(log), "method": label, "fresh_eyes": bool(fresh_eyes),
                        **({"notes": notes} if notes else {})}
            if fresh and p["n"] > 1:
                p["kind"] = "full"  # New full review: the whole PR again, not a re-review
            store(rec)
        if not ok and (job(*x) or {}).get("status") == "cancelled":
            continue
        j = dict(job(*x) or {}, status="done" if ok else "failed", exit=cp.returncode, ended=C.now_iso(),
                 why="" if ok else why)
        C.write_json(job_path(*x), j)
        C.audit("review_run", {"pr": ref(*x), "status": j["status"], "with": len(prs) - 1})
        first = first or j
    for i, x in enumerate(refs):
        for y in refs[i + 1:]:
            link(x, y)
    rec = load(repo, number) or {}
    p = (rec.get("passes") or [{}])[-1]
    if first is None:
        return job(repo, number)  # cancelled: no notice
    done = first["status"] == "done"
    score = " · score %s" % p["score"] if p.get("score") is not None else ""
    notify(ref(repo, number), "Review %s: %s" % ("done" if done else "failed", rec.get("title") or ref(repo, number)),
           "%s · %d findings%s" % (", ".join(refs), len(p.get("findings") or []), score) if done
           else first.get("why") or "see the log", ok=done)
    return first


# ---------------------------------------------------------------- notices: a review finished

NOTICES_KEEP = 50
SEEN_FOR = 90  # seconds: a dashboard tab that asked this recently shows the notice itself


def notices_path():
    return os.path.join(reviews_dir(), "notices.json")


def notify(pr, title, body, ok=True, place="findings"):
    """Tell you a review (or a fix) finished. Every open dashboard tab shows it as a desktop notification that opens
    the review; with no tab open, macOS shows a plain one instead."""
    import subprocess
    d = C.read_json(notices_path(), {}) or {}
    items = (d.get("items") or [])[-(NOTICES_KEEP - 1):]
    n = max([x["n"] for x in items] or [0]) + 1
    items.append({"n": n, "pr": pr, "title": title[:200], "body": str(body)[:400], "ok": bool(ok), "at": C.now_iso(),
                  "place": place})
    C.write_json(notices_path(), dict(d, items=items))
    if time.time() - float(d.get("seen") or 0) > SEEN_FOR and C.which("osascript"):
        script = "display notification %s with title %s" % (json.dumps(str(body)[:200]),
                                                             json.dumps("LFG: " + title[:150]))
        try:  # a notice is a courtesy: never let it break the review or fix that sent it
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


def notices(since):
    """Notices after number `since` (0: none, just the latest number to start from), and note a dashboard is open."""
    d = C.read_json(notices_path(), {}) or {}
    items = d.get("items") or []
    C.write_json(notices_path(), dict(d, seen=time.time()))
    last = max([x["n"] for x in items] or [0])
    return {"last": last, "items": [x for x in items if x["n"] > since] if since else []}


def session_id(log):
    """The Claude Code session a stream-json log came from (every event carries it)."""
    for ln in C.read_text(log).splitlines()[:50]:
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("session_id"):
            return ev["session_id"]
    return ""


def used(log):
    """What a review run used (sessions.used), with the review skill that runs it (lfg:review, marked `runner`: it
    reads the skill's file rather than calling the Skill tool, so the log alone wouldn't show it) and `method_files`:
    the files of your own skills it read, which is where a chosen method shows up."""
    u = SS.used(log)
    if u is None:
        return u
    u["skills"] = [x for x in u["skills"] if x["name"] != "lfg:review"]
    u["skills"].insert(0, {"name": "lfg:review", "count": 1, "plugin": "lfg", "runner": True})
    u["plugins"] = sorted(set(u["plugins"]) | {"lfg"})
    u["method_files"] = method_files(log)
    return u


def method_files(log):
    """Files under ~/.claude/skills a run read with the Read tool, in the order first read, as skill/path."""
    root = os.path.join(C.HOME, ".claude", "skills") + os.sep
    out = []
    try:
        fh = open(log, "rb")
    except OSError:
        return out
    with fh:
        for ln in fh:
            if b'"Read"' not in ln:
                continue
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            for b in ((ev.get("message") or {}).get("content") or []) if isinstance(ev, dict) else []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Read":
                    path = os.path.normpath(os.path.expanduser(str((b.get("input") or {}).get("file_path") or "")))
                    rel = path[len(root):] if path.startswith(root) else ""
                    if rel and rel not in out:
                        out.append(rel)
    return out


def resume(run):
    """The command that picks a review's session back up, so you can ask it about its findings."""
    return SS.resume_command({"cwd": run.get("cwd"), "id": run["session_id"]}) if run.get("session_id") else ""


def backfill(repo, number):
    """Reviews run before passes kept their session: the job log of the last run still has it, so give it to the
    latest pass if that pass came from that run."""
    import shutil
    rec, j = load(repo, number), job(repo, number) or {}
    p = ((rec or {}).get("passes") or [None])[-1]
    if not p or p.get("run") or j.get("status") != "done" or (p.get("ts") or "") < (j.get("started") or "~"):
        return rec
    sid = session_id(j.get("log") or "")
    if not sid:
        return rec
    kept = record_path(repo, number)[:-5] + ".pass%d.log" % p["n"]
    shutil.copyfile(j["log"], kept)
    p["run"] = {"session_id": sid, "cwd": j.get("cwd") or "", "log": kept, "with": list(j.get("with") or [])}
    store(rec)
    return rec


def refresh_used(rec):
    """Reviews saved before LFG kept what a run used, or before it marked the runner and the method's files: read it
    once from the kept log and save it."""
    stale = [p["run"] for p in (rec or {}).get("passes") or [] if (p.get("run") or {}).get("log")
             and "method_files" not in (p["run"].get("used") or {})]
    for run in stale:
        run["used"] = used(run["log"])
    if stale:
        store(rec)
    return rec


ASK = ("Lee is talking to you about the review you did, from the LFG dashboard. Answer from what you found and what "
       "the code says; read more of it if you need to. Answer short and plain. If a finding was wrong, say so. If the "
       "conversation settles a change to the review (Lee asks for one, or you agree a finding is wrong, mis-rated or "
       "badly worded), end your reply with one ```json block {\"changes\": [{\"pr\": \"owner/repo#n\", \"id\": "
       "\"1.2\", and only the fields that change: \"title\", \"severity\", \"issue\", \"fix\", \"body\", \"reply\", "
       "\"status\" (\"keep\" or \"drop\")}], \"new\": [one per problem found now that no finding covers: "
       "{\"title\", \"severity\", \"file\", \"line\", \"issue\", \"fix\", \"body\"}], \"summary\": \"only if the "
       "summary changes\", \"verdict\" (\"mergeable\", \"almost\" or \"not\") and \"verdict_why\" only if "
       "whether it can merge changes}. LFG applies it. The score is always 100 minus the points of what is still open "
       "(findings and questions that cost points), worked out by LFG: never give or promise a score, and never hold "
       "points back for a problem; make it a finding. "
       "The page has its own buttons to save a decision (to this repo's dev-graph, or to Lee's second-brain): "
       "never ask whether to save or remember something, and don't offer to. "
       "Never save, post or run anything that writes.\n\n"
       "The review as it stands: %s\n\n%s")


CHANGE_FIELDS = {"title": 200, "issue": 1000, "fix": 1000, "body": MAX_BODY, "reply": 4000}


def apply_changes(repo, number, n, out):
    """Apply what a conversation settled ({"changes": [...], "summary": ...} from Claude's reply) to the review it is
    about, and to PRs reviewed in the same session. Posted comments stay as they are. Returns what changed, in words."""
    done, recs = [], {}
    for c in (out or {}).get("changes") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        try:
            r, k = parse_pr(str(c.get("pr") or ref(repo, number)))
            rec = recs.get((r, k)) or need(r, k)
            f = find(rec, str(c["id"]))
        except ReviewError:
            continue
        if f.get("comment_id"):
            continue
        what = []
        for k2, limit in CHANGE_FIELDS.items():
            if isinstance(c.get(k2), str) and c[k2].strip() and c[k2] != f.get(k2):
                f[k2] = _text(c[k2], k2, limit)
                what.append({"body": "comment"}.get(k2, k2))
        if c.get("severity") in SEVERITIES and c["severity"] != f["severity"]:
            f["severity"] = c["severity"]
            what.append("severity")
        if c.get("status") == "drop" and c["status"] != f["status"]:
            f["dropped_by"] = "claude"  # agreed in a conversation that it isn't needed
        if c.get("status") in ("keep", "drop") and c["status"] != f["status"]:
            f["status"] = c["status"]
            what.append("kept" if c["status"] == "keep" else "dropped")
        if what:
            recs[(r, k)] = rec
            done.append("%s%s: %s" % ("" if (r, k) == (repo, number) else ref(r, k) + " ", f["id"], ", ".join(what)))
    new = [f for f in (out or {}).get("new") or [] if isinstance(f, dict)][:5]
    if new:
        rec = recs.get((repo, number)) or need(repo, number)
        p = next((x for x in rec["passes"] if x["n"] == int(n)), None)
        for f in new if p else []:
            try:
                f = _clean_finding(dict(f, since="missed"), len(p["findings"]) + 1)
            except ReviewError:
                continue
            f["id"] = "%d.%d" % (p["n"], len(p["findings"]) + 1)
            f["found_in_chat"] = True
            p["findings"].append(f)
            recs[(repo, number)] = rec
            done.append("%s: new %s finding" % (f["id"], f["severity"]))
    v = (out or {}).get("verdict")
    if v in VERDICTS:
        rec = recs.get((repo, number)) or need(repo, number)
        p = next((x for x in rec["passes"] if x["n"] == int(n)), None)
        if p and p.get("verdict") != v:
            p["verdict"], p["verdict_why"] = v, _text((out or {}).get("verdict_why"), "verdict_why", 400)
            recs[(repo, number)] = rec
            done.append("verdict %s" % v)
    summary = (out or {}).get("summary")
    if isinstance(summary, str) and summary.strip():
        rec = recs.get((repo, number)) or need(repo, number)
        p = next((x for x in rec["passes"] if x["n"] == int(n)), None)
        if p and p.get("summary") != summary:
            p["summary"] = _text(summary, "summary")
            recs[(repo, number)] = rec
            done.append("summary")
    for rec in recs.values():
        store(rec)
    return done


def _reply_text(text):
    """Claude's reply without the ```json change block, and that block parsed."""
    found = find_review_json(text, "changes")
    shown = re.sub(r"```json\s*\{[\s\S]*?\}\s*```\s*$", "", text).strip() if found else text
    return shown or "Done.", found


IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
FILE_MAX = 20_000_000


def chat_files_dir():
    return C.lfg_path("tmp", "chat")


PREVIEW_MAX = 400_000  # characters of text, rows of a table: enough to read, never the whole of a big file


def attachment_preview(path):
    """A file attached in a review chat, to look at in the page without downloading it: an image as a data: URL, a
    CSV or TSV as rows, a PDF as a data: URL, anything readable as text as text. Only files the chat saved."""
    import base64
    import csv
    import mimetypes
    base = os.path.realpath(chat_files_dir()) + os.sep
    real = os.path.realpath(str(path or ""))
    if not path or not real.startswith(base) or not os.path.isfile(real):
        raise ReviewError("that file isn't one this chat saved")
    name = os.path.basename(real)
    kind = mimetypes.guess_type(name)[0] or ""
    with open(real, "rb") as fh:
        raw = fh.read(FILE_MAX + 1)
    if kind in IMAGE_TYPES or kind == "application/pdf":
        return {"kind": "image" if kind in IMAGE_TYPES else "pdf", "name": name,
                "src": "data:%s;base64,%s" % (kind, base64.b64encode(raw).decode())}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"kind": "binary", "name": name, "size": len(raw)}
    if name.lower().endswith((".csv", ".tsv")):
        rows = list(csv.reader(text.splitlines()[:2000], delimiter="\t" if name.lower().endswith(".tsv") else ","))
        return {"kind": "table", "name": name, "rows": rows, "more": max(0, text.count("\n") - 2000)}
    return {"kind": "text", "name": name, "text": text[:PREVIEW_MAX], "cut": len(text) > PREVIEW_MAX}


def session_history(sid, limit=20):
    """The last `limit` exchanges of one of your Claude Code sessions (what you said, what Claude said back), for the
    review chat when it's pointed at that session. Tool steps and system notes are left out."""
    from . import claudesess as CS
    if not re.match(r"^[0-9a-f-]{36}$", str(sid or "")):
        raise ReviewError("not a session id")
    path = CS.transcript(sid)
    if not path:
        raise ReviewError("that session's transcript is gone")
    items, _ = CS.read(path)
    turns = []
    for it in items:
        if it.get("k") == "me" and not str(it.get("text") or "").lstrip().startswith("<"):
            turns.append({"q": it.get("text") or "", "a": "", "at": it.get("ts"),
                          "images": len(it.get("images") or [])})
        elif it.get("k") == "ai" and turns and it.get("text"):
            turns[-1]["a"] = (turns[-1]["a"] + "\n\n" + it["text"]).strip()
    return {"turns": turns[-limit:], "more": max(0, len(turns) - limit)}


def saved_note(rec):
    """What Lee already saved from this review with the page's buttons, so the chat doesn't ask about it again."""
    where = {"dev-graph": "this repo's dev-graph, as a decision", "second-brain": "his second-brain, as a note"}
    rows = []
    for p in rec.get("passes") or []:
        for q in p.get("questions") or []:
            if q.get("saved"):
                rows.append("your question \"%s\": saved to %s"
                            % (_one_line(q.get("ask"), 120), where[q["saved"]["to"]]))
        for f in p.get("findings") or []:
            for s in f.get("saved") or []:
                rows.append("finding %s: saved to %s" % (f["id"], where.get(s.get("to"), s.get("to"))))
    return ("Already saved by Lee from this review (don't ask about these): " + "; ".join(rows) + ".") if rows else ""


def _review_now(rec, p):
    """The pass as Claude needs it to change it: ids, ratings, statuses and comments, compact."""
    return json.dumps({"pr": ref(rec["repo"], rec["number"]), "summary": p.get("summary"),
                       "findings": [{k: f.get(k) for k in ("id", "severity", "status", "title", "file", "line", "body",
                                                           "reply") if f.get(k) is not None} for f in p["findings"]]})


def _where(q):
    """A question's place in the code, when it has one: {"file", "line"} (both optional)."""
    f = str(q.get("file") or "").strip()[:500]
    line = q.get("line") if isinstance(q.get("line"), int) and q["line"] > 0 else None
    return {k: v for k, v in (("file", f), ("line", line if f else None)) if v}


def _question(rec, n, qid):
    p = next((x for x in rec["passes"] if x["n"] == int(n or 0)), None)
    qq = next((x for x in (p or {}).get("questions") or [] if x["id"] == qid), None)
    if not qq:
        raise ReviewError("no question %s on review %s" % (qid, n))
    return p, qq


# ---------------------------------------------------------------- asking the author (user-only: guard blocks agents)

def ask_author(repo, number, n, qid, text=None, lines=None):
    """Post a review's question on the PR for its author: an inline comment on the question's line when GitHub takes
    one there, else a comment on the PR (naming the file and line). Their replies come back with `question_replies`.
    text: the comment as you want it to read (default: the question)."""
    rec = need(repo, number)
    p, qq = _question(rec, n, qid)
    if qq.get("asked"):
        raise ReviewError("already asked on GitHub: %s" % qq["asked"].get("url"))
    body = _text(text if str(text or "").strip() else qq["ask"], "question", 4000)
    if qq.get("file") and qq.get("line") and lines is None:
        lines = diff_lines(repo, rec["base"], p["head_sha"])
    if qq.get("file") and qq.get("line") and qq["line"] in (lines or {}).get(qq["file"], ()):
        out = gh_json(["api", "-X", "POST", "repos/%s/pulls/%d/comments" % (repo, number), "--input", "-"],
                      stdin=json.dumps({"body": body, "commit_id": p["head_sha"], "path": qq["file"],
                                        "line": qq["line"], "side": "RIGHT"}), timeout=60)
        kind = "inline"
    else:
        where = "`%s%s`: " % (qq["file"], ":%d" % qq["line"] if qq.get("line") else "") if qq.get("file") else ""
        out = gh_json(["api", "-X", "POST", "repos/%s/issues/%d/comments" % (repo, number), "--input", "-"],
                      stdin=json.dumps({"body": where + body}), timeout=60)
        kind = "comment"
    rec = need(repo, number)
    _, qq = _question(rec, n, qid)
    qq["asked"] = {"kind": kind, "comment_id": out.get("id"), "url": out.get("html_url"), "body": body,
                   "at": out.get("created_at") or C.now_iso()}
    store(rec)
    C.audit("review_ask", {"pr": "%s#%d" % (repo, number), "pass": int(n), "question": qid, "kind": kind})
    return qq


REPLIES_TTL = 120  # seconds: how long the replies read from GitHub are reused before asking again


def asked_questions(rec):
    """Every question asked on GitHub, in any review of the PR: [(pass, question)]."""
    return [(p, q) for p in rec.get("passes") or [] for q in p.get("questions") or [] if q.get("asked")]


def question_replies(repo, number, max_age=REPLIES_TTL):
    """Read the replies to the questions asked on GitHub and keep them on each question (`replies`: who, body, at,
    url). An inline question's replies are its thread; a PR comment's are the later PR comments by anyone but you.
    Asks GitHub at most once every max_age seconds. Returns the record."""
    rec = need(repo, number)
    asked = asked_questions(rec)
    if not asked:
        return rec
    now = time.time()
    if all(now - (q["asked"].get("checked") or 0) < max_age for _, q in asked):
        return rec
    mine = me()
    found = {}
    if any(q["asked"]["kind"] == "inline" for _, q in asked):
        for t in _threads(repo, number):
            nodes = t["comments"]["nodes"]
            if nodes:
                found[nodes[0]["databaseId"]] = [{"by": (c.get("author") or {}).get("login", ""),
                                                  "body": c["body"][:4000], "at": c["createdAt"]} for c in nodes[1:]]
    later = []
    if any(q["asked"]["kind"] == "comment" for _, q in asked):
        later = [{"by": (c.get("user") or {}).get("login", ""), "body": (c.get("body") or "")[:4000],
                  "at": c.get("created_at") or "", "url": c.get("html_url") or "", "id": c.get("id")}
                 for c in gh_json(["api", "--paginate", "repos/%s/issues/%d/comments" % (repo, number)]) or []]
    asks = sorted((q["asked"]["at"], q["asked"]["comment_id"]) for _, q in asked if q["asked"]["kind"] == "comment")
    rec = need(repo, number)
    for _, q in asked_questions(rec):
        a = q["asked"]
        if a["kind"] == "inline":
            got = found.get(a["comment_id"])
            if got is not None:
                q["replies"] = [r for r in got if r["by"] != mine] or []
        else:  # PR comments after it and before the next question asked this way
            nxt = next((at for at, cid in asks if at > a["at"] and cid != a["comment_id"]), None)
            q["replies"] = [{k: c[k] for k in ("by", "body", "at", "url")} for c in later
                            if c["at"] > a["at"] and (not nxt or c["at"] < nxt) and c["by"] != mine
                            and c["id"] != a["comment_id"]]
        a["checked"] = now
    store(rec)
    return rec


def record_answer(repo, number, n, qid, text):
    """Your answer to a question the review couldn't settle, kept on the question. Returns the question. The answer
    then goes to the review's chat (reviewchat.answer), where Claude can change the review to match."""
    if not str(text or "").strip():
        raise ReviewError("write an answer")
    rec = need(repo, number)
    p = next((x for x in rec["passes"] if x["n"] == int(n or 0)), None)
    qq = next((x for x in (p or {}).get("questions") or [] if x["id"] == qid), None)
    if not qq:
        raise ReviewError("no question %s on review %s" % (qid, n))
    qq["answer"] = _text(text, "answer", 4000)
    store(rec)
    return qq


VERDICTS = ("mergeable", "almost", "not")


def verdict_of(p):
    """The review's own call on whether it can merge, else one worked out from what's still open (older reviews).
    Once everything it raised is fixed or passed, mergeable."""
    if p.get("verdict_now") in VERDICTS:
        return p["verdict_now"]
    if p.get("verdict") in VERDICTS:
        return p["verdict"]
    open_ = [f for f in p.get("findings") or [] if f["status"] != "drop" and not (f.get("fixed") or {}).get("commit")]
    if any(f["severity"] in ("blocker", "major") for f in open_):
        return "not"
    return "almost" if any(f["severity"] == "minor" for f in open_) else "mergeable"


def scores(rec):
    """Every review's score in order, with its kind, so the page can show which way the PR is heading."""
    return [{"n": p["n"], "score": p.get("score"), "kind": p.get("kind") or "first"} for p in rec.get("passes") or []
            if p.get("score") is not None]


SAVED_PREFIX = "Review: "  # every decision or note saved from a review starts like this, so later reviews find them
SAVE_TARGETS = ("dev-graph", "second-brain")
SCOPES = ("pr", "repo", "all")  # where "don't flag this again" holds: this PR, every PR in the repo, every repo


def _save_knowledge(repo, to, title, text):
    """Save one thing from a review. dev-graph: a decision on this repo's own branch, where its sessions and
    `lfg review context` read it. second-brain: a personal note. Raises ReviewError with something sayable."""
    from . import knowledge as KN
    if to not in SAVE_TARGETS:
        raise ReviewError("save to dev-graph or second-brain")
    root = local_checkout(repo) if to == "dev-graph" else None
    if to == "dev-graph" and not root:
        raise ReviewError("%s isn't checked out on this machine, so it has no dev-graph here; save it to your "
                          "second-brain instead" % repo)
    try:
        return KN.add("decision" if to == "dev-graph" else "note", SAVED_PREFIX + title, text,
                      repo=repo.split("/")[-1] if to == "dev-graph" else "", root=root)
    except Exception as e:  # the graph may be down: say so on the page, the text itself is safe
        raise ReviewError("couldn't save to %s: %s" % (to, str(e)[:200])) from None


def remember(repo, number, n, qid, to):
    """Keep your answer to a review's question: a decision in this repo's dev-graph, or a note in your second-brain,
    so later sessions and reviews know it."""
    rec = need(repo, number)
    p = next((x for x in rec["passes"] if x["n"] == int(n or 0)), None)
    qq = next((x for x in (p or {}).get("questions") or [] if x["id"] == qid), None)
    if not qq or not qq.get("answer"):
        raise ReviewError("answer the question first")
    text = "%s\n\nAnswer: %s\n\n(From the review of %s.)" % (qq["ask"], qq["answer"], ref(repo, number))
    out = _save_knowledge(repo, to, qq["ask"][:200], text)
    rec = need(repo, number)
    p = next(x for x in rec["passes"] if x["n"] == int(n))
    next(x for x in p["questions"] if x["id"] == qid)["saved"] = {"to": to, "slug": out["slug"], "at": C.now_iso()}
    store(rec)
    return out


MAX_SAVED_TURNS = 6  # the last turns of a discussion that go into what is saved


def _one_line(text, limit):
    text = re.sub(r"```[\s\S]*?```", " ", str(text or ""))  # the change block Claude ends a reply with
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _conclusion(f, note):
    note = str(note or "").strip()
    if note:
        return note
    if f["status"] == "drop":
        return "Not a problem here. Reviews should not flag it again, unless it has become worse."
    if f["status"] == "keep":
        return "A real problem. Reviews should keep flagging it."
    return ""


def remember_finding(repo, number, fid, to, note=None):
    """Save what a finding's discussion settled, asked every time where it goes: a decision in this repo's dev-graph
    ("for this repo") or a note in your second-brain ("for me"). Later reviews read it as settled (`lfg review
    context`, `settled`). `note` is your own words for the conclusion; without it the finding's decision is the
    conclusion (dropped: not a problem here; kept: a real problem). The finding keeps where it was saved."""
    if to not in SAVE_TARGETS:
        raise ReviewError("save to dev-graph or second-brain")
    rec = need(repo, number)
    f = find(rec, fid)
    if any(s.get("to") == to for s in f.get("saved") or []):
        raise ReviewError("%s is already saved to %s" % (fid, to))
    conclusion, said = _conclusion(f, note), f.get("chat") or []
    if not conclusion:
        raise ReviewError("decide %s first (Keep or Drop), or say what was settled" % fid)
    if not said and not str(note or "").strip():
        raise ReviewError("discuss %s first, or say what was settled" % fid)
    talk = "\n".join("- Lee: %s\n  Claude: %s" % (_one_line(x.get("q"), 400), _one_line(x.get("a"), 700))
                     for x in said[-MAX_SAVED_TURNS:])
    where = "%s%s" % (f["file"], ":%s" % f["line"] if f.get("line") else "") if f.get("file") else "the PR as a whole"
    title = (f.get("title") or f.get("issue") or "a finding").strip()
    text = "\n".join(x for x in [
        "Finding %s of the review of %s: %s" % (fid, ref(repo, number), title),
        "Where: %s (%s)" % (where, f.get("severity")), "Problem raised: %s" % _one_line(f.get("issue"), 600),
        "\nDecision: %s" % conclusion, "\nDiscussion:\n%s" % talk if talk else "",
        "\n(Saved from the review of %s.)" % ref(repo, number)] if x)
    out = _save_knowledge(repo, to, title[:190], text)
    rec = need(repo, number)  # read again: the graph took a moment and the page may have saved meanwhile
    f = find(rec, fid)
    f["saved"] = (f.get("saved") or []) + [{"to": to, "slug": out["slug"], "at": C.now_iso()}]
    store(rec)
    return {"finding": fid, "to": to, "slug": out["slug"]}


# ---------------------------------------------------------------- what you already decided: read by every review

def _passes_path():
    return os.path.join(reviews_dir(), "passes.json")


def _norm(text):
    return re.sub(r"\W+", " ", str(text or "")).strip().lower()


def passes_list(repo=None):
    """Findings you passed on for good, newest first: every one, or those that apply to `repo` (its own, and every
    repo's)."""
    rows = (C.read_json(_passes_path(), {}) or {}).get("passes") or []
    if repo:
        rows = [x for x in rows if x.get("scope") == "all" or str(x.get("repo")).lower() == repo.lower()]
    return sorted(rows, key=lambda x: x.get("at") or "", reverse=True)


def pass_on(repo, number, fid, scope, note=None):
    """Pass on a finding: drop it, and say how far "don't flag this again" reaches. `pr`: this PR only (a dropped
    finding is already never raised again here unless it got worse). `repo`: every PR in this repo. `all`: every repo.
    The last two are kept in ~/.lfg/reviews/passes.json, shown on the Reviews page and given to every later review of
    the repo (`lfg review context`, `settled.passed`), which raises one again only if it is clearly worse."""
    if scope not in SCOPES:
        raise ReviewError("scope is one of %s" % ", ".join(SCOPES))
    rec = need(repo, number)
    f = find(rec, fid)
    if f["status"] != "drop":
        mark(repo, number, [fid], status="drop")  # refuses a comment that is already on GitHub
        rec = need(repo, number)
        f = find(rec, fid)
    if scope == "pr":
        return {"finding": fid, "scope": "pr"}
    title = (f.get("title") or f.get("issue") or "").strip()
    same = [x for x in passes_list() if x["scope"] == scope and _norm(x["title"]) == _norm(title)
            and (scope == "all" or x["repo"].lower() == repo.lower())]
    if same:
        entry = same[0]
    else:
        entry = {"id": "ps-" + hashlib.sha1(("%s%s%s%f" % (repo, fid, title, time.time())).encode()).hexdigest()[:8],
                 "scope": scope, "repo": repo, "title": _text(title, "title", 200),
                 "issue": _text(f.get("issue"), "issue", 1000), "severity": f.get("severity"),
                 "file": f.get("file") or "", "line": f.get("line"),
                 "pr": ref(repo, number), "finding": fid, "note": _text(str(note or "").strip(), "note", 1000),
                 "at": C.now_iso()}
        C.ensure_dir(reviews_dir())
        C.write_json(_passes_path(), {"passes": [entry] + passes_list()})
    f["passed_on"] = {"id": entry["id"], "scope": scope, "at": entry["at"]}
    store(rec)
    return dict(entry, finding=fid)


def pass_remove(pid):
    """Take a finding off the list of things reviews leave alone. The finding it came from stays dropped."""
    rows = passes_list()
    if not any(x["id"] == pid for x in rows):
        raise ReviewError("no such pass: %s" % pid)
    C.write_json(_passes_path(), {"passes": [x for x in rows if x["id"] != pid]})
    for rec in all_records():  # the finding it came from stops saying it was passed on for good
        hit = [f for f in findings(rec) if (f.get("passed_on") or {}).get("id") == pid]
        for f in hit:
            f.pop("passed_on", None)
        if hit:
            store(rec)
    return {"removed": pid}


MEMORY_CAP = 40  # decisions and notes handed to a review, newest first
MEMORY_TEXT = 1500


def _saved_rows(graph, node, name_field, text_field, branch=None):
    from . import omnigraph as OG
    q = ("query l() { match { $x: %s } return { $x.slug, $x.%s, $x.%s, $x.createdAt } "
         "order { $x.createdAt desc } limit 500 }" % (node, name_field, text_field))
    rows = [r for r in OG.read(graph, q, "l", branch=branch) if str(r.get(name_field) or "").startswith(SAVED_PREFIX)]
    return [{"slug": r["slug"], "title": r[name_field][len(SAVED_PREFIX):],
             "text": str(r.get(text_field) or "")[:MEMORY_TEXT], "at": str(r.get("createdAt") or "")[:10]}
            for r in rows[:MEMORY_CAP]]


def memory(repo):
    """What you already decided about this repo's code, for a review to treat as settled: decisions saved from earlier
    reviews (this repo's dev-graph), personal notes saved from them (second-brain: yours, in every repo; each says
    which PR it came from) and the findings you passed on for good. A graph that can't be read is named in
    `unavailable`, never skipped silently."""
    out = {"decisions": [], "notes": [], "passed": [] if fresh_eyes() else passes_list(repo), "unavailable": []}
    from . import setup as SU
    if not SU.pack_on("knowledge"):
        return out  # nothing can have been saved
    from . import teamknowledge as K
    root = local_checkout(repo)
    for key, graph, args in (("decisions", "dev-graph", ("Decision", "title", "decision")),
                             ("notes", "second-brain", ("Note", "name", "content"))):
        if key == "decisions" and not root:
            continue
        try:
            out[key] = _saved_rows(graph, *args, branch=K.branch_for(root) if key == "decisions" else None)
        except Exception as e:  # noqa: BLE001 - a graph that is down must not stop the review
            out["unavailable"].append("%s: %s" % (graph, str(e)[:160]))
    return out


def post_reply(repo, number, fid, body=None):
    """Reply to the comment a finding came from (your own PR, when you pass on it): in its thread when it was inline,
    else on the PR. The dashboard's button; agents can't reach it."""
    rec = need(repo, number)
    f = find(rec, fid)
    rb = f.get("raised_by")
    if not rb:
        raise ReviewError("%s isn't someone else's comment" % fid)
    text = _text(body if body is not None else f.get("reply"), "reply", 4000).strip()
    if not text:
        raise ReviewError("the reply is empty")
    if rb.get("kind") == "inline" and rb.get("comment_id"):
        out = gh_json(["api", "-X", "POST", "repos/%s/pulls/%d/comments/%d/replies" % (repo, number, rb["comment_id"]),
                       "-f", "body=" + text])
    else:
        quoted = "@%s %s" % (rb["who"], text) if not rb.get("bot") else text
        out = gh_json(["api", "-X", "POST", "repos/%s/issues/%d/comments" % (repo, number), "-f", "body=" + quoted])
    rec = need(repo, number)
    f = find(rec, fid)
    f["reply"], f["replied"] = text, {"url": (out or {}).get("html_url") or "", "at": C.now_iso()}
    store(rec)
    C.audit("review_reply", {"pr": ref(repo, number), "finding": fid})
    return f["replied"]


CHECK = ("A code review found this problem in a pull request. Since then the author pushed more commits. Say whether "
         "this one finding is fixed now, from the changes and the code below. Answer only with one ```json block "
         "{\"state\": \"fixed\" or \"partly\" or \"not\", \"why\": \"one plain sentence a person can check, naming "
         "the line or change that settles it\"}.\n\nThe finding (%s, %s): %s\nWhere: %s line %s\nIssue: %s\n"
         "Suggested fix: %s\n\nWhat changed in %s since the review (%s to %s):\n%s\n\nThat file now, around the "
         "spot:\n%s\n\nOther files changed since the review: %s")
CHECK_STATES = ("fixed", "partly", "not")


def _last_object(text, key):
    """The last JSON object in some text that has `key`, or {}."""
    dec, best = json.JSONDecoder(), {}
    for m in re.finditer(r"\{", text or ""):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and key in obj:
            best = obj
    return best


def check_fixed(repo, number, fid):
    """Is one finding fixed yet, without a re-review: the commits since the review, and the code where the finding
    points now, go to Claude with no tools, which answers fixed, partly or not, and why. Kept on the finding."""
    import subprocess
    rec = need(repo, number)
    f = find(rec, fid)
    p = next(x for x in rec["passes"] if f in x["findings"])
    head = (gh_status(repo, number, max_age=0) or {}).get("head_sha")
    if not head:
        raise ReviewError("couldn't ask GitHub where the PR is now")
    whole = not f.get("file")  # about the PR as a whole, often its description: that can change with no commit
    if head == p["head_sha"] and not whole:
        out = {"state": "not", "why": "No commits since this review, so nothing has changed yet.", "head": head,
               "at": C.now_iso(), "quick": True}
    else:
        if not C.which("claude"):
            raise ReviewError("Claude Code (`claude`) is not on PATH")
        files = gh_json(["api", "repos/%s/compare/%s...%s" % (repo, p["head_sha"], head)], timeout=120) or {} \
            if head != p["head_sha"] else {}
        changed = files.get("files") or []
        patch = next((x.get("patch") or "" for x in changed if x.get("filename") == f.get("file")), "")
        now = ""
        if f.get("file"):
            raw = _gh(["api", "-H", "Accept: application/vnd.github.raw",
                       "repos/%s/contents/%s?ref=%s" % (repo, f["file"], head)], timeout=60)
            if raw.returncode == 0:
                lines, at = raw.stdout.splitlines(), int(f.get("line") or 1)
                lo = max(0, at - 40)
                now = "\n".join("%d %s" % (lo + i + 1, t) for i, t in enumerate(lines[lo:at + 40]))
            else:
                now = "(the file is gone at the new head)"
        others = [x["filename"] for x in changed if x.get("filename") != f.get("file")]
        if whole:  # about the PR as a whole: every change counts, and the description as it reads now
            patch = "\n".join("--- %s\n%s" % (x["filename"], x.get("patch") or "") for x in changed)
            desc = (gh_json(["pr", "view", str(number), "-R", repo, "--json", "title,body"], timeout=60) or {})
            now = "The PR's title and description now:\n%s\n\n%s" % (desc.get("title") or "", desc.get("body") or "")
        prompt = CHECK % (fid, f.get("severity"), f.get("title") or "", f.get("file") or "the PR as a whole",
                          f.get("line") or "-", f.get("issue") or "", f.get("fix") or "", f.get("file") or "the PR",
                          p["head_sha"][:8], head[:8], (patch or "(no changes to this file)")[:30000],
                          now[:12000] or "-", ", ".join(others[:40]) or "none")
        cp = subprocess.run(["claude", "-p", "--output-format", "json", "--permission-mode", "dontAsk"] + C.CLAUDE_BARE
                            + _model() + _direct(), input=prompt, capture_output=True, text=True, timeout=300)
        try:
            ans = _last_object(json.loads(cp.stdout).get("result") or "", "state")
        except ValueError:
            ans = {}
        if ans.get("state") not in CHECK_STATES:
            raise ReviewError("Claude didn't answer: %s" % (cp.stderr or cp.stdout or "")[-300:].strip())
        out = {"state": ans["state"], "why": _text(ans.get("why"), "why", 600), "head": head, "at": C.now_iso()}
    rec = need(repo, number)
    find(rec, fid)["check"] = out
    store(rec)
    C.audit("review_check", {"pr": ref(repo, number), "finding": fid, "state": out["state"]})
    return out


FINDING_ABOUT = ("This is about one finding, %s: %s\nWhere: %s line %s\nIssue: %s\nSuggested fix: %s\nThe comment "
                 "drafted for the author: %s%s")
FINDING_RULE = ("If Lee says it isn't needed and the code agrees, say so in a sentence and drop it (\"status\": "
                "\"drop\"); LFG gives its points back. If you disagree, keep it and say plainly why it still matters "
                "and what has to change.")


# ---------------------------------------------------------------- code snippets

SNIP_AROUND = 4


def snippet(repo, number, fid):
    """The code a finding points at, like GitHub shows it: the diff hunk around the line when the PR changed it (old
    and new line numbers, added and removed lines), else the file at the reviewed commit. None for a finding with no
    file or line. Cached per file, commit and line, so a page shows it without asking GitHub again."""
    rec = need(repo, number)
    f = find(rec, fid)
    if not f.get("file") or not f.get("line"):
        return None
    p = next(x for x in rec["passes"] if f in x["findings"])
    now = (gh_status(repo, number) or {}).get("head_sha") or p["head_sha"]  # GitHub shows the PR's latest commit
    key = hashlib.sha1(("%s|%s|%s|%s|%s|%s" % (repo, rec.get("base"), p["head_sha"], now, f["file"], f["line"])
                        ).encode()).hexdigest()
    cache = os.path.join(reviews_dir(), "snippets", key + ".json")
    hit = C.read_json(cache)
    if hit:
        return hit
    head, line, changed = p["head_sha"], f["line"], False
    try:
        if now != head:  # follow the line through the commits since the review, to where GitHub has it now
            since = _file_patch(repo, head, now, f["file"])
            moved = map_line(since, line) if since else line
            if moved:
                head, line = now, moved
            else:
                changed = True  # the line itself changed: show it as it was reviewed
        rows = hunk_rows(_file_patch(repo, rec["base"], head, f["file"]) or "", line)
        if not rows:
            raw = _gh(["api", "-H", "Accept: application/vnd.github.raw",
                       "repos/%s/contents/%s?ref=%s" % (repo, f["file"], head)], timeout=60)
            if raw.returncode == 0:
                rows = file_rows(raw.stdout, line)
    except ReviewError:
        rows = None
    if not rows:
        return None
    out = {"file": f["file"], "line": line, "rows": rows, "head": head, "reviewed_line": f["line"],
           "reviewed_head": p["head_sha"], "changed_since": changed}
    C.write_json(cache, out)
    return out


def _file_patch(repo, a, b, path):
    files = gh_json(["api", "repos/%s/compare/%s...%s" % (repo, a, b)], timeout=120)
    return next((x.get("patch") for x in files.get("files") or [] if x.get("filename") == path), None)


def map_line(patch, line):
    """Where line `line` of the old side of a diff is on the new side, or None when that line was changed or
    removed. A file the diff doesn't touch keeps its numbers."""
    shift = 0
    old = new = 0
    for ln in patch.splitlines():
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", ln)
        if m:
            o, ol, n, nl = int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1)
            o, n = o + (ol == 0), n + (nl == 0)  # a hunk that only adds (or only removes) names the line before it
            if line < o:
                break
            if line >= o + ol:
                shift = (n + nl) - (o + ol)
                old = new = None
                continue
            old, new = o, n
            continue
        if old is None or not old and not new or ln.startswith("\\"):
            continue
        if ln[:1] == "+":
            new += 1
        elif ln[:1] == "-":
            if old == line:
                return None
            old += 1
        else:
            if old == line:
                return new
            old += 1
            new += 1
    return line + shift


def hunk_rows(patch, line, around=SNIP_AROUND):
    """Rows of the diff around new-file line `line`: {old, new, kind: " "|"+"|"-", text}. [] if no hunk shows it."""
    rows, old, new = [], 0, 0
    for ln in patch.splitlines():
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
        if m:
            old, new = int(m.group(1)), int(m.group(2))
            rows.append(None)  # a gap between hunks
            continue
        if ln.startswith("\\"):
            continue
        kind = ln[:1] if ln[:1] in "+-" else " "
        rows.append({"old": old if kind != "+" else None, "new": new if kind != "-" else None, "kind": kind,
                     "text": ln[1:]})
        old += kind != "+"
        new += kind != "-"
    at = next((i for i, r in enumerate(rows) if r and r["new"] == line), None)
    if at is None:
        return []
    lo, hi = at, at
    while lo > 0 and rows[lo - 1] and at - lo < around:
        lo -= 1
    while hi < len(rows) - 1 and rows[hi + 1] and hi - at < around:
        hi += 1
    return [dict(r, at=r["new"] == line) for r in rows[lo:hi + 1]]


def file_rows(text, line, around=SNIP_AROUND):
    lines = text.splitlines()
    lo, hi = max(1, line - around), min(len(lines), line + around)
    return [{"old": n, "new": n, "kind": " ", "text": lines[n - 1], "at": n == line} for n in range(lo, hi + 1)]


# ---------------------------------------------------------------- fixing your own PR

FIX_ALLOW = ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]
FIX_DENY = GH_WRITE_DENY + ["Bash(gh pr merge *)", "Bash(git push --force*)", "Bash(git push -f*)",
                            "Bash(git commit --amend*)", "Bash(git rebase *)", "Bash(git reset --hard*)"]
FIX = ("You are fixing findings from a review of %s (%s), Lee's own PR, in this checkout of its branch %s. Lee read "
       "each finding and chose these to fix:\n\n%s\n\nFix every one. Read AGENTS.md and CLAUDE.md first and follow "
       "the repo's conventions. Keep each fix to what the finding asks; no unrelated changes. Run the tests, lint and "
       "type checks that cover what you changed, and fix what you broke. Then commit: one commit for all of them, "
       "unless that would be too large to review as one (roughly 400 changed lines, or fixes that are clearly separate "
       "changes): then one commit per logical change, and say why in the note. Commit messages say what changed for a "
       "person; no Co-Authored-By line. Then `git push origin %s`. Never force-push, amend, rebase or merge. If a "
       "finding turns out to be wrong or can't be fixed safely, skip it and say why. You are running unattended: "
       "nobody can answer questions. End your last message with one ```json block: {\"fixed\": [ids], \"skipped\": "
       "[{\"id\": id, \"why\": text}], \"commits\": [full sha], \"note\": text}.")


def fix_job_path(repo, number):
    return job_path(repo, number)[:-5] + ".fix.json"


def fix_job(repo, number):
    j = C.read_json(fix_job_path(repo, number))
    if j and j.get("status") == "running" and not _alive(j.get("pid")):
        j["status"] = "failed"
        j["why"] = "the fix stopped without finishing"
    return j


def carried(rec):
    """Earlier findings the newest review followed up on and found still there (not fixed or withdrawn): they act
    like the newest review's own, so Fix can take them."""
    p = rec["passes"][-1]
    open_ids = [x["id"] for x in p.get("prior") or [] if x["state"] not in ("fixed", "withdrawn")]
    older = {f["id"]: f for q in rec["passes"][:-1] for f in q["findings"]}
    return [older[i] for i in open_ids if i in older]


def to_fix(rec):
    p = rec["passes"][-1]
    return [f for f in p["findings"] + carried(rec)
            if f["status"] == "keep" and not (f.get("fixed") or {}).get("commit")]


def fix_start(repo, number):
    """Start `lfg review fix` detached (the Fix button on your own PR)."""
    import subprocess
    import sys
    rec = need(repo, number)
    if rec.get("author") and rec["author"] != me():
        raise ReviewError("only your own PR can be fixed from here; on someone else's, post the comments")
    p = rec["passes"][-1]
    pending = undecided(p)
    if pending:
        raise ReviewError("decide fix or pass first: %s" % ", ".join(pending))
    if not to_fix(rec):
        raise ReviewError("nothing is marked fix")
    if (fix_job(repo, number) or {}).get("status") == "running":
        return {"started": False, "note": "A fix of %s is already running." % ref(repo, number)}
    args = [sys.executable, os.path.join(C.PLUGIN_ROOT, "bin", "lfg"), "review", "fix", ref(repo, number)]
    with open(os.devnull, "wb") as dn:
        subprocess.Popen(args, stdout=dn, stderr=dn, stdin=subprocess.DEVNULL, start_new_session=True,
                         close_fds=True)
    return {"started": True}


def fix_checkout(repo, branch):
    """A clean checkout of the PR's branch, up to date with GitHub: the worktree that already has it, else a new LFG
    worktree. Never the checkout you work in when it has changes."""
    from . import worktree as W
    root = local_checkout(repo)
    if not root:
        raise ReviewError("no checkout of %s on this machine to fix it in" % repo)
    git = lambda *a, cwd=root: C.run(["git", *a], cwd=cwd, timeout=300)  # noqa: E731
    if git("fetch", "origin", branch).returncode:
        raise ReviewError("couldn't fetch %s from GitHub" % branch)
    path = None
    for blk in git("worktree", "list", "--porcelain").stdout.split("\n\n"):
        if "branch refs/heads/%s\n" % branch in blk + "\n":
            path = blk.split("\n")[0][len("worktree "):]
    if path is None:
        if git("show-ref", "--verify", "--quiet", "refs/heads/" + branch).returncode:
            git("branch", "--track", branch, "origin/" + branch)
        try:
            path = W.new(root, branch)["path"]
        except (ValueError, RuntimeError) as e:
            raise ReviewError("couldn't check out %s: %s" % (branch, e)) from e
    if git("status", "--porcelain", cwd=path).stdout.strip():
        raise ReviewError("%s has uncommitted changes; commit or stash them first" % path)
    if git("merge", "--ff-only", "origin/" + branch, cwd=path).returncode:
        raise ReviewError("%s has commits GitHub doesn't, and GitHub has ones it doesn't; push or pull first" % path)
    return path


def fix_run(repo, number):
    """Fix the findings marked fix on your own PR with Claude Code, in a checkout of its branch: one commit (more only
    when one would be too big), pushed. Each fixed finding remembers the commit."""
    import subprocess
    rec = need(repo, number)
    p, todo = rec["passes"][-1], to_fix(rec)
    jp = fix_job_path(repo, number)
    log = jp[:-5] + ".log"
    j = {"repo": repo, "number": number, "status": "running", "pid": os.getpid(), "started": C.now_iso(), "log": log,
         "ids": [f["id"] for f in todo]}
    C.write_json(jp, j)
    try:
        if not todo:
            raise ReviewError("nothing is marked fix")
        if not C.which("claude"):
            raise ReviewError("Claude Code (`claude`) is not on PATH")
        cwd = fix_checkout(repo, rec["branch"])
        j["cwd"] = cwd
        C.write_json(jp, j)
        listing = "\n\n".join("%s (%s) %s%s\nIssue: %s\nFix: %s" % (
            f["id"], f["severity"], f.get("title") or "",
            " at %s:%s" % (f["file"], f.get("line") or "") if f.get("file") else "",
            f.get("issue") or "", f.get("fix") or "") for f in todo)
        prompt = FIX % (ref(repo, number), rec.get("title") or "", rec["branch"], listing, rec["branch"])
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            cp = subprocess.run(["claude", "-p", prompt, "--permission-mode", "dontAsk", "--output-format",
                                 "stream-json", "--verbose", "--allowedTools", ",".join(FIX_ALLOW),
                                 "--disallowedTools", ",".join(FIX_DENY)] + _model(),
                                cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        out = json_from_session(log, "fixed") or {}
        commits = [c for c in out.get("commits") or [] if isinstance(c, str) and re.match(r"^[0-9a-f]{7,40}$", c)]
        rec = need(repo, number)
        for fid in out.get("fixed") or []:
            try:
                find(rec, fid)["fixed"] = {"commit": commits[-1] if commits else "", "at": C.now_iso()}
            except ReviewError:
                continue
        p = rec["passes"][-1]
        p["fix"] = {"ended": C.now_iso(), "commits": commits, "note": str(out.get("note") or "")[:4000],
                    "skipped": [x for x in out.get("skipped") or [] if isinstance(x, dict)],
                    "session_id": session_id(log), "cwd": cwd, "used": SS.used(log)}
        store(rec)
        ok = bool(out.get("fixed")) and bool(commits)
        j.update(status="done" if ok else "failed", exit=cp.returncode, ended=C.now_iso(),
                 why="" if ok else "Claude finished without committing a fix: %s" % (
                     out.get("note") or "see the log")[:300])
    except ReviewError as e:
        j.update(status="failed", ended=C.now_iso(), why=str(e))
    C.write_json(jp, j)
    C.audit("review_fix", {"pr": ref(repo, number), "status": j["status"]})
    done = j["status"] == "done"
    n = sum(1 for f in need(repo, number)["passes"][-1]["findings"] if (f.get("fixed") or {}).get("commit"))
    notify(ref(repo, number), "Fix %s: %s" % ("pushed" if done else "failed", rec.get("title") or ref(repo, number)),
           "%d finding%s fixed and pushed" % (n, "" if n == 1 else "s") if done else j.get("why") or "see the log",
           ok=done, place="fix")
    return j


def activity(path, limit=400):
    """What a review run did, in order, from its log: what it said and each tool it used."""
    out = []
    for ln in C.read_text(path).splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant":
            continue
        for part in (ev.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and (part.get("text") or "").strip():
                out.append({"kind": "said", "text": part["text"].strip()[:4000]})
            elif part.get("type") == "tool_use":
                inp = part.get("input") or {}
                what = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("url") or ""
                out.append({"kind": "tool", "tool": part.get("name") or "", "text": str(what)[:400]})
    return out[-limit:]


# ---------------------------------------------------------------- links between reviews, and to sessions

def _links_path():
    return os.path.join(reviews_dir(), "links.json")


def _links():
    d = C.read_json(_links_path(), {}) or {}
    return {"prs": d.get("prs") or {}, "sessions": d.get("sessions") or {}}


def linked(pr):
    """PRs linked to this one: reviewed together, or linked by you. They can be in other repos."""
    return sorted(_links()["prs"].get(pr) or [])


def link(a, b, on=True):
    """Link two PRs' reviews (both ways), e.g. a backend and its frontend. Either can be in any repo."""
    a, b = ref(*parse_pr(a)), ref(*parse_pr(b))
    if a == b:
        raise ReviewError("a PR can't be linked to itself")
    d = _links()
    for x, y in ((a, b), (b, a)):
        cur = set(d["prs"].get(x) or [])
        cur = cur | {y} if on else cur - {y}
        if cur:
            d["prs"][x] = sorted(cur)
        else:
            d["prs"].pop(x, None)
    C.ensure_dir(reviews_dir())
    C.write_json(_links_path(), d)
    return {"pr": a, "linked": sorted(d["prs"].get(a) or [])}


def linked_sessions(pr):
    return list(_links()["sessions"].get(pr) or [])


def link_session(pr, sid, on=True):
    """Link a Claude Code session to a PR by hand, e.g. the session where you built it."""
    pr = ref(*parse_pr(pr))
    if not re.match(r"^[0-9a-f-]{36}$", str(sid or "")):
        raise ReviewError("not a session id: %r" % sid)
    d = _links()
    cur = [x for x in d["sessions"].get(pr) or [] if x != sid] + ([sid] if on else [])
    if cur:
        d["sessions"][pr] = cur
    else:
        d["sessions"].pop(pr, None)
    C.ensure_dir(reviews_dir())
    C.write_json(_links_path(), d)
    return {"pr": pr, "sessions": cur}


# ---------------------------------------------------------------- getting a review's JSON out of a session

def find_review_json(text, key="findings"):
    """The last review JSON ({..."findings": [...]}) in some text: a ```json block, a heredoc given to
    `lfg review save`, or a bare object. key="reviews" finds a review of several PRs instead. None if there is none."""
    dec, best = json.JSONDecoder(), None
    for m in re.finditer(r"\{", text or ""):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get(key), list):
            best = obj
    return best


def _session_texts(path):
    """What an agent said and the commands it ran, newest last, from a Claude Code transcript or a stream-json
    log (same event shapes)."""
    out = []
    for ln in C.read_text(path).splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "result" and isinstance(ev.get("result"), str):
            out.append(ev["result"])
        if ev.get("type") != "assistant":
            continue
        for part in (ev.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                out.append(part.get("text") or "")
            elif part.get("type") == "tool_use":
                inp = part.get("input") or {}
                out.append(str(inp.get("command") or inp.get("content") or ""))
    return out


def json_from_session(path, key="findings"):
    for t in reversed(_session_texts(path)):
        found = find_review_json(t, key)
        if found:
            return found
    return None


def _save_from_log(repo, number, log, ticket, many=False):
    """After an unattended run: save the JSON it ended with (or tried to save). many: a review of several PRs, where
    this PR's entry is picked out of {"reviews": [{"pr": ...}]}. Returns why not, or ""."""
    if many:
        want = ref(repo, number).lower()
        data = next((x for x in (json_from_session(log, "reviews") or {}).get("reviews") or []
                     if isinstance(x, dict) and str(x.get("pr") or "").lower().endswith(want)), None)
    else:
        data = json_from_session(log)
    if not data:
        return "Claude finished without a review of this PR to save; see the log"
    data.setdefault("reviewer", me())
    try:
        save(repo, number, data, ticket=ticket)
    except ReviewError as e:
        return "The review Claude wrote didn't fit the format (%s); see the log" % e
    return ""


SESSION_DIR = os.path.join(C.HOME, ".claude", "projects")


def _mentions(repo, number):
    name = repo.split("/")[-1]
    return [s.encode() for s in ("%s#%d" % (repo, number), "%s/pull/%d" % (repo, number), "%s#%d" % (name, number),
                                 "pr diff %d -R %s" % (number, repo), "pr view %d -R %s" % (number, repo),
                                 "review %d" % number)]


def mentions(raw, repo, number):
    """True if a transcript's bytes mention this PR. "review 12" alone is too loose: it also needs the repo's name."""
    keys = _mentions(repo, number)
    hits = [k for k in keys if k in raw]
    return bool(hits) and not (hits == [keys[-1]] and repo.split("/")[-1].encode() not in raw)


_SESS_SEEN = {}  # (transcript, size, mtime, repo, number) -> its row when it mentions the PR, else None
_SESS_INDEX = {}  # transcript -> [size, mtime, PR numbers it could mention]
PR_NUMBER_RX = re.compile(rb"(?:#|/pull/|pr diff |pr view |review )(\d+)")  # every place mentions() looks


def _index_path():
    return C.lfg_path("reviews", "session-index.json")


def session_index(days=30):
    """Which PR numbers each recent transcript could mention, read once per transcript version (a gigabyte of
    transcripts took a second or two to search on every new PR page). Kept on disk so a restart starts warm."""
    if not _SESS_INDEX:
        _SESS_INDEX.update(C.read_json(_index_path(), {}) or {})
    cut, live, changed = time.time() - days * 86400, set(), False
    for p in glob.glob(os.path.join(SESSION_DIR, "*", "*.jsonl")):
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_mtime < cut:
            continue
        live.add(p)
        hit = _SESS_INDEX.get(p)
        if not hit or hit[0] != st.st_size or hit[1] != st.st_mtime:
            try:
                with open(p, "rb") as fh:
                    nums = sorted({int(m) for m in PR_NUMBER_RX.findall(fh.read()) if len(m) < 8})
            except OSError:
                continue
            _SESS_INDEX[p], changed = [st.st_size, st.st_mtime, nums], True
    for p in [p for p in _SESS_INDEX if p not in live]:
        del _SESS_INDEX[p]
        changed = True
    if changed:
        try:
            C.write_json(_index_path(), _SESS_INDEX)
        except OSError:
            pass
    return _SESS_INDEX


_SESS_LAST, _SESS_LOOKING = {}, set()  # (repo, number) -> the last sessions_for answer; being looked for now


def sessions_soon(repo, number):
    """sessions_for without waiting: the last answer for this PR (None if there is none yet), looked for again in
    the background, so a PR page opens at once and picks up new sessions on its next refresh."""
    import threading
    key = (repo, int(number))

    def look():
        try:
            _SESS_LAST[key] = sessions_for(repo, number)
        finally:
            _SESS_LOOKING.discard(key)
    if key not in _SESS_LOOKING:
        _SESS_LOOKING.add(key)
        threading.Thread(target=look, daemon=True).start()
    return _SESS_LAST.get(key)


def sessions_for(repo, number, days=30):
    """Your Claude Code sessions from the last `days` that mention this PR, newest first. Only transcripts the index
    says name this PR's number are read, and each only again once it changes."""
    out = []
    for p, (size, mtime, nums) in list(session_index(days).items()):
        if int(number) not in nums:
            continue
        key = (p, size, mtime, repo, number)
        if key not in _SESS_SEEN:
            _SESS_SEEN[key] = _session_row(p, repo, number)
        if _SESS_SEEN[key]:
            out.append(_SESS_SEEN[key])
    rec = load(repo, number) or {}  # the review chat's own copies and sessions aren't sessions to ask about
    mine = set((rec.get("session_forks") or {}).values()) | {rec.get("chat_session")}
    out = sorted((x for x in out if x["id"] not in mine), key=lambda s: s["modified"], reverse=True)
    _SESS_LAST[(repo, int(number))] = out
    return out


def _session_row(p, repo, number):
    try:
        with open(p, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if not mentions(raw, repo, number):
        return None
    title, cwd, first = "", "", ""
    for ln in raw.splitlines():
        if b'"custom-title"' in ln or b'"cwd"' in ln or (not first and b'"type":"user"' in ln):
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if ev.get("type") == "custom-title":
                title = ev.get("customTitle") or title
            cwd = cwd or ev.get("cwd") or ""
            c = (ev.get("message") or {}).get("content") if ev.get("type") == "user" else None
            c = re.sub(r"\s+", " ", re.sub(r"</?pasted_content[^>]*>|<lfg-review\b[^>]*>[\s\S]*?</lfg-review>", " ", c)
                       ).strip() if isinstance(c, str) else c
            if not first and isinstance(c, str) and not c.startswith("<"):  # a paste's wrapper isn't a name
                first = c
    return {"path": p, "id": os.path.basename(p)[:-6], "title": title or first[:80] or "(untitled)",
            "cwd": cwd, "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(p))),
            "has_json": bool(json_from_session(p))}


ASK_SESSION = ("Lee is reviewing pull request %s from the LFG dashboard and asks you about it. You worked on this, so "
               "answer from what you know and from the code: a few plain sentences he could hand to the reviewer as "
               "they are. Don't change any files, commit or push, and don't change the review. "
               "The page has its own buttons to save a decision (to this repo's dev-graph, or to Lee's second-brain): "
               "never ask whether to save or remember something, and don't offer to.\n\n%s")


CONVERT = ("Below is a code review someone did in a Claude Code session. Turn it into this JSON and reply with only "
           "the JSON in one ```json block. Keep every finding the review settled on, with its wording; leave out "
           "ones it dropped or withdrew. Use null where the review doesn't say.\n\n%s\n\nThe review:\n\n%s")
SHAPE = ('{"summary": "...", "score": 0-100 or null, "verdict": "mergeable|almost|not", "verdict_why": "one line", '
         '"approach_notes": [], "findings": [{"title": "...", '
         '"severity": "blocker|major|minor|nitpick|note", "file": "path or null", "line": int or null, '
         '"issue": "one line", "fix": "one line", "detail": "evidence, not posted", "body": "the comment the author '
         'reads", "origin": "introduced|exposed|pre-existing", "since": "first"}]}')


def import_session(repo, number, path, ticket=None, convert=True):
    """Save a review you did in an ordinary Claude Code session. Uses the JSON if the session has one; otherwise
    asks Claude, with no tools, to turn the session's review into it (one short call on your login)."""
    import subprocess
    if not (os.path.isfile(path) and os.path.realpath(path).startswith(os.path.realpath(SESSION_DIR) + os.sep)
            or path.endswith(".log") and os.path.realpath(path).startswith(os.path.realpath(reviews_dir()))):
        raise ReviewError("not a Claude Code session or a review log: %s" % path)
    data = json_from_session(path)
    if not data:
        if not convert:
            raise ReviewError("that session has no review JSON")
        if not C.which("claude"):
            raise ReviewError("Claude Code (`claude`) is not on PATH")
        said = "\n\n".join(t for t in _session_texts(path) if t.strip())[-60000:]
        cp = subprocess.run(["claude", "-p", "--output-format", "json", "--permission-mode", "dontAsk"] + C.CLAUDE_BARE
                            + _model(), input=CONVERT % (SHAPE, said), capture_output=True, text=True, timeout=600)
        try:
            data = find_review_json(json.loads(cp.stdout).get("result") or "")
        except ValueError:
            data = None
        if not data:
            raise ReviewError("couldn't find a review in that session")
    data.setdefault("reviewer", me())
    rec = save(repo, number, data, ticket=ticket)
    rec["passes"][-1]["imported_from"] = path
    store(rec)
    j = job(repo, number)
    if j and j.get("status") == "failed":  # the run's review is saved now, so stop showing it as failed
        j.update(status="done", why="")
        C.write_json(job_path(repo, number), j)
    return rec


def progress(repo, number, lines=400, j=None):
    """The last few things a running review (or fix: pass its job) did, in words, from its stream-json log."""
    j = j or job(repo, number)
    if not j:
        return None
    steps = []
    for ln in C.read_text(j.get("log") or "").splitlines()[-400:]:
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        for part in ((ev.get("message") or {}).get("content") or []) if ev.get("type") == "assistant" else []:
            if part.get("type") == "tool_use":
                inp = part.get("input") or {}
                what = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                if inp.get("offset"):
                    what = "%s (from line %s)" % (what, inp["offset"])
                step = "%s %s" % (part.get("name"), str(what)[:160])
                m = re.match(r"^(.*?)(?: ×(\d+))?$", steps[-1]) if steps else None
                if m and m.group(1) == step:  # the same step again: count it rather than list it twice
                    steps[-1] = "%s ×%d" % (step, int(m.group(2) or 1) + 1)
                else:
                    steps.append(step)
        if ev.get("type") == "result":
            steps.append("finished: %s" % str(ev.get("result") or ev.get("subtype") or "")[:300])
    return dict(j, steps=steps[-lines:])


def score_stats(only=None):
    """How PRs score, per PR, per author and per repo. A PR's first score is its first review's (the code as it was
    first handed in); later reviews usually score higher after fixes, so they're shown apart: the latest score, the
    change, and how many reviews it took before you approved it. Full reviews and re-reviews are averaged apart."""
    names = github_names(only) if only else set()
    prs = []
    for r in all_records():
        if names and r["repo"].lower() not in names:
            continue
        ps = [p for p in r.get("passes") or [] if p.get("score") is not None]
        if not ps:
            continue
        approved = next((p["n"] for p in r["passes"] if (p.get("posted") or {}).get("event") == "APPROVE"), None)
        prs.append({"repo": r["repo"], "number": r["number"], "title": r.get("title") or "", "author": r.get("author")
                    or "?", "first": ps[0].get("score_at_review", ps[0]["score"]), "latest": ps[-1]["score"],
                    "reviews": len(r["passes"]),
                    "approved_after": approved, "verdict": verdict_of(r["passes"][-1]), "scores": scores(r),
                    "updated": r.get("updated") or ps[-1].get("ts"), "first_at": ps[0].get("ts") or ""})

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 1) if xs else None

    def group(key):
        out = {}
        for x in prs:
            out.setdefault(x[key], []).append(x)
        rows = []
        for k, xs in out.items():
            ok = [x["approved_after"] for x in xs if x["approved_after"]]
            rows.append({"name": k, "prs": len(xs), "first": avg(x["first"] for x in xs),
                         "latest": avg(x["latest"] for x in xs), "gain": avg(x["latest"] - x["first"] for x in xs),
                         "approved": len(ok), "to_approval": avg(ok),
                         "first_time": sum(1 for a in ok if a == 1)})
        return sorted(rows, key=lambda r: (-r["prs"], r["name"]))
    kinds = {}
    for r in all_records():
        if names and r["repo"].lower() not in names:
            continue
        for p in r.get("passes") or []:
            if p.get("score") is not None:
                kinds.setdefault("re-review" if (p.get("kind") or "first") == "re-review" else "full", []).append(
                    p["score"])
    return {"prs": sorted(prs, key=lambda x: x["updated"] or "", reverse=True), "authors": group("author"),
            "repos": group("repo"), "kinds": {k: {"reviews": len(v), "avg": avg(v)} for k, v in kinds.items()},
            "overall": {"prs": len(prs), "first": avg(x["first"] for x in prs), "latest": avg(x["latest"] for x in prs),
                        "to_approval": avg(x["approved_after"] for x in prs if x["approved_after"])}}


def dashboard(fresh=False, only=None):
    """Everything the Reviews page shows: the request queue, your own open PRs, saved reviews, and running jobs.
    `only`: a main checkout; keeps the PRs in its GitHub repos (all of them when it has no GitHub remote, with
    `no_remote` set)."""
    import concurrent.futures
    lists = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {w: pool.submit(queue, 0 if fresh else 120, w) for w in SEARCHES}
    for w, j in jobs.items():
        try:
            lists[w] = (j.result(), "")
        except ReviewError as e:
            lists[w] = ([], str(e))
    (q, qwhy), (mine, mwhy) = lists["requested"], lists["mine"]
    yours = {(x["repo"], x["number"]) for x in mine}
    q = [x for x in q if (x["repo"], x["number"]) not in yours]
    every = recs = all_records()
    names = github_names(only) if only else set()
    others = [dict(x) for x in q + mine if names and x["repo"].lower() not in names]
    if names:
        q = [x for x in q if x["repo"].lower() in names]
        mine = [x for x in mine if x["repo"].lower() in names]
        recs = [r for r in recs if r["repo"].lower() in names]
    q, mine = [dict(x) for x in q], [dict(x) for x in mine]  # the cached lists are shared by every filter
    have = {(r["repo"], r["number"]): r for r in recs}
    for x in q + mine:
        r = have.get((x["repo"], x["number"]))
        x["passes"] = len(r["passes"]) if r else 0
        x["job"] = job(x["repo"], x["number"])
        if r:  # the latest review, so the open lists say where each PR stands too
            p = r["passes"][-1]
            x.update(score=p.get("score"), scores=scores(r), verdict=verdict_of(p), posted=p.get("posted"),
                     reviewed=p.get("ts"), tally={s: sum(f["status"] == s for f in p["findings"])
                                                  for s in ("pending", "keep", "drop")})
    want = {(x["repo"], x["number"]) for x in q + mine + others}
    want |= {(r["repo"], r["number"]) for r in recs if r.get("state") == "OPEN"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        # Refresh asks GitHub again; otherwise a minute old at most, so a PR merged on GitHub drops off soon
        st = dict(zip(want, pool.map(lambda k: gh_status(*k, max_age=0 if fresh else 60), want)))
    for r in recs:  # remember a PR that was merged or closed, so it counts as done even when GitHub isn't asked
        g = st.get((r["repo"], r["number"])) or {}
        if g.get("state") in ("MERGED", "CLOSED") and r.get("state") in (None, "OPEN"):
            rec = load(r["repo"], r["number"])
            if rec:
                rec["state"] = r["state"] = g["state"]
                C.write_json(record_path(r["repo"], r["number"]), rec)  # not store(): its place in the list stays
    for x in q + mine:
        x["gh"] = st.get((x["repo"], x["number"]))
        x["ticket"] = ticket_of(x["title"], "", (x["gh"] or {}).get("branch")) or x.get("ticket") or ""
    for x in others:
        x["ticket"] = ticket_of(x["title"], "", (st.get((x["repo"], x["number"])) or {}).get("branch")) \
            or x.get("ticket") or ""
    out = []
    for r in recs:
        p = r["passes"][-1]
        tally = {}
        for f in p["findings"]:
            tally[f["status"]] = tally.get(f["status"], 0) + 1
        out.append({"repo": r["repo"], "number": r["number"], "title": r.get("title"), "author": r.get("author"),
                    "url": r.get("url"), "ticket": r.get("ticket") or ticket_of(r.get("title"), "", r.get("branch")),
                    "open": r.get("state") in (None, "OPEN"), "passes": len(r["passes"]),
                    "score": p.get("score"), "scores": scores(r), "verdict": verdict_of(p),
                    "posted": p.get("posted"), "tally": tally, "updated": r.get("updated"),
                    "job": job(r["repo"], r["number"]), "gh": st.get((r["repo"], r["number"]))})
    links = _links()["prs"]  # linked PRs show on every row, whichever repo they are in
    for x in q + mine + out:
        x["linked"] = links.get(ref(x["repo"], x["number"])) or []
    if names:
        near = {y for x in out for y in x["linked"]}
        for r in every:
            if ref(r["repo"], r["number"]) in near and r["repo"].lower() not in names:
                p, n = r["passes"][-1], ref(r["repo"], r["number"])
                tally = {s: sum(f["status"] == s for f in p["findings"]) for s in ("pending", "keep", "drop")}
                out.append({"repo": r["repo"], "number": r["number"], "title": r.get("title"),
                            "author": r.get("author"), "url": r.get("url"), "ticket": r.get("ticket") or "",
                            "open": r.get("state") in (None, "OPEN"), "passes": len(r["passes"]),
                            "score": p.get("score"), "scores": scores(r), "verdict": verdict_of(p),
                            "posted": p.get("posted"),
                            "tally": tally, "updated": r.get("updated"), "job": job(r["repo"], r["number"]), "gh": None,
                            "linked": links.get(n) or [], "other_repo": True})
    # a ticket's PRs in the repos not picked top left: its group shows all of them
    shown = {x.get("ticket") for x in q + mine + out} - {"", None}
    more = [dict(x, passes=0, job=job(x["repo"], x["number"])) for x in others if x["ticket"] in shown]
    kept = [x for x in passes_list() if not names or x["scope"] == "all" or x["repo"].lower() in names]
    return {"passed": kept, "ticket_more": more, "queue": q, "queue_why": qwhy, "mine": mine, "mine_why": mwhy,
            "reviews": out, "no_remote": bool(only) and not names}
