"""Why is this code here? Every commit that shaped a function or a few lines, newest first, with the ticket, issue or
pull request each one mentions turned into a link.

`git blame` says who touched a line last. This answers the question people actually have when the code is
unfamiliar: which changes made it look like this, and why (the commit message, the issue it fixed, the PR it came
in with). Read-only git; links are built from the repo's own remote and the configured Linear workspace, so nothing
is fetched. Author: Varun Singh.
"""
import os
import re

from . import common as C
from .explain5_engine import FIX_RX

ISSUE_RX = re.compile(r"(?<![\w/])#(\d{1,7})\b")
TICKET_RX = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,7})\b")
PR_MERGE_RX = re.compile(r"Merge pull request #(\d+)|\(#(\d+)\)\s*$")


def _web_base(root):
    """https://github.com/owner/repo (or GitLab/Bitbucket) from the origin URL, or ""."""
    url = C.run(["git", "remote", "get-url", "origin"], cwd=root, timeout=10).stdout.strip()
    m = re.match(r"^(?:git@|ssh://git@|https?://)([\w.-]+)[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return "https://%s/%s" % (m.group(1), m.group(2)) if m else ""


def refs(text, web="", linear=""):
    """Issue/PR numbers and tracker keys a commit message mentions, as [{label, url}] (url may be "")."""
    out, seen = [], set()
    for m in PR_MERGE_RX.finditer(text):
        n = m.group(1) or m.group(2)
        if n and "#" + n not in seen:
            seen.add("#" + n)
            out.append({"label": "PR #%s" % n, "url": "%s/pull/%s" % (web, n) if "github.com" in web else ""})
    for n in ISSUE_RX.findall(text):
        if "#" + n not in seen:
            seen.add("#" + n)
            out.append({"label": "#%s" % n, "url": "%s/issues/%s" % (web, n) if "github.com" in web else ""})
    for k in TICKET_RX.findall(text):
        if k not in seen and not re.match(r"^(CVE|GHSA|UTF|ISO|RFC|SHA|HTTP|TLS)-", k):
            seen.add(k)
            out.append({"label": k, "url": "https://linear.app/%s/issue/%s" % (linear, k) if linear else ""})
    return out


def why(root, path, start=None, end=None, limit=15):
    """Commits that changed `path` (or only lines start..end of it), newest first:
    {path, start, end, commits: [{sha, author, date, subject, body, fix, refs}], authors, fixes}."""
    fmt = "--format=%x01%H%x02%an%x02%ad%x02%s%x02%b"
    if start:
        try:
            with open(os.path.join(root, path), "rb") as fh:
                n = max(1, fh.read(5_000_000).count(b"\n"))
        except OSError:
            n = int(start)
        start = min(int(start), n)
        end = min(max(int(end or n), start), n)  # no end: to the end of the file
        cmd = ["git", "log", "-L", "%d,%d:%s" % (int(start), end, path), "--no-patch", fmt, "--date=short",
               "-n", str(limit)]
    else:
        cmd = ["git", "log", "--follow", fmt, "--date=short", "-n", str(limit), "--", path]
    cp = C.run(cmd, cwd=root, timeout=60)
    web = _web_base(root)
    linear = ((C.config().get("linear") or {}).get("workspace") or "").strip()
    commits = []
    for block in cp.stdout.split("\x01") if cp.returncode == 0 else []:
        parts = block.strip("\n").split("\x02")
        if len(parts) < 4:
            continue
        subject, body = parts[3], (parts[4] if len(parts) > 4 else "").strip()
        body = "\n".join(x for x in body.splitlines() if not re.match(r"^(Co-Authored-By|Signed-off-by):", x, re.I))
        commits.append({"sha": parts[0][:12], "author": parts[1], "date": parts[2], "subject": subject,
                        "body": body[:1200], "fix": bool(FIX_RX.search(subject)),
                        "refs": refs(subject + "\n" + body, web, linear),
                        "url": "%s/commit/%s" % (web, parts[0]) if "github.com" in web else ""})
    return {"path": path, "start": start, "end": end, "commits": commits,
            "authors": len({c["author"] for c in commits}), "fixes": sum(c["fix"] for c in commits)}
