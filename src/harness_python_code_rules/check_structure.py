#!/usr/bin/env python3
"""Structural code-quality checks not expressible in Ruff.

Enforces three rules (ported and softened for data science from a stricter
ESLint config):

  max-lines          function length, in physical lines
  max-depth          maximum nesting depth of blocks
  max-bool-operands  flag a boolean expression with this many operands or more,
                     and any expression mixing `and` with `or`

Thresholds are resolved with precedence CLI > pyproject.toml > defaults. In a
project's pyproject.toml:

    [tool.harness-code-rules]
    max-lines = 50
    max-depth = 3
    max-bool-operands = 3      # set any value to `false` to disable that check

Usage:
    harness-code-rules [paths ...] [--max-lines N] [--max-depth N]
                       [--max-bool-operands N] [--config pyproject.toml]

With no paths it scans `src/`. Exits 1 if any violation is found, else 0.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

# A threshold is an int limit, or False to disable that check.
Setting = int | bool
Settings = dict[str, Setting]
FunctionDef = ast.FunctionDef | ast.AsyncFunctionDef

CONFIG_TABLE: str = "harness-code-rules"
DEFAULTS: Settings = {"max-lines": 50, "max-depth": 3, "max-bool-operands": 3}
DEFAULT_TARGET: str = "src"

# Compound statements whose bodies introduce a deeper nesting level.
_LOOP_NODES: tuple[type[ast.AST], ...] = (ast.For, ast.AsyncFor, ast.While)
_WITH_NODES: tuple[type[ast.AST], ...] = (ast.With, ast.AsyncWith)
_MATCH: type[ast.AST] | None = getattr(ast, "Match", None)  # 3.10+


# --- nesting depth ---------------------------------------------------------


def _depth_of_body(body: list[ast.stmt], depth: int) -> int:
    deepest = depth
    for stmt in body:
        deepest = max(deepest, _depth_of_stmt(stmt, depth))
    return deepest


def _depth_of_if(stmt: ast.If, depth: int) -> int:
    deepest = _depth_of_body(stmt.body, depth + 1)
    # An `elif` is `orelse == [If(...)]`; it is the SAME logical level, not deeper.
    if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
        return max(deepest, _depth_of_stmt(stmt.orelse[0], depth))
    return max(deepest, _depth_of_body(stmt.orelse, depth + 1))


def _depth_of_try(stmt: ast.Try, depth: int) -> int:
    deepest = depth
    for block in (stmt.body, stmt.orelse, stmt.finalbody):
        deepest = max(deepest, _depth_of_body(block, depth + 1))
    for handler in stmt.handlers:
        deepest = max(deepest, _depth_of_body(handler.body, depth + 1))
    return deepest


def _depth_of_match(stmt: ast.Match, depth: int) -> int:
    deepest = depth
    for case in stmt.cases:
        deepest = max(deepest, _depth_of_body(case.body, depth + 1))
    return deepest


def _depth_of_stmt(stmt: ast.stmt, depth: int) -> int:
    if isinstance(stmt, ast.If):
        return _depth_of_if(stmt, depth)
    if isinstance(stmt, _LOOP_NODES):
        return max(
            _depth_of_body(stmt.body, depth + 1),
            _depth_of_body(stmt.orelse, depth + 1),
        )
    if isinstance(stmt, _WITH_NODES):
        return _depth_of_body(stmt.body, depth + 1)
    if isinstance(stmt, ast.Try):
        return _depth_of_try(stmt, depth)
    if _MATCH is not None and isinstance(stmt, _MATCH):
        return _depth_of_match(stmt, depth)
    return depth


# --- individual checks -----------------------------------------------------


def _check_length(
    func: FunctionDef, limit: Setting, path: Path, violations: list[str]
) -> None:
    if limit is False:
        return
    length = func.end_lineno - func.lineno + 1
    if length > limit:
        violations.append(
            f"{path}:{func.lineno}: function '{func.name}' is {length} lines "
            f"(max {limit})"
        )


def _check_nesting(
    func: FunctionDef, limit: Setting, path: Path, violations: list[str]
) -> None:
    if limit is False:
        return
    depth = _depth_of_body(func.body, 0)
    if depth > limit:
        violations.append(
            f"{path}:{func.lineno}: function '{func.name}' nests {depth} levels "
            f"deep (max {limit})"
        )


def _is_mixed_boolop(node: ast.BoolOp) -> bool:
    for value in node.values:
        if isinstance(value, ast.BoolOp) and type(value.op) is not type(node.op):
            return True
    return False


def _check_boolop(
    node: ast.BoolOp, limit: Setting, path: Path, violations: list[str]
) -> None:
    if limit is False:
        return
    if len(node.values) >= limit:
        violations.append(
            f"{path}:{node.lineno}: boolean expression with {len(node.values)} "
            f"operands (max {limit - 1}); extract a named predicate"
        )
        return
    if _is_mixed_boolop(node):
        violations.append(
            f"{path}:{node.lineno}: boolean expression mixes 'and' with 'or'; "
            f"extract a named predicate"
        )


# --- traversal -------------------------------------------------------------


def _check_function(
    func: FunctionDef, settings: Settings, path: Path, violations: list[str]
) -> None:
    _check_length(func, settings["max-lines"], path, violations)
    _check_nesting(func, settings["max-depth"], path, violations)


def _check_tree(
    tree: ast.Module, settings: Settings, path: Path, violations: list[str]
) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_function(node, settings, path, violations)
        elif isinstance(node, ast.BoolOp):
            _check_boolop(node, settings["max-bool-operands"], path, violations)


def _check_file(path: Path, settings: Settings, violations: list[str]) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        violations.append(f"{path}:{exc.lineno}: syntax error: {exc.msg}")
        return
    _check_tree(tree, settings, path, violations)


def _iter_py_files(targets: list[Path]) -> Iterator[Path]:
    for target in targets:
        if target.is_dir():
            yield from sorted(target.rglob("*.py"))
        elif target.suffix == ".py":
            yield target


# --- configuration ---------------------------------------------------------


def _find_pyproject(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _load_table(config_path: Path | None) -> dict[str, object]:
    if config_path is None:
        return {}
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return data.get("tool", {}).get(CONFIG_TABLE, {})


def _resolve_settings(
    table: dict[str, object], overrides: dict[str, int | None]
) -> Settings:
    settings: Settings = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in table:
            settings[key] = table[key]  # type: ignore[assignment]
    for key, value in overrides.items():
        if value is not None:
            settings[key] = value
    return settings


# --- entry point -----------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="harness-code-rules")
    parser.add_argument("paths", nargs="*", help="files or directories (default: src)")
    parser.add_argument("--max-lines", type=int, help="override max lines per function")
    parser.add_argument("--max-depth", type=int, help="override max nesting depth")
    parser.add_argument(
        "--max-bool-operands", type=int, help="override max bool operands"
    )
    parser.add_argument("--config", type=Path, help="explicit pyproject.toml path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    config_path = args.config or _find_pyproject(Path.cwd())
    overrides: dict[str, int | None] = {
        "max-lines": args.max_lines,
        "max-depth": args.max_depth,
        "max-bool-operands": args.max_bool_operands,
    }
    settings = _resolve_settings(_load_table(config_path), overrides)
    targets = [Path(p) for p in args.paths] or [Path(DEFAULT_TARGET)]
    violations: list[str] = []
    for path in _iter_py_files(targets):
        _check_file(path, settings, violations)
    for line in violations:
        print(line, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
