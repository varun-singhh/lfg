# Working on LFG

How changes ship in this repo. Every Claude Code session here reads this, on any computer.

## Changes ship in releases

Users get numbered releases, not every merge. The dashboard's Update button installs the newest release (a `v<x.y.z>`
tag on the fork's main), and the dashboard walks the user through what's new in it, once.

**Every pull request that changes something a user can see or do:**

1. Adds a line to `CHANGELOG.md` under `## Unreleased` (`### Added`, `### Changed` or `### Fixed`). This is the
   detailed record.
2. Adds an item to `plugin/releases.json` under the release whose `version` is `"unreleased"` (create it at the top
   of `releases` if it isn't there, with a `title` placeholder). This is what the user is told in the What's new
   walkthrough: a `title`, plain-English `text` saying what they can now see or do, and, when it lives on one page,
   `page` (a dashboard page key, e.g. `prs`) and `sel` (a CSS selector for the part to light up there).
3. Never bumps the version in `plugin/.claude-plugin/plugin.json`. Only a release does.

Internal changes (refactors, tests, tooling) get a changelog line only if they change behaviour.

**A release** is its own pull request, cut when the user asks for one ("cut a release", "ship 0.5.0"):

1. `plugin/bin/lfg release prepare <x.y.z> --title "<a few words>"` in the checkout. It bumps the version, names the
   unreleased What's new entry after it, and moves the changelog's Unreleased notes under the version. Fix anything
   it lists under `notes`.
2. Tidy the changelog section: one `### Added` / `### Changed` / `### Fixed` each, plain words, newest first.
3. Open the PR. Once it is merged, tag the merge commit and push the tag:
   `git tag v<x.y.z> <merge sha> && git push origin v<x.y.z>`. Until the tag exists, Update won't offer it.

Minor version for features (0.4.0 → 0.5.0), patch for fixes only (0.4.0 → 0.4.1).

## Pull requests

- One logical change per PR, on its own branch in its own worktree (`lfg worktree new <branch> --from origin/main`).
- Never merge one open PR's branch into another: after a squash merge it shows as a conflict on the same lines.
  Branch from `origin/main`, and update a PR from `origin/main` only.
- Before opening one: `python3 -m unittest discover -s tests`, `uvx ruff check plugin/lib plugin/bin/lfg tests`,
  `plugin/bin/lfg doctor --selftest`, and `node --check plugin/lib/lfgcore/ui_assets/app.js` when the dashboard
  changed. Say in the PR what was not checked (e.g. the page in a browser).
- `CONTRACT.md` lists every command, file and format; update it with the change. `docs/dashboard.md` describes each
  dashboard page.
- Tests never touch the real `~/.claude` or `~/.lfg`: patch `C.HOME`, `LFG_HOME` and any path fixed at import time
  (e.g. `prefs.PREFS_MD`).

See `CONTRIBUTING.md` for the ground rules and `FORK.md` for standing decisions about upstream.
