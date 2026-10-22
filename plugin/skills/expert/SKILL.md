---
name: expert
description: >
  Three-axis review of the current change: Standards (repo standards + smell baseline), Spec
  (does it do what the brief and tickets asked) and Blast radius (graph impact, flows,
  Principles and Invariants), ending in approve / changes / block. Use when the user says
  "review this", "second opinion", "what could this break?", or after /check and /secure pass.
author: Varun Singh
phase: prove
lanes: [express, standard, full, hotfix]
reads: [diff, 01-brief.md, 02-design.md, tasks.json, 04-qa.md, 05-secure.json, 05-pentest.json]
writes: [06-review.json]
auto-trigger: false
preflight: graphs
adapted-from: mattpocock/skills/code-review (MIT, © 2026 Matt Pocock)
---

# /expert: Standards · Spec · Blast radius

## Step 0: preflight

1. `lfg graphs ensure`. Non-zero exit: stop and show its output. Continue on a stale graph only if the user typed `--allow-stale`.
2. `lfg run path`. Exit 1: `lfg run new review-<branch-slug>`.
3. `lfg rule graph-first`.

## Steps

1. **Pin the base.** Default: `git merge-base HEAD origin/main`; use the user's ref if given. The change is `git diff <base>` (working tree, since nothing is committed) plus untracked files from `git status --porcelain`. Empty change or bad ref → stop here.
2. **Shape the change.** `get_minimal_context_tool`, then `detect_changes_tool` (risk-scored changed nodes) and `get_review_context_tool` for scoped snippets. These are the review set; read other files only if a finding needs them.
3. **Gather each axis's sources.**
   - **Standards:** the repo's `CODING_STANDARDS.md` / `CONTRIBUTING.md` / lint docs, `~/.lfg/repos/<repo-id>/docs/`, plus the smell baseline below.
   - **Spec:** `01-brief.md` acceptance criteria, `02-design.md`, `tasks.json` steps and `verification`, and the Linear issue (read only). No spec anywhere → ask once; if there is none, the Spec axis reports "no spec available".
   - **Blast radius:** `get_impact_radius_tool` and `get_affected_flows_tool` on the changed nodes; the dev-graph `Component`s they map to and their `Principle`, `Invariant`, `Gap` and `Decision` nodes; `04-qa.md` (untested nodes), `05-secure.json`, `05-pentest.json`.
4. **Review the three axes in parallel subagents** (use the `expert-review` agent; Opus in Hotfix, Sonnet diff-only in Express). Each gets the base ref, the review set and only its own sources, and returns findings in the schema below, under 400 words of prose.
   - **Standards:** each breach of a documented standard (cite file + rule) is a hard finding. Baseline smells are always judgement calls labelled "possible <smell>", and a documented repo standard overrides them. Skip what tooling already enforces.
   - **Spec:** requirements missing or partial; behaviour nobody asked for (scope creep); requirements that look done but are wrong. Quote the spec line.
   - **Blast radius:** callers and flows the change alters without tests or without the brief mentioning them; any `Invariant` or `Principle` the change touches or violates (cite the node); crossings between communities (bridge nodes); unresolved secure/pentest findings on affected flows.
5. **Aggregate without reranking.** Keep the three axes separate; a pass on one never offsets a fail on another.
6. **Verdict.** `block` if any finding is `blocker` (a violated `Invariant`, a wrong core requirement, an open reachable high/critical security finding). Else `changes` if any `major`. Else `approve`. `block` → **checkpoint 4**: stop and ask the user.
7. **Feed the store.** Copy the findings to the feedback store (`~/.lfg/feedback/`) so the Reviews viewer shows them. Tell the user they record accept/reject with `lfg feedback add <id> accept|reject [--note …]`; run it yourself only with a verdict the user stated.

**Smell baseline** (judgement calls; fix in brackets): Mysterious Name [rename]; Duplicated Code [extract the shared shape]; Feature Envy [move to the data it uses]; Data Clumps [bundle into a type]; Primitive Obsession [small domain type]; Repeated Switches [polymorphism or one shared map]; Shotgun Surgery [gather into one module]; Divergent Change [split by reason to change]; Speculative Generality [delete until needed]; Message Chains [hide the walk]; Middle Man [call the target]; Refused Bequest [composition].

## Output

`06-review.json` in the run folder:

```json
{ "run": "<run-id>", "base": "<sha>", "verdict": "approve|changes|block",
  "summary": { "standards": "<n> findings, worst: …", "spec": "…", "blast_radius": "…" },
  "findings": [ { "id": "<run-id>-R1", "axis": "standards|spec|blast_radius",
    "severity": "blocker|major|minor|nit", "file": "src/x.ts", "line": 42,
    "principle": "<standard rule, spec line, or Principle/Invariant id; null for a smell>",
    "message": "…", "fix": "…" } ] }
```

Reply with three sections (`## Standards`, `## Spec`, `## Blast radius`), the verdict, and one line per axis: count and worst finding. For `changes`: each item must be fixed (via `/fix`) or deferred with a linked `Issue` before gate 5 passes.

## PR mode (the dashboard's Reviews page)

When the prompt says **PR mode**, you are reviewing someone else's pull request for the human reviewer, in a
review worktree (`<repo>.worktrees/review-pr-<n>`, detached at the PR head). It changes these things:

- **No run.** Skip `lfg run path` / `lfg run new`. Write no files: no `06-review.json`, no feedback store, no
  dev-graph `Issue`. The worktree is read-only for you. Never write to GitHub; the reviewer posts.
- **Base** is the merge-base the prompt gives; the change is `git diff <merge-base>..HEAD`.
- **Spec** is the PR description (and a linked Linear issue, read only). No brief.
- **Brains are required.** Run `lfg graphs ensure`, then pull the dev-graph `Component`s the change touches and
  their `Principle`, `Invariant`, `Decision` and `Gap` nodes, plus second-brain notes on the same areas. Cite each
  one you rely on; list them in `context`.
- **Grill the reviewer.** Besides findings, rate each area (Correctness, Design, Tests, Security, Readability,
  Fits the codebase) 1-5 with a one-line reason, and ask the questions a sharp reviewer needs answered before
  approving: assumptions the author made, cases nobody tested, trade-offs to accept or push back on.
- **Comments are drafts for the human.** Put each on a changed line (`path`, `line` on the new side) when you can,
  written as it would be posted: what, why, and the fix. No praise padding.
- **Talking it through.** Later messages in the same session are the reviewer pushing back, answering your
  questions or asking for changes. Re-check the code before conceding a point; when the draft changes, end with
  the json block of the keys you changed, as the prompt describes.

## Comment triage mode (the Reviews page, on your own pull request)

When the prompt says **comment triage mode**, the PR is the user's own and the threads are what reviewers (people
and bots) said about it. Same read-only rules as PR mode, and brains are required. For each thread:

- **Check it against the code**, not the commenter's confidence: open the file at the line, follow callers with
  the graphs, and look for a dev-graph `Principle`, `Invariant` or `Decision` that settles it.
- **worth (0-100)**: how likely fixing it is the right call. 90+ = a real bug or a broken rule; 50-80 = a fair
  improvement; under 30 = wrong, already handled, out of scope or taste. Say why in one or two sentences.
- **Replies** are ready to post as the user: `reply_fix` says what will change, `reply_wont` gives the real
  reason, and `wont_reasons` offers 2-4 alternative complete replies (already handled at X, out of scope (follow-up
  ATO-…), intentional per Decision Y, the bot misread Z). Short, specific, polite, no filler.
- Later messages are the user asking about a thread; re-check the code before changing your view.

## Rules

- **A run filed under another repo** (this repo's tasks live in another repo's run, e.g. `/lfg` resumed that repo's handoff): write this repo's results as `06-review-<repo>.json`, with `<repo>` the repo's folder name (e.g. `aegis-compliance-portal`), never over the run's own files. The dashboard shows them under this repo, and the owner repo keeps its own.
- Review only: the reviewer edits no code. Findings cite `file:line` and never quote secrets.
- Out-of-scope problems become a dev-graph `Issue`, not an edit.
- Deferrals go to a dev-graph `Issue`. Never create a Linear issue for one unless the user asks; Linear writes (issues, comments) only after an explicit yes on the exact text.
