"""`lfg worktree`: git worktrees for working on another branch without touching the user's checkout.

Worktrees go next to the main checkout, in `<parent>/<repo>.worktrees/<branch-slug>`, so they are outside both the
repo and ~/.lfg. They share the main checkout's graphs (one graph per repo, see graphs.py). LFG never commits in a
worktree, never uses `--force`, and only removes worktrees it created that have no uncommitted changes.
Author: Varun Singh."""
import os
import re

from . import common as C


def base_dir(root):
    main = C.main_root(root)
    return os.path.join(os.path.dirname(main), os.path.basename(main) + ".worktrees")


def slug(branch):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-.") or "wt"


def _git(root, *args, timeout=60):
    return C.run(["git", *args], cwd=root, timeout=timeout)


def listing(root):
    """Every worktree of the repo: [{path, branch, head, lfg}], `lfg` true for the ones under base_dir()."""
    cp = _git(root, "worktree", "list", "--porcelain")
    mine = os.path.realpath(base_dir(root))
    out, cur = [], {}
    for line in (cp.stdout or "").splitlines() + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = {}
            continue
        k, _, v = line.partition(" ")
        if k == "worktree":
            cur = {"path": v, "branch": "", "head": "", "lfg": os.path.dirname(os.path.realpath(v)) == mine}
        elif k == "branch":
            cur["branch"] = v.replace("refs/heads/", "", 1)
        elif k == "HEAD":
            cur["head"] = v[:12]
    return out


def new(root, branch, base=None):
    """Check `branch` out in a new worktree (create it from `base`, default HEAD, if it doesn't exist)."""
    if not branch or branch.startswith("-") or _git(root, "check-ref-format", "--branch", branch).returncode:
        raise ValueError("not a valid branch name: %r" % branch)
    path = os.path.join(base_dir(root), slug(branch))
    if os.path.exists(path):
        raise ValueError("%s already exists" % path)
    exists = _git(root, "show-ref", "--verify", "--quiet", "refs/heads/" + branch).returncode == 0
    if exists and base:
        raise ValueError("branch %s already exists; --from only applies to a new branch" % branch)
    os.makedirs(base_dir(root), exist_ok=True)
    args = ["worktree", "add", path, branch] if exists else \
        ["worktree", "add", "-b", branch, path] + ([base] if base else [])
    cp = _git(root, *args, timeout=300)
    if cp.returncode:
        raise RuntimeError((cp.stderr or cp.stdout).strip())
    return {"path": path, "branch": branch, "created_branch": not exists}


def remove(root, name):
    """Remove an LFG worktree by folder name or branch. Refuses one with uncommitted or untracked changes."""
    hit = [w for w in listing(root) if w["lfg"] and name in (os.path.basename(w["path"]), w["branch"])]
    if not hit:
        raise ValueError("no LFG worktree named %r (see `lfg worktree list`)" % name)
    path = hit[0]["path"]
    dirty = _git(path, "status", "--porcelain").stdout.strip()
    if dirty:
        raise RuntimeError("%s has uncommitted changes; commit or move them first (LFG never forces):\n%s"
                           % (path, dirty[:1500]))
    cp = _git(root, "worktree", "remove", path)
    if cp.returncode:
        raise RuntimeError((cp.stderr or cp.stdout).strip())
    try:
        os.rmdir(base_dir(root))  # only when empty
    except OSError:
        pass
    return {"path": path, "branch": hit[0]["branch"]}


def _last_used(path):
    """Newest of the worktree folder and its git admin files (index/HEAD change on any git use there)."""
    admin = _git(path, "rev-parse", "--absolute-git-dir").stdout.strip()
    paths = [path] + ([os.path.join(admin, f) for f in ("index", "HEAD")] if admin else [])
    return max((os.path.getmtime(p) for p in paths if os.path.exists(p)), default=0)


def prune(root, idle_s=86400):
    """Remove LFG worktrees that are clean and unused for `idle_s` (run by SessionStart, so nobody has to).
    Worktrees with any change are kept; the branch is always kept. Returns the removed paths."""
    import time
    gone = []
    for w in listing(root):
        if not w["lfg"] or time.time() - _last_used(w["path"]) < idle_s:
            continue
        if os.path.basename(w["path"]).startswith("review-pr-"):
            continue  # a PR review from the dashboard: removed from its Reviews page when the reviewer is done
        if not os.path.isdir(w["path"]):
            continue  # folder deleted by hand: `git worktree prune` territory, not ours
        try:
            gone.append(remove(root, os.path.basename(w["path"]))["path"])
        except (ValueError, RuntimeError):
            pass  # has changes (the user's work) or git refused: leave it
    return gone
