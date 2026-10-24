# What LFG is

LFG turns Claude Code into your whole engineering loop. You say what you want; LFG plans it, builds it in small
tested slices, checks it and hands you a change that's ready to commit. You decide, review and ship. You don't
need to open an editor to do any of it.

## What it adds to Claude Code

- **A pipeline**: `/lfg:lfg <what you want>` runs grill → plan → build → check → secure → review → ship, and picks
  how much process the change needs (express, standard, full or hotfix).
- **Specialist agents**: product manager, architect, engineers, QA, security analyst and an expert reviewer. They
  hand work to each other through files in the run folder, never through chat history.
- **Guard rails, in code**: agents never push, deploy or read your secrets; every commit asks you first.
- **Understanding without an editor**: Insights, Reviews and the code map explain what changed, why the code
  looks the way it does, and where it's fragile.

## What stays yours

- [x] Pushing and merging
- [x] Deploying
- [x] Approving commits
- [x] Deciding what's worth building

Everything runs on your computer. LFG only turns on in the repos you pick (`lfg enable`).
