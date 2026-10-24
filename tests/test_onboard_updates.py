"""Unit tests for onboarding, updates, and related CLI commands.
Tests run with LFG_HOME pointed at a temp dir. Stdlib only."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugin", "lib"))

from lfgcore import common as C  # noqa: E402
from lfgcore import onboard as OB  # noqa: E402
from lfgcore import settings as S  # noqa: E402
from lfgcore import updates as UP  # noqa: E402


def _remove_state_files():
    """Remove state files for fresh test."""
    for name in ["state/onboarding.json", "state/updates.json", "state/ledger.json", "enabled.json"]:
        path = C.lfg_path(name)
        if os.path.exists(path):
            os.remove(path)


class OnboardStateTest(unittest.TestCase):
    """Test onboard module state and page visibility."""

    def setUp(self):
        _remove_state_files()

    def test_fresh_not_complete(self):
        """Fresh install: not complete, every page shown."""
        st = OB.state()
        self.assertFalse(st["complete"])
        pages = OB.pages(st)
        # Should include all NAV_ORDER pages
        self.assertEqual(pages, list(OB.NAV_ORDER))

    def test_existing_install_complete(self):
        """Existing install (ledger.json, no onboarding): complete with all features."""
        C.ensure_dir(C.lfg_path("state"))
        C.write_json(C.lfg_path("state", "ledger.json"), {"entries": []})
        st = OB.state()
        self.assertTrue(st["complete"])
        self.assertEqual(set(st["features"]), set(OB.FEATURES))
        pages = OB.pages(st)
        self.assertEqual(pages, list(OB.NAV_ORDER))
        os.remove(C.lfg_path("state", "ledger.json"))

    def test_choose_features(self):
        """Choose specific features, pages in nav order."""
        st = OB.choose(["reviews"])
        self.assertTrue(st["complete"])
        # st["features"] is a list of feature names when returned by choose() directly
        # but ob.view() returns full feature dicts
        names = [f["id"] if isinstance(f, dict) else f for f in st.get("features", [])]
        # Due to DEFAULT fallback, coding should be included too
        self.assertIn("reviews", names)

    def test_choose_everything(self):
        """Choose all features."""
        st = OB.choose(everything=True)
        self.assertTrue(st["complete"])
        # st is view() which returns full feature dicts
        names = [f["id"] if isinstance(f, dict) else f for f in st.get("features", [])]
        self.assertEqual(set(names), set(OB.FEATURES))

    def test_choose_invalid_feature(self):
        """Invalid feature raises Invalid."""
        with self.assertRaises(S.Invalid):
            OB.choose(["nope"])

    def test_toggle_unknown(self):
        """Toggle unknown feature raises Invalid."""
        _ = OB.choose([])  # Set up state
        with self.assertRaises(S.Invalid):
            OB.toggle("nope", True)

    def test_toggle_enables(self):
        """Toggle enables a feature."""
        OB.choose([])
        st = OB.toggle("reviews", True)
        names = [f["id"] if isinstance(f, dict) else f for f in st.get("features", [])]
        self.assertIn("reviews", names)

    def test_toggle_disables(self):
        """Toggle disables a feature."""
        # Start fresh and enable reviews + coding
        OB.choose(["coding", "reviews"])
        # Then toggle reviews off
        OB.toggle("reviews", False)
        # Check the state directly (not view)
        st = OB.state()
        self.assertNotIn("reviews", st["features"])
        self.assertIn("coding", st["features"])

    def test_set_show_all(self):
        """Set show_all returns every page."""
        OB.choose([])
        st = OB.set_show_all(True)
        self.assertTrue(st["show_all"])
        pages = OB.pages(st)
        self.assertEqual(pages, list(OB.NAV_ORDER))

    def test_view_structure(self):
        """view() returns the expected structure."""
        OB.choose(["reviews"])
        v = OB.view()
        self.assertIn("complete", v)
        self.assertIn("show_all", v)
        self.assertIn("pages", v)
        self.assertIn("features", v)
        for f in v["features"]:
            self.assertIn("id", f)
            self.assertIn("name", f)
            self.assertIn("description", f)
            self.assertIn("enabled", f)
            self.assertIn("pages", f)
            self.assertIn("page_titles", f)
            self.assertIn("skills", f)


class OnboardStateNoConfigTest(unittest.TestCase):
    """Verify config.json is NOT created/changed by choose/toggle/set_show_all."""

    def setUp(self):
        _remove_state_files()
        self.config_path = C.lfg_path("config.json")
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

    def test_choose_does_not_create_config(self):
        """choose() does not create or modify config.json."""
        OB.choose(["coding"])
        self.assertFalse(os.path.exists(self.config_path))

    def test_toggle_does_not_create_config(self):
        """toggle() does not create or modify config.json."""
        OB.choose([])
        OB.toggle("reviews", True)
        self.assertFalse(os.path.exists(self.config_path))

    def test_set_show_all_does_not_create_config(self):
        """set_show_all() does not create or modify config.json."""
        OB.choose([])
        OB.set_show_all(True)
        self.assertFalse(os.path.exists(self.config_path))


class UpdatesCacheTest(unittest.TestCase):
    """Test update checking and caching."""

    def setUp(self):
        _remove_state_files()

    def test_status_returns_cached(self):
        """status() returns cached state without network."""
        # Write cached state
        C.ensure_dir(C.lfg_path("state"))
        C.write_json(C.lfg_path("state", "updates.json"), {
            "upstream": C.VERSION,  # Same as current, so not available
            "checked_at": "2026-01-01T00:00:00",
        })
        st = UP.status()
        self.assertEqual(st["upstream"], C.VERSION)
        self.assertEqual(st["current"], C.VERSION)
        self.assertFalse(st["update_available"])

    def test_check_newer_version(self):
        """check() with newer upstream returns update_available."""
        # Mock fetch to return newer version
        def fake_fetch(url, timeout=5):
            if "plugin.json" in url:
                return json.dumps({"version": "99.0.0"})
            if "CHANGELOG" in url:
                return "## 99.0.0\n- New feature\n## %s\n- Old" % C.VERSION
            return ""

        with mock.patch.object(UP, "_fetch", side_effect=fake_fetch):
            st = UP.check()
            self.assertEqual(st["upstream"], "99.0.0")
            self.assertTrue(st["update_available"])
            self.assertIn("New feature", st["notes"])

    def test_check_same_version(self):
        """check() with same version returns not available."""
        def fake_fetch(url, timeout=5):
            if "plugin.json" in url:
                return json.dumps({"version": C.VERSION})
            return ""

        with mock.patch.object(UP, "_fetch", side_effect=fake_fetch):
            st = UP.check()
            self.assertEqual(st["upstream"], C.VERSION)
            self.assertFalse(st["update_available"])
            self.assertEqual(st["notes"], "")

    def test_check_error_keeps_previous(self):
        """Network error keeps previous upstream and sets error."""
        C.ensure_dir(C.lfg_path("state"))
        C.write_json(C.lfg_path("state", "updates.json"), {
            "upstream": "v0.5.0",
            "checked_at": "2026-01-01T00:00:00",
        })

        def fake_fetch(url, timeout=5):
            raise OSError("Network error")

        with mock.patch.object(UP, "_fetch", side_effect=fake_fetch):
            st = UP.check()
            # Previous upstream kept, error set
            self.assertEqual(st["upstream"], "v0.5.0")
            self.assertIn("Network error", st["error"])

    def test_notes_only_newer_sections(self):
        """Notes only include sections for versions newer than current."""
        current = "0.3.0"
        changelog = "## 0.5.0\n- Feature B\n## 0.4.0\n- Feature A\n## 0.3.0\n- Old\n## 0.2.0\n- Ancient"
        notes = UP.notes_since(changelog, current)
        self.assertIn("0.5.0", notes)
        self.assertIn("0.4.0", notes)
        self.assertIn("Feature A", notes)
        self.assertIn("Feature B", notes)
        self.assertNotIn("0.3.0", notes)
        self.assertNotIn("Old", notes)
        self.assertNotIn("Ancient", notes)

    def test_due_respects_auto_check_false(self):
        """due() returns False when auto_check is False."""
        C.write_json(C.lfg_path("config.json"), {"updates": {"auto_check": False}})
        self.assertFalse(UP.due())

    def test_due_true_after_check_interval(self):
        """due() returns True when interval passed."""
        import datetime
        # Write old timestamp
        old = (datetime.datetime.now(datetime.timezone.utc) -
               datetime.timedelta(hours=48)).isoformat()
        C.ensure_dir(C.lfg_path("state"))
        C.write_json(C.lfg_path("state", "updates.json"), {"tried_at": old})
        C.write_json(C.lfg_path("config.json"), {"updates": {"auto_check": True}})
        self.assertTrue(UP.due())

    def test_due_false_right_after_check(self):
        """due() returns False right after a check."""
        import datetime
        recent = datetime.datetime.now(datetime.timezone.utc).isoformat()
        C.ensure_dir(C.lfg_path("state"))
        C.write_json(C.lfg_path("state", "updates.json"), {"tried_at": recent})
        C.write_json(C.lfg_path("config.json"), {"updates": {"auto_check": True}})
        self.assertFalse(UP.due())

    def test_status_recomputes_availability(self):
        """status() checks against current VERSION."""
        # Cached upstream same as current
        C.ensure_dir(C.lfg_path("state"))
        C.write_json(C.lfg_path("state", "updates.json"), {
            "upstream": C.VERSION,
            "checked_at": "2026-01-01T00:00:00",
        })
        st = UP.status()
        self.assertFalse(st["update_available"])


class CLITest(unittest.TestCase):
    """Test CLI commands."""

    def setUp(self):
        _remove_state_files()

    def test_cmd_onboard_features_json(self):
        """lfg onboard --features coding,reviews --json."""
        from lfgcore import cli
        argv = ["onboard", "--features", "coding,reviews", "--json"]
        rc = cli.main(argv)
        self.assertEqual(rc, 0)

    def test_cmd_onboard_unknown_feature_exits_2(self):
        """lfg onboard --features nope should exit 2."""
        from lfgcore import cli
        argv = ["onboard", "--features", "nope"]
        with self.assertRaises(SystemExit) as cm:
            cli.main(argv)
        self.assertEqual(cm.exception.code, 2)

    def test_cmd_onboard_all_json(self):
        """lfg onboard --all --json."""
        from lfgcore import cli
        argv = ["onboard", "--all", "--json"]
        rc = cli.main(argv)
        self.assertEqual(rc, 0)

    def test_cmd_update_json_mocked(self):
        """lfg update --json with mocked network."""

        def fake_fetch(url, timeout=5):
            if "plugin.json" in url:
                return json.dumps({"version": "99.0.0"})
            return ""

        with mock.patch.object(UP, "_fetch", side_effect=fake_fetch):
            from lfgcore import cli
            argv = ["update", "--json"]
            rc = cli.main(argv)
            self.assertEqual(rc, 0)

    def test_cmd_explain5_with_temp_repo(self):
        """lfg explain5 with a temporary git repo."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="lfg-explain5-test-")
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "--allow-empty", "-m", "init", "-q"], cwd=tmpdir, check=True)
            test_file = os.path.join(tmpdir, "test_mod.py")
            with open(test_file, "w") as f:
                f.write('""\"Test module.""\"\ndef hello():\n    return "world"\n')
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "-m", "add mod", "-q"], cwd=tmpdir, check=True)

            from lfgcore import cli
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                argv = ["explain5", "test_mod.py", "--json"]
                rc = cli.main(argv)
                self.assertEqual(rc, 0)
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cmd_review_coach_with_temp_repo(self):
        """lfg review-coach with changes."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="lfg-review-coach-test-")
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "--allow-empty", "-m", "init", "-q"], cwd=tmpdir, check=True)
            # Add initial file
            with open(os.path.join(tmpdir, "app.py"), "w") as f:
                f.write("def foo():\n    pass\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "-m", "add app", "-q"], cwd=tmpdir, check=True)
            # Modify to create diff
            with open(os.path.join(tmpdir, "app.py"), "w") as f:
                f.write("def foo():\n    password = 'hardcoded'\n    return password\n")

            from lfgcore import cli
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                argv = ["review-coach", "--json"]
                rc = cli.main(argv)
                self.assertEqual(rc, 0)
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cmd_suggest_tests_with_temp_repo(self):
        """lfg suggest-tests with a temporary git repo."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="lfg-suggest-tests-")
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "--allow-empty", "-m", "init", "-q"], cwd=tmpdir, check=True)
            test_file = os.path.join(tmpdir, "calc.py")
            with open(test_file, "w") as f:
                f.write('def add(a, b):\n    return a + b\n')
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "-m", "add calc", "-q"], cwd=tmpdir, check=True)

            from lfgcore import cli
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                argv = ["suggest-tests", "calc.py", "--json"]
                rc = cli.main(argv)
                self.assertEqual(rc, 0)
            finally:
                os.chdir(old_cwd)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class EngineBehaviorTest(unittest.TestCase):
    """Test engine behavior with controlled repos."""

    def test_review_coach_multi_file_diff_real_paths_and_findings(self):
        """Several changed files (one named b*.py), committed + uncommitted changes, findings at file:line."""
        import shutil
        from lfgcore import review_coach_engine as RCE
        d = tempfile.mkdtemp(prefix="lfg-rc-")
        self.addCleanup(shutil.rmtree, d, True)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d,  # noqa: E731
                                         check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        for name in ("build.py", "other.py"):
            with open(os.path.join(d, name), "w") as f:
                f.write("x = 1\n")
        git("add", ".")
        git("commit", "-qm", "init")
        git("checkout", "-qb", "feature")
        with open(os.path.join(d, "build.py"), "w") as f:
            f.write("x = 1\npassword = \"hunter22\"\n")
        git("commit", "-qam", "committed on the branch")
        with open(os.path.join(d, "other.py"), "w") as f:
            f.write("x = 1\ntry:\n    y = 2\nexcept Exception:\n    pass\nfor r in [1]:\n    print(r)\n")
        res = RCE.review_changes("main", d)
        self.assertNotIn("error", res)
        self.assertEqual(sorted(f["path"] for f in res["files_reviewed"]), ["build.py", "other.py"])
        got = {(i["file"], i["line"], i["severity"]) for i in res["issues"]}
        self.assertIn(("build.py", 2, "critical"), got)  # committed on the branch
        self.assertIn(("other.py", 4, "medium"), got)  # uncommitted: swallowed except
        self.assertFalse([i for i in res["issues"] if "N+1" in i["message"]])  # plain loop
        self.assertEqual(res["risk_level"], "HIGH_RISK")

    def test_explain5_finds_related_tests(self):
        """explain5 finds related test files that import the module."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="lfg-engine-test-")
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "--allow-empty", "-m", "init", "-q"], cwd=tmpdir, check=True)
            # Create module
            os.makedirs(os.path.join(tmpdir, "mylib"))
            with open(os.path.join(tmpdir, "mylib", "__init__.py"), "w") as f:
                f.write("")
            with open(os.path.join(tmpdir, "mylib", "core.py"), "w") as f:
                f.write('def process(): pass\n')
            # Create test that imports it
            os.makedirs(os.path.join(tmpdir, "tests"))
            with open(os.path.join(tmpdir, "tests", "test_core.py"), "w") as f:
                f.write('from mylib import core\ndef test_process(): pass\n')
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "-m", "add files", "-q"], cwd=tmpdir, check=True)

            from lfgcore import explain5_engine as EE
            result = EE.explain_file("mylib/core.py", tmpdir)
            self.assertEqual(result["file"], "mylib/core.py")
            self.assertIn("tests/test_core.py", result["related_tests"])
            # Check top-level defs listed
            defs = [d["name"] for d in result["how_it_works"]]
            self.assertIn("process", defs)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_review_coach_issue_has_file_and_line(self):
        """review-coach issues have file and line."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="lfg-review-coach-")
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "--allow-empty", "-m", "init", "-q"], cwd=tmpdir, check=True)
            # Add initial file
            with open(os.path.join(tmpdir, "app.py"), "w") as f:
                f.write("def foo():\n    pass\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "-m", "add", "-q"], cwd=tmpdir, check=True)
            # Modify with hardcoded password
            with open(os.path.join(tmpdir, "app.py"), "w") as f:
                f.write("def foo():\n    password = 'hardcoded'\n    return password\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)

            from lfgcore import review_coach_engine as RCE
            result = RCE.review_changes("HEAD", tmpdir)
            self.assertTrue(len(result["issues"]) > 0)
            for issue in result["issues"]:
                self.assertIn("file", issue)
                self.assertIn("line", issue)
                self.assertIsInstance(issue["line"], int)
            # No score or good_practices key
            self.assertNotIn("overall_score", result)
            self.assertNotIn("good_practices", result)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_review_coach_no_n_plus_one_for_plain_loop(self):
        """review-coach does NOT flag plain loop without DB call."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="lfg-review-coach-")
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "--allow-empty", "-m", "init", "-q"], cwd=tmpdir, check=True)
            with open(os.path.join(tmpdir, "app.py"), "w") as f:
                f.write("def foo():\n    pass\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "-m", "add", "-q"], cwd=tmpdir, check=True)
            # Modify with just a loop, no DB call
            with open(os.path.join(tmpdir, "app.py"), "w") as f:
                f.write("def foo():\n    for x in range(10):\n        print(x)\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)

            from lfgcore import review_coach_engine as RCE
            result = RCE.review_changes("HEAD", tmpdir)
            # Should NOT flag N+1 for a plain loop
            nplus1_issues = [i for i in result["issues"] if "N+1" in i.get("message", "")]
            self.assertEqual(len(nplus1_issues), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_suggest_tests_no_coverage_key(self):
        """suggest-tests has no coverage_improvement_estimate key."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="lfg-suggest-tests-")
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "--allow-empty", "-m", "init", "-q"], cwd=tmpdir, check=True)
            with open(os.path.join(tmpdir, "calc.py"), "w") as f:
                f.write('def add(a, b):\n    return a + b\n')
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "-m", "add", "-q"], cwd=tmpdir, check=True)

            from lfgcore import test_suggester_engine as TSE
            result = TSE.suggest_tests("calc.py", tmpdir)
            self.assertIn("suggested_tests", result)
            self.assertIn("related_tests", result)
            # No coverage estimate key
            self.assertNotIn("coverage_improvement_estimate", result)
            # Each suggestion has a reason
            for s in result["suggested_tests"]:
                self.assertIn("reason", s)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class UIApiTest(unittest.TestCase):
    """Test UI api/save round-trip (simulating what the dashboard does)."""

    def setUp(self):
        _remove_state_files()

    def test_api_features(self):
        """api('features') returns expected structure."""
        from lfgcore import ui
        result = ui.api("features", {"repo": [""]})  # a fresh install has no project yet: Welcome must still work
        self.assertNotIn("available", result)
        with mock.patch.object(UP, "due", return_value=False):  # no background check: tests never touch the network
            self.assertNotIn("available", ui.api("updates", {"repo": [""]}))
        if True:
            self.assertIn("complete", result)
            self.assertIn("show_all", result)
            self.assertIn("pages", result)
            self.assertIn("features", result)
            for f in result["features"]:
                self.assertIn("id", f)
                self.assertIn("name", f)
                self.assertIn("description", f)
                self.assertIn("enabled", f)

    def test_feature_toggle_round_trip(self):
        """save('feature_toggle', ...) updates state."""
        from lfgcore import ui
        # First choose something
        ui.save("onboarding_save", {"features": ["coding"]})
        # Toggle reviews on
        result = ui.save("feature_toggle", {"feature": "reviews", "enabled": True})
        self.assertIn("review", result["pages"])
        # Toggle off
        result = ui.save("feature_toggle", {"feature": "reviews", "enabled": False})
        self.assertNotIn("review", result["pages"])

    def test_pages_show_all_round_trip(self):
        """save('pages_show_all', ...) updates state."""
        from lfgcore import ui
        ui.save("onboarding_save", {"features": ["coding"]})
        result = ui.save("pages_show_all", {"on": True})
        # All pages should be in result
        self.assertEqual(len(result["pages"]), len(OB.NAV_ORDER))


import shutil  # noqa: E402

if __name__ == "__main__":
    unittest.main()


class InsightsTest(unittest.TestCase):
    """Dashboard → Insights: only files git tracks in the project can be read; results come from the engines."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="lfg-ins-")
        self.addCleanup(shutil.rmtree, self.d, True)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],  # noqa: E731
                                         cwd=self.d, check=True, capture_output=True)
        os.makedirs(os.path.join(self.d, "pkg"))
        os.makedirs(os.path.join(self.d, "tests"))
        with open(os.path.join(self.d, "pkg", "billing.py"), "w") as f:
            f.write('"""Billing."""\n\n\ndef charge(amount):\n    """Charge a card."""\n    if not amount:\n'
                    '        return None\n    return amount\n')
        with open(os.path.join(self.d, "tests", "test_billing.py"), "w") as f:
            f.write("from pkg import billing\n")
        with open(os.path.join(self.d, "tests", "test_other.py"), "w") as f:
            f.write("import os\n")  # in tests/ but unrelated: must not be listed
        git("init", "-q", "-b", "main")
        git("add", ".")
        git("commit", "-qm", "fix: charge rounding")
        self.rid = "ins-test-0001"
        C.write_json(C.lfg_path("graphs", self.rid, "state.json"), {"repo_root": self.d})

    def test_only_tracked_files_and_real_results(self):
        from lfgcore import insights as IN
        self.assertIn("pkg/billing.py", IN.view("insight_files", self.rid, {})["files"])
        for bad in ("../../etc/passwd", "/etc/passwd", "pkg/missing.py", ""):
            self.assertIn("error", IN.view("insight_explain", self.rid, {"file": bad}))
        ex = IN.view("insight_explain", self.rid, {"file": "pkg/billing.py"})
        self.assertEqual(ex["related_tests"], ["tests/test_billing.py"])
        self.assertEqual(ex["why_its_here"]["recent_fixes"][0]["message"], "fix: charge rounding")
        self.assertIn("charge", [x["name"] for x in ex["how_it_works"]])
        ts = IN.view("insight_tests", self.rid, {"file": "pkg/billing.py"})
        self.assertTrue(ts["suggested_tests"])
        self.assertNotIn("coverage_improvement_estimate", ts)
        self.assertEqual(IN.view("insight_review", self.rid, {})["message"], "No changes to review.")
        self.assertIn("error", IN.view("insight_review", self.rid, {"base": "main; rm -rf /"}))
        # a new file nobody has added to git yet is reviewed too; planted secrets in tests count as low
        with open(os.path.join(self.d, "pkg", "new.py"), "w") as f:
            f.write("token = 1\npassword = \"hunter22\"\n")
        with open(os.path.join(self.d, "tests", "test_new.py"), "w") as f:
            f.write("password = \"hunter22\"\n")
        rv = IN.view("insight_review", self.rid, {})
        got = {(i["file"], i["line"], i["severity"]) for i in rv["issues"]}
        self.assertIn(("pkg/new.py", 2, "critical"), got)
        self.assertIn(("tests/test_new.py", 1, "low"), got)
        self.assertIn("pkg/new.py", IN.view("insight_files", self.rid, {})["files"])
        self.assertNotIn("error", IN.view("insight_tests", self.rid, {"file": "pkg/new.py"}))

    def test_insights_page_shown_with_coding_or_reviews(self):
        self.assertIn("insights", OB.pages({"complete": True, "features": ["coding"], "show_all": False}))
        self.assertNotIn("insights", OB.pages({"complete": True, "features": ["security"], "show_all": False}))

    def test_new_features_banner_is_remembered(self):
        from lfgcore import control as K
        self.assertFalse(K.tours_view()["news_welcome_closed"])
        K.tour_done("news-welcome", "closed")
        self.assertTrue(K.tours_view()["news_welcome_closed"])


class ReviewCoachRulesTest(unittest.TestCase):
    def test_comments_strings_and_plain_lookups_are_not_findings(self):
        from lfgcore import review_coach_engine as RCE
        f = {"path": "x.py", "changes": [{"line": i, "content": t} for i, t in enumerate([
            "# never call eval(user_input)",
            'MSG = "Use of eval() is risky"',
            "for j in range(3):",
            "    pos = lines[j].find(quote)",
            "items = rows.filter(lambda r: r)",
            "for r in rows:",
            "    db.execute(q, (r,))",
            "x = eval(expr)",
        ], 1)]}
        got = [(i["line"], i["message"]) for i in RCE._review_file(f, ".")["issues"]]
        self.assertEqual([g[0] for g in got], [6, 8], got)  # the real loop query and the real eval only


class HistRepoMixin:
    """A temp repo with history: pay.py changed six times (three fixes), calm.py twice. Fresh project id per test."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="lfg-hot-")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "git@github.com:acme/shop.git")
        os.makedirs(os.path.join(self.d, "app"))
        self.write("app/pay.py", "def pay(x):\n    return x\n")
        self.write("app/calm.py", "def calm():\n    return 1\n")
        self.commit("add pay and calm")
        for i, msg in enumerate(["fix: rounding in pay (#12)", "pay: support refunds ENG-7",
                                 "Fix crash on empty cart", "fix: currency bug", "tweak pay"]):
            self.write("app/pay.py", "def pay(x):\n    return x + %d\n" % i)
            self.commit(msg)
        self.write("app/calm.py", "def calm():\n    return 2\n")
        self.commit("calm: return 2")
        import uuid
        self.rid = "hot-test-" + uuid.uuid4().hex[:8]
        C.write_json(C.lfg_path("graphs", self.rid, "state.json"), {"repo_root": self.d})

    def git(self, *a):
        return subprocess.run(["git", "-c", "user.name=Ann", "-c", "user.email=a@a", *a], cwd=self.d, check=True,
                              capture_output=True, text=True).stdout

    def write(self, p, text):
        with open(os.path.join(self.d, p), "w") as f:
            f.write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)


class HotspotsHistoryQuestionsTest(HistRepoMixin, unittest.TestCase):
    """Hotspots (debt), why (archaeology), senior questions and recurring patterns, on a repo with real history."""

    def test_hotspots_rank_by_fixes_and_explain_why(self):
        from lfgcore import hotspots_engine as HE
        r = HE.hotspots(self.d)
        self.assertEqual(r["files"][0]["path"], "app/pay.py")
        top = r["files"][0]
        self.assertEqual((top["fixes"], top["changes"], top["level"]), (3, 6, "high"))  # 3 fixes, no tests
        self.assertIn("no test file covers it", top["reasons"])
        self.assertEqual(top["recent_fixes"][0]["subject"], "fix: currency bug")
        self.assertIn("app/calm.py", [f["path"] for f in r["files"]])  # changed twice: listed, not high
        self.assertEqual([f["level"] for f in r["files"] if f["path"] == "app/calm.py"], ["watch"])

    def test_why_lists_commits_with_links(self):
        from lfgcore import history_engine as HI
        r = HI.why(self.d, "app/pay.py", 2, 2)
        subjects = [c["subject"] for c in r["commits"]]
        self.assertEqual(subjects[0], "tweak pay")
        self.assertIn("fix: rounding in pay (#12)", subjects)
        c12 = next(c for c in r["commits"] if "#12" in c["subject"])
        self.assertEqual(c12["refs"][0]["url"], "https://github.com/acme/shop/pull/12")
        self.assertTrue(c12["url"].startswith("https://github.com/acme/shop/commit/"))
        self.assertEqual(r["fixes"], 3)
        self.assertEqual(len(HI.why(self.d, "app/pay.py", 999)["commits"]), len(r["commits"]))  # clamped

    def test_changes_ask_senior_questions_and_spot_patterns(self):
        from lfgcore import insights as IN
        self.write("app/pay.py", "def pay(x):\n    try:\n        return x\n    except Exception:\n        pass\n")
        for _ in range(3):
            r = IN.view("insight_review", self.rid, {})
        qs = " ".join(q["q"] for q in r["questions"])
        self.assertIn("app/pay.py needed 3 fixes recently", qs)
        self.assertIn("Nothing tests app/pay.py", qs)
        self.assertEqual(r["touches_hotspots"][0]["path"], "app/pay.py")
        self.assertEqual(r["patterns"][0]["times"], 3)
        self.assertTrue(r["patterns"][0]["kind"].startswith("Error swallowed"))
        hist = C.read_json(C.lfg_path("repos", self.rid, "insights", "reviews.json"), [])
        self.assertNotIn("return x", json.dumps(hist))  # kinds and counts only, never code
        self.assertEqual(IN.view("insight_why", self.rid, {"file": "../x"})["error"][:3], "../")

    def test_cli_why_and_hotspots(self):
        import io
        from contextlib import redirect_stdout
        from lfgcore import cli
        cwd = os.getcwd()
        os.chdir(self.d)
        self.addCleanup(os.chdir, cwd)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["why", "app/pay.py:2", "--json"]), 0)
        self.assertEqual(json.loads(buf.getvalue())["commits"][0]["subject"], "tweak pay")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli.main(["hotspots"]), 0)
        self.assertIn("app/pay.py", buf.getvalue())
        with self.assertRaises(SystemExit):
            cli.main(["why", "nope.py"])


class GapsTest(HistRepoMixin, unittest.TestCase):
    """Regression tests from past fixes, a runnable skeleton, fix trends, team decisions, and feature check-ins."""

    def test_regression_ideas_and_skeleton_that_runs(self):
        from lfgcore import test_suggester_engine as TSE
        os.makedirs(os.path.join(self.d, "tests"))
        self.write("tests/test_pay.py", "import unittest\nfrom app import pay as P  # noqa: E402\n")
        self.write("app/__init__.py", "")
        self.commit("tests for pay")
        r = TSE.suggest_tests("app/pay.py", self.d)
        reg = [t for t in r["suggested_tests"] if t["category"] == "regression"]
        self.assertEqual([t["test_name"] for t in reg][:1], ["test_regression_currency_bug"])
        self.assertIn("A test keeps it fixed", reg[0]["reason"])
        sk = r["skeleton"]
        self.assertIn("from app import pay as P\n", sk)  # reuses the repo's own import, without its comment
        self.assertIn("P.pay(...)", sk)
        self.write("tests/test_skel.py", sk)
        run = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_skel.py"],
                             cwd=self.d, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=self.d))
        self.assertEqual(run.returncode, 0, run.stderr)  # runs as-is
        self.assertIn("skipped=", run.stderr)  # and says it isn't written yet

    def test_fix_trend_rising(self):
        from lfgcore import hotspots_engine as HE
        top = HE.hotspots(self.d)["files"][0]
        self.assertEqual((top["trend"], top["fixes_recent"], top["fixes_earlier"]), ("rising", 3, 0))
        self.assertTrue(any(r.startswith("fixes rising") for r in top["reasons"]))

    def test_team_decision_becomes_a_question(self):
        from lfgcore import insights as IN
        C.write_text(C.lfg_path("repos", self.rid, "docs", "adr", "0001-money.md"),
                     "# Money is integer cents\n\nAll amounts in app/pay.py stay integer cents, never floats.\n")
        IN._cache.clear()
        self.write("app/pay.py", "def pay(x):\n    return x * 1.0\n")
        qs = IN.view("insight_review", self.rid, {})["questions"]
        self.assertTrue(qs[0]["q"].startswith("Your team decided “Money is integer cents”"), qs)

    def test_check_ins_from_skill_use_with_snooze(self):
        import sqlite3
        from lfgcore import onboard as OB
        _remove_state_files()
        OB.choose(["coding"])
        db = sqlite3.connect(C.lfg_path("usage.db"))
        db.execute("CREATE TABLE IF NOT EXISTS replies (prompt TEXT PRIMARY KEY, session TEXT, ts TEXT, repo TEXT, "
                   "kind TEXT, detail TEXT)")
        db.execute("DELETE FROM replies")
        db.executemany("INSERT INTO replies VALUES (?, 's', 't', 'r', 'skill', '/lfg:secure')",
                       [("p%d" % i,) for i in range(4)])
        db.commit()
        self.assertIsNone(OB.suggestion())  # too soon after Welcome
        st = C.read_json(C.lfg_path("state", "onboarding.json"))
        C.write_json(C.lfg_path("state", "onboarding.json"), dict(st, at="2026-01-01T00:00:00+00:00"))
        sug = OB.suggestion()
        self.assertEqual(sug["feature"], "security")
        self.assertIn("/lfg:secure 4 times", sug["why"])
        v = OB.answer_suggestion("security", False)
        self.assertNotIn("checks", v["pages"])
        self.assertIsNone(OB.suggestion())  # not now: snoozed
        v = OB.answer_suggestion("security", True)
        self.assertIn("checks", v["pages"])

    def test_fix_detector(self):
        from lfgcore.explain5_engine import FIX_RX
        yes = ["fix: rounding", "UI fixes", "Fixed the login redirect", "Handle null, fixes #88", "crash on save"]
        no = ["LFG 0.3.0: guard fixes", "v1.2.0 - fixes and polish", "Bump lodash", "Revert \"fix: x\"", "tweak pay"]
        self.assertEqual([bool(FIX_RX.search(t)) for t in yes + no], [True] * 5 + [False] * 5)


class GitHubStarTest(unittest.TestCase):
    """Starring happens only on an explicit yes or click, and setup asks only once."""

    def setUp(self):
        from lfgcore import ghstar as G
        self.G = G
        p = C.lfg_path("state", "github.json")
        if os.path.exists(p):
            os.remove(p)
        self.calls = []

        def run(cmd, **kw):
            self.calls.append(cmd)
            starred = any(c[:3] == ["gh", "api", "-X"] for c in self.calls[:-1])
            rc = 0 if cmd[:3] == ["gh", "auth", "status"] or cmd[:3] == ["gh", "api", "-X"] else (0 if starred else 1)
            return subprocess.CompletedProcess(cmd, rc, "", "")
        for target, value in (("run", run), ("which", lambda n: "/usr/bin/gh")):
            m = mock.patch.object(C, target, value)
            m.start()
            self.addCleanup(m.stop)

    def puts(self):
        return [c for c in self.calls if c[:3] == ["gh", "api", "-X"]]

    def test_no_means_no_and_it_never_asks_again(self):
        self.assertFalse(self.G.ask_once(inp=lambda q: "", out=lambda *a: None))  # Enter = no
        self.assertEqual(self.puts(), [])
        self.assertIsNone(self.G.ask_once(inp=lambda q: "y", out=lambda *a: None))  # asked already
        self.assertEqual(self.puts(), [])

    def test_yes_stars_once(self):
        self.assertTrue(self.G.ask_once(inp=lambda q: "y", out=lambda *a: None))
        self.assertEqual(self.puts(), [["gh", "api", "-X", "PUT", "/user/starred/varun-singhh/lfg", "--silent"]])
        self.assertTrue(self.G.view()["starred"])

    def test_not_signed_in_never_calls_github(self):
        with mock.patch.object(C, "which", lambda n: None):
            self.assertIsNone(self.G.ask_once(inp=lambda q: "y", out=lambda *a: None))
            self.assertFalse(self.G.star()["starred"])
        self.assertEqual(self.puts(), [])
