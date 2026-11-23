# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Every step_pop() call site in pyte says what finished."""
import ast
import pathlib

import pyte

SRC = pathlib.Path(pyte.__file__).parent


def _empty_pops(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(
            fn, "id", None)
        if name != "step_pop":
            continue
        args = list(node.args) + [k.value for k in node.keywords]
        if not args:
            yield node.lineno
        elif (isinstance(args[0], ast.Constant)
              and args[0].value in ("", None)):
            yield node.lineno


def test_no_empty_step_pop():
    bad = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), str(path))
        bad += [f"{path.relative_to(SRC)}:{n}" for n in _empty_pops(tree)]
    assert bad == [], "step_pop() without a text: " + ", ".join(bad)


def test_the_walk_sees_an_empty_pop():
    tree = ast.parse("log.step_pop()\nlog.step_pop('')\nlog.step_pop('x')")
    assert list(_empty_pops(tree)) == [1, 2]
