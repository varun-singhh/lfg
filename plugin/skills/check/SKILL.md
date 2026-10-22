---
name: check
description: >
  The green gate: fixes lint (never suppresses), type-checks, runs affected tests then the full
  suite, builds like CI, replays CI locally and reads the branch's GitHub CI status read-only.
  Use when the user says "is it green?", "run the checks", "fix the lint", "will CI pass?", or
  after /build or /fix finishes and before /expert or /ship.
author: Varun Singh
phase: prove
lanes: [express, standard, full, hotfix]
reads: [diff, 01-brief.md, 02-design.md, tasks.json, 03-build-*.md]
writes: [04-qa.md, ready.json]
auto-trigger: false
preflight: graphs
---

# /check: get to green, honestly

## Step 0: preflight

1. `lfg graphs ensure`. Non-zero exit: stop and show its output. Continue on a stale graph only if the user typed `--allow-stale`.
2. `lfg run path`. Exit 1 (no current run): `lfg run new check-<branch-slug>`.
3. `lfg rule graph-first` and follow it for every lookup below.

## Steps

1. **Scope the change.** `detect_changes_tool` on the working tree (uncommitted work included) → the changed nodes. Note the lane from `tasks.json` or `lfg lane --json`.
2. **Lint, fixed by hand.** Run the repo's lint/format autofix command (from `~/.lfg/repos/<repo-id>/commands.json`, else the repo's own scripts). Then fix every remaining error and warning in the touched files by editing the code. The fix is always in the code: the lint config, rule list and inline directives stay as they were.
3. **Types.** Run the repo's type-check command. Fix every error at its cause.
4. **Affected tests first.** For each changed node: `query_graph_tool` with `tests_for`. Run just those tests for fast feedback. Changed nodes with no test → record as **untested** (gate 2) and tell the user; write the missing test if the seam is agreed in `tasks.json`.
5. **The gate.** `lfg gate` (one line per check, output only for failures; full logs in `RUN/gate-logs/<check>.log`, read one only if the shown lines aren't enough): lint, types, full suite, build, gitleaks, new-suppression check, from exit codes. It writes `ready.json`. Read the per-check results from its output, never from memory.
6. **Local CI replay.** `lfg ci-local` (use `--list` first if unsure what it will run). It also runs `actionlint` on the workflows.
7. **Remote CI, read-only.** `gh auth status` (not logged in → ask the user to run `gh auth login` themselves; skip this step and say so). Then for the current branch:
   - `gh pr checks` (if a PR exists),
   - `gh run list --branch <branch> --limit 5`,
   - `gh run view <id> --log-failed` for any failed run. Summarise the failing step; fix it locally if the failure is in code this change touches.
8. **SonarQube (when `lfg sonar status` exits 0).** `lfg sonar scan` in the worktree or checkout you are checking. Exit 1 means a bug, vulnerability or security hotspot, or a major-or-worse issue, sits on a line this branch changed: fix each at its cause and scan again (fix the code, never the Sonar config). If GitHub's SonarCloud check failed, `lfg sonar cloud` shows its own verdict; "analysis failed" there is SonarCloud's side, not your code, so say so instead of chasing it.
9. **AI changes only (gate 6):** run the eval suite; score ≥ baseline − tolerance and cost per call ≤ budget, from `02-design.md`.
10. **Loop.** Any red check → fix the cause → re-run that check, then `lfg gate` again. Stop after 3 attempts on the same failure and report it with its output (suggest `/fix` for a real bug).
11. **QA matrix.** Map every acceptance criterion in `01-brief.md` (and each ticket's `verification` in `tasks.json`) to the test(s) that prove it. A criterion with no test fails gate 3 (Express: docs-only criteria are waived, say so).

**Done when:** `lfg gate` exits 0 in this run, `lfg ci-local` exits 0, every criterion maps to a passing test, and `04-qa.md` is written. Otherwise: done when the report below says exactly what is still red.

## Output

`04-qa.md` in the run folder:

```markdown
# QA: <run-id>
Lane: <lane> · Gate: green|red (ready.json) · CI replay: green|red · Remote CI: <state or "not checked: reason">

| # | Acceptance criterion | Test(s) (file::name) | Result |
|---|---|---|---|

## Checks run
| Check | Command | Exit | Notes (fixes made, attempts) |

## Untested changed nodes
## Still red (with output excerpt)
```

Reply to the user with: gate status per check, what you fixed, anything still red, untested nodes, and the next skill (`/secure` or `/expert`; `/fix` if stuck).

## Rules

- **A run filed under another repo** (this repo's tasks live in another repo's run, e.g. `/lfg` resumed that repo's handoff): write this repo's results as `04-qa-<repo>.md` and `ready-<repo>.json`, with `<repo>` the repo's folder name (e.g. `aegis-compliance-portal`), never over the run's own files. The dashboard shows them under this repo, and the owner repo keeps its own.
- A failing test is never skipped, deleted or weakened. If a test looks wrong, say so and ask.
- New `eslint-disable`, `# noqa`, `@ts-ignore`, `#[allow]`, `.skip(`, `xit(` or `@pytest.mark.skip` in the diff fails the gate; remove it and fix the code.
- `gh` is read-only here: `auth status`, `pr checks/view`, `run list/view`. See `lfg rule git-guard`.
- Report only what ran. A skipped step is named with its reason.
- Leave all changes unstaged.
