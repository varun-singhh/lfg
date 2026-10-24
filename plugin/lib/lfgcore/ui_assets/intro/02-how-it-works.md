# How it works

## 1. Turn LFG on in a repo

```bash
cd your-repo
lfg enable
```

Then start (or restart) Claude Code there.

## 2. Say what you want

```
/lfg:lfg add rate limiting to the public API
```

LFG asks a few questions until the goal is sharp, writes a brief with acceptance criteria, and plans the work as
small slices. Each slice is built test-first by an agent in its own git worktree.

## 3. Watch it, step in when it asks

Every request is a **run**. The dashboard's **Runs** page shows where it is: brief, plan, build, checks, review.
When something needs a decision, it's on **Home** under *Needs your attention*.

## 4. Review and ship

- **Insights → Your changes** lists the questions to ask before you approve.
- **Reviews** lets you talk to the diff: ask about a line, discuss a comment, decide what to fix.
- When it's ready, LFG says so. You commit and push.

## Not sure what to run?

Type `/lfg:which` and LFG suggests the next step, or `/lfg:wizard` for a guided run.
