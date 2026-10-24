"""Code review coach engine.

Provides code review feedback before PR submission.
Author: Varun Singh.
"""
import os
import re
from . import common as C


TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|fixtures?)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$")


_STR = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")


def _code_only(line, language):
    """The line with string contents and trailing comments removed, so pattern names and messages in strings or
    comments (like this engine's own rules) aren't mistaken for code."""
    code = _STR.sub('""', line)
    cut = code.find("#") if language == "python" else code.find("//")
    return code[:cut] if cut >= 0 else code


def _is_comment(line):
    return line.lstrip().startswith(("#", "//", "/*", "*", "<!--"))


def review_changes(base_branch="main", repo_root=None):
    """Review current changes and provide feedback.

    Args:
        base_branch: Base branch for comparison (default: main, auto-detected if not given)
        repo_root: Repository root (default: current repo)

    Returns:
        Dict with review feedback, issues, and risk level
    """
    root = repo_root or C.repo_root(os.getcwd())
    if not root:
        return {"error": "Not in a git repository"}

    C.audit("review_coach_start", {"base_branch": base_branch})

    result = {
        "base_branch": base_branch,
        "files_reviewed": [],
        "issues": [],
        "risk_level": "READY_TO_REVIEW",
        "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
    }

    try:
        # Determine base branch if not given
        if base_branch == "main":
            # Try origin/HEAD first, then main, then master
            cp = C.run(["git", "rev-parse", "--verify", "origin/HEAD"], cwd=root)
            if cp.returncode == 0:
                # origin/HEAD exists, extract branch name
                cp2 = C.run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=root)
                if cp2.returncode == 0:
                    base_branch = cp2.stdout.strip().replace("origin/", "")
            else:
                # Try main, then master
                for branch in ["main", "master"]:
                    cp = C.run(["git", "rev-parse", "--verify", f"origin/{branch}"], cwd=root)
                    if cp.returncode == 0:
                        base_branch = branch
                        break

        # Get diff
        diff = _get_diff(base_branch, root) or ""
        if not diff and not _untracked_files(root):
            result["message"] = "No changes to review."
            return result

        # Parse changed files, plus new files not added to git yet (git diff doesn't show them)
        changed_files = _parse_diff_files(diff) + _untracked_files(root)
        result["files_reviewed"] = changed_files

        # Analyze each file
        for file_info in changed_files:
            file_review = _review_file(file_info, root)
            result["issues"].extend(file_review.get("issues", []))

        # Test files plant fake secrets and odd inputs on purpose: keep the finding, as low
        for issue in result["issues"]:
            if TEST_PATH.search(issue.get("file", "")) and issue.get("severity") in ("critical", "high", "medium"):
                issue["message"] += " (in a test file)"
                issue["severity"] = "low"

        # Calculate counts by severity
        for issue in result["issues"]:
            sev = issue.get("severity", "medium").lower()
            if sev in result["counts"]:
                result["counts"][sev] += 1

        # Determine risk level
        if result["counts"]["critical"] > 0:
            result["risk_level"] = "HIGH_RISK"
        elif result["counts"]["high"] > 0:
            result["risk_level"] = "NEEDS_WORK"
        else:
            result["risk_level"] = "READY_TO_REVIEW"

    except Exception as e:
        result["error"] = str(e)
        C.audit("review_coach_error", {"error": str(e)})

    C.audit("review_coach_complete", {"files": len(result.get("files_reviewed", []))})
    return result


def _get_diff(base_branch, root):
    """Everything this branch changes: committed since it left `base_branch`, plus staged and unstaged edits
    (`git diff <merge-base>` compares the working tree with the fork point). Off the base branch or without one,
    just the uncommitted edits (`git diff HEAD`)."""
    mb = ""
    for ref in ("origin/%s" % base_branch, base_branch):
        cp = C.run(["git", "merge-base", ref, "HEAD"], cwd=root)
        if cp.returncode == 0 and cp.stdout.strip():
            mb = cp.stdout.strip()
            break
    cp = C.run(["git", "diff", "--no-color", "--no-ext-diff", mb or "HEAD"], cwd=root)
    return cp.stdout if cp.returncode == 0 and cp.stdout.strip() else None


def _untracked_files(root, max_bytes=500_000):
    """New files git would track but that aren't added yet: every line counts as added."""
    cp = C.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=root, timeout=20)
    out = []
    for path in (cp.stdout.splitlines() if cp.returncode == 0 else []):
        full = os.path.join(root, path)
        try:
            if os.path.getsize(full) > max_bytes:
                continue
            with open(full, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if b"\0" in data[:4096]:  # binary
            continue
        lines = data.decode("utf-8", "replace").splitlines()
        out.append({"path": path, "changes": [{"line": i, "content": t} for i, t in enumerate(lines, 1)],
                    "additions": len(lines), "deletions": 0, "new": True})
    return out


def _parse_diff_files(diff):
    """Changed files with their added lines, each numbered as in the new file (from the hunk headers)."""
    files, cur, line_no = [], None, 0
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            cur = None
        elif line.startswith("+++ "):
            path = line[4:].strip()
            if path == "/dev/null":  # deleted file: nothing added to review
                cur = None
                continue
            cur = {"path": path[2:] if path.startswith("b/") else path, "changes": [], "additions": 0,
                   "deletions": 0}
            files.append(cur)
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@ "):
            m = re.search(r"\+(\d+)", line)
            line_no = int(m.group(1)) if m else 1
        elif cur is None:
            continue
        elif line.startswith("+"):
            cur["changes"].append({"line": line_no, "content": line[1:]})
            cur["additions"] += 1
            line_no += 1
        elif line.startswith("-"):
            cur["deletions"] += 1
        elif not line.startswith("\\"):
            line_no += 1
    return files


def _review_file(file_info, root):
    """Review a single file's changes."""
    result = {
        "file": file_info["path"],
        "issues": [],
    }

    changes = file_info.get("changes", [])
    file_path = file_info.get("path", "")

    # Determine language
    language = _detect_language(file_path)

    # Track context for N+1 detection (loop + DB call in next few lines)
    for i, change in enumerate(changes):
        line_num = change.get("line", 1)
        content = change.get("content", "")

        # Security checks
        issue = _check_security(content, line_num, file_path, language)
        if issue:
            result["issues"].append(issue)

        # Performance checks (N+1: loop body contains DB/HTTP call)
        issue = _check_performance(content, line_num, file_path, changes, i, language)
        if issue:
            result["issues"].append(issue)

        # Correctness checks
        nxt = changes[i + 1]["content"] if i + 1 < len(changes) else ""
        issue = _check_correctness(content, line_num, file_path, language, nxt)
        if issue:
            result["issues"].append(issue)

    return result


def _detect_language(file_path):
    """Detect programming language from file extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".java": "java",
        ".rb": "ruby",
        ".rs": "rust",
        ".c": "c",
        ".cpp": "cpp",
    }
    _, ext = os.path.splitext(file_path)
    return ext_map.get(ext.lower(), "unknown")


def _check_security(line, line_num, file_path, language):
    """Check for security issues."""

    if _is_comment(line):
        return None
    code = _code_only(line, language)
    # Hardcoded passwords/secrets
    patterns = [
        (r"password\s*=\s*['\"][^'\"]+['\"]", "Hardcoded password detected", "critical"),
        (r"api_key\s*=\s*['\"][^'\"]+['\"]", "Hardcoded API key detected", "critical"),
        (r"secret\s*=\s*['\"][^'\"]+['\"]", "Hardcoded secret detected", "critical"),
        (r"token\s*=\s*['\"][^'\"]+['\"]", "Hardcoded token detected", "critical"),
    ]

    for pattern, message, severity in patterns:
        if re.search(pattern, line, re.I):
            return {
                "type": "security",
                "severity": severity,
                "file": file_path,
                "line": line_num,
                "message": message,
                "suggestion": "Use environment variables or secret management",
            }

    # SQL injection (Python)
    if language == "python":
        if re.search(r"['\"]SELECT.*\+|f['\"]SELECT", line, re.I):
            return {
                "type": "security",
                "severity": "high",
                "file": file_path,
                "line": line_num,
                "message": "Potential SQL injection",
                "suggestion": "Use parameterized queries",
            }

        # eval/exec
        if re.search(r"\b(eval|exec)\s*\(", code) and not re.search(r"\.(eval|exec)\s*\(", code):
            return {
                "type": "security",
                "severity": "high",
                "file": file_path,
                "line": line_num,
                "message": "Use of eval/exec - potential security risk",
                "suggestion": "Avoid eval/exec, use safer alternatives",
            }

    # JavaScript/TypeScript security
    if language in ["javascript", "typescript"]:
        # eval
        if re.search(r"(?<![.\w])eval\s*\(", code):
            return {
                "type": "security",
                "severity": "high",
                "file": file_path,
                "line": line_num,
                "message": "Use of eval() - security risk",
                "suggestion": "Avoid eval(), use JSON.parse() for JSON",
            }

        # innerHTML - only flag when template literal or string concat without esc()
        m = re.search(r"\.innerHTML\s*=", line)
        if m and ("${" in line or "+" in line) and "esc(" not in line:
            return {
                "type": "security",
                "severity": "medium",
                "file": file_path,
                "line": line_num,
                "message": "Potential XSS via innerHTML",
                "suggestion": "Use textContent or sanitize input",
            }

    return None


def _check_performance(line, line_num, file_path, changes, change_idx, language):
    """Check for performance issues, especially N+1 queries."""
    # N+1 detection: loop that might contain DB/HTTP call
    loop_patterns = [
        (r"^\s*for\s+\w+\s+in\s+.*:\s*$", "python"),
        (r"^\s*for\s*\(", "javascript"),
        (r".*\.forEach\s*\(", "javascript"),
        (r"^\s*for\s+.*\{", "go"),
    ]

    is_loop_start = False
    for pattern, lang in loop_patterns:
        if lang == language or lang in ["python", "javascript", "go"]:
            if re.search(pattern, line):
                is_loop_start = True
                break

    if is_loop_start:
        # Check next ~5 added lines for DB/HTTP call patterns
        db_http_patterns = [
            r"\.execute\s*\(",
            r"\.query\s*\(",
            r"\.objects\.",
            r"(?<![.\w])fetch\s*\(",
            r"\brequests\.(get|post|put|patch|delete)\s*\(",
            r"\baxios\.",
            r"\bcursor\.",
            r"\.find(One)?\(\s*\{",
            r"\bSELECT\s+.+\bFROM\b",
        ]

        for j in range(change_idx + 1, min(change_idx + 6, len(changes))):
            next_line = changes[j].get("content", "")
            if changes[j].get("line") != line_num + (j - change_idx):
                break  # not the next line in the file: the loop body isn't all in this change
            if language == "python" and next_line.strip() and \
                    len(next_line) - len(next_line.lstrip()) <= len(line) - len(line.lstrip()):
                break  # dedent: the loop body has ended
            if _is_comment(next_line):
                continue
            code = _code_only(next_line, language)
            for pattern in db_http_patterns:
                if re.search(pattern, next_line if "SELECT" in pattern else code, re.I):
                    return {
                        "type": "performance",
                        "severity": "medium",
                        "file": file_path,
                        "line": line_num,
                        "message": "Potential N+1 query in loop",
                        "suggestion": "Check if there are DB queries inside this loop",
                    }

    return None


def _check_correctness(line, line_num, file_path, language, next_line=""):
    """Errors swallowed silently: a bare or broad `except` whose body is just `pass` (Python), or an empty `catch {}`
    (JS/TS). A call without try/except is not flagged: most calls shouldn't be wrapped."""
    swallowed = False
    if language == "python":
        swallowed = bool(re.match(r"\s*except(\s+(Exception|BaseException))?\s*(as\s+\w+)?\s*:\s*(pass)?\s*$", line)) \
            and (line.rstrip().endswith("pass") or next_line.strip() == "pass")
    elif language in ("javascript", "typescript"):
        swallowed = bool(re.search(r"catch\s*(\([^)]*\))?\s*\{\s*\}", line))
    if swallowed:
        return {"type": "correctness", "severity": "medium", "file": file_path, "line": line_num,
                "message": "Error swallowed silently (empty or broad except/catch)",
                "suggestion": "Catch the specific error, and log or handle it"}
    return None
