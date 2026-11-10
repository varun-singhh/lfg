""""Where you left off": what Lee was last working on (epics, milestones, big tickets) and a briefing for each, built
from what LFG already has: dev-graph's copy of Linear, every session's ticket, and the saved reviews. Never writes to
Linear and never invents a number: what cannot be worked out is left out and says why."""
import datetime
import json
import re
import subprocess
import threading
import time

from . import common as C
from . import dash
from . import sessions as SS
from . import stacks

ACTIVE_DAYS = 14             # sessions older than this don't make an entry
MAX_ENTRIES = 30
DONE_DROP_DAYS = 3           # an epic with every ticket done drops off after this many quiet days
WORKING_MINUTES = 10         # a transcript changed this recently counts as working
IDLE_PR_MINUTES = 60         # a worker with an open PR idle this long needs you
SUMMARY_MIN_GAP_MINUTES = 10  # the written summary is made at most this often per entry
PROGRESS_TTL_SECONDS = 120   # stored progress older than this is shown at once and refreshed behind it
SUMMARY_MODEL = "claude-sonnet-5-5"  # the written summary always runs on Sonnet, never Opus


def tree(graph, epic):
    """The epic's tickets two levels deep: {"key", "title", "milestones": [{"key", "title", "leaves": [key]}],
    "loose": [key]}. A milestone is a child that has children of its own; the other children are loose tickets."""
    groups, issues = graph.get("groups") or {}, graph.get("issues") or {}

    def title(k):
        return (groups.get(k) or {}).get("title") or (issues.get(k) or {}).get("title") or ""

    def num(k):
        tail = k.rsplit("-", 1)[-1]
        return (k.rsplit("-", 1)[0], int(tail) if tail.isdigit() else 0)
    top = sorted((groups.get(epic) or {}).get("members") or (), key=num)
    milestones = [{"key": k, "title": title(k), "leaves": sorted(groups[k]["members"], key=num)}
                  for k in top if (groups.get(k) or {}).get("members")]
    return {"key": epic, "title": title(epic), "milestones": milestones,
            "loose": [k for k in top if not (groups.get(k) or {}).get("members")]}


def tickets_in(row):
    """Every ticket id in the session's branch, title and first message."""
    return SS._tickets_in(row.get("title"), row.get("ai_title"), row.get("first"), branch=row.get("branch"))


def role_of(row, epic_tree, followed):
    """"orchestrator", "worker" or "unsorted" for a session, against one epic. `followed`: the tickets that the
    session's group follows. Orchestrator when, in this order: its group follows the epic's ticket; it names the
    epic's ticket; it names three or more of the epic's tickets. Else a worker when it names one of them. Else
    unsorted: no guessing."""
    epic = epic_tree["key"]
    mine = {k for m in epic_tree["milestones"] for k in [m["key"]] + m["leaves"]} | set(epic_tree["loose"])
    named = tickets_in(row)
    if epic in (followed or ()) or epic in named or len(named & mine) >= 3:
        return "orchestrator"
    return "worker" if (named | set(followed or ())) & mine else "unsorted"


# ---------------------------------------------------------------- reading the sources

def _epoch(stamp):
    try:
        return time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return 0.0


def merge_graphs(graphs):
    """One graph from several repos' copies: the same ticket id seen from two repos is one ticket (the later copy
    wins the title and status, except that a terminal status in any copy stands)."""
    out = {"issues": {}, "groups": {}, "blocks": set(), "errors": [], "synced_at": ""}
    for g in graphs:
        for k, i in (g.get("issues") or {}).items():
            had = out["issues"].get(k)
            out["issues"][k] = dict(i, status=had["status"] if had and had["status"] in stacks.TERMINAL
                                    and i.get("status") not in stacks.TERMINAL else i.get("status"))
        for k, grp in (g.get("groups") or {}).items():
            had = out["groups"].setdefault(k, dict(grp, members=set()))
            had["members"] |= set(grp.get("members") or ())
            had["title"] = had.get("title") or grp.get("title") or ""
            if grp.get("kind") == "epic":
                had["kind"] = "epic"
        out["blocks"] |= {tuple(b) for b in g.get("blocks") or ()}
        out["errors"] += g.get("errors") or []
        out["synced_at"] = max(out["synced_at"], g.get("synced_at") or "")
    out["blocks"] = sorted(out["blocks"])
    return out


def _merged_graph(rids=None):
    """dev-graph's copy of Linear for the repos in `rids` (all repos when None), merged. A repo whose copy cannot
    be read adds a plain reason to `errors` instead of raising."""
    graphs = []
    for r in dash.repos()["repos"]:
        if rids is not None and r["id"] not in rids:
            continue
        try:
            g = dict(stacks._graph(r["id"]), synced_at=r.get("synced_at") or "")
        except Exception as e:  # dev-graph down or not set up for this repo: the page still works without it
            g = {"errors": ["dev-graph for %s: %s" % (r["name"], e)]}
        graphs.append(g)
    return merge_graphs(graphs)


def _prs_by_ticket():
    """({ticket: its PR}, [notes]) across every repo with a GitHub remote, one repo's PR list at a time (cached by
    `stacks`). A repo whose PRs cannot be read adds a note; it never raises."""
    out, notes = {}, []
    rank = {"merged_main": 0, "open": 1, "approved": 1, "changes": 1, "draft": 1, "merged_parent": 2, "closed": 3}
    for r in dash.repos()["repos"]:
        gh = stacks._origin(r["root"])
        if not gh:
            notes.append("%s has no GitHub remote" % r["name"])
            continue
        try:
            prs = stacks._pr_for(stacks._pr_rows(gh), stacks._default_branch(gh, r["root"]))
        except Exception as e:
            notes.append("PRs of %s could not be read: %s" % (r["name"], e))
            continue
        for t, pr in prs.items():
            if t not in out or rank.get(pr["state"], 9) < rank.get(out[t]["state"], 9):
                out[t] = dict(pr, repo=r["name"], gh_repo=gh)
    return out, notes


def _epic_of(graph, ticket):
    """The top of the tree holding `ticket` in dev-graph (leaf, then milestone, then epic); the ticket itself when
    nothing holds it."""
    groups, seen = graph.get("groups") or {}, set()
    t = ticket
    while t not in seen:
        seen.add(t)
        holding = sorted((g for g in groups.values() if t in g["members"] and g["key"] not in seen),
                         key=lambda g: (g["kind"] != "epic", len(g["members"])))
        if not holding:
            break
        t = holding[0]["key"]
    return t


def _followed(info, folder):
    """Every ticket followed by a group or any group above it."""
    out, seen = set(), set()
    while folder and folder not in seen:
        seen.add(folder)
        g = (info or {}).get(folder) or {}
        out |= set(g.get("tickets") or ())
        folder = g.get("parent") or ""
    return out


def activity(row, now=None):
    """"working" when the session runs in Studio now or its transcript changed in the last WORKING_MINUTES, else
    "idle"."""
    from . import claudesess
    live = claudesess._LIVE.get(row.get("id"))
    if live is not None and getattr(live, "state", "") != "ended":
        return "working"
    return "working" if (now or time.time()) - _epoch(row.get("modified")) <= WORKING_MINUTES * 60 else "idle"


def _leaves(t):
    return [k for m in t["milestones"] for k in m["leaves"]] + list(t["loose"])


def entries(now=None, rows=None, graph=None, groups=None):
    """What was last worked on, newest first: epics, milestones' epics and big tickets named by sessions active in
    the last ACTIVE_DAYS, at most MAX_ENTRIES, built from local files and dev-graph's copy only (no `gh`).
    {"key", "title", "kind": "epic" | "ticket", "repos", "last_active", "sessions": {"working", "idle",
    "unsorted"}, "progress": None}. Sessions naming no ticket and in no following group are one last entry,
    kind "unsorted", never dropped. An epic whose tickets are all done (by Linear's status) drops after
    DONE_DROP_DAYS quiet days. `rows`, `graph` and `groups` are for tests."""
    now = now or time.time()
    rows = SS.listing(days=ACTIVE_DAYS)["sessions"] if rows is None else rows
    info = SS.group_info() if groups is None else groups
    graph = _merged_graph({r["id"] for r in dash.repos()["repos"] if r["root"] in {x.get("root") for x in rows}}) \
        if graph is None else graph
    found, loose = {}, []
    for r in rows:
        at = _epoch(r.get("modified"))
        if now - at > ACTIVE_DAYS * 86400:
            continue
        keys = {_epic_of(graph, t) for t in tickets_in(r) | _followed(info, r.get("folder"))}
        if not keys:
            loose.append(r)
        for k in keys:
            found.setdefault(k, []).append(r)
    out = []
    for k, rs in found.items():
        t = tree(graph, k)
        issue = (graph["issues"].get(k) or {})
        kind = "epic" if t["milestones"] or t["loose"] else "ticket"
        last = max(r["modified"] for r in rs)
        statuses = [(graph["issues"].get(x) or {}).get("status") for x in (_leaves(t) if kind == "epic" else [k])]
        if statuses and all(str(s or "") in stacks.TERMINAL for s in statuses) and \
                now - _epoch(last) > DONE_DROP_DAYS * 86400:
            continue
        work = [activity(r, now) for r in rs]
        out.append({"key": k, "title": t["title"] or issue.get("title") or rs[0].get("name") or k, "kind": kind,
                    "repos": sorted({r["repo"] for r in rs if r.get("repo")}), "last_active": last,
                    "sessions": {"working": work.count("working"), "idle": work.count("idle"), "unsorted": 0},
                    "progress": None, "last_progress": stored_progress(k)})
    out.sort(key=lambda e: e["last_active"], reverse=True)
    out = out[:MAX_ENTRIES]
    if loose:
        work = [activity(r, now) for r in loose]
        out.append({"key": "", "title": "Unsorted", "kind": "unsorted",
                    "repos": sorted({r["repo"] for r in loose if r.get("repo")}),
                    "last_active": max(r["modified"] for r in loose),
                    "sessions": {"working": work.count("working"), "idle": work.count("idle"),
                                 "unsorted": len(loose)}, "progress": None, "last_progress": None})
    return out


def _done(graph, prs, k):
    pr = (prs or {}).get(k)
    return str((graph["issues"].get(k) or {}).get("status") or "") in stacks.TERMINAL or \
        bool(pr and pr["state"] in stacks.LANDED)


_WORLD_LOCK = threading.Lock()


def progress(key, graph=None, prs=None):
    """Real progress for one entry, read from the tickets and PRs: {"done", "total", "milestones": [{"key",
    "title", "done", "total"}], "linear_as_of", "notes"}: done leaf tickets out of all leaf tickets, counted once
    each across repos. A plain ticket gives {"kind": "ticket", "finished", "status", "pr", "pr_known"} instead of a
    count (`finished` is None and `pr_known` False when its PRs could not be read). When it cannot be read:
    {"unavailable": "<why>"} and no counts. Shares one 2-minute read of the repos unless `graph` is given."""
    if graph is None:
        g, p, notes = _world()
        return _progress(key, g, p, notes)
    return _progress(key, graph, prs or {}, [])


def _world():
    """(merged dev-graph, PRs by ticket, notes): read once and shared by every entry's progress for 2 minutes, so
    thirty entries don't each walk every repo."""
    def read():
        with _WORLD_LOCK:  # one walk of the repos at a time; the others wait for it and share the answer
            return dash.cached("briefing-world-inner", 120, lambda: (lambda p: (_merged_graph(), p[0], p[1]))(
                _prs_by_ticket()))
    return dash.cached("briefing-world", 120, read)


# ---------------------------------------------------------------- progress kept on disk
# The last progress read for each entry, so a repeat visit (or a restart) shows it at once with its age and refreshes
# it behind: the list is never empty or stuck on "reading". One file, state/briefings/_progress.json.

_PLOCK, _PREFRESH = threading.Lock(), set()


def progress_path():
    return C.lfg_path("state", "briefings", "_progress.json")


def _stamp(at):
    return datetime.datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds")


def stored_progress(key):
    """The last progress read for `key` with `as_of`, or None."""
    hit = (C.read_json(progress_path(), {}) or {}).get(key)
    if not isinstance(hit, dict) or not isinstance(hit.get("data"), dict):
        return None
    return dict(hit["data"], as_of=_stamp(hit.get("at") or 0))


def _keep_progress(key, data, now):
    with _PLOCK:
        every = C.read_json(progress_path(), {}) or {}
        every[key] = {"at": now, "data": data}
        C.write_json(progress_path(), every)


def _refresh_progress(key, now):
    """Read progress again and keep it, unless it can't be read and something good is stored: then that stays."""
    try:
        data = progress(key)
    except Exception as e:  # never let a thread die quietly with the list waiting on it
        data = {"unavailable": "Progress unavailable: %s" % e}
    old = stored_progress(key)
    if data.get("unavailable") and old and not old.get("unavailable"):
        with _PLOCK:
            every = C.read_json(progress_path(), {}) or {}
            if key in every:
                every[key]["error"] = data["unavailable"]
                every[key]["tried"] = now  # don't try again at once: the stored answer stays until the next window
                C.write_json(progress_path(), every)
        return
    _keep_progress(key, data, now)


def progress_view(key, now=None, background=True):
    """What the list shows for one entry: the stored progress at once ({..., "as_of", "refreshing"}), refreshed in the
    background when older than PROGRESS_TTL_SECONDS; the first time for an entry it is read here and stored. A
    refresh that fails keeps the stored one and says why in `refresh_error`."""
    now = now or time.time()
    hit = (C.read_json(progress_path(), {}) or {}).get(key)
    if not (isinstance(hit, dict) and isinstance(hit.get("data"), dict)):
        _refresh_progress(key, now)
        out = stored_progress(key)
        return dict(out or {"unavailable": "Progress unavailable: it could not be read"}, refreshing=False)
    out = dict(stored_progress(key), refreshing=False)
    if hit.get("error"):
        out["refresh_error"] = hit["error"]
    if now - max(hit.get("at") or 0, hit.get("tried") or 0) < PROGRESS_TTL_SECONDS:
        return out
    with _PLOCK:
        busy = key in _PREFRESH
        _PREFRESH.add(key)
    out["refreshing"] = True
    if busy:
        return out

    def work():
        try:
            _refresh_progress(key, now)
        finally:
            with _PLOCK:
                _PREFRESH.discard(key)
    if background:
        threading.Thread(target=work, daemon=True, name="briefing-progress").start()
    else:
        work()
    return out


def _progress(key, graph, prs, notes):
    known = key in graph["issues"] or key in graph["groups"]
    if not known:
        why = "; ".join(graph.get("errors") or ()) or \
            "dev-graph has no copy of %s (Linear is not mirrored for it yet)" % key
        return {"unavailable": "Progress unavailable: " + why}
    t = tree(graph, key)
    stamp = graph.get("synced_at") or ""
    if not (t["milestones"] or t["loose"]):
        known = bool(prs.get(key)) or not notes  # PRs that could not be read say nothing about this ticket
        finished = _done(graph, prs, key)
        return {"kind": "ticket", "finished": finished if known or finished else None, "pr": prs.get(key),
                "pr_known": known, "status": (graph["issues"].get(key) or {}).get("status") or "",
                "linear_as_of": stamp, "notes": notes}
    ms = []
    for m in t["milestones"]:
        n = sum(_done(graph, prs, k) for k in m["leaves"])
        ms.append({"key": m["key"], "title": m["title"], "done": n, "total": len(m["leaves"])})
    leaves = _leaves(t)
    return {"done": sum(_done(graph, prs, k) for k in leaves), "total": len(leaves), "milestones": ms,
            "linear_as_of": stamp, "notes": notes}


# ---------------------------------------------------------------- a briefing

OPEN = {"open", "approved", "changes", "draft"}
ROW_KEYS = ("id", "name", "auto_name", "named", "repo", "root", "worktree", "branch", "ticket", "folder", "labels",
            "starred", "hidden", "modified", "resume", "cwd", "folder_exists", "via_pr", "via_ticket")


def _session(r, role, now):
    return dict({k: r.get(k) for k in ROW_KEYS if k in r}, role=role, activity=activity(r, now),
                first=str(r.get("first") or "")[:400])


def _gh_state():
    """(PRs by ticket or None, note, your login). None when GitHub cannot be read at all."""
    from . import review as R
    try:
        prs, notes = _prs_by_ticket()
        who = R.me()
    except Exception as e:
        return None, "GitHub could not be read: %s" % e, ""
    return prs, "; ".join(notes), who


def _needs_you(tickets, prs, me, records, sessions, now):
    out = []
    saved = {(r.get("repo"), r.get("number")) for r in records}
    for t in sorted(tickets):
        p = (prs or {}).get(t)
        if not p or not me:  # without knowing who you are, "someone else's PR" and "your PR" can't be told apart
            continue
        mine = p.get("author") == me
        target = "#prs/%s/%d" % (p["gh_repo"], p["number"])
        if p["state"] in OPEN and p["state"] != "draft" and not mine and (p["gh_repo"], p["number"]) not in saved:
            out.append({"kind": "review_pr", "target": target, "ticket": t,
                        "text": "Review %s's PR #%d for %s: you have no saved review of it yet."
                                % (p.get("author") or "someone", p["number"], t)})
        if mine and p["state"] in OPEN and p.get("ci") == "fail":
            out.append({"kind": "checks", "target": target, "ticket": t,
                        "text": "Fix the failing checks on your PR #%d for %s." % (p["number"], t)})
    for rec in records:
        p = (prs or {}).get(rec.get("ticket"))
        if rec.get("ticket") not in tickets or not p or p["number"] != rec.get("number") or p["state"] not in OPEN:
            continue  # only a PR that is still open has a question waiting
        for ps in sorted(rec.get("passes") or [], key=lambda x: x.get("n") or 0)[-1:]:  # the latest review
            for q in ps.get("questions") or []:
                if not q.get("answer"):
                    out.append({"kind": "question", "ticket": rec["ticket"],
                                "target": "#prs/%s/%d" % (rec["repo"], rec["number"]),
                                "text": "Answer the open question on PR #%d: %s" % (rec["number"],
                                                                                   str(q.get("ask") or "")[:140])})
    for r in sessions:
        if r["role"] != "worker" or r["activity"] != "idle":
            continue
        for t in sorted(tickets & tickets_in(r)):
            p = (prs or {}).get(t)
            if p and p["state"] in OPEN and now - _epoch(r.get("modified")) >= IDLE_PR_MINUTES * 60:
                out.append({"kind": "idle_pr", "target": "#studio/%s" % r["id"], "ticket": t,
                            "text": "Pick up \"%s\" again: it has an open PR (#%d) and has been idle for over an hour."
                                    % (r.get("name") or r["id"], p["number"])})
                break
    return out


def briefing(key, now=None, rows=None, graph=None, groups=None, prs=0, me=None, records=None, gh_note=""):
    """Everything the briefing page shows for one entry: {"entry", "progress", "orchestrator": session | None,
    "other_orchestrators", "milestones": [{"key", "title", "done", "total", "sessions"}], "unsorted", "needs_you":
    [{"kind", "text", "target", "ticket"}], "gh_note", "summary"}. A session is {the listing's fields, "role",
    "activity"}. Key "" is the Unsorted entry. `prs=None` means GitHub is unreadable (the PR rules are skipped and
    `gh_note` says so); the other arguments are for tests."""
    from . import review as R
    now = now or time.time()
    rows = SS.listing(days=ACTIVE_DAYS)["sessions"] if rows is None else rows
    info = SS.group_info() if groups is None else groups
    if graph is None:
        graph = _merged_graph({r["id"] for r in dash.repos()["repos"] if r["root"] in {x.get("root") for x in rows}})
    found = entries(now, rows=rows, graph=graph, groups=info)
    entry = next((e for e in found if e["key"] == key), None)
    recent = [r for r in rows if now - _epoch(r.get("modified")) <= ACTIVE_DAYS * 86400]
    unsorted = [_session(r, "unsorted", now) for r in recent
                if not {_epic_of(graph, t) for t in tickets_in(r) | _followed(info, r.get("folder"))}]
    attach_ = {"tickets": [{"key": e["key"], "title": e["title"]} for e in found if e["kind"] != "unsorted"],
               "groups": sorted(info)}
    if not key:
        return {"entry": entry, "progress": None, "orchestrator": None, "other_orchestrators": [], "milestones": [],
                "unsorted": unsorted, "needs_you": [], "gh_note": "", "summary": None, "attach": attach_,
                "group_info": info, "label_list": SS.label_list()}
    t = tree(graph, key)
    plain = not (t["milestones"] or t["loose"])
    mine = [r for r in recent if key in {_epic_of(graph, x) for x in tickets_in(r) | _followed(info, r.get("folder"))}]
    if prs == 0:
        prs, gh_note, me = _gh_state()
    elif me is None:
        me = R.me()
    if prs is not None and not me:
        gh_note = "; ".join(x for x in (gh_note, "LFG couldn't tell who you are on GitHub, so PR items are left out")
                            if x)
    progress_ = _progress(key, graph, prs or {}, [gh_note] if gh_note else [])
    entry = entry or {"key": key, "title": t["title"] or (graph["issues"].get(key) or {}).get("title") or key,
                      "kind": "ticket" if plain else "epic"}
    sessions = [_session(r, "worker" if plain else role_of(r, t, _followed(info, r.get("folder"))), now) for r in mine]
    sessions.sort(key=lambda s: s["modified"], reverse=True)
    orch = [s for s in sessions if s["role"] == "orchestrator"]
    workers = [s for s in sessions if s["role"] != "orchestrator"]
    stats = {m["key"]: m for m in progress_.get("milestones") or []}
    sections = [{"key": m["key"], "title": m["title"], "tickets": {m["key"], *m["leaves"]}} for m in t["milestones"]]
    if plain:
        sections = [{"key": "", "title": "Sessions", "tickets": {key}}]
    elif t["loose"]:
        sections.append({"key": "", "title": "Other tickets", "tickets": set(t["loose"])})
    for sec in sections:
        sec["sessions"] = []
    for s in workers:
        named = tickets_in(s) | _followed(info, s.get("folder"))
        home = next((sec for sec in sections if sec["tickets"] & named), sections[-1] if sections else None)
        if home:
            home["sessions"].append(s)
    milestones = []
    for sec in sections:
        m = {"key": sec["key"], "title": sec["title"], "sessions": sec["sessions"]}
        if sec["key"] in stats:
            m.update(done=stats[sec["key"]]["done"], total=stats[sec["key"]]["total"])
        elif not plain and not sec["key"]:
            m.update(total=len(t["loose"]), done=sum(_done(graph, prs or {}, k) for k in t["loose"]))
        milestones.append(m)
    records = R.all_records() if records is None else records
    need = _needs_you(set(_leaves(t)) | {key} | {m["key"] for m in t["milestones"]}, prs, me, records, sessions, now) \
        if prs is not None else []
    out = {"entry": entry, "progress": progress_, "orchestrator": orch[0] if orch else None,
           "other_orchestrators": orch[1:], "milestones": milestones, "unsorted": unsorted, "needs_you": need,
           "gh_note": gh_note or "", "summary": None,
           "attach": attach_, "group_info": info, "label_list": SS.label_list()}
    out["summary"] = stored_summary(key, out, now)
    out["summary_error"] = (_ERR.get(key) or {}).get("error")
    return out


# ---------------------------------------------------------------- the written summary
# Claude writes 2 to 4 sentences about where the work stopped, in the background, from the facts above. Opening a
# briefing never waits on it: the last stored one shows with its age. Stored under state/briefings/<KEY>.json.

_TRY, _RUNNING, _SLOCK = {}, set(), threading.Lock()  # key -> when it last tried; keys being written now
_ERR = {}  # key -> {"error", "at"} of the last try that failed, until one works

PROMPT = """You write the "where you left off" note at the top of a briefing for one piece of work (an epic, a \
milestone or a ticket). Write 2 to 4 plain sentences for the person who owns it: where the work stopped, what is \
done, what is waiting on them and what comes next. Use only the facts below; if something is not in them, leave it \
out. Never invent a number, a name or a ticket. No headings, no bullet points, no preamble.

%s
"""


def pinned_model():
    """The model the summary runs on: Sonnet, always. models.briefing is used only when it names a Sonnet (the alias
    "sonnet" means SUMMARY_MODEL); missing, empty, invalid, Opus or anything else gives SUMMARY_MODEL."""
    try:
        v = (C.config().get("models") or {}).get("briefing")
    except Exception:  # a broken config must not unpin the model
        v = None
    v = v.strip().lower() if isinstance(v, str) else ""
    if v == "sonnet":
        return SUMMARY_MODEL
    if re.fullmatch(r"claude-sonnet-[a-z0-9.-]{1,20}", v):
        return v
    return SUMMARY_MODEL


def summary_path(key):
    return C.lfg_path("state", "briefings", re.sub(r"[^A-Za-z0-9_-]", "_", str(key or "unsorted")).upper() + ".json")


def _sessions_of(data):
    out = [data["orchestrator"]] if data.get("orchestrator") else []
    out += data.get("other_orchestrators") or []
    return out + [s for m in data.get("milestones") or [] for s in m["sessions"]]


def summary_key(key, data=None):
    """What the summary was built from: the newest transcript time under the entry and the counts of sessions and
    done tickets. When it changes, the work moved on."""
    data = briefing(key) if data is None else data
    ss = _sessions_of(data)
    pr = data.get("progress") or {}
    return "%s|s%d|d%s" % (max((s.get("modified") or "" for s in ss), default=""), len(ss),
                           pr.get("done", "-") if "done" in pr else int(bool(pr.get("finished"))))


def _last_messages(session):
    """The last few turns of a session as plain lines, or [] when its transcript cannot be read."""
    try:
        return ["%s: %s" % ("Me" if t["who"] == "you" else "Claude", t["text"].replace("\n", " "))
                for t in SS.recent(session["id"], 4)["turns"]]
    except (ValueError, OSError):
        return []


def _facts(data):
    e, pr = data["entry"] or {}, data.get("progress") or {}
    lines = ["%s: %s (%s)" % (e.get("key"), e.get("title"), e.get("kind"))]
    if "total" in pr:
        lines.append("Progress: %d of %d tickets done" % (pr["done"], pr["total"]))
        lines += ["  %s %s: %d of %d done" % (m["key"], m["title"], m["done"], m["total"])
                  for m in pr.get("milestones") or []]
    elif "finished" in pr:
        lines.append("Ticket %s; its PR: %s" % ("done" if pr["finished"] else "not done",
                                                  (pr.get("pr") or {}).get("state") or "none"))
    else:
        lines.append(pr.get("unavailable") or "Progress unavailable")
    for s in _sessions_of(data):
        lines.append("Session \"%s\" (%s, %s, last active %s)" % (s.get("name"), s["role"], s["activity"],
                                                                   s.get("modified")))
    lines += ["Waiting on the owner: " + i["text"] for i in data.get("needs_you") or []]
    head = data.get("orchestrator") or next(iter(_sessions_of(data)), None)
    if head:
        lines.append("The last messages of \"%s\":" % head.get("name"))
        lines += ["  " + m for m in _last_messages(head)]
    return "\n".join(lines)


def _claude(prompt, model):
    """One no-tools `claude -p` call, the way review.py makes them. Returns (text, cost)."""
    from . import review as R
    if not C.which("claude"):
        raise RuntimeError("Claude Code (`claude`) is not on PATH")
    cp = subprocess.run(["claude", "-p", "--output-format", "json", "--permission-mode", "dontAsk"] + C.CLAUDE_BARE
                        + ["--model", model or pinned_model()] + R._direct(), input=prompt,
                        capture_output=True, text=True, timeout=180)
    try:
        j = json.loads(cp.stdout)
    except ValueError:
        j = {}
    text = str(j.get("result") or "").strip()
    if not text:
        raise RuntimeError("Claude returned no text: %s" % (cp.stderr or cp.stdout or "")[-200:].strip())
    return text, j.get("total_cost_usd")


def stored_summary(key, data=None, now=None):
    """The stored summary with `stale` (the work moved on since it was written), or None."""
    s = C.read_json(summary_path(key))
    if not s or not s.get("text"):
        return None
    data = briefing(key) if data is None else data
    return {"text": s["text"], "at": s.get("at"), "cost": s.get("cost"),
            "stale": s.get("key") != summary_key(key, data)}


def summarize(key, run=None, data=None, now=None):
    """Write the summary now and store it: {"text", "at", "cost", "key"}. A call that fails keeps the stored one and
    returns {"error": "<plain reason>"}. `run(prompt, model) -> (text, cost)` is injected in tests."""
    now = now or time.time()
    data = briefing(key) if data is None else data
    if not key or not _sessions_of(data):
        return {"error": "Nothing to summarize: no session works on this."}
    with _SLOCK:
        _TRY[key] = now
    try:
        text, cost = (run or _claude)(PROMPT % _facts(data), pinned_model())
    except Exception as e:  # a timeout, no claude, a refusal: the stored summary stays
        with _SLOCK:
            _ERR[key] = {"error": "The summary could not be written: %s" % e, "at": now}
        return {"error": _ERR[key]["error"]}
    with _SLOCK:
        _ERR.pop(key, None)
    out = {"text": text, "at": datetime.datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
           "cost": cost, "key": summary_key(key, data)}
    C.write_json(summary_path(key), dict(out, at_epoch=now))
    return out


def maybe_summarize(key, run=None, data=None, now=None, background=True):
    """Start writing the summary in the background when the work changed since the stored one and nothing was tried
    for this entry in the last SUMMARY_MIN_GAP_MINUTES (a failed try counts). Never blocks. `background=False`
    runs it here (tests)."""
    now = now or time.time()
    stored = C.read_json(summary_path(key)) or {}
    with _SLOCK:
        last = max(stored.get("at_epoch") or 0, _TRY.get(key) or 0)
        if key in _RUNNING or now - last < SUMMARY_MIN_GAP_MINUTES * 60:
            return
    data = briefing(key) if data is None else data
    if not key or not _sessions_of(data) or stored.get("key") == summary_key(key, data):
        return

    def work():
        try:
            summarize(key, run, data, now)
        finally:
            with _SLOCK:
                _RUNNING.discard(key)
    with _SLOCK:
        if key in _RUNNING:
            return
        _RUNNING.add(key)
    if background:
        threading.Thread(target=work, daemon=True, name="briefing-summary").start()
    else:
        work()


# ---------------------------------------------------------------- "This belongs to..."

def attach(sid, ticket):
    """Tie a session to a ticket for good: put it in the group that follows the ticket (any group that does, else a
    group named after the ticket that follows it), filed by hand, so it beats any follow rule. Raises ValueError for
    something that is not a ticket id."""
    ticket = str(ticket or "").strip().upper()
    if not SS.TICKET.fullmatch(ticket) or ticket in SS.NOT_TICKETS:
        raise ValueError("not a ticket: %r (like ATO-7)" % ticket)
    SS._known(sid)
    group = next((g for g, i in sorted(SS.group_info().items()) if ticket in i["tickets"]), None)
    if not group:
        group = ticket
        SS.follow_ticket(group, ticket)
    SS.file_into(sid, group)
    return {"id": sid, "folder": group, "group": group, "ticket": ticket}


# ---------------------------------------------------------------- the list: last 24 hours and Done
# The list page's two plain additions. "Last 24 hours" is just sessions.listing cut by time (no matching rules).
# Done marks an entry or a session as finished with: it stops showing until it has new activity after the mark.
# One small file, state/briefings/_done.json: {"<entry key, "unsorted" or session id>": "<ISO time checked>"}.

RECENT_HOURS = 24


def done_path():
    return C.lfg_path("state", "briefings", "_done.json")


def set_done(key, on=True, now=None):
    """Check `key` off (an entry's key, "unsorted", or a session id), or undo it with on=False."""
    key = str(key or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
        raise ValueError("not something that can be checked off: %r" % key)
    with _PLOCK:
        marks = C.read_json(done_path(), {}) or {}
        if on:
            marks[key] = _stamp(now or time.time())
        else:
            marks.pop(key, None)
        C.write_json(done_path(), marks)
    return {"key": key, "on": bool(on)}


def _checked_at(marks, key):
    try:
        return datetime.datetime.fromisoformat(marks[key]).timestamp()
    except (KeyError, ValueError, TypeError):
        return None


def listing(now=None, rows=None, graph=None, groups=None):
    """What the list page shows: {"entries", "recent", "checked", "active_days", "group_info", "label_list"}.
    `recent`: every session touched in the last RECENT_HOURS, newest first, hidden ones left out, each with
    `activity` (it may also sit under an entry). Anything checked off is left out of `entries` and `recent` until it
    has activity after the mark; `checked` lists what is hidden that way, for "Show checked off" and Undo."""
    now = now or time.time()
    full = SS.listing(days=ACTIVE_DAYS) if rows is None else {"sessions": rows}
    rows = full["sessions"]
    marks = C.read_json(done_path(), {}) or {}
    checked = []
    entries_ = []
    for e in entries(now, rows=rows, graph=graph, groups=groups):
        at = _checked_at(marks, e["key"] or "unsorted")
        if at is not None and _epoch(e["last_active"]) <= at:
            k = e["key"] or "unsorted"
            checked.append({"type": "entry", "key": k, "title": e["title"], "at": marks[k]})
        else:
            entries_.append(e)
    recent = []
    for r in sorted(rows, key=lambda r: r.get("modified") or "", reverse=True):
        if now - _epoch(r.get("modified")) > RECENT_HOURS * 3600 or r.get("hidden"):
            continue
        at = _checked_at(marks, r["id"])
        if at is not None and _epoch(r.get("modified")) <= at:
            checked.append({"type": "session", "key": r["id"], "title": r.get("name") or r["id"],
                            "at": marks[r["id"]]})
        else:
            recent.append(_session(r, "", now))
    return {"entries": entries_, "recent": recent, "checked": checked, "active_days": ACTIVE_DAYS,
            "group_info": full.get("group_info") or SS.group_info(), "label_list": full.get("label_list") or []}
