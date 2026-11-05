"""Tests for installing LFG without touching what isn't LFG's: the change ledger, setup / enable / disable /
uninstall against a fake `claude` CLI, migration from older installs, per-repo hooks, the plugin's MCP stub and
manifests, and the dashboard's skills inventory. Stdlib only; never touches your real ~/.claude or ~/.lfg."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))
# commits in the throwaway repos never sign: 1Password would wait on you and the test run would time out
os.environ.update(GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="commit.gpgsign", GIT_CONFIG_VALUE_0="false",
                  GIT_CONFIG_KEY_1="tag.gpgsign", GIT_CONFIG_VALUE_1="false")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugin", "lib"))

from lfgcore import claudecfg as CC  # noqa: E402
from lfgcore import common as C  # noqa: E402
from lfgcore import control as K  # noqa: E402
from lfgcore import hooks as H  # noqa: E402
from lfgcore import mcp as M  # noqa: E402
from lfgcore import prefs as P  # noqa: E402
from lfgcore import setup as SU  # noqa: E402

PLUGIN = os.path.join(ROOT, "plugin")

# A stand-in for the `claude` CLI that edits settings the way the real one does (checked against Claude Code 2.1.299:
# a local install of a defaultEnabled:false plugin writes `false`, enable writes `true`, uninstall leaves `{}`).
FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
home = os.environ["HOME"]
with open(os.path.join(home, "claude-calls.log"), "a") as f:
    f.write(json.dumps([os.getcwd()] + a) + "\n")
def rw(p, fn):
    d = json.load(open(p)) if os.path.exists(p) and os.path.getsize(p) else {}
    fn(d)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(d, open(p, "w"), indent=2)
us = os.path.join(home, ".claude", "settings.json")
local = os.path.join(os.getcwd(), ".claude", "settings.local.json")
km = os.path.join(home, ".claude", "plugins", "known_marketplaces.json")
if a[:1] == ["--version"]:
    print("9.9.9 (Claude Code)")
elif a[:3] == ["plugin", "marketplace", "add"]:
    rw(us, lambda d: d.setdefault("extraKnownMarketplaces", {}).update({"lfg": {"source": {"path": a[3]}}}))
    rw(km, lambda d: d.update({"lfg": {}}))
elif a[:3] == ["plugin", "marketplace", "remove"]:
    rw(us, lambda d: d.setdefault("extraKnownMarketplaces", {}).pop("lfg", None))
    rw(km, lambda d: d.pop("lfg", None))
elif a[:1] == ["plugin"] and a[1] in ("install", "enable", "uninstall"):
    p = local if a[a.index("--scope") + 1] == "local" else us
    if a[1] == "uninstall":
        rw(p, lambda d: d.setdefault("enabledPlugins", {}).pop(a[2], None))
    else:
        rw(p, lambda d: d.setdefault("enabledPlugins", {}).__setitem__(a[2], a[1] == "enable"))
elif a[:2] == ["mcp", "remove"]:
    rw(os.path.join(home, ".claude.json"), lambda d: d.get("mcpServers", {}).pop(a[-1], None))
'''


class Sandbox(unittest.TestCase):
    """A throwaway HOME with a fake `claude`, fake Core tools on PATH and its own LFG_HOME."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lfg-sbx-")
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        self.lfg_home = os.path.join(self.home, ".lfg")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.makedirs(self.bin)
        for name, body in [("claude", FAKE_CLAUDE)] + [(t, "#!/bin/sh\nexit 0\n") for t in
                                                       ("uv", "gh", "code-review-graph", "graphify", "git-lfs-x")]:
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        self.patches = [
            mock.patch.object(C, "HOME", self.home), mock.patch.object(C, "LFG_HOME", self.lfg_home),
            mock.patch.object(SU, "EXTRA_PATH", []),
            mock.patch.dict(os.environ, {"HOME": self.home, "PATH": self.bin + os.pathsep + "/usr/bin:/bin",
                                         "ANTHROPIC_BASE_URL": ""}),
            mock.patch("lfgcore.graphs.spawn_background"),
            # fixed when prefs is imported, so HOME above doesn't move it: without this, setup's rules refresh
            # rewrites the real ~/.claude/lfg-preferences.md from the throwaway LFG_HOME's empty preferences
            mock.patch.object(P, "PREFS_MD", os.path.join(self.home, ".claude", "lfg-preferences.md")),
        ]
        for p in self.patches:
            p.start()
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.repo = os.path.realpath(self.repo)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def settings(self, data=None):
        p = os.path.join(self.home, ".claude", "settings.json")
        if data is not None:
            with open(p, "w") as f:
                json.dump(data, f, indent=2)
        return C.read_json(p, {})

    def local(self):
        return C.read_json(os.path.join(self.repo, ".claude", "settings.local.json"))

    def quiet(self, fn, *a, **kw):
        with mock.patch("sys.stdout", io.StringIO()):
            return fn(*a, **kw)


class LedgerTest(Sandbox):
    def test_json_set_and_revert_keep_everything_else(self):
        p = os.path.join(self.home, ".claude", "settings.json")
        self.settings({"theme": "dark", "env": {"KEEP": "1"}})
        e = CC.json_set(p, ["env", "ANTHROPIC_BASE_URL"], "http://127.0.0.1:8787", "why", "test", tag="t")
        self.assertEqual(self.settings()["env"], {"KEEP": "1", "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"})
        self.assertIsNone(CC.json_set(p, ["env", "ANTHROPIC_BASE_URL"], "http://127.0.0.1:8787", "why", "test"))
        self.assertEqual(CC.undo(e["id"])["status"], "undone")
        self.assertEqual(self.settings(), {"theme": "dark", "env": {"KEEP": "1"}})

    def test_a_value_you_changed_since_is_kept(self):
        p = os.path.join(self.home, ".claude", "settings.json")
        e = CC.json_set(p, ["model"], "opus", "why", "test")
        self.settings({"model": "sonnet"})
        self.assertEqual(CC.undo(e["id"])["status"], "kept")
        self.assertEqual(self.settings(), {"model": "sonnet"})

    def test_list_undo_removes_only_what_lfg_added(self):
        p = os.path.join(self.home, ".claude", "settings.json")
        self.settings({"permissions": {"deny": ["Read(./mine)", "Bash(env)"]}})
        e = CC.json_list_add(p, ["permissions", "deny"], ["Bash(env)", "Bash(sudo:*)"], "why", "test")
        self.assertEqual(e["added"], ["Bash(sudo:*)"])
        CC.undo(e["id"])
        self.assertEqual(self.settings()["permissions"]["deny"], ["Read(./mine)", "Bash(env)"])

    def test_invalid_json_is_left_alone(self):
        p = os.path.join(self.home, ".claude", "settings.json")
        with open(p, "w") as f:
            f.write("{nope")
        with self.assertRaises(ValueError):
            CC.json_set(p, ["x"], 1, "why", "test")
        self.assertEqual(C.read_text(p), "{nope")

    def test_compare_and_swap_redoes_the_edit_when_the_file_changed(self):
        p = os.path.join(self.home, ".claude", "settings.json")
        self.settings({"a": 1})
        real = CC._write
        calls = []

        def racing(path, data, expect_raw):
            if not calls:  # Claude Code writes the file between our read and our write
                calls.append(1)
                self.settings({"a": 1, "b": 2})
                return real(path, data, expect_raw)
            return real(path, data, expect_raw)
        with mock.patch.object(CC, "_write", side_effect=racing):
            CC.json_set(p, ["c"], 3, "why", "test")
        self.assertEqual(self.settings(), {"a": 1, "b": 2, "c": 3})

    def test_lines_and_links(self):
        ex = os.path.join(self.repo, ".git", "info", "exclude")
        before = C.read_text(ex)
        e = CC.lines_add(ex, ["graphify-out/"], "why", "test")
        self.assertIn("graphify-out/", C.read_text(ex))
        CC.undo(e["id"])
        self.assertEqual(C.read_text(ex).strip(), before.strip())
        link = os.path.join(self.home, ".local", "bin", "lfg")
        e = CC.link(link, "/x/lfg", "why", "test")
        self.assertTrue(os.path.islink(link))
        CC.undo(e["id"])
        self.assertFalse(os.path.lexists(link))
        with open(link, "w") as f:
            f.write("mine")
        with self.assertRaises(ValueError):
            CC.link(link, "/x/lfg", "why", "test")


class SetupFlowTest(Sandbox):
    def test_install_enable_disable_uninstall_leaves_your_settings_as_they_were(self):
        mine = {"theme": "dark", "hooks": {"Stop": []}, "env": {"FOO": "1"},
                "permissions": {"allow": ["Bash(npm test)"]}}
        self.settings(mine)
        os.makedirs(os.path.join(self.home, ".claude", "skills", "ship"))
        steps = SU.plan(["core"])
        self.assertEqual([s["id"] for s in steps], ["files", "shim", "marketplace"])
        self.assertTrue(self.quiet(SU.apply, steps)["ok"])
        self.assertTrue(os.path.isfile(os.path.join(self.lfg_home, "plugin", "bin", "lfg")))
        self.assertEqual({k: v for k, v in self.settings().items() if k != "extraKnownMarketplaces"}, mine)
        self.assertIn("ship", SU.scan()["skill_collisions"])

        other = tempfile.mkdtemp(dir=self.tmp)
        self.assertFalse(C.is_enabled(self.repo))
        SU.enable(self.repo)
        self.assertEqual(self.local(), {"enabledPlugins": {"lfg@lfg": True}})
        self.assertIn(".code-review-graph/", C.read_text(os.path.join(self.repo, ".git", "info", "exclude")))
        self.assertTrue(C.is_enabled(os.path.join(self.repo)))
        self.assertFalse(C.is_enabled(other))
        SU.disable(self.repo)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude")))  # LFG created it, LFG removed it
        self.assertNotIn(".code-review-graph/", C.read_text(os.path.join(self.repo, ".git", "info", "exclude")))

        SU.enable(self.repo, hardened=True)
        self.assertIn("Bash(git push:*)", self.local()["permissions"]["deny"])
        r = SU.uninstall()
        self.assertFalse(r["kept"])
        self.assertEqual(self.settings(), mine)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude")))
        self.assertFalse(os.path.lexists(os.path.join(self.home, ".local", "bin", "lfg")))
        self.assertFalse(os.path.exists(self.lfg_home))

    def test_failed_step_rolls_back_this_runs_changes(self):
        steps = [{"id": "shim", "title": "shim"}, {"id": "pack:nope", "title": "boom"}]
        res = self.quiet(SU.apply, steps)
        self.assertFalse(res["ok"])
        self.assertFalse(os.path.lexists(os.path.join(self.home, ".local", "bin", "lfg")))

    def test_enable_shows_lfg_folder_to_git_again_but_only_lfgs_own_line(self):
        ex = os.path.join(self.repo, ".git", "info", "exclude")
        CC.lines_add(ex, ["graphify-out/", ".lfg/"], "Keep LFG's graph folders out of git status", "repo",
                     tag="exclude", repo=os.path.realpath(self.repo))  # what an older `lfg enable` left
        SU.enable(self.repo, build=False)
        lines = C.read_text(ex).splitlines()
        self.assertNotIn(".lfg/", lines)
        self.assertIn("graphify-out/", lines)
        SU.disable(self.repo)
        self.assertNotIn("graphify-out/", C.read_text(ex).splitlines())
        with open(ex, "a") as f:
            f.write(".lfg/\n")  # the user's own line
        SU.enable(self.repo, build=False)
        self.assertIn(".lfg/", C.read_text(ex).splitlines())

    def test_enable_keeps_an_existing_claude_folder_and_your_local_settings(self):
        os.makedirs(os.path.join(self.repo, ".claude"))
        p = os.path.join(self.repo, ".claude", "settings.local.json")
        with open(p, "w") as f:
            json.dump({"permissions": {"allow": ["Bash(make)"]}}, f)
        SU.enable(self.repo)
        SU.disable(self.repo)
        self.assertEqual(C.read_json(p), {"permissions": {"allow": ["Bash(make)"]}})

    def test_older_install_is_cleaned_up_exactly(self):
        self.settings({"theme": "dark", "enabledPlugins": {"lfg@lfg": True, "other@x": True},
                       "permissions": {"deny": SU.HARDENED_DENY + ["Read(./mine)"]},
                       "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}})
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            json.dump({"mcpServers": {"dev-graph": {"command": "/x/.lfg/bin/lfg", "args": ["omnigraph", "mcp",
                                                                                            "dev-graph"]},
                                      "mine": {"command": "foo"}}}, f)
        C.write_json(C.lfg_path("graphs", "repo-1", "state.json"), {"repo_root": self.repo})
        ids = {i["id"] for i in SU.legacy_items()}
        self.assertEqual(ids, {"plugin-everywhere", "deny-rules", "mcp-dev-graph", "headroom-everywhere", "repos"})
        real_run = C.run

        def no_launchctl(cmd, *a, **kw):  # never touch this machine's real login agents
            return subprocess.CompletedProcess(cmd, 0, "", "") if cmd[0] == "launchctl" else real_run(cmd, *a, **kw)
        with mock.patch.object(C, "run", side_effect=no_launchctl):
            self.assertTrue(self.quiet(SU.apply, SU.plan(["core"], legacy=True))["ok"])
        s = self.settings()
        self.assertEqual(s["permissions"]["deny"], ["Read(./mine)"])
        self.assertEqual(s["enabledPlugins"], {"other@x": True})
        self.assertNotIn("env", s)
        self.assertEqual(list(C.read_json(os.path.join(self.home, ".claude.json"))["mcpServers"]), ["mine"])
        self.assertTrue(C.is_enabled(self.repo))
        self.assertEqual(SU.legacy_items(), [])

    def test_plain_setup_leaves_an_older_install_alone(self):
        from lfgcore import headroom as HR
        self.settings({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}})
        self.assertIn("headroom-everywhere", {i["id"] for i in SU.legacy_items()})
        self.assertEqual([s for s in SU.plan(["core"]) if s["where"] == "migrate"], [])
        self.assertEqual(HR.scope(), "everywhere")  # routing set outside LFG's ledger still shows as on
        self.settings({})
        self.assertEqual(HR.scope(), "off")

    def test_hooks_do_nothing_where_lfg_is_off(self):
        data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": self.repo})
        with mock.patch("sys.stdin", io.StringIO(data)), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(H.main("pre-tool"), 0)
        C.write_json(C.lfg_path("enabled.json"), {"repos": {self.repo: {}}})
        with mock.patch("sys.stdin", io.StringIO(data)), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(H.main("pre-tool"), 2)

    def test_worktree_counts_as_its_main_checkout(self):
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "--allow-empty", "-m", "x"], check=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                                GIT_COMMITTER_EMAIL="t@t"))
        wt = os.path.join(self.tmp, "wt")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", wt], check=True)
        self.assertEqual(C.git_main_root_fast(os.path.join(wt)), self.repo)

    def test_skills_inventory_flags_name_clashes_and_toggles_your_skill(self):
        d = os.path.join(self.home, ".claude", "skills", "ship")
        os.makedirs(d)
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write("---\nname: ship\ndescription: my ship\n---\nbody\n")
        inv = K.skills_inventory()
        mine = next(i for i in inv["skills"] if i["id"] == "personal:ship")
        lfg = next(i for i in inv["skills"] if i["id"] == "lfg@lfg:ship")
        self.assertIn("/lfg:ship", mine["collides_with"])
        self.assertTrue(lfg["shadowed"] and not mine["shadowed"])
        K.skill_auto("personal:ship", False)
        self.assertIn("disable-model-invocation: true", C.read_text(os.path.join(d, "SKILL.md")))
        self.assertTrue(os.listdir(C.lfg_path("backups", "skills-personal")))
        K.skill_auto("personal:ship", True)
        self.assertEqual(C.read_text(os.path.join(d, "SKILL.md")), "---\nname: ship\ndescription: my ship\n---\nbody\n")
        with self.assertRaises(K.Invalid):
            K.skill_auto("lfg@lfg:nope", False)


class PluginShapeTest(unittest.TestCase):
    def test_manifest_is_off_by_default_and_is_the_version_source(self):
        m = C.read_json(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"))
        self.assertIs(m["defaultEnabled"], False)
        self.assertEqual(m["version"], C.VERSION)

    def test_hooks_use_the_plugin_root_and_narrow_matchers(self):
        h = C.read_json(os.path.join(PLUGIN, "hooks", "hooks.json"))["hooks"]
        for event, groups in h.items():
            for g in groups:
                self.assertNotEqual(g.get("matcher"), "*", event)
                for hk in g["hooks"]:
                    self.assertTrue(hk["command"].startswith('"${CLAUDE_PLUGIN_ROOT}/bin/lfg"'), hk["command"])

    def test_mcp_servers_start_through_lfg_and_agents_use_their_names(self):
        servers = C.read_json(os.path.join(PLUGIN, ".mcp.json"))["mcpServers"]
        self.assertEqual(set(servers), set(M.SERVERS))
        for name, s in servers.items():
            self.assertEqual(s["args"], ["mcp", name])
        for f in os.listdir(os.path.join(PLUGIN, "agents")):
            tools = [t.strip() for t in H.re.search(r"^tools:(.*)$", C.read_text(os.path.join(PLUGIN, "agents", f)),
                                                     H.re.M).group(1).split(",")]
            for t in tools:
                if t.startswith("mcp__"):
                    self.assertTrue(t.startswith(("mcp__plugin_lfg_", "mcp__linear")), (f, t))

    def test_context_carries_what_claude_md_used_to(self):
        text = " ".join(H.CONTEXT)
        for phrase in ("CLAUDE.md files take priority", "never creates a Linear issue", "lfg rule remember", "lfg:"):
            self.assertIn(phrase, text)
        self.assertNotIn("Varun", text)


class McpStubTest(unittest.TestCase):
    def test_stub_answers_with_no_tools_and_the_reason(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"jsonrpc": "2.0", "id": 3, "method": "ping"},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "x"}}]
        out = io.StringIO()
        M.stub("dev-graph", "add the Knowledge pack", io.StringIO("".join(json.dumps(m) + "\n" for m in msgs)), out)
        replies = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3, 4])
        self.assertEqual(replies[0]["result"]["instructions"], "add the Knowledge pack")
        self.assertEqual(replies[1]["result"], {"tools": []})
        self.assertIn("error", replies[3])


class UsageOffsetTest(unittest.TestCase):
    def test_stop_reads_only_new_lines_and_keeps_totals(self):
        with tempfile.TemporaryDirectory() as d:
            t = os.path.join(d, "t.jsonl")
            line = json.dumps({"message": {"model": "m", "usage": {"input_tokens": 10, "output_tokens": 1}}}) + "\n"
            with open(t, "w") as f:
                f.write(line * 2 + '{"half":')
            self.assertEqual(H._transcript_usage(t, "s-off")["m"][:2], [20, 2])
            with open(t, "a") as f:
                f.write(' 1}\n' + line)
            self.assertEqual(H._transcript_usage(t, "s-off")["m"][:2], [30, 3])


if __name__ == "__main__":
    unittest.main()
