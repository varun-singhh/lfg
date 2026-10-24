"""Welcome: which LFG features you use, so the dashboard shows only their pages (progressive disclosure).

State lives in ~/.lfg/state/onboarding.json, never in config.json (so it never freezes config defaults):
{"complete": bool, "at": iso, "features": [ids], "show_all": bool}. Until the user has chosen, every page shows.
An install from before this existed counts as done with everything on, so nobody loses pages on update.
Author: Varun Singh.
"""
import os
import re
import sys

from . import common as C
from . import settings as S

FEATURES = {  # id -> what it is and the dashboard pages it adds (page keys are app.js NAV keys)
    "coding": {"name": "Building and fixing code", "description": "Plan, build, fix and ship changes with /lfg:lfg.",
               "skills": ["lfg", "build", "fix", "spike", "explain5", "suggest-tests"], "pages": ["insights"]},
    "reviews": {"name": "Code reviews", "description": "Review pull requests and AI chats before they merge.",
                "skills": ["expert", "review-coach"], "pages": ["review", "insights"]},
    "security": {"name": "Security checks", "description": "Dependency, secret and code scans; optional pentests.",
                 "skills": ["secure", "pentest"], "pages": ["checks"]},
    "knowledge": {"name": "Docs and knowledge", "description": "Project docs, decisions and what LFG remembers.",
                  "skills": ["note", "learn"], "pages": ["knowledge", "docs"]},
    "planning": {"name": "Planning and the code map", "description": "Issues, briefs, plans and the code graph.",
                 "skills": ["grill", "plan", "map"], "pages": ["issues", "code"]},
}
ALWAYS = ["home", "todos", "runs", "usage", "skills", "integrations", "settings", "help"]
NAV_ORDER = ["home", "todos", "runs", "issues", "review", "checks", "code", "insights", "docs", "knowledge", "usage",
             "skills", "integrations", "settings", "help"]
DEFAULT = ["coding"]


def _path():
    return C.lfg_path("state", "onboarding.json")


def _legacy():
    """Installed before Welcome existed (it left a ledger or enabled.json behind)."""
    return os.path.exists(C.lfg_path("state", "ledger.json")) or os.path.exists(C.lfg_path("enabled.json"))


def state():
    st = C.read_json(_path(), None)
    if not isinstance(st, dict):
        st = {"complete": True, "features": list(FEATURES), "legacy": True} if _legacy() else {"complete": False}
    feats = [f for f in (st.get("features") or DEFAULT) if f in FEATURES]
    return {"complete": bool(st.get("complete")), "features": feats, "show_all": bool(st.get("show_all")),
            "at": st.get("at"), "nudges": st.get("nudges") or {}}


def _write(**kw):
    st = state()
    st.update(kw)
    st["features"] = [f for f in FEATURES if f in st["features"]]
    C.write_json(_path(), {"complete": st["complete"], "features": st["features"], "show_all": st["show_all"],
                           "at": st.get("at") or C.now_iso(), "nudges": st.get("nudges") or {}})
    return st


def pages(st=None):
    """Dashboard pages to show: every page until the user has chosen (or with show_all), else the always-on pages plus
    those of the chosen features, in nav order."""
    st = st or state()
    if not st["complete"] or st["show_all"]:
        return list(NAV_ORDER)
    on = set(ALWAYS).union(*(FEATURES[f]["pages"] for f in st["features"]))
    return [p for p in NAV_ORDER if p in on]


def _check(names):
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise S.Invalid("features must be a list of names")
    bad = [n for n in names if n not in FEATURES]
    if bad:
        raise S.Invalid("unknown feature: %s (one of %s)" % (", ".join(bad), ", ".join(FEATURES)))
    return names


def choose(features=None, everything=False):
    """Finish Welcome with these features (or all of them)."""
    names = list(FEATURES) if everything else _check(list(features or []))
    st = _write(complete=True, features=names or DEFAULT, at=C.now_iso())
    C.audit("onboarding", {"features": st["features"]})
    return view(st)


def toggle(name, enabled):
    _check([name])
    st = state()
    names = set(st["features"]) | {name} if enabled else set(st["features"]) - {name}
    st = _write(complete=True, features=sorted(names))
    return view(st)


def set_show_all(on):
    return view(_write(show_all=bool(on)))


# ---------------------------------------------------------------- check-ins: offer a hidden page once it's earned

SNOOZE_DAYS, QUIET_DAYS, MIN_USES = 30, 3, 3


def _skill_uses():
    """How often each /lfg: skill answered a prompt (the replies table the Stop hook keeps)."""
    import sqlite3
    path = C.lfg_path("usage.db")
    if not os.path.exists(path):
        return {}
    try:
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=2)
        rows = db.execute("SELECT detail, COUNT(*) FROM replies WHERE kind = 'skill' GROUP BY detail").fetchall()
    except sqlite3.Error:
        return {}
    out = {}
    for detail, n in rows:
        for name in re.findall(r"/lfg:([\w-]+)", detail or ""):
            out[name] = out.get(name, 0) + n
    return out


def _has_data(fid):
    """Something already exists that the feature's pages would show."""
    import glob
    if fid == "reviews":
        return bool(glob.glob(C.lfg_path("reviews", "*", "*")))
    if fid == "security":
        return bool(glob.glob(C.lfg_path("runs", "*", "*", "05-secure*.json")))
    if fid == "knowledge":
        return bool(glob.glob(C.lfg_path("repos", "*", "docs", "**", "*.md"), recursive=True))
    if fid == "planning":
        return bool(glob.glob(C.lfg_path("graphs", "*", "state.json"))) and \
            bool(((C.config().get("linear") or {}).get("team") or "").strip())
    return False


def _days_since(iso):
    import datetime
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (datetime.datetime.now(t.tzinfo or datetime.timezone.utc) - t).total_seconds() / 86400
    except (TypeError, ValueError):
        return 1e9


def suggestion(st=None):
    """At most one hidden feature to offer, with the reason in the user's own usage: a skill of it used a few
    times, or data it would show already there. Never in the first days after Welcome, never more than once a
    week, and "not now" holds for a month. None when there's nothing to offer."""
    st = st or state()
    if not st["complete"] or st["show_all"] or _days_since(st.get("at")) < QUIET_DAYS:
        return None
    nudges = st.get("nudges") or {}
    if _days_since(nudges.get("_last")) < 7:
        return None
    uses = _skill_uses()
    hidden = [(fid, f) for fid, f in FEATURES.items() if fid not in st["features"] and
              _days_since((nudges.get(fid) or {}).get("at")) >= SNOOZE_DAYS]

    def offer(fid, why):
        f = FEATURES[fid]
        return {"feature": fid, "name": f["name"], "pages": f["pages"], "why": why}

    def pages_of(f):
        return ", ".join("Reviews" if p == "review" else p.capitalize() for p in f["pages"])
    # what you use comes first: the hidden feature whose skill you've run most
    used = sorted(((max((uses.get(k, 0), k) for k in f["skills"]), fid) for fid, f in hidden), reverse=True)
    if used and used[0][0][0] >= MIN_USES:
        (n, skill), fid = used[0]
        return offer(fid, "You've used /lfg:%s %d times. Show %s in the sidebar?" % (skill, n,
                                                                                    pages_of(FEATURES[fid])))
    for fid, f in hidden:  # then a page that already has something to show
        if _has_data(fid):
            return offer(fid, "There's already something for %s to show. Add it to the sidebar?" % pages_of(f))
    return None


def answer_suggestion(fid, yes):
    _check([fid])
    st = state()
    nudges = dict(st.get("nudges") or {}, **{fid: {"at": C.now_iso(), "answer": "yes" if yes else "later"}})
    nudges["_last"] = C.now_iso()
    if yes:
        st = _write(features=sorted(set(st["features"]) | {fid}), nudges=nudges)
    else:
        st = _write(nudges=nudges)
    return view(st)


def view(st=None):
    """What the dashboard needs (api "features"), and what the save endpoints return."""
    st = st or state()
    titles = dict({p: p.capitalize() for p in NAV_ORDER}, review="Reviews")
    try:
        sug = suggestion(st)
    except Exception:  # noqa: BLE001 - a check-in is never worth breaking the page
        sug = None
    return {"complete": st["complete"], "show_all": st["show_all"], "pages": pages(st), "suggestion": sug,
            "features": [{"id": k, "name": f["name"], "description": f["description"], "enabled": k in st["features"],
                          "pages": f["pages"], "page_titles": [titles[p] for p in f["pages"]],
                          "skills": ["/lfg:%s" % s for s in f["skills"]]} for k, f in FEATURES.items()]}


def wizard(inp=input, out=print):
    """`lfg onboard` in a terminal: one yes/no per feature."""
    st = state()
    out("Which LFG features will you use? The dashboard shows only their pages; change it any time in Settings.\n")
    chosen = []
    for k, f in FEATURES.items():
        on = k in st["features"] if st["complete"] else k in DEFAULT
        try:
            a = inp("  %s: %s [%s] " % (f["name"], f["description"], "Y/n" if on else "y/N")).strip().lower()
        except EOFError:
            a = ""
        if (a in ("y", "yes")) or (not a and on):
            chosen.append(k)
    return choose(chosen)


def is_complete():
    return state()["complete"]


def interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()
