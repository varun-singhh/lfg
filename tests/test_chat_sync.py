"""The PR review chat: a redraw never scrolls it from the top, and Claude knows what was already saved."""
import os
import re
import sys
import tempfile
import unittest

# like the other test files: a temp LFG_HOME unless one is set (test_core sets its own, and must be the one LFG's
# code sees, so a file that loads before it imports LFG lazily, inside the tests)
os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugin", "lib"))

ASSETS = os.path.join(ROOT, "plugin", "lib", "lfgcore", "ui_assets")


def review():
    """lfgcore.review, imported when a test runs: test_core has set LFG_HOME by then, whatever order files load in."""
    from lfgcore import review as R
    return R


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


class RedrawTest(unittest.TestCase):
    def test_a_redraw_that_changes_nothing_is_skipped_and_opened_sections_stay_open(self):
        js = read("app.js")
        draw = js[js.index("const draw = () => {"):]
        draw = draw[:draw.index("wired();")]
        # what it last drew lives on the element, not in a data- attribute a redraw of the page would take away;
        # what changed is updated in place (morph), so an open section is the same element and stays open
        self.assertIn("if (html !== conv._html) { morph(conv, html); conv._html = html; }", draw)
        self.assertNotIn("conv.dataset.html", js)
        self.assertNotIn("conv.innerHTML", draw)

    def test_copy_is_always_visible_under_a_reply_on_a_review_page(self):
        css = read("app.css")
        self.assertRegex(css, r"\.rv-conv \.ss-ai \.ss-msg-a\s*\{\s*opacity:\s*1;")


class SavedNoteTest(unittest.TestCase):
    def rec(self):
        return {"passes": [{"questions": [{"ask": "Use X?", "saved": {"to": "dev-graph"}}, {"ask": "Use Y?"}],
                            "findings": [{"id": "1.2", "saved": [{"to": "second-brain"}]}, {"id": "1.3"}]}]}

    def test_names_what_was_saved_and_where(self):
        note = review().saved_note(self.rec())
        self.assertIn('"Use X?": saved to this repo\'s dev-graph', note)
        self.assertIn("finding 1.2: saved to his second-brain", note)
        self.assertNotIn("Use Y?", note)
        self.assertNotIn("1.3", note)

    def test_nothing_saved_says_nothing(self):
        self.assertEqual(review().saved_note({"passes": [{"questions": [], "findings": [{"id": "1.1"}]}]}), "")

    def test_the_chat_is_told_not_to_ask_about_saving(self):
        for text in (review().ASK, review().ASK_SESSION):
            self.assertTrue(re.search(r"never ask whether to save", text), text[:60])


if __name__ == "__main__":
    unittest.main()
