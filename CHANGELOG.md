# Changelog

All notable changes to LFG. The version lives in `plugin/.claude-plugin/plugin.json`.

## Unreleased

## 0.4.3 (2026-11-05)

### Added
- A review's question can be asked on GitHub for the PR's author (Ask the author on GitHub…): inline on the line it's about when that line is in the diff, else as a PR comment. Their replies show under the question; Use their reply as the answer sends them to the review's chat, and re-reviews read them on their own (`lfg review ask`, `lfg review replies`).

### Fixed
- After an Update, dashboard tabs you had open (not only the one you pressed Update in) reload onto the new version; before, they kept running the old one until reloaded by hand, so new things like the browser tab names didn't show there.
- The repo list top left no longer shows repos whose folder is gone, e.g. throwaway ones left behind by LFG's own tests.

## 0.4.2 (2026-11-05)

### Added
- The browser tab names the repo, page and what's open, shortened so several tabs stay readable (e.g. "ext · PRs · #1800"); a repo's short name is its first word, cut to 3 letters when long.

## 0.4.1 (2026-11-05)

### Added
- Messages in Studio and in a PR review's chat show when they were sent: the time today, the date and time before that, the full date on hover.

### Fixed
- Studio and PR review tabs follow the repo selected top left: each repo shows its own, as the Studio list did before tabs. A PR's tab shows in the repo it belongs to (every repo when you have no checkout of it). Up to 40 tabs are kept across repos, pinned ones not counted.
- Integrations → Claude Code plugins said a plugin synced from your claude.ai account or organisation was "installed for one repo"; it now says where it comes from and that it's changed there.

## 0.4.0 (2026-11-05)

A repo's LFG knowledge now lives in the repo, in `.lfg/`, committed with the work, so a teammate who checks out a branch gets the same context and their additions flow back. See `docs/team-knowledge.md`.

### Added
- **Corrections** (dashboard page, `lfg corrections`): when you correct Claude, LFG queues it (off until you switch it on). Approve one as a rule, with a why and an example, for every repo or one; merge it into a rule that already says much the same; save it to second-brain; or discard it. Only you decide; the guard blocks Claude from approving. A Stop hook in your Preferences hooks captures them.
- **Tabs**: Studio sessions open as tabs like PR reviews, above the page and in the sidebar, and drag to reorder. **Pin** a tab, on either page, to keep it at the front.
- **What's new**: a walkthrough of each release, once after you update, page by page; Help → What's new lists every release. Notes live in `plugin/releases.json`.
- **Review combos**: save sets of review methods under a name and pick one in a click; the star makes one your default. The Method picker lists review skills from your installed plugins (e.g. superpowers).
- **Claude Code plugins** (Integrations, `lfg plugins`): install from the marketplaces, turn on and off, remove; each install is undoable from the change list.
- **Releases**: Update installs numbered releases (`v<x.y.z>` tags on your fork) instead of every merge (`updates.channel`: `releases` or `main`). `lfg release prepare <version>` cuts one.
- `.lfg/` in each repo: runs (`runs/<run-id>/`), glossary and ADRs (`docs/`), `commands.json`, `shipcheck.json`, and the shared dev-graph nodes as one markdown file each (`nodes/<Type>/<slug>.md`). `.lfg/.gitignore` keeps machine-only files and all security reports out of git.
- `.lfg/repo-id`: the repo id is stored once, so adding or changing a remote no longer orphans runs and docs.
- dev-graph keeps each checkout on its own branch (`repo/<repo-id>`, `repo/<repo-id>--wt-<hash>` for worktrees); the MCP server is pinned to it.
- `lfg knowledge sync | status | migrate [--dry-run] [--take-main-nodes]`. Sync runs in the background at session start and after every turn.
- `lfg run use <run-id>` to pick up a teammate's run; session start offers unfinished runs on the checked-out branch.
- `lfg run scratch`: this machine's folder for `/build` worktrees, `/spike` prototypes and `/secure audit` reports.
- Studio's background-work panel is an accordion: the panel folds to its header (remembered in this browser), and each subagent or command is one line that opens to its details; what's open survives the page's refreshes.
- **Claude's questions and plans in Studio**: when Claude asks (AskUserQuestion), the session shows each question with its options to pick (several for multi-select, 1-9 keys, or your own answer) and Send or Skip, instead of an Allow/Deny prompt with the raw JSON. Answers go back the way Claude Code's own picker sends them. A plan (ExitPlanMode) shows as a document with Approve plan or Keep planning (with what to change). Neither is ever auto-allowed by "Allow for this session", which used to let later questions through unanswered. Several questions in one ask show as tabs in one card (Next, Back, a tick on each answered tab), so the card stays one question tall. Answered questions show what you picked.
- Toasts are one short line with a dot in your accent colour (red when something failed), gone after 6 seconds; the details stay in the bell. Bell icons use the accent colour too.
- **What a session changed**: a session's header shows "N files changed +x −y · View changes", which opens every file it edited or created as diffs (the Reviews diff view: file tree, filter, folding), one hunk per edit with when it was made. Built from the session's own transcript, so it shows exactly what Claude did there, even after commits, and leaves out denied or rewound edits. Shell commands that can change files (sed, scripts, installs, formatters) are listed alongside, since they aren't recorded as edits. Select lines there (drag down the numbers, or click then shift-click) to **Ask** about them or **Make this change**: it goes into the same session as the next message, with the file, the line range and the selected lines, so Claude knows exactly what you mean. A session that isn't running is continued first.
- **Studio shows background work**: beside a session (above the composer on narrow screens), its running subagents (type, task, steps so far, what it's doing now) and background commands, plus what finished in the last 20 minutes. Read from Claude Code's transcript and its `subagents/` folder, so it works for terminal sessions too. Work a session started but stopped reporting on shows as "no news for 15 min" instead of claimed as running. Background-task notifications no longer show as messages you typed.
- Studio fills the window at every text size (Small left a gap under the composer).
- **README gallery**: six screenshots of the dashboard (`docs/gallery/`) in a 3 × 2 grid. Theme previews in Appearance now draw in your accent colour.
- **Orange is LFG's accent colour now** (logo, favicon, heroes, buttons). Blue and the others are still in Settings → Appearance. A blue saved before this change was just the old default, so it switches to orange; blue picked from now on stays.
- **Launch film** on the home page: a "The launch film" section (and a Film link in the top nav) to watch it any time, plus a popup that plays it once: it counts as seen the moment it shows, so the next `lfg ui` goes straight to the home page even if you quit mid-film (remembered in `~/.lfg/state/tours.json` as `launch-video`). The video streams from GitHub; the page's CSP allows media from GitHub's asset hosts only.
- **Star LFG, only if you want to**: `lfg setup` asks once in a terminal when the GitHub CLI is signed in (Enter means no), and the dashboard's Star buttons star it in one click from your account (or open GitHub when `gh` isn't signed in). LFG never stars or writes to GitHub on its own. Remembered in `~/.lfg/state/github.json`.
- **README**: a one-command install, and a prompt to paste into Claude Code so it sets LFG up for you.
- Sidebar foot: the LFG version, an "available" tag when a newer one is out, and a button to check now; a faint glow in the accent colour.
- **The brand follows your accent colour**: the logo, the favicon and every hero glow (home, Welcome, intro) are drawn from the accent, so picking violet, green, orange or rose recolours them too. Diff threads and the AI's text in reviews now use the app's own look (hairline card, avatar rows) instead of violet panels and chat bubbles.
- **Appearance** (Settings → Appearance): System, light or dark; three light themes (LFG, Paper, Mist) and three dark (Midnight, Graphite, Carbon); accent colour, density, text size, background glow and motion. Kept per browser.
- **Docs, reorganised**: *Getting started* (what LFG is, how it works, everyday commands), graphify's *Code wiki* (call flows, the architecture map and one page per area of the code), and *Your docs*, which you can now write and edit in the dashboard in Markdown, for the project or a branch. LFG's own playbooks are no longer listed as docs.
- **Add knowledge**: paste a note, decision, lesson or rule in Markdown on the Knowledge page. Saved in `~/.lfg/repos/<repo-id>/knowledge/` (`lfg repo knowledge`), and Claude is told to read your docs and knowledge in that project.
- **A logo**, and a thank-you on the home page to the open-source projects LFG is built on.
- **Product home** (what `lfg ui` opens): a full-screen page with the pitch, the flow from one sentence to a shipped change, a snapshot of each feature (talk-to-the-diff reviews, Insights questions, hotspots, why-is-this-here history, runs, guard rails, Dictate), and a button into the dashboard.
- **Intro journey** for first-time users: six steps, one feature each with its snapshot, then pick what you'll use; it ends on the dashboard with its tour. Replay it from the home page.
- **A tour for every page**: the Tour button in the top bar explains the page you're on.
- **Sharper finish**: small corners (3-6px) everywhere, one spacing scale, quieter shadows. Todos show status as a coloured tag, the project as a tag, and roomier rows.
- **New look**: the dashboard is card-based and blue. Light mode is soft white and blue, dark mode deep navy, both with a faint blue glow; Welcome gets the full LFG hero. Things that behave alike share a card (Settings → General is now Features, Updates, How LFG works, Agent models, Dashboard and disk space). Pill tags and status badges, blue checkboxes, switches for on/off settings, segmented tabs, dark code panels, task-list checkboxes in docs (`- [ ]` / `- [x]`), numbered review questions and a commit timeline in Insights.
- **Welcome** (dashboard, or `lfg onboard`): pick the features you use (building code, reviews, security, docs and knowledge, planning) and the sidebar shows only their pages. Change it any time in Settings → General (switches apply at once, plus "Show every page"). Nothing is hidden until you choose, and installs from before this keep every page. Stored in `~/.lfg/state/onboarding.json`, not config.json.
- **Update check**: the dashboard asks GitHub for LFG's latest version at most once a day (`updates.auto_check`, on by default; "Check for updates" in Settings; `lfg update`). A banner shows the new version, what's new, and the command to run (`git pull && ./install.sh` in your clone); close it to hide it for that version. Only the version file and changelog are fetched; nothing about you or your code is sent, and LFG never updates itself.
- **Insights** (dashboard, under This project): understand code you didn't write without opening an editor. *Your changes* reviews everything the branch changes, committed or not, and adds the questions a senior engineer would ask before approving it, the fragile files it touches, and the findings that keep coming back. *Hotspots* ranks files by fixes and churn from git history, with the reasons. *Files* explains a file and, for any function, why it's there: the commits that shaped it with their issues, tickets and PRs as links. Read-only git, nothing leaves the machine. Also `lfg hotspots`, `lfg why <file>[:lines]` and **/lfg:why**.
- **Check-ins**: once you start using a feature you hid (its skill used 3+ times, or its page already has something to show), the dashboard offers its pages once: *Show it* or *Not now* (asked again after a month at the earliest; never in the first days, never more than once a week). From the skills LFG already records per reply.
- **Tests from past bugs**: test ideas now include one per fix commit on the file in the last year, and a test file to start from in the project's own style (pytest, unittest, vitest or jest, reusing how existing tests import the module). Every test is skipped until written, so it runs as-is. Copy from Insights → Files.
- **Debt trend**: hotspots and folders say when fixes are rising (the recent half of the window vs the half before).
- **Team decisions in review questions**: Your changes asks whether the change still follows a decision record or dev-graph decision that names a changed file or its module.
- First setup in a terminal offers to open the dashboard, which starts on Welcome.
- Fix detection (hotspots, history, recent fixes, regression ideas) no longer counts release roll-ups like "LFG 0.3.0: … fixes" as bug fixes.
- **/lfg:explain5**, **/lfg:review-coach**, **/lfg:suggest-tests** (and `lfg explain5`, `lfg review-coach`, `lfg suggest-tests`): quick heuristic first passes (a file in plain terms; secrets, eval, swallowed errors and queries in loops at `file:line` across the branch's changes; test ideas per function with the case each targets). The skills tell Claude to check every finding in the code before repeating it.

### Changed
- The guard blocks agents from installing, removing or switching Claude Code plugins and marketplaces, and from adding MCP servers.
- `lfg enable` no longer hides `.lfg/` from git; `lfg knowledge migrate` takes back the line older versions added.
- New free-text issues get a short random suffix (`iss-fix-login-3f2a`) so two people's issues never merge.
- The guard protects `.lfg/repo-id` and `.lfg/.gitignore` and blocks a recursive delete of a repo's `.lfg/`.
- CI installs the Omnigraph CLI so the knowledge-sync tests run.
- Headroom runs in `cache` mode by default. `token` mode rewrote earlier turns, so about one call in nine on a long session sent the whole conversation again at full price, costing more than the compression saved. A `headroom.mode` you set yourself is kept.
- "Is it fixed?", rewriting a comment, turning a session into a review, knowledge questions and a review chat with no session start Claude with no tools, MCP servers or slash commands: about 2k tokens a call instead of about 230k.
- Headroom runs with `--lossless`: it no longer adds retrieval markers, which switched calls between streamed and unstreamed and made about half of those switches send the whole conversation again.
- Todos: **Create Linear ticket** now writes the title and description with your `/linear-ticket` skill first (a read-only Claude run with no Linear connection; `todos.ticket_skill` in config names another skill). You check and change the preview, and only **Create** plus the confirm files it. **Write it again** asks the skill for a new draft.
- PR reviews show the notes you started a review with: on the running review, and on the finished review, with **Edit for the next review** to change or reuse them. The start buttons say "with your notes" when the notes box has text.
- PR review chat takes any file, not only images: drop, paste or attach (paperclip) CSVs, documents, text and code files, up to 10 at a time. Files show as chips with their names, and several that can't be added say why in one message.

### Fixed
- The first-run setup guide can be skipped (Skip, or Escape).
- The install tests no longer rewrite your real `~/.claude/lfg-preferences.md`.
- Runs started in a repo with no commits recorded their branch as `detached@`.
- Clicking an option in Claude's questions could scroll the page into empty space (a black screen) and miss the click: each option's hidden checkbox was placed against the page instead of its own row, which also made the Studio page taller than the window.

### Upgrading
Install this version first, then run `lfg knowledge migrate --dry-run` in each repo, then without `--dry-run`. Until a repo is migrated, its old runs stay in `~/.lfg` and session start says so.

## 0.3.0 (2026-10-20)

### Added
- **Docs page as a tree**: project docs at the top (LFG's Wiki, glossary, Decisions, docs you asked for), then one folder per branch. Claude writes docs you ask for to `lfg repo docs` (project-wide) or the new `lfg repo docs --branch` (this branch's work), into the repo's `.lfg/docs` (this fork keeps project docs in the repo). The repo's own markdown and graphify's per-cluster pages ("plugin · re") are no longer listed.
- **LFG Dictate** (`lfg add dictate`, or Settings → Claude Code → Feature packs): hold Option+Space anywhere on the Mac to dictate, double-tap for hands-free, Esc or the shortcut again to finish. Text always goes two places: where the cursor is (pasted, or typed with `dictate.insert type`) and the clipboard, so it can be pasted again. Transcription runs on-device with Cactus Compute's Whistle model through cactus-needle 3.2.8, which LFG always starts with its telemetry off and Hugging Face offline. **Clean up with Claude** (on by default, `lfg dictate cleanup off` to keep everything on the Mac) sends text only (never audio) to Claude and falls back to the raw text if that fails. No audio or transcript is kept. Ships dormant: nothing is downloaded, installed or asked for until turned on, and `lfg remove dictate` deletes everything through the change ledger. The shortcut can be changed (Right Option, Fn, Control+Space, Command+Shift+Space), with a warning when a known app also claims it. Dictate runs as its own small app, **LFG Dictate** (`~/.lfg/dictate/LFG Dictate.app`, built and signed locally), so macOS asks for Microphone and Accessibility permission by that name. A quiet pill at the bottom centre of the screen shows only voice-level bars while listening, dimmed bars while transcribing, and text only when it has something to say. Its options (shortcut, paste or type, Clean up) sit on the Dictate row in Settings → Claude Code and in `lfg dictate cleanup on|off`, `lfg dictate insert paste|type` and `lfg dictate shortcut <preset>`; these are user-only (the guard blocks agents from them). `lfg dictate status|restart` (status also says where the last dictation went and why, never the words). Everyone, on a fresh install or after an update, learns about Dictate once: while it's off, a **New: LFG Dictate** banner sits above every dashboard page (Turn it on / Take the tour / close) with a tour; once it's on, the tour is offered once (Start tour / Skip) unless it was already finished. The tour walks through every control (gestures and the listening pill, shortcut, paste or type, Clean up, Add or Turn off, terminal commands); the Dictate row shows its controls greyed while it's off so they can be pointed at. Both are remembered in `~/.lfg/state/tours.json` and can be replayed from "Take the tour" on the Dictate row. `lfg setup` prints "New in LFG 0.3.0" after an update.

### Fixed (Dictate)
- Dictation in Chrome, Electron apps (Slack, VS Code, Claude) and other apps that don't report their focused field was left on the clipboard ("Copied") instead of being pasted. Dictate now always pastes (or types) where the cursor is, and also leaves the text on the clipboard.

### Changed
- Pentest and Headroom are labelled **Experimental** in setup, `lfg packs`, the dashboard and the README, each with a one-line warning.
- LFG is macOS-only: `lfg setup` now refuses other systems, like `install.sh`.

### Fixed
- The guard no longer treats a heredoc's text as commands (`cat > notes.md <<'EOF' ... git commit ... EOF` is a file write). A heredoc fed to a shell (`bash <<EOF`) is still checked, and so is `$(...)` in an unquoted heredoc.
- The guard allows `curl <api> | python3 -c "<parse>"`: inline code reads the download as data. Piping into a bare interpreter, or inline code that executes what it reads, is still blocked.

This fork leaves out 0.3.0's Commit approval: your Preferences (Git → Commits) decide when Claude commits.

## 0.2.0 (2026-10-14)

LFG no longer changes Claude Code for every session on the machine. It is now installed off, turned on per repo, and every change it makes outside `~/.lfg` is recorded and reversible.

### Added
- `lfg setup`: looks at the machine (read-only), prints a plan, and applies it only after a yes. A failed step rolls back that run's changes. `install.sh` is now a thin wrapper around it.
- `lfg enable` / `lfg disable`: turn LFG on or off for one repo, using Claude Code's per-repo plugin setting (`.claude/settings.local.json`). `--everywhere` is available but not the default.
- Change ledger (`~/.lfg/state/ledger.json`, `claudecfg.py`): every outside change is backed up, written with compare-and-swap, and undoable. Added `lfg changes [undo <id>]`.
- `lfg uninstall [--dry-run] [--keep-data]`: undoes everything, including what older versions did, and lists the tools and repo graph folders it leaves.
- Feature packs (`lfg packs`, `lfg add`, `lfg remove`): security, shipcheck, pentest, knowledge, linear, headroom. Core installs only uv, gh, code-review-graph and graphify.
- Dashboard **Skills** page: every skill from every source, with name clashes, context cost and an auto-invoke switch.
- Dashboard **Settings → Claude Code**: where LFG is on, packs (installed in the background), hardened mode, Headroom scope, MCP status, your setup (read-only), leftovers from older versions, and every change with Undo.
- Migration from older installs. `lfg setup`, the dashboard and `lfg uninstall` detect the old global deny rules, the `CLAUDE.md` block (only if unedited), the user-scope MCP servers, global Headroom routing and the plugin being on everywhere, and offer to remove exactly those.
- Hardened mode: Claude Code deny rules behind the guard, written per repo, never to user settings.
- `lfg mcp <name>`: the plugin's own MCP servers, with a no-tools stub when a pack isn't set up.
- Open-source project files: CI, contributing guide, security policy, code of conduct, issue templates.

### Changed
- `bin/` and `lib/` moved into `plugin/`, so the plugin is self-contained. Hooks call `${CLAUDE_PLUGIN_ROOT}/bin/lfg`.
- Plugin manifest: `defaultEnabled: false`, plus homepage and repository fields. MCP servers moved from user scope into `plugin/.mcp.json`, so agent tool names are now `mcp__plugin_lfg_<server>__*`.
- Hooks exit at once in repos where LFG is off, match only the tools they inspect, and start Python with `-S`. Measured with Anaconda Python, an off-repo hook dropped from about 196 ms to 64 ms. SessionStart caches `gh auth status` for an hour, and Stop reads only the new part of the transcript.
- Headroom is opt-in and scoped (`headroom.scope`: off / repos / everywhere), and refused on Bedrock, Vertex and Foundry.
- The guidance that used to be appended to `~/.claude/CLAUDE.md` is now session context, and only in LFG repos.
- Skill edits from the dashboard no longer write into Claude Code's plugin cache, because the local marketplace loads the plugin in place.
- The guard blocks agents from running `lfg setup|enable|disable|uninstall|add|remove|changes undo|headroom setup|off` and from editing `~/.lfg/state` or `enabled.json`.
- Skills are documented as `/lfg:<name>`, and `/lfg:which` recommends namespaced names.
- Ignore entries go in each repo's `.git/info/exclude` instead of the global gitignore.

### Dashboard
- New look: a calm, document-style workspace in the spirit of Notion. It has warm neutral colours, system fonts, a sidebar with icons and project and branch switchers, a breadcrumb bar, large page titles, lists and tables on light dividers instead of boxes, tinted status labels, coloured callouts for what needs you, expandable toggles, a side panel for files, and a full dark theme. It fits at phone width with no sideways scrolling.
- Data fixes found by checking every page against seeded runs, real code graphs and usage:
  - The ship check's checklist was never shown ("0 of 0 checks passed"). It is now counted and listed, including items left for you to do and items that don't apply.
  - Review feedback is matched to the run it was given on (finding IDs like R-1 repeat across runs).
  - A run's "next step" names what is blocking it first, most serious first (failing checks, then a blocked review, a security problem, review changes, then the ship check), instead of the next missing file. Progress counts only the steps actually done, so a review-only run no longer shows "8 of 10".
  - A pentest that didn't run is flagged. Run documents are listed in pipeline order.
  - Home's "needs your attention" only nags about packs you added and says what to do ("GitHub CLI isn't signed in: run `gh auth login`"). The issues tile no longer shows 0 when dev-graph is unreachable, and a dev-graph that refuses LFG's token is explained with a fix.
  - Home and Usage count tokens the same way.
  - Code: test functions are left out of "where changes are riskiest", areas get readable folder names instead of `__init__.py`, and docstrings are labelled as what they are, with locations as `file:line`.
  - Docs: vendored third-party files are no longer listed as your team's docs.
  - Usage shows this project's tokens per run.
  - Skill names are shown as `/lfg:<name>` throughout.

### Removed
- Global `permissions.deny` rules, the global `CLAUDE.md` block, user-scope MCP registration, global gitignore and `core.excludesFile` changes, and routing all Claude Code traffic through Headroom by default.
- References to design documents that weren't in the repository.

## 0.1.0

First version.
