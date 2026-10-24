"""Dashboard → Insights: understand code you didn't write, without opening an editor.

Three views of the selected project, all from git and the files on disk (read-only, no network):
- Your changes: what this branch changes, what in it looks risky, the questions a senior engineer would ask before
  approving it, and the problems that keep coming back in your reviews.
- Hotspots: the files and folders that keep needing fixes, with the evidence (architecture debt you can act on).
- Files: what a file is, why each part of it exists (the commits, issues and PRs behind it), and tests worth adding.

A file is read only when git lists it in the project (tracked, or new and not ignored), so the dashboard API can't
be pointed at anything else. The checks are patterns, said plainly in the UI: they point at what to read, they don't
replace reading it. Author: Varun Singh.
"""
import collections
import os
import re
import threading
import time

from . import common as C
from . import dash
from . import settings as S

_cache, _lock = {}, threading.Lock()
CONFIG_RX = re.compile(r"(^|/)(migrations?|alembic)/|\.sql$|(^|/)Dockerfile|docker-compose|(^|/)\.github/workflows/|"
                       r"\.(tf|tfvars)$|(^|/)(k8s|helm|deploy|infra)/|(^|/)\.env\.example$", re.I)


def _root(rid):
    root = dash.repo_root(rid)
    if not root:
        raise S.Invalid("this project's folder isn't known yet; open Claude Code in it once")
    return root


def files(rid):
    """Files git tracks, plus new files it would track (not ignored) that aren't committed yet."""
    cp = C.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=_root(rid), timeout=20)
    return sorted(set(cp.stdout.splitlines())) if cp.returncode == 0 else []


def _tracked(rid, path):
    path = (path or "").strip()
    while path.startswith("./"):
        path = path[2:]
    if not path:
        raise S.Invalid("pick a file")
    if path not in set(files(rid)):
        raise S.Invalid("%s isn't a file in this project (or git ignores it)" % path)
    return path


def _cached(key, ttl, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (time.time(), val)
    return val


# ---------------------------------------------------------------- hotspots

def hotspots(rid):
    from . import hotspots_engine as HE
    root = _root(rid)
    head = C.run(["git", "rev-parse", "HEAD"], cwd=root, timeout=10).stdout.strip()
    return _cached(("hot", root, head), 600, lambda: HE.hotspots(root))


# ---------------------------------------------------------------- your changes

def _kind(message):
    return re.sub(r"\s*\(in a test file\)$", "", message or "")


def _remember(rid, issues):
    """What the review coach found, by kind (never code or file contents), to spot what keeps coming back."""
    path = C.lfg_path("repos", rid, "insights", "reviews.json")
    hist = C.read_json(path, []) or []
    kinds = collections.Counter(_kind(i.get("message")) for i in issues if i.get("severity") != "low")
    hist = (hist + [{"at": C.now_iso(), "kinds": dict(kinds)}])[-30:]
    C.write_json(path, hist)
    return hist


def _patterns(hist):
    recent = hist[-10:]
    seen = collections.Counter(k for h in recent for k in (h.get("kinds") or {}))
    return [{"kind": k, "times": n, "of": len(recent)} for k, n in seen.most_common() if n >= 3][:4]


GENERIC = {"src", "lib", "app", "apps", "core", "utils", "util", "common", "tests", "test", "main", "index", "init",
           "__init__", "plugin", "plugins", "pkg", "internal", "cmd", "api", "web", "server", "client", "assets"}


def decisions(rid):
    """What the team decided, in words: this project's decision records (lfg repo docs → adr/) and, when the
    Knowledge pack is running, dev-graph decisions, principles and invariants. [{title, text, source}]."""
    def load():
        import glob
        out = []
        for p in sorted(glob.glob(C.lfg_path("repos", rid, "docs", "adr", "*.md"))):
            text = C.read_text(p)[:20000]
            m = re.search(r"^#\s+(.+)$", text, re.M)
            out.append({"title": (m.group(1) if m else os.path.basename(p)).strip(), "text": text,
                        "source": "decision record %s" % os.path.basename(p).split("-")[0]})
        try:
            k = dash.knowledge()
        except Exception:  # noqa: BLE001 - dev-graph is optional
            k = {}
        if k.get("available"):
            for d in k.get("decisions") or []:
                if str(d.get("status") or "").lower() not in ("superseded", "rejected", "deprecated"):
                    out.append({"title": d.get("title") or d.get("slug"), "source": "dev-graph decision",
                                "text": " ".join(str(d.get(x) or "") for x in ("title", "context", "decision"))})
            for p in (k.get("principles") or []) + (k.get("invariants") or []):
                out.append({"title": p.get("statement") or p.get("slug"), "source": "dev-graph rule",
                            "text": " ".join(str(p.get(x) or "") for x in ("statement", "rationale", "specRef",
                                                                           "guardRef"))})
        return out
    return _cached(("decisions", rid), 600, load)


def _touching(decs, changed):
    """Decisions that name a changed file, its module or its folder (not generic names like src or utils)."""
    hits = []
    for d in decs:
        low = d["text"].lower()
        for p in changed:
            stem = os.path.splitext(os.path.basename(p))[0].lower()
            folder = os.path.basename(os.path.dirname(p)).lower()
            keys = [p.lower()] + [k for k in (stem, folder) if len(k) >= 4 and k not in GENERIC]
            if any(re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(k), low) for k in keys):
                hits.append((d, p))
                break
    return hits


def senior_questions(review, hot, root, decs=()):
    """What an experienced reviewer would ask before approving this change, from what it touches. At most five."""
    from .explain5_engine import TEST_FILE, related_tests
    qs = []
    changed = [f["path"] for f in review.get("files_reviewed") or []]
    hot_by = {f["path"]: f for f in (hot or {}).get("files", [])}
    fragile = sorted((hot_by[p] for p in changed if p in hot_by and hot_by[p]["fixes"] >= 2),
                     key=lambda h: -h["fixes"])
    if len(fragile) == 1:
        qs.append({"q": "%s needed %d fixes recently. What makes this change safe, and how would you know if it "
                         "broke?" % (fragile[0]["path"], fragile[0]["fixes"]), "why": "hotspot"})
    elif fragile:
        names = ", ".join(os.path.basename(h["path"]) for h in fragile[:3])
        more = " and %d more" % (len(fragile) - 3) if len(fragile) > 3 else ""
        qs.append({"q": "It changes %d files that keep needing fixes (%s%s). What makes it safe, and how would you "
                         "know if one of them broke?" % (len(fragile), names, more), "why": "hotspot"})
    code = [p for p in changed if not TEST_FILE.search(p) and not re.search(r"\.(md|txt|json|ya?ml|lock|toml)$", p)]
    if code and not any(TEST_FILE.search(p) for p in changed):
        untested = [p for p in code[:12] if not related_tests(p, root)]
        if untested:
            more = " (and %d more)" % (len(untested) - 3) if len(untested) > 3 else ""
            qs.append({"q": "Nothing tests %s%s. Which check shows it still works?" % (", ".join(untested[:3]), more),
                       "why": "tests"})
        else:
            qs.append({"q": "The code changed but no test did. Which existing test covers the new behaviour?",
                       "why": "tests"})
    added = sum(f.get("additions", 0) for f in review.get("files_reviewed") or [])
    if added > 600 or len(changed) > 20:
        qs.append({"q": "This is {:,} new lines across {} files. Can it ship in smaller pieces that are each easy "
                         "to check and undo?".format(added, len(changed)), "why": "size"})
    risky = [p for p in changed if CONFIG_RX.search(p)]
    if risky:
        qs.append({"q": "It touches %s. How does this roll back if it goes wrong in production?" % ", ".join(risky[:3]),
                   "why": "rollout"})
    for d, p in _touching(decs, changed)[:2]:
        qs.append({"q": "Your team decided \u201c%s\u201d (%s), and this changes %s. Does it still follow that?" % (
            d["title"][:140], d["source"], p), "why": "decision"})
    crit = [i for i in review.get("issues") or [] if i.get("severity") in ("critical", "high")]
    if crit:
        qs.append({"q": "%s at %s:%s. Is that intended, and what's the safer way?" % (
            _kind(crit[0]["message"]), crit[0]["file"], crit[0]["line"]), "why": "finding"})
    order = {"decision": 0, "hotspot": 1, "finding": 2, "tests": 3, "rollout": 4, "size": 5}
    return sorted(qs, key=lambda x: order.get(x["why"], 9))[:5]


def changes(rid, base=""):
    from . import review_coach_engine as RCE
    base = (base or "").strip()
    if base and not re.match(r"^[\w./-]{1,200}$", base):
        raise S.Invalid("that doesn't look like a branch name")
    root = _root(rid)
    r = RCE.review_changes(base or "main", root)
    if r.get("error") or r.get("message"):
        return r
    try:
        hot = hotspots(rid)
    except Exception:  # noqa: BLE001 - the review still stands without history
        hot = {"files": []}
    hot_by = {f["path"]: f for f in hot.get("files", [])}
    touched = [hot_by[f["path"]] for f in r.get("files_reviewed") or [] if f["path"] in hot_by]
    r["touches_hotspots"] = sorted((h for h in touched if h["level"] == "high" or h["fixes"] >= 2),
                                   key=lambda h: (h["level"] != "high", -h["fixes"]))
    try:
        decs = decisions(rid)
    except Exception:  # noqa: BLE001
        decs = []
    r["questions"] = senior_questions(r, hot, root, decs)
    r["patterns"] = _patterns(_remember(rid, r.get("issues") or []))
    r["files_reviewed"] = [{k: f.get(k) for k in ("path", "additions", "deletions", "new")}
                           for f in r.get("files_reviewed") or []]
    return r


# ---------------------------------------------------------------- one file

def explain(rid, path):
    from . import explain5_engine as EE
    return EE.explain_file(_tracked(rid, path), _root(rid))


def tests(rid, path):
    from . import test_suggester_engine as TSE
    return TSE.suggest_tests(_tracked(rid, path), _root(rid))


def why(rid, path, start="", end=""):
    from . import history_engine as HI
    path = _tracked(rid, path)
    s = int(start) if str(start or "").isdigit() else None
    e = int(end) if str(end or "").isdigit() else None
    return HI.why(_root(rid), path, s, e)


def view(name, rid, q):
    def a(k):
        v = q.get(k) if isinstance(q, dict) else None
        return (v[0] if isinstance(v, list) and v else v) or ""
    try:
        if name == "insight_files":
            return {"files": files(rid)[:20000]}
        if name == "insight_review":
            return changes(rid, a("base"))
        if name == "insight_hotspots":
            return hotspots(rid)
        if name == "insight_explain":
            return explain(rid, a("file"))
        if name == "insight_why":
            return why(rid, a("file"), a("start"), a("end"))
        return tests(rid, a("file"))
    except S.Invalid as e:
        return {"error": str(e)}
