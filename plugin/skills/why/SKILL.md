---
name: why
description: >
  Explains why code looks the way it does: the commits that shaped a file, a
  function or a few lines, what each one changed and why, and the issues, tickets
  and pull requests they mention. Use when the user asks "why is this here?",
  "why was this changed?", "who added this and what for?", "what's the story
  behind X?", or is about to change code they don't understand.
author: Varun Singh
phase: helper
lanes: [express, standard, full, hotfix]
reads: [git log]
writes: []
auto-trigger: true
---

## Steps

1. **Find the code.** If the user named a function or class rather than lines, find its file and line range with
   code-review-graph (`semantic_search_nodes_tool`) or by reading the file. Ask only if it is still ambiguous.
2. **Get the history:**
   ```bash
   lfg why <file>:<start>-<end> --json     # or <file> for the whole file
   ```
   Each commit has `sha`, `author`, `date`, `subject`, `body`, `fix` and `refs` (issue numbers, tracker keys and PRs
   with links, built from the repo's remote and the Linear workspace; nothing is fetched).
3. **Read the important commits**, at most three: `git show <sha> -- <file>` for the ones whose message explains a
   decision or a fix. If a ref is a Linear key and the Linear tools are available, read that issue for the reason.
4. **Answer in plain words**, newest reason first:
   - one or two sentences: why the code is like this today;
   - the turning points: `sha` (date, author): what changed and why, with the issue or PR link when there is one;
   - fixes in this code (`fix: true`) and what they were for: these are what will break again if changed carelessly;
   - what to keep in mind before changing it.

Quote commit messages only as short phrases. Don't guess a reason the history doesn't show: say "the history doesn't
say why" instead.
