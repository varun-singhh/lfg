Rule module: remember · LFG · author Varun Singh

# remember: offer to save what matters, ask before every write

People forget why things are the way they are. When the conversation or the work turns up something durable, offer to save it to dev-graph or second-brain. Nothing is written until the user picks where it goes.

## What counts

| Goes to | Kind | Example | Stored query |
|---|---|---|---|
| dev-graph (team, this repo) | `Decision` + why | "we use Postgres advisory locks, not Redis, because…" | `record_decision` (`supersede_decision` if it replaces one) |
| dev-graph | `Learning` (gotcha, root cause, landmine) | "the billing webhook retries 3× and is not idempotent" | `add_learning` |
| dev-graph | `Learning` about setup: running, deploying or reaching something | "atomus-local-mcp needs its env vars set by hand to run locally" | `add_learning` (kind `gotcha`), then `lfg knowledge tag <slug> --topic setup` |
| dev-graph | `Invariant` / `Principle` | "every tenant query filters by org_id" | none: `schema_get`, then insert |
| dev-graph | `Issue` (follow-up, deferral) | "the CSV export times out over 50k rows" | `create_issue` |
| second-brain (personal, every project) | `Note` kind `preference` / `insight` / `question` / `idea` | "I want small PRs with a test first" | `save_note` (LFG's, keeps the text) |
| second-brain | `Person` | "Alex owns the payments service" | `add_person` |

Not worth saving: anything already in the code, a commit or a file in the repo; one-off task details; restatements of an LFG rule; guesses. Never secrets, credentials or other people's private data.

Something every session must know without searching (which account to use for prod, a command that must always
carry a flag) is not a Learning: offer to add it to the user's `~/.claude/CLAUDE.md` instead, as exact text.

After saving a `Decision` or `Learning`, tag it with the repo and feature it belongs to when you know them:
`lfg knowledge tag <slug> --repo <repo folder name> --feature "<epic or feature name>"`.

## When to offer

- The user states a decision, a constraint, a preference, or "always/never do X".
- Work uncovers a root cause, a landmine, or a reason something is odd.
- The user corrects you in a way that will matter next time. When corrections are on (the session is told so at the
  start), queue it with `lfg corrections add` instead of offering it here: the user reviews it on the Corrections page.
- The user asks to remember, note or save something: that is `/note`, run it.

Offer at a natural pause (the end of your reply or of a stage), not mid-task. At most 3 items per offer. Don't offer again what the user skipped in this session.

## How to ask

End the reply with one block. Each item has the exact text to store, the proposed graph and kind, and one line on why:

```
Remember?
1. [dev-graph · Decision] "Use advisory locks for job claims; Redis locks lost jobs on failover." Why: explains the odd lock code in jobs/claim.py.
2. [second-brain · preference] "Wants a failing test before any fix." Why: applies to every repo.
Reply e.g. "1 dev, 2 brain", "both", "edit 1: …" or "skip".
```

Always ask, even when the destination looks obvious. The user's choice wins: they can move an item to the other graph, save it to both, edit the text, or skip it.

## After the answer

1. Only for the items the user approved: de-duplicate first with LFG's keyword queries (`find_decisions`, `find_learnings`, `find_invariants`, `find_notes`; see `lfg rule graph-first`). A near match becomes an update proposal, not a new node.
2. Write with the Omnigraph MCP `mutate` tool, to the graph the user picked. Link to the repo's `Component` or `Project` and the run id when there is one.
3. Confirm in one line per item: graph, kind, node id.
4. Graph down (`lfg omnigraph status`): say so, keep the approved items in the run's `progress.md` under "To remember", and offer them again next session.

## Subagents

Subagents cannot ask the user. They add a `## Remember?` section to their output file with the same item format. The main session puts those items in its next offer and writes nothing until the user answers.
