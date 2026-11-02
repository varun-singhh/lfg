"""The Knowledge page: what's saved, with a repo, a feature and a topic on each item, searchable and askable.

dev-graph's Decisions and Learnings have no repo or feature of their own. LFG fills them in from what the graph does
link: a decision or lesson's ticket (Issue) gives the repo (the repo your sessions about that ticket ran in) and its
epic gives the feature. Your own tags, kept in ~/.lfg/state/knowledge-tags.json, always win over a guess. The graph
itself is never changed here.

Topics sort lessons by what they're about. The graph's own kinds (incident review, retro, gotcha, hindsight) are kept;
"setup" (how to run, deploy or access things) is LFG's, stored as a tag.
"""
import json
import os
import re
import subprocess

from . import common as C

TOPICS = {"setup": "Setup and environment", "gotcha": "Gotcha", "incident_review": "Incident review",
          "retro": "Retro", "hindsight": "Hindsight"}
SETUP_WORDS = re.compile(r"\b(local(ly)?|run(ning)? (it|the)|install|env(ironment)?|docker|gcloud|impersonat|"
                         r"service account|credential|port \d+|setup|set up|deploy|ssh|vpn|login|cli)\b", re.I)


def _tags_path():
    return C.lfg_path("state", "knowledge-tags.json")


def tags():
    return dict(C.read_json(_tags_path(), {}) or {})


def set_tags(slug, repo=None, feature=None, topic=None):
    """Your repo / feature / topic for one item. None leaves a field alone, "" clears it back to the guess."""
    if not re.match(r"^[\w.-]{1,160}$", str(slug or "")):
        raise ValueError("not a knowledge item: %r" % slug)
    if topic not in (None, "") and topic not in TOPICS:
        raise ValueError("topic is one of %s" % ", ".join(TOPICS))
    t = tags()
    cur = dict(t.get(slug) or {})
    for k, v in (("repo", repo), ("feature", feature), ("topic", topic)):
        if v is None:
            continue
        v = re.sub(r"\s+", " ", str(v)).strip()[:80]
        if v:
            cur[k] = v
        else:
            cur.pop(k, None)
    if cur:
        t[slug] = cur
    else:
        t.pop(slug, None)
    C.ensure_dir(os.path.dirname(_tags_path()))
    C.write_json(_tags_path(), t)
    return {"slug": slug, **cur}


def _read(q, name):
    from . import omnigraph as OG
    try:
        return OG.read("dev-graph", q, name)
    except Exception:  # noqa: BLE001 - a missing edge type or a down server just means no guesses
        return []


def _links():
    """slug -> ticket ids, slug -> epic titles, from the graph's edges. Columns are aliased: the server drops the
    variable prefix, so two `slug` columns would overwrite each other."""
    tickets, epics = {}, {}
    for r in _read("query a() { match { $d: Decision\n $d decisionEmergedFromIssue $i } "
                   "return { $d.slug as src, $i.slug as iss, $i.legacyRef as ref } limit 2000 }", "a"):
        tickets.setdefault(r["src"], set()).add(r.get("ref") or r["iss"])
    epic_of_ticket = {}
    for r in _read("query b() { match { $e: Epic\n $e epicContainsIssue $i } "
                   "return { $e.title as epic, $i.slug as iss, $i.legacyRef as ref } limit 2000 }", "b"):
        epic_of_ticket[_norm(r.get("ref") or r["iss"])] = r["epic"]
    for slug, ts in tickets.items():
        epics[slug] = {epic_of_ticket[_norm(t)] for t in ts if _norm(t) in epic_of_ticket}
    for r in _read("query c() { match { $l: Learning\n $l learningFromEpic $e } "
                   "return { $l.slug as src, $e.title as epic } limit 2000 }", "c"):
        epics.setdefault(r["src"], set()).add(r["epic"])
    for r in _read("query d() { match { $l: Learning\n $l learningReferencesDecision $d } "
                   "return { $l.slug as src, $d.slug as dec } limit 2000 }", "d"):
        tickets.setdefault(r["src"], set()).update(tickets.get(r["dec"], set()))
        epics.setdefault(r["src"], set()).update(epics.get(r["dec"], set()))
    return tickets, epics


def _repo_of_ticket():
    """Ticket -> the repo your sessions about it ran in most."""
    from . import sessions as SS
    count = {}
    for s in SS.listing(hidden=True)["sessions"]:
        if s.get("ticket") and s.get("repo") and s.get("root"):
            c = count.setdefault(s["ticket"].upper(), {})
            c[s["repo"]] = c.get(s["repo"], 0) + 1
    return {t: max(c, key=c.get) for t, c in count.items()}


def _norm(t):
    t = str(t or "").upper()
    m = re.match(r"^ISS-([A-Z][A-Z0-9]*-\d+)$", t)
    return m.group(1) if m else t


def enrich(decisions, learnings):
    """Add repo, feature, topic and tickets to each item; `guessed` lists the fields LFG filled in itself."""
    tickets, epics = _links()
    repo_of = _repo_of_ticket()
    mine = tags()
    for kind, rows in (("decision", decisions), ("learning", learnings)):
        for r in rows:
            slug = r.get("slug")
            ts = sorted({_norm(t) for t in tickets.get(slug, set())})
            repos = [repo_of[t] for t in ts if t in repo_of]
            guess = {"repo": max(set(repos), key=repos.count) if repos else "",
                     "feature": sorted(epics.get(slug, set()))[0] if epics.get(slug) else ""}
            if kind == "learning":
                text = "%s %s" % (r.get("title") or "", r.get("body") or "")
                guess["topic"] = "setup" if SETUP_WORDS.search(text) else (r.get("learningKind") or "")
            r["_guess"] = guess
            r.update(kind=kind, tickets=ts)
    # an item with no repo of its own takes the one most of its feature's items have
    by_feature = {}
    for r in decisions + learnings:
        g = r["_guess"]
        if g["feature"] and g["repo"]:
            by_feature.setdefault(g["feature"], []).append(g["repo"])
    for r in decisions + learnings:
        g, own = r.pop("_guess"), mine.get(r.get("slug"), {})
        if not g["repo"] and by_feature.get(g["feature"]):
            rs = by_feature[g["feature"]]
            g["repo"] = max(set(rs), key=rs.count)
        r.update(guessed=[k for k in g if g[k] and k not in own],
                 **{k: own.get(k, g.get(k, "")) for k in ("repo", "feature", "topic")})
    return decisions, learnings


ASK = ("Answer the question from these saved decisions, lessons and notes only. Reply with JSON only: "
       '{"answer": "two or three plain sentences, or \\"Nothing saved covers this.\\"", "slugs": ["the slugs you '
       'used, most relevant first"]}.\n\nQuestion: %s\n\nSaved items (one per line, slug | kind | repo | feature | '
       "title | text):\n%s")


def ask(question, items):
    """One tool-less Claude call over everything saved. Returns the answer and which items it drew on."""
    q = str(question or "").strip()
    if not q:
        raise ValueError("ask a question, e.g. \"how do we deploy to prod?\"")
    if not C.which("claude"):
        raise ValueError("Claude Code (`claude`) is not on PATH")
    lines = ["%s | %s | %s | %s | %s | %s" % (i.get("slug"), i.get("kind"), i.get("repo") or "-",
                                              i.get("feature") or "-", i.get("title") or i.get("name") or "",
                                              re.sub(r"\s+", " ", str(i.get("text") or ""))[:600]) for i in items]
    cp = subprocess.run(["claude", "-p", "--output-format", "json", "--permission-mode", "dontAsk"] + C.CLAUDE_BARE,
                        input=ASK % (q[:1000], "\n".join(lines)[:150000]), capture_output=True, text=True,
                        timeout=300)
    try:
        text = json.loads(cp.stdout).get("result") or ""
        m = re.search(r"\{.*\}", text, re.S)
        out = json.loads(m.group(0)) if m else {}
    except ValueError:
        out = {}
    if not out.get("answer"):
        raise ValueError("Claude didn't answer: %s" % (cp.stderr or cp.stdout or "")[-300:].strip())
    known = {i.get("slug") for i in items}
    return {"answer": str(out["answer"]), "slugs": [s for s in out.get("slugs") or [] if s in known]}


def _slug(prefix, title):
    import hashlib
    import time as _t
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "item"
    return "%s-%s-%s" % (prefix, base, hashlib.sha1(("%s%f" % (title, _t.time())).encode()).hexdigest()[:5])


def add(kind, title, text, repo="", feature="", topic="", root=None):
    """Save a decision or lesson to dev-graph, or a note to second-brain, from the dashboard (you typed it). Repo,
    feature and topic go into LFG's tags. With `root` (a checkout of the repo) a decision or lesson goes to that
    checkout's own dev-graph branch, the one its sessions read and `lfg knowledge sync` shares; without it, to main."""
    from . import omnigraph as OG
    title, text = re.sub(r"\s+", " ", str(title or "")).strip()[:200], str(text or "").strip()[:8000]
    if not title or not text:
        raise ValueError("give it a short title and the text itself")
    from .settings import _secret_kinds
    if _secret_kinds(title + "\n" + text):
        raise ValueError("that looks like it contains a secret; not saved")
    today, now = C.now_iso()[:10], C.now_iso()
    branch = None
    if root and kind in ("decision", "learning"):
        from . import teamknowledge as K
        K.ensure_locked(root)  # the branch exists before the first write
        branch = K.branch_for(root)
    if kind == "decision":
        slug = _slug("dec", title)
        OG.mutate("dev-graph", "query a($slug: String, $title: String, $decision: String, $at: Date) { insert Decision "
                  "{ slug: $slug, title: $title, decision: $decision, status: \"accepted\", createdAt: $at, "
                  "createdBy: \"lfg-dashboard\" } }", "a",
                  {"slug": slug, "title": title, "decision": text, "at": today}, branch=branch)
    elif kind == "learning":
        slug = _slug("lrn", title)
        lk = topic if topic in ("incident_review", "retro", "gotcha", "hindsight") else "gotcha"
        OG.mutate("dev-graph", "query a($slug: String, $title: String, $body: String, $kind: String, $at: Date) "
                  "{ insert Learning { slug: $slug, title: $title, body: $body, learningKind: $kind, "
                  "createdAt: $at, createdBy: \"lfg-dashboard\" } }", "a",
                  {"slug": slug, "title": title, "body": text, "kind": lk, "at": today}, branch=branch)
    elif kind == "note":
        slug = _slug("nt", title)
        OG.mutate("second-brain", "query a($slug: String, $name: String, $content: String, $now: DateTime) { insert "
                  "Note { slug: $slug, name: $name, kind: \"insight\", content: $content, createdAt: $now, "
                  "updatedAt: $now } }", "a", {"slug": slug, "name": title, "content": text, "now": now})
        return {"slug": slug, "saved_to": "second-brain"}
    else:
        raise ValueError("kind is decision, learning or note")
    if repo or feature or topic == "setup":
        set_tags(slug, repo=repo or None, feature=feature or None, topic="setup" if topic == "setup" else None)
    return {"slug": slug, "saved_to": "dev-graph"}
