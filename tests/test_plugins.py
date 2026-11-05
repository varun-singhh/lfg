"""Claude Code plugins from LFG (lfgcore.plugins): list, search, install, on/off and remove, with a stand-in
`claude`."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib"))

from lfgcore import claudecfg as CC  # noqa: E402
from lfgcore import guard  # noqa: E402
from lfgcore import plugins as PL  # noqa: E402

SP = "superpowers@claude-plugins-official"


class FakeClaude:
    """What `claude plugin` would say and do, kept in memory."""
    def __init__(self):
        self.installed = [{"id": "lfg@lfg", "scope": "user", "enabled": True},
                          {"id": "tool@team", "scope": "local", "enabled": True, "projectPath": "/r/app"}]
        self.available = [{"pluginId": SP, "name": "superpowers", "description": "Skills for planning and review",
                           "marketplaceName": "claude-plugins-official", "installCount": 900},
                          {"pluginId": "pr-review@market", "name": "pr-review", "description": "Review PRs",
                           "marketplaceName": "market", "installCount": 5},
                          {"pluginId": "lint@market", "name": "lint", "description": "Lint code"}]
        self.calls = []

    def run(self, argv, **kw):
        self.calls.append(argv[1:])
        out, rc = "", 0
        verb = argv[2]
        if verb == "list":
            out = json.dumps({"installed": self.installed, "available": self.available})
        elif verb == "install":
            self.installed.append({"id": argv[3], "scope": "user", "enabled": True, "version": "1.0.0"})
        elif verb in ("enable", "disable"):
            next(x for x in self.installed if x["id"] == argv[3])["enabled"] = verb == "enable"
        elif verb == "uninstall":
            self.installed = [x for x in self.installed if x["id"] != argv[3]]
        return mock.Mock(returncode=rc, stdout=out, stderr="")


class PluginsTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeClaude()
        for m in (mock.patch.object(PL.C, "run", side_effect=self.fake.run),
                  mock.patch.object(PL.C, "which", return_value="claude")):
            m.start()
            self.addCleanup(m.stop)
        PL._CACHE.update(ts=0, data=None)
        if os.path.exists(CC.ledger_path()):
            os.remove(CC.ledger_path())

    def test_lists_without_lfg_suggests_and_searches(self):
        v = PL.view()
        self.assertEqual([x["id"] for x in v["installed"]], ["tool@team"])  # LFG has its own switches
        self.assertFalse(v["installed"][0]["yours"])  # one repo only: shown, not switched here
        self.assertEqual([x["id"] for x in v["suggested"]], [SP])
        self.assertEqual(v["found"], [])
        self.assertEqual([x["id"] for x in PL.view("review")["found"]], [SP, "pr-review@market"])  # most installed
        self.assertEqual([x["id"] for x in PL.view("review prs")["found"]], ["pr-review@market"])  # every word

    def test_install_turn_off_on_and_remove_through_claude_with_an_undo_entry(self):
        PL.install(SP)
        self.assertIn(["plugin", "install", SP, "--scope", "user"], self.fake.calls)
        entry = CC.find(kind="cmd", tag="plugin-extra", target=SP)
        self.assertEqual(entry[0]["undo"][1:], ["plugin", "uninstall", SP, "--scope", "user"])
        self.assertEqual(PL.view()["suggested"], [])  # installed: no longer suggested
        PL.set_enabled(SP, False)
        self.assertFalse(next(x for x in PL.view()["installed"] if x["id"] == SP)["enabled"])
        n = len(self.fake.calls)
        PL.set_enabled(SP, False)  # already off: Claude isn't asked again
        self.assertEqual([c[1] for c in self.fake.calls[n:]], ["list"] if self.fake.calls[n:] else [])
        PL.set_enabled(SP, True)
        PL.uninstall(SP)
        self.assertNotIn(SP, [x["id"] for x in PL.view()["installed"]])
        self.assertEqual(CC.find(kind="cmd", tag="plugin-extra", target=SP), [])  # nothing left to undo

    def test_refuses_what_it_should(self):
        for pid, why in (("lfg@lfg", "Settings"), ("nope", "name@marketplace"), ("ghost@market", "marketplace"),
                         ("a b@c", "name@marketplace")):
            with self.assertRaisesRegex(ValueError, why):
                PL.install(pid)
        with self.assertRaisesRegex(ValueError, "one repo"):
            PL.set_enabled("tool@team", False)
        with self.assertRaisesRegex(ValueError, "one repo"):
            PL.uninstall("tool@team")
        with self.assertRaisesRegex(ValueError, "isn't installed"):
            PL.uninstall(SP)
        PL.install(SP)
        with self.assertRaisesRegex(ValueError, "already"):
            PL.install(SP)

    def test_claude_cannot_install_or_switch_plugins_itself(self):
        for cmd in ("claude plugin install %s" % SP, "claude plugins i x@y", "claude plugin disable x@y",
                    "claude plugin uninstall x@y --scope user", "claude plugin marketplace add o/r",
                    "claude mcp add foo -- npx foo", "lfg plugins install x@y", "lfg plugins disable x@y"):
            self.assertIsNotNone(guard.check("Bash", {"command": cmd}), cmd)
        for cmd in ("claude plugin list --json", "claude plugin details x@y", "lfg plugins", "lfg plugins list review",
                    "claude mcp list"):
            self.assertIsNone(guard.check("Bash", {"command": cmd}), cmd)


if __name__ == "__main__":
    unittest.main()
