"""`lfg update`: is there newer LFG code, and install it.

Three places code can be newer than what's installed in ~/.lfg: your fork (`origin`), the project you forked
(`upstream`), and commits in your checkout that were never installed. `check` asks git (fetch only, nothing
changes); `apply` brings the checkout's main up to date with both, runs the tests, pushes main to your fork and
installs it. Applying is yours: the guard keeps agents from running it.

The upstream merge never happens on main: it runs on an `lfg-update/...` branch in its own worktree, and main only
fast-forwards to that branch once it is merged and tested. A merge that conflicts stays there, half done, for you
(or Claude) to finish; the next apply picks it up from that branch. So does code whose tests fail: what was tested
stays on a held branch, and `fix` has Claude fix it there, unattended, then applies again.

You decide upstream's commits one at a time: Keep (the default), Skip or Later, kept in
~/.lfg/state/upstream-picks.json. Apply merges upstream up to the first commit that isn't Keep, then cherry-picks
(`-x`) the kept ones after it, so a Skip or Later never lands and a Later can still be kept weeks on: it stays
listed until it is kept or skipped. A commit counts as in once main has it, merged or cherry-picked.

FORK.md in your checkout holds your standing decisions about upstream ("never take X", "ours does Y this way"). Fix
with Claude follows them, writes what it kept and left out into the commit, and when an upstream change overlaps
something your fork does that no decision covers, it stops and leaves the question for you (NEEDS_YOU) instead of
guessing; the dashboard shows it with a prompt for a Claude Code session.
"""
import json
import os
import re
import subprocess
import sys
import time

from . import common as C
from . import worktree as W

BRANCH = "main"
HELD = "lfg-update/"  # branches where an upstream merge is in progress or waiting to be installed
TESTS = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]


def _state_path():
    return C.lfg_path("state", "source.json")


def remember_source(root):
    """Called by `lfg setup`: the checkout this install came from, so the installed copy can find it again."""
    if os.path.exists(os.path.join(root, ".git")):
        C.ensure_dir(os.path.dirname(_state_path()))
        C.write_json(_state_path(), {"path": os.path.realpath(root), "installed_at": C.now_iso(),
                                     "installed_head": _git(root, "rev-parse", "HEAD").stdout.strip()})


def source():
    p = (C.read_json(_state_path(), {}) or {}).get("path")
    if p and os.path.exists(os.path.join(p, ".git")):
        return p
    if os.path.exists(os.path.join(C.LFG_ROOT, ".git")):
        return C.LFG_ROOT
    return None


def _git(root, *args, timeout=60):
    return C.run(["git", *args], cwd=root, timeout=timeout)


def _count(root, a, b, *also):
    """Commits in b that a (and every ref in also) doesn't have."""
    cp = _git(root, "rev-list", "--count", b, "^" + a, *["^" + x for x in also])
    return int(cp.stdout.strip()) if cp.returncode == 0 and cp.stdout.strip().isdigit() else 0


def _log(root, a, b, *also, n=8):
    cp = _git(root, "log", "--format=%h %s", "-n", str(n), b, "^" + a, *["^" + x for x in also])
    return _lines(cp)


TAG_RX = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def channel():
    """releases (the default): Update offers your fork's newest release, the newest v<x.y.z> tag on its main. main:
    every commit merged to your fork's main, as before releases. A fork with no release tags yet follows main."""
    return "main" if (C.config().get("updates") or {}).get("channel") == "main" else "releases"


def release(root):
    """Your fork's newest release: the highest v<x.y.z> tag that its main contains. None without one."""
    cp = _git(root, "tag", "--merged", "origin/" + BRANCH, "--list", "v*")
    tags = [t for t in _lines(cp) if TAG_RX.match(t)]
    if not tags:
        return None
    t = max(tags, key=lambda x: tuple(int(n) for n in TAG_RX.match(x).groups()))
    return {"tag": t, "version": t[1:]}


def target(root):
    """What Update brings in from your fork: its newest release, else its main."""
    r = release(root) if channel() == "releases" else None
    return ("refs/tags/" + r["tag"]) if r else "origin/" + BRANCH


def _lines(cp):
    return [ln for ln in (cp.stdout or "").splitlines() if ln]


def _test_report(t, most=10):
    """Which tests failed and why, from a failed unittest run. unittest writes them to stderr; a plain tail of
    stderr+stdout was only the tests' own prints, so the failing test's name was lost."""
    err = (t.stderr or "").splitlines()
    sep = [i for i, ln in enumerate(err) if ln == "=" * 70] + [len(err)]
    if len(sep) == 1:
        return "\n".join(((t.stderr or "") + (t.stdout or "")).strip().splitlines()[-12:])
    out = []
    for a, b in list(zip(sep, sep[1:]))[:most]:
        block = err[a + 1:b]
        body = [ln for ln in block[2:] if ln.strip() and ln != "-" * 70 and not ln.startswith(("Ran ", "FAILED", "OK"))]
        out += block[:1] + body[-3:]
    ran = next((i for i in range(len(err) - 1, -1, -1) if err[i].startswith("Ran ")), None)
    return "\n".join(out + ([ln for ln in err[ran:] if ln.strip()] if ran is not None else []))


def _unreachable(r, cp):
    """Why fetching from or pushing to a remote failed, in words you can act on."""
    if cp.returncode == 124:
        return ("%s didn't answer in time. If git reaches GitHub through 1Password's SSH agent, unlock 1Password and "
                "try again" % r)
    return "couldn't reach %s: %s" % (r, (cp.stderr or "").strip()[-200:])


def _remote_url(root, name):
    return _git(root, "remote", "get-url", name).stdout.strip()


def _repo_name(url):
    """owner/repo from a GitHub-style URL (https or ssh), else the URL."""
    url = url.rstrip("/")
    tail = (url[:-4] if url.endswith(".git") else url).replace(":", "/").split("/")
    return "/".join(tail[-2:]) if len(tail) >= 2 and tail[-2] else url


VERDICTS = ("keep", "skip", "later")
DECISIONS = "FORK.md"  # your standing decisions about upstream, in the fork's own checkout
COMMIT_MSG = ".lfg-commit-msg"  # Fix with Claude's commit message, left in the held worktree for LFG to commit
NEEDS_YOU = ".lfg-needs-you.md"  # left in the held worktree by Fix with Claude when it needs a decision


def decisions(root):
    return (C.read_text(os.path.join(root, DECISIONS)) or "").strip() if root else ""
PICKED = re.compile(r"cherry picked from commit ([0-9a-f]{40})")


def _picks_path():
    return C.lfg_path("state", "upstream-picks.json")


def picks():
    """{sha: "skip" | "later"}; a commit that isn't listed is Keep."""
    return C.read_json(_picks_path(), {}) or {}


def set_pick(sha, verdict):
    """Keep, Skip or Later for one upstream commit (the dashboard's buttons; yours, like Update)."""
    if not re.match(r"^[0-9a-f]{40}$", str(sha or "")):
        raise ValueError("not a commit: %r" % sha)
    if verdict not in VERDICTS:
        raise ValueError("verdict is one of %s" % ", ".join(VERDICTS))
    d = picks()
    if verdict == "keep":
        d.pop(sha, None)
    else:
        d[sha] = verdict
    C.ensure_dir(os.path.dirname(_picks_path()))
    C.write_json(_picks_path(), d)
    _CACHE.update(ts=0, data=None)
    return {"sha": sha, "verdict": verdict}


def _picked(root, ref):
    """Upstream commits cherry-picked into ref (from the `-x` line git adds)."""
    return set(PICKED.findall(_git(root, "log", "--format=%B", "--grep=cherry picked from commit", ref).stdout or ""))


def _has(root, ref, sha):
    return _git(root, "merge-base", "--is-ancestor", sha, ref).returncode == 0 or sha in _picked(root, ref)


def _conflicts(root, sha, base=BRANCH):
    """Files where this commit on its own conflicts with base ([] if it applies cleanly, None if git can't say)."""
    cp = _git(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", "--merge-base=%s^" % sha,
              base, sha)
    if cp.returncode not in (0, 1):
        return None
    return sorted(set(_lines(cp)[1:])) if cp.returncode == 1 else []


def pending(root, remotes=None):
    """Upstream's commits main doesn't have yet, oldest first: {sha, short, subject, verdict, conflicts}."""
    remotes = remotes if remotes is not None else [r for r in ("origin", "upstream") if _remote_url(root, r)]
    if "upstream" not in remotes:
        return []
    also = ["^origin/" + BRANCH] if "origin" in remotes else []
    have = _picked(root, BRANCH) | (_picked(root, "origin/" + BRANCH) if also else set())
    P = picks()
    out = []
    for ln in _lines(_git(root, "log", "--reverse", "--format=%H %s", "upstream/" + BRANCH, "^" + BRANCH, *also)):
        sha, _, subject = ln.partition(" ")
        if sha not in have:
            out.append({"sha": sha, "short": sha[:7], "subject": subject, "verdict": P.get(sha, "keep")})
    return out


def _plan(todo):
    """(commit to merge up to or "", [commits to cherry-pick after it]) for the pending list: merge while every
    commit so far is Keep, then pick the kept ones one by one."""
    upto, i = "", 0
    while i < len(todo) and todo[i]["verdict"] == "keep":
        upto, i = todo[i]["sha"], i + 1
    return upto, [c["sha"] for c in todo[i:] if c["verdict"] == "keep"]


NOTE_HEAD = re.compile(r"^(kept|not kept)( from upstream)?:\s*$", re.I)


def _notes(root, branch):
    """What a prepared branch keeps and leaves out of upstream's changes, from its commit messages: a "Kept:" and a
    "Not kept:" heading, each followed by "- " lines."""
    out, cur = {"kept": [], "not_kept": []}, None
    for ln in (_git(root, "log", "--format=%B", branch, "^" + BRANCH).stdout or "").splitlines():
        m = NOTE_HEAD.match(ln.strip())
        if m:
            cur = "kept" if m.group(1).lower() == "kept" else "not_kept"
        elif cur and ln.strip().startswith("- "):
            out[cur].append(ln.strip()[2:])
        elif ln.strip():
            cur = None
    return out


def _held_all(root):
    """Every lfg-update/ branch, newest first: {branch, worktree, state, files, prompt, ahead}. state is "conflict"
    (a merge in progress), "uncommitted" (fixed but not committed), "tests" (the last apply's tests failed on it and
    nothing has been committed since) or "ready"; ahead is commits main doesn't have."""
    trees = {w["branch"]: w["path"] for w in W.listing(root) if os.path.isdir(w["path"])}
    last = job() or {}
    tested = last.get("tested") or {} if last.get("status") == "failed" else {}
    for b in _lines(_git(root, "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)",
                         "refs/heads/" + HELD)):
        wt = trees.get(b, "")
        h = {"branch": b, "worktree": wt, "state": "ready", "files": [], "prompt": "", "ahead": _count(root, BRANCH, b)}
        unmerged = _lines(_git(wt, "diff", "--name-only", "--diff-filter=U")) if wt else []
        if unmerged:
            h.update(state="conflict", files=unmerged, files_unmerged=unmerged)
        else:
            merging = bool(wt) and any(_git(wt, "rev-parse", "-q", "--verify", x).returncode == 0
                                       for x in ("MERGE_HEAD", "CHERRY_PICK_HEAD"))
            same = tested.get("branch") == b and _git(root, "rev-parse", b).stdout.strip() == tested.get("head")
            if same:
                h["output"] = last.get("output") or ""
            if merging or (wt and _git(wt, "status", "--porcelain", "--untracked-files=no").stdout.strip()):
                # leftover: an earlier Fix with Claude changed files on a branch whose tests failed, not mid-merge
                h.update(state="uncommitted", files=_lines(_git(wt, "diff", "--name-only", "HEAD")),
                         leftover=not merging)
            elif same:
                h["state"] = "tests"
        h.update(_notes(root, b))
        if h["state"] != "ready":
            h["prompt"] = fix_prompt(h, _repo_name(_remote_url(root, "upstream")) or "the original LFG",
                                     decisions(wt or root))
        yield h


def held(root):
    """The newest lfg-update/ branch with work main doesn't have: a merge to finish, or one ready to install."""
    return next((h for h in _held_all(root) if h["state"] != "ready" or h["ahead"]), None)


def fix_prompt(h, upstream, rules="", commit=True):
    """What to hand Claude: finish the update on the held branch. It never merges. commit=False (Fix with Claude):
    it leaves the message in COMMIT_MSG and LFG commits, so a commit-signing prompt nobody answers can't eat the run."""
    done = "`git add` the files and `git commit`" if commit else (
        "`git add` the files and write the commit message to %s in the worktree (don't add that file and don't run "
        "`git commit`: LFG commits it)" % COMMIT_MSG)
    if h["state"] == "tests" or h.get("leftover"):
        before = (" An earlier try already changed %s here and didn't commit; start from that and check it's right."
                  % (", ".join(h["files"][:20]) or "files")) if h.get("leftover") else ""
        return ("In %s (branch %s), LFG's update stopped because its tests fail there:\n%s\n%s Find the cause and "
                "fix it so `python3 -m unittest discover -s tests` passes there, then %s the fix. Don't run git "
                "merge, rebase or push, and don't touch main; I'll finish the update after."
                % (h["worktree"], h["branch"], h.get("output") or "(see the test run)", before, done))
    files = ", ".join(h["files"][:20]) or "the files git status lists"
    where = "In %s (branch %s), LFG's update is part way through merging %s's main (upstream/main) into my fork" % (
        h["worktree"], h["branch"], upstream)
    todo = ("and these files conflict: %s. Resolve each conflict" % files if h["state"] == "conflict"
            else "and the conflicts look resolved but aren't committed. Check them")
    rules = ("My standing decisions about upstream (%s); follow them, in conflicting files and in files that merged "
             "cleanly alike:\n%s\nOtherwise k" % (DECISIONS, rules)) if rules else "K"
    return ("%s %s. %seep both sides' changes (once: if one side already has the other's change, in its own "
            "words, keep that one). If an upstream change overlaps or contradicts something my fork already does and "
            "no decision above covers it, don't guess and don't commit: write %s in %s whose first line is one plain "
            "sentence saying what I have to decide, in terms of what I will see or be able to do, followed by the "
            "choices and which one you recommend and why, then stop. Otherwise run `python3 -m unittest discover -s "
            "tests` there until it passes, then %s, with a message whose body ends with a \"Kept:\" list and a "
            "\"Not kept:\" list (\"- \" lines, plain words, one per upstream change), to finish the merge (or the "
            "cherry-pick). Don't run git merge, rebase or push, and don't touch main; I'll finish the update after."
            % (where, todo, rules, NEEDS_YOU, h["worktree"], done))


def session_prompt(h, question, upstream):
    """For a Claude Code session you run yourself, when Fix with Claude stopped for a decision."""
    return ("This is a fresh session to finish an LFG update that stopped for a decision. In %s (branch %s), LFG is "
            "merging %s's changes into my fork, and Fix with Claude stopped with this question:\n\n%s\n\nTalk it "
            "through with me. Once I decide, add the decision as one line to %s in that worktree so the next update "
            "follows it, finish the merge that way, run `python3 -m unittest discover -s tests` until it passes, and "
            "`git commit` with \"Kept:\" and \"Not kept:\" lists at the end of the message. Don't run git merge, "
            "rebase or push, and don't touch main; I'll press Update in the dashboard after."
            % (h["worktree"], h["branch"], upstream, question.strip(), DECISIONS))


_CACHE = {"ts": 0, "data": None}


def check(max_age=60, fetch=True):
    """What's newer than the installed copy. Cached for max_age seconds; fetch=False skips asking GitHub."""
    if _CACHE["data"] and time.time() - _CACHE["ts"] < max_age:
        return _CACHE["data"]
    root = source()
    if not root:
        return {"available": False, "why": "LFG wasn't installed from a git checkout, so there is nothing to compare"}
    out = {"available": True, "source": root, "remotes": {}, "errors": []}
    remotes = [r for r in ("origin", "upstream") if _remote_url(root, r)]
    if fetch:
        for r in remotes:
            cp = _git(root, "fetch", "-q", *(["--tags"] if r == "origin" else []), r, BRANCH, timeout=60)
            if cp.returncode:
                out["errors"].append(_unreachable(r, cp))
    installed = (C.read_json(_state_path(), {}) or {}).get("installed_head") or ""
    head = _git(root, "rev-parse", BRANCH).stdout.strip()
    for r in remotes:
        # Each commit counts once: upstream's are the ones your fork doesn't have yet either, so an upstream merge
        # already made on the fork shows as the fork's, not as both.
        ref = target(root) if r == "origin" else "%s/%s" % (r, BRANCH)
        also = ["origin/" + BRANCH] if r == "upstream" and "origin" in remotes else []
        url = _remote_url(root, r)
        out["remotes"][r] = {"url": url, "name": _repo_name(url), "new": _count(root, BRANCH, ref, *also),
                             "commits": _log(root, BRANCH, ref, *also)}
    out["upstream"] = pending(root, remotes)
    # against what Update builds on: main, moved up to your fork's main first when the fork is ahead
    goal = target(root) if "origin" in remotes else ""
    base = goal if goal and _count(root, BRANCH, goal) else BRANCH
    for c in out["upstream"]:
        c["conflicts"] = _conflicts(root, c["sha"], base)
    if "upstream" in remotes:  # Skip and Later aren't part of this update; Later stays listed for another day
        keep = [c for c in out["upstream"] if c["verdict"] == "keep"]
        out["remotes"]["upstream"].update(new=len(keep), commits=["%s %s" % (c["short"], c["subject"]) for c in keep])
    out["sources"] = [r for r in ("upstream", "origin") if r in remotes and out["remotes"][r]["new"]]
    out["channel"], out["release"] = channel(), release(root) if "origin" in remotes else None
    out["held"] = held(root)
    out["not_installed"] = _count(root, installed, BRANCH) if installed and head else 0
    out["not_installed_commits"] = _log(root, installed, BRANCH) if out["not_installed"] else []
    out["unpushed"] = _count(root, "origin/%s" % BRANCH, BRANCH) if "origin" in remotes else 0
    out["current_branch"] = _git(root, "branch", "--show-current").stdout.strip()
    out["dirty"] = bool(_git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip())
    out["ready"] = bool(out["sources"] or out["not_installed"] or (out["held"] or {}).get("state") == "ready")
    out["checked_at"] = C.now_iso()
    out["job"] = job()
    _CACHE.update(ts=time.time(), data=out)
    return out


# ---------------------------------------------------------------- applying (user-only)

def _job_path():
    return C.lfg_path("state", "update-job.json")


def _fix_path():
    return C.lfg_path("state", "update-fix.json")


def _read_job(path):
    j = C.read_json(path, None)
    if j and j.get("status") == "running":
        try:
            os.kill(int(j.get("pid")), 0)
        except (OSError, TypeError, ValueError):
            j.update(status="failed", why="it stopped without finishing")
    return j


def job():
    return _read_job(_job_path())


def fix_job():
    return _read_job(_fix_path())


def start(action="apply"):
    """Run `lfg update apply` (the dashboard's Update button) or `lfg update fix` (Fix with Claude) detached."""
    if any((x or {}).get("status") == "running" for x in (job(), fix_job())):
        return {"started": False, "note": "An update or a fix is already running."}
    with open(os.devnull, "wb") as dn:
        subprocess.Popen([sys.executable, os.path.join(C.PLUGIN_ROOT, "bin", "lfg"), "update", action],
                         stdout=dn, stderr=dn, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return {"started": True}


def _tidy(root, branch):
    """Drop a held branch main already has, and its worktree if it is clean. Never forces."""
    try:
        W.remove(root, branch)
    except (ValueError, RuntimeError):
        pass
    _git(root, "branch", "-d", branch)


def apply(log=print):
    """Bring the checkout's main up to date with your fork, then with the upstream project, test it, push it to your
    fork, install it. In that order, so what gets installed always has both. The upstream merge runs on a held branch
    in its own worktree; main moves only once that is merged and tested. Stops at the first problem: uncommitted
    changes, another branch checked out, a merge that conflicts (left on the held branch), failing tests."""
    root = source()
    steps = []
    j = {"status": "running", "pid": os.getpid(), "started": C.now_iso(), "steps": steps, "why": ""}

    def say(msg):
        steps.append(msg)
        C.write_json(_job_path(), j)
        log(msg)

    def fail(why, conflict=None):
        j.update(status="failed", why=why, ended=C.now_iso(), conflict=conflict)
        C.write_json(_job_path(), j)
        log("stopped: " + why)
        if conflict:
            if conflict["files"]:
                log("conflicting files: " + ", ".join(conflict["files"]))
            log("hand this to Claude to fix it:\n" + conflict["prompt"])
        _CACHE.update(ts=0, data=None)
        return j

    C.ensure_dir(os.path.dirname(_job_path()))
    if not root:
        return fail("LFG wasn't installed from a git checkout")
    say("Checking %s" % root)
    if _git(root, "branch", "--show-current").stdout.strip() != BRANCH:
        return fail("%s has another branch checked out; switch it to %s first" % (root, BRANCH))
    if _git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        return fail("%s has uncommitted changes; commit or stash them first" % root)
    before = _git(root, "rev-parse", "HEAD").stdout.strip()
    was_installed = (C.read_json(_state_path(), {}) or {}).get("installed_head") or before
    has_up = bool(_remote_url(root, "upstream"))
    up_name = _repo_name(_remote_url(root, "upstream")) if has_up else ""
    for r in ("origin", "upstream"):
        if not _remote_url(root, r):
            continue
        say("Getting %s's latest" % r)
        cp = _git(root, "fetch", "-q", *(["--tags"] if r == "origin" else []), r, BRANCH, timeout=120)
        if cp.returncode:
            return fail(_unreachable(r, cp))
    goal = target(root) if _remote_url(root, "origin") else ""
    if goal and _count(root, BRANCH, goal):
        say("Bringing in %s" % ("release " + goal.split("/")[-1] if goal.startswith("refs/tags/")
                                else "your fork's new commits"))
        if _git(root, "merge", "--ff-only", "-q", goal).returncode:
            return fail("your checkout and your fork have both moved on; merge them by hand once")
    for x in list(_held_all(root)):
        if x["state"] == "ready" and not x["ahead"]:
            _tidy(root, x["branch"])  # main already has it
    h = held(root)
    if h and h["state"] != "ready":
        return fail("the merge of %s's changes on %s isn't finished yet (%s)" % (up_name, h["branch"], h["state"]), h)
    wt, branch = "", ""
    todo = pending(root) if has_up else []
    upto, cherry = _plan(todo)
    if h:
        held_too = [c for c in todo if c["verdict"] != "keep" and _has(root, h["branch"], c["sha"])]
        if held_too:
            c = held_too[0]
            return fail("%s (%s) is set to %s but is already on %s; set it back to Keep, or delete that branch to "
                        "start the update again without it" % (c["short"], c["subject"], c["verdict"].title(),
                                                                  h["branch"]))
    if h or upto or cherry:
        if h:
            branch = h["branch"]
            say("Picking up %s" % branch)
            wt = h["worktree"] or W.new(root, branch)["path"]
        else:
            sha = (cherry[-1:] or [upto])[0][:7]
            branch = HELD + "upstream-" + sha
            say("Merging %s's new commits on %s, away from main" % (up_name, branch))
            try:
                wt = W.new(root, branch, base=BRANCH)["path"]
            except (ValueError, RuntimeError) as e:
                return fail("couldn't make a worktree for the merge: %s" % e)
        steps_in = [("merge", r) for r in [BRANCH] + ([upto] if upto else [])] + [("cherry-pick", c) for c in cherry]
        for how, ref in steps_in:
            if how == "merge" and not _count(root, branch, ref):
                continue
            if how == "cherry-pick":
                if _has(root, branch, ref):
                    continue
                say("Keeping %s from %s" % (ref[:7], up_name))
            if _git(wt, *(["merge", "--no-edit", "-q"] if how == "merge" else ["cherry-pick", "-x"]), ref).returncode:
                h = held(root)
                if not h or h["state"] == "ready":  # git refused for another reason (it would overwrite a file)
                    return fail("%s %s into %s failed; nothing changed on main" % (
                        "merging" if how == "merge" else "cherry-picking", ref[:12], branch))
                return fail("%s's changes conflict with yours in %d file(s). Nothing changed on main or was "
                            "installed; the half-done %s is on %s in %s" % (up_name, len(h["files"]), how, branch,
                                                                          wt), h)
    say("Running LFG's tests")
    # no __pycache__ left behind: an untracked file would stop the merge worktree being removed afterwards
    t = C.run(TESTS, cwd=wt or root, timeout=900, env={"PYTHONDONTWRITEBYTECODE": "1"})
    if t.returncode:
        tested = _git(wt or root, "rev-parse", "HEAD").stdout.strip()
        if not branch:  # main itself failed: keep what was tested on a branch of its own, where it can be fixed
            branch = HELD + "tests-" + tested[:7]
            try:
                wt = W.new(root, branch, base=tested)["path"]
            except (ValueError, RuntimeError):
                branch = ""
        _git(root, "reset", "--keep", before)
        tail = _test_report(t)
        if not branch:
            return fail("tests failed, so the update was undone and nothing was installed:\n" + tail)
        j.update(status="failed", tested={"branch": branch, "head": tested}, output=tail)
        C.write_json(_job_path(), j)  # what was tested, so the branch reads as "tests" until something is committed
        return fail("tests failed on %s, so nothing changed on main and nothing was installed:\n%s" % (branch, tail),
                    next((x for x in _held_all(root) if x["branch"] == branch), None))
    if branch:
        if _git(root, "merge", "--ff-only", "-q", branch).returncode:
            return fail("couldn't move main to %s; nothing was installed" % branch)
        _tidy(root, branch)
    if _remote_url(root, "origin") and _count(root, "origin/" + BRANCH, BRANCH):
        say("Saving it to your fork")
        cp = _git(root, "push", "-q", "origin", BRANCH, timeout=120)
        if cp.returncode:
            say("Couldn't push to your fork (%s); installing anyway, push it later" % _unreachable("origin", cp))
    say("Installing")
    cp = C.run([sys.executable, os.path.join(root, "plugin", "bin", "lfg"), "setup", "--yes"], cwd=root, timeout=600)
    if cp.returncode:
        return fail("install failed: %s" % ((cp.stderr or cp.stdout).strip()[-400:]))
    _CACHE.update(ts=0, data=None)
    after = _git(root, "rev-parse", "HEAD").stdout.strip()
    j.update(status="done", ended=C.now_iso(), from_head=was_installed[:12], to_head=after[:12],
             changes=_log(root, was_installed, after, n=30))
    say("Installed. LFG commands and the dashboard use it now; start a new Claude Code session for new skills")
    return j


FIX_ALLOW = ["Read", "Grep", "Glob", "Edit", "Write", "Bash(git status)", "Bash(git status *)", "Bash(git diff)",
             "Bash(git diff *)", "Bash(git log *)", "Bash(git show *)", "Bash(git add *)",
             "Bash(python3 -m unittest *)"]
FIX_DENY = ["Bash(git push *)", "Bash(git merge *)", "Bash(git rebase *)", "Bash(git reset *)",
            "Bash(git checkout *)", "Bash(git switch *)", "Bash(git commit)", "Bash(git commit *)", "Bash(lfg *)"]
FIX_LOGS = 10  # Fix with Claude logs kept, newest first


def _commit(wt):
    """Commit what Fix with Claude staged in the held worktree, with its message. Signing can wait on you (1Password,
    a hardware key), so it gets a minute; returns why it didn't commit, or ""."""
    msg = os.path.join(wt, COMMIT_MSG)
    _git(wt, "rm", "-q", "--cached", "--ignore-unmatch", COMMIT_MSG)
    merging = _git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0
    if os.path.isfile(msg):
        args = ["-F", msg]
    elif merging:
        args = ["--no-edit"]
    else:
        args = ["-m", "Fix LFG's tests for the update"]
    cp = _git(wt, "commit", "-q", *args, timeout=60)
    if cp.returncode == 124:
        return ("the commit didn't finish within a minute, usually because commit signing is waiting on you. If you "
                "sign with 1Password, unlock it, then press Try again: it commits the same fix without redoing it")
    if cp.returncode:
        return "git couldn't commit the fix: " + ((cp.stderr or cp.stdout).strip()[-300:] or "no reason given")
    if os.path.isfile(msg):
        os.remove(msg)  # an untracked file would stop the worktree being removed afterwards
    return ""


def _fix_log():
    """A new log for this try; older tries' logs are kept, up to FIX_LOGS."""
    d = C.ensure_dir(C.lfg_path("state", "update-fix-logs"))
    old = sorted(f for f in os.listdir(d) if f.endswith(".log"))
    for f in old[:max(0, len(old) - FIX_LOGS + 1)]:
        os.remove(os.path.join(d, f))
    path = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + ".log")
    n = 1
    while os.path.exists(path):  # two tries in one second
        path, n = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + "-%d.log" % n), n + 1
    C.write_text(path, "", mode=0o600)
    return path


def _claude(prompt, cwd, log):
    """Claude Code in print mode on the held branch, on your own login. Returns its last message."""
    cmd = ["claude", "-p", prompt, "--permission-mode", "dontAsk", "--output-format", "stream-json", "--verbose",
           "--allowedTools", ",".join(FIX_ALLOW), "--disallowedTools", ",".join(FIX_DENY)]
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        # no __pycache__ from its test runs: an untracked file would stop the worktree being removed afterwards
        subprocess.run(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=3600,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    said = ""
    for ln in C.read_text(log).splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "result" and isinstance(ev.get("result"), str):
            said = ev["result"]
    return said


def fix(log=print):
    """Fix with Claude: hand the held branch's fix prompt to an unattended Claude Code session in its worktree, commit
    what it staged, then apply again (which re-runs the tests). Claude never commits, touches main, merges or pushes.
    A retry first checks a fix an earlier try left uncommitted: if the tests pass on it, it is committed as it is."""
    root = source()
    j = {"status": "running", "pid": os.getpid(), "started": C.now_iso(), "why": ""}

    def end(status, why=""):
        j.update(status=status, why=why, ended=C.now_iso())
        C.write_json(_fix_path(), j)
        _CACHE.update(ts=0, data=None)
        if why:
            log("stopped: " + why)
        return j

    C.ensure_dir(os.path.dirname(_fix_path()))
    C.write_json(_fix_path(), j)
    h = held(root) if root else None
    if not h or h["state"] == "ready":
        return end("failed", "there's nothing for Claude to fix")
    if not C.which("claude"):
        return end("failed", "Claude Code (`claude`) is not on PATH")
    if not h["worktree"]:  # pruned since; the branch is all that's needed
        W.new(root, h["branch"])
        h = next(x for x in _held_all(root) if x["branch"] == h["branch"])
    j.update(branch=h["branch"], state=h["state"], log=_fix_log())
    C.write_json(_fix_path(), j)
    upstream = _repo_name(_remote_url(root, "upstream")) or "the original LFG"
    if h["state"] == "uncommitted" and not h.get("files_unmerged"):
        # an earlier try fixed it and stopped before the commit (signing waited on you): if it passes, just commit it
        log("Checking the fix an earlier try left in %s" % h["worktree"])
        t = C.run(TESTS, cwd=h["worktree"], timeout=900, env={"PYTHONDONTWRITEBYTECODE": "1"})
        if not t.returncode:
            return _finish(h, j, end, log, "The earlier fix passes the tests; committing it")
        h["output"] = "\n".join(((t.stderr or "") + (t.stdout or "")).strip().splitlines()[-12:])
    log("Claude is fixing %s in %s" % (h["branch"], h["worktree"]))
    try:
        said = _claude(fix_prompt(h, upstream, decisions(h["worktree"]), commit=False) + " You are running "
                       "unattended from the LFG dashboard: nobody can answer questions. Run each shell command on its "
                       "own, never chained with ; or &&. If you can't fix it, stage nothing, and say why in your last "
                       "message.", h["worktree"], j["log"])
    except subprocess.TimeoutExpired:
        return end("failed", "Claude didn't finish within an hour")
    j["said"] = said[-2000:]
    ask = os.path.join(h["worktree"], NEEDS_YOU)
    if os.path.isfile(ask):  # it stopped for a decision only you can make
        question = C.read_text(ask).strip()
        os.remove(ask)  # an untracked file would stop the worktree being removed afterwards
        j.update(question=question, session=session_prompt(h, question, upstream))
        return end("needs_you", "Claude needs a decision from you: " + (question.splitlines() or [""])[0])
    after = next((x for x in _held_all(root) if x["branch"] == h["branch"]), None)
    if not after or after["state"] not in ("ready", "uncommitted") or after.get("files_unmerged"):
        return end("failed", "Claude finished without a fix" + (": " + said[-600:] if said else ""))
    return _finish(after, j, end, log, "Claude made a fix; committing it")


def _finish(h, j, end, log, what):
    """Commit the held branch's staged fix (if any), then run the update again, which re-runs the tests."""
    if h["state"] == "uncommitted":
        log(what)
        why = _commit(h["worktree"])
        if why:
            return end("failed", why)
    log("Running the update again")
    r = apply(log)  # the fix stays "running" until this ends, so the dashboard goes straight from one to the other
    if r["status"] == "done":
        end("done")
    else:
        end("failed", "The fix is committed, but the update still stopped: " + r.get("why", ""))
    return r


SOURCE_LABEL = {"upstream": "the original LFG", "origin": "your fork"}


def human(d):
    if not d.get("available"):
        print(d.get("why"))
        return
    R = d["remotes"]
    if d.get("sources"):
        print("new from: " + " and ".join("%s (%s)" % (SOURCE_LABEL[r], R[r]["name"]) for r in d["sources"]))
    for r, v in R.items():
        print("%-9s %s new commit(s)  (%s)" % (r, v["new"], v["url"]))
        for c in v["commits"]:
            print("            " + c)
    if d["not_installed"]:
        print("checkout  %d commit(s) on %s not installed yet" % (d["not_installed"], BRANCH))
    h = d.get("held")
    if h and h["state"] != "ready":
        print("\n%s on %s (%s), in %s" % ("tests fail" if h["state"] == "tests" else "merge not finished",
                                           h["branch"], h["state"], h["worktree"]))
        for f in h["files"]:
            print("  conflict  " + f)
        print("\nRun `lfg update fix` to have Claude fix it and finish the update, or hand this to Claude yourself, "
              "then run `lfg update apply`:\n\n" + h["prompt"])
    elif h:
        print("merged and committed on %s: `lfg update apply` finishes from it" % h["branch"])
    for e in d["errors"]:
        print("!! " + e)
    if not (h and h["state"] != "ready"):
        print("update ready: run `lfg update apply`" if d["ready"] else "up to date")


def as_json(d):
    return json.dumps(d, separators=(",", ":"))
