"""Shared helpers for LFG: paths, config, repo identity, run folders, process runner. Stdlib only, Python 3.9+."""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import threading

AUTHOR = "Varun Singh"

HOME = os.path.expanduser("~")
LFG_HOME = os.environ.get("LFG_HOME") or os.path.join(HOME, ".lfg")
# The plugin this code runs from (plugin/lib/lfgcore -> plugin) and the folder around it, which holds docs/ and
# CONTRACT.md: the source checkout, or ~/.lfg after install.
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LFG_ROOT = os.path.dirname(PLUGIN_ROOT)
# The installed plugin (what Claude Code loads in place from the local marketplace); the source tree in development.
PLUGIN_DIR = os.path.join(LFG_HOME, "plugin") if os.path.isdir(os.path.join(LFG_HOME, "plugin")) else PLUGIN_ROOT


def _version():
    try:
        with open(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")) as f:
            return json.load(f).get("version") or "0.0.0"
    except (OSError, ValueError):
        return "0.0.0"


VERSION = _version()  # single source of truth: plugin/.claude-plugin/plugin.json


def lfg_bin():
    """The `lfg` executable that background jobs and launchd agents call: the installed copy when there is one."""
    installed = os.path.join(LFG_HOME, "plugin", "bin", "lfg")
    return installed if os.path.isfile(installed) else os.path.join(PLUGIN_ROOT, "bin", "lfg")

# A one-shot `claude -p` that only reads its prompt and answers: no tools, MCP servers or slash commands. Without
# these every call carries the definitions of every connected tool (about 230k tokens with a few MCP servers), sent
# again at full price whenever the prompt cache has expired.
CLAUDE_BARE = ["--tools", "", "--strict-mcp-config", "--mcp-config", json.dumps({"mcpServers": {}}),
               "--disable-slash-commands"]

DEFAULT_CONFIG = {
    "models": {
        "product-manager": "sonnet", "architecture-designer": "opus", "software-engineer": "sonnet",
        "ai-engineer": "sonnet", "qa": "sonnet", "security-analyst": "sonnet",
        "expert-review": "opus", "lane-triage": "haiku", "briefing": "sonnet",
    },
    "lanes": {"express_max_files": 3, "express_max_lines": 80, "full_impact_nodes": 40},
    "graphs": {"full_rebuild_ratio": 0.3, "docs": True, "sync_timeout_s": 900},
    "shipcheck": {
        "prune_build_cache": False, "health_timeout_s": 90, "memory": "1g", "cpus": "1.5",
        "image_growth_warn": 0.2,
        "runner_image": "curlimages/curl:8.10.1",
    },
    "pentest": {"model": "", "ollama_url": "http://127.0.0.1:11434", "max_turns": 60},
    "ui": {"port": 7777},
    "storage": {"limit_mb": 500, "idle_graph_days": 30},
    "linear": {"team": "", "workspace": ""},
    "headroom": {"port": 8787, "mode": "cache", "scope": "off"},
    "guard": {"hardened": False, "allow_commit": False},
    "review": {"sources": [], "model": ""},
    "replies": {"lfg_tag": False},
    "sonarqube": {"telemetry": False},
    "dictate": {"shortcut": "option+space", "insert": "paste", "cleanup": True},
    "omnigraph": {
        "cookbooks_repo": "https://github.com/ModernRelay/omnigraph-cookbooks.git",
        "cookbooks_ref": "f797c6841c264d6b135aa1523e7c3fc023bbf3cd",
        "mcp_package": "@modernrelay/omnigraph-mcp@0.13.0",
        "version": "0.13.",
        "graphs": {"second-brain": {"graph": "brain", "port": 47181},
                   "dev-graph": {"graph": "dev", "port": 47182}},
    },
}


# ---------------------------------------------------------------- filesystem

def ensure_dir(path, mode=0o700):
    os.makedirs(path, mode=mode, exist_ok=True)
    return path


def lfg_path(*parts):
    return os.path.join(LFG_HOME, *parts)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def read_text(path, default=""):
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return default


def write_json(path, data, mode=0o600):
    ensure_dir(os.path.dirname(path))
    # a temp file of its own: the dashboard serves requests on threads, and two may save the same file at once
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_text(path, text, mode=0o600):
    ensure_dir(os.path.dirname(path))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def config():
    return _merge(DEFAULT_CONFIG, read_json(lfg_path("config.json"), {}))


# ---------------------------------------------------------------- where LFG is on (hot path: no subprocesses)

def git_main_root_fast(cwd):
    """The main checkout that contains cwd, found by walking up to `.git` (a linked worktree's `.git` file points at
    <main>/.git/worktrees/<name>). Pure filesystem, so hooks can decide in a few ms whether LFG is on here."""
    d = os.path.realpath(cwd or os.getcwd())
    while True:
        g = os.path.join(d, ".git")
        if os.path.isdir(g):
            return d
        if os.path.isfile(g):
            try:
                with open(g) as f:
                    line = f.read(4096).strip()
            except OSError:
                return d
            if line.startswith("gitdir:"):
                gd = os.path.realpath(os.path.join(d, line[7:].strip()))
                parts = gd.split(os.sep)
                if "worktrees" in parts:
                    return os.sep.join(parts[:parts.index("worktrees") - 1]) or d
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def enabled_state():
    """~/.lfg/enabled.json: {"everywhere": bool, "repos": {<main checkout realpath>: {"since": ts}}}."""
    st = read_json(lfg_path("enabled.json"), {}) or {}
    return {"everywhere": bool(st.get("everywhere")), "repos": st.get("repos") or {}}


def is_enabled(cwd):
    st = enabled_state()
    if st["everywhere"]:
        return True
    root = git_main_root_fast(cwd)
    return bool(root) and root in st["repos"]


# ---------------------------------------------------------------- processes

def clean_env(env):
    """env without macOS's MallocStackLogging* switches: a child that inherits one prints MallocStackLogging lines
    to stderr as it starts, so every python3 LFG runs would add a few. LFG never sets them; the terminal or app it
    was started from did."""
    for k in [k for k in env if k.startswith("MallocStackLogging")]:
        del env[k]
    return env


clean_env(os.environ)  # children started with subprocess directly, or os.execv, inherit the cleaned copy


def run(cmd, cwd=None, timeout=None, env=None, check=False, capture=True):
    """Run a command (list). Returns CompletedProcess with text output. Never uses a shell."""
    full_env = clean_env(dict(os.environ))
    if env:
        full_env.update(env)
    try:
        cp = subprocess.run(cmd, cwd=cwd, timeout=timeout, env=full_env, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    except FileNotFoundError:
        cp = subprocess.CompletedProcess(cmd, 127, "", "command not found: %s" % cmd[0])
    except subprocess.TimeoutExpired as e:
        cp = subprocess.CompletedProcess(cmd, 124, e.stdout or "", "timeout after %ss" % timeout)
    if check and cp.returncode != 0:
        raise RuntimeError("%s failed (%d): %s" % (" ".join(cmd), cp.returncode, (cp.stderr or "")[-2000:]))
    return cp


def which(name):
    from shutil import which as _w
    return _w(name)


# ---------------------------------------------------------------- repo identity

def repo_root(cwd=None):
    cp = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd or os.getcwd())
    return cp.stdout.strip() if cp.returncode == 0 else None


def main_root(root):
    """The main checkout of root's repository. A linked worktree shares its main checkout's graphs and repo id."""
    cp = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, timeout=10)
    common = cp.stdout.strip() if cp.returncode == 0 else ""
    if os.path.basename(common) == ".git" and os.path.isdir(os.path.dirname(common)):
        return os.path.dirname(common)
    return root


REPO_ID_RX = re.compile(r"^[A-Za-z0-9_.-]+-[0-9a-f]{8}$")
# Committed with the repo's knowledge so every clone and teammate files it under one id; ignored lines are the
# parts of a run that only make sense on one machine, plus security findings, which never go into the repo.
# `runs/**/` matches at any depth: skills keep earlier loops' copies in subfolders (runs/<id>/loop0/05-pentest.json).
KNOWLEDGE_IGNORE = ["runs/CURRENT", "runs/**/patches/", "runs/**/gate-logs/", "runs/**/ready.json",
                    "runs/**/05-secure.*", "runs/**/05-pentest.json", "runs/**/security-audit/",
                    "runs/**/COMMIT_MSG.md", "runs/**/PR_BODY.md"]


def _name_hash(root, key):
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", os.path.basename(root.rstrip("/"))) or "repo"
    return "%s-%s" % (name, hashlib.sha1(key.encode()).hexdigest()[:8])


def derived_repo_id(root):
    """The id LFG used before it was stored in the repo: hashed from the origin URL, else the main checkout path."""
    root = main_root(root)
    remote = run(["git", "config", "--get", "remote.origin.url"], cwd=root).stdout.strip()
    return _name_hash(root, remote or os.path.realpath(root))


def legacy_repo_ids(root):
    """Every id this repo may have had: with its current remote and with none (a remote added later)."""
    main = main_root(root)
    return sorted({derived_repo_id(root), _name_hash(main, os.path.realpath(main))})


def repo_id(root):
    """The stored id in .lfg/repo-id (this checkout's, else the main checkout's), else the derived one."""
    for d in (root, main_root(root)):
        rid = read_text(os.path.join(d, ".lfg", "repo-id")).strip()
        if REPO_ID_RX.match(rid):
            return rid
    return derived_repo_id(root)


def need_repo():
    root = repo_root()
    if not root:
        die("not inside a git repository", 2)
    return root, repo_id(root)


def knowledge_dir(root, create=True):
    """<checkout>/.lfg: the repo's shared knowledge, committed on the branch it was written on. A write stores the
    repo id beside it, once, and keeps LFG's ignore lines in its .gitignore (adding any a newer LFG knows; lines
    someone else added stay)."""
    d = os.path.join(root, ".lfg")
    if not create:
        return d
    if not os.path.isfile(os.path.join(d, "repo-id")):
        write_text(os.path.join(d, "repo-id"), repo_id(root) + "\n")
    ign = os.path.join(d, ".gitignore")
    have = read_text(ign)
    missing = [ln for ln in KNOWLEDGE_IGNORE if ln not in have.splitlines()]
    if missing:
        write_text(ign, have + ("" if not have or have.endswith("\n") else "\n") + "\n".join(missing) + "\n")
    return d


def repo_docs_dir(root):
    """Docs about the whole project (glossary, ADRs, guides the user asked for): the root of the Docs page."""
    d = os.path.join(knowledge_dir(root), "docs")
    ensure_dir(os.path.join(d, "adr"))
    return d


def repo_file(root, name, create=False):
    """A repo-level knowledge file (commands.json, shipcheck.json) in <checkout>/.lfg. create=True only to write it."""
    return os.path.join(knowledge_dir(root, create), name)


def branch_slug(branch):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", branch).strip("-.") or "branch"


def branch_docs_dir(root, branch):
    """Docs about the work on one branch: DOCS/branches/<branch>/, with the real branch name kept in `.branch`
    (folder names can't hold every character a branch name can)."""
    d = ensure_dir(os.path.join(repo_docs_dir(root), "branches", branch_slug(branch)))
    marker = os.path.join(d, ".branch")
    if not os.path.exists(marker):
        write_text(marker, branch + "\n")
    return d


# ---------------------------------------------------------------- run folders

def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s or "run")[:40]


def runs_dir(root, create=True):
    """<checkout>/.lfg/runs. Reads pass create=False so looking never adds a folder to the user's repo."""
    d = os.path.join(knowledge_dir(root, create), "runs")
    return ensure_dir(d) if create else d


def scratch_dir(root, run):
    """~/.lfg/runs/<repo-id>/<run-id>: what a run needs on this machine only (/build's ticket worktrees), kept out of
    the checkout so the code graphs never index a nested worktree."""
    return ensure_dir(lfg_path("runs", repo_id(root), os.path.basename(run)))


def git_branch(root):
    """The checked-out branch, `detached@<sha>` on a detached HEAD, or "" outside git."""
    if not root:
        return ""
    b = run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=root, timeout=10).stdout.strip()
    if b:  # also names the branch of a repo with no commits yet, where rev-parse answers "HEAD"
        return b
    b = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, timeout=10).stdout.strip()
    if b == "HEAD":
        return "detached@" + run(["git", "rev-parse", "--short", "HEAD"], cwd=root, timeout=10).stdout.strip()
    return b


def linked_worktree(root):
    """The main checkout when root is a linked worktree of it, else None. Pure filesystem."""
    main = git_main_root_fast(root) if root else None
    return main if main and os.path.realpath(main) != os.path.realpath(root) else None


def worktree_run(root):
    """The run in the main checkout's .lfg whose run.json lists this worktree (`lfg worktree new` adds it), the
    newest if several, or None. A worktree made for a run's work belongs to that run."""
    main = linked_worktree(root)
    if not main:
        return None
    me, runs = os.path.realpath(root), runs_dir(main, create=False)
    hits = []
    for name in os.listdir(runs) if os.path.isdir(runs) else []:
        meta = read_json(os.path.join(runs, name, "run.json"), None)
        if isinstance(meta, dict) and any(isinstance(w, dict) and w.get("path") and os.path.realpath(w["path"]) == me
                                          for w in meta.get("worktrees") or []):
            hits.append(name)
    return os.path.join(runs, max(hits)) if hits else None


def new_run(root, slug, branch=None):
    """A new run folder, made current. From a linked worktree: the run that already lists it when there is one (never
    a second run for the same work), else a new one in the main checkout's .lfg that lists the worktree, leaving the
    main checkout's CURRENT alone."""
    main = linked_worktree(root)
    if main and worktree_run(root):
        return worktree_run(root)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    base = "%s-%s" % (stamp, _slug(slug))
    runs = runs_dir(main or root)
    path, n = os.path.join(runs, base), 2
    while os.path.exists(path):
        path, n = os.path.join(runs, "%s-%d" % (base, n)), n + 1
    ensure_dir(path)
    br = git_branch(root) if branch is None else branch
    meta = {"run_id": os.path.basename(path), "slug": slug, "repo_id": repo_id(root), "branch": br,
            "created": now_iso(), "lane": None}
    if main:
        meta["worktrees"] = [{"path": root, "branch": br, "created": now_iso()}]
    else:
        write_text(os.path.join(runs, "CURRENT"), os.path.basename(path) + "\n")
    write_json(os.path.join(path, "run.json"), meta)
    return path


def merge_runs(src, dst):
    """Move run folder src's files into run dst (two runs started for one piece of work). A file both have with
    different contents keeps dst's and saves src's beside it as <name>.from-<src run>.<ext>; run.json gains src's
    worktrees and skipped steps (dst's win) and `merged_from`. src is removed, and a CURRENT naming it is cleared."""
    import shutil
    src, dst = os.path.realpath(src), os.path.realpath(dst)
    if src == dst or not all(os.path.isfile(os.path.join(d, "run.json")) for d in (src, dst)):
        raise ValueError("need two different run folders, each with a run.json")
    sid = os.path.basename(src)
    out = {"from": src, "into": dst, "copied": [], "same": [], "kept_both": []}
    for d, _dirs, files in os.walk(src):
        for f in sorted(files):
            p = os.path.join(d, f)
            rel = os.path.relpath(p, src)
            if rel == "run.json":
                continue
            to = os.path.join(dst, rel)
            if os.path.exists(to):
                with open(p, "rb") as a, open(to, "rb") as b:
                    if a.read() == b.read():
                        out["same"].append(rel)
                        continue
                stem, ext = os.path.splitext(to)
                to = "%s.from-%s%s" % (stem, sid, ext)
                out["kept_both"].append(rel)
            else:
                out["copied"].append(rel)
            ensure_dir(os.path.dirname(to))
            shutil.copy2(p, to)
    a, b = read_json(os.path.join(src, "run.json"), {}) or {}, read_json(os.path.join(dst, "run.json"), {}) or {}
    have = {os.path.realpath(w.get("path") or "") for w in b.get("worktrees") or [] if isinstance(w, dict)}
    b["worktrees"] = (b.get("worktrees") or []) + [w for w in a.get("worktrees") or [] if isinstance(w, dict)
                                                    and os.path.realpath(w.get("path") or "") not in have]
    b["skipped"] = dict(a.get("skipped") or {}, **(b.get("skipped") or {}))
    b["merged_from"] = (b.get("merged_from") or []) + [sid]
    b["updated"] = now_iso()
    write_json(os.path.join(dst, "run.json"), b)
    shutil.rmtree(src)
    cur = os.path.join(os.path.dirname(src), "CURRENT")
    if read_text(cur).strip() == sid:
        write_text(cur, "")
    return out


def current_run(root):
    """This checkout's current run: for a linked worktree the run that lists it, else CURRENT (per checkout, never
    committed). None when there is neither."""
    if not root:
        return None
    listed = worktree_run(root)
    if listed:
        return listed
    runs = runs_dir(root, create=False)
    name = read_text(os.path.join(runs, "CURRENT")).strip()
    path = os.path.join(runs, name)
    return path if name and os.path.isdir(path) else None


def git_head(root):
    """The checked-out commit's full sha, or "" (no commits yet, or not git)."""
    cp = run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=root, timeout=10)
    return cp.stdout.strip() if cp.returncode == 0 else ""


def checks_state(ready):
    """What a ready.json says: green, red, cant_run (failed only for tools missing on this machine) or none."""
    if not isinstance(ready, dict):
        return "none"
    return ready.get("state") or ("green" if ready.get("green") else "red")


def stamp_review(root):
    """Record in the current run's 06-review.json the checks it was written against and the commit it read
    (`lfg run review-stamp`, run by /lfg:expert after writing it). Returns {checks, head, note}: note is the line
    to open the review's reply with, "" when the checks were green."""
    r = current_run(root)
    p = os.path.join(r, "06-review.json") if r else ""
    rv = read_json(p, None) if p else None
    if not isinstance(rv, dict):
        raise ValueError("no 06-review.json in the current run to stamp")
    ready = read_json(os.path.join(r, "ready.json"), None)
    state = checks_state(ready)
    rv.update(checks=state, checks_at=(ready or {}).get("ts"), head=git_head(root), stamped=now_iso())
    write_json(p, rv)
    note = {"red": "Checks were red when this review was written (%s); it may change once they are fixed."
                   % ((ready or {}).get("ts") or "time not recorded"),
            "cant_run": "Some checks couldn't run on this machine (a tool isn't installed); the rest passed.",
            "none": "No checks had run when this review was written."}.get(state, "")
    return {"checks": state, "head": rv["head"], "note": note}


def review_status(root):
    """Does the current run's review still stand? Not when it was written while checks were red and commits landed
    after it. A review on red checks with the code unchanged stands, and so does one on green checks."""
    r = current_run(root)
    rv = read_json(os.path.join(r, "06-review.json"), None) if r else None
    if not isinstance(rv, dict):
        return {"stands": False, "why": "no review in the current run", "commits_since": 0}
    head, since = rv.get("head") or "", 0
    if head and head != git_head(root):
        cp = run(["git", "rev-list", "--count", "%s..HEAD" % head], cwd=root, timeout=10)
        since = int(cp.stdout.strip() or 0) if cp.returncode == 0 else 0
    stale = rv.get("checks") == "red" and since > 0
    return {"stands": not stale, "checks": rv.get("checks"), "commits_since": since,
            "why": "written while checks were red, and %d commit(s) landed since" % since if stale else ""}


def run_file(root, name):
    """Path of a file in the current run folder, or None when there is no current run."""
    r = current_run(root)
    return os.path.join(r, name) if r else None


# ---------------------------------------------------------------- output

def audit(event, detail):
    ensure_dir(LFG_HOME)
    line = json.dumps({"ts": now_iso(), "event": event, **detail}) + "\n"
    fd = os.open(lfg_path("audit.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(line)


def die(msg, code=1):
    sys.stderr.write("lfg: %s\n" % msg)
    sys.exit(code)


def emit(obj, as_json, human):
    """Print obj as compact JSON (it goes into an agent's context), or call human(obj) for a readable form."""
    if as_json:
        print(json.dumps(obj, separators=(",", ":"), default=str))
    else:
        human(obj)
