"""Data for the `lfg ui` dashboard: one read-only view over every tool LFG uses.

code-review-graph (SQLite, read-only) · graphify (graph.json + GRAPH_REPORT.md) · generated docs/playbooks ·
Omnigraph dev-graph + second-brain (reader role) · Linear (through the dev-graph mirror; the dashboard never
calls Linear) · Headroom (`headroom savings --json`) · LFG runs, gates, reviews, security and usage.db.

Every function returns plain JSON-able data and degrades to {"available": False, "why": ...} instead of
raising, so one missing tool never takes the dashboard down. Never returns secrets. Author: Varun Singh.
"""
import collections
import fnmatch
import glob
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request

from . import common as C
from . import docs as D

STAGES = [  # (key, label, file glob) in pipeline order
    ("brief", "Brief", "01-brief.md"), ("design", "Design", "02-design.md"), ("tasks", "Tasks", "tasks.json"),
    ("build", "Build", "03-build-*.md"), ("qa", "QA", "04-qa.md"), ("gate", "Gate", "ready.json"),
    ("secure", "Secure", "05-secure.json"), ("review", "Review", "06-review.json"),
    ("ship", "Ship check", "07-shipcheck.json"), ("packet", "Ship packet", "COMMIT_MSG.md"),
]


# ---------------------------------------------------------------- small cache

_CACHE, _CLOCK = {}, threading.Lock()


def cached(key, ttl, fn):
    now = time.time()
    with _CLOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _CLOCK:
        _CACHE[key] = (now, val)
    return val


def _na(why):
    return {"available": False, "why": why}


# ---------------------------------------------------------------- repos + runs

def repo_ids():
    ids = set()
    for d in ("runs", "graphs"):
        if os.path.isdir(C.lfg_path(d)):
            ids |= {i for i in os.listdir(C.lfg_path(d)) if not i.startswith(".")
                    and os.path.isdir(C.lfg_path(d, i))}
    return sorted(ids)


def repo_root(rid):
    return (C.read_json(C.lfg_path("graphs", rid, "state.json"), {}) or {}).get("repo_root")


def repos():
    out = []
    for rid in repo_ids():
        st = C.read_json(C.lfg_path("graphs", rid, "state.json"), {}) or {}
        root = st.get("repo_root")
        out.append({"id": rid, "root": root, "synced_at": st.get("synced_at"), "error": bool(st.get("last_error")),
                    "name": os.path.basename((root or "").rstrip("/")) or re.sub(r"-[0-9a-f]{8}$", "", rid),
                    "branch": C.git_branch(root) if root and os.path.isdir(root) else ""})
    clash = collections.Counter(r["name"] for r in out)
    for r in out:  # two checkouts with the same folder name: show where each lives
        if clash[r["name"]] > 1:
            r["name"] += " (%s)" % os.path.basename(os.path.dirname((r["root"] or "").rstrip("/")) or r["id"])
    out.sort(key=lambda r: r.get("synced_at") or "", reverse=True)
    return {"repos": out}


# ---------------------------------------------------------------- branches
# Runs record the branch they were started on (run.json "branch"); runs from before that have none. The graphs are one
# copy per repo that follows whatever branch is checked out, so they are not filtered by branch.
UNRECORDED = "-"


def run_branch(d):
    return (C.read_json(os.path.join(d, "run.json"), {}) or {}).get("branch") or ""


def _branch_ok(d, branch):
    return not branch or (run_branch(d) or UNRECORDED) == branch


def _run_files(rid, name, branch=None):
    """Newest first: runs/<rid>/*/<name> for runs on `branch` (None or "" = every branch, "-" = not recorded)."""
    if not name:  # the run folders themselves
        return [d for d in sorted(glob.glob(C.lfg_path("runs", rid, "*")), reverse=True)
                if os.path.isdir(d) and _branch_ok(d, branch)]
    return [p for p in sorted(glob.glob(C.lfg_path("runs", rid, "*", name)), reverse=True)
            if _branch_ok(os.path.dirname(p), branch)]


def git_branches(root):
    """Local branches, which are merged into the default branch, the default branch and the checked-out one."""
    if not root or not os.path.isdir(root):
        return None
    def g(*a):
        cp = C.run(["git"] + list(a), cwd=root, timeout=15)
        return cp.stdout.split() if cp.returncode == 0 else []
    local = g("for-each-ref", "refs/heads", "--format=%(refname:short)")
    head = (g("symbolic-ref", "--short", "refs/remotes/origin/HEAD") or [""])[0].split("/", 1)[-1]
    default = head if head in local else next((b for b in ("main", "master", "develop") if b in local), "")
    merged = set(g("branch", "--merged", default, "--format=%(refname:short)")) - {default} if default else set()
    return {"local": local, "merged": merged, "default": default, "current": C.git_branch(root)}


def branches(rid):
    counts = collections.Counter(run_branch(d) or UNRECORDED for d in _run_files(rid, ""))
    gb = git_branches(repo_root(rid))
    names = set(counts) - {UNRECORDED} | ({gb["current"]} if gb and gb["current"] else set())
    out = []
    for b in sorted(names):
        state = "unknown" if gb is None else ("current" if b == gb["current"] else "default" if b == gb["default"]
                                              else "merged" if b in gb["merged"] else "local" if b in gb["local"]
                                              else "deleted")
        out.append({"name": b, "runs": counts.get(b, 0), "state": state})
    out.sort(key=lambda x: (x["state"] != "current", x["name"]))
    return {"branches": out, "current": gb["current"] if gb else "", "unrecorded": counts.get(UNRECORDED, 0),
            "graphs_follow": gb["current"] if gb else ""}


def _stage_state(d):
    files = set(os.listdir(d))
    done = {}
    for key, _label, pat in STAGES:
        done[key] = any(fnmatch.fnmatch(f, pat) for f in files)
    return done


def _verdict(v):
    """05-secure.json verdicts are a string or {"overall": ..., "blocking": [...]}."""
    return v.get("overall") if isinstance(v, dict) else v


def _blocking(s):
    b = s.get("blocking")
    if isinstance(b, int) and not isinstance(b, bool):
        return b
    v = s.get("verdict")
    if isinstance(v, dict) and isinstance(v.get("blocking"), list):
        return len(v["blocking"])
    return sum(1 for f in s.get("findings", []) if isinstance(f, dict) and f.get("blocking") is True)


def _about(d, review=None):
    """(title, one-paragraph description) of a run, from the brief's heading and Problem section."""
    title, about, section = "", "", None
    for line in C.read_text(os.path.join(d, "01-brief.md")).splitlines():
        s = line.strip()
        if s.startswith("# ") and not title:
            title = s[2:].split(":", 1)[-1].strip() if s[2:].lower().startswith("brief:") else s[2:].strip()
        elif s.startswith("#"):
            if about:
                break
            section = s.lstrip("#").strip().lower()
        elif s and section in (None, "problem", "summary", "goal", "what") and not s.startswith(("-", "|", "```")):
            about += (" " if about else "") + s
        elif not s and about:
            break
    if not about and isinstance(review, dict):  # review-only runs: the review's own summary
        s = review.get("summary") or ""
        parts = [str(v).strip() for v in (s.values() if isinstance(s, dict) else [s]) if str(v).strip()]
        about = " ".join(x if x.endswith((".", "!", "?")) else x + "." for x in parts)
    return title, about[:400]


def _run_summary(d):
    meta = C.read_json(os.path.join(d, "run.json"), {}) or {}
    fix = None
    if meta.get("kind") == "pr-fix":  # a fix run started from a PR's fix list on the Reviews page
        from . import prreview as PR
        PR.settle_fix(d)
        res = C.read_json(os.path.join(d, "fix-result.json"), None) or {}
        fix = {"working": PR.fix_running(d), "total": len(meta.get("items") or []), "ok": res.get("ok"),
               "done": {s: sum(1 for x in (res.get("items") or {}).values() if x.get("status") == s)
                        for s in PR.FIX_STATUS}, "items": res.get("items") or {},
               "titles": {t.get("id"): {"title": PR._title(t.get("body"))[:160], "path": t.get("path"),
                                        "line": t.get("line")}
                          for t in (C.read_json(os.path.join(d, "fixlist.json"), {}) or {}).get("items") or []}}
    rd = C.read_json(os.path.join(d, "ready.json"), None)
    sc = C.read_json(os.path.join(d, "07-shipcheck.json"), None)
    rv = C.read_json(os.path.join(d, "06-review.json"), None)
    se = C.read_json(os.path.join(d, "05-secure.json"), None)
    pt = C.read_json(os.path.join(d, "05-pentest.json"), None)
    tasks = C.read_json(os.path.join(d, "tasks.json"), None)
    tl = tasks if isinstance(tasks, list) else (tasks or {}).get("tasks", []) if isinstance(tasks, dict) else []
    stages = _stage_state(d)
    title, about = _about(d, rv)
    ready = None if rd is None else ("green" if rd.get("green") else "red")
    if ready and _newer_work(d, os.path.join(d, "ready.json")):
        ready = "stale"  # the work changed after the checks ran: their result says nothing about it now
    return {"run": os.path.basename(d), "slug": meta.get("slug"), "created": meta.get("created"),
            "title": title, "about": about,
            "branch": meta.get("branch") or "", "kind": meta.get("kind"), "pr": meta.get("pr"),
            "pr_url": meta.get("pr_url"), "worktree": meta.get("worktree"), "fix": fix,
            "archived": meta.get("archived"),
            "lane": meta.get("lane"), "stage": meta.get("stage"), "issue": meta.get("issue"),
            "stages": stages, "progress": sum(stages.values()),
            "ready": ready, "checked_at": (rd or {}).get("ts"), "checking": checks_running(d),
            "review": (rv or {}).get("verdict"), "secure": _verdict((se or {}).get("verdict")),
            "pentest": (pt or {}).get("status") if isinstance(pt, dict) else None,
            "shipcheck": None if sc is None else ("pass" if sc.get("pass") else "fail"),
            "tasks": {"total": len(tl), "done": sum(1 for t in tl if isinstance(t, dict) and t.get("passes"))}}


def checks_running(d):
    """When `lfg gate` started from the dashboard is still running for run dir `d`: its start time, else None."""
    m = C.read_json(os.path.join(d, "gate-running.json"), None)
    if not isinstance(m, dict):
        return None
    try:
        os.kill(int(m.get("pid")), 0)
    except (OSError, TypeError, ValueError):
        return None
    return m.get("started") or True


def _newer_work(d, since):
    """Did the run's work (build notes, patches, task list) change after the file `since` was written?"""
    try:
        t = os.path.getmtime(since)
    except OSError:
        return False
    work = glob.glob(os.path.join(d, "03-*.md")) + glob.glob(os.path.join(d, "patches", "*")) + \
        [os.path.join(d, "tasks.json")]
    return any(os.path.getmtime(p) > t + 1 for p in work if os.path.isfile(p))


def _for_repo(summary, mine, d=None, rid=None):
    """A shared run as seen from one of the other repos it has tasks for: the brief, design and task list are
    shared; build counts once all of this repo's tasks pass; the checks, review and ship files after that are
    about the owner's work, so they neither count nor show here."""
    every = bool(mine) and all(t.get("passes") for t in mine)
    st = summary["stages"]
    stages = {k: (bool(st.get(k)) if k in ("brief", "design") else k == "tasks" or (k == "build" and every))
              for k, _, _ in STAGES}
    part = {}  # this repo's own stage results in the shared run (04-qa-portal.md, 05-secure-portal.json, ...)
    for key, _, pat in STAGES:
        if d and rid and "*" not in pat and key not in ("brief", "design", "tasks"):
            hit = next((p for label, p in _part_files(d, pat).items() if repo_matches(rid, label)), None)
            if hit:
                stages[key], part[key] = True, hit
    se = C.read_json(part["secure"], {}) if "secure" in part else {}
    rv = C.read_json(part["review"], {}) if "review" in part else {}
    sc = C.read_json(part["ship"], None) if "ship" in part else None
    rd = C.read_json(part["gate"], None) if "gate" in part else None
    return dict(summary, stages=stages, progress=sum(stages.values()),
                ready=None if rd is None else ("green" if rd.get("green") else "red"),
                review=(rv or {}).get("verdict"), secure=_verdict((se or {}).get("verdict")), pentest=None,
                shipcheck=None if sc is None else ("pass" if sc.get("pass") else "fail"),
                tasks={"total": len(mine), "done": sum(bool(t.get("passes")) for t in mine)})


def _repo_name(rid):
    root = repo_root(rid)
    return (os.path.basename(root.rstrip("/")) if root else re.sub(r"-[0-9a-f]{8}$", "", rid)).lower()


def repo_matches(rid, value):
    """Does a free-text repo label (a task's "repo", an issue's "Repo:") mean repo `rid`? Exact folder name, or its
    last part(s): "portal" and "compliance-portal" both mean aegis-compliance-portal."""
    v, name = str(value or "").strip().lower().rstrip("/").rsplit("/", 1)[-1], _repo_name(rid)
    return bool(v) and (v == name or name.endswith("-" + v))


def _tasks(d):
    t = C.read_json(os.path.join(d, "tasks.json"), []) or []
    t = t.get("tasks", []) if isinstance(t, dict) else t
    return [x for x in t if isinstance(x, dict)]


def shared_runs(rid):
    """Runs filed under another repo whose tasks.json has tasks for this one (one run can span several repos):
    [(owner rid, run dir, [this repo's tasks])], newest first."""
    out = []
    for other in repo_ids():
        if other == rid:
            continue
        for d in _run_files(other, ""):
            mine = [t for t in _tasks(d) if repo_matches(rid, t.get("repo"))]
            if mine:
                out.append((other, d, mine))
    return sorted(out, key=lambda x: os.path.basename(x[1]), reverse=True)


def _run_dir(rid, run):
    """A run of this repo, or one filed under another repo that has tasks for this one."""
    d = C.lfg_path("runs", rid, run)
    if os.path.isdir(d):
        return d
    return next((d for _, d, _ in shared_runs(rid) if os.path.basename(d) == run), None)


def refresh_pr_states(rid, max_age=600):
    """Fetch every pull request GitHub knows for this repo (open, merged, closed) into pr-states.json, when the saved
    list is older than `max_age`. One `gh pr list` for the whole repo; run by `lfg ui`'s watcher, never by a page."""
    p = C.lfg_path("repos", rid, "pr-states.json")
    hit = C.read_json(p, None)
    if isinstance(hit, dict) and time.time() - hit.get("at", 0) < max_age:
        return False
    root = repo_root(rid)
    if not root or not os.path.isdir(root) or not C.which("gh"):
        return False
    cp = C.run(["gh", "pr", "list", "--state", "all", "--limit", "300", "--json",
                "number,headRefName,state,mergedAt,closedAt,title,url"], cwd=root, timeout=60)
    try:
        prs = json.loads(cp.stdout or "[]") if cp.returncode == 0 else None
    except ValueError:
        prs = None
    if not isinstance(prs, list):
        return False
    C.ensure_dir(os.path.dirname(p))
    C.write_json(p, {"at": time.time(), "prs": prs})
    return True


def pr_states(rid):
    """The saved list of this repo's pull requests, as ({number: pr}, {branch: newest pr}). Pages only read it, so a
    page never waits on GitHub; until `lfg ui` has fetched it once, runs simply show no PR tags."""
    hit = C.read_json(C.lfg_path("repos", rid, "pr-states.json"), None)
    prs = [x for x in (hit or {}).get("prs") or [] if isinstance(x, dict) and x.get("number")]
    by_branch = {}
    for x in sorted(prs, key=lambda x: x["number"]):  # a branch reused for a later PR: the newest one counts
        by_branch[x.get("headRefName")] = x
    return {x["number"]: x for x in prs}, by_branch


def _lazy_branches(rid):
    """git_branches(), asked at most once and only when a run needs it."""
    memo = []

    def get():
        if not memo:
            memo.append(git_branches(repo_root(rid)))
        return memo[0]
    return get


def run_life(r, by_n, by_branch, branches):
    """A run's tags and whether it still needs anything: its PR (and that PR's state), its issue, what kind of run it
    is, and active / done / not needed (its PR was merged or closed, its branch merged, or the user said so).
    `branches` gives git_branches() when called (or is it, or None)."""
    branch = r.get("branch") or ""
    gb = (branches() if callable(branches) else branches) if branch and not r.get("pr") else None
    pr = by_n.get(r["pr"]) if r.get("pr") else \
        by_branch.get(branch) if branch and gb is not None and branch != gb.get("default") else None
    tags = []
    if r.get("kind") == "pr-fix":
        tags.append({"text": "Fix run", "tone": "on"})
    if pr:
        tags.append({"text": "PR #%d" % pr["number"], "tone": {"MERGED": "merged", "CLOSED": "bad"}.get(pr.get("state"),
                                                                                                    "on"),
                     "href": pr.get("url"), "state": pr.get("state")})
    if r.get("issue"):
        iss = str(r["issue"])
        if re.match(r"^[a-z]+-\d+$", iss, re.I):  # a Linear key: ATO-123
            tags.append({"text": iss.upper(), "tone": ""})
        else:  # a dev-graph slug: iss-rollout-devices-onboarding-gap -> "Issue: rollout devices onboarding…"
            words = re.sub(r"^iss-", "", iss).replace("-", " ")
            tags.append({"text": "Issue: " + (words[:28].rsplit(" ", 1)[0] + "…" if len(words) > 30 else words),
                         "tone": "", "title": iss})
    stages = r.get("stages") or {}
    fix = r.get("fix") or {}
    finished = (fix.get("ok") and not (fix.get("done") or {}).get("failed")) if r.get("kind") == "pr-fix" \
        else bool(stages) and all(stages.values())
    if r.get("archived"):
        life = ("not-needed", "Marked not needed")
    elif pr and pr.get("state") == "MERGED":
        life = ("not-needed", "PR #%d merged" % pr["number"])
    elif pr and pr.get("state") == "CLOSED":
        life = ("not-needed", "PR #%d closed" % pr["number"])
    elif gb and branch and branch in gb.get("merged", ()):
        life = ("not-needed", "Branch merged")
    elif finished:
        life = ("done", "All steps done")
    else:
        life = ("active", "")
    return {"tags": tags, "life": life[0], "life_why": life[1]}


def set_needed(rid, run, needed):
    """The user's own call on a run: not needed any more (hidden from Active), or needed again."""
    d = C.lfg_path("runs", rid, os.path.basename(str(run or "")))
    p = os.path.join(d, "run.json")
    if not os.path.isfile(p):
        raise ValueError("run not found")
    meta = C.read_json(p, {}) or {}
    if needed:
        meta.pop("archived", None)
    else:
        meta["archived"] = C.now_iso()
    C.write_json(p, meta)
    return {"saved": True}


def search_runs(rid, q):
    from . import runsearch as RS
    dirs = [d for d in _run_files(rid, "")[:300] if os.path.isdir(d)]
    return dict(RS.search(rid, q, dirs), available=True)


def runs(rid, branch=None):
    cur = C.read_text(C.lfg_path("runs", rid, "CURRENT")).strip()
    out = []
    by_n, by_branch = pr_states(rid)
    gb = _lazy_branches(rid)
    for d in _run_files(rid, "", branch)[:100]:
        if os.path.isdir(d):
            r = _run_summary(d)
            r["current"] = r["run"] == cur
            r.update(run_life(r, by_n, by_branch, gb))
            out.append(r)
    if not branch:  # a shared run's branch is the other repo's, so it only shows under all branches
        for owner, d, mine in shared_runs(rid):
            r = _for_repo(_run_summary(d), mine, d, rid)
            r.update(current=False, owner=owner, owner_name=_repo_name(owner), tasks_here=len(mine),
                     tasks_here_done=sum(bool(t.get("passes")) for t in mine))
            out.append(r)
        out.sort(key=lambda r: r["run"], reverse=True)
    return {"runs": out, "stages": [[k, label] for k, label, _ in STAGES]}


def run_detail(rid, run):
    d = _run_dir(rid, run)
    if not d:
        return _na("run not found")
    files = []
    for root, _dirs, fs in os.walk(d):
        for f in sorted(fs):
            p = os.path.join(root, f)
            files.append({"name": os.path.relpath(p, d), "size": os.path.getsize(p),
                          "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))})
    tasks = C.read_json(os.path.join(d, "tasks.json"), None)
    tl = tasks if isinstance(tasks, list) else (tasks or {}).get("tasks", []) if isinstance(tasks, dict) else []
    ready = C.read_json(os.path.join(d, "ready.json"), None) or {}
    owner = os.path.basename(os.path.dirname(d))
    summary = _run_summary(d)
    by_n, by_branch = pr_states(rid)
    summary.update(run_life(summary, by_n, by_branch, _lazy_branches(rid)))
    if owner != rid:  # opened from another repo it has tasks for: that repo's part of it
        tl = [t for t in _tasks(d) if repo_matches(rid, t.get("repo"))]
        summary = _for_repo(summary, tl, d, rid)
        ready = {}  # its checks ran in the owner's repo, on the owner's code
    summary["current"] = owner == rid and C.read_text(C.lfg_path("runs", rid, "CURRENT")).strip() == run
    return dict(summary, files=files, tasks_list=tl, owner_name=_repo_name(owner) if owner != rid else "",
                checks=[dict({k: c.get(k) for k in ("name", "cmd", "exit", "seconds")},
                             tail=str(c.get("tail") or "")[-2000:]) for c in ready.get("checks", [])])


def run_file(rid, run, name):
    base = os.path.realpath(_run_dir(rid, run) or C.lfg_path("runs", rid, run))
    p = os.path.realpath(os.path.join(base, name))
    if not p.startswith(base + os.sep) or not os.path.isfile(p):
        return {"text": "not found"}
    with open(p, errors="replace") as fh:
        return {"text": fh.read(400000), "name": name}


# ---------------------------------------------------------------- code-review-graph

def code(rid, full=True):
    db = D.crg_db(rid)
    if not db:
        return _na("No code-review-graph data yet. Run `lfg graphs ensure` in the repo.")
    root = repo_root(rid)
    def q(sql, *a):
        return db.execute(sql, a).fetchall()
    try:
        meta = dict(q("SELECT key, value FROM metadata WHERE key IN ('last_updated','git_branch','git_head_sha',"
                      "'last_build_type','build_state')"))
        cov = dict(q("SELECT test_coverage, count(*) FROM risk_index GROUP BY 1"))
        out = {"available": True, "meta": meta,
               "nodes": dict(q("SELECT kind, count(*) FROM nodes GROUP BY 1")),
               "edges": dict(q("SELECT kind, count(*) FROM edges GROUP BY 1")),
               "flows": q("SELECT count(*) FROM flows")[0][0],
               "communities": q("SELECT count(*) FROM communities")[0][0],
               "coverage": {"tested": cov.get("tested", 0), "untested": cov.get("untested", 0)},
               "security_untested": q("SELECT count(*) FROM risk_index WHERE security_relevant=1 AND "
                                      "test_coverage='untested'")[0][0]}

        def sym(qn):
            f, s = D._qual(qn, root)
            return {"file": f, "symbol": s}

        lim = 60 if full else 6
        hot = [dict(sym(r[0]), risk=round(r[1], 2), callers=r[2], coverage=r[3], security=bool(r[4]))
               for r in q("SELECT qualified_name, risk_score, caller_count, test_coverage, security_relevant FROM "
                          "risk_index ORDER BY risk_score DESC, caller_count DESC LIMIT ?", lim * 4)]
        out["hotspots"] = [h for h in hot if not D.is_test(h["file"])][:lim]  # tests aren't where changes reach
        if not full:
            return out
        out["languages"] = dict(q("SELECT COALESCE(language,'?'), count(*) FROM nodes WHERE kind='File' "
                                  "GROUP BY 1 ORDER BY 2 DESC LIMIT 12"))
        out["flow_list"] = [{"name": r[0], "nodes": r[1], "files": r[2], "criticality": round(r[3], 2),
                             "depth": r[4], "entry": D._short(r[5] or "", root)}
                            for r in q("SELECT f.name, f.node_count, f.file_count, f.criticality, f.depth, "
                                       "n.file_path FROM flows f LEFT JOIN nodes n ON n.id=f.entry_point_id "
                                       "ORDER BY f.criticality DESC LIMIT 60")]
        out["community_list"] = [{"name": r[0], "size": r[1], "cohesion": round(r[2], 2), "language": r[3],
                                  "purpose": r[4] or r[6] or "", "key_symbols": json.loads(r[5] or "[]")[:6]}
                                 for r in q("SELECT c.name, c.size, c.cohesion, c.dominant_language, s.purpose, "
                                            "s.key_symbols, c.description FROM communities c LEFT JOIN "
                                            "community_summaries s ON s.community_id=c.id ORDER BY c.size DESC")]
        out["large_functions"] = [{"symbol": r[0], "file": D._short(r[1], root), "lines": r[2], "kind": r[3]}
                                  for r in q("SELECT name, file_path, line_end-line_start+1 AS n, kind FROM nodes "
                                             "WHERE kind IN ('Function','Class') AND line_end IS NOT NULL "
                                             "ORDER BY n DESC LIMIT 25")]
        out["graph_html"] = bool(D.data(rid, "crg") and glob.glob(D.data(rid, "crg", "*.html")))
        return out
    finally:
        db.close()


# ---------------------------------------------------------------- graphify

def architecture(rid, full=True):
    g = D.graphify_graph(rid)
    if not g:
        return _na("No graphify graph yet. Run `lfg graphs ensure` in the repo.")
    nodes = g.get("nodes", [])
    deg = g["_degree"]
    byid = {n["id"]: n for n in nodes}
    names = D._area_names(g)  # "Community 12" / "__init__.py" -> the area's shared folder
    for n in nodes:
        n["community_name"] = names.get(n.get("community_name"), n.get("community_name"))
    comm = collections.Counter(n.get("community_name") or "?" for n in nodes)
    gods = [byid[i] for i, _ in deg.most_common(80) if i in byid and byid[i].get("file_type") == "code"][:25]
    out = {"available": True, "nodes": len(nodes), "links": len(g.get("links", [])), "communities": len(comm),
           "types": dict(collections.Counter(n.get("file_type") for n in nodes)),
           "commit": g.get("built_at_commit"),
           "gods": [{"label": n.get("label"), "edges": deg[n["id"]], "file": n.get("source_file"),
                     "area": n.get("community_name")} for n in (gods if full else gods[:6])]}
    if not full:
        return out
    files = collections.defaultdict(collections.Counter)
    for n in nodes:
        if n.get("source_file"):
            files[n.get("community_name") or "?"][n["source_file"]] += 1
    out["community_list"] = [{"name": c, "size": s, "files": [f for f, _ in files[c].most_common(3)]}
                             for c, s in comm.most_common(60)]
    rel = collections.Counter(e.get("relation") for e in g.get("links", []))
    out["relations"] = dict(rel.most_common(10))
    notes = [n for n in nodes if n.get("file_type") == "rationale" and not D.is_test(n.get("source_file") or "")]
    out["rationale_total"] = len(notes)
    out["rationale"] = [{"note": n.get("label"), "file": n.get("source_file"),
                         "line": str(n.get("source_location") or "").lstrip("Ll")} for n in notes][:100]
    s = D.report_sections(rid)
    out["report"] = {k: D.section(s, k) for k in ("Corpus Check", "Summary", "Surprising", "Import Cycles")}
    out["graph_html"] = bool(D.data(rid, "graphify")) and os.path.exists(D.data(rid, "graphify", "graph.html"))
    out["callflow_html"] = bool(D.data(rid, "graphify")) and os.path.exists(D.data(rid, "graphify", "callflow.html"))
    return out


# ---------------------------------------------------------------- docs + playbooks

DOC_SOURCES = [  # (id, title, base dir: relative to ~/.lfg, or {graphify}/{crg} = the repo's graph data, description)
    ("intro", "Getting started", "{intro}", "what LFG is and how to use it"),
    ("playbooks", "Start here", "playbooks/{rid}", "onboarding tour, landmines, test gaps, incident runbooks"),
    ("guides", "From your docs", "{graphify}/wiki", "what your team's own docs and runbooks say"),
    ("gwiki", "Parts of the code", "{graphify}/wiki", "one page per area of the code, largest first"),
    ("repo", "Decisions", "repos/{rid}/docs", "decision records and notes LFG keeps for this project"),
]


INTRO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_assets", "intro")


def _doc_base(rid, base):
    if base == "{intro}":
        return INTRO_DIR
    for kind in ("graphify", "crg"):
        tag = "{%s}" % kind
        if base.startswith(tag):
            d = D.data(rid, kind)
            return d + base[len(tag):] if d else ""
    return C.lfg_path(base.format(rid=rid))


def _title(path):
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                if line.startswith("# "):
                    return line[2:].strip()[:120]
    except OSError:
        pass
    return os.path.splitext(os.path.basename(path))[0].replace("_", " ")


MIN_AREA_NODES = 10
THIRD_PARTY = D.THIRD_PARTY


DOC_FOLDERS = {"adr": "Decisions"}
WIKI = (("onboarding.md", "Onboarding tour"), ("landmines.md", "Landmines"), ("test-gaps.md", "Test gaps"),
        ("incidents.md", "Incident runbooks"))


def _doc_files(base, prefix="", top=True):
    """Markdown under base as {items, folders}: one level of folders, titles from each file's first heading. Paths
    are prefix + the path under base."""
    d = base
    items, folders = [], []
    if not os.path.isdir(d):
        return {"items": items, "folders": folders}
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if name.startswith("."):
            continue
        if os.path.isdir(p):
            if top and name == "branches":
                continue
            sub = sorted(glob.glob(os.path.join(p, "**", "*.md"), recursive=True))
            if sub:
                folders.append({"name": DOC_FOLDERS.get(name, name.replace("-", " ").replace("_", " ").capitalize()),
                                "items": [{"src": "repo", "path": prefix + os.path.relpath(x, base), "title": _title(x)}
                                          for x in sub]})
        elif name.endswith(".md"):
            items.append({"src": "repo", "path": prefix + name,
                          "title": "Glossary" if name == "GLOSSARY.md" else _title(p)})
    return {"items": items, "folders": folders}


def docs_index(rid):
    """The Docs page as a tree. Root: what applies to the whole project (LFG's wiki: onboarding, landmines, test
    gaps, playbooks /learn wrote; the glossary, decisions and guides the user asked for). Then one folder per branch
    for docs about that branch's work (`lfg repo docs --branch`). The repo's own markdown and graphify's per-cluster
    pages aren't listed: the first is in the repo already, the second isn't written for people."""
    base = C.lfg_path("repos", rid, "docs")
    root = _doc_files(base)
    intro = [{"src": "intro", "path": n, "title": _title(os.path.join(INTRO_DIR, n))}
             for n in sorted(os.listdir(INTRO_DIR)) if n.endswith(".md")] if os.path.isdir(INTRO_DIR) else []
    code = []  # graphify's wiki: its overview, then one page per area of the code, largest first
    gw = _doc_base(rid, "{graphify}/wiki")
    if gw and os.path.isfile(os.path.join(gw, "index.md")):
        code.append({"src": "gwiki", "path": "index.md", "title": "Overview"})
    code += [{"src": "gwiki", "path": pg["path"], "title": pg["title"]}
             for pg in D.wiki_pages(rid) if pg["kind"] == "code" and pg["nodes"] >= MIN_AREA_NODES]
    gout = _doc_base(rid, "{graphify}")
    views = [{"src": "view", "path": k, "title": t} for k, t, f in (("callflow", "How calls flow", "callflow.html"),
                                                                     ("architecture", "Map of the code", "graph.html"))
             if gout and os.path.isfile(os.path.join(gout, f))]
    gb = git_branches(repo_root(rid))
    out = []
    bdir = os.path.join(base, "branches")
    for slug in sorted(os.listdir(bdir)) if os.path.isdir(bdir) else []:
        d = os.path.join(bdir, slug)
        if not os.path.isdir(d):
            continue
        name = (C.read_text(os.path.join(d, ".branch")) or slug).strip() or slug
        tree = _doc_files(d, "branches/%s/" % slug, top=False)  # paths from the docs root, as `doc` reads them
        if not tree["items"] and not tree["folders"]:
            continue
        state = "" if gb is None else ("current" if name == gb["current"] else "default" if name == gb["default"]
                                       else "merged" if name in gb["merged"] else "" if name in gb["local"]
                                       else "deleted")
        out.append(dict(tree, name=name, state=state))
    out.sort(key=lambda b: (b["state"] != "current", b["state"] != "default", b["name"].lower()))
    return {"intro": intro, "code": code, "views": views, "root": root, "branches": out, "state": D.docs_state(rid),
            "due": D.due(rid), "paths": {"project": base, "branches": bdir}}


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:60] or "untitled"


def _check_md(title, text, limit=200_000):
    from . import settings as S
    title, text = (title or "").strip(), (text or "").replace("\r\n", "\n")
    if not title:
        raise S.Invalid("give it a title")
    if len(text) > limit:
        raise S.Invalid("that's over %d KB; split it into smaller docs" % (limit // 1000))
    if S._secret_kinds(text):
        raise S.Invalid("it looks like it contains a password or key; secrets never go in docs")
    return title, text


def doc_save(rid, body):
    """A doc the user wrote or edited in the dashboard: about the whole project, or about one branch's work.
    Editing keeps the file; a new doc gets a file named after its title (never overwriting another)."""
    from . import settings as S
    title, text = _check_md(body.get("title"), body.get("text"))
    base = C.lfg_path("repos", rid, "docs")
    if not text.lstrip().startswith("# "):
        text = "# %s\n\n%s" % (title, text.lstrip())
    path = (body.get("path") or "").strip()
    if path:  # an edit
        full = os.path.realpath(os.path.join(base, path))
        if not path.endswith(".md") or not full.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(full):
            raise S.Invalid("that doc can't be edited here")
    else:
        if body.get("where") == "branch":
            branch = (body.get("branch") or C.git_branch(repo_root(rid)) or "").strip()
            if not branch or branch.startswith("detached@"):
                raise S.Invalid("pick a branch, or save it to the project instead")
            d = C.branch_docs_dir(rid, branch)
        else:
            d = C.repo_docs_dir(rid)
        full, n = os.path.join(d, _slug(title) + ".md"), 2
        while os.path.exists(full):
            full, n = os.path.join(d, "%s-%d.md" % (_slug(title), n)), n + 1
        path = os.path.relpath(full, base)
    C.write_text(full, text.rstrip() + "\n")
    C.audit("doc_saved", {"repo": rid, "path": path})
    return {"src": "repo", "path": path}


# ---------------------------------------------------------------- knowledge the user pastes in (Markdown files)

KNOWLEDGE_KINDS = ("note", "decision", "lesson", "rule")


def knowledge_dir(rid):
    return C.lfg_path("repos", rid, "knowledge")


def knowledge_list(rid):
    d = knowledge_dir(rid)
    out = []
    for n in sorted(os.listdir(d), reverse=True) if os.path.isdir(d) else []:
        if not n.endswith(".md"):
            continue
        text = C.read_text(os.path.join(d, n))
        m = re.match(r"^# (.+)\n(?:\n?> (\w+) · (\S+)\n)?", text)
        out.append({"file": n, "title": m.group(1) if m else n[:-3],
                    "kind": m.group(2) if m and m.group(2) else "note",
                    "date": m.group(3) if m and m.group(3) else n[:10], "text": text})
    return out


def knowledge_add(rid, body):
    from . import settings as S
    title, text = _check_md(body.get("title"), body.get("text"), limit=100_000)
    if not text.strip():
        raise S.Invalid("write or paste something first")
    kind = body.get("kind") if body.get("kind") in KNOWLEDGE_KINDS else "note"
    day = time.strftime("%Y-%m-%d")
    d = C.ensure_dir(knowledge_dir(rid))
    full, n = os.path.join(d, "%s-%s.md" % (day, _slug(title))), 2
    while os.path.exists(full):
        full, n = os.path.join(d, "%s-%s-%d.md" % (day, _slug(title), n)), n + 1
    body_md = re.sub(r"^# .*\n+", "", text.lstrip(), count=1)
    C.write_text(full, "# %s\n\n> %s · %s\n\n%s\n" % (title, kind, day, body_md.rstrip()))
    C.audit("knowledge_added", {"repo": rid, "kind": kind})
    return {"file": os.path.basename(full)}


def doc(rid, src, path):
    base = dict((s[0], s[2]) for s in DOC_SOURCES).get(src)
    if not base or not path.endswith(".md") or not _doc_base(rid, base):
        return {"text": "not found"}
    b = os.path.realpath(_doc_base(rid, base))
    p = os.path.realpath(os.path.join(b, path))
    if not p.startswith(b + os.sep) or not os.path.isfile(p):
        return {"text": "not found"}
    with open(p, errors="replace") as fh:
        return {"text": fh.read(600000), "src": src, "path": path}


# ---------------------------------------------------------------- Help: LFG's own docs, skills and agents

# The installed LFG folder (~/.lfg, or the source checkout when run from there): holds plugin/, docs/, CONTRACT.md.
LFG_ROOT = C.LFG_ROOT
GUIDE_DOCS = (("sharing", "Share LFG with your team", "docs/sharing.md"),
              ("dashboard", "The dashboard", "docs/dashboard.md"),
              ("cli", "CLI reference", "CONTRACT.md"))


def _frontmatter(path):
    """`name` / `description` (incl. folded `>` blocks) from a SKILL.md or agent .md header."""
    try:
        with open(path, errors="replace") as fh:
            lines = fh.read(8000).splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    out, key = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            out[key] = "" if val in (">", "|", ">-", "|-") else val.strip("\"'")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def guide():
    plugin = os.path.join(LFG_ROOT, "plugin")
    skills = []
    for p in sorted(glob.glob(os.path.join(plugin, "skills", "*", "SKILL.md"))):
        fm = _frontmatter(p)
        skills.append({"name": "/lfg:" + (fm.get("name") or os.path.basename(os.path.dirname(p))),
                       "description": fm.get("description", "")})
    agents = []
    for p in sorted(glob.glob(os.path.join(plugin, "agents", "*.md"))):
        fm = _frontmatter(p)
        agents.append({"name": fm.get("name") or os.path.basename(p)[:-3], "description": fm.get("description", ""),
                       "model": fm.get("model", ""), "tools": fm.get("tools", "")})
    rules = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(plugin, "rules", "*.md")))
    manifest = C.read_json(os.path.join(plugin, ".claude-plugin", "plugin.json")) or {}
    return {"version": manifest.get("version", "?"), "root": LFG_ROOT,
            "has_guide": os.path.isfile(os.path.join(LFG_ROOT, "docs", "guide.html")),
            "docs": [{"id": i, "title": t} for i, t, f in GUIDE_DOCS if os.path.isfile(os.path.join(LFG_ROOT, f))],
            "skills": skills, "agents": agents, "rules": rules}


def guide_doc(doc_id):
    rel = dict((i, f) for i, _, f in GUIDE_DOCS).get(doc_id)
    if not rel:
        return {"text": "not found"}
    with open(os.path.join(LFG_ROOT, rel), errors="replace") as fh:
        return {"text": fh.read(400000)}


# ---------------------------------------------------------------- Omnigraph: dev-graph, Linear mirror, second-brain

def _og(fn, *a):
    from . import omnigraph as OG
    try:
        return fn(OG, *a)
    except Exception as e:
        return {"error": "%s" % (getattr(e, "reason", None) or type(e).__name__)}


def _og_ready(name):
    from . import omnigraph as OG
    try:
        return OG.ready(name, timeout=1)
    except Exception:
        return False


def og_access(name):
    """None when `name` answers and accepts LFG's token; otherwise what's wrong and the fix, in plain words.
    Cached briefly, since every LFG page asks."""
    def check():
        if not _og_ready(name):
            from . import setup as SU
            return ("%s isn't running. %s" % (name, "Add the Knowledge pack (`lfg add knowledge`)." if not
                                              SU.pack_on("knowledge") else "Run `lfg omnigraph restart %s`." % name))
        r = _og(lambda OG: OG.invoke(name, "ready" if name == "dev-graph" else "notes_recent"))
        err = r.get("error") if isinstance(r, dict) else None
        if err and re.search(r"unauthori[sz]ed|forbidden|401|403", str(err), re.I):
            return ("%s is running but refused LFG's access token: another %s server may be using its port, or the "
                    "tokens changed. Run `lfg omnigraph setup`." % (name, name))
        return "%s answered with an error: %s" % (name, err) if err else None
    return cached("og-access:" + name, 30, check)


def _list(name, node, fields, order=None, limit=200):
    var = "$x"
    q = "query l() { match { %s: %s } return { %s }%s limit %d }" % (
        var, node, ", ".join("%s.%s" % (var, f) for f in fields),
        " order { %s.%s desc }" % (var, order) if order else "", limit)
    return _og(lambda OG: OG.read(name, q, "l"))


def _inv(name, stored, params=None):
    return _og(lambda OG: OG.invoke(name, stored, params))


def _rows(v):
    return v if isinstance(v, list) else []


STALE_DAYS = 14
TERMINAL = {"done", "canceled", "duplicate"}
STUB = re.compile(r"^\s*(?:Repo:\s*\S+\s+Run\s+\S+?\.?(?:\s+Brief ACs:\s*[\d,\s]+)?)?\s*$")  # empty or a bare pointer
REPO_LINE = re.compile(r"^Repo:\s*([\w.-]+?)\.?(?:\s|$)", re.M)
REF_SLUG = re.compile(r"^[a-z][a-z0-9]+-\d+$")  # a tracker key as LFG stores it: ATO-4225 -> ato-4225


def _issue_key(key):
    """Compare issues by key: `ATO-4225`, `ato-4225`, `aeginv-001` and `iss-aeginv-001` are told apart only by the
    iss- prefix and case, which differ with how each was filed."""
    from . import tracker as T
    try:
        slug = T.slug_for(str(key))
    except SystemExit:
        return ""
    return slug[4:] if slug.startswith("iss-") else slug


def _run_links(rid):
    """What this repo's runs say about issues: [(branch, issue keys they name, {task issue key: passed}, text)]."""
    out = []
    for d in _run_files(rid, ""):
        meta = C.read_json(os.path.join(d, "run.json"), {}) or {}
        tasks = C.read_json(os.path.join(d, "tasks.json"), []) or []
        tasks = tasks.get("tasks", []) if isinstance(tasks, dict) else tasks
        tasks = {_issue_key(t.get("id")): t for t in tasks if isinstance(t, dict) and t.get("id")}
        done = {k: bool(t.get("passes")) for k, t in tasks.items()}
        named = {_issue_key(meta["issue"])} if meta.get("issue") else set()
        text = " ".join(C.read_text(os.path.join(d, f)) for f in ("01-brief.md", "02-design.md")).lower()
        out.append({"branch": meta.get("branch") or "", "named": (named | set(done)) - {""}, "done": done,
                    "text": text, "tasks": tasks, "run": os.path.basename(d), "dir": d, "own": named})
    for _, d, mine in shared_runs(rid):  # another repo's run, only its tasks for this repo; no branch here
        tasks = {_issue_key(t.get("id")): t for t in mine if t.get("id")}
        out.append({"branch": "", "named": set(tasks) - {""}, "done": {k: bool(t.get("passes")) for k, t in
                                                                     tasks.items()},
                    "text": "", "tasks": tasks, "run": os.path.basename(d), "dir": d, "own": set()})
    return out


def issue_links(rid, issues):
    """Which of `issues` belong to repo `rid`, and on which branches. dev-graph issues carry no repo, so this comes
    from local evidence: a run of this repo names the issue (run.json, a task in tasks.json, its brief or design;
    the issue is on that run's branch), or a local branch's name holds its tracker key (ato-4232 in
    keshav/ato-4232-...). An issue whose description says `Repo: <name>` belongs to that repo only.
    Returns ({slug: set(branches)}, {slug: True when a run's task for it passed},
    {slug: (run, description, done-when) from the run's tasks.json or brief})."""
    from . import tracker as T
    links, passed, text_for = collections.defaultdict(set), {}, {}
    for r in _run_links(rid):
        branch, named, done, text = r["branch"], r["named"], r["done"], r["text"]
        for i in issues:
            slug = i.get("slug") or ""
            key = _issue_key(slug)
            if key in done:
                passed[slug] = passed.get(slug, False) or done[key]
            if key in r["tasks"] and slug not in text_for:
                text_for[slug] = (r["run"],) + T.task_text(r["tasks"][key])
            elif key in r["own"] and slug not in text_for:
                text_for[slug] = (r["run"], _about(r["dir"])[1], T.brief_section(r["dir"], "Acceptance criteria"))
            if key in named or (len(key) > 5 and re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(key), text)):
                links[slug].add(branch)
    root = repo_root(rid)
    for i in issues:  # an issue that names its repo ("Repo: aegis-agent.") goes there, whichever run filed it
        m = REPO_LINE.search(i.get("description") or "")
        if m and repo_matches(rid, m.group(1)):
            links.setdefault(i["slug"], set())
        elif m:
            links.pop(i.get("slug"), None)
    gb = git_branches(root) or {}
    for i in issues:
        keys = {k.lower() for k in (i.get("slug"), i.get("legacyRef")) if k and REF_SLUG.match(k.lower())}
        for b in gb.get("local", []):
            if any(re.search(r"(?<![a-z0-9])%s(?![0-9])" % re.escape(k), b.lower()) for k in keys):
                links[i["slug"]].add(b)
    return links, passed, text_for


def issues(rid=None, branch=None):
    why = og_access("dev-graph")
    if why:
        return _na(why)
    ws = C.config()["linear"].get("workspace") or ""
    allq = _list("dev-graph", "Issue", ["slug", "title", "description", "acceptanceCriteria", "status", "priority",
                                        "issueType", "legacyRef", "updatedAt"], "updatedAt", 300)
    every = _rows(allq)
    links, passed, text_for = issue_links(rid, every) if rid else ({}, {}, {})
    keep = []
    for i in every:
        on = links.get(i.get("slug"))
        if rid and on is None:
            continue
        if branch and (branch == UNRECORDED and "" not in on or branch != UNRECORDED and branch not in on):
            continue
        i = dict(i, branches=sorted(b for b in on or () if b))
        if passed.get(i["slug"]) and i.get("status") not in TERMINAL:  # the run finished it; dev-graph lags
            i.update(graph_status=i.get("status"), status="done")
        run, desc, done_when = text_for.get(i["slug"], ("", "", ""))
        if run and (desc and STUB.match(i.get("description") or "") or done_when and not i.get("acceptanceCriteria")):
            if desc and STUB.match(i.get("description") or ""):  # filed without its text: show the run's
                i["description"] = desc
            i["acceptanceCriteria"] = i.get("acceptanceCriteria") or done_when
            i["text_from"] = run
        keep.append(i)
    open_ = {i["slug"] for i in keep if i.get("status") not in TERMINAL}

    def only(rows):
        seen, out = set(), []
        for r in rows:  # one row per blocker comes back: list each issue once
            if r.get("slug") in open_ and r["slug"] not in seen:
                seen.add(r["slug"])
                out.append(r)
        return out
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - STALE_DAYS * 86400))
    out = {"available": True, "linear_workspace": ws, "issues": keep,
           "error": allq.get("error") if isinstance(allq, dict) else None,
           "ready": only(_rows(_inv("dev-graph", "ready"))), "blocked": only(_rows(_inv("dev-graph", "blocked"))),
           "stale": [i for i in keep if i["slug"] in open_ and str(i.get("updatedAt") or "") < cutoff],
           "stale_days": STALE_DAYS, "hidden": len(every) - len(keep),
           "epics": _rows(_inv("dev-graph", "open_epics")),
           "prs": _rows(_list("dev-graph", "PR", ["slug", "title", "status", "githubRef", "updatedAt"],
                              "updatedAt", 100))}
    out["by_status"] = dict(collections.Counter(i.get("status") or "?" for i in keep))
    return out


def knowledge():
    why = og_access("dev-graph")
    if why:
        return _na(why)
    return {
        "available": True,
        "decisions": _rows(_list("dev-graph", "Decision", ["slug", "title", "status", "context", "decision",
                                                           "consequences", "createdAt"], "createdAt")),
        "principles": _rows(_list("dev-graph", "Principle", ["slug", "statement", "polarity", "status",
                                                             "rationale", "correctAlternative", "specRef"],
                                  "updatedAt")),
        "invariants": _rows(_list("dev-graph", "Invariant", ["slug", "statement", "status", "guardRef", "specRef"],
                                  "updatedAt")),
        "unheld": _rows(_inv("dev-graph", "unheld_invariants")),
        "gaps": _rows(_list("dev-graph", "Gap", ["slug", "title", "state", "currentBehavior", "targetBehavior",
                                                 "updatedAt"], "updatedAt")),
        "learnings": _rows(_list("dev-graph", "Learning", ["slug", "title", "learningKind", "body", "createdAt"],
                                 "createdAt")),
        "incidents": _rows(_list("dev-graph", "Incident", ["slug", "title", "severity", "status", "startedAt"],
                                 "startedAt")),
        "components": _rows(_list("dev-graph", "Component", ["slug", "name", "criticality", "summary"],
                                  "updatedAt")),
    }


def brain():
    why = og_access("second-brain")
    if why:
        return _na(why)
    notes = _rows(_list("second-brain", "Note", ["slug", "name", "kind", "content", "when", "tags"], "when", 100))
    return {"available": True, "notes": notes,
            "kinds": dict(collections.Counter(n.get("kind") or "?" for n in notes)),
            "preferences": _rows(_inv("second-brain", "notes_by_kind", {"kind": "preference"})),
            "insights": _rows(_inv("second-brain", "notes_by_kind", {"kind": "insight"})),
            "questions": _rows(_inv("second-brain", "open_questions")),
            "principles": _rows(_inv("second-brain", "principles_all")),
            "tasks": _rows(_inv("second-brain", "tasks_next")),
            "projects": _rows(_inv("second-brain", "projects_active"))}


# ---------------------------------------------------------------- reviews + security

def _mtime_iso(p):
    """When a file was written, for results that don't record it themselves."""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(os.path.getmtime(p)))
    except OSError:
        return None


def _part_files(d, name):
    """{repo label: path} for `<stem>-<label><ext>` beside `name` in run dir `d`: a stage's result for one repo's
    part of a run that spans repos (05-secure-portal.json is the portal's security check)."""
    stem, ext = os.path.splitext(name)
    out = {}
    for p in glob.glob(os.path.join(d, "%s-*%s" % (stem, ext))):
        out[os.path.basename(p)[len(stem) + 1:-len(ext) or None]] = p
    return out


def stage_files(rid, name, branch=None):
    """Newest first: this repo's `name` (e.g. 05-secure.json) from its own runs, plus the per-repo variants
    (05-secure-<repo>.json) meant for it, from its own runs and, under all branches, from runs filed under other
    repos that have tasks for it. Variants for other repos are left to those repos."""
    out = list(_run_files(rid, name, branch))
    dirs = list(_run_files(rid, "", branch)) + ([d for _, d, _ in shared_runs(rid)] if not branch else [])
    for d in dirs:
        out += [p for label, p in _part_files(d, name).items() if repo_matches(rid, label)]
    return sorted(set(out), key=lambda p: (os.path.basename(os.path.dirname(p)), os.path.getmtime(p)), reverse=True)


def reviews(rid, branch=None):
    findings, blocked, verdicts = [], [], []
    fb = C.read_json(C.lfg_path("feedback", rid + ".json"), {}) or {}
    for p in stage_files(rid, "06-review.json", branch):
        rv = C.read_json(p, {}) or {}
        run = os.path.basename(os.path.dirname(p))
        verdicts.append({"run": run, "verdict": rv.get("verdict"), "findings": len(rv.get("findings", []))})
        for f in rv.get("findings", []):
            v = fb.get("%s/%s" % (run, f.get("id"))) or fb.get(f.get("id")) or {}
            mine = not v.get("run") or v.get("run") == run
            findings.append(dict(f, run=run, feedback=v.get("verdict") if mine else None))
    for e in _audit(400):
        if e.get("event") == "blocked":
            blocked.append(e)
    rules = dict(collections.Counter(str(e.get("rule")) for e in blocked))
    return {"findings": findings, "verdicts": verdicts, "blocked": blocked[:200], "blocked_by_rule": rules}


def security(rid, branch=None):
    sec, pen = [], []
    for p in stage_files(rid, "05-secure.json", branch):
        s = C.read_json(p, {}) or {}
        inv = s.get("inventory") or {}
        sec.append({"run": os.path.basename(os.path.dirname(p)), "ts": s.get("ts") or _mtime_iso(p),
                    "verdict": _verdict(s.get("verdict")),
                    "blocking": _blocking(s), "mode": s.get("mode"), "scope": s.get("scope"),
                    "inventory": {k: len(v) for k, v in inv.items() if isinstance(v, list)},
                    "scanners": [{"tool": x.get("tool"), "exit": x.get("exit"), "note": x.get("note")}
                                 for x in s.get("scanners", [])],
                    "findings": s.get("findings", [])[:200]})
    for p in stage_files(rid, "05-pentest.json", branch):
        s = C.read_json(p, {}) or {}
        keep = ("mode", "model", "status", "next_steps", "preflight_failures")
        pen.append({"run": os.path.basename(os.path.dirname(p)), **{k: s.get(k) for k in keep},
                    "summary": s.get("summary") or s.get("conclusion")})
    ships = []
    for p in stage_files(rid, "07-shipcheck.json", branch)[:10]:
        s = C.read_json(p, {}) or {}
        checks = shipcheck_items(s)
        counted = [c for c in checks if c["ok"] is not None]
        ships.append({"run": os.path.basename(os.path.dirname(p)), "pass": s.get("pass"),
                      "ts": s.get("ts") or _mtime_iso(p),
                      "ok": sum(1 for c in counted if c["ok"]), "total": len(counted),
                      "manual": [c["check"] for c in checks if c.get("manual")],
                      "failed": [c["check"] for c in checks if c["ok"] is False],
                      "checks": checks, "note": (s.get("part_a") or {}).get("note") or ""})
    return {"secure": sec, "pentest": pen, "shipcheck": ships, "sonar": sonar_view(rid)}


def sonar_view(rid):
    """The local SonarQube's last scan of this repo, for the Checks page (None when the pack is off)."""
    from . import setup as SU
    from . import sonar as SQ
    if not SU.pack_on("sonarqube") and not SQ.last(rid):
        return None
    res = SQ.last(rid) or {}
    run = C.read_json(C.lfg_path("repos", rid, "sonar-running.json"), None)
    alive = False
    if isinstance(run, dict):
        try:
            os.kill(int(run.get("pid")), 0)
            alive = True
        except (OSError, TypeError, ValueError):
            pass
    return {"server": SQ.server_state(), "scanning": run.get("started") if alive else None,
            "ts": res.get("ts"), "gate": res.get("gate"), "conditions": res.get("conditions") or [],
            "measures": res.get("measures") or {}, "url": res.get("url"), "base": res.get("base"),
            "root": res.get("root"), "total": res.get("total", 0), "mine": res.get("mine", 0),
            "branch": res.get("branch"), "head": res.get("head"), "base_name": res.get("base_name"),
            "rest_by_kind": dict(collections.Counter(i.get("kind") for i in res.get("issues") or []
                                                     if not i.get("mine"))),
            "changed_files": res.get("changed_files", 0),
            "issues": [i for i in res.get("issues") or [] if i.get("mine")][:300] +
                      [i for i in res.get("issues") or [] if not i.get("mine")][:200]}


def shipcheck_items(s):
    """Part A (Docker) checks and the shipping checklist of a 07-shipcheck.json as one list of
    {check, ok: True|False|None, detail, part, manual}. ok None = not applicable or not run."""
    out = []
    for c in (s.get("part_a") or {}).get("checks", []):
        warn = c.get("severity") == "warn"
        out.append({"check": c.get("check"), "ok": c.get("ok") if not (warn and c.get("ok") is False) else None,
                    "detail": str(c.get("detail") or "")[-1500:], "part": "container",
                    "warning": warn and c.get("ok") is False})
    for i in s.get("checklist") or (s.get("part_b") or {}).get("checks", []):
        st = i.get("status")
        ok = i.get("ok") if "ok" in i else True if st == "pass" else False if st == "fail" else None
        out.append({"check": i.get("requirement") or i.get("check"), "ok": ok, "detail": i.get("detail") or "",
                    "part": "checklist", "manual": st == "manual", "status": st})
    return out


# ---------------------------------------------------------------- usage + Headroom

def _headroom():
    if not C.which("headroom"):
        return _na("headroom is not installed")
    cp = C.run(["headroom", "savings", "--json"], timeout=20)
    try:
        d = json.loads(cp.stdout)
    except ValueError:
        return _na("headroom savings returned no data")
    d.pop("path", None)
    d["available"] = True
    return d


def headroom():
    return in_background("headroom", 60, _headroom, "checking Headroom")


def _tokensave_uploads():
    """tokensave can send token counts to a worldwide counter; LFG only runs it with that switched off."""
    cfg = C.read_text(os.path.join(C.HOME, ".tokensave", "config.toml"))
    m = re.search(r"^\s*upload_enabled\s*=\s*(\w+)", cfg, re.M)
    return not m or m.group(1).lower() != "false"


_BUSY = {}


def in_background(key, ttl, fn, doing):
    """Cached value of fn(), refreshed in a background thread with at most one run per key in flight, so a slow or
    stuck external tool never holds up a page. Until the first run finishes, says it is pending."""
    with _CLOCK:
        hit = _CACHE.get(key)
        lock = _BUSY.setdefault(key, threading.Lock())
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    if lock.acquire(blocking=False):
        def work():
            try:
                val = fn()
                with _CLOCK:
                    _CACHE[key] = (time.time(), val)
            finally:
                lock.release()
        threading.Thread(target=work, daemon=True).start()
    return hit[1] if hit else {"available": False, "pending": True, "why": doing}


def spend():
    """Dollars spent, as tokensave computes them from Claude Code's own session logs (all projects)."""
    return in_background("spend", 300, _spend, "working out costs")


def _spend():
    if not C.which("tokensave"):
        return _na("tokensave is not installed")
    if _tokensave_uploads():
        return _na("tokensave's upload counter is on; run `tokensave disable-upload-counter` to show costs here")
    out = {"available": True}
    for rng in ("today", "7d", "30d"):
        cp = C.run(["tokensave", "cost", rng, "--by-model", "--export", "json"], timeout=20)
        text = cp.stdout or ""
        try:
            d = json.loads(text[text.index("{"):])
        except ValueError:
            return _na("tokensave cost returned no data")
        out[rng] = round(float(d.get("total_cost_usd") or 0), 2)
        if rng == "30d":
            out["models"] = [{"model": m.get("model"), "usd": round(float(m.get("cost") or 0), 2)}
                             for m in d.get("by_model") or [] if (m.get("cost") or 0) >= 0.01]
    return out


def _all_usage(days=30):
    from . import sessions as SS
    d = SS.usage(days=days)
    d["available"] = True
    return d


def headroom_detail(days=30):
    from . import hrstats
    days = 90 if days > 30 else 30
    return in_background("headroom_detail_%d" % days, 120, lambda: dict(hrstats.summary(days), available=True),
                         "reading Headroom's logs")


def usage(rid, days=30):
    """Per day, per model and dollars from every Claude Code session's own log (whether or not LFG is on there);
    per-run and per-project rows from LFG's usage.db, which only records repos where LFG is on."""
    p = C.lfg_path("usage.db")
    out = {"rows": [], "days": [], "models": [], "headroom": headroom(), "spend": spend()}
    days = 90 if days > 30 else 30
    every = in_background("all_usage_%d" % days, 120, lambda: _all_usage(days), "adding up usage")
    if every.get("available"):
        out["days"], out["models"] = every["days"], every["models"]
        out["spend"] = {"available": True, "today": every["spend"]["today"], "7d": every["spend"]["7d"],
                        "30d": every["spend"]["30d"], "source": "lfg",
                        "models": [{"model": m["model"], "usd": round(m["usd"], 2)} for m in every["models"]
                                   if m["usd"] >= 0.01]}
    elif every.get("pending"):
        out["spend"] = dict(out["spend"], pending=True) if not out["spend"].get("available") else out["spend"]
    if not os.path.exists(p):
        return out
    db = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    try:
        cols = ["day", "model", "input", "output", "cache_read", "cache_write"]
        out["rows"] = [dict(zip(cols, r)) for r in db.execute(
            "SELECT substr(ts,1,10), model, sum(input), sum(output), sum(cache_read), sum(cache_write) FROM usage "
            "WHERE repo=? GROUP BY 1,2 ORDER BY 1 DESC LIMIT 400", (rid,))]
        days = [dict(zip(["day", "input", "output", "cache_read", "cache_write"], r)) for r in db.execute(
            "SELECT substr(ts,1,10), sum(input), sum(output), sum(cache_read), sum(cache_write) FROM usage "
            "WHERE ts >= date('now','-30 day') GROUP BY 1 ORDER BY 1")]
        models = [dict(zip(["model", "input", "output", "cache_read"], r)) for r in db.execute(
            "SELECT model, sum(input), sum(output), sum(cache_read) FROM usage GROUP BY 1 ORDER BY 2 DESC")]
        if not every.get("available"):
            out["days"], out["models"] = days, models
        out["runs"] = [dict(zip(["run", "input", "output", "cache_read"], r)) for r in db.execute(
            "SELECT COALESCE(run,'(no run)'), sum(input), sum(output), sum(cache_read) FROM usage WHERE repo=? "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 30", (rid,))]
        out["replies"] = _replies(db, rid)
    finally:
        db.close()
    return out


def _replies(db, rid):
    """Whether Claude's replies in this repo said they used LFG (the Stop hook records each reply's `**LFG:**`
    line): counts for the last 30 days, and the latest replies that didn't use LFG or didn't say."""
    try:
        counts = dict(db.execute("SELECT kind, count(*) FROM replies WHERE repo=? AND ts >= date('now','-30 day') "
                                 "GROUP BY 1", (rid,)).fetchall())
        recent = [dict(zip(["ts", "kind", "detail"], r)) for r in db.execute(
            "SELECT ts, kind, detail FROM replies WHERE repo=? AND kind IN ('not-used','missing') "
            "ORDER BY ts DESC LIMIT 15", (rid,))]
    except sqlite3.OperationalError:  # no replies recorded yet
        return {"counts": {}, "recent": []}
    return {"counts": counts, "recent": recent}


# ---------------------------------------------------------------- tools + integrations

def _version(cmd, args=("--version",)):
    if not C.which(cmd):
        return None
    cp = C.run([cmd] + list(args), timeout=20)
    line = ((cp.stdout or cp.stderr or "").strip().splitlines() or [""])[0]
    m = re.search(r"\d+\.\d+(\.\d+)?", line)
    return m.group(0) if m else (line[:40] or "installed")


def _http_ok(u, timeout=1.5):
    try:
        with urllib.request.urlopen(u, timeout=timeout) as r:
            return r.status < 500
    except Exception:
        return False


def _mcp_servers():
    exe = C.which("claude")
    if not exe:
        return {}
    cp = C.run([exe, "mcp", "list"], timeout=90)
    out = {}
    for line in (cp.stdout or "").splitlines():
        m = re.match(r"^([\w.@/-]+): .* - (.+)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


HEADROOM_DOWN = ("The Headroom proxy is down and Claude Code is pointed at it, so terminal sessions can't reach "
                 "Claude: run `lfg headroom restart`")


def _headroom_proxy():
    """Is Claude Code pointed at a local Headroom proxy, and is it answering? Only yes/no ever leaves this function."""
    from . import claudecfg as CC
    from . import headroom as HR
    return bool(HR.routed() or CC.find(tag=HR.ROUTE_TAG)), HR.live(timeout=1)


def _headroom_row(installed, optional):
    routed, live = _headroom_proxy()
    row = {"name": "Headroom", "kind": "Token compression", "ok": installed and (live or not routed),
           "detail": "proxy %s" % ("routing Claude Code" if routed and live else "down, and Claude Code is pointed "
                                   "at it" if routed else "off"), "optional": optional}
    if routed and not live:
        row["problem"] = HEADROOM_DOWN
    return row


def tools():
    def get():
        from . import setup as SU
        from .cli import TOOLS
        rows = []
        for cmd, why, pack in TOOLS:
            rows.append({"tool": cmd, "purpose": why, "pack": pack, "required": SU.pack_on(pack),
                         "installed": bool(SU.which(cmd))})
        versions = {t: _version(t) for t in ("code-review-graph", "graphify", "headroom", "ollama", "docker",
                                              "semgrep", "trivy", "gitleaks", "osv-scanner", "strix", "gh")}
        versions["omnigraph"] = _version("omnigraph", ("version",))
        for r in rows:
            r["version"] = versions.get(r["tool"])
        mcp = _mcp_servers()
        gh = C.run(["gh", "auth", "status"], timeout=15).returncode == 0 if C.which("gh") else False
        pg = C.run(["pgrep", "-qi", "LuLu|Little Snitch"]).returncode == 0
        docker_up = C.run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15).returncode == 0 \
            if C.which("docker") else False
        integrations = [
            {"name": "code-review-graph", "kind": "Code graph (MCP)", "ok": bool(versions["code-review-graph"]),
             "detail": "MCP: provided by the LFG plugin in repos where LFG is on"},
            {"name": "graphify", "kind": "Architecture graph (CLI)", "ok": bool(versions["graphify"]),
             "detail": "v%s, graph in <repo>/graphify-out/ (git-ignored)" % versions["graphify"]},
            {"name": "Omnigraph dev-graph", "kind": "Work + decisions graph", "ok": _og_ready("dev-graph"),
             "detail": "server %s · Knowledge pack" % ("up" if _og_ready("dev-graph") else "not running"),
             "optional": not SU.pack_on("knowledge")},
            {"name": "Omnigraph second-brain", "kind": "Personal knowledge graph", "ok": _og_ready("second-brain"),
             "detail": "server %s · Knowledge pack" % ("up" if _og_ready("second-brain") else "not running"),
             "optional": not SU.pack_on("knowledge")},
            {"name": "Linear", "kind": "Issues (MCP, OAuth)", "ok": "linear" in mcp and "Connected" in mcp["linear"],
             "detail": "MCP: %s. Sign in with /mcp in Claude Code; the dashboard shows the dev-graph mirror."
                       % mcp.get("linear", "not registered"), "optional": not SU.pack_on("linear")},
            _headroom_row(bool(versions["headroom"]), not SU.pack_on("headroom")),
            {"name": "GitHub (gh)", "kind": "PR/CI status, read-only", "ok": gh,
             "detail": "signed in" if gh else "not signed in: run `gh auth login` yourself",
             "problem": "GitHub CLI isn't signed in: run `gh auth login`" if C.which("gh") else
             "GitHub CLI isn't installed: run `lfg setup`"},
            {"name": "Ollama", "kind": "Local model for /pentest", "ok": _http_ok("http://127.0.0.1:11434/api/tags"),
             "detail": "only needed for /lfg:pentest", "optional": not SU.pack_on("pentest"),
             "problem": "Ollama isn't running: open the Ollama app"},
            {"name": "Egress firewall", "kind": "LuLu / Little Snitch", "ok": pg,
             "detail": "running" if pg else "not running; /lfg:pentest refuses to start without it",
             "optional": not SU.pack_on("pentest"), "problem": "No egress firewall running: open LuLu"},
            {"name": "Docker", "kind": "Ship check, pentest sandbox", "ok": docker_up,
             "detail": "running" if docker_up else "not running", "optional": not SU.pack_on("shipcheck"),
             "problem": "Docker isn't running: start Docker Desktop (or Colima)"},
        ]
        for i in integrations:
            i.setdefault("problem", "%s: %s" % (i["name"], re.sub(r"^MCP:\s*", "", i["detail"])))
        return {"tools": rows, "integrations": integrations, "mcp": mcp, "checked_at": C.now_iso()}
    return cached("tools", 300, get)


def tools_quick():
    """Cheap status for the overview (no subprocess-heavy checks)."""
    hit = _CACHE.get("tools")
    if hit:
        return hit[1]["integrations"]
    from . import setup as SU
    off = not SU.pack_on("knowledge")
    return [{"name": n, "ok": _og_ready(n), "optional": off, "problem": "%s isn't running: run `lfg omnigraph restart "
             "%s`" % (n, n)} for n in ("dev-graph", "second-brain")] + [_headroom_row(True, False)]


# ---------------------------------------------------------------- overview

def _audit(n):
    try:
        with open(C.lfg_path("audit.log")) as fh:
            lines = fh.readlines()[-n:]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def graph_state(rid):
    from . import graphs as G
    st = C.read_json(C.lfg_path("graphs", rid, "state.json"), {}) or {}
    root = st.get("repo_root")
    fresh = None
    if root and os.path.isdir(root):
        try:
            fresh = G.status(root, rid)["status"]
        except Exception:
            fresh = None
    return {"status": fresh or ("error" if st.get("last_error") else "unknown"), "synced_at": st.get("synced_at"),
            "mode": st.get("mode"), "seconds": st.get("last_sync_s"), "error": st.get("last_error"), "root": root,
            "docs": D.docs_state(rid)}


def overview(rid, branch=None):
    rs = runs(rid, branch)["runs"]
    cur = next((r for r in rs if r.get("current")), rs[0] if rs else None)
    u = usage(rid)
    week = [d for d in u["days"] if d["day"] >= time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))]
    why = og_access("dev-graph")
    if why:
        work = {"why": why}
    else:
        iss = issues(rid, branch)
        work = {"ready": len(iss["ready"]), "blocked": len(iss["blocked"]), "epics": len(iss["epics"])}
    sec = security(rid, branch)
    return {
        "graphs": graph_state(rid), "code": code(rid, full=False), "architecture": architecture(rid, full=False),
        "run": cur, "runs": len(rs), "work": work,
        "security": (sec["secure"] or [None])[0] and {k: sec["secure"][0][k] for k in ("run", "verdict", "blocking")},
        "tokens_7d": {k: sum(d[k] or 0 for d in week) for k in ("input", "output", "cache_read", "cache_write")},
        "days": u["days"], "headroom": u["headroom"], "spend": u["spend"], "integrations": tools_quick(),
        "activity": [{k: e.get(k) for k in ("ts", "event", "rule", "tool", "why", "repo_id")} for e in _audit(40)][:15],
        "playbooks": [os.path.basename(p) for p in sorted(glob.glob(os.path.join(D.playbook_dir(rid), "*.md")))],
    }
