"""Explain code in plain English engine.

Uses git history, code analysis, and test discovery.
Author: Varun Singh.
"""
import ast
import os
import re
from . import common as C


def explain_file(file_path, repo_root=None):
    """Explain a file in plain English.

    Args:
        file_path: Path to the file (relative or absolute)
        repo_root: Repository root (default: current repo)

    Returns:
        Dict with structured explanation
    """
    root = repo_root or C.repo_root(os.getcwd())
    if not root:
        return {"error": "Not in a git repository", "file": file_path}

    # Resolve file path
    if not os.path.isabs(file_path):
        full_path = os.path.join(root, file_path)
    else:
        full_path = file_path
        file_path = os.path.relpath(file_path, root)

    # Check file exists
    if not os.path.isfile(full_path):
        return {"error": "File not found: %s" % file_path, "file": file_path}

    C.audit("explain5_start", {"file": file_path})

    result = {
        "file": file_path,
        "summary": "",
        "how_it_works": [],
        "why_its_here": {},
        "related_tests": [],
        "potential_issues": [],
    }

    try:
        # Get file content and language
        content = C.read_text(full_path)
        result["language"] = _detect_language(file_path)

        # Get git blame info
        result["why_its_here"] = _get_blame_info(file_path, root)

        # Find related tests
        result["related_tests"] = _find_related_tests(file_path, root)

        # Generate summary from docstring/comments
        result["summary"] = _generate_summary(content, result["language"])

        # Extract structure (defs/classes)
        result["how_it_works"] = _extract_structure(content, result["language"])

        # Find potential issues
        result["potential_issues"] = _find_issues(content, result["language"])

    except Exception as e:
        result["error"] = str(e)
        C.audit("explain5_error", {"file": file_path, "error": str(e)})

    C.audit("explain5_complete", {"file": file_path})
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
        ".h": "c",
        ".hpp": "cpp",
        ".sh": "bash",
        ".sql": "sql",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
    }
    _, ext = os.path.splitext(file_path)
    return ext_map.get(ext.lower(), "unknown")


def _get_blame_info(file_path, root):
    """Get git blame information for the file."""
    cp = C.run(
        ["git", "log", "--reverse", "--format=%H|%an|%ae|%ai|%s", "--follow", "--", file_path],
        cwd=root
    )

    if cp.returncode != 0 or not cp.stdout.strip():
        return {}

    lines = cp.stdout.strip().split("\n")
    if not lines:
        return {}

    # First commit (creation)
    try:
        first_parts = lines[0].split("|", 4)
        author = first_parts[1] if len(first_parts) > 1 else "Unknown"
        date = first_parts[3][:10] if len(first_parts) > 3 else "Unknown"
        message = first_parts[4] if len(first_parts) > 4 else ""
    except (IndexError, ValueError):
        author, date, message = "Unknown", "Unknown", ""

    # Last commit (most recent change)
    last_author, last_date = author, date
    if len(lines) > 1:
        try:
            last_parts = lines[-1].split("|", 4)
            last_author = last_parts[1] if len(last_parts) > 1 else author
            last_date = last_parts[3][:10] if len(last_parts) > 3 else date
        except (IndexError, ValueError):
            pass

    return {
        "created_by": author,
        "created_date": date,
        "created_message": message[:100] if message else "",
        "last_modified_by": last_author,
        "last_modified_date": last_date,
        "total_commits": len(lines),
        "recent_fixes": _recent_fixes(lines),
    }


class _FixDetector:
    """A commit subject that says it fixed something, not a release or version roll-up that only lists fixes.
    Shared by recent fixes, hotspots, history and regression-test ideas so they all agree."""
    START = re.compile(r"^\s*(\[?(fix|bug|hotfix|bugfix)\b|fix(es|ed)?\s*[:(])", re.I)
    ANY = re.compile(r"\b(fix(es|ed|ing)?|bugfix|hotfix|regression|crash(es|ed|ing)?|broken)\b", re.I)
    RELEASE = re.compile(r"^\s*(release|bump|merge|revert)\b|^\s*v?\d+\.\d+(\.\d+)?\b|^\s*[\w.-]+\s+v?\d+\.\d+(\.\d+)?"
                         r"\s*[:-]", re.I)

    def search(self, text):
        text = text or ""
        if self.RELEASE.search(text):
            return None
        return self.START.search(text) or self.ANY.search(text)


FIX_RX = _FixDetector()


def _recent_fixes(log_lines, limit=5):
    """Commits on this file in the last 180 days whose subject says they fixed something (newest first)."""
    import datetime
    cutoff = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    out = []
    for line in reversed(log_lines):
        parts = line.split("|", 4)
        if len(parts) == 5 and parts[3][:10] >= cutoff and FIX_RX.search(parts[4]):
            out.append({"sha": parts[0][:12], "date": parts[3][:10], "author": parts[1], "message": parts[4][:120]})
            if len(out) >= limit:
                break
    return out


TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$")


def related_tests(file_path, root):
    """Test files for this module: named after it (test_<name>, <name>_test, <name>.test/.spec) or importing it
    (Python `import`/`from`, JS/TS `import ... from` / `require`). One `git ls-files` and one `git grep`."""
    base = os.path.splitext(os.path.basename(file_path))[0]
    if not base or base == "__init__":
        base = os.path.basename(os.path.dirname(file_path))
    if not base:
        return []
    cp = C.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, timeout=20)
    tests = [f for f in cp.stdout.splitlines() if TEST_FILE.search(f) and f != file_path] if cp.returncode == 0 else []
    if not tests:
        return []
    b = re.escape(base)
    named = {f for f in tests if re.search(r"(^|/)(test_)?%s([_.-](test|spec))?\.\w+$" % b, f)}
    imp = re.compile(r"^\s*(from\s+[\w.]*\b%s\b[\w.]*\s+import\b|import\s+[\w.]*\b%s\b"
                     r"|from\s+[\w.]+\s+import\s+.*\b%s\b)"
                     r"|from\s+['\"][^'\"]*\b%s['\"]|require\(\s*['\"][^'\"]*\b%s['\"]" % ((b,) * 5), re.M)
    g = C.run(["git", "grep", "--untracked", "-l", "-w", "-F", base, "--"] + tests, cwd=root,
              timeout=20)  # cheap prefilter (new test files too)
    importing = set()
    for f in (g.stdout.splitlines() if g.returncode == 0 else []):
        try:
            with open(os.path.join(root, f), errors="replace") as fh:
                if imp.search(fh.read(400_000)):
                    importing.add(f)
        except OSError:
            pass
    return sorted(named | importing)[:10]


def _find_related_tests(file_path, root):
    return related_tests(file_path, root)


def _extract_structure(content, language):
    """Extract top-level definitions (functions, classes) with line numbers."""
    structure = []
    lines = content.split("\n")

    if language == "python":
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Only top-level or class-level
                    if hasattr(node, 'col_offset') and node.col_offset == 0:
                        docstring = ast.get_docstring(node)
                        structure.append({
                            "line": node.lineno,
                            "type": "function",
                            "name": node.name,
                            "docstring": docstring.split("\n")[0] if docstring else None,
                        })
                elif isinstance(node, ast.ClassDef):
                    if hasattr(node, 'col_offset') and node.col_offset == 0:
                        docstring = ast.get_docstring(node)
                        structure.append({
                            "line": node.lineno,
                            "type": "class",
                            "name": node.name,
                            "docstring": docstring.split("\n")[0] if docstring else None,
                        })
        except SyntaxError:
            # Fallback to regex if AST fails
            for i, line in enumerate(lines, 1):
                m = re.match(r"^(def|class)\s+(\w+)", line)
                if m:
                    structure.append({"line": i, "type": m.group(1), "name": m.group(2)})
    elif language in ["javascript", "typescript"]:
        # Regex-based for JS/TS
        for i, line in enumerate(lines, 1):
            # Functions
            m = re.match(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", line)
            if m:
                structure.append({"line": i, "type": "function", "name": m.group(1)})
            # Classes
            m = re.match(r"^\s*(?:export\s+)?class\s+(\w+)", line)
            if m:
                structure.append({"line": i, "type": "class", "name": m.group(1)})
            # Arrow functions
            m = re.match(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", line)
            if m:
                structure.append({"line": i, "type": "function", "name": m.group(1)})

    return structure[:40]  # Up to 40 items


def _first_paragraph(text, limit=600):
    para = re.split(r"\n\s*\n", (text or "").strip(), maxsplit=1)[0]
    para = " ".join(para.split())
    if len(para) <= limit:
        return para
    cut = para[:limit]
    end = max(cut.rfind(". "), cut.rfind(": "))
    return (cut[:end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0] + "…")


def _generate_summary(content, language):
    """What the file says about itself: the module docstring (Python) or the leading comment block, first
    paragraph only. "" when it says nothing."""
    if language == "python":
        try:
            doc = ast.get_docstring(ast.parse(content))
        except (SyntaxError, ValueError):
            doc = None
        if doc:
            return _first_paragraph(doc)
    lines = content.lstrip("\ufeff").splitlines()
    m = re.match(r"\s*/\*\*?(.*?)\*/", content, re.S)
    if m and language in ("javascript", "typescript", "go", "rust", "java", "c", "cpp"):
        return _first_paragraph(re.sub(r"^\s*\* ?", "", m.group(1), flags=re.M))
    marks = ("#",) if language in ("python", "ruby", "shell") else ("//", "#")
    block = []
    for line in lines[:40]:
        t = line.strip()
        if not t and not block:
            continue
        if t.startswith("#!") or t.startswith("# -*-"):
            continue
        mk = next((k for k in marks if t.startswith(k)), None)
        if not mk:
            break
        block.append(t[len(mk):].strip())
    return _first_paragraph("\n".join(block)) if block else ""


def _find_issues(content, language):
    """Find potential issues in the code."""
    issues = []
    lines = content.split("\n")

    for i, line in enumerate(lines, 1):
        # Check for TODO/FIXME
        if "TODO" in line or "FIXME" in line:
            issues.append({
                "line": i,
                "type": "todo",
                "message": line.strip()[:100],
            })

        # Check for hardcoded passwords (security)
        if re.search(r"password\s*=\s*['\"]", line, re.I):
            issues.append({
                "line": i,
                "type": "security",
                "severity": "high",
                "message": "Hardcoded password detected",
            })

        # Check for eval/exec (security) - Python only
        if language == "python":
            if re.search(r"\beval\s*\(", line) or re.search(r"\bexec\s*\(", line):
                issues.append({
                    "line": i,
                    "type": "security",
                    "severity": "medium",
                    "message": "Use of eval/exec - potential security risk",
                })

        # Check for SQL injection (security)
        if re.search(r"['\"]SELECT.*\+|f['\"]SELECT", line, re.I):
            issues.append({
                "line": i,
                "type": "security",
                "severity": "high",
                "message": "Potential SQL injection vulnerability",
            })

    return issues[:10]
