"""`lfg ui`: the LFG dashboard on 127.0.0.1.

One place for everything LFG knows about a repo: runs, the Linear mirror, reviews, security, both code
graphs, generated docs/playbooks, dev-graph, second-brain, token usage (incl. Headroom), tool health, the Claude Code
settings that matter for LFG and every skill Claude Code loads (control.py).
Data comes from dash.py; the page is ui_assets/ (no external resources). Serves files only from ~/.lfg,
never from the repo, never secrets. Changes (settings, todos, reviews...) are POSTs that only the dashboard's own
page can send: Host and Origin must be this dashboard on 127.0.0.1/localhost, with its X-LFG header (which no other
site can add without a CORS preflight this server never grants) and a JSON body. Author: Varun Singh.
"""
import concurrent.futures
import glob
import html
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import webbrowser

from . import common as C
from . import dash
from . import settings as S

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_assets")
ASSET_TYPES = {"html": "text/html", "js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}

# The dashboard itself loads nothing from outside 127.0.0.1.
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "media-src 'self' https://github.com https://github-production-user-asset-6210df.s3.amazonaws.com; "
            "connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'")
# Tool-generated views (graphify graph/call-flow, code-review-graph graph) pull their chart libraries from
# these CDNs. They may load scripts from there, but cannot send data anywhere: no fetch/XHR/beacons, no
# images from other hosts, no forms, and they only render inside the dashboard.
STATIC_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com "
              "https://cdn.jsdelivr.net https://d3js.org; style-src 'self' 'unsafe-inline' https://unpkg.com "
              "https://cdn.jsdelivr.net; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
              "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")


def _rid(q):
    s = (q.get("repo") or [""])[0]
    return s if s and "/" not in s and ".." not in s and not s.startswith(".") else None


def _arg(q, k):
    return (q.get(k) or [""])[0]


def _only(q):
    """The picked repo's main checkout for the pages that list every repo (Sessions, PR reviews, Environment), or
    None when "Show all repos" is on or no repo is picked."""
    return None if _arg(q, "all") == "1" else dash.repo_root(_rid(q)) if _rid(q) else None


def ticket_titles():
    """{"ATO-4223": title} from the Linear issues LFG mirrors into dev-graph (`/lfg:inbox`); the dashboard never asks
    Linear itself."""
    def build():
        out = {}
        for rid in dash.repo_ids():
            d = dash.issues(rid)
            for i in d.get("issues") or [] if isinstance(d, dict) else []:
                if i.get("legacyRef") and i.get("title"):
                    out.setdefault(str(i["legacyRef"]).upper(), i["title"])
            if out:  # one dev-graph serves every repo
                break
        return out
    return dash.cached("ticket-titles", 300, build)


def linked_pr(pr):
    """A linked PR as the detail page shows it: where it is and whether it has a review."""
    from . import review as R
    repo, number = R.parse_pr(pr)
    rec = R.load(repo, number) or {}
    return {"pr": pr, "title": rec.get("title") or "", "reviewed": bool(rec.get("passes"))}


def pr_sessions(rows, linked=()):
    """Sessions about a PR, each with its resume command: the ones you linked by hand first, then every session that
    mentions it. The dashboard's own review runs are named as such: they were started with `claude -p` but resume
    like any other session."""
    from . import sessions as SS
    run = "Read %s" % os.path.join(C.PLUGIN_ROOT, "skills", "review")
    out = []
    if linked:
        known = {s["id"]: s for s in SS.listing(scripted=True, hidden=True)["sessions"]}
        for sid in linked:
            s = known.get(sid)
            if s:
                out.append({"id": sid, "title": s.get("name") or sid, "cwd": s.get("cwd") or "",
                            "modified": s.get("modified"), "linked": True, "resume": s.get("resume")})
        rows = [s for s in rows if s.get("id") not in set(linked)]
    for s in rows:
        mine = s["title"].startswith(run) or s["title"].startswith("Read ") and "/skills/review/SKILL.md" in s["title"]
        out.append(dict(s, dashboard=mine, title="Review run from the dashboard" if mine else s["title"],
                        resume=SS.resume_command(s)))
    return out


def graph_view(rid, kind):
    """URL of a tool-generated interactive view, generating it on first request. Graph views live in the repo's
    graph data (served by /graphdata/), the health report under ~/.lfg (served by /static/)."""
    from . import graphs as G
    root = dash.repo_root(rid)
    crg, gout = G.data_dir(rid, "crg") or "", G.data_dir(rid, "graphify") or ""
    if kind == "code":
        cands = glob.glob(os.path.join(crg, "*.html")) if crg else []
        if crg and not cands and root and C.which("code-review-graph"):
            C.run(["code-review-graph", "visualize", "--repo", root, "--data-dir", crg],
                  cwd=root, timeout=600, env={"CRG_DATA_DIR": crg})
            cands = glob.glob(os.path.join(crg, "*.html"))
    elif kind == "architecture":
        cands = glob.glob(os.path.join(gout, "graph.html")) if gout else []
        gj = os.path.join(gout, "graph.json")
        if gout and not cands and os.path.exists(gj) and C.which("graphify"):
            C.run(["graphify", "export", "html", "--graph", gj], cwd=gout, timeout=600,
                  env={"GRAPHIFY_OUT": gout, "GRAPHIFY_NO_AUTO_REFRESH": "1"})
            cands = glob.glob(os.path.join(gout, "graph.html"))
    elif kind == "callflow":
        cands = glob.glob(os.path.join(gout, "callflow.html")) if gout else []
    elif kind == "health":
        cands = glob.glob(C.lfg_path("ui", "static", "arch-health", "%s.html" % rid))
    else:
        cands = []
    if not cands:
        return {"message": {"code": "No code graph view yet. Run `lfg graphs ensure` in the repo.",
                            "architecture": "No architecture graph yet. Run `lfg graphs ensure` in the repo.",
                            "callflow": "No call-flow view yet. Run `lfg graphs docs` in the repo.",
                            "health": "No architecture-health report yet. Run /health in the repo."}.get(kind, "?")}
    p = cands[0]
    if kind == "health":
        return {"src": "/static/" + urllib.parse.quote(os.path.relpath(p, C.LFG_HOME)), "size": os.path.getsize(p)}
    sub = "crg" if kind == "code" else "graphify"
    return {"src": "/graphdata/%s/%s/%s" % (urllib.parse.quote(rid), sub, urllib.parse.quote(os.path.basename(p))),
            "size": os.path.getsize(p)}


def api(view, q):
    if view == "repos":
        return dash.repos()
    if view == "tools":
        return dash.tools()
    if view == "knowledge":
        from . import knowledge as KN
        k = dash.knowledge(_rid(q))
        if k.get("available"):
            KN.enrich(k["decisions"], k["learnings"])
        return k
    if view == "brain":
        return dash.brain()
    if view == "guide":
        return dash.guide()
    if view == "guide_doc":
        return dash.guide_doc(_arg(q, "id"))
    if view == "settings":
        return S.config_view()
    if view == "skills":
        return S.skills()
    if view == "skill":
        try:
            return S.skill(_arg(q, "name"))
        except S.Invalid as e:
            return {"available": False, "why": str(e)}
    if view == "claudemd":
        return S.claude_md()
    if view == "ollama":
        return S.ollama_models()
    if view == "rules":
        return S.rules()
    if view == "storage":
        return S.storage()
    if view == "prefs":
        from . import prefs as P
        d = P.load()
        sid = _arg(q, "session") or None
        return {"catalog": P.catalog(d), "defaults": P.effective(None, d), "values": P.effective(sid, d),
                "overrides": d["sessions"].get(sid or "", {}), "session": sid, "installed": P.installed(),
                "file": P.PREFS_MD, "sessions_with_changes": len(d["sessions"])}
    if view == "corrections":
        from . import corrections as CR
        from . import prefs as P
        pend = CR.items("pending")
        for x in pend:
            x["similar"] = CR.similar(x["said"] + " " + (x.get("note") or ""))
        return {"enabled": CR.enabled(), "pending": pend, "done": CR.items("all")[:40], "rules": CR.rules(),
                "installed": P.installed(), "file": P.PREFS_MD}
    if view == "mylibrary":
        return S.personal_library()
    if view == "myfile":
        try:
            return S.read_personal(_arg(q, "path"))
        except S.Invalid as e:
            return {"available": False, "why": str(e)}
    if view == "skillgroups":
        return S.skill_groups()
    if view == "headroom":
        return dash.headroom_detail(int(_arg(q, "days") or 30) if (_arg(q, "days") or "").isdigit() else 30)
    if view == "environment":
        from . import env as E
        if _arg(q, "fresh") == "1":
            dash.forget("environment")
        snap = dash.in_background("environment", 300, E.snapshot, "looking at every repo and worktree")
        return E.only(snap, _only(q))
    if view == "update":
        from . import updates as U
        if _arg(q, "fresh") == "1":
            dash.stale("update")
        d = dash.in_background("update", 60, lambda: U.check(max_age=0), "checking for updates")  # one cache, not two
        j = U.job() or {}
        if j.get("ended") and str(d.get("checked_at") or "~") < j["ended"]:  # checked before the last install: stale
            dash.forget("update")
            d = dash.in_background("update", 60, lambda: U.check(max_age=0), "checking for updates")
        # the jobs even while the check is still running, e.g. right after a restart
        return dict(d, job=U.job(), fix=U.fix_job())
    if view == "sessions":
        from . import sessions as SS
        return SS.listing(hidden=_arg(q, "hidden") == "1", only=_only(q), loose=_arg(q, "loose") == "1")
    if view == "sessionrecent":
        from . import sessions as SS
        try:
            return dict(SS.recent(_arg(q, "id")), used=SS.usage_of(_arg(q, "id")))
        except ValueError as e:
            return {"available": False, "why": str(e)}
    if view in ("sessionchanges", "sessionwork"):  # what a session changed, what it has running (read only)
        from . import sesswork as SW
        try:
            return (SW.changes if view == "sessionchanges" else SW.work)(_arg(q, "id"))
        except ValueError as e:
            return {"available": False, "why": str(e)}
    if view == "skillruns":
        from . import review as R
        from . import skillrun as SR
        sid = _arg(q, "id")
        runs = [SR.view(j) for j in SR.listing(sid or None)]
        if _arg(q, "runs_only") == "1":
            return {"runs": runs}
        return {"runs": runs, "skills": SR.skills(_rid(q)),
                "modes": [{"id": k, "label": v} for k, v in SR.MODES.items()], "models": R.models(),
                "model": R.chosen_model()}
    if view == "sessiondone":
        from . import sessions as SS
        return SS.group_cleanup(_arg(q, "repo"), _arg(q, "group"))
    if view == "claude":
        from . import control as K
        return K.claude_view()
    if view == "integrations":
        from . import control as K
        return K.integrations_view()
    if view == "todos":
        from . import todos as T
        return T.listing()
    if view == "notifications":
        from . import notify as N
        N.page_seen(_arg(q, "visible") == "1")
        from . import claudesess as CS
        live = [x for x in CS._LIVE.values() if x.state != "ended"]
        return dict(N.recent(_arg(q, "since")), sessions={"live": len(live),
                                                          "needs_you": sum(x.state == "needs-you" for x in live)})
    if view == "linear_options":  # Linear's teams, projects and people for the Create Linear ticket sheet
        from . import todos as T
        try:
            return T.linear_options(fresh=_arg(q, "fresh") == "1")
        except T.Invalid as e:
            return {"available": False, "why": str(e)}
    if view == "releases":
        from . import control as K
        return {"version": C.VERSION, "releases": K.releases()}
    if view == "tours":
        from . import control as K
        return K.tours_view()
    if view == "allskills":
        from . import control as K
        return K.skills_inventory(_rid(q))
    if view == "skilltext":
        from . import control as K
        return K.skill_text(_arg(q, "id"), _rid(q))
    if view == "ticketprs":
        from . import review as R
        try:
            return {"ticket": _arg(q, "ticket").strip().upper(), "prs": R.ticket_prs(_arg(q, "ticket")),
                    "title": ticket_titles().get(_arg(q, "ticket").strip().upper(), "")}
        except R.ReviewError as e:
            return {"available": False, "why": str(e)}
    if view == "notices":
        from . import review as R
        try:
            return R.notices(int(_arg(q, "since") or 0))
        except ValueError:
            return {"last": 0, "items": []}
    if view in ("chatfile", "chatsession", "review_chat"):  # a review chat's attachment; a session's recent talk; where
        from . import review as R  # the chat on a PR's page is pointed
        try:
            if view == "chatfile":
                return R.attachment_preview(_arg(q, "path"))
            if view == "review_chat":
                from . import reviewchat as RC
                repo, number = R.parse_pr(_arg(q, "pr"))
                return RC.target(repo, number, _arg(q, "pass"), _arg(q, "session"))
            return R.session_history(_arg(q, "id"), limit=int(_arg(q, "limit") or 20))
        except (R.ReviewError, ValueError) as e:
            return {"available": False, "why": str(e)}
    if view in ("prreviews", "prreview", "prreviewlog", "prsnippet", "prscores"):
        from . import review as R
        from . import sessions as SS
        if view == "prscores":
            return R.score_stats(only=_only(q))
        if view == "prreviews":
            return dict(R.dashboard(fresh=_arg(q, "fresh") == "1", only=_only(q)), method=R.method(),
                        ticket_titles=ticket_titles(), models=R.models(), model=R.chosen_model(),
                        methods=R.method_choices(), method_saved=R.method_saved(), combos=R.combos(),
                        method_now=R.method_label((C.config().get("review") or {}).get("sources")))
        try:
            repo, number = R.parse_pr(_arg(q, "pr"))
            pr = R.ref(repo, number)
            if view == "prsnippet":
                return {"snippet": R.snippet(repo, number, _arg(q, "id"))}
            if view == "prreviewlog":
                rec = R.need(repo, number)
                p = next((x for x in rec["passes"] if x["n"] == int(_arg(q, "n") or 0)), None)
                return {"steps": R.activity((p or {}).get("run", {}).get("log") or "")}
            rec = R.refresh_used(R.backfill(repo, number))
            rec = R.rescore(rec) if rec else rec  # saved before the score rules last changed: show it as it stands now
            for p in (rec or {}).get("passes") or []:
                if p.get("run"):
                    p["run"]["resume"] = R.resume(p["run"])
                    p["together"] = R.together(p)
            fj = R.fix_job(repo, number)
            fresh = False
            if _arg(q, "wait") == "0":  # the page first: what is known now, GitHub and the session search behind it
                fresh = _arg(q, "fresh") == "1"  # Refresh: the last answer now, GitHub's new one when it lands
                gh, sess = R.gh_status(repo, number, 0 if fresh else 300, wait=False), R.sessions_soon(repo, number)
            else:  # GitHub and the session search don't wait on each other
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    gh = pool.submit(R.gh_status, repo, number, 0 if _arg(q, "fresh") == "1" else 300)
                    sess = pool.submit(R.sessions_for, repo, number)
                    gh, sess = gh.result(), sess.result()
            return {"record": rec, "pending": [k for k, v in (("gh", fresh or (gh or {}).get("pending")),
                                                               ("sessions", sess is None)) if v],
                    "job": R.progress(repo, number), "repo": repo, "number": number,
                    "fix_job": R.progress(repo, number, j=fj) if fj else None,
                    "gh": gh, "sessions": pr_sessions(sess or [], R.linked_sessions(pr))[:12],
                    "linked": [linked_pr(x) for x in R.linked(pr)],
                    "groups": SS.groups_of(pr), "all_groups": SS.group_names(),
                    "models": R.models(), "model": R.chosen_model(), "methods": R.method_choices(),
                    "method_saved": R.method_saved(), "combos": R.combos(),
                    "method_now": R.method_label((C.config().get("review") or {}).get("sources"))}
        except R.ReviewError as e:
            return {"available": False, "why": str(e)}
    if view == "stack":  # stacked PRs and their epic; from a PR page there may be no repo picked
        from . import stacks as SK
        return SK.view(rid=_rid(q), gh=_arg(q, "gh"), pr=_arg(q, "pr"), run=_arg(q, "run"), ticket=_arg(q, "ticket"))
    if view == "github":
        from . import ghstar
        return ghstar.view()
    if view in ("features", "onboarding"):  # about LFG itself, not a repo: work before any project exists
        from . import onboard as OB
        return OB.view()
    rid = _rid(q)
    if not rid:
        return {"available": False, "why": "No repo yet. Open Claude Code in a git repo; LFG builds its graphs "
                                           "on the first session."}
    if view == "overview":
        return dash.overview(rid, _arg(q, "branch"))
    if view == "issues":
        return dash.issues(rid, _arg(q, "branch"))
    if view == "sonar_cloud":
        from . import sonar as SQ
        root = dash.repo_root(rid)
        return (SQ.cloud(root) or {"found": False}) if root and os.path.isdir(root) else {"found": False}
    if view in ("studio", "studio_session"):  # Studio: Claude Code sessions run from the dashboard
        from . import claudesess as CS
        root = dash.repo_root(rid)
        return CS.listing(rid, root) if view == "studio" else \
            CS.detail(rid, root, _arg(q, "id"), limit=int(_arg(q, "limit") or 0) or None)
    if view == "studio_changes":  # every file a session changed, as diffs, from its transcript
        from . import claudesess as CS
        return CS.changes(rid, dash.repo_root(rid), _arg(q, "id"))
    if view == "studio_where":
        from . import claudesess as CS
        return CS.where(rid, dash.repo_root(rid))
    if view in ("studio_image", "studio_context"):  # an image from a transcript; how full the context is
        from . import claudesess as CS
        try:
            if view == "studio_image":
                return CS.image(_arg(q, "id"), dash.repo_root(rid), _arg(q, "u"), _arg(q, "i") or "0")
            return CS.live(_arg(q, "id")).context()
        except (CS.Invalid, ValueError) as e:
            return {"available": False, "why": str(e)}
    if view in ("studio_suggest", "studio_files"):
        from . import claudesess as CS
        root = dash.repo_root(rid)
        return CS.suggestions(rid, root) if view == "studio_suggest" else CS.files(root, _arg(q, "q"))
    if view == "runs":
        return dash.runs(rid, _arg(q, "branch"))
    if view == "runs_search":  # vector search over what each run is about (local only)
        return dash.search_runs(rid, _arg(q, "q"))
    if view == "run":
        return dash.run_detail(rid, os.path.basename(_arg(q, "run")))
    if view == "file":
        return dash.run_file(rid, os.path.basename(_arg(q, "run")), _arg(q, "f"))
    if view == "code":
        return dash.code(rid)
    if view == "architecture":
        return dash.architecture(rid)
    if view == "docs":
        return dash.docs_index(rid)
    if view == "doc":
        return dash.doc(rid, _arg(q, "src"), _arg(q, "path"))
    if view == "knowledge_local":
        return {"items": dash.knowledge_list(rid), "dir": dash.knowledge_dir(rid)}
    if view == "view":
        return graph_view(rid, _arg(q, "kind"))
    if view == "reviews":
        return dash.reviews(rid, _arg(q, "branch"))
    if view == "security":
        return dash.security(rid, _arg(q, "branch"))
    if view == "branches":
        return dash.branches(rid)
    if view == "usage":
        return dash.usage(rid, int(_arg(q, "days")) if (_arg(q, "days") or "").isdigit() else 30)
    if view == "graphs":
        return dash.graph_state(rid)
    if view in ("insight_files", "insight_review", "insight_hotspots", "insight_explain", "insight_why",
                "insight_tests"):
        from . import insights as IN
        return IN.view(view, rid, q)
    return {"available": False, "why": "unknown view"}


MAX_BODY = 600_000
MAX_UPLOAD = 28_000_000  # a file dropped on a session's composer, base64 in JSON (files up to 20 MB)
NO_KEY = {"/api/save/graphs_build", "/api/save/tour_done"}  # neither changes your settings


def save(what, body):
    if what == "config":
        return S.save_config(body.get("values"))
    if what == "skill":
        return S.save_skill(body.get("name"), body.get("text"))
    if what == "skill_reset":
        return S.reset_skill(body.get("name"))
    if what == "claudemd":
        return S.save_claude_md(body.get("text"))
    if what == "ollama_pull":
        return S.pull_model(body.get("name"))
    if what == "storage_cleanup":
        return S.cleanup(body.get("ids"))
    if what == "rule":
        return S.save_rule(body.get("name"), body.get("text"))
    if what == "rule_reset":
        return S.reset_rule(body.get("name"))
    if what.startswith("todo_"):
        return todo_action(what, body)
    if what.startswith("sess_"):
        return session_action(what, body)
    if what == "sonar_scan":
        return sonar_scan(str(body.get("repo") or ""))
    if what == "run_needed":
        rid = _rid({"repo": [str(body.get("repo") or "")]})
        try:
            return dash.set_needed(rid, body.get("run"), bool(body.get("needed")))
        except ValueError as e:
            raise S.Invalid(str(e)) from None
    if what in ("onboarding_save", "feature_toggle", "pages_show_all", "feature_suggestion"):
        from . import onboard as OB
        if what == "feature_suggestion":
            return OB.answer_suggestion(body.get("feature"), body.get("answer") == "yes")
        if what == "onboarding_save":
            return OB.choose(body.get("features"), everything=bool(body.get("skip")))
        if what == "feature_toggle":
            return OB.toggle(body.get("feature"), bool(body.get("enabled")))
        return OB.set_show_all(body.get("on"))
    if what in ("doc_save", "knowledge_add"):
        rid = _rid({"repo": [str(body.get("repo") or "")]})
        if not rid:
            raise S.Invalid("open a project first")
        return dash.doc_save(rid, body) if what == "doc_save" else dash.knowledge_add(rid, body)
    if what == "github_star":  # the user clicked Star: the only way the dashboard writes to GitHub
        from . import ghstar
        return ghstar.star()
    if what == "run_checks":
        return run_checks(_rid({"repo": [str(body.get("repo") or "")]}), body.get("run"))
    if what == "graphs_build":
        return build_graphs(body.get("repo"), body.get("what"))
    if what in ("corr_toggle", "corr_approve", "corr_merge", "corr_discard", "corr_brain", "corr_rule_edit"):
        from . import corrections as CR
        from . import prefs as P
        try:
            if what == "corr_toggle":
                return CR.set_enabled(bool(body.get("on")))
            if what == "corr_approve":
                return CR.approve(str(body.get("id") or ""), body.get("text"), title=body.get("title") or "",
                                  why=body.get("why") or "", example=body.get("example") or "",
                                  scope=body.get("scope") or "global")
            if what == "corr_merge":
                return CR.merge(str(body.get("id") or ""), str(body.get("rule") or ""), text=body.get("text") or "",
                                why=body.get("why") or "", example=body.get("example") or "")
            if what == "corr_brain":
                return CR.to_brain(str(body.get("id") or ""), body.get("title") or "", body.get("text") or "")
            if what == "corr_discard":
                return CR.discard([str(x) for x in (body.get("ids") or [])])
            return P.update_custom(str(body.get("id") or ""), text=body.get("text"), why=body.get("why"),
                                   example=body.get("example"), title=body.get("title"))
        except (ValueError, PermissionError) as e:
            raise S.Invalid(str(e)) from None
    if what in ("pref_set", "pref_clear", "prefs_install", "pref_add", "pref_remove", "pref_remind", "pref_text"):
        from . import prefs as P
        try:
            if what == "pref_set":
                return P.set_pref(body.get("id"), body.get("value"), session=body.get("session") or None)
            if what == "pref_clear":
                return P.clear_session(str(body.get("session") or ""))
            if what == "pref_add":
                return P.add_custom(body.get("id"), body.get("group"), body.get("title"), body.get("text") or "",
                                    body.get("off_text") or "", bool(body.get("default", True)))
            if what == "pref_text":
                return P.set_text(body.get("id"), body.get("text"))
            if what == "pref_remove":
                return P.remove_custom(body.get("id"))
            if what == "pref_remind":
                return P.remind(str(body.get("session") or ""))
            return P.install()
        except (ValueError, PermissionError) as e:
            raise S.Invalid(str(e)) from None
    if what in ("knowledge_tag", "knowledge_ask"):
        from . import knowledge as KN
        try:
            if what == "knowledge_tag":
                return KN.set_tags(body.get("slug"), repo=body.get("repo"), feature=body.get("feature"),
                                   topic=body.get("topic"))
            k, b = dash.knowledge(), dash.brain()
            items = []
            if k.get("available"):
                d, ls = KN.enrich(k["decisions"], k["learnings"])
                items += [dict(x, text=" ".join(filter(None, [x.get("decision"), x.get("context")]))) for x in d]
                items += [dict(x, text=x.get("body") or "") for x in ls]
                items += [dict(slug=p["slug"], kind="rule", title=p.get("statement"), text=p.get("rationale") or "")
                          for p in k.get("principles") or []]
            if b.get("available"):
                items += [dict(slug=n["slug"], kind="note", title=n.get("name"), text=str(n.get("content") or ""))
                          for n in b.get("notes") or []]
            return KN.ask(body.get("question"), items)
        except ValueError as e:
            raise S.Invalid(str(e)) from None
    if what == "my_file":
        return S.save_personal(body.get("path"), body.get("text"))
    if what == "skill_group":
        return S.set_skill_group(body.get("id"), body.get("group"))
    if what == "update_pick":
        from . import updates as U
        try:
            res = U.set_pick(body.get("sha"), body.get("verdict"))
        except ValueError as e:
            raise S.Invalid(str(e)) from None
        # a pick changes nothing on GitHub: re-check without fetching (well under a second) so the banner shows it now
        dash.remember("update", U.check(max_age=0, fetch=False))
        return res
    if what in ("update_apply", "update_fix"):
        from . import updates as U
        dash.forget("update")
        return U.start("fix" if what == "update_fix" else "apply")
    if what == "ui_restart":
        threading.Timer(0.5, _restart).start()
        return {"restarting": True}
    if what == "worktree_prune":
        from . import env as E
        try:
            res = E.prune(str(body.get("root") or ""))
        except ValueError as e:
            raise S.Invalid(str(e)) from None
        dash.forget("environment")
        return res
    if what in ("session_name", "session_folder", "session_hide", "session_trash", "worktree_remove", "session_star",
                "group_pr"):
        from . import sessions as SS
        try:
            if what == "session_name":
                return SS.rename(body.get("id"), body.get("name"))
            if what == "session_hide":
                ids = body.get("ids") or []
                if not isinstance(ids, list):
                    raise ValueError("ids must be a list")
                return SS.hide(ids, on=body.get("on", True) is not False)
            if what == "session_trash":
                return SS.trash(body.get("id"))
            if what == "session_star":
                return SS.star(body.get("id"), body.get("on", True) is not False)
            if what == "group_pr":
                return SS.follow_pr(body.get("group"), body.get("pr"), body.get("on", True) is not False)
            if what == "worktree_remove":
                res = SS.remove_worktree(str(body.get("path") or ""))
                dash.forget("environment")
                return res
            return SS.file_into(body.get("id"), body.get("folder"), body.get("from") or "")
        except ValueError as e:
            raise S.Invalid(str(e)) from None
    if what == "session_lines":  # lines picked in a session's changes: ask about them, or have it change them
        from . import sesswork as SW
        from . import skillrun as SR
        kind = "change" if body.get("kind") == "change" else "ask"
        try:
            say = SW.about_lines(str(body.get("path") or ""), body.get("lines") or [], body.get("said") or "", kind)
            return SR.start(body.get("session"), say=say, mode="acceptEdits" if kind == "change" else "dontAsk",
                            fork=body.get("fork", True) is not False)
        except (SR.RunError, ValueError, TypeError) as e:
            raise S.Invalid(str(e)) from None
    if what in ("skill_run", "skill_stop"):
        from . import skillrun as SR
        try:
            if what == "skill_stop":
                return SR.stop(body.get("id"))
            return SR.start(body.get("session"), skill=body.get("skill") or "", say=body.get("say") or "",
                            times=body.get("times") or 1, until_clean=bool(body.get("until_clean")),
                            mode=str(body.get("mode") or "auto"), model=str(body.get("model") or ""),
                            fork=body.get("fork", True) is not False)
        except (SR.RunError, ValueError, TypeError) as e:
            raise S.Invalid(str(e)) from None
    if what.startswith("review_"):
        return review_action(what, body)
    from . import control as K
    actions = {
        "repo_on": lambda: K.repo_on(body.get("root")), "repo_off": lambda: K.repo_off(body.get("root")),
        "everywhere": lambda: K.everywhere(body.get("on")), "headroom": lambda: K.headroom_scope(body.get("scope")),
        "hardened": lambda: K.hardened(body.get("on")), "pack_add": lambda: K.pack_add(body.get("name")),
        "pack_remove": lambda: K.pack_remove(body.get("name")), "change_undo": lambda: K.change_undo(body.get("id")),
        "legacy_fix": lambda: K.legacy_fix(body.get("id")),
        "skill_auto": lambda: K.skill_auto(body.get("id"), bool(body.get("auto"))),
        "tour_done": lambda: K.tour_done(body.get("name"), body.get("how")),
        "omnigraph_restart": K.omnigraph_restart, "sonar_apply": K.sonar_apply,
    }
    if what in actions:
        res = actions[what]()
        return res if isinstance(res, dict) else {"result": res}
    raise S.Invalid("unknown setting")


def review_action(what, body):
    """The Reviews page's buttons. Posting is here because a person pressed it with the edit key; the guard keeps
    `lfg review post` away from agents."""
    from . import review as R
    try:
        if what == "review_sources":  # Save as my default: the methods ticked in the picker
            R.set_sources(R.method_sources(body.get("sources")))
            return {"saved": R.method_saved(), "methods": R.method_choices()}
        if what == "review_combo_save":  # Save as combo: the ticked methods under a name
            return R.save_combo(body.get("name"), body.get("sources"), old_name=body.get("old") or "")
        if what == "review_combo_delete":
            return R.delete_combo(body.get("name"))
        if what == "review_model":
            return S.save_config({"review.model": str(body.get("model") or "")})
        if what == "review_unpass":
            return R.pass_remove(str(body.get("id") or ""))
        repo, number = R.parse_pr(str(body.get("pr") or ""))
        if what == "review_mark":
            ids = body.get("ids") or []
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise S.Invalid("ids must be a list of finding ids")
            R.mark(repo, number, ids, status=body.get("status"), body=body.get("body"))
            return {}
        if what == "review_post":
            return R.post(repo, number, str(body.get("event") or ""), body=str(body.get("body") or ""),
                          dry_run=bool(body.get("dry_run")))
        if what == "review_check":
            return R.check_fixed(repo, number, str(body.get("id") or ""))
        if what == "review_remember":
            return R.remember(repo, number, body.get("pass"), str(body.get("id") or ""), str(body.get("to") or ""))
        if what == "review_remember_finding":
            return R.remember_finding(repo, number, str(body.get("id") or ""), str(body.get("to") or ""),
                                      note=body.get("note"))
        if what == "review_pass":
            return R.pass_on(repo, number, str(body.get("id") or ""), str(body.get("scope") or ""),
                             note=body.get("note"))
        if what == "review_run":
            together = body.get("with") or []
            if not isinstance(together, list):
                raise S.Invalid("with must be a list of PRs")
            return R.start(repo, number, ticket=body.get("ticket") or None, fresh=bool(body.get("fresh")),
                           together=[R.parse_pr(str(x)) for x in together], method=body.get("method") or None,
                           sources=body.get("sources") if isinstance(body.get("sources"), list) else None,
                           fresh_eyes=bool(body.get("fresh_eyes")), notes=body.get("notes") or None)
        if what == "review_link":
            return R.link(R.ref(repo, number), str(body.get("other") or ""), on=body.get("on", True) is not False)
        if what == "review_link_session":
            return R.link_session(R.ref(repo, number), body.get("id"), on=body.get("on", True) is not False)
        if what == "review_cancel":
            return R.cancel(repo, number)
        if what == "review_discard":
            return R.discard(repo, number, int(body.get("pass") or 0))
        if what in ("review_answer", "review_chat_say"):  # the review page's chat is Studio's, bound to the review
            from . import reviewchat as RC
            rid = _rid({"repo": [str(body.get("repo") or "")]})
            root = R.local_checkout(repo) or (dash.repo_root(rid) if rid else None)
            if not root:
                raise S.Invalid("LFG doesn't know where %s is on disk" % repo)
            if what == "review_answer":
                return RC.answer(rid, root, repo, number, body.get("pass"), str(body.get("id") or ""),
                                 body.get("answer"))
            return RC.say(rid, root, repo, number, body.get("pass"), body.get("text"),
                          fid=str(body.get("finding") or ""), qid=str(body.get("question") or ""),
                          sid=str(body.get("session") or ""), attachments=body.get("attachments"))
        if what == "review_reply":
            return R.post_reply(repo, number, str(body.get("id") or ""), body.get("body"))
        if what == "review_fix":
            return R.fix_start(repo, number)
        if what == "review_rewrite":
            return R.rewrite(repo, number, str(body.get("id") or ""), body.get("instruction"))
        if what == "review_sessions":
            return {"sessions": R.sessions_for(repo, number)}
        if what == "review_import":
            path = str(body.get("path") or "")
            if path == "log":
                path = (R.job(repo, number) or {}).get("log") or ""
            rec = R.import_session(repo, number, path, ticket=body.get("ticket") or None)
            return {"findings": len(rec["passes"][-1]["findings"])}
    except R.ReviewError as e:
        raise S.Invalid(str(e)) from None
    raise S.Invalid("unknown action")


def session_action(what, body):
    """The Sessions page: start, continue, message, answer a permission prompt, change mode, stop or end a session.
    Each runs Claude Code in the project's checkout, as you would in a terminal there."""
    from . import claudesess as CS
    rid = _rid({"repo": [str(body.get("repo") or "")]})
    root = dash.repo_root(rid) if rid else None
    sid = str(body.get("id") or "")
    try:
        if what == "sess_start":
            return CS.start(rid, root, body.get("text"), body.get("model"), body.get("mode") or "default",
                            where=body.get("where"), attachments=body.get("attachments"))
        if what == "sess_upload":
            return CS.upload(body.get("name"), str(body.get("type") or ""), body.get("data"))
        if what == "sess_fork":
            return CS.fork(rid, root, sid, str(body.get("at") or ""), body.get("text"), body.get("attachments"))
        if what in ("sess_rewind", "sess_rewind_preview"):  # a saved session is started again to rewind it
            CS.resume(rid, root, sid)
            live = CS.live(sid)
            for _ in range(50):  # it's ready once Claude Code has answered `initialize`
                if live.state != "starting":
                    break
                time.sleep(0.1)
            msg = str(body.get("message") or "")
            if not re.match(r"^[0-9a-f-]{36}$", msg):
                raise CS.Invalid("pick a message to rewind to")
            if what == "sess_rewind_preview":
                return live.rewind_preview(msg)
            return live.rewind(msg, str(body.get("what") or ""))
        if what == "sess_compact":  # (reloaded first, as for a message: see CS.fresh)
            live, reloaded = CS.fresh(rid, root, sid)
            return {"status": live.say("/compact " + CS._one_line(body.get("focus"))[:300]
                                       if body.get("focus") else "/compact"), "reloaded": reloaded}
        if what == "sess_reload":
            CS.reload(rid, root, sid)
            return {"saved": True}
        if what == "sess_resume":
            return CS.resume(rid, root, sid)
        if what == "sess_say":
            att = body.get("attachments")
            text = CS._check(body.get("text"), att)
            live, reloaded = CS.fresh(rid, root, sid)  # another window wrote to it: read that first, don't split it
            return {"status": live.say(text, att), "reloaded": reloaded}
        if what == "sess_decide":
            CS.live(sid).decide(str(body.get("request") or ""), str(body.get("decision") or ""),
                                answers=body.get("answers"), message=str(body.get("message") or ""))
            return {"saved": True}
        if what == "sess_mode":
            CS.live(sid).set_mode(str(body.get("mode") or ""))
            return {"saved": True}
        if what == "sess_interrupt":
            CS.live(sid).interrupt()
            return {"saved": True}
        if what == "sess_end":
            CS.live(sid).stop()
            return {"saved": True}
        if what in ("wt_merge", "wt_merge_all", "wt_remove"):  # the worktrees on the Sessions page
            from . import worktree as W
            try:
                if what == "wt_remove":
                    return W.remove(root, str(body.get("name") or ""))
                if what == "wt_merge_all":
                    into = str(body.get("into") or "")
                    return {"done": W.merge_all(root, into, True, bool(body.get("merge_commit")))}
                return W.merge(root, str(body.get("name") or ""), None, bool(body.get("remove")),
                               bool(body.get("merge_commit")))
            except W.NeedsMergeCommit as e:
                return {"needs_merge_commit": True, "why": str(e)}
            except (ValueError, RuntimeError) as e:
                raise CS.Invalid(str(e)) from None
        if what == "sess_rename":
            title = CS._one_line(body.get("title"))[:90]
            if not title:
                raise CS.Invalid("give it a name")
            CS._remember(sid, title=title)
            if sid in CS._LIVE:
                CS._LIVE[sid].title = title
            return {"saved": True}
    except CS.Invalid as e:
        raise S.Invalid(str(e)) from None
    raise S.Invalid("unknown action")


def todo_action(what, body):
    """The Todos page. `todo_linear` files one Linear issue, only from its Create Linear ticket button."""
    from . import todos as T
    tid = str(body.get("id") or "")
    try:
        if what == "todo_add":
            return T.add(body.get("text"), repo=body.get("repo"), notes=body.get("notes") or "")
        if what == "todo_update":
            return T.update(tid, text=body.get("text"), notes=body.get("notes"), status=body.get("status"))
        if what == "todo_delete":
            return T.delete(tid)
        if what == "todo_draft":  # the sheet's title and description, from the user's /linear-ticket skill
            return T.draft_linear(tid)
        if what == "todo_linear":  # the Create Linear ticket button, after the user confirmed the exact text
            return T.create_linear(tid, body.get("title"), body.get("description") or "", body.get("team") or "",
                                   body.get("project") or "", body.get("assignee") or "")
    except T.Invalid as e:
        raise S.Invalid(str(e)) from None
    raise S.Invalid("unknown action")


def build_graphs(rid, what):
    """Start building/refreshing a repo's code map (or its docs) in the background, like the hooks do."""
    from . import docs as D
    from . import graphs as G
    root = dash.repo_root(rid) if rid in dash.repo_ids() else None
    if not root or not os.path.isdir(root):
        raise S.Invalid("LFG doesn't know where this project is on disk; run `lfg init` in it once")
    if what == "docs":
        D.spawn_background(root)
    elif what in ("update", "rebuild"):
        G.spawn_background(root, rebuild=what == "rebuild")
    else:
        raise S.Invalid("unknown action")
    return {"started": what}


def sonar_scan(rid):
    """Start `lfg sonar scan` for the repo's checkout in the background (the Checks page's Scan now button)."""
    import subprocess
    import sys
    root = dash.repo_root(rid) if rid in dash.repo_ids() else None
    if not root or not os.path.isdir(root):
        raise S.Invalid("LFG doesn't know where this project is on disk")
    if (dash.sonar_view(rid) or {}).get("scanning"):
        return {"started": False, "running": True}
    lfg = C.lfg_bin() if os.path.exists(C.lfg_bin()) else os.path.abspath(sys.argv[0])
    log = os.path.join(C.ensure_dir(C.lfg_path("repos", rid)), "sonar-scan.log")
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out:
        p = subprocess.Popen([sys.executable, lfg, "sonar", "scan"], cwd=root, stdout=out, stderr=out,
                             stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    C.write_json(C.lfg_path("repos", rid, "sonar-running.json"), {"pid": p.pid, "started": C.now_iso()})
    return {"started": True}


def run_checks(rid, run):
    """Re-run `lfg gate` (lint, types, tests, build) for the repo's current run, in the background, where the run's
    code is: its worktree when it has one, else the repo. Only the current run, since that is where the gate
    writes ready.json."""
    import subprocess
    import sys
    root = dash.repo_root(rid) if rid in dash.repo_ids() else None
    cur = C.current_run(root) if root else None
    if not cur or os.path.basename(cur) != os.path.basename(str(run or "")):
        raise S.Invalid("Checks can only be re-run here for the project's current run; for another run, run "
                        "/lfg:check in it")
    if dash.checks_running(cur):
        return {"started": False, "running": True}
    meta = C.read_json(os.path.join(cur, "run.json"), {}) or {}
    where = next((w["path"] for w in meta.get("worktrees") or [] if os.path.isdir(w.get("path") or "")), root)
    lfg = C.lfg_bin() if os.path.exists(C.lfg_bin()) else os.path.abspath(sys.argv[0])
    logs = C.ensure_dir(os.path.join(cur, "gate-logs"))
    with open(os.path.join(logs, "gate.out"), "wb") as out:
        p = subprocess.Popen([sys.executable, lfg, "gate", "--json"], cwd=where, stdout=out, stderr=out,
                             stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    C.write_json(os.path.join(cur, "gate-running.json"), {"pid": p.pid, "started": C.now_iso(), "where": where})
    return {"started": True}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "lfg-ui"
    sys_version = ""
    port = 0

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype, csp=PAGE_CSP, extra=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        if csp:
            self.send_header("Content-Security-Policy", csp)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):  # DNS-rebinding guard
            return self._send(403, "forbidden", "text/plain")
        u = urllib.parse.urlsplit(self.path)
        if u.path in ("/", "/index.html"):
            # the page brings this dashboard's edit key, so any tab of it (any port, localhost, any browser) can
            # make changes without `lfg ui --unlock`. Only this dashboard's own address gets the page (the Host check
            # above), and another site can't read it: browsers keep a page's content from other origins.
            page = C.read_text(os.path.join(ASSETS, "index.html")).replace(
                "<head>", '<head>\n<meta name="lfg-key" content="%s">' % html.escape(S.edit_key()), 1)
            return self._send(200, page, "text/html; charset=utf-8")
        if u.path.startswith("/assets/"):
            return self._asset(u.path[len("/assets/"):])
        if u.path.startswith("/api/"):
            if self.headers.get("X-LFG") != "1":  # only the dashboard's own scripts may read the API
                return self._send(403, json.dumps({"why": "forbidden"}), "application/json")
            if u.path == "/api/unlocked":
                return self._send(200, json.dumps({"ok": S.key_ok(self.headers.get("X-LFG-Key"))}),
                                  "application/json")
            try:
                body = json.dumps(api(u.path[5:], urllib.parse.parse_qs(u.query)), default=str)
            except Exception as e:  # keep the dashboard up
                body = json.dumps({"available": False, "why": "error: %s" % type(e).__name__})
            return self._send(200, body, "application/json")
        if u.path.startswith("/static/"):
            return self._static(urllib.parse.unquote(u.path[len("/static/"):]))
        if u.path.startswith("/guide/"):
            return self._guide(urllib.parse.unquote(u.path[len("/guide/"):]))
        if u.path.startswith("/graphdata/"):
            return self._graphdata(urllib.parse.unquote(u.path[len("/graphdata/"):]))
        return self._send(404, "not found: %s" % html.escape(u.path), "text/plain")

    def do_POST(self):
        """Changes from the dashboard's own page only: same host and origin, the dashboard's header, and JSON."""
        def no(code, why):
            return self._send(code, json.dumps({"ok": False, "why": why}), "application/json")
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        origins = {"http://%s:%d" % (h, self.port) for h in ("127.0.0.1", "localhost")}
        if host not in ("127.0.0.1", "localhost") or self.headers.get("Origin") not in origins \
                or self.headers.get("X-LFG") != "1":
            return no(403, "forbidden")
        u = urllib.parse.urlsplit(self.path)
        if not u.path.startswith("/api/save/"):
            return no(404, "not found")
        if u.path not in NO_KEY and not S.key_ok(self.headers.get("X-LFG-Key")):
            return no(403, "editing is locked: run `lfg ui --unlock` in your terminal")
        size = int(self.headers.get("Content-Length") or 0)
        limit = MAX_UPLOAD if u.path == "/api/save/sess_upload" else MAX_BODY
        if not (self.headers.get("Content-Type") or "").startswith("application/json") or not 0 < size <= limit:
            return no(400, "expected a JSON body")
        try:
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return no(400, "invalid JSON")
        try:
            res = save(u.path[len("/api/save/"):], body)
        except S.Invalid as e:
            return no(400, str(e))
        except Exception as e:  # keep the dashboard up, never echo internals
            return no(500, "could not save (%s)" % type(e).__name__)
        C.audit("ui-save", {"what": u.path[len("/api/save/"):], "name": body.get("name") or ""})
        res["ok"] = True
        return self._send(200, json.dumps(res), "application/json")

    def _asset(self, name):
        p = os.path.realpath(os.path.join(ASSETS, name))
        ext = p.rsplit(".", 1)[-1]
        if p.startswith(os.path.realpath(ASSETS) + os.sep) and ext in ASSET_TYPES and os.path.isfile(p):
            with open(p, "rb") as fh:
                return self._send(200, fh.read(), ASSET_TYPES[ext] + "; charset=utf-8")
        return self._send(404, "not found", "text/plain")

    def _static(self, rel):
        """Tool-generated views under ~/.lfg/{graphs,ui,omnigraph}. Never JSON/DB files, never the repo."""
        p = os.path.realpath(os.path.join(C.LFG_HOME, rel))
        allowed = [os.path.realpath(C.lfg_path(d)) + os.sep for d in ("graphs", "ui", "omnigraph")]
        ext = p.rsplit(".", 1)[-1]
        if any(p.startswith(a) for a in allowed) and ext in ASSET_TYPES and os.path.isfile(p):
            with open(p, "rb") as fh:
                return self._send(200, fh.read(), ASSET_TYPES[ext] + "; charset=utf-8", csp=STATIC_CSP)
        return self._send(404, "not found", "text/plain")

    def _graphdata(self, rel):
        """Generated graph views (html/js/css/svg) in a known repo's graph data dir: `<rid>/<crg|graphify>/<file>`.
        Never graph.db/graph.json, never anything else in the repo."""
        from . import graphs as G
        parts = rel.split("/", 2)
        if len(parts) != 3 or parts[0] not in dash.repo_ids() or parts[1] not in G.DATA:
            return self._send(404, "not found", "text/plain")
        base = G.data_dir(parts[0], parts[1])
        if not base:
            return self._send(404, "not found", "text/plain")
        base = os.path.realpath(base)
        p = os.path.realpath(os.path.join(base, parts[2]))
        ext = p.rsplit(".", 1)[-1]
        if p.startswith(base + os.sep) and ext in ASSET_TYPES and os.path.isfile(p):
            with open(p, "rb") as fh:
                return self._send(200, fh.read(), ASSET_TYPES[ext] + "; charset=utf-8", csp=STATIC_CSP)
        return self._send(404, "not found", "text/plain")

    def _guide(self, name):
        """LFG's own user guide (docs/guide.html in the installed folder)."""
        base = os.path.realpath(os.path.join(dash.LFG_ROOT, "docs"))
        p = os.path.realpath(os.path.join(base, name))
        ext = p.rsplit(".", 1)[-1]
        if p.startswith(base + os.sep) and ext in ("html", "css", "svg") and os.path.isfile(p):
            with open(p, "rb") as fh:
                return self._send(200, fh.read(), ASSET_TYPES[ext] + "; charset=utf-8", csp=STATIC_CSP)
        return self._send(404, "not found", "text/plain")


def _restart():
    """Start this dashboard again on the newly installed code, same port, without opening a new tab."""
    from . import common as C2
    os.execv(sys.executable, [sys.executable, os.path.join(C2.lfg_path("plugin"), "bin", "lfg"), "ui", "--port",
                              str(Handler.port), "--no-open"])


def open_editor(port, browser=None):
    """Open the dashboard with the edit key in the URL fragment (never sent to a server, never printed). browser: a
    macOS app name ("Google Chrome", "Microsoft Edge") to unlock that one instead of the default browser."""
    url = "http://127.0.0.1:%d/#unlock=%s" % (port, S.edit_key())
    if not browser:
        return webbrowser.open(url)
    import subprocess
    return subprocess.run(["open", "-a", browser, url], capture_output=True, timeout=20).returncode == 0


def _state_path():
    return C.lfg_path("state", "ui.json")


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _command(pid):
    return C.run(["ps", "-o", "command=", "-p", str(pid)], timeout=5).stdout.strip()


def _stop_old(port):
    """Stop the LFG dashboard an earlier `lfg ui` left on this port (e.g. from a terminal that has since closed).
    Returns what holds the port when it is something else, else ""."""
    import signal
    import time
    old = C.read_json(_state_path(), {}) or {}
    pid = old.get("pid")
    if old.get("port") == port and pid and pid != os.getpid() and _alive(pid) and " ui" in _command(pid) \
            and "lfg" in _command(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if not _alive(pid):
                break
            time.sleep(0.1)
        print("Stopped the LFG dashboard that was already running on port %d (pid %d)." % (port, pid), flush=True)
        return ""
    holder = C.run(["lsof", "-t", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN"], timeout=5).stdout.split()
    return "%s (pid %s)" % (_command(holder[0])[:120], holder[0]) if holder else "another program"


def _exit_with_terminal():
    """A dashboard started from a terminal stops when that terminal is gone, even if it never sent a hangup: its
    parent shell dies and it is handed to launchd (pid 1)."""
    import time

    def watch():
        while os.getppid() != 1:
            time.sleep(5)
        os._exit(0)
    if sys.stdin and sys.stdin.isatty() and os.getppid() != 1:
        threading.Thread(target=watch, daemon=True).start()


def _code_stamp():
    """When this dashboard's own code last changed on disk (an update installs new files under it)."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        return max(os.path.getmtime(os.path.join(d, f)) for d, _, fs in os.walk(here) for f in fs
                   if f.endswith((".py", ".js", ".css", ".html")))
    except ValueError:
        return 0


def _restart_on_update(srv, every=3):
    """An update replaces the code under a running dashboard, which would keep serving pages from the old code. Once
    the new files have stopped changing, start again from them in the same process: same port, same terminal."""
    started, last = _code_stamp(), None
    while True:
        time.sleep(every)
        now = _code_stamp()
        if now <= started:
            continue
        if now != last:  # still being written: wait until it settles
            last = now
            continue
        print("LFG updated: restarting the dashboard on the new code")
        srv.restart = True
        srv.shutdown()  # serve() starts again once the server has stopped
        return


def watch_jobs(quiet=False):
    """One pass over every project's background jobs: anything that finished is read in and announced (notify.py),
    even when nobody has its page open. Reviews, answers and comment reading, fix runs, Diff-tab threads, Linear
    tickets, the SonarQube scans and checks started from here, and reviews whose PR was merged or closed. `quiet`
    (the first pass after start) marks scans and checks that ended before the dashboard started as seen instead of
    announcing old news."""
    import glob
    from . import notify as N
    from . import prdiff as PD
    from . import prreview as PR
    for rid in dash.repo_ids():
        for d in glob.glob(os.path.join(PR.folder(rid), "pr-*")):
            n = int(os.path.basename(d)[3:]) if os.path.basename(d)[3:].isdigit() else None
            if n is None:
                continue
            if os.path.exists(os.path.join(d, "job.json")):
                PR.settle(rid, n)
            if '"job"' in C.read_text(os.path.join(d, "diffchat.json")):
                PD.settle(rid, n)
        if any(m.get("status") != "closed" for _n, m in PR._metas(rid)):  # merged or closed on GitHub since?
            root = dash.repo_root(rid)
            if root and os.path.isdir(root):
                PR.sync_states(rid, root, PR.open_prs(rid, root))
        if glob.glob(C.lfg_path("runs", rid, "*", "run.json")):  # PR states for the runs' tags, every 10 minutes
            dash.refresh_pr_states(rid)
        for d in glob.glob(C.lfg_path("runs", rid, "*", "fix-job.json")):
            PR.settle_fix(os.path.dirname(d))
        for p in glob.glob(C.lfg_path("runs", rid, "*", "gate-running.json")):
            job = C.read_json(p, None)
            if isinstance(job, dict) and not job.get("announced") and not N.alive(job.get("pid")):
                ready = C.read_json(os.path.join(os.path.dirname(p), "ready.json"), None) or {}
                run = os.path.basename(os.path.dirname(p))
                if not quiet:
                    N.add("checks", "Checks passed" if ready.get("green") else "Checks failed", run,
                          "#runs/%s" % run, rid, ok=bool(ready.get("green")))
                C.write_json(p, dict(job, announced=True))
        p = C.lfg_path("repos", rid, "sonar-running.json")
        job = C.read_json(p, None)
        if isinstance(job, dict) and not job.get("announced") and not N.alive(job.get("pid")):
            from . import sonar as SQ
            res = SQ.last(rid) or {}
            fresh = res.get("ts") and res["ts"] >= (job.get("started") or "")
            if not quiet:
                gate = "passed" if res.get("gate") == "OK" else "failed" if res.get("gate") else "unknown"
                N.add("sonar", "SonarQube scan done: quality gate %s" % gate if fresh
                      else "The SonarQube scan didn't finish",
                      "%s issues on this branch" % res.get("mine", 0) if fresh
                      else "See the scan log on the Checks page",
                      "#checks", rid, ok=bool(fresh and res.get("gate") == "OK"))
            C.write_json(p, dict(job, announced=True))
    if os.path.exists(C.lfg_path("todos.json")) and '"linear_job"' in C.read_text(C.lfg_path("todos.json")):
        from . import todos as T
        T.listing()


def _watcher(every=4):
    import time
    first = True
    while True:
        try:
            watch_jobs(quiet=first)
            first = False
        except Exception:  # a bad file must never stop the dashboard; the page shows the job's state anyway
            pass
        time.sleep(every)


def serve(port, open_browser=True):
    Handler.port = port
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        if e.errno != __import__("errno").EADDRINUSE:
            raise
        other = _stop_old(port)
        if other:
            sys.exit("Port %d is in use by %s. Stop it, or start the dashboard on another port: lfg ui --port N"
                     % (port, other))
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    C.write_json(_state_path(), {"pid": os.getpid(), "port": port, "started": C.now_iso()})
    _exit_with_terminal()
    # tool/MCP checks take a few seconds; warm them so the first overview shows every integration
    threading.Thread(target=dash.tools, daemon=True).start()
    from . import review as R
    threading.Thread(target=R.session_index, daemon=True).start()  # the first PR page then reads only its sessions
    threading.Thread(target=_restart_on_update, args=(srv,), daemon=True).start()
    from . import notify as N
    N.DESK["port"] = port  # macOS notifications when no dashboard tab is in front
    threading.Thread(target=_watcher, daemon=True).start()  # announces finished AI jobs, scans and checks
    print("LFG dashboard: http://127.0.0.1:%d  (Ctrl-C to stop)" % port)
    if open_browser:
        threading.Timer(0.5, open_editor, (port,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        from . import claudesess as CS
        CS.stop_all()  # live sessions end with the dashboard; each can be continued later
    if getattr(srv, "restart", False):
        srv.server_close()
        argv = getattr(sys, "orig_argv", None) or [sys.executable] + sys.argv  # keeps python's own flags (3.10+)
        os.execv(sys.executable, argv + ([] if "--no-open" in argv else ["--no-open"]))
