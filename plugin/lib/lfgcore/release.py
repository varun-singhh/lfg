"""`lfg release`: notes for each pull request, and turning what's on main into a numbered release, in a checkout of
LFG.

Each pull request that changes something a user sees writes its notes to a file of its own, `changes/<name>.json`
(`lfg release note`), so two open PRs never edit the same lines. They did when every PR added to the top of
CHANGELOG.md and releases.json, and the second to merge always conflicted:

    {"changelog": {"Added": ["..."], "Changed": [], "Fixed": []},
     "whats_new": [{"title": "...", "text": "...", "page": "prs", "sel": "#..."}]}

A release is one more pull request (`lfg release prepare <version>`): it bumps plugin.json's version, gathers every
changes/*.json (and any notes left the old way, under CHANGELOG.md's `## Unreleased` and releases.json's "unreleased"
entries) into the version's changelog section and What's new entry, and deletes the files it gathered. Once merged,
tag the merge commit `v<version>` and push the tag: Update installs releases (tags), not every merge to main.

Edits files in the checkout only; nothing is committed, pushed or tagged.
"""
import glob
import json
import os
import re
import time

UNRELEASED = "unreleased"
VERSION_RX = re.compile(r"^\d+\.\d+\.\d+$")
KINDS = ("Added", "Changed", "Fixed")
NAME_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")


def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])


def _paths(root):
    return {"plugin": os.path.join(root, "plugin", ".claude-plugin", "plugin.json"),
            "releases": os.path.join(root, "plugin", "releases.json"),
            "changelog": os.path.join(root, "CHANGELOG.md")}


def changes_dir(root):
    return os.path.join(root, "changes")


def _read(p):
    with open(p) as f:
        return f.read()


def _write(p, text):
    with open(p, "w") as f:
        f.write(text)


def _check_note(d, where):
    """A changes file's problems, as plain sentences ([] when it's fine)."""
    if not isinstance(d, dict):
        return ["%s isn't a JSON object" % where]
    bad = []
    log = d.get("changelog") or {}
    if not isinstance(log, dict) or any(k not in KINDS or not isinstance(v, list) or
                                        not all(isinstance(x, str) and x.strip() for x in v) for k, v in log.items()):
        bad.append("%s: changelog is {\"Added\"|\"Changed\"|\"Fixed\": [lines]}" % where)
    items = d.get("whats_new") or []
    if not isinstance(items, list) or not all(isinstance(i, dict) and str(i.get("title") or "").strip() and
                                              str(i.get("text") or "").strip() for i in items):
        bad.append("%s: each whats_new item needs a title and a text" % where)
    if not bad and not any(log.values()) and not items:
        bad.append("%s says nothing: give it a changelog line or a What's new item" % where)
    return bad


def note(root, name, added=(), changed=(), fixed=(), whats_new=()):
    """Write changes/<name>.json for a pull request (name: its branch). Replaces the file if it exists."""
    name = re.sub(r"[^a-z0-9._-]+", "-", str(name or "").lower()).strip("-.")
    if not NAME_RX.match(name):
        raise ValueError("name the notes after the branch, e.g. tabs-follow-repo")
    d = {"changelog": {k: [str(x).strip() for x in v if str(x).strip()]
                       for k, v in zip(KINDS, (added, changed, fixed)) if v},
         "whats_new": [dict(i) for i in whats_new]}
    bad = _check_note(d, "changes/%s.json" % name)
    if bad:
        raise ValueError("; ".join(bad))
    os.makedirs(changes_dir(root), exist_ok=True)
    path = os.path.join(changes_dir(root), name + ".json")
    _write(path, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return {"written": os.path.relpath(path, root)}


def pending(root):
    """Every changes/*.json in name order: [(path, notes)]. Raises on a file that isn't right."""
    out, bad = [], []
    for f in sorted(glob.glob(os.path.join(changes_dir(root), "*.json"))):
        try:
            d = json.loads(_read(f))
        except ValueError:
            bad.append("%s isn't valid JSON" % os.path.relpath(f, root))
            continue
        bad += _check_note(d, os.path.relpath(f, root))
        out.append((f, d))
    if bad:
        raise ValueError("; ".join(bad))
    return out


def prepare(root, version, title="", today=None):
    """Bump to version and gather every unreleased note under it. Returns what changed, and what's missing."""
    if not VERSION_RX.match(str(version or "")):
        raise ValueError("a version is three numbers, e.g. 0.5.0")
    p = _paths(root)
    for path in p.values():
        if not os.path.isfile(path):
            raise ValueError("no %s here: run it in your LFG checkout" % os.path.relpath(path, root))
    plugin = json.loads(_read(p["plugin"]))
    current = plugin.get("version") or "0.0.0"
    if _ver(version) <= _ver(current):
        raise ValueError("%s isn't newer than %s" % (version, current))
    today = today or time.strftime("%Y-%m-%d")
    files = pending(root)
    notes = []

    # What's new: the old way's "unreleased" entries first, then each changes file's items
    rel = json.loads(_read(p["releases"]))
    rs = rel.get("releases") or []
    old = [r for r in rs if r.get("version") in (UNRELEASED, version)]
    items = [i for r in old for i in r.get("items") or []] + [i for _, d in files for i in d.get("whats_new") or []]
    title = title or next((r["title"] for r in old if r.get("title") and r["title"].lower() != UNRELEASED), "")
    if not title:
        notes.append("give the release a title (--title): What's new shows it")
    if not items:
        notes.append("nothing for What's new: users are told nothing about %s" % version)
    rs = [r for r in rs if r not in old]
    if items:
        rs.insert(0, {"version": version, "title": title or version, "items": items})
    rel["releases"] = rs

    # Changelog: what's under ## Unreleased, then each changes file's lines, one heading per kind
    log = _read(p["changelog"])
    m = re.search(r"^## Unreleased[^\n]*\n", log, re.M)
    if not m:
        raise ValueError("CHANGELOG.md has no `## Unreleased` section")
    nxt = re.search(r"^## ", log[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(log)
    groups = {}
    for h, body in re.findall(r"^### ([^\n]+)\n(.*?)(?=^### |\Z)", log[m.end():end], re.M | re.S):
        groups.setdefault(h.strip(), []).extend(ln for ln in body.strip().splitlines() if ln.strip())
    for _, d in files:
        for k, lines in (d.get("changelog") or {}).items():
            groups.setdefault(k, []).extend("- " + re.sub(r"^-\s*", "", x.strip()) for x in lines)
    if not any(groups.values()):
        notes.append("no changelog lines for %s" % version)
    order = [k for k in KINDS if groups.get(k)] + [k for k in groups if k not in KINDS and groups[k]]
    section = "".join("\n### %s\n%s\n" % (k, "\n".join(groups[k])) for k in order)
    log = log[:m.start()] + "## Unreleased\n\n## %s (%s)\n%s\n" % (version, today, section) + log[end:]

    plugin["version"] = version
    _write(p["plugin"], json.dumps(plugin, indent=2, ensure_ascii=False) + "\n")
    _write(p["releases"], json.dumps(rel, indent=2, ensure_ascii=False) + "\n")
    _write(p["changelog"], log)
    for f, _ in files:
        os.remove(f)
    return {"from": current, "to": version,
            "changed": [os.path.relpath(x, root) for x in p.values()] +
                       ["%s (gathered, deleted)" % os.path.relpath(f, root) for f, _ in files],
            "notes": notes, "next": "open a PR; once merged, tag it: git tag -m 'LFG %s' v%s <merge commit> && "
                                    "git push origin v%s" % (version, version, version)}
