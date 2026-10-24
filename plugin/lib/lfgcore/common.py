"""Shared helpers for LFG: paths, config, repo identity, run folders, process runner. Stdlib only, Python 3.9+."""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

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

DEFAULT_CONFIG = {
    "models": {
        "product-manager": "sonnet", "architecture-designer": "opus", "software-engineer": "sonnet",
        "ai-engineer": "sonnet", "qa": "sonnet", "security-analyst": "sonnet",
        "expert-review": "opus", "lane-triage": "haiku",
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
    "headroom": {"port": 8787, "mode": "token", "scope": "off"},
    "guard": {"hardened": False, "allow_commits": True},
    "replies": {"lfg_tag": True},
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
    "updates": {
        "check_interval_hours": 24,
        "auto_check": True,
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
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


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

def run(cmd, cwd=None, timeout=None, env=None, check=False, capture=True):
    """Run a command (list). Returns CompletedProcess with text output. Never uses a shell."""
    full_env = dict(os.environ)
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


def repo_id(root):
    root = main_root(root)
    remote = run(["git", "config", "--get", "remote.origin.url"], cwd=root).stdout.strip()
    key = remote or os.path.realpath(root)
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", os.path.basename(root.rstrip("/"))) or "repo"
    return "%s-%s" % (name, hashlib.sha1(key.encode()).hexdigest()[:8])


def need_repo():
    root = repo_root()
    if not root:
        die("not inside a git repository", 2)
    return root, repo_id(root)


def repo_docs_dir(rid):
    """Docs about the whole project (glossary, ADRs, guides the user asked for): the root of the Docs page."""
    d = lfg_path("repos", rid, "docs")
    ensure_dir(os.path.join(d, "adr"))
    return d


def branch_slug(branch):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", branch).strip("-.") or "branch"


def branch_docs_dir(rid, branch):
    """Docs about the work on one branch: DOCS/branches/<branch>/, with the real branch name kept in `.branch`
    (folder names can't hold every character a branch name can)."""
    d = ensure_dir(os.path.join(lfg_path("repos", rid, "docs"), "branches", branch_slug(branch)))
    marker = os.path.join(d, ".branch")
    if not os.path.exists(marker):
        write_text(marker, branch + "\n")
    return d


# ---------------------------------------------------------------- run folders

def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s or "run")[:40]


def runs_dir(rid):
    return ensure_dir(lfg_path("runs", rid))


def git_branch(root):
    """The checked-out branch, `detached@<sha>` on a detached HEAD, or "" outside git."""
    if not root:
        return ""
    b = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, timeout=10).stdout.strip()
    if b == "HEAD":
        return "detached@" + run(["git", "rev-parse", "--short", "HEAD"], cwd=root, timeout=10).stdout.strip()
    return b


def new_run(rid, slug, branch="", current=True, **extra):
    """A new run folder. `current=False` leaves the repo's current run alone (a run started from the dashboard
    next to whatever the user is doing); `extra` goes into run.json (a PR fix run's pr, pr_url, worktree...)."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    base = "%s-%s" % (stamp, _slug(slug))
    path, n = os.path.join(runs_dir(rid), base), 2
    while os.path.exists(path):
        path, n = os.path.join(runs_dir(rid), "%s-%d" % (base, n)), n + 1
    ensure_dir(path)
    if current:
        write_text(os.path.join(runs_dir(rid), "CURRENT"), os.path.basename(path) + "\n")
    write_json(os.path.join(path, "run.json"), dict({"run_id": os.path.basename(path), "slug": slug,
                                                     "repo_id": rid, "branch": branch, "created": now_iso(),
                                                     "lane": None}, **extra))
    return path


def current_run(rid):
    try:
        with open(os.path.join(runs_dir(rid), "CURRENT")) as f:
            name = f.read().strip()
    except OSError:
        return None
    path = os.path.join(runs_dir(rid), name)
    return path if name and os.path.isdir(path) else None


def run_file(rid, name):
    """Path of a file in the current run folder, or None when there is no current run."""
    r = current_run(rid)
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
