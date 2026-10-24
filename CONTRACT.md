# LFG build contract

The single interface every part of LFG agrees on: the CLI, hooks, skills, agents and the dashboard. User-facing docs:
`docs/guide.html` (also `lfg ui` → Help), `docs/sharing.md`, `docs/dashboard.md`.

## Layout

Source checkout: `install.sh`, `plugin/` (the Claude Code plugin with the CLI inside it), `docs/`, `tests/`, `CONTRACT.md`.

After install (`~/.lfg`, mode 700):

```
~/.lfg/
├── plugin/                 # the plugin AND the local marketplace Claude Code loads it from, in place
│   ├── .claude-plugin/{plugin,marketplace}.json   # version lives in plugin.json; defaultEnabled: false
│   ├── bin/lfg             # CLI (python3 -S, stdlib only, 3.9+); on the Bash PATH while the plugin is on
│   ├── lib/lfgcore/        # CLI + dashboard modules
│   ├── skills/<name>/SKILL.md   agents/<role>.md   rules/<rule>.md   hooks/hooks.json   .mcp.json
├── docs/{guide.html,sharing.md,dashboard.md}  CONTRACT.md   # shown in `lfg ui` → Help
├── enabled.json            # where LFG is on: {"everywhere": bool, "repos": {<main checkout>: {...}}}
├── state/ledger.json       # every change LFG made outside ~/.lfg (claudecfg.py), what `lfg uninstall` replays
├── state/{packs.json,gh.json,usage-offsets.json}
├── state/onboarding.json  # Welcome: chosen features, show-every-page (never in config.json)
├── state/updates.json     # last update check: upstream version, notes, error
├── repos/<repo-id>/knowledge/*.md  # knowledge the user added (Knowledge → Add knowledge)
├── repos/<repo-id>/insights/reviews.json  # Insights: kinds and counts of findings per check (never code), for "keeps coming up"
├── config.json             # user config, mode 600 (models, lanes, shipcheck, pentest, ports, linear, graphs.docs,
│                           # headroom.port/mode/scope, guard.hardened)
├── overrides/{skills,rules}/  defaults/skills/  backups/   # your dashboard edits, pristine copies, backups
├── graphs/<repo-id>/{state.json,docs.json,.lock,sync.log}  # graph bookkeeping only; the graphs are in the repo (below)
├── repos/<repo-id>/{docs/GLOSSARY.md,docs/adr/,commands.json,shipcheck.json}
├── runs/<repo-id>/<run-id>/   # 01-brief.md … 07-shipcheck.json, tasks.json, progress.md, COMMIT_MSG.md, PR_BODY.md,
│                              # ready.json, gate-logs/, shipcheck-routes.json (optional)
├── omnigraph/{tokens.json (600),src/,dev-graph/,second-brain/}  # local graph clusters + server.log
├── headroom/{state.json,proxy.log}  # proxy upstream + previous ANTHROPIC_BASE_URL (launchd dev.lfg.headroom)
├── ui/static/              # generated viewer pages (e.g. arch-health/<repo-id>.html from /lfg:health)
├── playbooks/<repo-id>/{onboarding,landmines,test-gaps,incidents}.md   # generated from the graphs, never in the repo
├── secintel/cache/  strix/<repo-id>/  feedback/<repo-id>.json  usage.db (600)  audit.log
```

`<repo-id>` = `<repo-dir-name>-<first 8 hex of sha1(git remote origin url, or the absolute repo path)>`.
`<run-id>` = `YYYYMMDD-HHMM-<slug>`. The **current run** for a repo is in `~/.lfg/runs/<repo-id>/CURRENT`.

Tests: `python3 -m unittest discover -s tests` (stdlib, temp `LFG_HOME` and `HOME`, a fake `claude`) + `lfg doctor --selftest`. Lint: `uvx ruff check plugin/lib plugin/bin/lfg tests`, `shellcheck install.sh bootstrap.sh`, `claude plugin validate plugin`.

## Footprint: what LFG may change outside ~/.lfg

Only through `claudecfg.py` (backup, compare-and-swap, ledger entry), only after the user agreed (`lfg setup` plan, `lfg enable`, `lfg add`, the dashboard with the edit key), and never anything the guard calls user-only (agents can't run `lfg setup|enable|disable|uninstall|add|remove|changes undo|headroom setup|off`):

| Change | When | Undo |
|---|---|---|
| `~/.local/bin/lfg` symlink | setup | removed |
| `claude plugin marketplace add ~/.lfg/plugin` (Claude Code records it in `extraKnownMarketplaces`) | setup | `marketplace remove`, empty key dropped |
| `claude plugin install/enable lfg@lfg --scope local` → `enabledPlugins` in `<repo>/.claude/settings.local.json` | `lfg enable` | `uninstall --scope local`, empty key/file/folder LFG created dropped |
| LFG's graph folders in `<repo>/.git/info/exclude` | `lfg enable` | exactly those lines removed |
| deny rules in `<repo>/.claude/settings.local.json` | hardened mode | exactly those rules removed |
| `env.ANTHROPIC_BASE_URL` → Headroom, per repo (`scope: repos`) or in `~/.claude/settings.json` (`everywhere`) | Headroom pack | restored if still LFG's value |
| launchd agents `dev.lfg.headroom`, `dev.lfg.omnigraph.<name>` | Headroom / Knowledge packs | booted out, plist removed |
| user-scope MCP `linear` (only if you have none) | Linear pack | `claude mcp remove` |
| `claude plugin install lfg@lfg --scope user` | `lfg enable --everywhere` | `uninstall --scope user` |
| launchd agent `dev.lfg.dictate` (runs `plugin/lib/lfgcore/dictate_helper.py` in `~/.lfg/dictate/venv`) | Dictate pack | booted out, plist removed, `~/.lfg/dictate` deleted |

Revert restores a value only while it still equals what LFG wrote. Homebrew/uv installs are listed (`state/packs.json`), never removed. Older versions' machine-wide changes (global deny rules, the `~/.claude/CLAUDE.md` block, user-scope MCP servers, global Headroom routing, the plugin on everywhere) are detected exactly by `setup.legacy_items()` and offered for clean-up by `lfg setup`, the dashboard and `lfg uninstall`.

## CLI (`lfg <command>`). Every command: exit 0 = ok, 1 = failed check, 2 = usage/env error. `--json` where noted.

| Command | Does |
|---|---|
| `lfg setup [--packs a,b] [--here] [--everywhere] [--no-migrate] [--dry-run] [--yes] [--json]` | Install or update: read-only scan → plan → apply after a yes; a failed step rolls back this run's changes. `install.sh` runs it |
| `lfg enable [path] [--hardened] [--everywhere]` / `lfg disable [path] [--everywhere]` | LFG on/off for one repo (or machine-wide); `disable` undoes exactly what `enable` changed, keeps graphs and runs |
| `lfg packs [list\|add\|remove] [<name>] [--yes] [--no-scripts]`, `lfg add <pack>`, `lfg remove <pack>` | Optional packs: security, shipcheck, pentest, knowledge, linear, headroom. Core is always on |
| `lfg changes [list\|undo <id>] [--json]` | The change ledger; `undo` reverts one entry if it is still LFG's |
| `lfg uninstall [--dry-run] [--keep-data] [--yes]` | Replays the ledger backwards, cleans up older installs and LFG launchd agents, removes `~/.lfg`; lists tools and repo graph folders left behind |
| `lfg mcp <code-review-graph\|dev-graph\|second-brain\|headroom>` | The plugin's MCP servers (`plugin/.mcp.json`): the real server when its pack is ready, else a stub with no tools that says how to add it |
| `lfg dictate [status\|restart] [--json]` | LFG Dictate (pack `dictate`, off until `lfg add dictate`): on-device speech-to-text anywhere on the Mac. Hold the shortcut (`dictate.shortcut`, default Option+Space) to talk, double-tap for hands-free; text is put where the cursor is (`dictate.insert`: paste\|type) and also left on the clipboard. Runs cactus-needle's Whistle model offline (telemetry off, Hugging Face offline, explicit weights path). `dictate.cleanup` (on by default) sends text only to `claude -p`. No audio or transcript is kept; `~/.lfg/dictate/state.json` holds permissions, last error and today's count |
| `lfg version` | Version |
| `lfg doctor [--selftest]` | Tools of the packs that are on, Claude Code + marketplace, where LFG is on, Docker, Omnigraph, a Headroom proxy that is down, gh auth, leftovers from older installs, the ledger; `--selftest` proves every forbidden action is blocked |
| `lfg init [--rebuild]` | First-time setup for the current repo (graphs + repo dirs). Normally automatic |
| `lfg graphs ensure [--background] [--allow-stale] [--rebuild] [--json] [--quiet]` | **Graph preflight.** Builds on first use, syncs if code changed (incl. uncommitted). Exit 1 if graphs can't be made fresh |
| `lfg graphs status [--json]` | `fresh` / `syncing` / `stale` / `missing` |
| `lfg graphs docs [--quiet]` | Regenerates graphify's wiki + call-flow view, code-review-graph's wiki and the playbooks (no LLM, no network). Runs automatically in the background after a sync changes the graphs (`graphs.docs` in config.json, default on). Writes `graphs/<repo-id>/docs.json` |
| `lfg playbooks` | Writes only the playbooks: onboarding tour, landmines (code notes, untested security code, cycles, churn × untested), test gaps, incident runbooks (from dev-graph) |
| `lfg run new <slug>` | Creates a run folder, sets CURRENT, prints its path |
| `lfg run path [<file>]` | Prints the current run folder (or a file inside it). Exit 1 if no current run |
| `lfg run list` | Recent runs for this repo |
| `lfg run set [lane=…] [stage=…] [issue=<ID or title>] [--force]` | Records lane, stage and issue in the current run's `run.json` (what the dashboard shows). A stage moves the linked dev-graph Issue (plan → todo, build/fix/check/secure → in_progress, expert/ship → needs_review, done → done). Refuses to lower the lane without `--force` |
| `lfg issue sync <ID\|title> [--title] [--type] [--status] [--priority 0-4] [--description] [--criteria] \| show <ID> \| sync-tasks \| sync-brief [--json]` | `sync-tasks`: one Issue per task in the current run's tasks.json (description + steps, verification as acceptance criteria, done once `passes`), called by /plan and /build. `sync-brief`: the brief's Problem and Acceptance criteria onto the run's Issue, called after /grill. `sync`: creates or updates the Issue in dev-graph as the writer role (`ACME-4225` → slug `acme-4225`, `legacyRef` kept; an idea → `iss-<kebab>`). The Issues page lists these; skills call it at intake |
| `lfg rule <name>` | Prints a hidden rule module (`tdd-rules`, `slice-rules`, `domain-docs`, `module-design`, `bug-loop`, `agent-writing`, `git-guard`, `graph-first`, `remember`, `worktrees`), or the user's own version from `~/.lfg/overrides/rules/<name>.md` (changed or added in the dashboard). SessionStart lists rules the user added |
| `lfg repo docs [--branch [NAME]]` | Prints the per-repo docs dir (glossary, ADRs, project-wide docs the user asked for), never inside the repo. `--branch` prints `docs/branches/<branch>/` for docs about one branch's work (checked-out branch by default; the real name is kept in `.branch`) |
| `lfg repo knowledge` | Prints the per-repo folder of knowledge the user pasted in the dashboard (Markdown notes, decisions, lessons, rules), never inside the repo |
| `lfg repo id` | Prints `<repo-id>` (the same in every worktree of a repo) |
| `lfg repo root` / `lfg repo graph` | Prints the main checkout / its `graphify-out/graph.json` (also from a linked worktree) |
| `lfg worktree new <branch> [--from <ref>]` / `list` / `remove <name\|branch>` | Checks a branch out in `<parent>/<repo>.worktrees/<branch-slug>` (an existing branch, or a new one from `--from`, default HEAD) without touching the user's checkout, and records it in the current run's `run.json` `worktrees`. `remove` only takes worktrees it made, refuses any with uncommitted or untracked changes, never forces and keeps the branch. Agents run it on their own (rule module `lfg rule worktrees`); SessionStart removes LFG worktrees that are clean and unused for 24 h |
| `lfg lane [--json]` | Suggests a lane from the diff + code-review-graph impact (`express`/`standard`/`full`/`hotfix`) with reasons |
| `lfg gate [--json] [--fix] [--affected] [--only lint,types,test,build,secrets,suppressions]` | The green gate: lint, types, tests, build, gitleaks, new-suppression check. Results from exit codes. `--fix` runs the detected formatter/fixer first; `--affected` narrows tests to graph-impacted files where the runner supports it. Writes `ready.json` |
| `lfg ci-local [--list] [--json]` | Replays lint/type/test/build `run:` steps from `.github/workflows/*.yml` locally (only steps the guard allows; steps using `${{ }}` are skipped); `actionlint` + `zizmor` on workflows |
| `lfg secure [diff\|all\|<pkg@ver>\|<url>\|<image>] [--json] [--offline]` | Local scanners + metadata-only online intel. Writes `05-secure.json` when a run is active. Exit 1 on a blocking finding |
| `lfg pentest [--target <local url>] [--mode quick\|standard\|deep] [--model <ollama model>] [--preflight] [--json]` | Strix with a local Ollama model only, on a scrubbed copy of the repo. Refuses non-local targets, non-loopback Ollama, a missing sandbox image, or no egress firewall. Writes `05-pentest.json` |
| `lfg shipcheck [--cleanup] [--json]` | Ship check (gate 8): Docker build → scan → run on internal network → smoke test → delete → verify cleanup, plus shipping checklist. Writes `07-shipcheck.json` |
| `lfg watch` | Read-only: follows the CI run of the current branch via `gh` |
| `lfg ui [--port 7777] [--no-open] [--unlock]` | Dashboard on 127.0.0.1: read-only except Settings and Skills, which need the local edit key (handed to the browser in the URL fragment, never printed). Pages, rules and API: [docs/dashboard.md](docs/dashboard.md) |
| `lfg claudemd show\|remove-legacy` | Shows `~/.claude/CLAUDE.md`, or removes the marked block an older LFG appended, only if it is byte-identical to one LFG shipped. LFG no longer writes this file: the same guidance is session context in LFG repos (`hooks.CONTEXT`) |
| `lfg sonar setup \| status \| scan [--base REF] \| issues \| cloud [--base SHA] \| login \| stop \| remove [--data] [--json]` | Optional SonarQube pack (`lfg add sonarqube`; needs Docker and Node). `setup` pulls SonarQube Community 26.10 (pinned by digest), runs it as container `lfg-sonarqube` on 127.0.0.1:9000 with labelled volumes, replaces admin/admin with a generated password and makes a scanner token (`~/.lfg/sonarqube/credentials.json`, 0600; only `login` prints it), and installs SonarSource's npm scanner `@sonar/scan@5.0.2` into `~/.lfg/sonarqube/scanner` (`--ignore-scripts`). `scan` copies the git-tracked and new, non-ignored files (never secret-looking ones, never over 20 MB) to a scratch folder, analyses it natively (token in the environment, never argv), honours `.sonarcloud.properties` / `sonar-project.properties`, and writes `repos/<rid>/sonar.json` (gate, conditions, measures, every open issue and hotspot, `mine` = on a line this branch changed against `--base`, default origin's default branch). Exit 1 when a bug, vulnerability, hotspot or major-or-worse issue is on a changed line. `cloud` reads SonarCloud's own verdict for a commit from its GitHub check run (read-only). `remove` only touches resources labelled `lfg=sonarqube`; `--data` also drops the volumes and the credentials. /lfg:check runs `scan` when the server is up |
| `lfg omnigraph setup [--no-launchd] \| status \| restart <name> \| serve <name> \| mcp <name> [--json]` | dev-graph + second-brain (Knowledge pack): creates the graphs from the pinned Omnigraph cookbooks (no seed data), generates per-machine tokens (never printed), runs each server on 127.0.0.1 under a launchd agent `dev.lfg.omnigraph.<name>` (in the ledger). `serve` clears a cluster lock left by a server that died (only when the pid in `__cluster/lock.json` is gone, via `omnigraph cluster force-unlock`) and, if another server already answers on the port, waits and takes over when it stops; `restart` reloads an agent launchd gave up on; `lfg doctor` flags a brain that answers but isn't kept running by its agent. The plugin's `.mcp.json` provides MCP `<name>` → `lfg mcp <name>` → `lfg omnigraph mcp <name>`, only in LFG repos. Agents search with LFG's keyword queries in `plugin/omnigraph/{dev-graph,second-brain}.gq` (`find_*`, `save_note`; bm25, local, no API key); the cookbook's embedding `search_*` queries need an OpenAI/OpenRouter/Gemini key and are never used |
| `lfg headroom setup [--scope repos\|everywhere] [--upstream URL] \| status \| restart \| off \| serve [--json]` | Optional (Headroom pack, off by default): runs `headroom proxy` on 127.0.0.1:`headroom.port` under launchd `dev.lfg.headroom` (`headroom.mode`: `token` or `cache`; no rate limit, no response cache, telemetry off), forwarding to the previous `ANTHROPIC_BASE_URL` or api.anthropic.com. Routes Claude Code there only once the proxy answers: per LFG repo (`.claude/settings.local.json`, default) or everywhere (`~/.claude/settings.json`), all through the ledger. Refused on Bedrock/Vertex/Foundry. `off` undoes exactly that routing and unloads the agent. The SessionStart hook restarts a dead proxy Setup never adopts the Claude desktop app's own `ANTHROPIC_BASE_URL` (its gateway takes the app's sign-in, not the claude.ai login terminal sessions send); without a setting it forwards to api.anthropic.com. |
| `lfg feedback add <finding-id> accept\|reject [--note ...]` | Records your verdict on a review finding |
| `lfg usage [--json]` | Token/time summary from `usage.db` |
| `lfg vendor status\|sync\|update` | Pinned mattpocock/skills source |
| `lfg hook <session-start\|prompt\|pre-tool\|post-tool\|stop\|pre-compact>` | Hook entry points (stdin = hook JSON) |
| `lfg onboard [--all] [--features coding,reviews,...] [--json]` | Pick the features you use (Welcome); the dashboard sidebar then shows only their pages. Flags: non-interactive; a terminal with no flags: one question per feature; otherwise prints the current choice. Until chosen, and on installs from before 0.4, every page shows |
| `lfg update [--check] [--json]` | Asks GitHub for the latest version (two GETs: plugin.json and, when newer, CHANGELOG.md; nothing about you or your code is sent) and prints the update command. Never updates anything itself. The dashboard does the same at most once a day (`updates.auto_check`, default on) |
| `lfg explain5 <file> [--json]` | A file in plain terms: its top-level definitions, who changed it and when, related tests, recent fixes (read-only git) |
| `lfg review-coach [--base BRANCH] [--json]` | Heuristic pre-review of everything the branch changes (committed since the base plus uncommitted): hardcoded secrets, eval/exec, swallowed errors, queries in loops, at `file:line`. A first pass: verify before acting |
| `lfg suggest-tests <file> [--json]` | Heuristic test ideas per public function, each with the branch or edge case it targets, plus the existing test files to put them in |
| `lfg hotspots [--days N] [--limit N] [--json]` | Files that keep needing fixes, ranked by fix commits and churn from git history, each with plain reasons (fixes, changes, authors, size, no tests) and recent fixes; plus folders. Read-only git |
| `lfg why <file>[:LINE[-LINE]] [--limit N] [--json]` | The commits that shaped a file or lines of it (`git log -L`), newest first, with the issue numbers, tracker keys and PRs they mention as links built from the origin remote and `linear.workspace` (nothing fetched) |

## Skills

- Folder `plugin/skills/<name>/SKILL.md`. One-word lowercase names.
- Frontmatter (exact keys):

```yaml
---
name: <name>
description: >
  <what it does>. Use when the user says "<trigger>", "<trigger>", … <auto-trigger conditions>.
author: Varun Singh
phase: talk|plan|build|prove|ship|learn|helper|run
lanes: [express, standard, full, hotfix]
reads: [...]
writes: [...]
auto-trigger: true|false
preflight: graphs          # omit only for /note
adapted-from: mattpocock/skills/<name> (MIT, © 2026 Matt Pocock)   # only if adapted
disable-model-invocation: true                                      # only for explicit-only skills
---
```

- Body sections, in this order: `## Step 0: preflight` → `## Steps` → `## Output` → `## Rules` (short).
- **Step 0 (every skill except /note):** run `lfg graphs ensure`; if it exits non-zero, stop and show its output (never continue on a stale graph unless the user typed `--allow-stale`). Then `lfg run path` (or `lfg run new <slug>` for skills that start work).
- Rules modules are loaded with `lfg rule <name>` (Bash), never copied into the skill.
- Use graph tools before reading files: code-review-graph MCP (`get_minimal_context_tool` first, then `get_impact_radius_tool`, `query_graph_tool`, `get_review_context_tool`, `detect_changes_tool`), then `graphify query/explain/path` (from a worktree with `--graph "$(lfg repo graph)"`), then dev-graph (Omnigraph MCP), then files.
- Linear: read through the Linear MCP freely. **Any write** (create/update issue, comment, label, status) is shown to the user as exact text first and done only after an explicit yes.
- Never: push, commit without the user's approval (Commit approval), gh writes, read `.env*`/keys, print env, write secrets, deploy, `docker push`, delete Docker resources LFG didn't label. Changes are left unstaged.
- Keep skills short (target < 120 lines): they are loaded into context.

## Agents (`plugin/agents/<role>.md`)

Frontmatter: `name`, `description`, `model` (opus|sonnet|haiku), `tools` (comma list). Body: role, inputs (run-folder files), output contract (exact file), rules. Roles: product-manager, architecture-designer, software-engineer, ai-engineer, qa, security-analyst, expert-review, lane-triage.

## Hooks

`plugin/hooks/hooks.json` calls `"${CLAUDE_PLUGIN_ROOT}/bin/lfg" hook <event>`, with matchers limited to the tools LFG inspects (`Bash|Read|Edit|Write|MultiEdit|NotebookEdit|NotebookRead|WebFetch|mcp__.*`; SessionStart on `startup|resume`). Every hook first checks `C.is_enabled(cwd)` (a filesystem walk to the main checkout + `enabled.json`; no subprocess, no heavy imports) and exits 0 where LFG is off. SessionStart prints `hooks.CONTEXT` (what used to be the `CLAUDE.md` block) plus `hooks.TAG_RULE`: use an LFG skill whenever one fits even if the user didn't type the command, and start every reply with `**LFG:** /lfg:<skill>`, `**LFG:** tools only (<which>)` or `**LFG:** not used - <reason>`. UserPromptSubmit adds the one-line `hooks.TAG_REMINDER` to every prompt. Both follow `replies.lfg_tag` (default true; Settings → General). Stop reads only the transcript bytes appended since the last Stop, and records each reply's LFG line (`skill`, `tools`, `not-used` with its reason, or `missing`) in `usage.db` table `replies`, shown on the Usage page.
PreToolUse blocks with exit code 2 + a reason on stderr: `Blocked by LFG rule <N>: <why>. A human must do this in their own terminal.`

## Files LFG writes (formats)

- `reviews/<rid>/pr-<n>/` — the Reviews page: `meta.json` (worktree, reviewed head, merge-base, base, the Claude session id, `posted`), `draft.json` (summary, event, ratings `{area, ai, mine, why}`, questions `{id, ask, why, answer}`, comments `{id, path, line, body, severity, source, include}`, context), `triage.json` (your own PR: `threads` by id `t-<comment id>` / `r-<review id>` / `c-<comment id>` with the comment, `worth`, `why`, `fix`, `reply_fix`, `reply_wont`, `wont_reasons`, your `decision` and `reply`, and `posted`), `chat.jsonl`, `job.json` while the AI works, `job-<k>.in/.out` (prompt and raw `claude -p` JSON output). `reviews/<rid>/pending.json` caches the review-requested list.

- `repos/<rid>/commands.json` — `{"lint", "lint_fix", "types", "test", "build", "start"}` → shell command strings; detected once, then hand-editable. The gate only runs commands the guard allows.
- `repos/<rid>/shipcheck.json` or `<run>/shipcheck-routes.json` — `{"port": 8080, "health": "/healthz", "routes": [{"path": "/", "status": [200], "optional": false, "needs_credential": false}]}`. Routes with `needs_credential: true` are skipped (LFG never uses a real credential).
- `<run>/ready.json` — `{"ts", "green", "commands_file", "commands_detected", "checks": [{"name", "cmd", "exit", "seconds", "tail"}], "missing"}`; `exit: null` = not configured.
- `<run>/05-secure.json` — `{"ts", "mode", "target", "inventory", "scanners", "findings": [{"id","type","item","where","severity","blocking","evidence","fix","source"}], "verdict": "safe|safe with caveats|don't", "blocking", "offline", "licences_checked": [names]}`.
- `<run>/05-pentest.json` — normalized Strix findings `{"id","title","severity","location","evidence","fix","false_positive"}` plus `summary` counts and `gate4: pass|fail` (fail on any critical/high).
- `<run>/06-review.json` — expert-review findings; `lfg feedback add` records verdicts in `feedback/<rid>.json`.
- `<run>/07-shipcheck.json` — part A (Docker) checks, part B (10-item checklist), cleanup verification.

## Secrets in tool output

PostToolUse cannot rewrite output, so LFG **detects + warns + audits**: when output matches a secret pattern the hook returns `{"decision":"block","reason":...}` telling the model not to repeat it, and writes an audit entry (pattern name only, never the value).

## MCP servers

Declared by the plugin in `plugin/.mcp.json`, so they exist only where the plugin is on: `code-review-graph`, `dev-graph`, `second-brain`, `headroom`, each started as `lfg mcp <name>`. Tool names are `mcp__plugin_lfg_<server>__<tool>`, which is what the agents' `tools` lists use. Linear is the user-scope `linear` server (the Linear pack adds one only if you have none), so its tools are `mcp__linear__*`. Ollama is checked only by `lfg pentest` preflight.
