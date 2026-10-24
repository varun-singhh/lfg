---
name: suggest-tests
description: >
  Suggest tests you should write based on your code.
  Uses AST parsing to find functions and suggests tests based on code patterns.
  Use when writing new code or modifying existing code.
author: Varun Singh
phase: build
lanes: [standard, full]
reads: [git]
writes: []
auto-trigger: false
---

## Steps

1. **Run test suggester engine**:
   ```bash
   lfg suggest-tests <file> --json
   ```

   This engine is a heuristic first pass based on function signatures and code patterns. It is not a substitute for actual coverage analysis.

2. **Review and present suggestions**:
   - `functions`: public functions/classes found (private ones skipped unless that's all there is)
   - `suggested_tests`: each has `test_name`, `priority` (1-3), `category`, `reason` (e.g., "Found 'return None' in function")
   - `related_tests`: existing test files that import or match the module name
   - `priority_summary`: counts by priority

3. **No coverage estimate**: There is no "coverage improvement estimate" key or line - we can't measure coverage from static analysis alone.

## Output

- List of functions and classes found
- Suggested tests with priority and concrete reason (e.g., "returns None when fetch fails" from `return None` in code)
- Related existing test files (so the user knows where to add)
- Priority summary: must have, should have, nice to have

## Rules

- Skip private (leading `_`) functions/classes unless they're the only ones.
- Test names should hint at the branch/edge: `test_<func>_returns_none_when_appropriate` not just `test_<func>_valid_input`.
- Reasons come from the code: `return None`, `raise X`, `if not x`, comparisons, loops.
- Drop the "coverage improvement estimate" entirely - we can't measure it.
- **Important**: This is a heuristic engine. Verify each suggestion makes sense for the code before recommending it.
