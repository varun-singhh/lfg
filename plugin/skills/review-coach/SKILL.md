---
name: review-coach
description: >
  Review your code before you submit. Get feedback like a senior engineer would give.
  Catches early warnings (security patterns, N+1 queries) using heuristics.
  Use before creating a PR or when you want feedback on your code.
author: Varun Singh
phase: prove
lanes: [standard, full]
reads: [git diff]
writes: []
auto-trigger: false
---

## Steps

1. **Run review coach engine**:
   ```bash
   lfg review-coach [--base BRANCH] --json
   ```

   This engine is a heuristic first pass using regex patterns. Every finding has `file` and `line`. You must read the flagged code yourself before telling the user about it. Drop false positives.

2. **Parse the output**:
   - `risk_level`: HIGH_RISK (critical), NEEDS_WORK (high), READY_TO_REVIEW
   - `counts`: by severity (critical, high, medium, low)
   - Each issue: `file`, `line`, `severity`, `message`, `suggestion`

3. **Present the feedback**:
   - Start with risk level and counts
   - For each issue: show file:line, the message, and read that line to verify
   - Offer fixes where appropriate
   - Acknowledge false positives exist

4. **No "Good practices" count**: This engine doesn't count those. Focus on actionable issues.

## Output

- Risk level (HIGH_RISK / NEEDS_WORK / READY_TO_REVIEW)
- Counts by severity
- Issues: each with file:line, severity, message
- Suggestions for fixes

## Rules

- N+1 is only flagged when a loop body (next ~5 added lines) contains a DB/HTTP call pattern (`.execute(`, `.query(`, `fetch(`, etc.) - not every loop.
- innerHTML: only flagged when the assigned expression contains `${` or `+` and not `esc(`.
- If `--base` not given: uses merge-base with `origin/HEAD`'s branch if it exists, else `main`, else `master`.
- No "good practices" counting, no 0-100 score - just risk level and counts.
- **Important**: This is a heuristic engine. Verify each finding by reading the code. Drop false positives before reporting to the user.
