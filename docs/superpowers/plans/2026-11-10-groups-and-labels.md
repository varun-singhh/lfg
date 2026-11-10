# Nested groups and labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let studios and sessions sit in nested groups and carry labels, with groups that can follow tickets, in both the Sessions page and Studio's list.

**Architecture:** All state stays in `~/.lfg/state/sessions.json`, read and written only through `sessions.py` (`prefs()`, `_save_prefs()`), keyed by Claude Code session id, which Studio and Sessions already share. `sessions.py` gets group and label functions plus one function, `placements()`, that decides every session's group (manual, then PR-following, then ticket-following). `ui.py` exposes them as `save()` actions. `app.js` nests the groups and shows labels on both lists.

**Tech Stack:** Python 3 standard library, `unittest`, vanilla JS in `plugin/lib/lfgcore/ui_assets/app.js`.

**Spec:** `docs/superpowers/specs/2026-11-10-groups-and-labels-design.md`

## Global Constraints

- Work in its own worktree and branch off `origin/main`: `lfg worktree new groups-and-labels --from origin/main`. Copy the spec and this plan into that worktree's `docs/superpowers/`; they are uncommitted in the main checkout.
- Old `sessions.json` files read unchanged: every new key is optional and empty by default.
- Group names: global across all repos, unique, 2 to 80 characters (`_group_name` and the existing "at least 2 characters" rule).
- Groups and labels are LFG-only; nothing on disk moves and `/resume` is unchanged.
- A session sits in at most one group. Manual placement and "taken out" (`left_out`) always beat follow rules.
- Ticket following matches only the session's branch, title and first message, using `TICKET` and `NOT_TICKETS` from `sessions.py`.
- Auto-match tie-break: deepest group first, then first by name.
- Labels are case-insensitive, 1 to 30 characters, from a fixed colour set; the dashboard's status colours (gray, green, yellow, red, blue, purple, pink, orange).
- Label filter with several labels means all of them; a group shows if anything under it matches, and its count follows the filter.
- Tests never touch the real `~/.claude` or `~/.lfg`; follow the existing `setUp` in the `test_core.py` class that holds `test_names_and_folders_are_yours_and_reversible` (it already patches the paths).
- Before any PR: `python3 -m unittest discover -s tests`, `uvx ruff check plugin/lib plugin/bin/lfg tests`, `plugin/bin/lfg doctor --selftest`, `node --check plugin/lib/lfgcore/ui_assets/app.js`.
- Commit steps run only when Lee has asked for commits this session (his rule); push right after each commit, never amend. Otherwise leave the work uncommitted and say so.
- Do not bump the version in `plugin/.claude-plugin/plugin.json`.

## Review Focus

- Renaming a group to a name another group already has: refused, nothing changes.
- Moving a group under itself or under one of its own descendants: refused, in one step and through a chain.
- Deleting a group that has sessions and child groups: nothing is hidden or lost; its sessions and child groups go to its parent, or to Unsorted if it has none.
- A `sessions.json` written before this change (only the old keys): loads, lists and saves without error.
- A label typed as `Needs Review`, `needs review` and ` needs  review `: one label.
- A session id that no longer exists (transcript deleted) still has entries in `labels` or `folders`: listing ignores it and nothing crashes; `trash()` also drops its labels.

---

### Task 1: Group registry, nesting and group actions

**Files:**
- Modify: `plugin/lib/lfgcore/sessions.py` (`prefs()` at line 33, `group_names()` at 253, `file_into()` at 479, `follow_pr()` at 439)
- Test: `tests/test_core.py` (the class containing `test_names_and_folders_are_yours_and_reversible`)

**Interfaces:**
- Produces (all in `sessions.py`):
  - `prefs()` returns the old keys plus `"groups": list[str]`, `"group_parent": dict[str, str]`, `"group_tickets": dict[str, list[str]]`, `"labels": dict[str, list[str]]`, `"label_colors": dict[str, str]`.
  - `group_names() -> list[str]`: every group that exists (in `groups`, or has a member, a child, a followed PR or a followed ticket).
  - `group_info() -> dict[str, dict]`: `{name: {"parent": str, "prs": list, "tickets": list}}` for every group in `group_names()`.
  - `make_group(name: str, parent: str = "") -> dict`: creates it in `groups`; returns `{"group": name, "parent": parent}`.
  - `rename_group(old: str, new: str) -> dict`: moves the name in `groups`, `folders`, `group_prs`, `group_tickets`, `left_out`, and in `group_parent` as key and as value. Raises `ValueError` if `new` exists or `old` does not.
  - `move_group(name: str, parent: str) -> dict`: empty `parent` makes it top level. Raises `ValueError` on a cycle or an unknown group.
  - `delete_group(name: str) -> dict`: members and child groups go to its parent (or Unsorted / top level); removes it from every map.
- Changes: `file_into()` must not drop a group from existence when it empties, if the group is in `groups`; and it must add a newly named group to `groups`.

- [ ] **Step 1: Write the failing tests** in the class named above:
  - `test_groups_nest_and_survive_being_empty`: `make_group("Epic")`, `make_group("M1", parent="Epic")`; `group_info()["M1"]["parent"] == "Epic"`; `"Epic" in group_names()` with no sessions; file a session into `"M1"` then out with `file_into(sid, "")`; `"M1" in group_names()` still.
  - `test_group_cycles_and_name_clashes_are_refused`: `move_group("Epic", "M1")` raises `ValueError`; a three-deep chain too; `rename_group("M1", "Epic")` raises `ValueError`; `group_info()` unchanged afterwards.
  - `test_renaming_a_group_moves_it_everywhere`: a group with a session, a followed PR (`follow_pr`), a child; after `rename_group` the session's `listing()` row has `folder == new`, `group_prs` has the new key only, the child's `parent == new`.
  - `test_deleting_a_group_moves_its_contents_up`: `Epic > M1 > session`; `delete_group("M1")`; session's folder is `"Epic"`; `delete_group("Epic")`; session's folder is `""` and still listed.
  - `test_an_old_sessions_file_still_loads`: write `{"names": {}, "folders": {"Q4": [sid]}}` to `_prefs_path()`; `listing()` works, `prefs()["group_parent"] == {}`.
  - Update `test_names_and_folders_are_yours_and_reversible`: its expected `prefs()` dict gains the five new empty keys.

- [ ] **Step 2: Run** `python3 -m unittest tests.test_core -k groups -v` and the updated test. Expected: new tests FAIL (names not defined), the updated one FAILS on the dict.

- [ ] **Step 3: Implement** the signatures above in `sessions.py`. Reuse `_group_name()` for normalising. Cycle check: walk `group_parent` up from the proposed parent; refuse if it meets `name`. `group_names()` becomes the union of the six sources named above.

- [ ] **Step 4: Run** the same tests, then the whole `test_core` module. Expected: PASS.

- [ ] **Step 5: Commit** (only if asked): `git add plugin/lib/lfgcore/sessions.py tests/test_core.py && git commit -m "Groups can hold groups and exist empty"`.

### Task 2: Placements, ticket following and who wins

**Files:**
- Modify: `plugin/lib/lfgcore/sessions.py` (`listing()` at 259: its `folder_of` and `auto` lines; `_following()` at 220)
- Test: same class in `tests/test_core.py`

**Interfaces:**
- Consumes: Task 1's `group_info()`, `prefs()`.
- Produces:
  - `follow_ticket(group: str, ticket: str, on: bool = True) -> dict`: returns `{"group", "tickets"}`; raises `ValueError` unless `TICKET` matches the whole string. Mirrors `follow_pr`, including clearing `left_out[group]` only when the group follows nothing at all.
  - `placements() -> dict[str, dict]`: `{session id: {"folder": str, "via": "" | "pr" | "ticket"}}`, for every session that has a group. Order of precedence: manual `folders`; sessions in `left_out[g]` are skipped for `g`; then PR-following (existing `_following`); then ticket-following. Among several matching ticket groups, deepest first (count `group_parent` hops), then name order.
  - `listing()` rows gain `"via_ticket": bool`; `via_pr` stays; both come from `placements()`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_group_following_a_ticket_gathers_matching_sessions`: sessions with branch `lee/ato-7-x` (write helper's second positional args are cwd, branch, first prompt), one naming `ATO-7` only in the first message, one naming it only late in the transcript, one unrelated. `follow_ticket("M1", "ATO-7")` puts the first two in, not the late one, not the unrelated; rows have `via_ticket` true.
  - `test_manual_placement_beats_following`: a matching session filed by hand into another group stays there; a matching session taken out with `file_into(sid, "", came_from="M1")` stays out.
  - `test_deepest_ticket_group_wins`: `Epic` and its child `M1` both follow `ATO-7`; the session's folder is `"M1"`.
  - `test_follow_ticket_refuses_a_non_ticket`: `follow_ticket("M1", "hello")` raises `ValueError`.

- [ ] **Step 2: Run** them. Expected: FAIL (`follow_ticket` not defined).

- [ ] **Step 3: Implement** `follow_ticket`, a helper `_tickets_in(*texts) -> set[str]` (uses `TICKET`, drops `NOT_TICKETS`) and `placements()`. Make `listing()` use `placements()` instead of its own `folder_of`/`auto`; keep the script-session rule that shows a `claude -p` session when it joined a group.

- [ ] **Step 4: Run** the new tests and the existing `test_a_group_following_a_pr_gathers_its_sessions_and_review_runs`. Expected: PASS.

- [ ] **Step 5: Commit** (only if asked): `git commit -m "Groups can follow tickets; manual placement always wins"`.

### Task 3: Labels

**Files:**
- Modify: `plugin/lib/lfgcore/sessions.py` (`listing()`, `trash()` at ~700)
- Test: same class

**Interfaces:**
- Produces:
  - `LABEL_COLORS = ("gray", "green", "yellow", "red", "blue", "purple", "pink", "orange")`.
  - `set_labels(sid: str, names: list[str]) -> dict`: normalises each name (collapse spaces, lower-case for identity, keep the first spelling typed as display), 1 to 30 characters, no duplicates; returns `{"id", "labels"}`. A name seen for the first time gets the next unused colour from `LABEL_COLORS`.
  - `label_list() -> list[dict]`: `[{"name", "color", "count"}]`, counting only sessions that exist.
  - `edit_label(name: str, new_name: str = "", color: str = "") -> dict`: rename (merges into an existing label of that name) and/or recolour. Raises `ValueError` for an unknown name or colour.
  - `delete_label(name: str) -> dict`: removes it from every session and from `label_colors`.
  - `listing()` rows gain `"labels": list[{"name", "color"}]`; the response gains `"label_list"`.

- [ ] **Step 1: Write the failing tests:** `test_labels_are_case_insensitive_and_coloured` (the three spellings in Review Focus give one label with one colour); `test_label_rename_merges_and_delete_removes`; `test_labels_on_a_deleted_session_are_ignored` (delete the transcript file; `listing()` and `label_list()` don't count or crash); `test_trashing_a_session_drops_its_labels`.

- [ ] **Step 2: Run** them. Expected: FAIL.

- [ ] **Step 3: Implement** the signatures. A label is stored as `labels[sid] = [display names]`; identity is `name.lower()`. Colours live in `label_colors` keyed by lower-case name. When the last item loses a label, drop its colour unless the label was created through `edit_label` (keep a marker in `label_colors`; simplest: store colours for manager-created labels under the same map and prune only those with no items and no `created` flag kept in a `label_created` list in `prefs()`).

- [ ] **Step 4: Run** the new tests. Expected: PASS.

- [ ] **Step 5: Commit** (only if asked): `git commit -m "Labels with colours for sessions and studios"`.

### Task 4: Dashboard actions and Studio's list data

**Files:**
- Modify: `plugin/lib/lfgcore/ui.py` (the `session_*` branch at ~617), `plugin/lib/lfgcore/claudesess.py` (`listing()` at 426)
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces, as `ui.save(what, body)` actions (each raises `S.Invalid` on `ValueError`, like the others): `group_make {name, parent}`, `group_rename {old, new}`, `group_move {name, parent}`, `group_delete {name}`, `group_ticket {group, ticket, on}`, `session_labels {id, labels}`, `label_edit {name, new_name, color}`, `label_delete {name}`.
- `claudesess.listing(rid, root)` rows gain `"folder"`, `"via"`, `"labels"` from `SS.placements()` and `SS.prefs()`; the response gains `"group_info"` (`SS.group_info()`) and `"label_list"`.

- [ ] **Step 1: Write the failing tests:** `test_group_actions_go_through_save` (each action once, including an invalid one that raises `S.Invalid`); `test_studio_listing_carries_group_and_labels` (a studio-listed session filed into a group and labelled shows both in `claudesess.listing`).

- [ ] **Step 2: Run** them. Expected: FAIL.

- [ ] **Step 3: Implement** the actions by adding their names to the tuple at `ui.py:617` and one branch each, following the `group_pr` branch; add the three fields to `claudesess.listing` rows.

- [ ] **Step 4: Run** the new tests. Expected: PASS.

- [ ] **Step 5: Commit** (only if asked): `git commit -m "Dashboard actions for groups and labels; Studio's list carries them"`.

### Task 5: Sessions page, nested groups, label chips and filter

**Files:**
- Modify: `plugin/lib/lfgcore/ui_assets/app.js` (the Sessions renderer around lines 2810 to 2870, `setGroup`/`ask` around 3010 to 3040, and the `[data-sess-folder]` handlers near 3130)
- Docs: `docs/dashboard.md` (Sessions row)

**Interfaces:**
- Consumes: the `listing` response from Task 2/3 (`sessions[].folder`, `.via_pr`, `.via_ticket`, `.labels`, `group_info`, `label_list`) and Task 4's actions.
- Produces: a shared helper `groupTree(rows, info, filter) -> [{name, count, rows, children}]` in `app.js`, used by Task 6 as well. Counts include nested rows and follow the label filter; a group with no matching row anywhere under it is omitted when a filter is on.

- [ ] **Step 1:** Add `groupTree` next to the Sessions renderer, and render Sessions' groups from it: nested `<details>` with indentation, a count per group, label chips on each row, "Unsorted" for rows with no group (today's ungrouped rows in "Your groups" and the repo sections stay as they are for ungrouped sessions by repo).
- [ ] **Step 2:** Replace the "Put this session in a group" drawer with one that also offers "New group" under a chosen parent, plus a "Labels…" drawer (type to add, click to remove, colour dots, existing labels as suggestions). Add a group manager drawer opened from a group header: rename, move under another group, follow a ticket, delete (with a plain sentence about what moves up).
- [ ] **Step 3:** Add the label filter (chips, narrowing) beside the existing search box and starred toggle.
- [ ] **Step 4: Verify:** `node --check plugin/lib/lfgcore/ui_assets/app.js`; then run the dashboard (`lfg ui`) and, in a browser, create `Epic > M1`, file one studio and one terminal session into `M1`, label one, filter by the label, delete `M1`. Say in the PR if the browser pass was not done.
- [ ] **Step 5: Commit** (only if asked): `git commit -m "Sessions page: nested groups, labels and a label filter"`.

### Task 6: Studio's list, group view and row actions

**Files:**
- Modify: `plugin/lib/lfgcore/ui_assets/app.js` (Studio list renderer around line 5800 to 5830: the `row` function and the time-bucket headings)

**Interfaces:**
- Consumes: `groupTree` from Task 5; `studio listing` fields from Task 4.

- [ ] **Step 1:** Add a "By time / By group" switch above Studio's list (kept in the page state like other switches). "By group" renders `groupTree` for the current repo: groups with no member in this repo are hidden, counts are this repo's members only, ungrouped rows go under "Unsorted".
- [ ] **Step 2:** Each Studio row gets label chips and a small menu with "Add to a group…" and "Labels…", opening the same drawers as Task 5.
- [ ] **Step 3: Verify:** `node --check`; browser pass as in Task 5, plus: a session grouped on the Sessions page appears under the same group in Studio's "By group".
- [ ] **Step 4: Commit** (only if asked): `git commit -m "Studio's list: group view, labels and row actions"`.

### Task 7: Notes, contract and the full checks

**Files:**
- Create: `changes/groups-and-labels.json` (via `plugin/bin/lfg release note groups-and-labels --added "..." --whats-new "..." --page sessions`)
- Modify: `CONTRACT.md` (the `sessions.json` entry and the new `save` actions), `docs/dashboard.md`

- [ ] **Step 1:** Write the release note with `lfg release note groups-and-labels`: one `--added` line per user-visible piece (nested groups; studios in groups; labels and filter; groups following tickets) and one `--whats-new` titled "Groups can hold groups, and studios can join them".
- [ ] **Step 2:** Update `CONTRACT.md`: the new `sessions.json` keys and their shapes, the eight actions, and the precedence rule. Update `docs/dashboard.md` for the Sessions and Studio rows.
- [ ] **Step 3: Run** `python3 -m unittest discover -s tests`, `uvx ruff check plugin/lib plugin/bin/lfg tests`, `plugin/bin/lfg doctor --selftest`, `node --check plugin/lib/lfgcore/ui_assets/app.js`. Expected: all pass.
- [ ] **Step 4: Commit and open the PR** (only if asked; then push, and open the PR since the branch has none, per Lee's rules). The PR body says what was not checked (the browser pass if skipped).

## Self-review

- **Spec coverage:** nesting (T1), studios in groups from either list (T4, T5, T6), labels and filter (T3, T5), ticket following (T2), Unsorted and non-goals respected (T5, T6), notes and docs (T7). Group delete safety, cycle and clash refusal, old-file loading, case-insensitive labels, stale ids: Review Focus lines each have a test in T1 or T3.
- **Types:** `group_info()`, `placements()`, `groupTree` and the eight action names are used with the same spelling in the tasks that consume them.
- **Not done on purpose:** group-level star or hide (spec non-goal); Linear epic expansion (project 2).
