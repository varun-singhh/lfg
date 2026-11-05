"""Corrections (lfgcore.corrections): what you correct Claude on, queued for you to turn into rules."""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib"))

from lfgcore import common as C  # noqa: E402
from lfgcore import corrections as CR  # noqa: E402
from lfgcore import guard  # noqa: E402
from lfgcore import prefs as P  # noqa: E402

SID = "aaaaaaaa-2222-3333-4444-555555555555"


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def assistant(text="", tool=None):
    content = [{"type": "text", "text": text}] if text else []
    if tool:
        content.append({"type": "tool_use", "name": tool[0], "input": tool[1]})
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def rejected(reason=""):
    body = CR.REJECTED + " The tool use was rejected (eg. if it was a file edit, the new_string was NOT written to " \
                         "the file). "
    body += ("To tell you how to proceed, " + CR.SAID_AFTER_REJECT + reason) if reason else \
        "STOP what you are doing and wait for the user to tell you how to proceed."
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": body}]}}


class Base(unittest.TestCase):
    def setUp(self):
        for f in (CR._path(), CR._offsets_path(), P._state_path(), P._seen_path()):
            if os.path.exists(f):
                os.remove(f)
        self.md = os.path.join(tempfile.mkdtemp(), "lfg-preferences.md")
        m = mock.patch.object(P, "PREFS_MD", self.md)
        m.start()
        self.addCleanup(m.stop)
        self.repo = tempfile.mkdtemp(prefix="repo-")
        os.mkdir(os.path.join(self.repo, ".git"))


class DetectTest(Base):
    def test_reads_corrections_and_lets_agreement_and_requests_through(self):
        for t in ("no, use pnpm", "Actually it lives in the api repo", "I told you not to push", "stop adding comments",
                  "why did you delete that?", "That's not what I asked", "don't touch the migrations"):
            self.assertIsNotNone(CR.detect(t), t)
        for t in ("no it's okay. now do the next one", "no that's fine", "No worries", "add a test for the parser",
                  "<pasted_content id=\"1\">no, never do this</pasted_content>", "[Request interrupted by user]",
                  "x" * 2000):
            self.assertIsNone(CR.detect(t), t)
        self.assertIsNotNone(CR.detect("no that's fine, but I told you to keep it short"))

    def test_scan_pairs_each_correction_with_what_claude_did(self):
        lines = [user("fix the build"), assistant("I'll run npm.", ("Bash", {"command": "npm test"})),
                 user("no, use pnpm here")]
        found, _ = CR.scan(lines)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], "said")
        self.assertIn("npm test", found[0]["did"])

    def test_rejections_and_interruptions(self):
        found, st = CR.scan([assistant("", ("Bash", {"command": "git push"})), rejected("push only when I say")])
        self.assertEqual([x["kind"] for x in found], ["rejected"])
        self.assertEqual(found[0]["said"], "push only when I say")
        # a rejection with no reason: what you say next is the reason, even in the next turn
        found, st = CR.scan([assistant("", ("Edit", {"file_path": "/r/a.py"})), rejected(),
                             user("[Request interrupted by user for tool use]")])
        self.assertEqual(found, [])
        found, st = CR.scan([user("leave a.py alone, edit b.py")], st)
        self.assertEqual(found[0]["kind"], "rejected")
        self.assertIn("a.py", found[0]["did"])
        found, st = CR.scan([assistant("Working"), user("[Request interrupted by user]"), user("continue")], st)
        self.assertEqual(found, [])
        self.assertNotIn("after", st)
        # AskUserQuestion's "chat about this" is not a reason
        found, _ = CR.scan([rejected("The user wants to clarify these questions.")])
        self.assertEqual(found, [])


class QueueTest(Base):
    def transcript(self, events):
        path = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        with open(path, "a") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        return path

    def test_off_by_default_and_capture_reads_each_line_once(self):
        path = self.transcript([assistant("done"), user("no, wrong branch")])
        data = {"session_id": SID, "transcript_path": path, "cwd": self.repo}
        self.assertEqual(CR.capture(data), [])
        CR.set_enabled(True)
        got = CR.capture(data)  # a session seen for the first time: its recent tail is read
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["repo"], os.path.realpath(self.repo))
        self.assertEqual(CR.capture(data), [])  # nothing new
        with open(path, "a") as f:
            f.write(json.dumps(user("I told you, the staging one")) + "\n")
        self.assertEqual(len(CR.capture(data)), 1)
        self.assertEqual(len(CR.items()), 2)

    def test_secrets_are_masked(self):
        CR.set_enabled(True)
        x = CR.add("no, the key is ghp_" + "a" * 36, cwd=self.repo)
        self.assertNotIn("ghp_", x["said"])
        self.assertIn("[github-token removed]", x["said"])

    def test_add_needs_the_feature_on_and_is_never_a_rule(self):
        with self.assertRaises(ValueError):
            CR.add("you keep asking me")
        CR.set_enabled(True)
        x = CR.add("you asked me to decide something already decided", did="asked a question",
                   note="Don't ask about what is already decided.", cwd=self.repo)
        self.assertEqual(x["kind"], "flagged")
        self.assertEqual(CR.add("you asked me to decide something already decided", cwd=self.repo)["queued"], False)
        self.assertEqual(CR.rules(), [])


class PromoteTest(Base):
    def setUp(self):
        super().setUp()
        CR.set_enabled(True)
        self.x = CR.add("you asked me to decide something already decided", cwd=self.repo)

    def test_approve_global_goes_to_the_rules_file_with_why_and_example(self):
        r = CR.approve(self.x["id"], "Don't ask me to decide what's already decided.", title="No settled questions",
                       why="It wastes a turn.", example="Asking where 4203 goes after we agreed.")
        text = C.read_text(self.md)
        self.assertIn("Don't ask me to decide", text)
        self.assertIn("Why: It wastes a turn.", text)
        self.assertIn("For example: Asking where 4203 goes", text)
        self.assertEqual(CR.get(self.x["id"])["status"], "approved")
        P.set_pref(r["rule"], False)  # its own switch
        self.assertNotIn("Don't ask me to decide", C.read_text(self.md))
        with self.assertRaises(ValueError):
            CR.approve(self.x["id"], "again")

    def test_project_rules_reach_only_that_repo(self):
        CR.approve(self.x["id"], "Use pnpm in this repo.", scope="project")
        self.assertNotIn("pnpm", C.read_text(self.md))
        self.assertIn("Use pnpm in this repo.", CR.session_note(self.repo))
        self.assertNotIn("pnpm", CR.session_note(tempfile.mkdtemp()))

    def test_similar_rules_are_offered_for_merging(self):
        P.add_custom("cr-pnpm", CR.GROUP, "pnpm", "Always use pnpm, never npm, in every repo.")
        y = CR.add("no, use pnpm not npm", cwd=self.repo)
        self.assertEqual(CR.similar("use pnpm, never npm")[0]["id"], "cr-pnpm")
        CR.merge(y["id"], "cr-pnpm", why="npm breaks the lockfile")
        rule = next(r for r in CR.rules() if r["id"] == "cr-pnpm")
        self.assertEqual(rule["why"], "npm breaks the lockfile")
        self.assertIn(y["id"], rule["sources"])
        CR.discard([self.x["id"]])
        self.assertEqual(CR.items(), [])

    def test_background_goes_to_second_brain_not_the_rules(self):
        with mock.patch("lfgcore.knowledge.add", return_value={"slug": "nt-x", "saved_to": "second-brain"}) as add:
            r = CR.to_brain(self.x["id"], "", "Lee decides scope before tickets exist.")
        add.assert_called_once_with("note", "Lee decides scope before tickets exist.",
                                    "Lee decides scope before tickets exist.")
        self.assertEqual(r["saved_to"], "second-brain")
        self.assertEqual(CR.get(self.x["id"])["status"], "to second-brain")
        self.assertEqual(CR.rules(), [])
        self.assertIn("Remember?", CR.FLAG_NOTE)

    def test_the_hooks_tell_sessions(self):
        CR.approve(self.x["id"], "Use pnpm in this repo.", scope="project")
        data = {"session_id": SID, "cwd": self.repo}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(data))), mock.patch("sys.stdout", io.StringIO()) as out:
            P.hook("session-start")
        ctx = json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Use pnpm in this repo.", ctx)
        self.assertIn("lfg corrections add", ctx)
        CR.set_enabled(False)
        with mock.patch("sys.stdin", io.StringIO(json.dumps(data))), mock.patch("sys.stdout", io.StringIO()) as out:
            P.hook("prompt")
        self.assertNotIn("lfg corrections add", out.getvalue())
        self.assertIn("Use pnpm in this repo.", out.getvalue())


class OnlyYouDecideTest(Base):
    def test_claude_cannot_approve_discard_or_switch_it(self):
        v = P.effective()
        for cmd in ("lfg corrections approve c-1 --text x", "lfg corrections merge c-1 r",
                    "lfg corrections discard c-1", "lfg corrections brain c-1", "lfg corrections off",
                    "lfg corrections on"):
            self.assertIsNotNone(P.check_command(cmd, v), cmd)
            self.assertIsNotNone(guard.check("Bash", {"command": cmd}, prefs=v), cmd)
        for cmd in ('lfg corrections add "no, use pnpm"', "lfg corrections", "lfg corrections show c-1"):
            self.assertIsNone(P.check_command(cmd, v), cmd)
        data = {"session_id": SID, "tool_name": "Write", "tool_input": {"file_path": CR._path()}}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(data))), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(P.hook("pre-tool"), 2)

    def test_the_stop_hook_is_installed_with_the_others(self):
        self.assertIn(("Stop", None, "stop"), P.HOOKS)


if __name__ == "__main__":
    unittest.main()
