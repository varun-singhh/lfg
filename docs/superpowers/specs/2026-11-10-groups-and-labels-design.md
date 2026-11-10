# Nested groups and labels for studios and sessions

Project 1 of 4 (see "Where this sits"). Status: draft, waiting for Lee's approval. A builder read it once and the
questions it raised are settled below under "Decisions I made".

## Why

Lee runs an orchestrator in Studio (a chat in the dashboard) and spawns named Claude Code sessions in his terminal that
do what the orchestrator says. He does this for an epic, for one milestone of an epic, and for big tickets. Today:

- He can put sessions in a group ("Add to a group...") but a group is one flat level.
- Studio chats cannot be put in a group, so the orchestrator can't sit with the sessions it directs.
- A session can only be in one group, so there is no way to also mark it "orchestrator" or "needs review".

What he wants: one place where an orchestrator and its sessions sit together, in a hierarchy when there is one
(epic, then milestones, then sessions), plus labels that cut across it. Neither should be work he has to do by hand
for every session.

## What a studio and a session are, in the code

They are the same thing. Studio's list (`claudesess.listing`) reads every Claude Code transcript for the repo and its
LFG worktrees, including ones started in a terminal (`source`: `lfg`, `desktop`, `terminal` or `background`). The
Sessions page (`sessions.listing`) reads the same transcripts. Both key everything by the Claude Code session id.
Groups, names, stars and hidden flags are kept by that id in `~/.lfg/state/sessions.json`. So a studio chat can
already be a member of a group in the data. Only the Studio side of the dashboard has no way to do it.

## Goals

1. A group can contain other groups, to any depth (epic > milestone > sessions).
2. Studio chats and sessions are grouped the same way, from either part of the dashboard, and appear together.
3. Labels: any number per session or studio, with a colour, shown as chips, usable as a filter.
4. Groups can follow a ticket, the way they already follow PRs: every session that mentions the ticket joins
   automatically, unless Lee takes it out. This is what keeps it from being manual work.
5. Anything that doesn't match a rule stays visible as "Unsorted", never hidden and never required to be sorted.

## Non-goals

- Merging the Studio and Sessions pages into one (project 4).
- The "where you left off" page and any progress numbers (project 2). Following a ticket here only matches sessions that
  name that exact ticket. Pulling in an epic's sub-issues from Linear is project 2.
- Changing anything on disk: groups and labels remain LFG-only labels, as the group code already says.
- Group-level actions such as "star the whole group" or "hide the whole group". Not asked for.

## Anti-goals

- Nothing may require Lee to organise before a session is usable. A new session with no group and no label is normal.
- Moving or deleting a group must never delete or hide a session. A deleted group's children move up one level.

## Decisions (as Lee decided them)

- Groups hold other groups.
- Labels are separate from groups, and an item can carry several.

## Decisions I made (Lee can override)

- **Groups are global, as they are today.** `sessions.json` is one file for all of LFG and the Sessions page lists every
  repo, so a group name is unique across everything and can hold sessions from several repos (an epic often spans repos).
  Studio shows only the groups that have a member in the repo it is showing, with the count of that repo's members.
- **Groups are explicit.** Today a group exists only while it has a session in it, and filing the last one out deletes it
  (`file_into`). That can't work for an epic that holds only milestone groups. Add a `groups` list of group names that
  exist on purpose; a group lives while it is in that list, has a member, a child, or follows something. "New group...",
  rename and delete are actions in both lists. Rename moves the name everywhere it is stored.
- **Storage.** Also in `sessions.json`: `group_parent` ({child: parent}), `labels` ({session id: [names]}),
  `label_colors` ({name: colour}), `group_tickets` ({group: [ticket ids]}, like `group_prs`). `left_out` covers tickets
  as it does PRs. A group can follow PRs and tickets at once.
- **Cycles** (a group inside its own descendant) are refused with a plain message.
- **A session sits in one group** (as today); labels are the many-to-many part.
- **Manual beats automatic.** A session you filed by hand, or took out of a group, is never moved by a follow rule (this is
  how PRs already work). Among several ticket-following groups that match, the deepest group wins, then the first by name.
  A group's count includes everything in the groups under it.
- **Ticket following** matches the text the session summary already reads: the session's branch, title and first message
  (`issues`). It does not scan the whole transcript, on purpose: an orchestrator that mentions every ticket in its epic
  must not be pulled into one milestone's group. The CLI sessions Lee names after a ticket or branch are the target.
- **Unsorted** is today's "no group" state under a clearer name. Existing groups and PR-following keep working unchanged.
- **Labels.** Names are case-insensitive. A Labels manager renames, recolours and deletes them; deleting removes it
  from every item. A label disappears when its last item loses it, unless it was created in the manager.
- **Label filter.** Choosing several labels narrows (item must have all of them). A group shows if anything under it
  matches, and its count follows the filter.
- **Colour list** is a small fixed set, the ones the dashboard already uses for statuses. No free colour picker.
- **Where it shows.** Both lists get the same group tree with a count per group (including nested), label chips on rows, and
  a label filter. Studio's session list gains "Add to a group..." and "Labels..." on a row, matching the Sessions page.
- **Naming.** The UI says "group" and "label". No new word for the link between two things: being in the same group is the link.

## Constraints

- Follow `CLAUDE.md`: a notes file under `changes/<branch>.json`, `CONTRACT.md` and `docs/dashboard.md` updated, tests that
  patch `C.HOME` and `LFG_HOME`, `python3 -m unittest discover -s tests`, `uvx ruff check`, `lfg doctor --selftest`,
  `node --check` on `app.js`.
- Old `sessions.json` files must read unchanged: missing new keys are empty, the same way `prefs()` reads them now.
- Dark and light themes both, matching the existing look. No new UI library.
- One PR, on its own branch in its own worktree off `origin/main`.

## Left to the builder

Exact controls and layout for the tree and the label editor, the label colour names, how deep the tree indents, keyboard
behaviour, and the test split.

## Where this sits

1. **This project:** nested groups and labels, same for studios and sessions.
2. "Where you left off" page, generated from groups, ticket ids, PRs and the Linear epic.
3. Tab fixes: "+" on the tab row, repo-pinned tabs that an alert can't hijack, per-tab colours that survive reloads.
4. One concept for studio and session: everything a session has (star, copy resume command, what it changed, run a skill,
   rules, style reminders, rename, hide, delete) on a studio, and a model setting for a studio.
