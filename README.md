# harness-python-code-rules

A starting point for data-science projects that enforces an opinionated set of
**structural code-quality rules** — ported from a stricter JavaScript/ESLint setup and
deliberately relaxed for the realities of data-science code (data pipelines, notebooks,
exploratory work).

This repo enforces **only structural rules**. Formatting, import-sorting, and git/commit
plumbing are intentionally left to other tooling.

## The rules

| # | Origin (ESLint) | Rule here | Threshold | Enforced by |
|---|-----------------|-----------|-----------|-------------|
| 1 | `complexity` | Cyclomatic complexity per function | **≤ 8** | Ruff `C901` |
| 2 | `max-lines-per-function` | Physical lines per function | **≤ 50** | `scripts/check_structure.py` |
| 3 | `max-depth` | Nesting depth of blocks | **≤ 3** | `scripts/check_structure.py` |
| 4 | `max-statements` | Statements per function | **≤ 15** | Ruff `PLR0915` |
| 5 | no `&&`/`\|\|`/`??` | Boolean expressions | no 3+ operands; no mixed `and`/`or` | `scripts/check_structure.py` |
| 6 | no ternary | *dropped* — idiomatic in Python, clashes with Ruff `SIM108` | — | — |
| 7 | `no-else-return` | Redundant `else`/`elif` after return/raise/continue/break | flagged | Ruff `RET505`–`RET508` |
| 8 | `prefer-const` / `no-var` | *dropped* — no Python equivalent | — | — |

Rule 4 (≤15 statements) is the primary brake on function size; Rule 2 (≤50 lines) is a
backstop that mainly catches line-dense functions (chained calls, multi-line plot/kwargs).

Rule 5 stays out of pandas/numpy boolean indexing, which uses the **bitwise** `&`/`|`/`~`
operators — only the `and`/`or` keywords are inspected.

## Running the checks

```bash
ruff check src/                      # rules 1, 4, 7
python scripts/check_structure.py    # rules 2, 3, 5 (defaults to scanning src/)
```

Both are also wired into a Claude Code `PostToolUse` hook in `.claude/settings.json`, so they
run automatically after Claude edits a file and block on violations.

## Tuning

Ruff thresholds live in `pyproject.toml` (`max-complexity`, `max-statements`). The custom
checker's thresholds are named constants at the top of `scripts/check_structure.py`
(`MAX_LINES`, `MAX_DEPTH`, `MAX_BOOL_OPERANDS`).
