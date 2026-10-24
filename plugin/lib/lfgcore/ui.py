"""`lfg ui`: the LFG dashboard on 127.0.0.1.

One place for everything LFG knows about a repo: runs, the Linear mirror, reviews, security, both code
graphs, generated docs/playbooks, dev-graph, second-brain, token usage (incl. Headroom), tool health, the Claude Code
settings that matter for LFG and every skill Claude Code loads (control.py).
Data comes from dash.py; the page is ui_assets/ (no external resources). Serves files only from ~/.lfg,
never from the repo, never secrets. Changes (settings, todos, reviews...) are POSTs that only the dashboard's own
page can send: Host and Origin must be this dashboard on 127.0.0.1/localhost, with its X-LFG header (which no other
site can add without a CORS preflight this server never grants) and a JSON body. Author: Varun Singh.
"""
import glob
import html
import http.server
import json
import os
import threading
import urllib.parse
import webbrowser

from . import common as C
from . import dash
from . import settings as S

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_assets")
ASSET_TYPES = {"html": "text/html", "js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}

# The dashboard itself loads nothing from outside 127.0.0.1.
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
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
        return dash.knowledge()
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
    if view == "headroom":
        return dash.headroom_detail(int(_arg(q, "days") or 30) if (_arg(q, "days") or "").isdigit() else 30)
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
        return N.recent(_arg(q, "since"))
    if view == "linear_options":  # Linear's teams, projects and people for the Create Linear ticket sheet
        from . import todos as T
        try:
            return T.linear_options(fresh=_arg(q, "fresh") == "1")
        except T.Invalid as e:
            return {"available": False, "why": str(e)}
    if view == "tours":
        from . import control as K
        return K.tours_view()
    if view == "allskills":
        from . import control as K
        return K.skills_inventory(_rid(q))
    if view == "skilltext":
        from . import control as K
        return K.skill_text(_arg(q, "id"), _rid(q))
    if view in ("features", "onboarding"):  # about LFG itself, not a repo: work before any project exists
        from . import onboard as OB
        return OB.view()
    if view == "updates":
        from . import updates as UP
        return UP.status_and_maybe_check()
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
    if view in ("prs", "pr", "pr_outgoing", "mine", "triage", "triage_out", "pr_diff"):
        from . import prreview as PR
        root = dash.repo_root(rid)
        if not root or not os.path.isdir(root):
            return {"available": False, "why": "LFG doesn't know where this project is on disk"}
        try:
            if view == "prs":
                return PR.pending(rid, root, fresh=_arg(q, "fresh") == "1")
            if view == "pr":
                return PR.detail(rid, root, _arg(q, "n"))
            if view == "mine":
                return PR.mine(rid, root, fresh=_arg(q, "fresh") == "1")
            if view == "triage":
                return PR.triage_detail(rid, root, _arg(q, "n"))
            if view == "triage_out":
                return PR.replies_out(rid, _arg(q, "n"))
            if view == "pr_diff":
                from . import prdiff as PD
                try:
                    return PD.diff(rid, root, _arg(q, "n"), fresh=_arg(q, "fresh") == "1")
                except PD.Invalid as e:
                    return {"available": False, "why": str(e)}
            return PR.outgoing(rid, _arg(q, "n"))
        except PR.Invalid as e:
            return {"available": False, "why": str(e)}
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
    if what.startswith("pr_"):
        return pr_action(what, body)
    if what.startswith("todo_"):
        return todo_action(what, body)
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
    if what == "updates_check":
        from . import updates as UP
        return UP.check()
    if what == "run_checks":
        return run_checks(_rid({"repo": [str(body.get("repo") or "")]}), body.get("run"))
    if what == "graphs_build":
        return build_graphs(body.get("repo"), body.get("what"))
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


def pr_action(what, body):
    """The Reviews page's actions. They spend AI tokens (start, ask, update), change the reviewer's draft, remove a
    worktree, or post to GitHub (only `pr_post`, sent by the Post button after the reviewer confirmed)."""
    from . import prreview as PR
    rid = str(body.get("repo") or "")
    root = dash.repo_root(rid) if rid in dash.repo_ids() else None
    if not root or not os.path.isdir(root):
        raise S.Invalid("LFG doesn't know where this project is on disk")
    n = body.get("n")
    try:
        if what == "pr_start":
            return PR.start(rid, root, n, focus=body.get("focus") or "")
        if what == "pr_ask":
            return PR.ask(rid, root, n, body.get("text"))
        if what == "pr_draft":
            return PR.save_draft(rid, n, body.get("draft"))
        if what == "pr_update":
            return PR.update(rid, root, n)
        if what == "pr_post":
            return PR.post(rid, root, n)
        if what == "pr_close":
            return PR.close(rid, root, n)
        if what == "pr_triage":
            return PR.triage(rid, root, n, focus=body.get("focus") or "")
        if what == "pr_decide":
            return PR.decide(rid, n, body.get("decisions"))
        if what == "pr_replies":
            return PR.post_replies(rid, root, n)
        if what == "pr_fixlist":
            return PR.fixlist(rid, n, remove=body.get("remove"), add=body.get("add"))
        if what == "pr_fixall":
            return PR.fix_all(rid, root, n)
        if what in ("pr_diff_ask", "pr_diff_thread"):  # the Diff tab: local AI threads, never sent to GitHub
            from . import prdiff as PD
            try:
                if what == "pr_diff_ask":
                    return PD.ask(rid, root, n, body.get("text"), thread=body.get("thread"), path=body.get("path"),
                                  side=body.get("side") or "new", start=body.get("start"), end=body.get("end"))
                return PD.thread_action(rid, n, body.get("thread"), body.get("action"))
            except PD.Invalid as e:
                raise S.Invalid(str(e)) from None
    except PR.Invalid as e:
        raise S.Invalid(str(e)) from None
    raise S.Invalid("unknown action")


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
    cur = C.current_run(rid) if root else None
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
            return self._asset("index.html")
        if u.path.startswith("/assets/"):
            return self._asset(u.path[len("/assets/"):])
        if u.path.startswith("/api/"):
            if self.headers.get("X-LFG") != "1":  # only the dashboard's own scripts may read the API
                return self._send(403, json.dumps({"why": "forbidden"}), "application/json")
            if u.path == "/api/unlocked":  # editing is always on; kept for pages that still ask
                return self._send(200, json.dumps({"ok": True}), "application/json")
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
        size = int(self.headers.get("Content-Length") or 0)
        if not (self.headers.get("Content-Type") or "").startswith("application/json") or not 0 < size <= MAX_BODY:
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


def open_editor(port):
    """Open the dashboard with the edit key in the URL fragment (never sent to a server, never printed)."""
    return webbrowser.open("http://127.0.0.1:%d/#unlock=%s" % (port, S.edit_key()))


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
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    # tool/MCP checks take a few seconds; warm them so the first overview shows every integration
    threading.Thread(target=dash.tools, daemon=True).start()
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
