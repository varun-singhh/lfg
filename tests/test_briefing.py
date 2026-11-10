"""Tests for the "Where you left off" briefing (lfgcore/briefing.py). Stdlib only; run with the rest:
`python3 -m unittest discover -s tests`."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

# like the other test files: a temp LFG_HOME unless one is set (test_core sets its own, and must be the one LFG's
# code sees), so lfgcore is imported in setUpModule, after every file has loaded
os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib"))

B = C = SS = S = ui = None


def setUpModule():
    global B, C, SS, S, ui
    from lfgcore import briefing as B_
    from lfgcore import common as C_
    from lfgcore import sessions as SS_
    from lfgcore import settings as S_
    from lfgcore import ui as ui_
    B, C, SS, S, ui = B_, C_, SS_, S_, ui_


def graph():
    """EPIC-1 holds milestones MS-10 (leaves TT-1, TT-2, TT-3) and MS-20 (leaf TT-4) and the loose ticket TT-5."""
    def issue(k, status="Todo"):
        return {"key": k, "title": "Title " + k, "status": status}
    issues = {k: issue(k) for k in ("EPIC-1", "MS-10", "MS-20", "TT-1", "TT-2", "TT-3", "TT-4", "TT-5")}
    return {"issues": issues, "blocks": [],
            "groups": {"EPIC-1": {"key": "EPIC-1", "title": "The epic", "kind": "epic",
                                  "members": {"MS-10", "MS-20", "TT-5"}},
                       "MS-10": {"key": "MS-10", "title": "First milestone", "kind": "parent",
                                "members": {"TT-1", "TT-2", "TT-3"}},
                       "MS-20": {"key": "MS-20", "title": "Second milestone", "kind": "parent", "members": {"TT-4"}}}}


def row(**kw):
    return dict({"ticket": "", "folder": "", "branch": "", "title": "", "ai_title": "", "first": ""}, **kw)


class TreeAndRolesTest(unittest.TestCase):
    def setUp(self):
        self.tree = B.tree(graph(), "EPIC-1")

    def test_tree_two_levels_with_loose_leaves(self):
        t = self.tree
        self.assertEqual((t["key"], t["title"]), ("EPIC-1", "The epic"))
        self.assertEqual([(m["key"], m["title"], m["leaves"]) for m in t["milestones"]],
                         [("MS-10", "First milestone", ["TT-1", "TT-2", "TT-3"]),
                          ("MS-20", "Second milestone", ["TT-4"])])
        self.assertEqual(t["loose"], ["TT-5"])

    def test_tickets_in_reads_branch_title_and_first_message(self):
        r = row(branch="lee/ato-3574-fix", title="see TT-1", first="also ABC-9 and SHA-256 and gpt-4")
        self.assertEqual(B.tickets_in(r), {"ATO-3574", "TT-1", "ABC-9"})

    def test_orchestrator_by_group(self):
        self.assertEqual(B.role_of(row(folder="G"), self.tree, {"EPIC-1"}), "orchestrator")

    def test_orchestrator_by_naming_the_epic(self):
        self.assertEqual(B.role_of(row(first="work on EPIC-1"), self.tree, set()), "orchestrator")
        self.assertEqual(B.role_of(row(branch="lee/epic-1-plan"), self.tree, set()), "orchestrator")

    def test_orchestrator_by_three_children(self):
        r = row(first="TT-1 TT-4 and TT-5 please")
        self.assertEqual(B.role_of(r, self.tree, set()), "orchestrator")

    def test_worker_when_it_names_one_child(self):
        self.assertEqual(B.role_of(row(branch="lee/tt-2-do-it"), self.tree, set()), "worker")
        self.assertEqual(B.role_of(row(first="TT-1 and TT-2"), self.tree, set()), "worker")

    def test_a_milestone_counts_as_a_child_for_naming(self):
        self.assertEqual(B.role_of(row(first="MS-20 stuff"), self.tree, set()), "worker")

    def test_unsorted_when_nothing_matches(self):
        self.assertEqual(B.role_of(row(first="what does this do"), self.tree, set()), "unsorted")
        self.assertEqual(B.role_of(row(first="ZZZ-1"), self.tree, {"OTHER-1"}), "unsorted")

    def test_orchestrator_wins_over_worker(self):
        self.assertEqual(B.role_of(row(branch="lee/tt-2-x", first="for EPIC-1"), self.tree, set()), "orchestrator")


NOW = 1_800_000_000.0
DAY = 86400


def iso(ago):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - ago))


def srow(sid, ago, **kw):
    return row(**dict({"id": sid, "modified": iso(ago), "repo": "app", "folder": ""}, **kw))


def done_graph():
    g = graph()
    for k in ("TT-1", "TT-2", "TT-3", "TT-4", "TT-5"):
        g["issues"][k]["status"] = "done"
    return g


class EntriesTest(unittest.TestCase):
    def test_entries_newest_first_and_capped(self):
        rows = [srow("s%d" % i, i * 60, first="ZZ-%d" % (i + 1)) for i in range(40)]
        out = B.entries(NOW, rows=rows, graph=graph(), groups={})
        self.assertEqual(len(out), B.MAX_ENTRIES)
        self.assertEqual(out[0]["key"], "ZZ-1")  # the newest session
        self.assertEqual([e["key"] for e in out], sorted((e["key"] for e in out), key=lambda k: int(k[3:])))

    def test_sessions_of_one_epic_make_one_entry_with_counts(self):
        rows = [srow("a", 60, first="for EPIC-1"), srow("b", 3 * 3600, branch="lee/tt-1-x"),
                srow("c", 2 * DAY, branch="lee/tt-4-y")]
        out = B.entries(NOW, rows=rows, graph=graph(), groups={})
        self.assertEqual([e["key"] for e in out], ["EPIC-1"])
        e = out[0]
        self.assertEqual((e["kind"], e["title"], e["progress"]), ("epic", "The epic", None))
        self.assertEqual(e["sessions"], {"working": 1, "idle": 2, "unsorted": 0})
        self.assertEqual(e["last_active"], iso(60))
        self.assertEqual(e["repos"], ["app"])

    def test_a_group_that_follows_a_ticket_names_it(self):
        rows = [srow("a", 60, folder="Sub")]
        groups = {"Sub": {"parent": "Top", "prs": [], "tickets": []},
                  "Top": {"parent": "", "prs": [], "tickets": ["EPIC-1"]}}
        out = B.entries(NOW, rows=rows, graph=graph(), groups=groups)
        self.assertEqual([e["key"] for e in out], ["EPIC-1"])

    def test_old_sessions_do_not_make_an_entry(self):
        rows = [srow("a", (B.ACTIVE_DAYS + 1) * DAY, first="for EPIC-1")]
        self.assertEqual(B.entries(NOW, rows=rows, graph=graph(), groups={}), [])

    def test_a_finished_epic_drops_after_three_quiet_days(self):
        quiet = [srow("a", (B.DONE_DROP_DAYS + 1) * DAY, first="for EPIC-1")]
        fresh = [srow("a", DAY, first="for EPIC-1")]
        self.assertEqual(B.entries(NOW, rows=quiet, graph=done_graph(), groups={}), [])
        self.assertEqual([e["key"] for e in B.entries(NOW, rows=fresh, graph=done_graph(), groups={})], ["EPIC-1"])
        self.assertEqual(len(B.entries(NOW, rows=quiet, graph=graph(), groups={})), 1)  # not done: stays

    def test_plain_ticket_with_no_children_is_kind_ticket(self):
        out = B.entries(NOW, rows=[srow("a", 60, branch="lee/ato-9-fix")], graph=graph(), groups={})
        self.assertEqual([(e["key"], e["kind"]) for e in out], [("ATO-9", "ticket")])

    def test_a_session_with_no_ticket_and_no_group_goes_under_unsorted(self):
        out = B.entries(NOW, rows=[srow("a", 60, first="what does this do"), srow("b", 90, first="EPIC-1")],
                        graph=graph(), groups={})
        self.assertEqual([(e["key"], e["kind"]) for e in out], [("EPIC-1", "epic"), ("", "unsorted")])
        self.assertEqual(out[1]["sessions"]["unsorted"], 1)

    def test_activity_is_working_for_ten_minutes_after_the_transcript_changed(self):
        self.assertEqual(B.activity(srow("a", 5 * 60), NOW), "working")
        self.assertEqual(B.activity(srow("a", 11 * 60), NOW), "idle")


class ProgressTest(unittest.TestCase):
    def test_progress_counts_leaf_tickets_once_across_repos(self):
        other = {"issues": {"TT-1": {"key": "TT-1", "title": "x", "status": "done"}}, "blocks": [],
                 "groups": {"MS-10": {"key": "MS-10", "title": "", "kind": "parent", "members": {"TT-1"}}}}
        g = B.merge_graphs([graph(), other])
        out = B.progress("EPIC-1", graph=g, prs={})
        self.assertEqual((out["done"], out["total"]), (1, 5))  # TT-1 is one ticket, done in either copy
        self.assertEqual([(m["key"], m["done"], m["total"]) for m in out["milestones"]],
                         [("MS-10", 1, 3), ("MS-20", 0, 1)])

    def test_a_merged_pr_counts_as_done(self):
        prs = {"TT-2": {"number": 7, "state": "merged_main"}, "TT-3": {"number": 8, "state": "open"}}
        out = B.progress("EPIC-1", graph=graph(), prs=prs)
        self.assertEqual((out["done"], out["total"]), (1, 5))

    def test_progress_unavailable_says_why(self):
        out = B.progress("ATO-77", graph=graph(), prs={})
        self.assertIn("unavailable", out)
        self.assertNotIn("done", out)
        self.assertIn("ATO-77", out["unavailable"])
        g = dict(graph(), errors=["dev-graph is not running"])
        out = B.progress("EPIC-1", graph=dict(g, issues={}, groups={}), prs={})
        self.assertIn("dev-graph is not running", out["unavailable"])

    def test_a_plain_ticket_shows_its_pr_not_zero_of_zero(self):
        prs = {"TT-5": {"number": 9, "state": "open"}}
        out = B.progress("TT-5", graph=graph(), prs=prs)
        self.assertEqual((out["kind"], out["pr"]["number"], out["finished"]), ("ticket", 9, False))
        self.assertNotIn("total", out)


def pr(n, state="open", author="sam", ci="pass", repo="acme/app"):
    return {"number": n, "title": "PR %d" % n, "state": state, "author": author, "ci": ci, "gh_repo": repo,
            "url": "https://github.com/%s/pull/%d" % (repo, n)}


class BriefingTest(unittest.TestCase):
    def setUp(self):
        self.rows = [srow("orch", 120, name="Plan the epic", first="Plan EPIC-1"),
                     srow("w1", 3 * 3600, name="Build one", branch="lee/tt-1-build"),
                     srow("w4", 30 * 60, name="Build four", branch="lee/tt-4-build"),
                     srow("loose", 3 * 60, name="Five", branch="lee/tt-5-build"),
                     srow("lost", 600, name="Lost one", first="what is this")]
        self.prs = {}

    def make(self, key="EPIC-1", **kw):
        args = dict(rows=self.rows, graph=graph(), groups={}, prs=self.prs, me="lee", records=[], now=NOW)
        args.update(kw)
        return B.briefing(key, **args)

    def test_orchestrator_is_on_top_not_in_a_milestone(self):
        out = self.make()
        self.assertEqual((out["orchestrator"]["id"], out["orchestrator"]["role"]), ("orch", "orchestrator"))
        self.assertEqual(out["orchestrator"]["activity"], "working")
        ids = [r["id"] for m in out["milestones"] for r in m["sessions"]]
        self.assertNotIn("orch", ids)
        by = {m["key"]: [r["id"] for r in m["sessions"]] for m in out["milestones"]}
        self.assertEqual(by["MS-10"], ["w1"])
        self.assertEqual(by["MS-20"], ["w4"])
        self.assertEqual(by[""], ["loose"])  # a ticket with no milestone: "Other tickets"
        self.assertEqual((out["entry"]["key"], out["entry"]["kind"]), ("EPIC-1", "epic"))
        self.assertEqual((out["progress"]["done"], out["progress"]["total"]), (0, 5))
        self.assertEqual([(m["key"], m["total"]) for m in out["milestones"]], [("MS-10", 3), ("MS-20", 1), ("", 1)])

    def test_unsorted_sessions_listed_not_dropped(self):
        out = self.make()
        self.assertEqual([r["id"] for r in out["unsorted"]], ["lost"])
        self.assertEqual([r["id"] for r in self.make("")["unsorted"]], ["lost"])

    def test_needs_you_review_someone_elses_open_pr_with_no_saved_review(self):
        self.prs = {"TT-1": pr(11, author="sam")}
        out = self.make()
        item = next(i for i in out["needs_you"] if i["kind"] == "review_pr")
        self.assertEqual(item["target"], "#prs/acme/app/11")
        self.assertIn("sam", item["text"])
        saved = {"repo": "acme/app", "number": 11, "ticket": "TT-1", "passes": []}
        self.assertFalse([i for i in self.make(records=[saved])["needs_you"] if i["kind"] == "review_pr"])

    def test_needs_you_answer_an_open_question_in_a_saved_review(self):
        rec = {"repo": "acme/app", "number": 11, "ticket": "TT-1",
               "passes": [{"n": 1, "questions": [{"id": "q1", "ask": "Why a new table?"},
                                                 {"id": "q2", "ask": "Done?", "answer": "yes"}]}]}
        self.prs = {"TT-1": pr(11, author="lee")}
        out = self.make(records=[rec])
        items = [i for i in out["needs_you"] if i["kind"] == "question"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target"], "#prs/acme/app/11")
        self.assertIn("Why a new table?", items[0]["text"])

    def test_needs_you_fix_your_own_pr_with_failing_checks(self):
        self.prs = {"TT-2": pr(12, author="lee", ci="fail")}
        items = [i for i in self.make()["needs_you"] if i["kind"] == "checks"]
        self.assertEqual([i["target"] for i in items], ["#prs/acme/app/12"])

    def test_needs_you_a_worker_idle_for_an_hour_with_an_open_pr(self):
        self.prs = {"TT-1": pr(13, author="lee"), "TT-4": pr(14, author="lee")}
        items = [i for i in self.make()["needs_you"] if i["kind"] == "idle_pr"]
        self.assertEqual([i["target"] for i in items], ["#studio/w1"])  # w4 was active 30 minutes ago

    def test_no_needs_you_when_nothing_is_waiting(self):
        self.prs = {"TT-1": pr(15, author="lee"), "TT-2": pr(16, state="merged_main", author="sam")}
        self.assertEqual(self.make(rows=self.rows[:1])["needs_you"], [])

    def test_without_github_the_pr_rules_are_skipped_and_it_says_so(self):
        out = self.make(prs=None, gh_note="gh is not signed in")
        self.assertEqual(out["needs_you"], [])
        self.assertIn("gh is not signed in", out["gh_note"])

    def test_a_plain_ticket_lists_its_sessions_without_an_orchestrator(self):
        out = self.make("ATO-9", rows=[srow("a", 60, branch="lee/ato-9-x")])
        self.assertIsNone(out["orchestrator"])
        self.assertEqual([r["id"] for m in out["milestones"] for r in m["sessions"]], ["a"])
        self.assertEqual(out["entry"]["kind"], "ticket")


class SummaryTest(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="lfg-test-briefing-")
        p = mock.patch.object(C, "LFG_HOME", home)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(__import__("shutil").rmtree, home, True)
        rows = [srow("orch", 120, name="Plan the epic", first="Plan EPIC-1"),
                srow("w1", 3 * 3600, name="Build one", branch="lee/tt-1-build")]
        self.data = B.briefing("EPIC-1", rows=rows, graph=graph(), groups={}, prs={}, me="lee", records=[], now=NOW)
        self.calls = []
        B._TRY.clear()
        B._RUNNING.clear()
        p = mock.patch.object(B, "_last_messages", lambda s: ["Me: do the migration", "Claude: migration written"])
        p.start()
        self.addCleanup(p.stop)

    def run_ok(self, prompt, model):
        self.calls.append((prompt, model))
        return "It stopped after the migration.", 0.04

    def test_summary_stored_with_time_and_key(self):
        out = B.summarize("EPIC-1", run=self.run_ok, data=self.data, now=NOW)
        self.assertEqual((out["text"], out["cost"], out["key"]), ("It stopped after the migration.", 0.04,
                                                                B.summary_key("EPIC-1", self.data)))
        self.assertTrue(out["at"])
        stored = C.read_json(B.summary_path("EPIC-1"))
        self.assertEqual(stored["text"], out["text"])
        self.assertTrue(B.summary_path("EPIC-1").startswith(C.lfg_path("state", "briefings")))
        prompt, model = self.calls[0]
        self.assertEqual(model, B.pinned_model())
        for want in ("The epic", "migration written", "0 of 5"):
            self.assertIn(want, prompt)

    def test_a_failed_call_keeps_the_last_summary(self):
        B.summarize("EPIC-1", run=self.run_ok, data=self.data, now=NOW)

        def boom(prompt, model):
            raise RuntimeError("claude timed out")
        out = B.summarize("EPIC-1", run=boom, data=self.data, now=NOW + 3600)
        self.assertIn("claude timed out", out["error"])
        self.assertEqual(C.read_json(B.summary_path("EPIC-1"))["text"], "It stopped after the migration.")
        self.assertEqual(B.stored_summary("EPIC-1", self.data, now=NOW + 3600)["text"],
                         "It stopped after the migration.")

    def stored(self, key, at):
        C.write_json(B.summary_path("EPIC-1"), {"text": "old", "at": time.strftime("%Y-%m-%dT%H:%M:%S",
                     time.localtime(at)), "at_epoch": at, "cost": 0, "key": key})

    def test_not_regenerated_within_ten_minutes(self):
        self.stored("an older key", NOW - 5 * 60)
        B.maybe_summarize("EPIC-1", run=self.run_ok, data=self.data, now=NOW, background=False)
        self.assertEqual(self.calls, [])
        B.maybe_summarize("EPIC-1", run=self.run_ok, data=self.data, now=NOW + 6 * 60, background=False)
        self.assertEqual(len(self.calls), 1)

    def test_not_regenerated_when_the_key_is_unchanged(self):
        self.stored(B.summary_key("EPIC-1", self.data), NOW - DAY)
        B.maybe_summarize("EPIC-1", run=self.run_ok, data=self.data, now=NOW, background=False)
        self.assertEqual(self.calls, [])

    def test_a_failed_attempt_also_waits_ten_minutes(self):
        def boom(prompt, model):
            raise RuntimeError("no")
        B.maybe_summarize("EPIC-1", run=boom, data=self.data, now=NOW, background=False)
        B.maybe_summarize("EPIC-1", run=self.run_ok, data=self.data, now=NOW + 60, background=False)
        self.assertEqual(self.calls, [])

    def test_stored_summary_is_marked_stale_when_the_work_moved_on(self):
        B.summarize("EPIC-1", run=self.run_ok, data=self.data, now=NOW)
        self.assertFalse(B.stored_summary("EPIC-1", self.data, now=NOW)["stale"])
        moved = dict(self.data, orchestrator=dict(self.data["orchestrator"], modified=iso(-60)))
        self.assertTrue(B.stored_summary("EPIC-1", moved, now=NOW)["stale"])


class ApiTest(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="lfg-test-briefing-api-")
        self.projects = tempfile.mkdtemp(prefix="lfg-test-briefing-proj-")
        for d in (home, self.projects):
            self.addCleanup(__import__("shutil").rmtree, d, True)
        for p in (mock.patch.object(C, "LFG_HOME", home), mock.patch.object(SS, "PROJECTS", self.projects)):
            p.start()
            self.addCleanup(p.stop)

    def write(self, sid, branch="main", prompt="hello"):
        d = os.path.join(self.projects, "-nowhere-app")
        os.makedirs(d, exist_ok=True)
        ev = {"type": "user", "cwd": "/nowhere/app", "gitBranch": branch, "entrypoint": "cli",
              "timestamp": "2026-10-19T10:00:00Z", "message": {"role": "user", "content": prompt}}
        with open(os.path.join(d, sid + ".jsonl"), "w") as f:
            f.write(json.dumps(ev) + "\n")

    SID = "%08d-0000-0000-0000-000000000000" % 7

    def test_views_return_the_documented_shape(self):
        sample = [{"key": "EPIC-1", "title": "The epic", "kind": "epic", "repos": ["app"], "last_active": iso(60),
                   "sessions": {"working": 1, "idle": 0, "unsorted": 0}, "progress": None}]
        data = {"entry": sample[0], "progress": {"unavailable": "x"}, "orchestrator": None, "milestones": [],
                "unsorted": [], "needs_you": [], "gh_note": "", "summary": None}
        with mock.patch.object(B, "entries", return_value=sample), \
                mock.patch.object(B, "progress", return_value={"done": 1, "total": 2, "milestones": []}) as prog, \
                mock.patch.object(B, "briefing", return_value=data), \
                mock.patch.object(B, "maybe_summarize") as maybe:
            self.assertEqual(ui.api("continue", {})["entries"], sample)
            self.assertEqual(ui.api("continue_progress", {"key": ["EPIC-1"]})["done"], 1)
            prog.assert_called_with("EPIC-1")
            self.assertEqual(ui.api("continue_entry", {"key": ["EPIC-1"]}), data)
            maybe.assert_called_once()  # opening a briefing starts the summary, without waiting for it

    def test_refresh_writes_the_summary_now(self):
        with mock.patch.object(B, "summarize", return_value={"error": "no"}) as w:
            self.assertEqual(ui.save("briefing_refresh", {"key": "EPIC-1"}), {"error": "no"})
            w.assert_called_once_with("EPIC-1")

    def test_attach_creates_a_followed_group_and_files_the_session(self):
        self.write(self.SID)
        out = ui.save("briefing_attach", {"id": self.SID, "ticket": "ATO-7"})
        self.assertEqual(out, {"id": self.SID, "folder": "ATO-7", "group": "ATO-7", "ticket": "ATO-7"})
        self.assertEqual(SS.group_info()["ATO-7"]["tickets"], ["ATO-7"])
        row = next(r for r in SS.listing()["sessions"] if r["id"] == self.SID)
        self.assertEqual(row["folder"], "ATO-7")

    def test_attach_reuses_an_existing_group_that_follows_the_ticket(self):
        self.write(self.SID)
        SS.follow_ticket("Billing work", "ATO-7")
        out = ui.save("briefing_attach", {"id": self.SID, "ticket": "ato-7"})
        self.assertEqual(out["group"], "Billing work")
        self.assertEqual(sorted(SS.group_info()), ["Billing work"])  # no second group

    def test_attach_refuses_a_non_ticket(self):
        self.write(self.SID)
        for bad in ("nope", "SHA-256", "", "ATO-7 and more"):
            with self.assertRaises(S.Invalid) as cm:
                ui.save("briefing_attach", {"id": self.SID, "ticket": bad})
            self.assertIn("ticket", str(cm.exception))
        self.assertEqual(SS.group_info(), {})


class ReviewFixesTest(BriefingTest):
    """What the whole-branch review found, each shown failing first."""

    def test_when_github_does_not_say_who_you_are_your_own_prs_are_not_asked_for_review(self):
        self.prs = {"TT-1": pr(11, author="lee"), "TT-2": pr(12, author="lee", ci="fail")}
        out = self.make(me="")
        self.assertEqual([i["kind"] for i in out["needs_you"] if i["kind"] in ("review_pr", "checks")], [])
        self.assertIn("who you are", out["gh_note"])

    def test_a_plain_ticket_whose_prs_could_not_be_read_does_not_say_no_pr(self):
        out = B._progress("TT-5", graph(), {}, ["app has no GitHub remote"])
        self.assertIs(out["pr_known"], False)
        self.assertIsNone(out["finished"])
        known = B._progress("TT-5", graph(), {}, [])
        self.assertTrue(known["pr_known"])
        self.assertIs(known["finished"], False)

    def test_a_failed_background_summary_is_reported_by_the_briefing(self):
        B._ERR.clear()

        def boom(prompt, model):
            raise RuntimeError("no claude")
        B.summarize("EPIC-1", run=boom, data=self.make(), now=NOW)
        self.assertIn("no claude", self.make()["summary_error"])
        B.summarize("EPIC-1", run=lambda p, m: ("ok", 0.0), data=self.make(), now=NOW)
        self.assertIsNone(self.make()["summary_error"])
        B._ERR.clear()

    def test_progress_for_every_entry_shares_one_read_of_the_world(self):
        calls = []
        g, p = graph(), ({}, [])
        dash_ = __import__("lfgcore.dash", fromlist=["dash"])
        dash_._CACHE.pop("briefing-world", None)
        with mock.patch.object(B, "_merged_graph", lambda *a: calls.append("g") or g), \
                mock.patch.object(B, "_prs_by_ticket", lambda: calls.append("p") or p):
            B.progress("EPIC-1")
            B.progress("ATO-9")
            B.progress("TT-5")
        dash_._CACHE.pop("briefing-world", None)
        self.assertEqual(sorted(calls), ["g", "p"])  # each read once, whatever the order

    def test_a_session_in_a_group_that_follows_a_milestone_ticket_is_a_worker(self):
        t = B.tree(graph(), "EPIC-1")
        self.assertEqual(B.role_of(row(folder="G"), t, {"TT-2"}), "worker")
        self.assertEqual(B.role_of(row(folder="G"), t, {"OTHER-1"}), "unsorted")

    def test_a_question_on_a_merged_pr_or_an_old_pass_is_not_waiting_on_you(self):
        old = {"repo": "acme/app", "number": 11, "ticket": "TT-1",
               "passes": [{"n": 1, "questions": [{"id": "q1", "ask": "Old?"}]},
                          {"n": 2, "questions": [{"id": "q1", "ask": "New?", "answer": "yes"}]}]}
        self.prs = {"TT-1": pr(11, author="lee")}
        self.assertEqual([i for i in self.make(records=[old])["needs_you"] if i["kind"] == "question"], [])
        rec = {"repo": "acme/app", "number": 11, "ticket": "TT-1", "passes": [{"n": 1, "questions": [
            {"id": "q1", "ask": "Why?"}]}]}
        self.prs = {"TT-1": pr(11, state="merged_main", author="lee")}
        self.assertEqual([i for i in self.make(records=[rec])["needs_you"] if i["kind"] == "question"], [])

    def test_nothing_is_written_for_a_key_no_session_works_on(self):
        calls = []
        data = self.make("NOPE-1", rows=[])
        out = B.summarize("NOPE-1", run=lambda p, m: calls.append(1) or ("x", 0), data=data, now=NOW)
        self.assertIn("error", out)
        B.maybe_summarize("NOPE-1", run=lambda p, m: calls.append(1) or ("x", 0), data=data, now=NOW,
                          background=False)
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(B.summary_path("NOPE-1")))


class ListPageProgressTest(unittest.TestCase):
    """The list's per-entry progress, run as the real app.js code in Node with fetch stubbed."""

    def run_page(self, setup, wait_ms=400):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        js = open(os.path.join(os.path.dirname(B.__file__), "ui_assets", "app.js")).read()

        def between(a, b):
            i = js.index(a)
            return js[i:js.index(b, i)]

        def line(a):
            i = js.index(a)
            return js[i:js.index("\n", i)]
        src = "\n".join([line("const esc = s =>"), line("const n = v =>"), between("function ago(ts)", "const pct = "),
                         line("const pct = "), line("const plural = "), line("const dot = t =>"),
                         line("const fmtWhy = "), between("function empty(title", "/* table(rows, cols"),
                         line("const labelChip = "), line("const labelChips = "),
                         between("/* wires the label filter bar", "/* \"Starred only\""),
                         between("function wireSessions(root)", "/* Environment: every repo")])
        script = """
const state = { sessions: undefined };   // as on the list page when Sessions was never opened this visit
const els = [{ dataset: { contProgress: "EPIC-1" }, innerHTML: "Reading progress…" },
             { dataset: { contProgress: "ZZZ-77" }, innerHTML: "Reading progress…" }];
const $ = () => null, $$ = sel => (sel === "[data-cont-progress]" ? els : []);
const document = { body: { contains: () => true } };
const PAGES = {}, route = () => {}, softRoute = () => {}, pageTimer = () => {}, isUnlocked = async () => true;
const localStorage = { getItem: () => "" };
%s
%s
setTimeout(() => console.log(JSON.stringify(els.map(e => e.innerHTML))), %d);
try { wireContinue({}); } catch (e) { console.log("THROWN " + e.message); }
""" % (src, setup, wait_ms)
        return subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)

    def test_progress_fills_in_on_the_list_even_when_the_sessions_page_was_never_opened(self):
        r = self.run_page("""
const api = async (v, q) => q.key === "EPIC-1" ? { done: 2, total: 6, milestones: [] } :
  { unavailable: "Progress unavailable: dev-graph has no copy of ZZZ-77" };
""")
        self.assertNotIn("THROWN", r.stdout, r.stdout + r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertIn("2 of 6 tickets done", out[0])
        self.assertIn("dev-graph has no copy of ZZZ-77", out[1])

    def test_a_read_that_never_answers_says_progress_unavailable_with_a_reason(self):
        r = self.run_page("""
CONT_TIMEOUT_MS = 50;
const api = async () => new Promise(() => {});
""", wait_ms=600)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        for html in out:
            self.assertNotIn("Reading progress", html)
            self.assertIn("Progress unavailable", html)
            self.assertIn("took too long", html)

    def test_a_failed_read_says_why(self):
        r = self.run_page("""
const api = async () => { throw new Error("HTTP 500"); };
""")
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(all("HTTP 500" in h and "Reading progress" not in h for h in out), out)

    def test_progress_already_known_stays_on_screen_when_a_refresh_fails(self):
        r = self.run_page("""
els[0].innerHTML = "KNOWN 2 of 6";
els[0].dataset.contHave = "1";
const api = async () => { throw new Error("HTTP 500"); };
""")
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertIn("KNOWN 2 of 6", out[0])
        self.assertIn("could not refresh", out[0])

    def test_a_refreshing_answer_is_asked_again_until_it_settles(self):
        r = self.run_page("""
CONT_RETRY_MS = 10;
let calls = 0;
const api = async (v, q) => {
  calls++;
  return calls < 3 ? { done: 1, total: 6, milestones: [], refreshing: true } : { done: 3, total: 6, milestones: [] };
};
""", wait_ms=500)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertIn("3 of 6 tickets done", out[0])


class StoredProgressTest(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="lfg-test-briefing-prog-")
        p = mock.patch.object(C, "LFG_HOME", home)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(__import__("shutil").rmtree, home, True)
        B._PREFRESH.clear()
        self.calls = []

    def fake(self, key, **kw):
        self.calls.append(key)
        return dict({"done": len(self.calls), "total": 6, "milestones": [], "linear_as_of": "x", "notes": []}, **kw)

    def view(self, key, now, **kw):
        with mock.patch.object(B, "progress", self.fake):
            return B.progress_view(key, now=now, background=False, **kw)

    def test_the_first_read_is_stored_and_a_repeat_visit_answers_from_disk(self):
        first = self.view("EPIC-1", NOW)
        self.assertEqual((first["done"], first["refreshing"]), (1, False))
        again = self.view("EPIC-1", NOW + 30)
        self.assertEqual((again["done"], again["refreshing"], self.calls), (1, False, ["EPIC-1"]))
        self.assertEqual(again["as_of"], first["as_of"])
        self.assertTrue(os.path.exists(B.progress_path()))

    def test_an_old_answer_shows_at_once_and_is_refreshed_behind_it(self):
        self.view("EPIC-1", NOW)
        old = self.view("EPIC-1", NOW + B.PROGRESS_TTL_SECONDS + 5)
        self.assertEqual((old["done"], old["refreshing"]), (1, True))  # the stored one, now
        self.assertEqual(len(self.calls), 2)  # and the refresh ran (in the test, before returning)
        later = self.view("EPIC-1", NOW + B.PROGRESS_TTL_SECONDS + 6)
        self.assertEqual((later["done"], later["refreshing"]), (2, False))

    def test_the_last_progress_survives_a_restart_and_rides_on_the_list(self):
        self.view("EPIC-1", NOW)
        B._PREFRESH.clear()
        dash_ = __import__("lfgcore.dash", fromlist=["dash"])
        dash_._CACHE.clear()  # what a restart does to every in-memory cache
        out = B.entries(NOW, rows=[srow("a", 60, first="for EPIC-1")], graph=graph(), groups={})
        self.assertEqual(out[0]["progress"], None)
        self.assertEqual(out[0]["last_progress"]["done"], 1)
        self.assertTrue(out[0]["last_progress"]["as_of"])

    def test_a_failed_refresh_never_replaces_good_progress_with_unavailable(self):
        self.view("EPIC-1", NOW)
        with mock.patch.object(B, "progress", lambda k: {"unavailable": "Progress unavailable: gh down"}):
            B.progress_view("EPIC-1", now=NOW + 999, background=False)  # shows the old one, refreshes behind it
            out = B.progress_view("EPIC-1", now=NOW + 1000, background=False)
        self.assertEqual(out["done"], 1)
        self.assertIn("gh down", out["refresh_error"])

    def test_nothing_stored_and_unreadable_says_why(self):
        with mock.patch.object(B, "progress", lambda k: {"unavailable": "Progress unavailable: nope"}):
            out = B.progress_view("ATO-77", now=NOW, background=False)
        self.assertIn("nope", out["unavailable"])


class PinnedModelTest(unittest.TestCase):
    ID = "claude-sonnet-5-5"

    def model_for(self, value, present=True):
        models = {"briefing": value} if present else {}
        with mock.patch.object(C, "config", return_value={"models": models}):
            return B.pinned_model()

    def test_sonnet_and_nothing_else_is_ever_used(self):
        self.assertEqual(self.model_for("sonnet"), self.ID)
        self.assertEqual(self.model_for("SONNET "), self.ID)
        self.assertEqual(self.model_for(None, present=False), self.ID)
        for bad in ("", None, "opus", "claude-opus-4-1", "OPUS", "claude-opus-5-5", "fable", "haiku", 7, "a b", "--x"):
            self.assertEqual(self.model_for(bad), self.ID, bad)
        self.assertEqual(self.model_for("claude-sonnet-5-5"), self.ID)
        self.assertEqual(self.model_for("claude-sonnet-4-6"), "claude-sonnet-4-6")  # another Sonnet is Lee's call

    def test_the_command_line_for_the_summary_never_contains_opus(self):
        rows = [srow("orch", 120, name="Plan", first="Plan EPIC-1")]
        data = B.briefing("EPIC-1", rows=rows, graph=graph(), groups={}, prs={}, me="lee", records=[], now=NOW)
        for value in ("opus", "", "sonnet", "claude-opus-4-1"):
            seen = []

            def fake_run(argv, seen=seen, **kw):
                seen.append(argv)
                return mock.Mock(stdout=json.dumps({"result": "ok", "total_cost_usd": 0.01}), stderr="", returncode=0)
            with mock.patch.object(C, "config", return_value={"models": {"briefing": value}}), \
                    mock.patch.object(C, "which", return_value="/x/claude"), \
                    mock.patch.object(B.subprocess, "run", fake_run), \
                    mock.patch.object(B, "_last_messages", lambda s: []):
                B._TRY.clear()
                out = B.summarize("EPIC-1", data=data, now=NOW)
            self.assertEqual(out["text"], "ok")
            argv = seen[0]
            self.assertEqual(argv[argv.index("--model") + 1], self.ID)
            self.assertFalse([a for a in argv if "opus" in str(a).lower()], argv)


class LastDayAndCheckOffTest(ApiTest):
    """The list's "Last 24 hours" rows and the Done check-off. Real sessions.listing on transcripts in a temp folder."""

    def write_aged(self, n, hours, branch="main", prompt="hello there"):
        sid = "%08d-0000-0000-0000-000000000000" % n
        self.write(sid, branch=branch, prompt=prompt)
        path = os.path.join(self.projects, "-nowhere-app", sid + ".jsonl")
        t = time.time() - hours * 3600
        os.utime(path, (t, t))
        return sid

    def recent(self, **kw):
        return B.listing(graph=graph(), groups=kw.pop("groups", None) or {}, **kw)

    def test_every_session_of_the_last_24_hours_shows_newest_first_even_with_no_ticket_or_group(self):
        a = self.write_aged(1, 23.5)
        b = self.write_aged(2, 1, prompt="no ticket at all")
        c = self.write_aged(3, 24.5)  # just outside
        out = self.recent()["recent"]
        self.assertEqual([r["id"] for r in out], [b, a])
        self.assertNotIn(c, [r["id"] for r in out])
        self.assertEqual(out[0]["activity"], "idle")
        self.assertEqual(out[0]["ticket"], "")

    def test_a_session_already_under_an_entry_is_listed_here_too(self):
        a = self.write_aged(1, 2, branch="lee/tt-1-build")
        out = self.recent()
        self.assertEqual([r["id"] for r in out["recent"]], [a])
        self.assertEqual(out["recent"][0]["ticket"], "TT-1")
        self.assertEqual([e["key"] for e in out["entries"]], ["EPIC-1"])

    def test_hidden_sessions_are_left_out(self):
        a, b = self.write_aged(1, 2), self.write_aged(2, 3)
        SS.hide([a])
        self.assertEqual([r["id"] for r in self.recent()["recent"]], [b])

    def test_a_session_checked_off_stops_showing_and_comes_back_on_new_activity(self):
        a = self.write_aged(1, 5)
        now = time.time()
        B.set_done(a, True, now=now)
        out = self.recent()
        self.assertEqual(out["recent"], [])
        self.assertEqual([x["key"] for x in out["checked"]], [a])
        path = os.path.join(self.projects, "-nowhere-app", a + ".jsonl")
        os.utime(path, (now + 60, now + 60))  # the transcript changed after it was checked
        out = self.recent()
        self.assertEqual([r["id"] for r in out["recent"]], [a])
        self.assertEqual(out["checked"], [])

    def test_undo_brings_a_checked_session_back(self):
        a = self.write_aged(1, 5)
        B.set_done(a, True)
        self.assertEqual(self.recent()["recent"], [])
        B.set_done(a, False)
        self.assertEqual([r["id"] for r in self.recent()["recent"]], [a])
        self.assertEqual(C.read_json(B.done_path()), {})

    def entry_rows(self):
        return [srow("orch", 120, first="Plan EPIC-1")]

    def test_an_entry_checked_off_stops_showing_and_comes_back_when_it_has_new_activity(self):
        rows = self.entry_rows()
        B.set_done("EPIC-1", True, now=NOW)
        out = B.listing(NOW, rows=rows, graph=graph(), groups={})
        self.assertEqual([e["key"] for e in out["entries"]], [])
        self.assertEqual([x["key"] for x in out["checked"] if x["type"] == "entry"], ["EPIC-1"])
        newer = [srow("orch", 120, first="Plan EPIC-1"), srow("w", -60, branch="lee/tt-1-x")]  # a minute after
        out = B.listing(NOW, rows=newer, graph=graph(), groups={})
        self.assertEqual([e["key"] for e in out["entries"]], ["EPIC-1"])
        self.assertEqual(out["checked"], [])

    def test_undo_brings_an_entry_back(self):
        B.set_done("EPIC-1", True, now=NOW)
        B.set_done("EPIC-1", False)
        out = B.listing(NOW, rows=self.entry_rows(), graph=graph(), groups={})
        self.assertEqual([e["key"] for e in out["entries"]], ["EPIC-1"])

    def test_the_unsorted_entry_can_be_checked_off_too(self):
        rows = [srow("a", 60, first="what is this")]
        B.set_done("unsorted", True, now=NOW)
        self.assertEqual(B.listing(NOW, rows=rows, graph=graph(), groups={})["entries"], [])

    def test_the_checked_off_marks_are_one_small_file_and_a_bad_key_is_refused(self):
        B.set_done("EPIC-1", True)
        self.assertEqual(list(C.read_json(B.done_path())), ["EPIC-1"])
        self.assertTrue(B.done_path().startswith(C.lfg_path("state", "briefings")))
        for bad in ("", "../x", "a b", "x" * 200):
            with self.assertRaises(ValueError):
                B.set_done(bad, True)

    def test_the_view_and_the_save_action(self):
        a = self.write_aged(1, 5)
        self.assertEqual([r["id"] for r in ui.api("continue", {})["recent"]], [a])
        self.assertEqual(ui.save("briefing_done", {"key": a, "on": True})["key"], a)
        self.assertEqual(ui.api("continue", {})["recent"], [])
        self.assertEqual([x["key"] for x in ui.api("continue", {})["checked"]], [a])
        with self.assertRaises(S.Invalid):
            ui.save("briefing_done", {"key": "../x", "on": True})
        ui.save("briefing_done", {"key": a, "on": False})
        self.assertEqual(len(ui.api("continue", {})["recent"]), 1)


class ListRowsPageTest(unittest.TestCase):
    """The list's rows (Last 24 hours, Done boxes, checked off), as the real app.js code in Node."""

    run_page = ListPageProgressTest.run_page

    def test_the_list_has_a_last_24_hours_section_with_a_done_box_on_every_row(self):
        r = self.run_page("""
const api = async () => ({});
const D = { active_days: 14,
  entries: [{ key: "EPIC-1", title: "The epic", kind: "epic", repos: ["app"], last_active: "2026-11-10T09:00:00",
              sessions: { working: 1, idle: 0, unsorted: 0 } }],
  recent: [
    { id: "s1", name: "Fix login", ticket: "ATO-1", folder: "", activity: "working", repo: "app",
      modified: "2026-11-10T09:00:00" },
    { id: "s2", name: "Just a chat", ticket: "", folder: "My group", activity: "idle", repo: "api",
      modified: "2026-11-10T08:00:00" }],
  checked: [
    { type: "entry", key: "ATO-3", title: "Old epic", at: "2026-11-09T09:00:00" },
    { type: "session", key: "s9", title: "Old chat", at: "2026-11-09T09:00:00" }] };
console.log("HTML1 " + JSON.stringify(contList(D)));
state.contChecked = true;
console.log("HTML2 " + JSON.stringify(contList(D)));
console.log("HTML3 " + JSON.stringify(contList({ active_days: 14, entries: [], recent: [], checked: [] })));
""", wait_ms=10)
        self.assertNotIn("THROWN", r.stdout, r.stdout + r.stderr)
        got = {ln[:5]: json.loads(ln[6:]) for ln in r.stdout.splitlines() if ln.startswith("HTML")}
        one, two, three = got["HTML1"], got["HTML2"], got["HTML3"]
        self.assertLess(one.index("Last 24 hours"), one.index("Epics and tickets"))  # the day section is on top
        for want in ("Fix login", "Just a chat", "ATO-1", "My group", "working now", "idle", 'data-cont-open="s1"',
                     'data-cont-open="s2"', "The epic"):
            self.assertIn(want, one)
        self.assertEqual(one.count("data-cont-done="), 3)  # two sessions and the entry
        self.assertIn('data-cont-done="EPIC-1"', one)
        self.assertIn("Show 2 checked off", one)
        self.assertNotIn("data-cont-undo", one)
        self.assertIn("Hide 2 checked off", two)
        self.assertEqual(two.count("data-cont-undo="), 2)
        self.assertIn("No session was touched in the last 24 hours", three)
        self.assertNotIn("checked off", three)


if __name__ == "__main__":
    unittest.main()
