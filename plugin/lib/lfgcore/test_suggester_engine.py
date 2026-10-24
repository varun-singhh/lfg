"""Smart test suggestion engine.

Suggests tests based on code analysis and patterns.
Author: Varun Singh.
"""
import ast
import os
import re
from . import common as C


def suggest_tests(file_path, repo_root=None):
    """Suggest tests for a given file.

    Args:
        file_path: Path to the source file
        repo_root: Repository root (default: current repo)

    Returns:
        Dict with suggested tests, priorities, and related test files
    """
    root = repo_root or C.repo_root(os.getcwd())
    if not root:
        return {"error": "Not in a git repository", "file": file_path}

    # Resolve path
    if not os.path.isabs(file_path):
        full_path = os.path.join(root, file_path)
    else:
        full_path = file_path
        file_path = os.path.relpath(file_path, root)

    if not os.path.isfile(full_path):
        return {"error": "File not found: %s" % file_path, "file": file_path}

    C.audit("test_suggest_start", {"file": file_path})

    result = {
        "file": file_path,
        "language": _detect_language(file_path),
        "functions": [],
        "classes": [],
        "suggested_tests": [],
        "related_tests": [],
        "priority_summary": {},
    }

    try:
        # Read and analyze code
        content = C.read_text(full_path)

        # Extract functions and classes
        result["functions"], result["classes"] = _extract_definitions(content, result["language"])

        # Filter to public functions/classes (skip private unless that's all there is)
        public_fns = [f for f in result["functions"] if not f["name"].startswith("_")]
        if not public_fns:
            public_fns = result["functions"]  # All private, use them

        public_cls = [c for c in result["classes"] if not c["name"].startswith("_")]
        if not public_cls:
            public_cls = result["classes"]

        # Generate test suggestions for each public function
        for func in public_fns:
            suggestions = _suggest_for_function(func, content, result["language"])
            result["suggested_tests"].extend(suggestions)

        # Generate test suggestions for each public class
        for cls in public_cls:
            suggestions = _suggest_for_class(cls, content, result["language"])
            result["suggested_tests"].extend(suggestions)

        # Find existing test files
        result["related_tests"] = _find_related_tests(file_path, root)

        # Bugs this file already had: a test for each keeps it fixed
        result["suggested_tests"] = _regressions(file_path, root) + result["suggested_tests"]

        # Prioritize suggestions
        result = _prioritize_suggestions(result)

    except Exception as e:
        result["error"] = str(e)
        C.audit("test_suggest_error", {"file": file_path, "error": str(e)})

    if not result.get("error"):
        result["skeleton"] = skeleton(result, root)
    C.audit("test_suggest_complete", {"file": file_path, "suggestions": len(result.get("suggested_tests", []))})
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


def _extract_definitions(content, language):
    """Extract function and class definitions."""
    functions = []
    classes = []
    lines = content.split("\n")

    if language == "python":
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if hasattr(node, 'col_offset') and node.col_offset == 0:
                        params = [arg.arg for arg in node.args.args if arg.arg != "self"]
                        docstring = ast.get_docstring(node)
                        functions.append({
                            "name": node.name,
                            "line": node.lineno,
                            "params": params,
                            "docstring": docstring.split("\n")[0] if docstring else None,
                        })
                elif isinstance(node, ast.ClassDef):
                    if hasattr(node, 'col_offset') and node.col_offset == 0:
                        classes.append({
                            "name": node.name,
                            "line": node.lineno,
                            "methods": [],
                        })
        except SyntaxError:
            # Fallback to regex
            for i, line in enumerate(lines, 1):
                m = re.match(r"^def\s+(\w+)\s*\(([^)]*)\)", line)
                if m:
                    params = [p.strip().split(":")[0].strip() for p in m.group(2).split(",")
                              if p.strip() and p.strip() != "self"]
                    functions.append({"name": m.group(1), "line": i, "params": params})
                m = re.match(r"^class\s+(\w+)", line)
                if m:
                    classes.append({"name": m.group(1), "line": i, "methods": []})

    elif language in ["javascript", "typescript"]:
        for i, line in enumerate(lines, 1):
            m = re.match(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", line)
            if m:
                functions.append({
                    "name": m.group(1),
                    "line": i,
                    "params": [p.strip() for p in m.group(2).split(",") if p.strip()],
                })

            m = re.match(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:\([^)]*\)|[^=]*)\s*=>", line)
            if m:
                functions.append({"name": m.group(1), "line": i, "params": []})

            m = re.match(r"^\s*(?:export\s+)?class\s+(\w+)", line)
            if m:
                classes.append({"name": m.group(1), "line": i, "methods": []})

    return functions, classes


def _suggest_for_function(func, content, language):
    """Generate test suggestions for a function based on code analysis."""
    suggestions = []
    func_name = func.get("name", "")
    params = func.get("params", [])

    # Look for patterns in the function body (simplified)
    lines = content.split("\n")
    start_line = func.get("line", 1)

    # Grab next ~30 lines after function definition
    func_lines = lines[start_line - 1:start_line + 30]

    # Find edge cases from code patterns
    has_none_return = any("return None" in line or "return null" in line for line in func_lines)
    has_exception = any("raise " in line or "throw " in line for line in func_lines)
    has_if_not = any(re.match(r"^\s*if\s+not\s+", line) for line in func_lines)
    has_comparison = any(re.search(r"if\s+\w+\s*(==|!=|>|<)\s+", line) for line in func_lines)
    has_loop = any("for " in line or "while " in line for line in func_lines)

    # Priority 1: Happy path (always suggest)
    suggestions.append({
        "function": func_name,
        "priority": 1,
        "category": "happy_path",
        "test_name": "test_%s_returns_expected" % func_name,
        "reason": "Happy path - basic functionality",
    })

    # Priority 2: Edge cases based on code patterns
    if has_none_return:
        suggestions.append({
            "function": func_name,
            "priority": 2,
            "category": "edge_case",
            "test_name": "test_%s_returns_none_when_appropriate" % func_name,
            "reason": "Found 'return None' in function",
        })

    if has_exception:
        suggestions.append({
            "function": func_name,
            "priority": 2,
            "category": "error_handling",
            "test_name": "test_%s_raises_on_invalid_input" % func_name,
            "reason": "Found raise/throw in function",
        })

    if has_if_not:
        suggestions.append({
            "function": func_name,
            "priority": 2,
            "category": "edge_case",
            "test_name": "test_%s_handles_falsy_input" % func_name,
            "reason": "Found 'if not' check in function",
        })

    if has_comparison:
        suggestions.append({
            "function": func_name,
            "priority": 2,
            "category": "boundary",
            "test_name": "test_%s_boundary_values" % func_name,
            "reason": "Found comparison in function",
        })

    if has_loop:
        suggestions.append({
            "function": func_name,
            "priority": 3,
            "category": "iteration",
            "test_name": "test_%s_with_multiple_items" % func_name,
            "reason": "Found loop in function",
        })

    # Generic edge cases for params
    for param in params[:3]:
        suggestions.append({
            "function": func_name,
            "priority": 3,
            "category": "edge_case",
            "test_name": "test_%s_with_empty_%s" % (func_name, param),
            "reason": "Edge case: %s empty" % param,
        })

    return suggestions


def _suggest_for_class(cls, content, language):
    """Generate test suggestions for a class."""
    suggestions = []
    cls_name = cls.get("name", "")

    # Instantiation test
    suggestions.append({
        "class": cls_name,
        "priority": 1,
        "category": "instantiation",
        "test_name": "test_%s_instantiation" % cls_name.lower(),
        "reason": "Class should instantiate correctly",
    })

    # State tests
    suggestions.append({
        "class": cls_name,
        "priority": 2,
        "category": "state",
        "test_name": "test_%s_state_changes" % cls_name.lower(),
        "reason": "Class state should be consistent",
    })

    return suggestions


def _find_related_tests(file_path, root):
    from .explain5_engine import related_tests
    return related_tests(file_path, root)


def _prioritize_suggestions(result):
    """Sort and prioritize test suggestions."""
    suggestions = result.get("suggested_tests", [])

    # Sort by priority
    suggestions.sort(key=lambda x: x.get("priority", 99))

    # Create summary
    priority_counts = {}
    for suggestion in suggestions:
        priority = suggestion.get("priority", 0)
        priority_counts[priority] = priority_counts.get(priority, 0) + 1

    result["priority_summary"] = {
        "total_suggestions": len(suggestions),
        "priority_1_must_have": priority_counts.get(1, 0),
        "priority_2_should_have": priority_counts.get(2, 0),
        "priority_3_nice_to_have": priority_counts.get(3, 0),
    }

    result["suggested_tests"] = suggestions[:20]
    return result


# ---------------------------------------------------------------- regressions and a skeleton to start from

def _slug(text, words=6):
    w = re.findall(r"[a-z0-9]+", re.sub(r"^\s*(fix(es|ed)?|bug|hotfix)\s*[:(]?\s*", "", text.lower()))
    return "_".join(x for x in w if x not in ("the", "a", "an", "in", "on", "of", "to", "and", "for"))[:60] or "bug"


def _regressions(file_path, root, days=365, limit=5):
    """One test idea per fix commit on this file in the last year: the bug it fixed, so it stays fixed."""
    from .explain5_engine import FIX_RX
    import datetime
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    cp = C.run(["git", "log", "--follow", "--since=%s" % since, "--format=%h%x02%ad%x02%s", "--date=short", "--",
                file_path], cwd=root, timeout=30)
    out = []
    for line in cp.stdout.splitlines() if cp.returncode == 0 else []:
        sha, date, subject = (line.split("\x02") + ["", ""])[:3]
        if FIX_RX.search(subject) and not re.match(r"^(merge|revert)\b", subject, re.I):
            out.append({"function": "", "priority": 1, "category": "regression", "sha": sha,
                        "test_name": "test_regression_%s" % _slug(subject),
                        "reason": "Fixed in %s (%s): %s. A test keeps it fixed." % (sha, date, subject[:120])})
            if len(out) >= limit:
                break
    return out


def _framework(result, root):
    """pytest, unittest, vitest or jest, from the existing tests that cover this file (else the usual default)."""
    lang = result.get("language")
    text = ""
    for t in result.get("related_tests") or []:
        text += C.read_text(os.path.join(root, t))[:20000]
    if lang == "python":
        return "pytest" if "import pytest" in text or ("unittest" not in text and "def test_" in text) else \
            "unittest" if "unittest" in text else "pytest"
    if lang in ("javascript", "typescript"):
        return "vitest" if "vitest" in text else "jest"
    return ""


def _import_line(result, root):
    """Reuse how an existing test imports this module, so the skeleton runs as-is in this repo."""
    base = os.path.splitext(os.path.basename(result["file"]))[0]
    for t in result.get("related_tests") or []:
        for line in C.read_text(os.path.join(root, t)).splitlines()[:80]:
            if re.match(r"^\s*(from\s+\S+\s+import|import)\b", line) and re.search(r"\b%s\b" % re.escape(base), line):
                return re.sub(r"\s+(#|//).*$", "", line.strip())
    if result.get("language") == "python":
        mod = os.path.splitext(result["file"])[0].replace("/", ".")
        return "from %s import *  # adjust to how your tests import this module" % mod
    return 'import * as mod from "./%s";  // adjust the path' % base


def skeleton(result, root, limit=12):
    """A test file to start from: one test per idea (regressions and edge cases first), each skipped until it is
    written, so it runs in CI without passing silently. "" for languages without a known test style."""
    fw = _framework(result, root)
    ideas = [t for t in result.get("suggested_tests") or [] if t.get("priority") in (1, 2)][:limit]
    if not fw or not ideas:
        return ""
    imp = _import_line(result, root)
    base = os.path.splitext(os.path.basename(result["file"]))[0]
    m = re.search(r"\bimport\s+(?:\*\s+as\s+(\w+)|%s(?:\s+as\s+(\w+))?)\s*;?\s*(#.*|//.*)?$" % re.escape(base), imp)
    prefix = (m.group(1) or m.group(2) or base) + "." if m else ""
    name = re.sub(r"\W", "", os.path.splitext(os.path.basename(result["file"]))[0].title()) or "Module"
    if fw in ("pytest", "unittest"):
        lines = (["import unittest", ""] if fw == "unittest" else ["import pytest", ""]) + [imp, "", ""]
        if fw == "unittest":
            lines.append("class Test%s(unittest.TestCase):" % name)
        for t in ideas:
            ind = "    " if fw == "unittest" else ""
            call = "%s%s(...)" % (prefix, t["function"]) if t.get("function") else "..."
            lines += [ind + ("@unittest.skip(\"not written yet\")" if fw == "unittest" else
                             "@pytest.mark.skip(reason=\"not written yet\")"),
                      ind + "def %s(%s):" % (t["test_name"], "self" if fw == "unittest" else ""),
                      ind + "    # " + t["reason"],
                      ind + "    result = %s" % call,
                      ind + ("    self.assertEqual(result, ...)" if fw == "unittest" else "    assert result == ..."),
                      ""]
        return "\n".join(lines).rstrip() + "\n"
    head = ['import { describe, it } from "vitest";'] if fw == "vitest" else []
    lines = head + [imp, "", 'describe("%s", () => {' % result["file"]]
    for t in ideas:
        lines.append('  it.todo("%s");  // %s' % (t["test_name"].replace("test_", "", 1).replace("_", " "),
                                                   t["reason"].replace("\n", " ")))
    return "\n".join(lines + ["});"]) + "\n"
