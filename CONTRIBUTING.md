# Contributing to LFG

Thanks for helping. LFG is a Claude Code plugin with a small Python CLI (standard library only, Python 3.9+) inside it.

## Set up

```bash
git clone https://github.com/varun-singhh/lfg.git && cd lfg
python3 -m unittest discover -s tests
```

You don't need to install LFG to work on it. The tests run against a temporary `HOME` and `LFG_HOME` with a fake `claude` CLI, so they never touch your real `~/.claude` or `~/.lfg`. To try your change for real, run `./install.sh` (it shows its plan first) and `lfg uninstall` when you're done.

## Before you open a pull request

```bash
python3 -m unittest discover -s tests
uvx ruff check plugin/lib plugin/bin/lfg tests
shellcheck install.sh bootstrap.sh
plugin/bin/lfg doctor --selftest      # guard self-test (the tool rows may show missing tools; that's fine)
claude plugin validate plugin         # if you have Claude Code
```

CI runs the same checks on macOS.

## Releases

Changes reach users as numbered releases, not every merge: each pull request adds its notes under "unreleased" in
`CHANGELOG.md` and `plugin/releases.json`, and a release PR (`plugin/bin/lfg release prepare <x.y.z>`) names them and
bumps the version. Once merged, the merge commit is tagged `v<x.y.z>`. The details are in `CLAUDE.md`.

## Ground rules

- **Do no harm to the user's setup.** Any write outside `~/.lfg` must go through `plugin/lib/lfgcore/claudecfg.py`, so it is backed up, recorded in the ledger and undoable, and it must only happen after the user agreed (`lfg setup` plan, `lfg enable`, `lfg add`, or the dashboard with the edit key). Add a row to the *Footprint* table in `CONTRACT.md` and a test that undo restores the file.
- **Hooks must stay fast and scoped.** They run on every tool call. Keep the "is LFG on here?" check first and keep heavy imports lazy.
- **Standard library only** for the CLI and dashboard. The dashboard loads nothing from outside 127.0.0.1.
- **Guard changes need tests.** Add cases to `guard.SELFTEST` for every new block and every new allowed command.
- **Skills and agents are loaded into Claude's context,** so keep them short (skills under 120 lines), follow the frontmatter in `CONTRACT.md`, and load rule modules with `lfg rule <name>` instead of copying them in.
- **Bump the version** in `plugin/.claude-plugin/plugin.json` (the only place it lives) and add a `CHANGELOG.md` entry for anything user-visible.

## Reporting bugs

Open an issue with `lfg version`, the output of `lfg doctor`, and what you expected. Never paste tokens, `.env` contents or private code. For security issues, see [SECURITY.md](SECURITY.md).
