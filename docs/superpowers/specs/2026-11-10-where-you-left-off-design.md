# "Where you left off": an automatic briefing for an epic, a milestone or a big ticket

Project 2 of 4. Status: draft, waiting for Lee's approval. Project 1 (nested groups and labels) shipped in LFG 0.5.0 and
this builds on it.

## Why

Lee runs an orchestrator (a Studio chat) for an epic, a milestone of an epic, or a big ticket, and spins up named Claude
Code sessions in his terminal that do what the orchestrator says. When he comes back to that work he has to rebuild the
picture himself: which sessions were doing what, what is done, what is waiting on him. He does not want to organise or
label anything by hand to get this. He wants a page he can always go to that orients him: clear, visual, progress
shown, generated automatically.

## What a person gets

1. A page, "Where you left off", in the sidebar under Your work. It opens on a short list of what Lee was last working
   on, across all repos, most recent first. Each entry is an epic, a milestone or a big ticket, with a progress count
   and a one-line status.
2. Clicking an entry opens its briefing: a header with progress (done of total, from real ticket data), chips for how
   many sessions are working, need him or are idle, a short written summary of where he stopped, a "Needs you" list
   with a button for each item, the milestones with the sessions working on each, and a detail panel per session
   (what it was for, where it stopped, what it changed, resume command, and the same actions a session has today).
3. Nothing to maintain. If a session cannot be matched to anything it shows under "Unsorted", and one click ("This
   belongs to...") ties it to a ticket. That click is the only manual step and is never required.

The look follows the existing dashboard (its colours, spacing and components). The approved starting point is the
clickable mockup from the brainstorm (`briefing-interactive.html`, kept in the brainstorm folder); the made-up numbers in it
are placeholders for the real ones below.

## Goals

- The list and every briefing build themselves from data LFG already has. No new thing to fill in.
- Progress is real: done tickets out of all tickets in the epic.
- The orchestrator and its worker sessions are told apart without labels.
- One click from "Needs you" to the thing that needs him (a PR review, a question, a session).
- Works on a machine where Linear is not connected: the page still shows sessions and PRs, just without progress.

## Non-goals

- Writing to Linear, creating tickets, or changing any ticket status.
- Changing groups, labels, sessions or tabs (projects 1, 3 and 4).
- A manual board or any drag-and-drop planning.
- Storing progress anywhere new: it is always read from the tickets and PRs.

## Anti-goals

- Inventing numbers. A count that cannot be worked out is left out and says why, never guessed.
- Making the page slow or costly. Opening it must never wait on Claude writing a summary.
- Hiding that something was written by Claude: the summary is labelled as written automatically.

## Where the data comes from (all exists today)

| Shown | Source |
|---|---|
| The epic, its child tickets, which block which | dev-graph's copy of Linear (`stacks._graph`, `stacks.epic_for`) |
| A ticket's PR, its state and checks, its LFG run, whether it is done | `stacks.epic_items`: done means Linear says so or the PR merged into main |
| Which sessions belong where | each session's ticket, read from its branch, title and first message (`sessions.listing`, `claudesess.listing`) |
| Groups | project 1: a group that follows a ticket, or holds the sessions |
| Reviews and unanswered questions | `reviews/` records |
| Live or idle | the session's state in Studio's list |

Linear data is only as fresh as dev-graph's copy (refreshed by the inbox skill). The page shows "Linear as of <time>".

## Decisions I made (Lee can override)

- **What an entry is.** Take the tickets named by recent sessions. A ticket that has an epic or parent in dev-graph
  resolves to that epic; otherwise the ticket is its own entry. A group that follows a ticket counts as naming it.
  Entries are ordered by the most recent session activity under them.
- **Orchestrator and workers.** A session or studio chat is the orchestrator of an epic when any of these holds, in
  this order: it is in a group that follows the epic's ticket; its branch, title or first message names the epic's
  ticket; or it names three or more of the epic's tickets. Anything else that names one of the epic's tickets is a
  worker, shown under the milestone that holds that ticket. The orchestrator is shown on top, not inside a milestone.
  When no rule fits, the session goes to "Unsorted" and the page says so; it never guesses. If both an orchestrator
  and a worker match one session, the orchestrator reading wins. This matches how Lee uses it: the orchestrator is the
  one named for the epic, the workers are named for their tickets.
- **Milestones, and what "total" counts.** A milestone is a child ticket of the epic that itself has children (the
  "parent" kind in dev-graph; the epic's other direct children are plain tickets). Walk the epic's tree two levels
  deep (epic, milestone, ticket). Progress counts the leaf tickets: done leaf tickets out of all leaf tickets. A
  milestone shows its own done out of total. A worker on a ticket resolves to the milestone that holds it, and to the
  epic through that milestone. An epic that spans repos is fine: dev-graph's data is read per repo, and the entry
  combines every repo that holds one of its tickets.
- **Progress.** An entry that is a plain ticket with no children shows its PR state instead of a count.
- **Fetching across repos.** The list must come up fast: it shows each entry's title, last activity and session
  counts from local files, and fills in progress per entry afterwards (one repo's PR list at a time, cached for two
  minutes as `stacks` already does). An entry whose progress cannot be read (no GitHub remote, Linear not mirrored)
  shows "progress unavailable" and why. The same ticket id seen from two repos is one ticket.
- **"Needs you".** Only things that can be known without guessing, and only about the epic's tickets:
  (a) an open PR by someone else that Lee has no saved review of in `reviews/`; (b) an open question in a saved review
  that he has not answered; (c) one of his own PRs with failing checks; (d) a worker whose ticket has an open PR and
  whose session has been idle for an hour. Lee is whoever `gh` is signed in as (the page already knows this as
  `gh.me` on the review page). No attempt to read minds from chat text.
- **Working, idle, finished.** A session is "working" if it is running in Studio now or its transcript changed in the
  last 10 minutes; otherwise "idle". The header chips count working, needs-you and idle. "Finished" is not detected
  from the transcript: the page uses the facts in the bullet above only.
- **Which entries and in what order.** Entries are tickets or epics named by sessions active in the last 14 days, newest
  activity first, capped at 30. An epic whose tickets are all done drops off after 3 days without activity. Both
  numbers are constants the builder can name.
- **The written summary.** Generated by Claude from the orchestrator's last messages and the facts above, labelled
  "written automatically". It reuses LFG's existing one-shot Claude call (the `claude -p` helper the review code
  already uses, `review.py`) and the model setting in Settings, with a new `models.briefing` entry beside the other
  per-job models. It is stored under `~/.lfg/state/briefings/<ticket>.json` with the time, the cost and a key of
  what it was built from (the newest transcript time under the entry and the facts' counts). It runs in the
  background only when someone opens a briefing whose key has changed, never at page load for the list, and never
  more than once per ten minutes per entry. Opening a briefing never waits on it: facts show at once, and the
  summary appears when ready, or the last stored one shows with its age. A "Refresh summary" button regenerates it.
- **Unmatched sessions** show under "Unsorted" in the same list. "This belongs to..." offers the recent tickets and
  groups; picking a ticket puts the session in the group that follows that ticket (creating a group named after the
  ticket and calling `follow_ticket` if none exists), with `file_into`. So it is persistent and reuses project 1's
  rules: Lee's own placement always beats a follow rule.
- **Where it lives.** A new page `#continue` and `#continue/<ticket>`, "Where you left off" in the sidebar's Your work
  section, across all repos like the Sessions page's "All repos".
- **Session actions in the panel** are the existing ones (Copy resume command, What it changed, Run a skill, Rules,
  Remind it of my style, Rename, Add to a group, Labels, Hide, Delete, Star). It reuses their handlers, not copies.

## Constraints

- Follow `CLAUDE.md`: per-PR notes file `changes/where-you-left-off.json`, `CONTRACT.md` and `docs/dashboard.md`
  updated, tests that patch `C.HOME` and `LFG_HOME`, no version bump.
- Before the PR: `python3 -m unittest discover -s tests`, `uvx ruff check plugin/lib plugin/bin/lfg tests`,
  `plugin/bin/lfg doctor --selftest`, `node --check plugin/lib/lfgcore/ui_assets/app.js`. Say what was not checked.
- Dark and light themes both. No new UI library. Each part loads on its own so the page shows something quickly.
- Never writes to Linear. Reads dev-graph and local files only.
- One PR, its own branch and worktree off `origin/main`.

## Left to the builder

The exact layout and spacing, the cache for the summary, how the entry list is paged, empty and loading states, the
prompt used to write the summary, and the test split.

## Where this sits

1. Nested groups and labels: shipped in 0.5.0.
2. This project.
3. Tab fixes: a "+" on the tab row, repo-pinned tabs an alert cannot hijack, per-tab colours.
4. One concept for studio and session, including a model setting on a studio.
