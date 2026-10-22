"""Unit tests for lfgcore. Stdlib only: `python3 -m unittest discover -s tests` from the lfg folder.

Tests run with LFG_HOME pointed at a temp dir so they never touch ~/.lfg."""
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

_TMP_HOME = tempfile.mkdtemp(prefix="lfg-test-home-")
os.environ["LFG_HOME"] = _TMP_HOME
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib"))

from lfgcore import common as C  # noqa: E402
from lfgcore import dash  # noqa: E402
from lfgcore import docs as D  # noqa: E402
from lfgcore import gate as G  # noqa: E402
from lfgcore import guard  # noqa: E402
from lfgcore import headroom as HR  # noqa: E402
from lfgcore import omnigraph as OG  # noqa: E402
from lfgcore import secure as S  # noqa: E402
from lfgcore import shipcheck as SC  # noqa: E402
from lfgcore import settings as ST  # noqa: E402
from lfgcore import tracker as T  # noqa: E402
from lfgcore import ui  # noqa: E402


def bash(cmd):
    return guard.check("Bash", {"command": cmd})


class GuardTest(unittest.TestCase):
    def test_selftest_has_no_failures(self):
        self.assertEqual(guard.selftest(), [])

    def test_blocks_history_and_remote_changes(self):
        for cmd in ("git push", "git commit -m x", "git reset --hard", "FOO=1 git push", "sudo git push",
                    "bash -c 'git push'", "echo $(git push)"):
            self.assertIsNotNone(bash(cmd), cmd)

    def test_allows_read_only_git(self):
        for cmd in ("git status", "git diff --stat", "git log -5", "git reset -- app.py"):
            self.assertIsNone(bash(cmd), cmd)

    def test_secret_files(self):
        self.assertTrue(guard.is_secret_path("/x/.env"))
        self.assertTrue(guard.is_secret_path("/x/.env.production"))
        self.assertFalse(guard.is_secret_path("/x/.env.example"))
        self.assertIsNotNone(guard.check("Read", {"file_path": "/x/.env"}))
        self.assertIsNone(guard.check("Read", {"file_path": "/x/.env.example"}))

    def test_docker_delete_only_lfg_resources(self):
        self.assertIsNotNone(bash("docker rm somebox"))
        self.assertIsNone(bash("docker rm -f lfg-shipcheck-abc"))


class CommonTest(unittest.TestCase):
    def test_repo_id_format(self):
        d = tempfile.mkdtemp(prefix="my repo!")
        subprocess.run(["git", "init", "-q", d], check=True)
        rid = C.repo_id(d)
        self.assertRegex(rid, r"^[A-Za-z0-9_.-]+-[0-9a-f]{8}$")
        self.assertEqual(rid, C.repo_id(d))

    def test_new_run_sets_current(self):
        path = C.new_run("unit-rid", "Hello World!")
        self.assertTrue(path.startswith(_TMP_HOME))
        self.assertRegex(os.path.basename(path), r"^\d{8}-\d{4}-hello-world$")
        self.assertEqual(C.current_run("unit-rid"), path)


class GateTest(unittest.TestCase):
    DIFF = "+++ b/app.py\n+x = 1  # noqa\n+++ b/t.test.js\n+it.only('a', () => {})\n context\n"

    def test_added_lines(self):
        self.assertEqual(G.added_lines(self.DIFF),
                         [("app.py", "x = 1  # noqa"), ("t.test.js", "it.only('a', () => {})")])

    def test_suppression_scan_flags_new_suppressions(self):
        self.assertEqual(G.suppression_scan(self.DIFF)["exit"], 1)
        self.assertEqual(G.suppression_scan("+++ b/a.py\n+x = 1\n")["exit"], 0)


class SecureTest(unittest.TestCase):
    def test_levenshtein(self):
        self.assertEqual(S._lev("requests", "reqeusts"), 2)
        self.assertEqual(S._lev("react", "react"), 0)

    def test_private_hosts_never_queried(self):
        for h in ("localhost", "10.0.0.5", "192.168.1.1", "api.internal", "intranet"):
            self.assertTrue(S._private_host(h), h)
        self.assertFalse(S._private_host("pypi.org"))

    def test_sanitize_refuses_non_metadata(self):
        self.assertTrue(S.sanitize("requests"))
        for bad in ("", "/etc/passwd", "~/.ssh/id_rsa", "x" * 301, "ghp_" + "a" * 36):
            self.assertFalse(S.sanitize(bad), bad)


class ShipcheckTest(unittest.TestCase):
    def test_dockerfile_info(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "Dockerfile")
        with open(p, "w") as fh:
            fh.write("FROM python:3.12-slim AS base\n# comment\nEXPOSE 8000/tcp \\\n  9000\n"
                     "USER app\nHEALTHCHECK CMD curl -f http://localhost:8000/\n")
        os.makedirs(os.path.join(d, "graphify-out"))
        with mock.patch.object(C, "which", return_value=None):
            checks = {c["check"]: c for c in SC.lint_dockerfile(d, "Dockerfile", {"from": [], "user": "app",
                                                                                   "healthcheck": True})}
        leak = checks[".dockerignore excludes LFG graph folders"]
        self.assertEqual((leak["ok"], leak["severity"]), (False, "warn"))
        self.assertIn("graphify-out", leak["detail"])
        self.assertNotIn(".code-review-graph", leak["detail"])  # only folders that exist
        with open(os.path.join(d, ".dockerignore"), "w") as fh:
            fh.write(".git\n.env*\ngraphify-out/\n")
        with mock.patch.object(C, "which", return_value=None):
            checks = {c["check"]: c for c in SC.lint_dockerfile(d, "Dockerfile", {"from": [], "user": "app",
                                                                                   "healthcheck": True})}
        self.assertTrue(checks[".dockerignore excludes LFG graph folders"]["ok"])
        info = SC.dockerfile_info(p)
        self.assertEqual(info["from"], ["python:3.12-slim"])
        self.assertEqual(info["expose"], ["8000", "9000"])
        self.assertEqual(info["user"], "app")
        self.assertTrue(info["healthcheck"])


class OmnigraphTest(unittest.TestCase):
    def test_tokens_private_and_stable(self):
        t = OG.tokens()
        self.assertEqual(sorted(t), sorted(OG.ROLES))
        self.assertEqual(os.stat(OG.root("tokens.json")).st_mode & 0o777, 0o600)
        self.assertEqual(OG.tokens(), t)

    def test_plist_is_valid_and_loopback_only(self):
        import plistlib
        p = plistlib.loads(OG._plist("dev-graph").encode())
        self.assertEqual(p["Label"], "dev.lfg.omnigraph.dev-graph")
        self.assertEqual(p["ProgramArguments"][-3:], ["omnigraph", "serve", "dev-graph"])
        self.assertEqual(OG.url("dev-graph"), "http://127.0.0.1:47182")

    def test_lock_regex(self):
        err = "applying...\nAdmission lock: 01ABCXYZ9; retain until 2026-10-13T00:00:00Z\n"
        self.assertEqual(OG.LOCK_RX.search(err).group(1), "01ABCXYZ9")

    def test_stale_lock_cleared_only_when_its_process_is_gone(self):
        lock = OG.root("dev-graph", "__cluster", "lock.json")
        C.ensure_dir(os.path.dirname(lock))
        ran = []
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(OG, "_which", lambda n: "/bin/omnigraph"), \
                mock.patch.object(C, "run", lambda argv, **k: ran.append(argv) or ok):
            C.write_text(lock, json.dumps({"lock_id": "01LIVE", "operation": "serve", "pid": os.getpid()}))
            self.assertIsNone(OG.clear_stale_lock("dev-graph"))
            self.assertEqual(ran, [])
            dead = subprocess.Popen([sys.executable, "-c", "pass"])
            dead.wait()
            C.write_text(lock, json.dumps({"lock_id": "01DEAD", "operation": "serve", "pid": dead.pid}))
            self.assertEqual(OG.clear_stale_lock("dev-graph"), "01DEAD")
            self.assertEqual(ran, [["/bin/omnigraph", "cluster", "force-unlock", "01DEAD", "--config", "."]])
            os.remove(lock)
            self.assertIsNone(OG.clear_stale_lock("dev-graph"))


class OmnigraphRowsTest(unittest.TestCase):
    def test_rows_from_columns_and_dicts(self):
        res = {"columns": [{"name": "$i.slug"}, "$i.title"], "rows": [["a-1", "First"]]}
        self.assertEqual(OG._rows(res), [{"slug": "a-1", "title": "First"}])
        self.assertEqual(OG._rows({"rows": [{"$x.status": "done"}]}), [{"status": "done"}])
        self.assertEqual(OG._rows({}), [])

    def test_subject_wins_over_a_joined_node(self):
        res = {"rows": [{"i.slug": "iss-b", "i.status": "todo", "b.slug": "iss-a", "b.status": "done"}]}
        self.assertEqual(OG._rows(res), [{"slug": "iss-b", "status": "todo"}])

    def test_api_contract_header_matches_pin(self):
        self.assertRegex(OG.cfg()["version"].rstrip("."), r"^\d+\.\d+$")


class DocsTest(unittest.TestCase):
    def _graphify(self, rid, *sub):
        """The repo's graphify-out/ (graphs live in the repo; state.json says where the repo is)."""
        import shutil
        root = tempfile.mkdtemp(prefix="lfg-docs-repo-")
        self.addCleanup(shutil.rmtree, root, True)
        C.write_json(C.lfg_path("graphs", rid, "state.json"), {"repo_root": root})
        return os.path.join(root, "graphify-out", *sub)

    def test_qualified_names(self):
        self.assertEqual(D._qual("/r/src/a.ts::Cls.fn", "/r"), ("src/a.ts", "Cls.fn"))
        self.assertEqual(D._qual("/elsewhere/b.py", "/r"), ("/elsewhere/b.py", "b.py"))

    def test_report_sections(self):
        rid = "docs-test-0001"
        d = self._graphify(rid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "GRAPH_REPORT.md"), "w") as fh:
            fh.write("# Report\nintro\n## Summary\n- 3 nodes\n## God Nodes (top)\n1. `x`\n")
        secs = D.report_sections(rid)
        self.assertEqual(secs["Summary"], "- 3 nodes")
        self.assertEqual(D.section(secs, "god nodes"), "1. `x`")
        self.assertEqual(D.section(secs, "missing"), "")

    def test_wiki_pages_split_guides_from_code(self):
        rid = "docs-test-0002"
        d = self._graphify(rid, "wiki")
        os.makedirs(d, exist_ok=True)
        pages = {
            "index.md": "# Knowledge Graph Index\n",
            "linux.mdx.md": "# linux.mdx\n\n> 9 nodes\n\n## Source Files\n\n- `docs/content/runbooks/linux.mdx`\n",
            "README.md.md": "# Agent\n\n> 20 nodes\n\n## Source Files\n\n- `README.md`\n",
            "a_test.go.md": "# a_test.go\n\n> 50 nodes\n\n## Source Files\n\n- `internal/a/a.go`\n"
                            "- `internal/a/a_test.go`\n- `internal/a/b.go`\n",
            "Big.md": "# Big\n\n> 80 nodes\n\n## Source Files\n\n- `x/big.go`\n",
            "Node.md": "# Node\n\n## Relationships\n",
        }
        for name, text in pages.items():
            with open(os.path.join(d, name), "w") as fh:
                fh.write(text)
        got = [(p["kind"], p["title"]) for p in D.wiki_pages(rid)]
        self.assertEqual(got, [("doc", "runbooks · linux"), ("doc", "Agent"), ("code", "Big"),
                               ("code", "internal/a"), ("node", "Node")])
        self.assertIn("linux", dash.doc(rid, "guides", "linux.mdx.md")["text"])  # still readable for wiki links
        idx = dash.docs_index(rid)  # but not listed: the repo's own docs and cluster pages aren't LFG docs
        self.assertEqual((idx["root"], idx["branches"]), ({"items": [], "folders": []}, []))

    def test_docs_tree_project_at_root_then_one_folder_per_branch(self):
        rid = "docs-test-tree"
        C.write_text(C.lfg_path("playbooks", rid, "landmines.md"), "# Landmines\n")
        C.write_text(C.lfg_path("playbooks", rid, "onboarding.md"), "# Onboarding\n")
        C.write_text(C.lfg_path("playbooks", rid, "add-a-route.md"), "# How to add a route\n")
        docs = C.repo_docs_dir(rid)
        C.write_text(os.path.join(docs, "GLOSSARY.md"), "# Billing\n")
        C.write_text(os.path.join(docs, "billing-retries.md"), "# How billing retries work\n")
        C.write_text(os.path.join(docs, "adr", "0001-x.md"), "# Use Postgres\n")
        C.write_text(os.path.join(C.branch_docs_dir(rid, "feature/retry-v2"), "design.md"), "# Retry v2 design\n")
        C.branch_docs_dir(rid, "empty-branch")
        idx = dash.docs_index(rid)
        self.assertEqual([i["title"] for i in idx["root"]["items"]], ["Glossary", "How billing retries work"])
        wiki, adr = idx["root"]["folders"]
        self.assertEqual((wiki["name"], [i["title"] for i in wiki["items"]]),
                         ("Wiki", ["Onboarding tour", "Landmines", "How to add a route"]))
        self.assertEqual((adr["name"], adr["items"][0]["title"]), ("Decisions", "Use Postgres"))
        self.assertEqual(len(idx["branches"]), 1)  # folders with no docs are left out
        b = idx["branches"][0]
        self.assertEqual((b["name"], b["items"][0]["title"]), ("feature/retry-v2", "Retry v2 design"))
        self.assertIn("Retry v2", dash.doc(rid, "repo", b["items"][0]["path"])["text"])
        self.assertEqual(dash.doc(rid, "repo", "branches/../../x.md")["text"], "not found")

    def test_community_pages_get_readable_names(self):
        rid = "docs-test-0003"
        d = self._graphify(rid, "wiki")
        os.makedirs(d, exist_ok=True)
        key = "- **%s** (9 connections) — `%s`\n"
        pages = {"Community_1.md": "# Community 1\n\n> 40 nodes\n\n## Key Concepts\n\n"
                                   + key % ("step.types.ts", "src/security-controls/core/step.types.ts")
                                   + key % ("run()", "src/security-controls/steps/run.ts"),
                 "Community_2.md": "# Community 2\n\n> 12 nodes\n\n## Key Concepts\n\n"
                                   + key % ("1. Set up the gateway", "docs/gate.md")
                                   + "\n## Source Files\n\n- `docs/gate.md`\n"}
        for name, text in pages.items():
            with open(os.path.join(d, name), "w") as fh:
                fh.write(text)
        self.assertEqual({p["path"]: p["title"] for p in D.wiki_pages(rid)},
                         {"Community_1.md": "security-controls", "Community_2.md": "Set up the gateway"})
        self.assertEqual(D.area_name(["a/x.py", "b/y.py"]), "a")
        self.assertEqual(D.area_name(["x.py", "y.py"]), "x, y")

    def test_is_test(self):
        for p in ("a/b_test.go", "tests/x.py", "test_x.py", "src/x.spec.ts", "src/tests.rs"):
            self.assertTrue(D.is_test(p), p)
        for p in ("src/a.go", "lib/testing.py", "", None):
            self.assertFalse(D.is_test(p), p)


class UiTest(unittest.TestCase):
    def test_repo_id_blocks_traversal(self):
        self.assertEqual(ui._rid({"repo": ["repo-1234abcd"]}), "repo-1234abcd")
        for bad in ("../x", "a/b", ".hidden", ""):
            self.assertIsNone(ui._rid({"repo": [bad]}), bad)
        self.assertIsNone(ui._rid({}))

    def test_file_readers_stay_inside_their_folders(self):
        rid, run = "ui-test-0001", "20260101-0000-x"
        rd = C.lfg_path("runs", rid, run)
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, "01-brief.md"), "w") as fh:
            fh.write("brief")
        with open(C.lfg_path("config.json"), "a"):
            pass
        self.assertEqual(dash.run_file(rid, run, "01-brief.md")["text"], "brief")
        for bad in ("../../../config.json", "/etc/hosts", "missing.md"):
            self.assertEqual(dash.run_file(rid, run, bad), {"text": "not found"}, bad)
        self.assertEqual(dash.doc(rid, "playbooks", "../../config.json"), {"text": "not found"})
        self.assertEqual(dash.doc(rid, "nope", "x.md"), {"text": "not found"})

    def test_server_checks_host_and_header(self):
        import http.client
        import http.server
        import threading
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ui.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def get(path, headers=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", path, headers=headers or {})
            r = c.getresponse()
            out = (r.status, r.getheader("Content-Security-Policy") or "", r.read())
            c.close()
            return out

        try:
            status, csp, body = get("/")
            self.assertEqual(status, 200)
            self.assertIn("script-src 'self';", csp)
            self.assertIn(b"/assets/app.js", body)
            self.assertEqual(get("/api/repos")[0], 403)  # no X-LFG header: other sites cannot read the API
            self.assertEqual(get("/api/repos", {"X-LFG": "1"})[0], 200)
            self.assertEqual(get("/", {"Host": "evil.example:80"})[0], 403)  # DNS rebinding
            self.assertEqual(get("/assets/../ui.py")[0], 404)
            self.assertEqual(get("/static/config.json")[0], 404)
            self.assertEqual(get("/static/../../etc/hosts")[0], 404)
            status, csp, body = get("/guide/guide.html")
            self.assertEqual(status, 200)
            self.assertIn(b"Share with your team", body)
            self.assertEqual(get("/guide/sharing.md")[0], 404)  # only html/css/svg are served
            self.assertEqual(get("/guide/../CONTRACT.md")[0], 404)
            self.assertEqual(get("/guide/%2e%2e/bin/lfg")[0], 404)
        finally:
            srv.shutdown()
            srv.server_close()



class GuideTest(unittest.TestCase):
    def test_frontmatter_reads_folded_description(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "SKILL.md")
            with open(p, "w") as fh:
                fh.write("---\nname: demo\ndescription: >\n  first line\n  second line\nmodel: sonnet\n---\nbody\n")
            fm = dash._frontmatter(p)
        self.assertEqual(fm["name"], "demo")
        self.assertEqual(fm["description"], "first line second line")

    def test_guide_lists_plugin_skills_agents_and_docs(self):
        g = dash.guide()
        self.assertTrue(g["has_guide"])
        names = [s["name"] for s in g["skills"]]
        self.assertIn("/lfg:wizard", names)
        self.assertTrue(all(s["description"] for s in g["skills"]))
        self.assertTrue(g["agents"] and all(a["model"] for a in g["agents"]))
        self.assertEqual({x["id"] for x in g["docs"]}, {"sharing", "dashboard", "cli"})
        self.assertIn("lfg setup", dash.guide_doc("sharing")["text"])
        self.assertEqual(dash.guide_doc("../config")["text"], "not found")



class HeadroomTest(unittest.TestCase):
    GW = "https://gateway.example.com"

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.settings = os.path.join(self.home, ".claude", "settings.json")
        os.makedirs(os.path.dirname(self.settings))
        self.patches = [mock.patch.object(C, "HOME", self.home), mock.patch.object(HR, "install_agent"),
                        mock.patch.object(HR, "restart", return_value=True),
                        mock.patch.object(HR, "_which", return_value="/usr/bin/true"),
                        mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": ""})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        import shutil
        shutil.rmtree(self.home, ignore_errors=True)
        for f in ("state.json",):
            if os.path.exists(C.lfg_path("headroom", f)):
                os.remove(C.lfg_path("headroom", f))

    def write(self, data):
        with open(self.settings, "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))

    def read(self):
        with open(self.settings) as fh:
            return json.load(fh)

    def test_upstream_validation(self):
        self.assertTrue(HR.valid_upstream(self.GW))
        self.assertTrue(HR.valid_upstream("http://127.0.0.1:9000"))
        for bad in ("http://gateway.example.com", "https://u:p@gateway.example.com", "https://g.example.com/?k=v",
                    "file:///etc/hosts", ""):
            self.assertFalse(HR.valid_upstream(bad), bad)

    def test_setup_forwards_to_previous_gateway_and_off_restores_it(self):
        self.write({"env": {"ANTHROPIC_BASE_URL": self.GW, "KEEP": "x"}, "model": "opus"})
        with mock.patch.object(HR, "wait_live", return_value=True):
            out = HR.setup(new_scope="everywhere")
        self.assertTrue(out["live"] and HR.routed())
        self.assertEqual(out["upstream"], self.GW)
        s = self.read()
        self.assertEqual(s["env"], {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787", "KEEP": "x"})
        self.assertEqual(s["model"], "opus")
        self.assertTrue(os.listdir(C.lfg_path("backups", "claude")))
        with mock.patch.object(HR, "wait_live", return_value=True):
            self.assertEqual(HR.setup()["upstream"], self.GW)  # re-running keeps the real upstream
        with mock.patch.object(C, "run"):
            HR.off()
        self.assertEqual(self.read()["env"], {"ANTHROPIC_BASE_URL": self.GW, "KEEP": "x"})

    def test_setup_without_gateway_uses_anthropic_and_off_removes_key(self):
        self.write({"permissions": {}})
        with mock.patch.object(HR, "wait_live", return_value=True):
            self.assertEqual(HR.setup(new_scope="everywhere")["upstream"], HR.DEFAULT_UPSTREAM)
        with mock.patch.object(C, "run"):
            HR.off()
        self.assertEqual(self.read(), {"permissions": {}})

    def test_never_routes_to_a_proxy_that_is_down(self):
        self.write({"env": {"ANTHROPIC_BASE_URL": self.GW}})
        with mock.patch.object(HR, "wait_live", return_value=False):
            out = HR.setup(new_scope="everywhere")
        self.assertFalse(out["live"])
        self.assertEqual(self.read()["env"]["ANTHROPIC_BASE_URL"], self.GW)

    def test_broken_settings_are_left_alone(self):
        self.write("{not json")
        with mock.patch.object(HR, "wait_live", return_value=True), self.assertRaises(SystemExit):
            HR.setup(new_scope="everywhere")
        with open(self.settings) as fh:
            self.assertEqual(fh.read(), "{not json")

    def test_serve_uses_configured_mode(self):
        self.assertEqual(HR.mode(), "token")
        with mock.patch.object(os, "execvpe") as ex:
            HR.serve()
        argv = ex.call_args[0][1]
        self.assertEqual(argv[argv.index("--mode") + 1], "token")
        self.assertEqual(C.read_json(C.lfg_path("headroom", "state.json"), {})["mode"], "token")

    def session_start_text(self):
        import io
        from contextlib import redirect_stdout
        from lfgcore import hooks
        buf = io.StringIO()
        with mock.patch.object(C, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                mock.patch.object(hooks, "_repo", return_value=(None, None)), \
                mock.patch.object(HR, "ensure_live", return_value=True), redirect_stdout(buf):
            hooks.session_start({})
        return buf.getvalue()

    def test_session_start_says_when_the_desktop_app_bypasses_the_proxy(self):
        self.write({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}})
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                                          "CLAUDE_CODE_ENTRYPOINT": "claude-desktop"}):
            self.assertEqual(HR.bypassed(), "https://api.anthropic.com")
            out = self.session_start_text()
        self.assertIn("Headroom proxy: BYPASSED", out)
        self.assertIn("https://api.anthropic.com", out)
        self.assertIn("Claude desktop app", out)
        self.assertNotIn("Headroom proxy: up", out)

    def test_session_start_says_up_when_the_session_goes_through_the_proxy(self):
        self.write({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}})
        for env in ({"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787/"}, {"ANTHROPIC_BASE_URL": ""}):
            with mock.patch.dict(os.environ, env):
                self.assertIsNone(HR.bypassed())  # unset: no way to tell, so no warning
                self.assertIn("Headroom proxy: up.", self.session_start_text())

    def prompt_out(self, live, revived=None):
        """The prompt hook's Headroom part only: the LFG reminder is switched off (LfgTagTest covers it)."""
        import io
        from contextlib import redirect_stdout
        from lfgcore import hooks
        buf = io.StringIO()
        with mock.patch.object(hooks, "_repo", return_value=(None, None)), \
                mock.patch.object(hooks, "_tag_on", return_value=False), \
                mock.patch.object(HR, "live", return_value=live), \
                mock.patch.object(HR, "revive", return_value=revived) as rv, \
                mock.patch.object(C, "audit"), redirect_stdout(buf):
            self.assertEqual(hooks.prompt({}), 0)
        return buf.getvalue(), rv

    def test_prompt_is_silent_while_the_proxy_answers(self):
        self.write({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}})
        out, rv = self.prompt_out(live=True)
        self.assertEqual(out, "")
        rv.assert_not_called()

    def test_prompt_restarts_a_proxy_that_went_down(self):
        self.write({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}})
        out, rv = self.prompt_out(live=False, revived=True)
        rv.assert_called_once()
        self.assertIn("restarted", json.loads(out)["systemMessage"])

    def test_prompt_tells_the_user_when_the_proxy_stays_down(self):
        self.write({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}})
        out, _rv = self.prompt_out(live=False, revived=False)
        msg = json.loads(out)["systemMessage"]
        self.assertIn("can't reach Claude", msg)
        self.assertIn("lfg headroom restart", msg)

    def test_prompt_leaves_unrouted_and_bypassed_sessions_alone(self):
        out, rv = self.prompt_out(live=False)  # no routing in settings
        self.assertEqual(out, "")
        self.write({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}})
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}):
            out, rv = self.prompt_out(live=False)  # the desktop app: can't be fixed, already warned at start
        self.assertEqual(out, "")
        rv.assert_not_called()

    def test_session_start_tells_the_user_when_the_proxy_stays_down(self):
        import io
        from contextlib import redirect_stdout
        from lfgcore import hooks
        self.write({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}})
        buf = io.StringIO()
        with mock.patch.object(C, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                mock.patch.object(hooks, "_repo", return_value=(None, None)), \
                mock.patch.object(HR, "ensure_live", return_value=False), redirect_stdout(buf):
            hooks.session_start({})
        out = json.loads(buf.getvalue())
        self.assertIn("lfg headroom restart", out["systemMessage"])
        self.assertIn("Headroom proxy: DOWN.", out["hookSpecificOutput"]["additionalContext"])

    def test_revive_reloads_an_unloaded_agent_and_restarts_a_loaded_one(self):
        os.makedirs(os.path.dirname(HR._plist_path()))
        open(HR._plist_path(), "w").close()
        for loaded in (False, True):
            with mock.patch.object(HR, "_agent_loaded", return_value=loaded), \
                    mock.patch.object(HR, "wait_live", return_value=True), \
                    mock.patch.object(C, "run") as run, mock.patch.object(HR, "restart") as rs:
                self.assertTrue(HR.revive())
            if loaded:
                rs.assert_called_once()
                run.assert_not_called()
            else:
                rs.assert_not_called()
                self.assertEqual(run.call_args[0][0][:2], ["launchctl", "bootstrap"])

    def test_dashboard_flags_a_routed_proxy_that_is_down(self):
        with mock.patch.object(dash, "_headroom_proxy", return_value=(True, False)):
            row = dash._headroom_row(True, False)
        self.assertFalse(row["ok"])
        self.assertIn("lfg headroom restart", row["problem"])
        for state in ((True, True), (False, False)):
            with mock.patch.object(dash, "_headroom_proxy", return_value=state):
                row = dash._headroom_row(True, False)
            self.assertTrue(row["ok"])
            self.assertNotIn("problem", row)


class TrackerTest(unittest.TestCase):
    def test_slugs(self):
        self.assertEqual(T.slug_for("ACME-4225"), "acme-4225")
        self.assertEqual(T.slug_for("acme-4225"), "acme-4225")  # run.json stores the slug; must map to itself
        self.assertEqual(T.slug_for("Make billing-service logs useful!"), "iss-make-billing-service-logs-useful")
        self.assertEqual(T.slug_for("iss-x"), "iss-x")

    def test_sync_tasks_and_brief_carry_the_real_text(self):
        run = tempfile.mkdtemp()
        C.write_json(os.path.join(run, "tasks.json"), [
            {"id": "t-001", "description": "Add the thing", "steps": ["one", "two"], "verification": "tests pass",
             "passes": True, "priority": 2},
            {"id": "t-002", "description": "Next thing", "passes": False, "linear_id": "ACME-9"}])
        C.write_json(os.path.join(run, "run.json"), {"issue": "ACME-1"})
        C.write_text(os.path.join(run, "01-brief.md"), "# Brief: X\n\n## Problem\nIt breaks.\n\n"
                     "## Acceptance criteria\n1. **Works**\n   Given a, Then b.\n### detail\nmore\n\n"
                     "## Non-goals\nnone\n")
        calls = []
        with mock.patch.object(T, "lookup", lambda slug: {"slug": slug} if slug == "acme-9" else None), \
                mock.patch.object(T, "sync", lambda key, **kw: calls.append((key, kw)) or {"action": "x", **kw}):
            T.sync_tasks(run)
            T.sync_brief(run)
        self.assertEqual(calls[0], ("iss-t-001", {"title": "Add the thing", "description":
                                                  "Add the thing\n\nSteps:\n- one\n- two", "criteria": "tests pass",
                                                  "status": "done", "priority": 2}))
        self.assertEqual(calls[1][0], "ACME-9")  # its tracker id, and an existing issue keeps title and status
        self.assertEqual((calls[1][1]["title"], calls[1][1]["status"]), (None, None))
        self.assertEqual(calls[2], ("ACME-1", {"description": "It breaks.", "criteria":
                                               "1. **Works**\n   Given a, Then b.\n### detail\nmore"}))

    def test_sync_creates_then_updates_only_given_fields(self):
        calls = []
        og = mock.Mock(read=mock.Mock(return_value=[]), mutate=lambda g, q, n, p: calls.append((q, p)))
        with mock.patch.object(T, "_og", return_value=og):
            out = T.sync("ACME-1", title="Alert", issue_type="bug", priority=1)
            self.assertEqual(out["action"], "created")
            q, p = calls[-1]
            self.assertIn("insert Issue", q)
            self.assertEqual((p["slug"], p["legacyRef"], p["status"], p["issueType"]),
                             ("acme-1", "ACME-1", "todo", "bug"))
            self.assertIn("$priority: I32", q)
            og.read.return_value = [{"slug": "acme-1", "status": "todo"}]
            out = T.set_status("acme-1", "in_progress")
            q, p = calls[-1]
            self.assertEqual(out["action"], "updated")
            self.assertIn("update Issue set { status: $status, updatedAt", q)
            self.assertNotIn("title", p)

    def test_run_set_records_lane_stage_issue_and_never_lowers_lane(self):
        from lfgcore import cli
        rid = "tracker-test-0001"
        run = C.new_run(rid, "x")
        with mock.patch.object(C, "need_repo", return_value=("/r", rid)), \
                mock.patch.object(T, "set_status", return_value={"slug": "acme-9", "status": "in_progress"}) as st:
            self.assertEqual(cli.main(["run", "set", "lane=standard", "stage=build", "issue=ACME-9"]), 0)
            st.assert_called_with("acme-9", "in_progress")
            meta = C.read_json(os.path.join(run, "run.json"), {})
            self.assertEqual((meta["lane"], meta["stage"], meta["issue"]), ("standard", "build", "acme-9"))
            with self.assertRaises(SystemExit):
                cli.main(["run", "set", "lane=express"])
            self.assertEqual(cli.main(["run", "set", "lane=express", "--force"]), 0)
            with self.assertRaises(SystemExit):
                cli.main(["run", "set", "stage=nope"])


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="lfg-test-user-")
        self.patch = mock.patch.object(C, "HOME", self.home)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_save_config_validates_and_only_touches_given_keys(self):
        C.write_json(C.lfg_path("config.json"), {"linear": {"team": "ACME"}, "custom": {"keep": 1}})
        r = ST.save_config({"linear.workspace": "acme", "headroom.mode": "token"})
        self.assertEqual(r["changed"], ["linear.workspace"])
        raw = C.read_json(C.lfg_path("config.json"))
        self.assertEqual(raw["custom"], {"keep": 1})
        self.assertEqual(raw["linear"], {"team": "ACME", "workspace": "acme"})
        for bad in ({"pentest.ollama_url": "https://api.example.com"}, {"ui.port": 80},
                    {"headroom.mode": "fast"}, {"pentest.require_firewall": False},
                    {"linear.team": "ghp_" + "a" * 36}):
            with self.assertRaises(ST.Invalid, msg=bad):
                ST.save_config(bad)

    def test_skill_edit_survives_and_resets(self):
        txt = "---\nname: demo\ndescription: d\n---\n\nbody\n"
        cache = os.path.join(self.home, ".claude", "plugins", "cache", "lfg", "lfg", "0.1.0", "skills", "demo",
                             "SKILL.md")
        for p in (os.path.join(C.PLUGIN_DIR, "skills", "demo", "SKILL.md"),
                  C.lfg_path("defaults", "skills", "demo", "SKILL.md"), cache):
            C.write_text(p, txt)
        new = txt.replace("body", "edited body")
        ST.save_skill("demo", new)
        self.assertTrue(ST.skill("demo")["edited"])
        self.assertEqual(C.read_text(os.path.join(C.PLUGIN_DIR, "skills", "demo", "SKILL.md")), new)
        self.assertEqual(C.read_text(cache), txt)  # Claude Code's own cache is never written
        with self.assertRaises(ST.Invalid):
            ST.save_skill("demo", "no front matter")
        with self.assertRaises(ST.Invalid):
            ST.save_skill("../etc", txt)
        ST.reset_skill("demo")
        self.assertFalse(ST.skill("demo")["edited"])
        self.assertEqual(ST.skill("demo")["text"], txt)

    def test_unedited_legacy_claude_md_block_is_removed_and_nothing_else_changes(self):
        body = ("## LFG plugin\n- When you use the LFG plugin (`/lfg`, `/wizard` or any other `lfg:` skill or agent), "
                "follow that skill's steps,\n  checkpoints and bookkeeping commands (`lfg issue sync`, "
                "`lfg run set`) as written.")
        ST.SHIPPED_SECTIONS.add(__import__("hashlib").sha256(body.encode()).hexdigest())
        mine = "# Mine\n- rule one\n\n%s\n%s\n%s\n# after\n" % (ST.BEGIN, body, ST.END)
        C.write_text(ST.claude_md_path(), mine)
        self.assertFalse(ST.legacy_section_edited())
        self.assertTrue(ST.remove_claude_md_section()["removed"])
        self.assertEqual(C.read_text(ST.claude_md_path()), "# Mine\n- rule one\n# after\n")
        self.assertFalse(ST.remove_claude_md_section()["removed"])

    def test_edited_legacy_claude_md_block_is_left_alone(self):
        mine = "# Mine\n\n%s\n## LFG plugin\n- my own line\n%s\n" % (ST.BEGIN, ST.END)
        C.write_text(ST.claude_md_path(), mine)
        self.assertTrue(ST.legacy_section_edited())
        self.assertTrue(ST.remove_claude_md_section().get("edited"))
        self.assertEqual(C.read_text(ST.claude_md_path()), mine)

    def test_writes_need_the_edit_key_and_same_origin(self):
        import http.client
        import threading
        srv = ui.http.server.ThreadingHTTPServer(("127.0.0.1", 0), ui.Handler)
        ui.Handler.port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        origin = "http://127.0.0.1:%d" % ui.Handler.port

        def post(headers):
            c = http.client.HTTPConnection("127.0.0.1", ui.Handler.port, timeout=5)
            c.request("POST", "/api/save/config", json.dumps({"values": {"linear.team": "X"}}),
                      dict({"Content-Type": "application/json", "X-LFG": "1", "Origin": origin}, **headers))
            try:
                return c.getresponse().status
            finally:
                c.close()

        self.assertEqual(post({}), 403)
        self.assertEqual(post({"X-LFG-Key": "wrong"}), 403)
        self.assertEqual(post({"X-LFG-Key": ST.edit_key(), "Origin": "http://evil.test"}), 403)
        self.assertEqual(post({"X-LFG-Key": ST.edit_key()}), 200)

    def test_ollama_pull_is_local_only_and_validated(self):
        for bad in ("qwen3:cloud", "deepseek-v4-pro:cloud", "rm -rf /", "", "../x"):
            with self.assertRaises(ST.Invalid, msg=bad):
                ST.pull_model(bad)
        with mock.patch.object(ST, "_ollama_json", side_effect=OSError("down")):
            with self.assertRaises(ST.Invalid):
                ST.pull_model("qwen3:8b")
        C.write_json(C.lfg_path("config.json"), {"pentest": {"ollama_url": "https://ollama.example.com"}})
        self.addCleanup(os.remove, C.lfg_path("config.json"))
        with self.assertRaises(ST.Invalid):
            ST.pull_model("qwen3:8b")

    def test_ollama_models_marks_fit_and_installed(self):
        tags = {"models": [{"name": "qwen3:8b", "size": 5.2e9, "details": {"parameter_size": "8B"}}]}
        with mock.patch.object(ST, "_ram_gb", return_value=24), \
                mock.patch.object(ST, "_ollama_json",
                                  side_effect=lambda path, body=None: tags if path == "/api/tags"
                                  else {"capabilities": ["tools"]}):
            d = ST.ollama_models()
        self.assertTrue(d["running"])
        self.assertTrue(d["installed"][0]["tools"])
        cat = {m["name"]: m for m in d["catalog"]}
        self.assertTrue(cat["qwen3:8b"]["installed"])
        self.assertEqual(cat["qwen3:8b"]["fit"], "fits")
        self.assertEqual(cat["nemotron-3.5-lightning:30b"]["fit"], "too big")

    def test_guard_keeps_agents_away_from_the_key_and_edited_files(self):
        self.assertIsNotNone(bash("cat ~/.lfg/ui/edit.key"))
        self.assertIsNotNone(guard.check("Read", {"file_path": os.path.join(C.LFG_HOME, "ui", "edit.key")}))
        for p in ("~/.lfg/overrides/skills/lfg/SKILL.md", "~/.claude/CLAUDE.md",
                  "~/.claude/plugins/cache/lfg/lfg/0.1.0/skills/lfg/SKILL.md"):
            self.assertIsNotNone(guard.check("Write", {"file_path": os.path.expanduser(p), "content": "x"}), p)


class RulesAndLeanOutputTest(unittest.TestCase):
    def test_every_guard_rule_has_catalogue_text(self):
        import re
        src = open(guard.__file__).read()
        raised = set(re.findall(r'Block\("(\d+)"', src))
        self.assertTrue(raised)
        self.assertLessEqual(raised, set(guard.RULES))
        self.assertEqual(sorted(guard.RULES, key=int), [str(i) for i in range(1, 19)])
        self.assertEqual(guard.rule_title(4), "Never read secret files")

    def test_rules_view_lists_rules_and_modules(self):
        plugin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin")
        with mock.patch.object(C, "PLUGIN_DIR", plugin):
            r = ST.rules()
            self.assertEqual(ui.api("rules", {})["rules"][0]["id"], "1")
        self.assertEqual(len(r["rules"]), 18)
        names = {m["name"]: m for m in r["modules"]}
        self.assertIn("graph-first", names)
        self.assertTrue(all(m["summary"] for m in r["modules"]))

    def test_rule_edit_add_and_undo(self):
        import io
        from contextlib import redirect_stdout
        from lfgcore import cli
        plugin = tempfile.mkdtemp(prefix="lfg-test-plugin-")
        C.write_text(os.path.join(plugin, "rules", "demo.md"), "# demo: shipped text\n")
        with mock.patch.object(C, "PLUGIN_DIR", plugin), mock.patch.object(cli, "plugin_dir", lambda: plugin):
            ST.save_rule("demo", "# demo: my text\n")
            ST.save_rule("api-style", "# api-style: use REST nouns\n")
            mods = {m["name"]: m for m in ST.rules()["modules"]}
            self.assertTrue(mods["demo"]["edited"] and not mods["demo"]["yours"])
            self.assertEqual(mods["demo"]["summary"], "my text")
            self.assertTrue(mods["api-style"]["yours"])
            self.assertEqual(ST.own_rules(), ["api-style"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.cmd_rule(types.SimpleNamespace(name="demo"))
            self.assertIn("my text", buf.getvalue())
            for bad in (("Bad Name", "x"), ("ok", " "), ("ok", "token ghp_" + "a" * 36)):
                with self.assertRaises(ST.Invalid, msg=bad):
                    ST.save_rule(*bad)
            self.assertFalse(ST.reset_rule("demo")["deleted"])
            self.assertEqual(ST.rule_text("demo"), "# demo: shipped text\n")
            self.assertTrue(ST.reset_rule("api-style")["deleted"])
            self.assertIsNone(ST.rule_text("api-style"))
            with self.assertRaises(ST.Invalid):
                ST.reset_rule("demo")

    def test_graph_build_needs_a_known_repo(self):
        with self.assertRaises(ST.Invalid):
            ui.build_graphs("nope-12345678", "update")
        self.assertIn("/api/save/graphs_build", ui.NO_KEY)

    def test_lean_output_drops_passing_check_logs(self):
        from lfgcore import cli
        checks = [{"name": "lint", "exit": 0, "tail": "x" * 500}, {"name": "test", "exit": 1, "tail": "boom"},
                  {"name": "build", "exit": None, "tail": "no command"}]
        lean = cli._lean(checks, lambda c: c["exit"] == 0)
        self.assertNotIn("tail", lean[0])
        self.assertEqual(lean[1]["tail"], "boom")
        self.assertEqual(lean[2]["tail"], "no command")
        self.assertIn("tail", checks[0])  # the result written to ready.json keeps everything

    def test_emit_json_is_compact(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            C.emit({"a": [1, 2], "b": {"c": "d"}}, True, None)
        self.assertEqual(buf.getvalue().strip(), '{"a":[1,2],"b":{"c":"d"}}')


class BranchAndStorageTest(unittest.TestCase):
    def _git(self, *args):
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args], cwd=self.root,
                       check=True, capture_output=True)

    def setUp(self):
        import shutil
        self.root = tempfile.mkdtemp(prefix="lfg-branch-repo-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self._git("init", "-q", "-b", "main")
        self._git("commit", "-q", "--allow-empty", "-m", "base")
        self._git("branch", "feat-merged")
        self._git("checkout", "-q", "-b", "feat-live")
        self._git("commit", "-q", "--allow-empty", "-m", "live")
        self._git("checkout", "-q", "main")
        self.rid = "branchy-" + os.path.basename(self.root)[-6:]
        self.addCleanup(lambda: [shutil.rmtree(C.lfg_path(d, self.rid), True) for d in ("runs", "graphs")])
        C.write_json(C.lfg_path("graphs", self.rid, "state.json"), {"repo_root": self.root})
        self.runs = {b: C.new_run(self.rid, "r-" + (b or "none"), branch=b)
                     for b in ("feat-merged", "gone", "feat-live", "main", "")}
        os.remove(C.lfg_path("runs", self.rid, "CURRENT"))

    def _mine(self):
        return {c["id"]: c for c in ST._candidates() if c["repo"] == self.rid}

    def test_new_run_records_branch_and_views_filter_by_it(self):
        self.assertEqual(C.git_branch(self.root), "main")
        self.assertEqual(dash.run_branch(self.runs["feat-live"]), "feat-live")
        self.assertEqual([r["branch"] for r in dash.runs(self.rid, "feat-live")["runs"]], ["feat-live"])
        self.assertEqual(len(dash.runs(self.rid, dash.UNRECORDED)["runs"]), 1)
        self.assertEqual(len(dash.runs(self.rid)["runs"]), 5)
        b = dash.branches(self.rid)
        states = {x["name"]: x["state"] for x in b["branches"]}
        self.assertEqual(states, {"feat-merged": "merged", "gone": "deleted", "feat-live": "local", "main": "current"})
        self.assertEqual((b["unrecorded"], b["graphs_follow"]), (1, "main"))

    def test_cleanup_offers_only_merged_or_deleted_branches_and_deletes_only_those(self):
        self.assertEqual(set(self._mine()), {"runs:%s:feat-merged" % self.rid, "runs:%s:gone" % self.rid})
        with self.assertRaises(ST.Invalid):
            ST.cleanup(["runs:%s:feat-live" % self.rid])
        with self.assertRaises(ST.Invalid):
            ST.cleanup([])
        self.assertTrue(ST.cleanup(["runs:%s:gone" % self.rid])["ok"])
        self.assertFalse(os.path.exists(self.runs["gone"]))
        for b in ("feat-merged", "feat-live", "main", ""):
            self.assertTrue(os.path.isdir(self.runs[b]), b)

    def test_current_run_is_never_offered(self):
        C.write_text(C.lfg_path("runs", self.rid, "CURRENT"), os.path.basename(self.runs["gone"]) + "\n")
        self.assertNotIn("runs:%s:gone" % self.rid, self._mine())

    def test_missing_repo_and_idle_graphs_are_offered(self):
        st = C.lfg_path("graphs", self.rid, "state.json")
        os.utime(st, (0, 0))
        self.assertIn("graphs:" + self.rid, self._mine())
        C.write_json(st, {"repo_root": os.path.join(self.root, "gone-folder")})
        self.assertEqual(list(self._mine()), ["repo:" + self.rid])
        ST.cleanup(["repo:" + self.rid])
        self.assertFalse(os.path.exists(C.lfg_path("runs", self.rid)))
        self.assertFalse(os.path.exists(C.lfg_path("graphs", self.rid)))

    def test_cleanup_refuses_paths_outside_lfg_home(self):
        fake = [{"id": "x", "repo": self.rid, "paths": [self.root]}]
        with mock.patch.object(ST, "_candidates", return_value=fake):
            with self.assertRaises(ST.Invalid):
                ST.cleanup(["x"])
        self.assertTrue(os.path.isdir(self.root))

    def test_storage_view_reports_limit(self):
        d = ui.api("storage", {})
        self.assertEqual(d["limit_mb"], 500)
        self.assertIn(self.rid, [r["repo"] for r in d["repos"]])
        self.assertNotIn("paths", json.dumps(d["candidates"]))


class RememberFlowTest(unittest.TestCase):
    PLUGIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin")

    def test_remember_is_wired_everywhere_and_always_asks_first(self):
        rule = C.read_text(os.path.join(self.PLUGIN, "rules", "remember.md"))
        self.assertIn("Nothing is written until the user picks where it goes", rule)
        note = C.read_text(os.path.join(self.PLUGIN, "skills", "note", "SKILL.md"))
        self.assertIn("Never write before the user picked the graph", note)
        from lfgcore import hooks as H
        self.assertIn("lfg rule remember", " ".join(H.CONTEXT))
        for agent in ("software-engineer", "expert-review", "qa", "product-manager"):
            self.assertIn("## Remember?", C.read_text(os.path.join(self.PLUGIN, "agents", agent + ".md")), agent)
        import io
        from contextlib import redirect_stdout
        from lfgcore import hooks
        buf = io.StringIO()
        with mock.patch.object(C, "run", return_value=subprocess.CompletedProcess([], 1, "", "")), \
                mock.patch.object(hooks, "_repo", return_value=(None, None)), redirect_stdout(buf):
            hooks.session_start({})
        self.assertIn("lfg rule remember", buf.getvalue())


class SecurityAuditVendorTest(unittest.TestCase):
    PLUGIN = RememberFlowTest.PLUGIN
    VENDOR = os.path.join(PLUGIN, "vendor", "cloudflare-security-audit")

    def test_vendored_files_match_the_pinned_checksums(self):
        import hashlib
        import re
        upstream = C.read_text(os.path.join(self.VENDOR, "UPSTREAM.md"))
        self.assertIn("c1c8a8c1471069fb0e188eeaff69b8e8db6564a8", upstream)
        sums = dict((n, h) for h, n in re.findall(r"^([0-9a-f]{64})  (\S+)$", upstream, re.M))
        on_disk = sorted(n for n in os.listdir(self.VENDOR) if n != "UPSTREAM.md")
        self.assertEqual(sorted(sums), on_disk)
        for name, digest in sums.items():
            with open(os.path.join(self.VENDOR, name), "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), digest, name)

    def test_secure_uses_it_and_never_runs_target_code(self):
        skill = C.read_text(os.path.join(self.PLUGIN, "skills", "secure", "SKILL.md"))
        for s in ("vendor/cloudflare-security-audit", "guidance mode", "/secure audit", "Agree the budget first",
                  "No target code is executed", "validate-findings.cjs", "validate-coverage-ledger.cjs",
                  "<run>/security-audit/"):
            self.assertIn(s, skill)
        agent = C.read_text(os.path.join(self.PLUGIN, "agents", "security-analyst.md"))
        self.assertIn("cloudflare-security-audit", agent)
        self.assertIn("needs_validation", agent)


class UsageTest(unittest.TestCase):
    def setUp(self):
        from lfgcore import sessions as SS
        self.SS = SS
        self.dir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        p = mock.patch.object(SS, "PROJECTS", self.dir)
        p.start()
        self.addCleanup(p.stop)

    def test_usage_counts_each_reply_once_and_prices_it(self):
        u = {"input_tokens": 1000000, "output_tokens": 100000, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 0}
        reply = {"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "message": {"id": "msg_1", "model": "claude-opus-5-5", "usage": u}}
        d = os.path.join(self.dir, "-nowhere-app")
        os.makedirs(d)
        with open(os.path.join(d, "%08d-0000-0000-0000-000000000000.jsonl" % 1), "w") as f:
            f.write(json.dumps(reply) + "\n" + json.dumps(reply) + "\n")  # one reply, logged twice (two blocks)
        with mock.patch.object(self.SS, "_usage_index_path", lambda: os.path.join(self.dir, "idx.json")):
            d = self.SS.usage()
        self.assertEqual(d["models"][0]["input"], 1000000)
        self.assertEqual(d["spend"]["today"], 6.0)  # 1M in at $4 + 0.1M out at $20

    def test_headroom_savings_add_up_per_day(self):
        from lfgcore import hrstats
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        with open(os.path.join(self.dir, "savings_events.jsonl"), "w") as f:
            for saved in (100, 300):
                f.write(json.dumps({"ts": now, "model": "claude-opus-5-5", "before": 1000, "saved": saved,
                                    "cost_usd": 0.5}) + "\n")
            f.write("not json\n")
        with mock.patch.object(hrstats, "HR_HOME", self.dir):
            w = hrstats.when(30)
        self.assertEqual(len(w["days"]), 1)
        self.assertEqual((w["days"][0]["saved"], w["days"][0]["usd"], w["days"][0]["percent"]), (400, 1.0, 20.0))
        self.assertEqual(sum(h["calls"] for h in w["today_by_hour"]), 2)


if __name__ == "__main__":
    unittest.main()


class RepoGraphsAndWorktreesTest(unittest.TestCase):
    """Graphs live in the main checkout (git-ignored, shared by every branch and worktree); `lfg worktree`."""

    def _git(self, *args, cwd=None):
        return subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                              cwd=cwd or self.root, check=True, capture_output=True, text=True).stdout

    def setUp(self):
        import shutil
        self.parent = os.path.realpath(tempfile.mkdtemp(prefix="lfg-wt-"))
        self.addCleanup(shutil.rmtree, self.parent, True)
        self.root = os.path.join(self.parent, "app")
        os.makedirs(self.root)
        self._git("init", "-q", "-b", "main")
        with open(os.path.join(self.root, "a.py"), "w") as fh:
            fh.write("x = 1\n")
        self._git("add", "a.py")
        self._git("commit", "-q", "-m", "base")
        self.rid = C.repo_id(self.root)
        self.addCleanup(lambda: [shutil.rmtree(C.lfg_path(d, self.rid), True) for d in ("runs", "graphs")])

    def test_worktree_shares_main_root_and_repo_id(self):
        from lfgcore import worktree as W
        res = W.new(self.root, "feat/x")
        self.assertEqual(res["path"], os.path.join(self.parent, "app.worktrees", "feat-x"))
        self.assertTrue(res["created_branch"])
        self.assertEqual(C.main_root(res["path"]), self.root)
        self.assertEqual(C.repo_id(res["path"]), self.rid)
        self.assertEqual(C.main_root(self.root), self.root)
        self.assertEqual(self._git("branch", "--show-current"), "main\n")  # the user's checkout is untouched
        mine = [w for w in W.listing(self.root) if w["lfg"]]
        self.assertEqual([w["branch"] for w in mine], ["feat/x"])
        with self.assertRaises(ValueError):
            W.new(self.root, "feat/x")  # folder exists
        with self.assertRaises(ValueError):
            W.new(self.root, "--force")
        with self.assertRaises(ValueError):
            W.new(self.root, "main", "HEAD")  # --from only for a new branch

    def test_remove_refuses_dirty_and_keeps_branch(self):
        from lfgcore import worktree as W
        path = W.new(self.root, "fix-1")["path"]
        with open(os.path.join(path, "new.txt"), "w") as fh:
            fh.write("wip\n")
        with self.assertRaises(RuntimeError):
            W.remove(self.root, "fix-1")
        self.assertTrue(os.path.isdir(path))
        os.remove(os.path.join(path, "new.txt"))
        with self.assertRaises(ValueError):
            W.remove(self.root, "main")  # never the main checkout or a worktree LFG didn't make
        W.remove(self.root, "fix-1")
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(W.base_dir(self.root)))
        self.assertIn("fix-1", self._git("branch", "--list", "fix-1"))

    def test_data_dirs_are_in_repo_ignored_and_legacy_graphs_move(self):
        from lfgcore import graphs as G
        legacy = C.lfg_path("graphs", self.rid, "graphify")
        os.makedirs(legacy)
        C.write_text(os.path.join(legacy, "graph.json"), "{}")
        G._prepare(self.root, self.rid)
        self.assertEqual(G.data_dir(self.rid, "crg", self.root), os.path.join(self.root, ".code-review-graph"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "graphify-out", "graph.json")))
        self.assertTrue(os.path.islink(legacy))  # the old path now points into the repo
        for d in G.DATA.values():
            self.assertEqual(C.read_text(os.path.join(self.root, d, ".gitignore")), "*\n")
        self.assertEqual(self._git("status", "--porcelain", "--ignored=no", "--untracked-files=all"), "")
        wt = os.path.join(self.parent, "wt")
        self._git("worktree", "add", "-q", wt, "-b", "other")
        self.assertEqual(G.data_dir(self.rid, "graphify", wt), os.path.join(self.root, "graphify-out"))

    def test_old_graph_paths_become_symlinks_to_the_repo(self):
        from lfgcore import graphs as G
        G._prepare(self.root, self.rid)
        link = C.lfg_path("graphs", self.rid, "graphify")
        self.assertEqual(os.path.realpath(link), os.path.join(self.root, "graphify-out"))
        G._prepare(self.root, self.rid)  # idempotent
        self.assertTrue(os.path.islink(link))
        self.assertEqual(ST._du(C.lfg_path("graphs", self.rid)), 0)  # links are not counted twice

    def test_prune_removes_only_clean_idle_lfg_worktrees(self):
        from lfgcore import worktree as W
        clean = W.new(self.root, "idle")["path"]
        dirty = W.new(self.root, "busy")["path"]
        fresh = W.new(self.root, "fresh")["path"]
        C.write_text(os.path.join(dirty, "wip.txt"), "x")
        old = __import__("time").time() - 3 * 86400
        for p in (clean, dirty):
            admin = self._git("rev-parse", "--absolute-git-dir", cwd=p).strip()
            for f in (p, os.path.join(admin, "index"), os.path.join(admin, "HEAD")):
                if os.path.exists(f):
                    os.utime(f, (old, old))
        self.assertEqual(W.prune(self.root), [clean])
        self.assertFalse(os.path.exists(clean))
        self.assertTrue(os.path.isdir(dirty) and os.path.isdir(fresh))
        self.assertIn("idle", self._git("branch", "--list", "idle"))

    def test_missing_graph_is_not_fresh(self):
        from lfgcore import graphs as G
        G.save_state(self.rid, {"fingerprint": G.snapshot(self.root)["fingerprint"], "repo_root": self.root})
        with mock.patch.object(C, "which", return_value="/bin/x"):
            self.assertFalse(G.present(self.rid, self.root))
            self.assertEqual(G.status(self.root, self.rid)["status"], "missing")
        with mock.patch.object(C, "which", return_value=None):
            self.assertEqual(G.status(self.root, self.rid)["status"], "fresh")

    def test_storage_counts_repo_graphs_separately_and_cleanup_stays_in_known_dirs(self):
        from lfgcore import graphs as G
        G.save_state(self.rid, {"repo_root": self.root})
        G._prepare(self.root, self.rid)
        C.write_text(os.path.join(self.root, "graphify-out", "graph.html"), "x" * 300000)
        d = ST.storage()
        row = [r for r in d["repos"] if r["repo"] == self.rid][0]
        self.assertGreater(row["repo_graphs_mb"], 0)
        self.assertGreaterEqual(d["in_repos_mb"], row["repo_graphs_mb"])
        os.utime(C.lfg_path("graphs", self.rid, "state.json"), (0, 0))
        cand = [c for c in ST._candidates() if c["id"] == "graphs:" + self.rid][0]
        self.assertIn(os.path.join(self.root, "graphify-out"), cand["paths"])
        bad = [{"id": "x", "repo": self.rid, "paths": [os.path.join(self.root, "a.py")]}]
        with mock.patch.object(ST, "_candidates", return_value=bad):
            with self.assertRaises(ST.Invalid):
                ST.cleanup(["x"])
        self.assertTrue(os.path.isfile(os.path.join(self.root, "a.py")))
        ST.cleanup(["graphs:" + self.rid])
        self.assertFalse(os.path.exists(os.path.join(self.root, "graphify-out")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "a.py")))

    def test_graphdata_route_is_confined(self):
        from lfgcore import graphs as G
        G.save_state(self.rid, {"repo_root": self.root})
        G._prepare(self.root, self.rid)
        C.write_text(os.path.join(self.root, "graphify-out", "graph.html"), "<p>ok</p>")
        C.write_text(os.path.join(self.root, "graphify-out", "graph.json"), "{}")
        h = object.__new__(ui.Handler)
        sent = []
        h._send = lambda code, *a, **k: sent.append(code)
        for rel, code in (("%s/graphify/graph.html" % self.rid, 200), ("%s/graphify/graph.json" % self.rid, 404),
                          ("%s/graphify/../a.py" % self.rid, 404), ("%s/other/graph.html" % self.rid, 404),
                          ("not-a-repo/graphify/graph.html", 404)):
            sent.clear()
            h._graphdata(rel)
            self.assertEqual(sent, [code], rel)


class RepoNameTest(unittest.TestCase):
    def test_repos_show_folder_name_not_id(self):
        from lfgcore import dash
        root = tempfile.mkdtemp(prefix="lfg-test-names-")
        for rid, sub in (("api-aaaaaaaa", "one/api"), ("api-bbbbbbbb", "two/api"), ("web-cccccccc", None)):
            st = {"repo_root": os.path.join(root, sub)} if sub else {}
            C.write_json(C.lfg_path("graphs", rid, "state.json"), st)
        with mock.patch.object(dash, "repo_ids", lambda: ["api-aaaaaaaa", "api-bbbbbbbb", "web-cccccccc"]):
            names = {r["id"]: r["name"] for r in dash.repos()["repos"]}
        self.assertEqual(names, {"api-aaaaaaaa": "api (one)", "api-bbbbbbbb": "api (two)", "web-cccccccc": "web"})


class OnboardingTourTest(unittest.TestCase):
    def test_tour_has_plain_counts_and_folder_names(self):
        import collections
        nodes = [{"id": "a", "label": "Thing", "file_type": "code", "community_name": "Community 3",
                  "source_file": "src/billing/invoice.ts"},
                 {"id": "b", "label": "Other", "file_type": "code", "community_name": "Community 3",
                  "source_file": "src/billing/tax.ts"}]
        g = {"nodes": nodes, "links": [{"source": "a", "target": "b"}], "_degree": collections.Counter(a=1, b=1)}
        sections = {"Summary": "- 2 nodes · EXTRACTED: 97% · Token cost: 0 input"}
        with mock.patch.object(D, "wiki_pages", lambda rid: []):
            text = D._onboarding("demo-12345678", "", g, sections, None)
        self.assertIn("2 code files, 2 symbols and 1 links between them, in 1 areas.", text)
        self.assertIn("**billing**", text)
        self.assertNotIn("Community 3", text)
        self.assertNotIn("EXTRACTED", text)


class IssueScopeTest(unittest.TestCase):
    def test_issues_follow_repo_branch_and_run_progress(self):
        rid = "scope-1234abcd"
        run = C.lfg_path("runs", rid, "20261001-0000-thing")
        C.write_json(os.path.join(run, "run.json"), {"issue": "iss-big-thing", "branch": "feat/x"})
        C.write_json(os.path.join(run, "tasks.json"), [{"id": "thing-001", "passes": True, "description": "Do one"},
                                                       {"id": "thing-002", "passes": False},
                                                       {"id": "thing-003", "passes": False}])
        old, new = "2026-01-01", time.strftime("%Y-%m-%d")
        rows = [{"slug": "iss-big-thing", "status": "in_progress", "updatedAt": new},
                {"slug": "iss-thing-001", "status": "todo", "updatedAt": new},
                {"slug": "iss-thing-002", "status": "todo", "updatedAt": old},
                {"slug": "ato-77", "status": "todo", "updatedAt": new},
                {"slug": "iss-elsewhere", "status": "todo", "updatedAt": old},
                {"slug": "iss-thing-003", "status": "todo", "updatedAt": new, "description": "Repo: other. Run x."},
                {"slug": "iss-named", "status": "todo", "updatedAt": new, "description": "Repo: scope. Run y."}]
        inv = {"ready": [{"slug": "iss-thing-002"}, {"slug": "iss-elsewhere"}, {"slug": "iss-thing-001"}],
               "blocked": [{"slug": "ato-77"}, {"slug": "ato-77"}], "open_epics": []}
        gb = {"local": ["main", "feat/x", "kim/ato-77-fix"], "merged": set(), "default": "main", "current": "main"}
        with mock.patch.object(dash, "og_access", lambda n: None), \
                mock.patch.object(dash, "_list", lambda *a, **k: rows if a[1] == "Issue" else []), \
                mock.patch.object(dash, "_inv", lambda n, q, p=None: inv[q]), \
                mock.patch.object(dash, "git_branches", lambda root: gb), \
                mock.patch.object(dash, "repo_root", lambda r: "/src/scope"):
            d = dash.issues(rid)
            by = {i["slug"]: i for i in d["issues"]}
            self.assertEqual(set(by), {"iss-big-thing", "iss-thing-001", "iss-thing-002", "ato-77", "iss-named"})
            self.assertEqual(d["hidden"], 2)  # iss-elsewhere (no link) and iss-thing-003 (says another repo)
            self.assertEqual((by["iss-thing-001"]["status"], by["iss-thing-001"]["graph_status"]), ("done", "todo"))
            self.assertEqual(by["ato-77"]["branches"], ["kim/ato-77-fix"])
            self.assertEqual([r["slug"] for r in d["ready"]], ["iss-thing-002"])  # done and other repos drop out
            self.assertEqual([r["slug"] for r in d["blocked"]], ["ato-77"])  # once, not per blocker
            self.assertEqual([i["slug"] for i in d["stale"]], ["iss-thing-002"])
            self.assertEqual({i["slug"] for i in dash.issues(rid, "kim/ato-77-fix")["issues"]}, {"ato-77"})
            self.assertEqual(len(dash.issues(rid, "feat/x")["issues"]), 3)
            self.assertEqual((by["iss-thing-001"]["description"], by["iss-thing-001"]["text_from"]),
                             ("Do one", "20261001-0000-thing"))
            # no run text to fill it from: left as saved
            self.assertEqual(by["iss-named"]["description"], "Repo: scope. Run y.")


class SharedRunTest(unittest.TestCase):
    def test_a_run_shows_under_every_repo_its_tasks_name(self):
        api, portal = "api-11111111", "acme-portal-22222222"
        run = C.lfg_path("runs", api, "20261002-0000-span")
        C.write_json(os.path.join(run, "run.json"), {"branch": "main"})
        for f in ("01-brief.md", "02-design.md", "04-qa.md"):
            C.write_text(os.path.join(run, f), "x")
        C.write_json(os.path.join(run, "06-review.json"), {"verdict": "changes"})
        C.write_json(os.path.join(run, "tasks.json"), [{"id": "s-001", "repo": "api", "passes": True},
                                                       {"id": "s-portal-1", "repo": "portal", "passes": False}])
        roots = {api: "/src/api", portal: "/src/acme-portal"}
        with mock.patch.object(dash, "repo_ids", lambda: [api, portal]), \
                mock.patch.object(dash, "repo_root", lambda r: roots.get(r)):
            self.assertTrue(dash.repo_matches(portal, "portal"))
            self.assertFalse(dash.repo_matches(portal, "tal"))
            self.assertFalse(dash.repo_matches(api, "portal"))
            mine = dash.runs(portal)["runs"]
            self.assertEqual([(r["run"], r["owner_name"], r["tasks_here"], r["tasks_here_done"]) for r in mine],
                             [("20261002-0000-span", "api", 1, 0)])
            self.assertEqual(dash.runs(portal, "main")["runs"], [])  # main is api's branch, not the portal's
            self.assertEqual(mine[0]["progress"], 3)  # brief/design/tasks; api's checks are not the portal's
            self.assertIsNone(mine[0]["review"])
            det = dash.run_detail(portal, "20261002-0000-span")
            self.assertEqual((det["owner_name"], [t["id"] for t in det["tasks_list"]]), ("api", ["s-portal-1"]))
            self.assertEqual(dash.run_detail(portal, "nope").get("available"), False)
            self.assertNotIn("owner", dash.runs(api)["runs"][0])
            self.assertEqual(det["checks"], [])  # api's checks ran on api's code
            C.write_json(os.path.join(run, "05-secure-portal.json"), {"verdict": "safe", "findings": [{"id": "P-1"}]})
            C.write_json(os.path.join(run, "05-secure.json"), {"verdict": "don't", "blocking": 3})
            self.assertEqual([x["verdict"] for x in dash.security(portal)["secure"]], ["safe"])
            self.assertEqual([x["verdict"] for x in dash.security(api)["secure"]], ["don't"])  # not the portal's
            self.assertEqual(dash.runs(portal)["runs"][0]["secure"], "safe")
            self.assertTrue(dash.runs(portal)["runs"][0]["stages"]["secure"])

    def test_checks_older_than_the_work_are_out_of_date(self):
        d = tempfile.mkdtemp()
        C.write_json(os.path.join(d, "ready.json"), {"green": False, "checks": [{"name": "types", "exit": 1}]})
        self.assertEqual(dash._run_summary(d)["ready"], "red")
        C.write_text(os.path.join(d, "03-build-t1.md"), "built")
        later = os.path.getmtime(os.path.join(d, "ready.json")) + 60
        os.utime(os.path.join(d, "03-build-t1.md"), (later, later))
        self.assertEqual(dash._run_summary(d)["ready"], "stale")


class RunChecksTest(unittest.TestCase):
    def test_rerun_only_the_current_run_and_once_at_a_time(self):
        from lfgcore import settings as ST2
        rid = "chk-33333333"
        root = tempfile.mkdtemp()
        cur, old = C.lfg_path("runs", rid, "20261003-0000-now"), C.lfg_path("runs", rid, "20261001-0000-old")
        for d in (cur, old):
            C.write_json(os.path.join(d, "run.json"), {"worktrees": [{"path": root}]})
        C.write_text(C.lfg_path("runs", rid, "CURRENT"), "20261003-0000-now")
        started = []
        fake = types.SimpleNamespace(pid=os.getpid())
        with mock.patch.object(dash, "repo_ids", lambda: [rid]), mock.patch.object(dash, "repo_root", lambda r: root), \
                mock.patch("subprocess.Popen", lambda argv, **k: started.append((argv, k["cwd"])) or fake):
            with self.assertRaises(ST2.Invalid):
                ui.run_checks(rid, "20261001-0000-old")
            self.assertEqual(ui.run_checks(rid, "20261003-0000-now"), {"started": True})
            self.assertEqual((started[0][0][-2:], started[0][1]), (["gate", "--json"], root))
            self.assertTrue(dash.run_detail(rid, "20261003-0000-now")["checking"])  # its pid is alive
            self.assertEqual(ui.run_checks(rid, "20261003-0000-now"), {"started": False, "running": True})
            self.assertEqual(len(started), 1)


class PrReviewTest(unittest.TestCase):
    """The Reviews page's flow against a real local "origin" that has refs/pull/1/head; gh and claude are faked."""

    def setUp(self):
        from lfgcore import prreview as PR
        self.PR = PR
        top = tempfile.mkdtemp(prefix="lfg-pr-")
        origin, self.root = os.path.join(top, "origin.git"), os.path.join(top, "app")
        def g(cwd, *a):
            subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
        g(top, "init", "-q", "--bare", origin)
        g(top, "init", "-q", "-b", "main", self.root)
        for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
            g(self.root, "config", k, v)
        C.write_text(os.path.join(self.root, "a.py"), "one\ntwo\nthree\n")
        g(self.root, "add", ".")
        g(self.root, "commit", "-qm", "base")
        g(self.root, "remote", "add", "origin", origin)
        g(self.root, "push", "-q", "origin", "main")
        g(self.root, "checkout", "-qb", "feature")
        C.write_text(os.path.join(self.root, "a.py"), "one\ntwo\nthree\nfour\n")
        g(self.root, "commit", "-qam", "add four")
        g(self.root, "push", "-q", "origin", "feature:refs/pull/1/head")
        g(self.root, "checkout", "-q", "main")
        self.rid = "app-%08x" % (abs(hash(self._testMethodName)) % 16 ** 8)  # each test its own review state
        self.pr = {"number": 1, "title": "Add four", "author": {"login": "kim"}, "url": "https://github.com/o/app/pull/1",
                   "baseRefName": "main", "headRefName": "feature", "body": "adds a line"}
        self.runs = []
        self.patches = [mock.patch.object(PR, "_pr_view", lambda root, n: self.pr),
                        mock.patch.object(PR, "_run", lambda rid, root, n, kind, prompt, resume:
                                          self.runs.append((kind, resume)))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_review_flow_from_worktree_to_post(self):
        PR, rid, root = self.PR, self.rid, self.root
        out = PR.start(rid, root, 1)
        wt = out["worktree"]
        self.assertEqual(os.path.basename(wt), "review-pr-1")
        self.assertEqual(C.read_text(os.path.join(wt, "a.py")), "one\ntwo\nthree\nfour\n")  # the PR's code
        self.assertEqual(subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True,
                                        text=True).stdout.strip(), "main")  # the user's checkout didn't move
        self.assertEqual(self.runs, [("review", False)])
        # the AI's answer arrives: chat + draft
        res = {"result": "**LFG:** /lfg:expert\n\nLooks fine.\n```json\n" + json.dumps({
            "summary": "Adds a fourth line.", "verdict": "changes",
            "ratings": [{"area": "Tests", "score": 2, "why": "no test"}],
            "questions": [{"id": "Q1", "ask": "Why four?", "why": "scope"}],
            "comments": [{"id": "C1", "path": "a.py", "line": 4, "body": "Name this.", "severity": "minor"},
                         {"id": "C2", "path": "a.py", "line": 99, "body": "Elsewhere.", "severity": "nit"}],
            "context": ["dev-graph Principle p-1"]}) + "\n```"}
        out_file = os.path.join(PR.folder(rid, 1), "job-1.out")
        C.write_text(out_file, json.dumps(res))
        C.write_json(os.path.join(PR.folder(rid, 1), "job.json"), {"pid": 999999999, "kind": "review", "out": out_file})
        d = PR.detail(rid, root, 1)
        self.assertEqual(d["review"]["status"], "ready")
        self.assertEqual(d["review"]["worktree_name"], "review-pr-1")
        self.assertEqual(d["chat"][-1]["text"], "**LFG:** /lfg:expert\n\nLooks fine.")
        self.assertEqual([(c["id"], c["inline"]) for c in d["draft"]["comments"]], [("C1", True), ("C2", False)])
        # the reviewer's own edits survive and decide what is posted
        PR.save_draft(rid, 1, {"summary": "Please add a test.", "event": "REQUEST_CHANGES",
                               "ratings": [{"area": "Tests", "mine": 1}],
                               "comments": [{"id": "C1", "path": "a.py", "line": 4, "body": "Name this.",
                                             "include": True},
                                            {"id": "C2", "path": "a.py", "line": 99, "body": "Elsewhere.",
                                             "include": True}]})
        o = PR.outgoing(rid, 1)
        self.assertEqual((o["event"], o["comments"], o["in_body"]),
                         ("REQUEST_CHANGES", [{"path": "a.py", "line": 4, "side": "RIGHT", "body": "Name this."}], 1))
        self.assertIn("| Tests | 1/5 |", o["body"])
        self.assertIn("**a.py:99**: Elsewhere.", o["body"])
        with self.assertRaises(PR.Invalid):  # a secret never goes out, not even in a draft
            PR.save_draft(rid, 1, {"summary": "key AKIA" + "ABCDEFGHIJKLMNOP"})
        sent = []
        ok = subprocess.CompletedProcess([], 0, json.dumps({"html_url": "https://github.com/o/app/pull/1#r1"}), "")
        with mock.patch.object(PR, "_gh", lambda root, *a, **k: sent.append((a, json.loads(k["input"]))) or ok):
            self.assertEqual(PR.post(rid, root, 1)["url"], "https://github.com/o/app/pull/1#r1")
            with self.assertRaises(PR.Invalid):
                PR.post(rid, root, 1)  # once only
        self.assertEqual(sent[0][0][:4], ("api", "-X", "POST", "repos/o/app/pulls/1/reviews"))
        self.assertEqual(sent[0][1]["event"], "REQUEST_CHANGES")
        # done: the worktree goes, the chat and draft stay
        self.assertEqual(PR.close(rid, root, 1), {"closed": True})
        self.assertFalse(os.path.exists(wt))
        self.assertTrue(PR.chat(rid, 1))

    def test_chat_keeps_the_reviewers_scores_and_switches(self):
        PR, rid = self.PR, self.rid
        PR.start(rid, self.root, 1)
        PR.save_draft(rid, 1, {"ratings": [{"area": "Tests", "mine": 4}]})
        PR.apply(rid, 1, {"comments": [{"id": "C9", "body": "General point."}],
                          "ratings": [{"area": "Tests", "score": 2, "why": "thin"}]})
        PR.save_draft(rid, 1, {"comments": [{"id": "C9", "body": "General point.", "include": False}]})
        PR.apply(rid, 1, {"comments": [{"id": "C9", "body": "General point, reworded."}]})
        d = PR._read(rid, 1, "draft.json", {})
        tests = [r for r in d["ratings"] if r["area"] == "Tests"][0]
        self.assertEqual((tests["mine"], tests["ai"]), (4, 2))
        self.assertEqual((d["comments"][0]["body"], d["comments"][0]["include"]), ("General point, reworded.", False))
        with self.assertRaises(PR.Invalid):
            PR.ask(rid, self.root, 1, "  ")

    def test_threads_include_every_unresolved_comment_people_and_bots(self):
        PR = self.PR

        def node(i, who, body, typ="User"):
            return {"databaseId": i, "author": {"login": who, "__typename": typ}, "body": body, "url": "u%d" % i}
        summary = ("**Actionable comments posted: 1**\n> **Outside diff range comments (1)**\n> <details>\n"
                   "> <summary>Minor · Fix the count · <code>sync.ts:88-91</code></summary><blockquote>\n>\n"
                   "> `src/sync.ts:88-91`\n> **Correctness** | **Minor**\n>\n> **Fix the count.**\n>\n"
                   "> <details>\n> <summary>🤖 Prompt for AI Agents</summary>\n> do this\n> </details>\n"
                   "> <!-- cr-comment:v1:aa11 -->\n> </blockquote></details>\n"
                   "<details>\n<summary>🧹 Nitpick comments: 1</summary><blockquote>\n<details>\n"
                   "<summary>src/util.ts: 1</summary><blockquote>\n\n`12-14`: **Style** | **Trivial**\n\n"
                   "**Rename x.**\n\n<!-- cr-comment:v1:bb22 -->\n</blockquote></details>\n")
        page1 = {"reviewThreads": {"pageInfo": {"hasNextPage": True, "endCursor": "c1"}, "nodes": [
                     {"isResolved": False, "isOutdated": False, "path": "a.py", "line": 4,
                      "comments": {"nodes": [node(1, "coderabbitai", "<!-- state -->Null check?", "Bot"),
                                             node(2, "me", "on it")]}},
                     {"isResolved": True, "path": "a.py", "line": 2,
                      "comments": {"nodes": [node(3, "kim", "typo")]}}]},
                 "reviews": {"nodes": [node(5, "kim", "Looks good but see a.py"),
                                       node(6, "coderabbitai", summary, "Bot"),
                                       node(7, "devin-ai-integration", "**Devin Review** found 8 potential issues.",
                                            "Bot")]},
                 "comments": {"nodes": [node(8, "vercel", "[vc]: #abc=", "Bot"), node(9, "lee", "Can we ship today?"),
                                        node(10, "sonarqubecloud", "## Quality Gate Failed\n3 new issues", "Bot"),
                                        node(11, "coderabbitai", "No actionable comments were generated in the recent "
                                                                 "review.", "Bot")]}}
        page2 = {"reviewThreads": {"pageInfo": {"hasNextPage": False}, "nodes": [
                     {"isResolved": False, "path": "b.py", "line": 9,
                      "comments": {"nodes": [node(12, "devin-ai-integration", "Race here", "Bot")]}}]},
                 "reviews": {"nodes": []}, "comments": {"nodes": []}}
        pages = iter([page1, page2])

        def gh(root, *a, **k):
            body = json.dumps({"data": {"repository": {"pullRequest": next(pages)}}})
            return subprocess.CompletedProcess([], 0, body, "")
        with mock.patch.object(PR, "_gh", gh), mock.patch.object(PR, "me", lambda root: "me"):
            ths = PR.threads("/x", "https://github.com/o/app/pull/1", 1)
        by = {t["id"]: t for t in ths}
        self.assertEqual(sorted(by), ["b-aa11", "b-bb22", "c-10", "c-9", "r-5", "t-1", "t-12", "t-3"])
        self.assertEqual((by["b-aa11"]["path"], by["b-aa11"]["line"], by["b-aa11"]["from_summary"]),
                         ("src/sync.ts", 88, True))
        self.assertNotIn("Prompt for AI", by["b-aa11"]["body"])
        self.assertEqual((by["b-bb22"]["path"], by["b-bb22"]["line"]), ("src/util.ts", 12))
        self.assertTrue(by["t-3"]["resolved"] and by["t-1"]["you_replied"] and by["t-1"]["bot"])
        self.assertEqual(PR._title(by["b-aa11"]["body"]), "Fix the count.")

    def test_triage_decide_and_post_replies_once(self):
        PR, rid, root = self.PR, self.rid, self.root
        ths = [{"id": "t-1", "kind": "inline", "reply_to": 11, "author": "bot", "path": "a.py", "line": 4,
                "body": "Null check?", "resolved": False, "replies": []},
               {"id": "c-9", "kind": "comment", "author": "lee", "body": "Can we ship today?\nthanks",
                "resolved": False, "replies": []}]
        with mock.patch.object(PR, "threads", lambda *a: ths):
            self.assertTrue(PR.triage(rid, root, 1)["started"])
        self.assertEqual(self.runs, [("triage", False)])
        PR.apply(rid, 1, {"threads": [{"id": "t-1", "worth": 85, "why": "real", "reply_fix": "Added the check.",
                                       "reply_wont": "Handled upstream.", "wont_reasons": ["Out of scope."]},
                                      {"id": "nope", "worth": 5}]})
        PR.decide(rid, 1, {"t-1": {"decision": "fix", "reply": "Added the check."},
                           "c-9": {"decision": "wont", "reply": "Not today, after QA."}})
        out = PR.replies_out(rid, 1)["replies"]
        self.assertEqual([(r["id"], r["body"]) for r in out],
                         [("t-1", "Added the check."), ("c-9", "> @lee: Can we ship today?\n\nNot today, after QA.")])
        sent = []
        ok = subprocess.CompletedProcess([], 0, "{}", "")
        with mock.patch.object(PR, "_gh", lambda root, *a, **k: sent.append(a[3]) or ok):
            self.assertEqual(PR.post_replies(rid, root, 1), {"posted": 2})
            with self.assertRaises(PR.Invalid):
                PR.post_replies(rid, root, 1)  # nothing left: never twice
        self.assertEqual(sent, ["repos/o/app/pulls/1/comments/11/replies", "repos/o/app/issues/1/comments"])
        tri = PR._read(rid, 1, "triage.json", {})
        self.assertEqual(tri["threads"]["t-1"]["worth"], 85)
        with mock.patch.object(PR, "threads", lambda *a: ths):  # a refresh keeps the analysis and what was sent
            PR.triage(rid, root, 1)
        self.assertTrue(PR._read(rid, 1, "triage.json", {})["threads"]["t-1"]["posted"])

    def test_review_worktrees_survive_the_idle_clean_up(self):
        from lfgcore import worktree as W2
        self.PR.start(self.rid, self.root, 1)
        with mock.patch.object(W2, "_last_used", lambda p: 0):
            self.assertEqual(W2.prune(self.root, idle_s=0), [])


class SonarTest(unittest.TestCase):
    def setUp(self):
        from lfgcore import sonar as SQ
        self.SQ = SQ

    def test_repo_settings_pass_through_but_nothing_else(self):
        d = tempfile.mkdtemp()
        C.write_text(os.path.join(d, ".sonarcloud.properties"),
                     "# comment\nsonar.sources=src\nsonar.exclusions=**/gen/**\nsonar.host.url=http://evil\n"
                     "sonar.login=abc\n")
        self.assertEqual(self.SQ._props(d), {"sonar.sources": "src", "sonar.exclusions": "**/gen/**"})

    def test_setup_replaces_the_stock_login_and_keeps_it_private(self):
        SQ, calls = self.SQ, []

        def api(path, method="GET", data=None, auth=None, timeout=30):
            calls.append((path, auth if isinstance(auth, tuple) else "token"))
            return {"token": "squ_t"} if "user_tokens" in path else {}
        try:
            os.remove(SQ.creds_path())
        except OSError:
            pass
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(SQ, "_docker", lambda *a, **k: ok), mock.patch.object(SQ, "_api", api), \
                mock.patch.object(SQ, "server_state", lambda: "up"), mock.patch.object(C, "which", lambda n: "/x"):
            SQ.setup(log=lambda m: None)
        c = SQ.creds()
        self.assertEqual(calls[0], ("/api/users/change_password", ("admin", "admin")))
        self.assertEqual(calls[1], ("/api/user_tokens/generate", ("admin", c["password"])))
        self.assertTrue(len(c["password"]) >= 12 and c["password"] != "admin" and c["token"] == "squ_t")
        self.assertEqual(os.stat(SQ.creds_path()).st_mode & 0o777, 0o600)

    def test_issues_on_changed_lines_come_first_and_decide_the_exit(self):
        from lfgcore import cli
        SQ = self.SQ
        answers = {"/api/qualitygates": {"projectStatus": {"status": "ERROR", "conditions": [
                       {"metricKey": "new_bugs", "status": "ERROR", "actualValue": "1", "errorThreshold": "0",
                        "comparator": "GT"}]}},
                   "/api/issues": {"issues": [
                       {"key": "a", "type": "CODE_SMELL", "severity": "MINOR", "component": "k:src/x.ts", "line": 9},
                       {"key": "b", "type": "BUG", "severity": "MAJOR", "component": "k:src/x.ts", "line": 3}],
                       "paging": {"total": 2}},
                   "/api/hotspots": {"hotspots": [], "paging": {"total": 0}},
                   "/api/measures": {"component": {"measures": [{"metric": "bugs", "value": "1"}]}}}

        def api(path, *a, **k):
            return next(v for p, v in answers.items() if path.startswith(p))
        with mock.patch.object(SQ, "_api", api), mock.patch.object(SQ, "_base", lambda root, base: "abc"), \
                mock.patch.object(SQ, "_changed_lines", lambda root, base: {"src/x.ts": {3, 4}}):
            res = SQ._collect("sq-55555555", "/r", "k", None, "t", 1)
        self.assertEqual([(i["key"], i["mine"]) for i in res["issues"]], [("b", True), ("a", False)])
        self.assertEqual((res["gate"], res["mine"]), ("ERROR", 1))
        self.assertEqual([i["key"] for i in cli._sonar_blocking(res)], ["b"])
        self.assertEqual(SQ.last("sq-55555555")["mine"], 1)

    def test_scan_copy_has_what_sonarcloud_sees_and_never_secrets(self):
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", d], check=True)
        for rel, text in (("src/a.ts", "x"), (".gitignore", "*.log\n.env\nout/\n"), (".env", "KEY=1"),
                          ("out/big.js", "y"), ("debug.log", "z"), ("src/new.ts", "n"), ("config/.env.prod", "S=1")):
            C.write_text(os.path.join(d, rel), text)
        subprocess.run(["git", "-C", d, "add", "src/a.ts", ".gitignore"], check=True)
        subprocess.run(["git", "-C", d, "add", "-f", "config/.env.prod"], check=True)  # even a tracked one stays out
        snap, copied, skipped = self.SQ.stage("sq-66666666", d)
        got = sorted(os.path.relpath(os.path.join(r, f), snap) for r, _, fs in os.walk(snap) for f in fs)
        self.assertEqual(got, [".gitignore", "src/a.ts", "src/new.ts"])
        self.assertEqual((copied, skipped), (3, 1))

    def test_remove_only_touches_lfg_labelled_containers(self):
        SQ, ran = self.SQ, []

        def docker(*a, **k):
            ran.append(a)
            return subprocess.CompletedProcess(a, 0, "someone-else\n", "")
        with mock.patch.object(SQ, "_docker", docker):
            SQ.remove(volumes=True)
        self.assertFalse([a for a in ran if a[0] in ("rm", "volume") and "inspect" not in a])


class LfgTagTest(unittest.TestCase):
    def test_reply_tags_are_read_from_the_first_lines(self):
        from lfgcore import hooks as H
        self.assertEqual(H.reply_tag("**LFG:** /lfg:fix\n\nFixed it."), ("skill", "/lfg:fix"))
        self.assertEqual(H.reply_tag("**LFG:** tools only (code graph)"), ("tools", "code graph"))
        self.assertEqual(H.reply_tag("**LFG:** not used - a question about Docker"),
                         ("not-used", "a question about Docker"))
        self.assertEqual(H.reply_tag("Done.\n\nLFG wasn't needed"), ("missing", ""))

    def test_last_reply_is_the_first_text_after_the_latest_prompt(self):
        from lfgcore import hooks as H
        d = tempfile.mkdtemp()
        path = os.path.join(d, "t.jsonl")
        evs = [{"type": "user", "uuid": "p1", "message": {"content": "first"}},
               {"type": "assistant", "message": {"content": [{"type": "text", "text": "**LFG:** /lfg:fix"}]}},
               {"type": "user", "uuid": "p2", "message": {"content": [{"type": "text", "text": "second"}]}},
               {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t"}]}},
               {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t"}]}},
               {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "sub"}]}},
               {"type": "assistant", "message": {"content": [{"type": "text", "text": "**LFG:** not used - x"}]}},
               {"type": "assistant", "message": {"content": [{"type": "text", "text": "later text"}]}}]
        C.write_text(path, "\n".join(json.dumps(e) for e in evs) + "\n")
        self.assertEqual(H._last_reply(path), ("p2", "**LFG:** not used - x"))

    def test_prompt_reminder_follows_the_setting(self):
        from lfgcore import hooks as H
        from lfgcore import headroom as HR2
        import io
        with mock.patch.object(HR2, "routed", lambda *a: False):
            for on, want in ((True, H.TAG_REMINDER), (False, None)):
                with mock.patch.object(H, "_tag_on", return_value=on), \
                        mock.patch("sys.stdout", new=io.StringIO()) as o:
                    H.prompt({"cwd": tempfile.mkdtemp()})
                got = json.loads(o.getvalue())["hookSpecificOutput"]["additionalContext"] if o.getvalue() else None
                self.assertEqual(got, want)




class IntegrationsTest(unittest.TestCase):
    def test_each_pack_is_a_card_with_its_own_settings(self):
        from lfgcore import control as K
        from lfgcore import hooks as H
        from lfgcore import setup as SU2
        packs = [dict(name=n, title=n, about="", on=n in ("core", "sonarqube"), missing=[], requires=[],
                      experimental=False) for n in ("core", "sonarqube", "dictate", "linear")]
        boom = mock.Mock(side_effect=RuntimeError("down"))
        with mock.patch.object(SU2, "packs_view", lambda: packs), mock.patch.object(H, "_gh_signed_in", lambda: True), \
                mock.patch.dict(K.STATUS, {"core": lambda su: ("ok", "fine"), "sonarqube": boom}):
            v = K.integrations_view()["integrations"]
        by = {i["name"]: i for i in v}
        self.assertEqual(list(by), ["core", "sonarqube", "dictate", "linear", "github"])
        self.assertEqual((by["core"]["tone"], by["core"]["status"]), ("ok", "fine"))
        self.assertEqual(by["sonarqube"]["status"], "")  # a broken status check doesn't take the page down
        self.assertEqual([f["key"] for f in by["sonarqube"]["fields"]], ["sonarqube.telemetry"])
        self.assertEqual([f["key"] for f in by["linear"]["fields"]], ["linear.team", "linear.workspace"])
        self.assertEqual(by["dictate"]["status"], "")  # off: no status check runs
        general = [f for f in ST.config_view()["fields"] if not f["owner"]]
        self.assertFalse([f for f in general if f["key"].startswith(("sonarqube.", "dictate.", "headroom."))])

    def test_sonarqube_is_fully_local_by_default(self):
        from lfgcore import sonar as SQ
        self.assertEqual(SQ.privacy_env(), {"SONAR_TELEMETRY_ENABLE": "false", "SONAR_UPDATECENTER_ACTIVATE": "false"})
        stock = subprocess.CompletedProcess([], 0, json.dumps(["SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true"]), "")
        local = subprocess.CompletedProcess([], 0, json.dumps(["SONAR_TELEMETRY_ENABLE=false",
                                                               "SONAR_UPDATECENTER_ACTIVATE=false"]), "")
        with mock.patch.object(SQ, "_docker", lambda *a, **k: stock):
            self.assertFalse(SQ.privacy_applied())  # stock container phones home: needs the restart
        with mock.patch.object(SQ, "_docker", lambda *a, **k: local):
            self.assertTrue(SQ.privacy_applied())


class HeadroomUpstreamTest(unittest.TestCase):
    def test_the_desktop_apps_gateway_is_never_taken_as_the_upstream(self):
        with mock.patch.object(HR, "_settings_path", lambda: os.path.join(tempfile.mkdtemp(), "none.json")), \
                mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://gw.example", "CLAUDE_CODE_ENTRYPOINT":
                                             "claude-desktop"}):
            self.assertTrue(HR.in_desktop_app())
            self.assertEqual(HR.base_url(use_env=not HR.in_desktop_app()), "")
            self.assertEqual(HR.base_url(), "https://gw.example")  # still what this process itself uses


class ReviewRetryTest(unittest.TestCase):
    def test_a_failed_first_pass_gets_a_fresh_session_and_a_clear_hint(self):
        from lfgcore import prreview as PR
        rid = "retry-77777777"
        C.write_json(os.path.join(PR.folder(rid, 5), "meta.json"), {"number": 5, "session": "old", "ai_started": True})
        out = os.path.join(PR.folder(rid, 5), "job-1.out")
        C.write_text(out, json.dumps({"is_error": True, "result": "API Error: 401 Invalid proxy server token passed"}))
        C.write_json(os.path.join(PR.folder(rid, 5), "job.json"), {"pid": 999999999, "kind": "review", "out": out})
        PR.settle(rid, 5)
        meta = PR._read(rid, 5, "meta.json", {})
        self.assertNotEqual(meta["session"], "old")
        self.assertFalse(meta["ai_started"])
        last = PR.chat(rid, 5)[-1]
        self.assertTrue(last["error"])
        self.assertIn("refused Claude Code's sign-in", last["text"])


class KnowledgeDetailTest(unittest.TestCase):
    def test_knowledge_and_notes_carry_their_full_text(self):
        asked = {}
        with mock.patch.object(dash, "og_access", lambda n: None), \
                mock.patch.object(dash, "_inv", lambda *a, **k: []), \
                mock.patch.object(dash, "_list", lambda g, node, fields, *a, **k: asked.update({node: fields}) or []):
            dash.knowledge()
            dash.brain()
        self.assertTrue({"context", "decision", "consequences"} <= set(asked["Decision"]))
        self.assertTrue({"rationale", "correctAlternative"} <= set(asked["Principle"]))
        self.assertIn("body", asked["Learning"])
        self.assertIn("content", asked["Note"])  # the stored query for recent notes leaves the text out


class InBackgroundTest(unittest.TestCase):
    def test_slow_tool_never_blocks_and_runs_once(self):
        import threading
        gate, calls = threading.Event(), []

        def slow():
            calls.append(1)
            gate.wait(5)
            return {"available": True, "v": 1}
        key = "test-bg-%d" % os.getpid()
        first = dash.in_background(key, 60, slow, "busy")
        second = dash.in_background(key, 60, slow, "busy")
        self.assertEqual((first["pending"], second["pending"]), (True, True))
        gate.set()
        for _ in range(50):
            with dash._CLOCK:
                if key in dash._CACHE:
                    break
            threading.Event().wait(0.05)
        self.assertEqual(dash.in_background(key, 60, slow, "busy"), {"available": True, "v": 1})
        self.assertEqual(len(calls), 1)


class RunSummaryTest(unittest.TestCase):
    def test_about_from_brief_then_review_summary(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "01-brief.md"), "w") as fh:
            fh.write("# Brief: logs that explain\n\n## Problem\nLogs say nothing.\nNobody can debug.\n\n"
                     "- cause one\n\n## Users\nOn-call.\n")
        self.assertEqual(dash._about(d), ("logs that explain", "Logs say nothing. Nobody can debug."))
        e = tempfile.mkdtemp()
        self.assertEqual(dash._about(e, {"summary": {"standards": "Two helpers repeat.", "spec": "Undo leaves a key"}}),
                         ("", "Two helpers repeat. Undo leaves a key."))
        self.assertEqual(dash._about(e, {"summary": "Looks fine."}), ("", "Looks fine."))

    def test_shipcheck_counts_the_checklist_and_what_needs_a_person(self):
        s = {"pass": True, "part_a": {"applicable": True, "checks": [
                {"check": "build", "ok": True}, {"check": "image size", "ok": False, "severity": "warn"},
                {"check": "smoke", "ok": None}]},
             "checklist": [{"n": 1, "requirement": "Gates green", "status": "pass"},
                           {"n": 2, "requirement": "Migrations reversible", "status": "n/a"},
                           {"n": 3, "requirement": "Rollback plan", "status": "manual"},
                           {"n": 4, "requirement": "Docs", "status": "fail", "detail": "README not updated"}]}
        items = dash.shipcheck_items(s)
        self.assertEqual([i["ok"] for i in items], [True, None, None, True, None, None, False])
        self.assertEqual([i["check"] for i in items if i.get("manual")], ["Rollback plan"])
        rid = "ship-rid"
        C.new_run(rid, "x")
        C.write_json(C.run_file(rid, "07-shipcheck.json"), s)
        sc = dash.security(rid)["shipcheck"][0]
        self.assertEqual((sc["ok"], sc["total"], sc["failed"], sc["manual"]), (2, 3, ["Docs"], ["Rollback plan"]))

    def test_review_feedback_only_marks_the_run_it_was_given_on(self):
        rid = "fb-rid"
        a = C.new_run(rid, "first")
        C.write_json(os.path.join(a, "06-review.json"), {"verdict": "approve", "findings": [{"id": "R-1"}]})
        b = os.path.join(C.runs_dir(rid), "20991231-0000-second")
        os.makedirs(b)
        C.write_json(os.path.join(b, "06-review.json"), {"verdict": "changes", "findings": [{"id": "R-1"}]})
        C.write_json(C.lfg_path("feedback", rid + ".json"), {"R-1": {"verdict": "accept", "run": os.path.basename(a)}})
        got = {f["run"]: f["feedback"] for f in dash.reviews(rid)["findings"]}
        self.assertEqual(got, {os.path.basename(a): "accept", "20991231-0000-second": None})

    def test_dev_graph_that_refuses_the_token_says_so(self):
        dash._CACHE.pop("og-access:dev-graph", None)
        with mock.patch.object(dash, "_og_ready", return_value=True), \
                mock.patch.object(dash, "_og", return_value={"error": "HTTP Error 401: Unauthorized"}):
            why = dash.og_access("dev-graph")
            self.assertIn("refused LFG's access token", why)
            self.assertEqual(dash.issues(), {"available": False, "why": why})
        dash._CACHE.pop("og-access:dev-graph", None)

    def test_vendored_docs_are_not_your_docs(self):
        self.assertTrue(dash.THIRD_PARTY.search("plugin/vendor/x/README.md"))
        self.assertFalse(dash.THIRD_PARTY.search("docs/runbooks/vendors.md"))

    def test_security_verdict_string_or_object(self):
        self.assertEqual(dash._verdict("safe"), "safe")
        self.assertEqual(dash._verdict({"overall": "don't", "blocking": ["S-1"]}), "don't")
        self.assertEqual(dash._blocking({"blocking": 3}), 3)
        self.assertEqual(dash._blocking({"verdict": {"overall": "don't", "blocking": ["a", "b"]}}), 2)
        self.assertEqual(dash._blocking({"findings": [{"blocking": True}, {"blocking": False}]}), 1)
