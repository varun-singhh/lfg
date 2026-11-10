# "Where you left off" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in one session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dashboard page that lists what Lee was last working on (epics, milestones, big tickets) with real progress, and opens a briefing for each: who is working on what, what needs him, and an automatic written summary.

**Architecture:** A new module `plugin/lib/lfgcore/briefing.py` joins three things LFG already has: dev-graph's copy of Linear (`stacks._graph`, `stacks.epic_items`), every session's ticket (`sessions.listing`), and review records. `ui.py` exposes it as two read views and two save actions. `app.js` adds one page. The written summary is the only model call; it reuses the `claude -p` pattern in `review.py`, runs in the background, and is cached under `~/.lfg/state/briefings/`.

**Tech Stack:** Python 3 standard library, `unittest`, vanilla JS in `plugin/lib/lfgcore/ui_assets/app.js`.

**Spec:** `docs/superpowers/specs/2026-11-10-where-you-left-off-design.md` (read it first; every decision is in it)

## Global Constraints

- Work only in the existing worktree `/Users/leek/code/lfg.worktrees/where-you-left-off` (branch `where-you-left-off`, off `origin/main`). Never touch `/Users/leek/code/lfg`.
- Never writes to Linear. Reads dev-graph, local files and `gh` only.
- Opening the list or a briefing never waits on a model call. The summary is generated in the background, at most once per 10 minutes per entry, only when the briefing is opened and its key changed.
- Constants (named at the top of `briefing.py`): `ACTIVE_DAYS = 14`, `MAX_ENTRIES = 30`, `DONE_DROP_DAYS = 3`, `WORKING_MINUTES = 10`, `IDLE_PR_MINUTES = 60`, `SUMMARY_MIN_GAP_MINUTES = 10`.
- Orchestrator rule order: in a group that follows the epic's ticket; names the epic's ticket (branch, title or first message); names 3 or more of the epic's tickets. Otherwise a session that names a ticket of the epic is a worker; otherwise Unsorted. Orchestrator wins over worker. Never guess.
- Milestone = a child ticket of the epic that has children of its own (dev-graph kind `parent`). Progress counts leaf tickets (done of total).
- "Done" is `stacks.epic_items`' meaning: Linear status terminal, or its PR merged into main.
- Own placement always beats a follow rule (project 1's `file_into`, `follow_ticket`, `placements`).
- Tests never touch the real `~/.claude` or `~/.lfg`: patch `C.HOME`, `LFG_HOME` and path constants like the existing sessions tests do.
- Commit steps run only when Lee has asked for commits this session; push right after each commit; never amend; no Claude attribution lines.
- No version bump. Before the PR: `python3 -m unittest discover -s tests`, `uvx ruff check plugin/lib plugin/bin/lfg tests`, `plugin/bin/lfg doctor --selftest`, `node --check plugin/lib/lfgcore/ui_assets/app.js`.

## Review Focus

- A session that names no ticket and is in no group: shows under Unsorted, never dropped, never attached to the wrong epic.
- Linear not mirrored or a repo with no GitHub remote: the entry still lists, with "progress unavailable" and a reason; no exception.
- An epic with no children (a plain ticket): shows its PR state, not "0 of 0".
- A session naming a ticket of the epic and also the epic itself: orchestrator, not worker.
- The same ticket id seen from two repos: counted once.
- A summary call that fails or times out: the last stored summary stays, the page still loads, the error is shown next to Refresh.
- A transcript that is huge or unreadable: skipped for that session, never crashes the list.

---

### Task 1: Resolve sessions to epics and read the epic tree

**Files:**
- Create: `plugin/lib/lfgcore/briefing.py`
- Test: `tests/test_briefing.py` (new; model the setUp on the `sessions` test class in `tests/test_core.py` that patches `C.HOME`)

**Interfaces:**
- Consumes: `stacks._graph(rid) -> {"issues", "groups", "blocks"}`, `stacks.epic_for(rid, ticket)`, `sessions.listing(hidden=False, scripted=True) -> {"sessions": [rows with id, ticket, repo, root, folder, modified]}`, `sessions.prefs()["group_tickets"]`.
- Produces (all in `briefing.py`):
  - `tree(graph: dict, epic: str) -> {"key", "title", "milestones": [{"key", "title", "leaves": [key]}], "loose": [key]}`: epic, milestones, and leaf tickets, two levels deep.
  - `role_of(row: dict, epic_tree: dict, followed: set[str]) -> "orchestrator" | "worker" | "unsorted"`, applying the rule order in Global Constraints. `row` needs `ticket`, `folder`, and the text fields the session summary already carries (`branch`, `title`, `first`).
  - `tickets_in(row: dict) -> set[str]`: every ticket id in the session's branch, title and first message (use `sessions.TICKET`, drop `sessions.NOT_TICKETS`).

- [ ] **Step 1: Write the failing tests:** `test_orchestrator_by_group_by_naming_and_by_three_children` (each rule alone), `test_worker_when_it_names_one_child`, `test_unsorted_when_nothing_matches`, `test_orchestrator_wins_over_worker`, `test_tree_two_levels_with_loose_leaves` using a hand-built graph dict.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_briefing -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the three functions. Pure functions over dicts; no I/O.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** (only if asked): `git add plugin/lib/lfgcore/briefing.py tests/test_briefing.py && git commit -m "Briefing: resolve sessions to an epic's orchestrator and workers"`.

### Task 2: The entry list, progress and activity

**Files:** Modify `plugin/lib/lfgcore/briefing.py`; test in `tests/test_briefing.py`.

**Interfaces:**
- Consumes: Task 1; `stacks.epic_items(issues, blocks, stacks, rows, default, runs, here)`, `stacks._pr_rows(gh_repo)`.
- Produces:
  - `entries(now: float | None = None) -> list[dict]`: `{"key", "title", "kind": "epic"|"ticket", "repos", "last_active", "sessions": {"working", "idle", "unsorted"}, "progress": None}`, built from local files only, newest activity first, capped at `MAX_ENTRIES`, applying `ACTIVE_DAYS` and `DONE_DROP_DAYS` (a done epic drops after 3 quiet days).
  - `progress(key: str) -> {"done", "total", "milestones": [{"key", "title", "done", "total"}], "linear_as_of": str, "unavailable": str}`: `unavailable` is a plain-words reason when it cannot be read; counts are then absent. Cached 2 minutes (`dash.cached`).
  - `activity(row) -> "working" | "idle"`: running in Studio now (`claudesess._LIVE`) or transcript changed within `WORKING_MINUTES`.

- [ ] **Step 1: Write the failing tests:** `test_entries_newest_first_and_capped`, `test_old_sessions_do_not_make_an_entry`, `test_a_finished_epic_drops_after_three_quiet_days`, `test_progress_counts_leaf_tickets_once_across_repos`, `test_progress_unavailable_says_why`, `test_plain_ticket_with_no_children_is_kind_ticket`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** `entries()` must not call `gh` or dev-graph (they are for `progress`).
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Commit** (only if asked): `git commit -m "Briefing: the entry list and real progress"`.

### Task 3: A briefing's contents and "Needs you"

**Files:** Modify `briefing.py`; test in `tests/test_briefing.py`.

**Interfaces:**
- Consumes: Tasks 1 and 2; the review records (`review.py` readers used by the PR reviews page for `reviews/<owner>__<repo>/<n>.json`); `gh.me` as the review page obtains it.
- Produces: `briefing(key: str) -> dict`: `{"entry", "progress", "orchestrator": row|None, "milestones": [{"key", "title", "done", "total", "sessions": [row with role, activity]}], "unsorted": [row], "needs_you": [{"kind": "review_pr"|"question"|"checks"|"idle_pr", "text", "target": "#prs/owner/repo/n" | "#studio/<id>" | ...}], "summary": None | {"text", "at", "cost", "stale": bool}}`.
- Needs-you rules exactly as the spec's four bullets (a to d); each item's `text` is one plain sentence about what a person would do.

- [ ] **Step 1: Write the failing tests:** one per needs-you kind plus `test_no_needs_you_when_nothing_is_waiting`, `test_orchestrator_is_on_top_not_in_a_milestone`, `test_unsorted_sessions_listed_not_dropped`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** `gh` data is read through helpers the code already has (`stacks._pr_rows`); when `gh` is unavailable, skip rules a, c and d and say so in the entry, don't raise.
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Commit** (only if asked): `git commit -m "Briefing: contents and what needs you"`.

### Task 4: The written summary

**Files:** Modify `briefing.py`, `plugin/lib/lfgcore/common.py` (add `"briefing"` to `DEFAULT_CONFIG["models"]`, next to the other per-job models), `plugin/lib/lfgcore/settings.py` only if its model list needs the new key to show in Settings; test in `tests/test_briefing.py`.

**Interfaces:**
- Produces:
  - `summary_key(key: str) -> str`: the newest transcript time under the entry plus counts of sessions and done tickets.
  - `summary_path(key: str) -> str`: `~/.lfg/state/briefings/<KEY>.json` (via `C.lfg_path`).
  - `summarize(key: str, run=None) -> dict`: builds the prompt from the orchestrator's last messages and the briefing's facts, runs `claude -p` with `--model` from `models.briefing` (inject `run` in tests, like the review code does), stores `{"text", "at", "cost", "key"}`; on failure keeps the old file and returns `{"error": "<plain reason>"}`.
  - `maybe_summarize(key: str) -> None`: starts `summarize` in a background thread only if the stored key differs and the last run was over `SUMMARY_MIN_GAP_MINUTES` ago; never blocks.

- [ ] **Step 1: Write the failing tests** with a fake `run`: `test_summary_stored_with_time_and_key`, `test_a_failed_call_keeps_the_last_summary`, `test_not_regenerated_within_ten_minutes`, `test_not_regenerated_when_the_key_is_unchanged`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Reuse the call shape and `C.CLAUDE_BARE` flags from `review.py` (around line 176). The prompt tells Claude to write 2 to 4 plain sentences about where the work stopped and what is next, from the given facts only.
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Commit** (only if asked): `git commit -m "Briefing: automatic written summary, cached"`.

### Task 5: API views and actions

**Files:** Modify `plugin/lib/lfgcore/ui.py` (the view dispatch near line 404 and the `save()` actions near line 617); test in `tests/test_briefing.py`.

**Interfaces:**
- Produces: read views `continue` (the `entries()` list) and `continue_entry` (`briefing(key)` for `?key=`, also calls `maybe_summarize(key)`); a view `continue_progress` (`progress(key)` for `?key=`) so the list can fill progress per entry; save actions `briefing_refresh {key}` (runs `summarize` now, returns the result) and `briefing_attach {id, ticket}` (the "This belongs to..." click: find or create a group named after the ticket, `follow_ticket(group, ticket)`, then `file_into(id, group)`; refuses a non-ticket with `S.Invalid`).

- [ ] **Step 1: Write the failing tests:** `test_views_return_the_documented_shape`, `test_attach_creates_a_followed_group_and_files_the_session`, `test_attach_refuses_a_non_ticket`, `test_attach_reuses_an_existing_group_that_follows_the_ticket`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** by following how the `studio` view and the `group_pr` action are wired.
- [ ] **Step 4: Run** them, then the whole suite. Expected: PASS.
- [ ] **Step 5: Commit** (only if asked): `git commit -m "Briefing: API views and the attach action"`.

### Task 6: The page

**Files:** Modify `plugin/lib/lfgcore/ui_assets/app.js` (the `NAV` list near line 1489: add `["continue", "Where you left off"]` in Your work; a new `PAGES.continue`; reuse the session row handlers from the Sessions page), `plugin/lib/lfgcore/ui_assets/app.css`.

**Interfaces:** Consumes Task 5's views and actions. The design reference is the clickable mockup `briefing-interactive.html` in `/private/tmp/claude-501/-Users-leek-code-lfg/3269eed7-2821-401f-83dd-7a9d9900b9a7/scratchpad/brainstorm/.superpowers/brainstorm/65674-1794336252/content/`; use the dashboard's own classes and colours, not the mockup's.

- [ ] **Step 1:** `#continue`: the list. Each entry shows title, kind, last activity, session counts, and a progress bar that fills in after the list renders (`continue_progress` per entry; "progress unavailable" with the reason when it says so). Empty state: plain words saying nothing was touched in 14 days.
- [ ] **Step 2:** `#continue/<key>`: the briefing: header with ring and chips, the "written automatically" summary with its age and a Refresh button (shows the error if the last run failed), "Needs you" with a button per item that goes to its target, milestones (open by default when they have a working or needs-you session) with session rows, the orchestrator on top, an Unsorted block with "This belongs to..." (a small drawer listing recent tickets).
- [ ] **Step 3:** A session detail panel on the right with what it was for, where it stopped, what it changed and the existing actions (Copy resume command, What it changed, Run a skill, Rules, Remind it of my style, Rename, Add to a group, Labels, Hide, Delete, Star), reusing the Sessions page's handlers (`wireGroupsAndLabels` and the `data-sess-*` handlers), not new copies.
- [ ] **Step 4: Verify:** `node --check`; render the page in Node on a sample (an epic with two milestones, one orchestrator, two workers, one unsorted, one needs-you item, a summary and one with progress unavailable) and check each of those appears; light and dark use only theme variables. Say in the PR if no browser pass was done.
- [ ] **Step 5: Commit** (only if asked): `git commit -m "Where you left off: the page"`.

### Task 7: Notes, contract and full checks

**Files:** Create `changes/where-you-left-off.json` (via `plugin/bin/lfg release note where-you-left-off --added "..." --whats-new "<title>" "<plain words>" --page continue`); modify `CONTRACT.md` (the views, the two actions, `state/briefings/<KEY>.json`, `models.briefing`), `docs/dashboard.md` (a "Where you left off" row).

- [ ] **Step 1:** Write the release note and docs. Do not bump the version.
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests`, `uvx ruff check plugin/lib plugin/bin/lfg tests`, `plugin/bin/lfg doctor --selftest`, `node --check plugin/lib/lfgcore/ui_assets/app.js`. Expected: all pass.
- [ ] **Step 3:** Report to the design session; do not commit or open a PR until Lee says so.

## Self-review

- **Spec coverage:** page and list (T2, T6), briefing and panel (T3, T6), real progress and milestones (T1, T2), orchestrator rules and Unsorted (T1, T3), needs-you (T3), working/idle (T2), entry window (T2), written summary and cost (T4), attach click (T5), notes and docs (T7).
- **Types:** `tree`, `role_of`, `tickets_in`, `entries`, `progress`, `briefing`, `summarize`, `maybe_summarize` and the four view and action names are spelled the same wherever used.
- **Not here:** the studio and session merge (project 4); tabs (project 3).
