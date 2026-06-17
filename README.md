# harness-python-code-rules

A small, installable tool that enforces an opinionated set of **structural code-quality
rules** for Python — ported from a stricter JavaScript/ESLint setup and deliberately relaxed
for data-science code (data pipelines, notebooks, exploratory work).

It enforces **only structural rules**. Formatting, import-sorting, and git/commit plumbing are
intentionally left to other tooling.

Two engines:
- **Ruff** for the rules it expresses natively (complexity, statement count, no-else-return).
- **A custom checker** (`harness-code-rules`) for the three rules Ruff can't express
  (function length, nesting depth, boolean-expression shape).

## The rules

| # | Origin (ESLint) | Rule here | Default | Enforced by |
|---|-----------------|-----------|---------|-------------|
| 1 | `complexity` | Cyclomatic complexity per function | **≤ 8** | Ruff `C901` |
| 2 | `max-lines-per-function` | Physical lines per function | **≤ 50** | `harness-code-rules` |
| 3 | `max-depth` | Nesting depth of blocks | **≤ 3** | `harness-code-rules` |
| 4 | `max-statements` | Statements per function | **≤ 15** | Ruff `PLR0915` |
| 5 | no `&&`/`\|\|`/`??` | Boolean expressions | no 3+ operands; no mixed `and`/`or` | `harness-code-rules` |
| 6 | no ternary | *dropped* — idiomatic in Python, clashes with Ruff `SIM108` | — | — |
| 7 | `no-else-return` | Redundant `else` after return/raise/continue/break | flagged | Ruff `RET505`–`RET508` |
| 8 | `prefer-const` / `no-var` | *dropped* — no Python equivalent | — | — |

Rule 5 stays out of pandas/numpy boolean indexing, which uses the **bitwise** `&`/`|`/`~`
operators — only the `and`/`or` keywords are inspected.

## Install

```bash
pip install git+https://github.com/kimzed/harness-python-code-rules.git
```

## Use

```bash
harness-code-rules                 # scans ./src
harness-code-rules path/to/pkg     # scan specific files or dirs
ruff check src/                    # the Ruff-native rules (config below)
```

The custom checker discovers config automatically; Ruff reads its own `[tool.ruff]` config.

## Configure

The custom checker resolves thresholds with precedence **CLI > `pyproject.toml` > defaults**.
Add a `[tool.harness-code-rules]` table to your project's `pyproject.toml`:

```toml
[tool.harness-code-rules]
max-lines = 60          # raise the function-length cap
max-depth = 3
max-bool-operands = false   # disable the boolean-expression check entirely
```

Any value set to `false` disables that check. Or override ad hoc on the command line:

```bash
harness-code-rules --max-lines 80 --max-depth 4 src/
```

For the Ruff side, copy the reference `[tool.ruff]` tables from this repo's `pyproject.toml`
into your project (Ruff does not inherit config from an installed package).

## Wire it into your project

### pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/kimzed/harness-python-code-rules
    rev: v0.1.0
    hooks:
      - id: harness-code-rules
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.0
    hooks:
      - id: ruff
```

### Claude Code PostToolUse hook

To have the checks run (and block) after Claude edits a file, add to your project's
`.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": "ruff check $CLAUDE_FILE_PATHS 1>&2 || exit 2" },
          { "type": "command", "command": "harness-code-rules $CLAUDE_FILE_PATHS 1>&2 || exit 2" }
        ]
      }
    ]
  }
}
```

Using `$CLAUDE_FILE_PATHS` checks only the file just edited, so hook latency stays constant
regardless of repo size (every rule here is per-file).

## Development

This repo dogfoods its own rules — `ruff check src/` and `harness-code-rules src/` both run
clean against the package source.
