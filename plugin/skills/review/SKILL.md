---
name: review
description: >
  Reviews someone else's PR, or every PR on a Linear ticket, and saves all findings at once as a review record
  you triage (keep, drop, edit) and then post yourself. Re-reviews check whether earlier comments were fixed,
  answered or ignored, look for bugs in the new commits, and hunt for ones the first pass missed. Use when the
  user says "/lfg:review 123", "review ATO-1234", "re-review this PR", "check if they fixed my comments".
author: Varun Singh
phase: prove
lanes: [express, standard, full, hotfix]
reads: [PR diff, PR description, Linear ticket, AGENTS.md, review sources, earlier review record]
writes: [~/.lfg/reviews/<owner>__<repo>/<number>.json]
auto-trigger: false
preflight: graphs
---

# /lfg:review: review a PR, save every finding, let the user decide

## Step 0: preflight

1. If the current folder is a checkout of the PR's repo: `lfg graphs ensure`. Non-zero exit: stop and show its
   output (continue on a stale graph only if the user typed `--allow-stale`). PRs in repos not checked out here are
   reviewed from GitHub alone; say so.
2. `lfg rule graph-first` and follow it for code lookups in a local checkout.

## Steps

1. **Targets.** A PR number, `owner/repo#12` or a PR URL is one target. A Linear ticket id: read the ticket
   (Linear MCP) and its attachments, then `gh search prs <ID> --state open --json repository,number,title` for any
   it doesn't link. Every PR is its own target, saved with `--ticket <ID>`.
2. **Context, per target.** `lfg review context <pr>` (JSON). If `mine` is true, say so and stop for that PR
   unless the user asked anyway: GitHub won't take an approval from its author.
3. **Method.** Read every file in `sources`, in order; later files win. There may be several methods in it (LFG's
   built-in one and one or more of the user's own review skills): apply all of them together, as one review. A
   check any of them asks for is done; where two disagree (a severity, a score rule, how a comment reads), the later
   one wins. Use them for what to look for, how to
   judge severity and score, and how to word comments. **Skip any step in them about presenting findings one at a
   time, waiting for the user, paste blocks or posting:** this skill's Output replaces those. Paths inside a source
   resolve against its own folder, then its parent folders. Name any `missing_sources` to the user.
4. **Repo rules.** Read every file in `agents_md` with the `read_agents_md` command (the PR's version, not main's).
   They outrank the sources.
   **Settled by the user.** `settled` in the context is what they already decided, across PRs: `passed` (findings
   they passed on for good, in this repo or every repo, each with its `title`, `issue` and `severity`; none on Fresh
   eyes, which never sees their Fix/Pass choices), `decisions` (saved from earlier reviews' discussions and answers, in
   this repo's dev-graph) and `notes` (saved to their second-brain: personal, each names the PR it came from, so apply
   those that fit this repo). Read them before filing anything.
   Never file a finding one of them covers, in other words or at another line. Raise it only if in this PR it is
   clearly worse than when it was settled (higher severity, wider reach, a new way to hit it) and say in `body` what is worse;
   a decision saying something *is* a real problem means keep flagging it. A name in `unavailable` is a graph that
   couldn't be read: say so in the summary.
5. **Intent: the ticket and the description.** Always, with any method and in Fresh eyes too (neither is an earlier
   review's opinion). Context gives `description` (the PR body) and `ticket`: the Linear id its branch, title or
   description names. A ticket the user named (step 1, or the prompt) wins over it; a ticket's PRs reviewed together
   share it. Read the ticket with the Linear MCP (`get_issue`), and `list_comments` when its description is thin: scope
   changes and acceptance criteria often live there. No ticket, or the read fails: carry on from the description and
   the code, and say so in `intent`. Never stop or ask over it.

   Hold the ticket and the description lightly: either can be wrong, out of date, vague or silent on something, and
   the review should still be good. Treat them as the author's claims about the change, not a spec to grade line by
   line, and check each against the code and against each other:
   - **The ask.** List what the ticket asks for (its goal and acceptance criteria). Anything it asks that the diff
     doesn't do is a finding on the code (`about: "code"`, `file` null unless one file is plainly where it belongs),
     unless the description or a ticket comment narrows the scope on purpose: then it's a note, at most.
   - **Claims.** What the ticket or the description says about current behaviour, the root cause or what the PR does
     ("fixes the timeout by…", "no behaviour change", "adds tests for…"): verify each in the code. One that isn't
     true is a finding with `about: "ticket"` or `"description"`.
   - **Agreement.** Ticket and description that contradict each other, or a ticket whose criteria contradict its
     own problem statement: say which one the code follows and whether that's the right one.
   - **Gaps.** Criteria too thin to define done, or a description that doesn't say what the PR does or how to test
     it: say what's missing, without inventing criteria and grading against them.
   - **Drift.** A diff that reflects a later, better understanding than the ticket is the code diverging correctly,
     not a defect: a `note` saying the ticket should be updated before it closes.
   - **Scope creep.** Work well beyond the ask: a finding when it should be its own PR, a question when it might be.
   Severity for findings `about` the ticket or description: usually `minor` or `note`, and never deducted for being
   absent alone (no ticket or no description is said in `intent`, not filed). `major` only when a wrong ticket or
   description is steering the change to the wrong fix, or would mislead someone merging or testing it.
6. **Read the change.** `gh pr view <n> -R <repo> --json files` and `gh pr diff <n> -R <repo>`. Read the code
   around each hunk at `head_sha`: from a worktree (`git fetch origin pull/<n>/head:review/pr-<n>` then
   `lfg worktree new review/pr-<n>`) when the repo is local, else `gh api repos/<repo>/contents/<path>?ref=<sha>`.
7. **First review** (`re_review` false): one full pass over the whole diff, following the method. Every finding
   gets `since: "first"`. **Fresh eyes** (`fresh_eyes` true) is a first review on a PR that has earlier ones: skip
   steps 8 and 9, leave `prior` and `echoes` empty, and don't look for earlier reviews or others' comments (the
   commands that show them refuse). LFG notes repeats itself after saving.
8. **Re-review** (`re_review` true): `lfg review show <pr> --json` and `lfg review threads <pr>`, then three passes:
   - **Earlier findings.** For each row in `threads.posted`, read the code at the new head and set a state:
     `fixed` (the problem is gone, verified in the code), `replied` (the author answered and the issue is still
     open: say whether the answer holds up), `withdrawn` (their answer is right, or you were wrong),
     `resolved-unchanged` (thread resolved but the problem is still there), `ignored` (no change, no reply) or
     `open`. `file_changed` and `outdated` are hints only; the code decides. Do the same for each row in
     `threads.unposted` (kept or never decided, and never posted; `fixed_in` is the commit LFG's Fix made):
     `fixed`, `ignored` or `open`, with no thread to read. Both go in `prior`.
   - **Questions asked on GitHub.** `threads.asked` lists questions the user posted for the author, with the
     author's `replies`. A reply is the author's answer: let it settle the findings it bears on (update or withdraw
     them in `prior`, or file what it reveals), the same as an answer in `answered`. If it doesn't settle the
     question, ask what is still open in `questions`, saying what the author said; never ask the same thing again
     unchanged. No reply yet: leave it, it stays open.
   - **Settled.** `threads.settled` lists findings the user dropped on this PR, and step 4's `settled` what they
     decided before. They decided; never raise one again in any pass, in other words or at another line. Only if later
     commits made that exact problem worse, file it with `since: "new"` and say in `body` what changed since it was
     dropped.
   - **New commits.** Review `last_reviewed_sha...head_sha` only (`gh api repos/<repo>/compare/<a>...<b>`).
     Findings get `since: "new"`.
   - **Missed.** One more pass over the whole PR for what earlier passes missed. Findings get `since: "missed"`.
     Never re-file an earlier finding: track it in `prior` instead, and never re-raise a settled one.
   **New full review** (asked for one on a PR with earlier reviews): review the whole PR from scratch, findings with
   `since: "first"`, and still do the **Earlier findings** and **Settled** passes above, so every finding still open
   is tracked in `prior` rather than lost or filed twice.
9. **Other reviewers.** `lfg review others <pr>`: what people and bots (CodeRabbit, Sonar, other agents) already
   said, inline (with `file` and `line`) or in the conversation. For each finding someone already raised, at the same
   spot or the same idea in other words, list them in `echoes` and say so in `body`: agree with them by name and add
   only what is new ("@coderabbitai flagged this too; the part it missed is ..."). If they said everything you would,
   keep it as a short agreement rather than a second copy of their comment. Never echo LFG's own earlier comments
   (those are in `prior`).
   **On the user's own PR** (its author is the `gh` user) also triage what others said: every comment from
   `lfg review others` that asks for a change, isn't answered or resolved, and isn't already one of your findings
   becomes a finding with `raised_by` (`who`, `url`, `comment_id`, `kind`, `bot` from that entry), `worth` (`fix`:
   it is right and worth the change; `maybe`; `skip`: wrong, already handled, or not worth it, and say why in
   `issue`), your own `severity`, and `reply`: what the user would answer in that thread if they pass on it, in
   their voice (one or two sentences: why not, or what was done instead). `body` stays your own read of it.
10. **Questions.** Anything you couldn't settle from the code, the ticket or the sources and that would change a
   finding (intent, a product decision, whether a caller exists elsewhere) goes in `questions`, at most five, each
   with `why` it matters. Don't ask what the code can answer. Give `file` and `line` when a question is about one
   place in the code: the user can post it there for the PR's author, so write `ask` so the author can answer it
   (plain, no finding ids) and keep `why` for the user. `lfg review context` lists in `answered` every
   question the user already answered about this PR, from any earlier review: take each answer as a fact, never ask
   it again (in other words either), and let it settle the findings it bears on. Fresh eyes too: answers aren't an
   earlier review's opinion. Also check `settled.decisions` and `settled.notes` before asking; a saved one is an answer.
11. **Save.** Write the JSON below to a scratch file and `lfg review save <pr> --file <path> [--ticket <ID>]`.
   Fix and re-run on a validation error.

## Output

The file passed to `lfg review save`:

```json
{"summary": "two or three sentences: what the PR does and whether it is mergeable",
 "verdict": "mergeable|almost|not", "verdict_why": "one line: what stands between it and merging",
 "approach_notes": ["..."],
 "findings": [{"title": "short name", "severity": "blocker|major|minor|nitpick|note",
   "file": "path/in/repo.ts", "line": 42, "issue": "one line", "fix": "one line",
   "detail": "evidence for the reviewer: what you checked and where; not posted",
   "body": "the comment the author reads, in the voice the sources describe",
   "origin": "introduced|exposed|pre-existing", "since": "first|new|missed", "about": "code|ticket|description",
   "echoes": [{"who": "coderabbitai", "url": "https://github.com/...#discussion_r1", "said": "what they said, short",
               "bot": true}],
   "raised_by": {"who": "coderabbitai", "url": "...", "comment_id": 123, "kind": "inline|review|comment",
                 "bot": true},
   "worth": "fix|maybe|skip", "reply": "only with raised_by: the user's answer if they pass on it"}],
 "intent": {"ticket": "ATO-4223 or empty when there is none", "ticket_title": "its title in Linear",
            "read_ticket": true, "read_description": true, "delivers": "all|most|part|unclear",
            "note": "one or two sentences: what the ticket asked, what the PR does of it, and what is off in either"},
 "questions": [{"ask": "is the old export endpoint still called by the mobile app?", "why": "if so, 1.2 is a blocker",
                "costs": 12, "file": "src/export.ts", "line": 88}],
 "prior": [{"id": "1.3", "state": "fixed|replied|withdrawn|resolved-unchanged|ignored|open", "note": "why"}]}
```

`line` is a line in the PR's version of the file, or null for a finding about the PR as a whole. `about` is
`code` (the default) for a problem in the diff, `ticket` or `description` for one in the Linear ticket or the PR's
description (step 5); those have `file` and `line` null. `read_description` is false when the PR has no
description, or one that says nothing about what it does.

A question that holds the verdict back costs points (the method's Score rule): put that cost in its `costs` (4, 12 or
25; leave it out when the question costs nothing). LFG works out the score as 100 minus what is still open, so don't
give one: anything that holds the PR back must be a finding or a question that costs points. `verdict`: `mergeable` when nothing
should hold it up, `almost` when only small fixes stand in the way (minors, a
failing check with an obvious cause, a question to answer), `not` with any blocker or major, or a design problem.

Then show the user, per PR: the intent line (ticket id and title, how much of it the PR does, the note), the
earlier-finding states (re-review), the score, then one row per finding: id,
severity, title, `file:line`, the `issue` line. All at once, not one at a time. Then triage on their word:
`lfg review mark <pr> <id>... --keep|--drop`, and for an edit `--body-file <path>` with the new comment. When every
finding is decided, give the posting command for them to run, in a fenced block:
`! lfg review post <pr> --event request-changes|approve|comment [--body "..."]` (`--dry-run` shows the payload).

## Rules

- Never post, comment, approve or request changes on GitHub yourself, by any route. Posting is the user's.
- Never edit a review source or AGENTS.md during a review. When a dropped finding shows a source is wrong, propose
  the exact change and let the user make it.
- A finding the code doesn't support is dropped before saving, not saved and flagged.
