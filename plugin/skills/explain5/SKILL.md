---
name: explain5
description: >
  Explain code in plain English like you're explaining to a 5-year-old.
  Use when the user asks "explain this", "what does this code do", or wants to understand complex code.
author: Varun Singh
phase: helper
lanes: [express, standard, full, hotfix]
reads: [git]
writes: []
auto-trigger: false
---

## Steps

1. **Identify target**: Extract file path from user request
   - If user provides file path, use it
   - If unclear, ask: "Which file would you like me to explain?"

2. **Run explain5 engine**:
   ```bash
   lfg explain5 <file> --json
   ```

   This engine is a heuristic first pass: it uses AST parsing and regex patterns to extract structure and find test files. Read the file yourself to understand it properly.

3. **Present the explanation**:
   - Start with "What it does" (summary from docstring/comments)
   - Explain the structure (all top-level functions and classes, up to 40)
   - Mention who touched it last and when (from git log)
   - List related tests (files under tests/, test/ etc. that import the module)
   - Note any potential issues found (TODOs, security patterns)

4. **Read the code yourself**: The engine gives you a map; read the actual file for details.

## Output

Plain English explanation with:
- Summary from docstring or first comment
- List of all top-level definitions with line numbers
- Who created it and when
- Related test files (or "None found")
- Potential issues if any

## Rules

- The engine lists every top-level function/class it finds (up to 40). That's a map, not the full story.
- Related tests: files under tests/, test/, __tests__/ or matching test patterns that mention the module. Use `git ls-files` (fast, respects .gitignore).
- Read the file yourself for details; the engine output is not a substitute.
- False positives are possible in "potential issues" - verify before reporting.
