# Review method (LFG default)

The default way `/lfg:review` finds and judges issues. Replace it by pointing `review.sources` in
`~/.lfg/config.json` at your own files, or add to it in `~/.lfg/overrides/review/` (read last, wins on conflict).

## What to look for

1. **Intent first.** Read the PR's description and its Linear ticket, and judge the diff against what it was meant to
   do, as `/lfg:review`'s Intent step says: missing pieces of the ask are findings, and so is work well beyond it that
   belongs in its own PR. Either can be wrong or out of date; check their claims against the code.
2. **Bugs the PR introduces.** Read enough of the surrounding code to judge each hunk; never review a hunk blind.
3. **Latent bugs the PR exposes.** A new caller that now reaches an existing broken edge case is a real finding even
   though the broken line didn't change. Mark these `origin: exposed`.
4. **Pre-existing bugs** found along the way: report them, marked `origin: pre-existing`, so the author can tell
   them apart from what the PR introduced.
5. **The repo's own rules.** Every AGENTS.md (and CLAUDE.md) that `lfg review context` lists outranks this file.
6. **The approach.** Only when there is a specific, better alternative that avoids a specific failure mode. At most
   two, as `approach_notes`, never as findings.

## Before keeping a finding

- Re-check it against the code. Would it actually misbehave, on which input, on which path? Drop it if not.
- Findings are statements, not questions. If you could answer the question by reading more, read more.
- A branch that is behind its base produces findings about staleness, not about the code: check before filing.

## Severity

| Severity | Means |
|---|---|
| blocker | Misbehaves on a realistic path: data loss or corruption, a security or access gap, a crash on common input |
| major | A real bug on a less common path, or wrong-but-recoverable behaviour |
| minor | No bug today but a real cost: duplication, a convention break, a missing type, an avoidable inefficiency |
| nitpick | Cosmetic or taste |
| note | Not a defect: context for the author, never deducted |

Score: LFG works it out, always 100 minus what is still open: blocker -25, major -12, minor -4, nitpick -1 (once per
kind of nitpick), and an open question that could stop the merge costs what the finding it could become would (-4 if
it would be minor, -12 if major, -25 if a blocker). Floor 0. Nothing comes off any other way, so every problem that
holds the PR back is a finding or a question that costs points, never a deduction in the summary.

## Comments

The `body` of a finding is what the author reads on GitHub. Write it to them: what is wrong, where, what happens
because of it, and the fix in one or two sentences. Plain words, no severity labels, no "I think" padding. Prefix
nitpicks with `nit:`.
