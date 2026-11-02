# Disk space

How much room LFG takes on your Mac: at install, as you use it, and for each optional pack.

**In short:** a fresh install takes about **0.7 GB**. Each project you use it in then adds its code map, usually tens to a few hundred MB. The optional packs range from almost nothing (Linear) to 12–27 GB (Pentest, with its local model).

Measured on an Apple-silicon Mac (macOS, LFG 0.3, October 2026). Your numbers will differ with your repos and tool versions.

## Fresh install (Core)

`./install.sh` installs only the Core pack unless you ask for more.

| What | Size | Notes |
|---|---|---|
| LFG source clone | 6 MB | 4 MB of it is git history |
| LFG's copy in `~/.lfg` (plugin, docs, skills) | 2.3 MB | |
| `uv` and `gh` (Homebrew) | 85 MB | Skipped if you already have them |
| Python 3.10 for the tools (downloaded by `uv`) | 70 MB | Shared by every `uv` tool |
| code-review-graph | 440 MB | 350 MB of it is tree-sitter grammars for ~160 languages |
| graphify | 120 MB | |
| **Total** | **≈ 0.7 GB** | |

Not counted: Homebrew, Python 3.9+ (from Xcode's command-line tools) and Claude Code, which the installer expects you to have.

`uv` keeps a download cache in `~/.cache/uv`. On macOS it shares file blocks with the installed tools (copy-on-write), so the cache adds little real space even though Finder and `du` count it again.

## As you use it

| What | Where | How big | When it goes away |
|---|---|---|---|
| Code map for each project | In the repo: `.code-review-graph/` and `graphify-out/` (git-ignored) | About 7–20× the repo's tracked source. Examples: 6 MB of source gives 43 MB; 25 MB of source gives 477 MB | Settings → Disk space offers it once a repo hasn't been synced for a while; it's rebuilt when you work there again |
| Graph pictures | Same folders (`graph.html`) | Up to ~65 MB per big repo | Settings → Disk space |
| Worktrees (Studio sessions in a worktree, PR reviews) | Next to the repo: `<repo>.worktrees/` | One checkout each: the repo's size without `.git` (30–60 MB here) | When you remove or merge them (Studio → All sessions, Reviews, or `lfg worktree`) |
| Runs, reviews, notes, sessions index | `~/.lfg/runs`, `reviews`, `repos`, `sessions` | A few MB | Settings → Disk space offers runs on merged or deleted branches |
| Files and images you drop into Studio | `~/.lfg/uploads` | Whatever you attach | When you delete them |
| Files and images dropped into a PR review chat before it moved into Studio | `~/.lfg/tmp/chat` | Whatever was attached | When you delete them |
| Security lookups (`/lfg:secure`) | `~/.lfg/secintel/cache` | Grows with use (236 MB after a few weeks here) | Not cleaned up yet (see below) |

## Optional packs

Turn them on in Integrations or with `lfg packs add <name>`.

| Pack | On disk | What takes the space |
|---|---|---|
| Linear | ~0 | Nothing installed; Claude Code's own MCP sign-in |
| Dictate | ~100 MB | On-device speech model and its Python environment (`~/.lfg/dictate`) |
| Knowledge graphs | ~0.5–0.7 GB | Omnigraph 440 MB; Node.js ~0.2 GB if you don't have it; your graphs (tens of MB) |
| Security | ~0.6 GB, plus the lookup cache | semgrep 240 MB, trivy 200 MB, hadolint 100 MB, osv-scanner 50 MB, zizmor 20 MB, gitleaks 15 MB, actionlint 6 MB |
| Headroom | ~1.8 GB | The proxy and its libraries: PyTorch 410 MB, tree-sitter 350 MB, pyarrow and OpenCV 120 MB each, scipy… |
| Ship check | ~2 GB, plus images | Docker Desktop. Its virtual disk grows with the images you build |
| SonarQube | ~3 GB, plus Docker | Server image 2.6 GB; scanner cache 0.5 GB in `~/.lfg/sonarqube` |
| Pentest | ~12–27 GB, plus Docker | Local model 5–20 GB (picked by your RAM: qwen3 8b / 14b / 32b), Strix sandbox image 5.8 GB, Ollama 0.6 GB, Strix 65 MB, LuLu 9 MB |

With everything on, expect roughly 20–35 GB, most of it the pentest model and Docker images.

## Seeing and freeing space

- **Settings → Disk space** shows what `~/.lfg` and each repo's graphs take, and deletes only what is safe: idle graphs, graph pictures, runs on merged or deleted branches, and everything for repos whose folder is gone.
- **Turning a pack off** (`lfg packs remove <name>`) stops what it runs but keeps its tools installed. To get the space back as well:
  - `uv tool uninstall headroom-ai` (or `picklescan`, `code-review-graph`, `graphifyy`)
  - `brew uninstall semgrep trivy hadolint osv-scanner zizmor gitleaks actionlint` (Security), `brew uninstall omnigraph` (Knowledge)
  - `ollama rm <model>` (Pentest), and `docker image rm <image>` for the SonarQube and Strix images
  - `uv cache clean` drops `uv`'s download cache
- **`lfg uninstall`** undoes every change LFG made and removes `~/.lfg`. It leaves the tools above and the in-repo graph folders, and lists them so you can delete them yourself.

## Known gaps

- The security lookup cache (`~/.lfg/secintel/cache`) is never pruned: expired entries are skipped but not deleted.
- Graph databases written by older LFG versions to `~/.lfg/graphs/<repo>/crg/` are no longer used, but Settings → Disk space doesn't offer them yet. Graphs now live in the repo; the old copies can be deleted by hand.
- The pack descriptions in `lfg setup` understate two sizes: SonarQube says about 1.5 GB (it's ~3 GB on disk) and Pentest says about 10 GB (it leaves out the 5.8 GB Strix sandbox image).
