"""`lfg release prepare <version>`: turn what's on main into a numbered release, in a checkout of LFG.

Features land on main as pull requests, each adding its notes under "unreleased": CHANGELOG.md's `## Unreleased`
section, and plugin/releases.json's entry with version "unreleased" (what the user is told: What's new). A release
is one more pull request that names them: this command bumps plugin.json's version, renames the releases.json entry
and moves the changelog's Unreleased notes under the version, leaving an empty Unreleased above. Once it is merged,
tag the merge commit `v<version>` and push the tag: Update installs releases (tags), not every merge to main.

Edits files in the checkout only; nothing is committed, pushed or tagged.
"""
import json
import os
import re
import time

UNRELEASED = "unreleased"
VERSION_RX = re.compile(r"^\d+\.\d+\.\d+$")


def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])


def _paths(root):
    return {"plugin": os.path.join(root, "plugin", ".claude-plugin", "plugin.json"),
            "releases": os.path.join(root, "plugin", "releases.json"),
            "changelog": os.path.join(root, "CHANGELOG.md")}


def _read(p):
    with open(p) as f:
        return f.read()


def _write(p, text):
    with open(p, "w") as f:
        f.write(text)


def prepare(root, version, title="", today=None):
    """Bump to version and name the unreleased notes after it. Returns what changed, and what's missing."""
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
    notes = []

    rel = json.loads(_read(p["releases"]))
    rs = rel.get("releases") or []
    entry = next((r for r in rs if r.get("version") in (UNRELEASED, version)), None)
    if entry:
        entry["version"] = version
        if title:
            entry["title"] = title
        if not entry.get("title") or entry["title"].lower() == UNRELEASED:
            notes.append("give the release a title in plugin/releases.json (--title)")
        if not entry.get("items"):
            notes.append("plugin/releases.json has no What's new items for it")
        rs.remove(entry)
        rs.insert(0, entry)
    else:
        notes.append("plugin/releases.json has no unreleased notes: users get no What's new for %s" % version)
    rel["releases"] = rs

    log = _read(p["changelog"])
    m = re.search(r"^## Unreleased[^\n]*\n", log, re.M)
    if not m:
        raise ValueError("CHANGELOG.md has no `## Unreleased` section")
    nxt = re.search(r"^## ", log[m.end():], re.M)
    if not log[m.end():m.end() + nxt.start() if nxt else len(log)].strip():
        notes.append("CHANGELOG.md's Unreleased section is empty")
    log = log[:m.start()] + "## Unreleased\n\n## %s (%s)\n" % (version, today) + log[m.end():]

    plugin["version"] = version
    _write(p["plugin"], json.dumps(plugin, indent=2, ensure_ascii=False) + "\n")
    _write(p["releases"], json.dumps(rel, indent=2, ensure_ascii=False) + "\n")
    _write(p["changelog"], log)
    return {"from": current, "to": version, "changed": [os.path.relpath(x, root) for x in p.values()],
            "notes": notes, "next": "open a PR; once merged, tag it: git tag v%s <merge commit> && "
                                    "git push origin v%s" % (version, version)}
