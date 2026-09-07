# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""The declared scenario, walked out of a test module's AST.

A Python test declares its scenario the way a C test does, with step
calls scattered through the code: ``t.step("...")``, and for a nested
group ``log.step_push("...")`` / ``log.step_pop()``.  Reading them in
source order gives a flat list; the nesting a reader expects comes from
the control flow the steps sit in, so a step guarded by an ``if`` is
shown one level under a heading naming the condition.

The heading phrasing mirrors TE's own C-side scenario extractor
(``te/scripts/scenario/steptree.py``), so a Python suite's scenario
reads exactly like a C suite's.

Not every construct is structure.  ``with`` is transparent: every pyte
test body is a ``with test.start() as t:`` block, and a heading for it
would push every step of every test to depth 2 under a line saying
nothing.  ``try``/``except``/``finally`` are transparent for the same
reason -- they are error handling, not scenario.  Function bodies are
walked in place, so a helper defined in the test module contributes its
steps where it is defined; no test does that today, but the steps would
otherwise vanish without a word.

A construct contributes a heading only when it actually contains a
step.  A run of pure setup code inside an ``if`` is not scenario.
"""
from __future__ import annotations

import ast
from typing import Iterator

#: Call attribute names that declare scenario, and what they do.
_KINDS = {"step": "step", "step_push": "push", "step_pop": "pop"}

#: Statements that group other statements without being scenario
#: structure of their own.  Their bodies are walked at the enclosing
#: depth.  ``ast.TryStar`` and ``ast.Match`` are looked up rather than
#: named so this keeps parsing on the oldest Python pyte supports.
_TRANSPARENT = tuple(
    node
    for node in (
        ast.With,
        ast.AsyncWith,
        ast.Try,
        getattr(ast, "TryStar", None),
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        getattr(ast, "Match", None),
    )
    if node is not None
)


def _kind(call: ast.Call) -> str | None:
    """'step', 'push', 'pop' for a scenario call, None otherwise.

    Matched on the attribute name alone, whatever the receiver: a test
    says ``t.step(...)`` and a library says ``log.step_push(...)``, and
    a suite is free to wrap either.
    """
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    return _KINDS.get(func.attr)


def _text(call: ast.Call) -> str | None:
    """A step call's text, or None when it is not a literal.

    A plain string constant is used verbatim.  An f-string keeps its
    literal parts and renders each hole as ``{expression}``, so the
    reader sees which value fills it.  Anything else -- a bare name, a
    call, a concatenation of non-constants -- has no text at build time
    and is a finding for the caller.
    """
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if not isinstance(arg, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in arg.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            parts.append("{" + ast.unparse(value.value) + "}")
        else:
            return None
    return "".join(parts)


def _calls(node: ast.AST) -> Iterator[ast.Call]:
    """Every call under a node, outermost first, in source order."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call):
            yield child
        yield from _calls(child)


def _child_statements(node: ast.AST) -> Iterator[ast.stmt]:
    """The statements a compound statement groups, in source order."""
    for _, value in ast.iter_fields(node):
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, ast.stmt):
                yield item
            elif isinstance(item, (ast.ExceptHandler,
                                   getattr(ast, "match_case", ()))):
                yield from item.body


def _has_step(body: list[ast.stmt]) -> bool:
    """Whether a statement list declares a step anywhere below it.

    A closing ``step_pop`` does not count: it opens nothing, so a
    construct holding only that is still not scenario structure.
    """
    for statement in body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and _kind(node) in ("step", "push"):
                return True
    return False


class _Walker:
    """One scenario extraction pass over a module."""

    def __init__(self) -> None:
        self.steps: list[tuple[int, str]] = []
        self.findings: list[str] = []
        # Open step groups.  step_push/step_pop pair up at run time,
        # not syntactically, so this is a running count rather than
        # part of the syntactic depth.
        self.pushed = 0

    def _emit(self, depth: int, text: str) -> None:
        self.steps.append((depth + self.pushed, text))

    def walk(self, body: list[ast.stmt], depth: int) -> None:
        """Emit the steps of a statement list at the given depth."""
        for statement in body:
            self._statement(statement, depth)

    def _statement(self, node: ast.stmt, depth: int) -> None:
        if isinstance(node, ast.If):
            self._branch(node, depth)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            target = ast.unparse(node.target)
            source = ast.unparse(node.iter)
            self._construct(node.body, depth,
                            f"For each {target} in {source}:")
            self.walk(node.orelse, depth)
        elif isinstance(node, ast.While):
            self._construct(node.body, depth,
                            f"While {ast.unparse(node.test)}:")
            self.walk(node.orelse, depth)
        elif isinstance(node, _TRANSPARENT):
            self.walk(list(_child_statements(node)), depth)
        else:
            self._leaf(node, depth)

    def _construct(self, body: list[ast.stmt], depth: int,
                   heading: str) -> None:
        """A construct's body: one level deeper, under its heading.

        A body with no step in it gets neither, so setup code inside a
        loop or a branch does not invent a scenario level.
        """
        if _has_step(body):
            self._emit(depth, heading)
            self.walk(body, depth + 1)
        else:
            self.walk(body, depth)

    def _branch(self, node: ast.If, depth: int) -> None:
        """An if/elif/else chain.

        An ``elif`` parses as a lone ``If`` inside ``orelse``, which
        would render as a level deeper than the branch it is an
        alternative to -- a five-branch chain becoming a five-level
        staircase.  It is rendered at the same depth instead.  A real
        ``else:`` holding a single ``if`` is not that, and is told apart
        by its column: an ``elif`` starts where its ``if`` does.
        """
        self._construct(node.body, depth, f"If {ast.unparse(node.test)}:")
        if not node.orelse:
            return
        inner = node.orelse[0]
        if (len(node.orelse) == 1 and isinstance(inner, ast.If)
                and inner.col_offset == node.col_offset):
            self._branch(inner, depth)
            return
        self._construct(node.orelse, depth,
                        f"If not {ast.unparse(node.test)}:")

    def _leaf(self, node: ast.stmt, depth: int) -> None:
        """A statement that groups nothing: its scenario calls."""
        for call in _calls(node):
            kind = _kind(call)
            if kind is None:
                continue
            if kind == "pop":
                self.pushed = max(0, self.pushed - 1)
                continue
            text = _text(call)
            if text is None:
                self.findings.append(
                    f"line {call.lineno}: step text is not a literal "
                    f"string")
                continue
            self._emit(depth, text)
            if kind == "push":
                self.pushed += 1


def scenario(tree: ast.Module) -> tuple[list[tuple[int, str]], list[str]]:
    """The declared scenario of a parsed test module.

    Args:
        tree: The module's AST.

    Returns:
        The (depth, text) steps in source order, depth starting at 1 as
        the C emitter's do, and the findings for steps whose text could
        not be read.
    """
    walker = _Walker()
    walker.walk(tree.body, 1)
    return walker.steps, walker.findings
