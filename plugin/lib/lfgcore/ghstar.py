"""Star LFG on GitHub, only when the user says so.

LFG never writes to GitHub on its own. `lfg setup` asks once (in a terminal, when the GitHub CLI is signed in), and
the dashboard has a Star button; both call `star()`, which runs `gh api -X PUT /user/starred/<repo>` as the user.
The answer is remembered in ~/.lfg/state/github.json so setup never asks twice.
Author: Varun Singh.
"""
from . import common as C

REPO = "varun-singhh/lfg"


def _state_path():
    return C.lfg_path("state", "github.json")


def state():
    return C.read_json(_state_path(), {}) or {}


def _remember(**kw):
    st = dict(state(), **kw)
    C.write_json(_state_path(), st)
    return st


def gh_ready():
    """The GitHub CLI is installed and signed in."""
    if not C.which("gh"):
        return False
    cp = C.run(["gh", "auth", "status"], timeout=15)
    return cp.returncode == 0


def starred():
    """True/False when gh can tell, None when it can't (not installed, not signed in, offline)."""
    if not gh_ready():
        return None
    cp = C.run(["gh", "api", "/user/starred/%s" % REPO, "--silent"], timeout=15)
    return cp.returncode == 0


def star():
    """Star the repo from the signed-in GitHub account. Only ever called from an explicit yes or click."""
    if not gh_ready():
        return {"starred": False, "why": "Sign in to the GitHub CLI first (`gh auth login`), or star it on github.com.",
                "url": "https://github.com/%s" % REPO}
    cp = C.run(["gh", "api", "-X", "PUT", "/user/starred/%s" % REPO, "--silent"], timeout=20)
    ok = cp.returncode == 0
    _remember(asked=True, starred=ok)
    C.audit("github_star", {"ok": ok})
    return {"starred": ok, "why": "" if ok else (cp.stderr or cp.stdout or "gh couldn't star it").strip()[:200],
            "url": "https://github.com/%s" % REPO}


def view():
    """For the dashboard: can it star with one click, and is it starred already."""
    ready = gh_ready()
    return {"ready": ready, "starred": bool(ready and starred()), "url": "https://github.com/%s" % REPO}


def ask_once(inp=input, out=print):
    """During `lfg setup` in a terminal: ask once, star only on yes."""
    st = state()
    if st.get("asked") or not gh_ready() or starred():
        return None
    try:
        yes = inp("Star LFG on GitHub (%s) from your GitHub account? [y/N] " % REPO).strip().lower() in ("y", "yes")
    except EOFError:
        yes = False
    if not yes:
        _remember(asked=True, starred=False)
        return False
    r = star()
    out("Thanks for the star!" if r["starred"] else "Couldn't star it: %s" % r["why"])
    return r["starred"]
