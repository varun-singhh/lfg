# ruff: noqa: E501  (embedded JavaScript)
"""Tab fixes in the dashboard (app.js), run as the real code in Node: each tab keeps its own appearance and repo, an alert
for another repo never moves this tab, and the "+" at the end of the tab row. Skipped when node isn't installed."""
import json
import os
import shutil
import subprocess
import unittest

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib", "lfgcore",
                      "ui_assets")
JS = open(os.path.join(ASSETS, "app.js")).read()

PRELUDE = """
const store = () => { const m = {}; return { getItem: k => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); },
  removeItem: k => { delete m[k]; }, dump: () => m }; };
const matchMedia = () => ({ matches: false, addEventListener() {} });
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
"""


def between(a, b):
    i = JS.index(a)
    return JS[i:JS.index(b, i)]


def run(script):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node isn't installed")
    cp = subprocess.run([node, "-e", PRELUDE + script], capture_output=True, text=True, timeout=30)
    if cp.returncode:
        raise AssertionError(cp.stderr[-1500:])
    return json.loads(cp.stdout.strip().splitlines()[-1])


class PerTabSettingsTest(unittest.TestCase):
    """Appearance and the picked repo: kept by the tab that set them across a reload, never changed in another tab."""

    SRC = lambda self: between("/* Per-tab settings", "/* The logo, drawn")  # noqa: E731

    def go(self, body):
        src = json.dumps(self.SRC())
        head = ("const local = store(); const localStorage = local;\nfunction openTab(session) {\n"
                "  const sessionStorage = session || store();\n  const document = { documentElement: { dataset: {} } };\n"
                "  const apFavicon = () => {};\n"
                "  const h = new Function('localStorage', 'sessionStorage', 'document', 'matchMedia', 'apFavicon', "
                + src + " + '\\napApply();\\nreturn { apRead, apSet, apApply, tabPrefGet, tabPrefSet, tabPrefClear };');\n"
                "  return { session: sessionStorage, doc: document, ...h(local, sessionStorage, document, matchMedia, "
                "apFavicon) };\n}\n")
        return run(head + body)

    def test_the_tab_that_sets_a_colour_keeps_it_across_a_reload(self):
        out = self.go("""
const a = openTab();
a.apSet("accent", "blue");
const reloaded = openTab(a.session);   // same tab, reloaded: its sessionStorage is still there
console.log(JSON.stringify({ now: a.doc.documentElement.dataset.accent, after: reloaded.doc.documentElement.dataset.accent }));
""")
        self.assertEqual(out, {"now": "blue", "after": "blue"})

    def test_another_tab_does_not_change_when_one_tab_picks_a_colour_even_after_its_own_reload(self):
        out = self.go("""
const a = openTab(), b = openTab();          // both open, both on the default colour
a.apSet("accent", "blue");
const bReloaded = openTab(b.session);        // B reloads: it keeps what it had
console.log(JSON.stringify({ a: a.doc.documentElement.dataset.accent, b: b.doc.documentElement.dataset.accent,
  bAfter: bReloaded.doc.documentElement.dataset.accent }));
""")
        self.assertEqual(out["a"], "blue")
        self.assertEqual(out["b"], out["bAfter"])
        self.assertNotEqual(out["b"], "blue")

    def test_a_new_tab_starts_from_the_last_colour_picked(self):
        out = self.go("""
const a = openTab();
a.apSet("accent", "blue");
const c = openTab();                         // a brand new tab: no sessionStorage yet
console.log(JSON.stringify({ c: c.doc.documentElement.dataset.accent }));
""")
        self.assertEqual(out["c"], "blue")

    def test_two_tabs_can_have_two_colours(self):
        out = self.go("""
const a = openTab(), b = openTab();
a.apSet("accent", "blue"); b.apSet("accent", "green");
const a2 = openTab(a.session), b2 = openTab(b.session);
console.log(JSON.stringify([a2.doc.documentElement.dataset.accent, b2.doc.documentElement.dataset.accent]));
""")
        self.assertEqual(out, ["blue", "green"])

    def test_the_picked_repo_is_kept_per_tab_too(self):
        out = self.go("""
const a = openTab(), b = openTab();
a.tabPrefSet("lfg.repo", "api-1"); b.tabPrefSet("lfg.repo", "web-2");
console.log(JSON.stringify({ a: openTab(a.session).tabPrefGet("lfg.repo"), b: openTab(b.session).tabPrefGet("lfg.repo"),
  fresh: openTab().tabPrefGet("lfg.repo") }));
""")
        self.assertEqual((out["a"], out["b"], out["fresh"]), ("api-1", "web-2", "web-2"))

    def test_a_repo_set_for_this_tab_only_leaves_the_default_for_new_tabs_alone(self):
        out = self.go("""
const a = openTab();
a.tabPrefSet("lfg.repo", "api-1");
a.tabPrefSet("lfg.repo", "from-link", true);   // set for this tab only (opened from an alert)
console.log(JSON.stringify({ a: openTab(a.session).tabPrefGet("lfg.repo"), fresh: openTab().tabPrefGet("lfg.repo") }));
""")
        self.assertEqual((out["a"], out["fresh"]), ("from-link", "api-1"))

    def test_reset_clears_this_tab_and_the_default(self):
        out = self.go("""
const a = openTab(); a.apSet("accent", "blue");
a.tabPrefClear("lfg.appearance");
console.log(JSON.stringify({ a: openTab(a.session).apRead().accent, fresh: openTab().apRead().accent }));
""")
        self.assertEqual(out["a"], out["fresh"])
        self.assertNotEqual(out["a"], "blue")

    def test_a_browser_that_refuses_storage_still_works(self):
        out = run("""
const bad = { getItem() { throw new Error("no"); }, setItem() { throw new Error("no"); }, removeItem() { throw new Error("no"); } };
const h = new Function('localStorage', 'sessionStorage', 'document', 'matchMedia', 'apFavicon',
  %s + '\\nreturn { apRead, apSet };');
const t = h(bad, bad, { documentElement: { dataset: {} } }, matchMedia, () => {});
t.apSet("accent", "blue");
console.log(JSON.stringify({ accent: t.apRead().accent }));
""" % json.dumps(self.SRC()))
        self.assertTrue(out["accent"])


class AlertsStayOnTheirRepoTest(unittest.TestCase):
    SRC = lambda self: between("/* Alerts and tabs: which repo", "function noteHtml(")  # noqa: E731

    def go(self, body, found="null"):
        src = json.dumps(self.SRC())
        head = """
const log = [];
const state = { repo: "api-1", repos: [{ id: "api-1", name: "api" }, { id: "web-2", name: "web" }] };
const loc = { hash: "#home", pathname: "/" };
const localStorage = store(), sessionStorage = store();
const closeBell = () => {}, route = () => log.push("route"), loadBranches = async () => log.push("loadBranches"), toast = ev => log.push("toast:" + ev.title);
const repoName = id => (state.repos.find(r => r.id === id) || {}).name || id;
let channelFound = %s;
const posted = [];
class BroadcastChannel { constructor() { this.onmessage = null; BroadcastChannel.last = this; }
  postMessage(m) { posted.push(m); if (m.t === "who" && channelFound) setTimeout(() => this.onmessage({ data: { t: "me", repo: m.repo, id: channelFound, ask: m.ask } }), 5); } }
const opened = [];
const window = { open: (url, target) => { opened.push([url, target]); return {}; }, focus() {} };
const document = { title: "LFG", addEventListener() {}, visibilityState: "visible" };
const location = new Proxy(loc, { set(o, k, v) { o[k] = v; log.push("hash:" + v); return true; } });
const mk = new Function('state', 'location', 'localStorage', 'sessionStorage', 'closeBell', 'route', 'loadBranches', 'toast',
  'repoName', 'BroadcastChannel', 'window', 'document', 'esc', 'setTimeout',
  %s + '\\nreturn { openNote, noteRepoHere, findRepoTab };');
const T = mk(state, location, localStorage, sessionStorage, closeBell, route, loadBranches, toast, repoName,
  BroadcastChannel, window, document, esc, setTimeout);
""" % (found, src)
        return run(head + body)

    def test_an_alert_for_the_same_repo_goes_to_its_page_as_before(self):
        out = self.go("""
(async () => { await T.openNote({ repo: "api-1", href: "#prs/acme/api/7" });
console.log(JSON.stringify({ log, opened, repo: state.repo })); })();
""")
        self.assertEqual(out["log"], ["hash:#prs/acme/api/7"])
        self.assertEqual((out["opened"], out["repo"]), ([], "api-1"))

    def test_an_alert_for_another_repo_opens_a_new_browser_tab_and_leaves_this_one_alone(self):
        out = self.go("""
(async () => { await T.openNote({ repo: "web-2", href: "#prs/acme/web/9" });
console.log(JSON.stringify({ log, opened, repo: state.repo, hash: loc.hash, local: localStorage.dump(), session: sessionStorage.dump() })); })();
""")
        self.assertEqual(out["repo"], "api-1")  # this tab did not switch repo
        self.assertEqual(out["hash"], "#home")  # and did not navigate
        self.assertEqual(out["local"], {})  # and the default repo for other tabs was not changed
        self.assertEqual(out["session"], {})
        self.assertEqual(len(out["opened"]), 1)
        url, target = out["opened"][0]
        self.assertTrue(url.startswith("/?repo=web-2"), url)
        self.assertTrue(url.endswith("#prs/acme/web/9"), url)
        self.assertEqual(target, "_blank")

    def test_an_alert_for_another_repo_goes_to_the_tab_that_already_has_that_repo(self):
        out = self.go("""
(async () => { await T.openNote({ repo: "web-2", href: "#prs/acme/web/9" });
console.log(JSON.stringify({ log, opened, posted: posted.map(m => [m.t, m.to, m.href]), hash: loc.hash })); })();
""", found='"tab-xyz"')
        self.assertEqual(out["opened"], [])
        self.assertIn(["go", "tab-xyz", "#prs/acme/web/9"], out["posted"])
        self.assertEqual(out["hash"], "#home")
        self.assertTrue([x for x in out["log"] if x.startswith("toast:")])  # says where it went

    def test_an_alert_for_a_repo_not_known_here_behaves_as_before(self):
        out = self.go("""
(async () => { await T.openNote({ repo: "gone-9", href: "#checks" });
console.log(JSON.stringify({ log, opened })); })();
""")
        self.assertEqual((out["log"], out["opened"]), (["hash:#checks"], []))

    def test_an_alert_with_no_repo_just_goes_to_its_page(self):
        out = self.go("""
(async () => { await T.openNote({ href: "#checks" }); console.log(JSON.stringify({ log, opened })); })();
""")
        self.assertEqual((out["log"], out["opened"]), (["hash:#checks"], []))


class TabPlusTest(unittest.TestCase):
    SRC = lambda self: between("const TABSETS = {", "const tabNavRow = ")  # noqa: E731

    def test_the_tab_row_ends_with_a_plus_that_offers_new_studio_and_new_pr_review(self):
        out = run("""
const icon = () => "", state = { repo: "r", repos: [], navSess: [] }, location = { hash: "#prs/o/r/1" };
const localStorage = { getItem: () => JSON.stringify([{ pr: "o/r#1", title: "One" }]) };
const repoName = () => "";
const ssLive = () => false;
const nsDot = () => "", ssStateOf = () => "", TABS_MAX = 40;
const h = new Function('esc', 'icon', 'state', 'location', 'localStorage', 'repoName', 'ssLive', 'nsDot', 'ssStateOf',
  'TABS_MAX', 'tabData_', %s + '\\nreturn { tabStrip, tabAddMenu };');
const t = h(esc, icon, state, location, localStorage, repoName, ssLive, nsDot, ssStateOf, TABS_MAX, null);
console.log(JSON.stringify({ strip: t.tabStrip("prs"), menu: t.tabAddMenu() }));
""" % json.dumps(self.SRC()))
        strip, menu = out["strip"], out["menu"]
        self.assertTrue(strip.rstrip().endswith("</div>"))
        self.assertIn("data-tab-add", strip)
        self.assertLess(strip.index("prtab"), strip.index("data-tab-add"))  # after the tabs
        self.assertIn("New studio", menu)
        self.assertIn("New PR review", menu)
        self.assertIn('data-tab-new="studio"', menu)
        self.assertIn('data-tab-new="prs"', menu)


class SourceChecksTest(unittest.TestCase):
    def test_nothing_writes_the_repo_or_appearance_to_the_shared_store_directly_any_more(self):
        self.assertNotIn('localStorage.setItem("lfg.repo"', JS)
        self.assertNotIn('localStorage.setItem("lfg.appearance"', JS)
        self.assertNotIn('localStorage.getItem("lfg.appearance")', JS)
        self.assertIn('tabPrefGet("lfg.repo")', JS)


if __name__ == "__main__":
    unittest.main()
