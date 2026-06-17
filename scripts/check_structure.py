#!/usr/bin/env python3
"""Structural code-quality checks not expressible in Ruff.

Mirrors the role of the JS project's scripts/check-arch.js. Enforces three rules
ported (and softened for data science) from an ESLint config:

  Rule 2  max function length      <= MAX_LINES physical lines
  Rule 3  max nesting depth        <= MAX_DEPTH nested blocks
  Rule 5  boolean expression size  no BoolOp with MAX_BOOL_OPERANDS+ operands,
                                    and no expression mixing `and` with `or`

Usage:
    python scripts/check_structure.py [path ...]

With no arguments it scans the `src/` directory for *.py files. Exits 1 if any
violation is found, 0 otherwise. Stdlib only, no dependencies.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MAX_LINES = 50
MAX_DEPTH = 3
MAX_BOOL_OPERANDS = 3

DEFAULT_TARGET = "src"

# Compound statements whose bodies introduce a deeper nesting level.
_LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)
_WITH_NODES = (ast.With, ast.AsyncWith)
_MATCH = getattr(ast, "Match", None)  # 3.10+


def _depth_of_body(body, depth):
    deepest = depth
    for stmt in body:
        deepest = max(deepest, _depth_of_stmt(stmt, depth))
    return deepest


def _depth_of_if(stmt, depth):
    # The if-body sits one level deeper.
    deepest = _depth_of_body(stmt.body, depth + 1)
    # An `elif` is `orelse == [If(...)]`; it is the SAME logical level, not deeper.
    if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
        return max(deepest, _depth_of_stmt(stmt.orelse[0], depth))
    return max(deepest, _depth_of_body(stmt.orelse, depth + 1))


def _depth_of_try(stmt, depth):
    deepest = depth
    for block in (stmt.body, stmt.orelse, stmt.finalbody):
        deepest = max(deepest, _depth_of_body(block, depth + 1))
    for handler in stmt.handlers:
        deepest = max(deepest, _depth_of_body(handler.body, depth + 1))
    return deepest


def _depth_of_match(stmt, depth):
    deepest = depth
    for case in stmt.cases:
        deepest = max(deepest, _depth_of_body(case.body, depth + 1))
    return deepest


def _depth_of_stmt(stmt, depth):
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
    # Nested def/class and simple statements do not add to this function's depth;
    # nested functions are analysed independently by the top-level walk.
    return depth


def _check_function(func, path, violations):
    length = func.end_lineno - func.lineno + 1
    if length > MAX_LINES:
        violations.append(
            f"{path}:{func.lineno}: function '{func.name}' is {length} lines "
            f"(max {MAX_LINES})"
        )
    depth = _depth_of_body(func.body, 0)
    if depth > MAX_DEPTH:
        violations.append(
            f"{path}:{func.lineno}: function '{func.name}' nests {depth} levels "
            f"deep (max {MAX_DEPTH})"
        )


def _check_boolop(node, path, violations):
    if len(node.values) >= MAX_BOOL_OPERANDS:
        violations.append(
            f"{path}:{node.lineno}: boolean expression with {len(node.values)} "
            f"operands (max {MAX_BOOL_OPERANDS - 1}); extract a named predicate"
        )
        return
    for value in node.values:
        if isinstance(value, ast.BoolOp) and type(value.op) is not type(node.op):
            violations.append(
                f"{path}:{node.lineno}: boolean expression mixes 'and' with 'or'; "
                f"extract a named predicate"
            )
            return


def _check_tree(tree, path, violations):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_function(node, path, violations)
        elif isinstance(node, ast.BoolOp):
            _check_boolop(node, path, violations)


def _check_file(path, violations):
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        violations.append(f"{path}:{exc.lineno}: syntax error: {exc.msg}")
        return
    _check_tree(tree, path, violations)


def _resolve_targets(args):
    if args:
        return [Path(a) for a in args]
    return [Path(DEFAULT_TARGET)]


def _iter_py_files(targets):
    for target in targets:
        if target.is_dir():
            yield from sorted(target.rglob("*.py"))
        elif target.suffix == ".py":
            yield target


def main(argv):
    targets = _resolve_targets(argv)
    violations = []
    for path in _iter_py_files(targets):
        _check_file(path, violations)
    for line in violations:
        print(line, file=sys.stderr)
    if violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
