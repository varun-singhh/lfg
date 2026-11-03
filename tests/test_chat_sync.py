"""The PR review chat: a redraw never scrolls it from the top, and Claude knows what was already saved."""
import os
import re
import sys
import tempfile
import unittest

# LFG code reads LFG_HOME when it is first imported: point it at a temp folder before anything imports it,
# whatever order the test files load in, so a test can never touch ~/.lfg
os.environ["LFG_HOME"] = tempfile.mkdtemp(prefix="lfg-test-home-")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugin", "lib"))
from lfgcore import review as R  # noqa: E402

ASSETS = os.path.join(ROOT, "plugin", "lib", "lfgcore", "ui_assets")


def read(name):
    with open(os.path.join(ASSETS, name), encoding="utf-8") as f:
        return f.read()


class ScrollTest(unittest.TestCase):
    def test_the_review_chat_does_not_animate_when_redrawn(self):
        css = read("app.css")
        self.assertRegex(css, r"\.rv-conv\s*\{\s*scroll-behavior:\s*auto;")
        self.assertGreater(css.index(".rv-conv { scroll-behavior"), css.index(".ss-conv { display: flex"))

    def test_restoring_a_scroll_position_is_instant(self):
        js = read("app.js")
        restore = js[js.index("function uiRestore"):]
        restore = restore[:restore.index("\n}\n")]
        self.assertIn('behavior: "instant"', restore)
        self.assertNotRegex(restore, r"el\.scrollTop\s*=")


class SavedNoteTest(unittest.TestCase):
    def rec(self):
        return {"passes": [{"questions": [{"ask": "Use X?", "saved": {"to": "dev-graph"}}, {"ask": "Use Y?"}],
                            "findings": [{"id": "1.2", "saved": [{"to": "second-brain"}]}, {"id": "1.3"}]}]}

    def test_names_what_was_saved_and_where(self):
        note = R.saved_note(self.rec())
        self.assertIn('"Use X?": saved to this repo\'s dev-graph', note)
        self.assertIn("finding 1.2: saved to his second-brain", note)
        self.assertNotIn("Use Y?", note)
        self.assertNotIn("1.3", note)

    def test_nothing_saved_says_nothing(self):
        self.assertEqual(R.saved_note({"passes": [{"questions": [], "findings": [{"id": "1.1"}]}]}), "")

    def test_the_chat_is_told_not_to_ask_about_saving(self):
        for text in (R.ASK, R.ASK_SESSION):
            self.assertTrue(re.search(r"never ask whether to save", text), text[:60])


if __name__ == "__main__":
    unittest.main()
