"""The dashboard updates itself in place: a page or chat that redraws while Claude works (every 1.2 to 4 seconds)
changes only what changed, so what you opened, scrolled to, selected or typed stays as it was.

These read app.js; the behaviour itself was checked in headless Chrome against a dashboard with fake sessions (see
the PR). No LFG code is imported, but like every test file this one never points at the real ~/.lfg."""
import os
import re
import tempfile
import unittest

os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "plugin", "lib", "lfgcore", "ui_assets", "app.js")


def js():
    with open(APP, encoding="utf-8") as f:
        return f.read()


def body(src, start):
    """The source of a top-level function (or block) from `start` to its closing brace at the start of a line."""
    i = src.index(start)
    return src[i:src.index("\n}\n", i) + 2]


class MorphTest(unittest.TestCase):
    """morph(el, html): the one way a redraw changes what is on screen."""

    def test_keeps_what_belongs_to_the_person_or_to_script(self):
        keep = body(js(), "function keepAttr(")
        self.assertIn('name === "open" && a.tagName === "DETAILS"', keep)  # a section you opened
        self.assertIn('name === "style" && !inNew', keep)  # a text box script grew
        self.assertIn('name === "hidden" && a.matches(KEEP_SHOWN)', keep)  # an edit box you showed
        self.assertIn('getAttribute("data-keep")', keep)  # an open menu, an enlarged image
        self.assertIn("SCRIPT_FLAGS.includes(name)", keep)

    def test_leaves_script_drawn_content_and_script_added_boxes(self):
        src = js()
        self.assertIn('b.hasAttribute("data-fill") && a.childNodes.length', body(src, "function morphNode("))
        kids = body(src, "function morphKids(")
        self.assertIn("isLocal(cur)", kids)
        self.assertIn("if (!isLocal(cur)) cur.remove()", kids)

    def test_matches_elements_by_id_or_key_before_replacing_them(self):
        src = js()
        self.assertIn('n.id || n.getAttribute("data-key") || n.getAttribute("data-i")', src)
        self.assertIn("a.tagName === b.tagName && nodeKey(a) === nodeKey(b)", body(src, "function sameNode("))


class PageRedrawTest(unittest.TestCase):
    def test_a_page_already_showing_is_morphed_not_rebuilt(self):
        route = body(js(), "async function route(")
        self.assertIn("if (soft || seen) morph(view, html); else view.innerHTML = html;", route)
        self.assertIn("uiRestore(view, snap)", route)

    def test_a_page_numbers_its_tables_charts_and_logos_from_one(self):
        src = js()
        route = body(src, "async function route(")
        self.assertIn("TID = 0; tPage = true;", route)
        for start in ("function table(", "function iChart(", "function logoSvg("):
            self.assertIn("tPage ? ++TID", body(src, start), start)
        self.assertIn("same ? was.sort", body(src, "function table("))  # how you sorted it survives

    def test_restoring_focus_never_moves_your_text_selection(self):
        self.assertIn("document.activeElement !== el", body(js(), "function uiRestore("))

    def test_timers_redraw_in_place(self):
        src = js()
        wire = body(src, "function wire(root)")
        self.assertIn('pageTimer("checks"', wire)
        self.assertNotRegex(wire, r"\broute\(\); \}\s*\}, 10000\)")
        auto = src[src.index("const AUTO_REFRESH"):]
        auto = auto[:auto.index("}, 10 * 60 * 1000);")]
        self.assertIn("softRoute()", auto)
        self.assertNotIn("refresh()", auto)
        env = src[src.index("PAGES.environment = "):]
        self.assertIn('startsWith("environment")) softRoute();', env[:env.index("\n};\n")])
        self.assertIn("one pending per name", src)
        self.assertIn('pageTimer("pr", 4000', src)


class ChatRedrawTest(unittest.TestCase):
    def test_the_review_chat_is_its_own_and_starts_at_its_end_only_once(self):
        src = js()
        pane = body(src, "function talkPane(")
        self.assertIn('class="pr-thread ss-conv rv-conv" data-hint="${esc(hint)}" data-fill', pane)
        self.assertIn('data-chat-to="${esc(pr)}" data-fill', pane)
        self.assertIn('<span class="rv-ctx" data-fill>', pane)
        self.assertIn('rvBusy(rd) ? "Queue" : "Send"', pane)  # drawn from what the chat last saw, no flicker
        wire = body(src, "function wireChatPane(")
        self.assertIn("first = !conv._drawn", wire)
        self.assertIn("if (first) conv.scrollTop = conv.scrollHeight;", wire)
        self.assertNotIn("conv.innerHTML", wire)
        self.assertNotIn("sel.innerHTML", wire)
        self.assertNotIn("ctxBox.innerHTML", wire)

    def test_studio_updates_the_conversation_and_header_in_place(self):
        studio = body(js(), "function wireStudio(")
        self.assertIn("morph(conv, ssConv(n)); morph(head, ssHead(n));", studio)
        self.assertNotRegex(studio, r"(conv|head)\.innerHTML\s*=")
        self.assertIn('if (once(conv, "at-end")) conv.scrollTop = conv.scrollHeight;', studio)
        self.assertIn("morph(box, ssAct(n))", studio)

    def test_studio_menu_images_and_rewind_survive_a_redraw(self):
        src = js()
        self.assertIn('class="ss-menu" role="menu" data-keep="hidden"', body(src, "function ssHead("))
        self.assertIn('data-fill data-keep="class"', body(src, "function ssItems("))
        self.assertIn('box.dataset.local = ""', src)


class WiringTest(unittest.TestCase):
    """A redraw that keeps an element runs its wiring again: nothing may be added to it twice."""

    def test_listeners_are_added_once_per_element(self):
        src = js()
        studio = body(src, "function wireStudio(")
        self.assertIn('fresh = ta && once(ta, "studio")', studio)
        self.assertIn("if (fresh) {", studio)
        self.assertIn('if (once(t, "grow")) t.addEventListener', body(src, "function grow("))
        self.assertIn('once(box, "act")', body(src, "function wireAct("))
        self.assertIn("if (!o.comp._att) o.comp._att = ssAttachNew(o);", body(src, "function ssAttach("))

    def test_no_element_listener_is_added_on_every_wiring_of_a_view(self):
        # every addEventListener inside a wire* function is guarded by once(), or sits on something rebuilt each time
        src = js()
        allowed = {"wireInsights", "wireStudio", "wireAct", "wireView"}  # each checked above or guarded on the line
        for m in re.finditer(r"\n(?:async )?function (wire\w*)\(", src):
            name = m.group(1)
            fn = body(src, m.group(0).strip("\n"))
            for line in fn.splitlines():
                if ".addEventListener(" in line and "document.addEventListener" not in line:
                    self.assertTrue(name in allowed or "once(" in line, "%s adds a listener on every redraw: %s"
                                    % (name, line.strip()[:100]))


if __name__ == "__main__":
    unittest.main()
