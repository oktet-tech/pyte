# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Parameter documentation findings for a Python test module.

The four findings mirror TE's C-side checker
(``te/scripts/scenario/cparam.py``): a parameter with no doc entry, a
doc entry for no parameter, two entries for one name, and an entry with
nothing in it.  An empty entry still occupies its name -- it is
reported for being empty, not also for being undocumented, and a second
entry for the same name is still a duplicate of it.

What a parameter *is* differs from the C side, because a Python suite
has a second authority the C side lacks: the package.xml sitting beside
the script says what the Tester passes, while the source says only what
the test has got round to reading.  Both cross-checks run against the
union (see the packagexml module), so documentation that runs ahead of
the code is clean rather than stale, and a declared parameter nobody
documented is a finding rather than invisible.

What counts as a read is pyte's ``Params`` API and nothing else:
``p["name"]`` and the typed accessors ``get``/``int``/``float``/
``bool``/``enum``.  Unlike the C side, which can match any
``TEST_GET_*_PARAM`` spelling on the macro name alone, those method
names are ordinary English and the subscript is ordinary Python: taken
receiver-blind, ``os.environ.get("NAPTS_DURATION")`` and
``result["series"]`` would both be read as parameter reads and every
real test would report findings it has not earned.  So the receiver has
to be a ``Params``: a ``.params`` attribute, or a name assigned from
one (``p = t.params``, the spelling every suite uses).  Assignment
tracking is by name across the whole module, which is what lets a
helper function taking the same name -- ``_tunables(p, name)`` in
nap-ts -- have its reads counted too.
"""
from __future__ import annotations

import ast

#: The Params accessors, matched on the method name.
_METHODS = frozenset({"get", "int", "float", "bool", "enum"})

#: The attribute a Test exposes its parameters under.
_PARAMS = "params"

#: Never reported stale.  The env parameter is not read through Params
#: at all: it reaches the test as ``t.env``, built by the harness from
#: the Tester's own argument, exactly as the C side's env read hides
#: inside TEST_START.  Every test documents it and none of them reads
#: it, so without this exemption every test would report it stale.
_EXEMPT = frozenset({"env"})

#: Functions that read a parameter without naming it at the call site,
#: keyed by the called function's own name.
#:
#: nap-ts's ``ts.default_duration(t, "trex_int/throughput")`` reads the
#: ``duration`` parameter through the Configurator's per-test default;
#: the word "duration" appears nowhere in the call, so every test using
#: it would report its documented ``duration`` stale.  Add an entry
#: here when a suite grows another such helper: the key is the name the
#: call site uses (the attribute of ``ts.default_duration``, or a bare
#: function name), the value the parameters a call to it reads.  Keep
#: it short -- a helper that names its parameter needs no entry, and a
#: long table is a sign the reads should be visible at the call site
#: instead.
INDIRECT_READERS = {
    "default_duration": ("duration",),
}


def _string(node: ast.AST | None) -> str | None:
    """A string constant's value, or None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_params_attr(node: ast.AST) -> bool:
    """Whether an expression is a ``.params`` attribute access."""
    return isinstance(node, ast.Attribute) and node.attr == _PARAMS


def params_aliases(tree: ast.Module) -> set[str]:
    """Names bound to a test's parameters somewhere in the module."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_params_attr(node.value):
            targets = node.targets
        elif (isinstance(node, ast.AnnAssign) and node.value is not None
                and _is_params_attr(node.value)):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _is_params(node: ast.AST, aliases: set[str]) -> bool:
    """Whether an expression evaluates to a test's parameters."""
    if _is_params_attr(node):
        return True
    return isinstance(node, ast.Name) and node.id in aliases


def reads(tree: ast.Module) -> list[str]:
    """The parameter names a module reads, in source order.

    Args:
        tree: The module's AST.

    Returns:
        The names, deduplicated, first read first.
    """
    aliases = params_aliases(tree)
    found: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            name = _string(node.slice)
            if name is not None and _is_params(node.value, aliases):
                found.append((node.lineno, node.col_offset, name))
            continue
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = None
        if isinstance(func, ast.Attribute):
            called = func.attr
            name = _string(node.args[0]) if node.args else None
            if (called in _METHODS and name is not None
                    and _is_params(func.value, aliases)):
                found.append((node.lineno, node.col_offset, name))
        elif isinstance(func, ast.Name):
            called = func.id
        for name in INDIRECT_READERS.get(called, ()):
            found.append((node.lineno, node.col_offset, name))
    found.sort()
    return list(dict.fromkeys(name for _, _, name in found))


def check_params(tree: ast.Module, entries: list[tuple[str, str]],
                 declared: frozenset[str] = frozenset()) -> list[str]:
    """Parameter documentation findings for one test module.

    A parameter exists if either authority says so: the source reads
    it, or the package declares it.  Both cross-checks are against that
    union, which is what stops a documented-but-not-yet-read <arg> from
    being called stale (see packagexml) and what makes a declared
    parameter nobody documented a finding.

    Args:
        tree: The module's AST, for the reads.
        entries: The (name, description) documentation entries, in
            docstring order and with duplicates kept.
        declared: The parameters package.xml declares for this script;
            empty when there is no package.xml to read, which reduces
            both checks to the C side's reads-only behaviour.

    Returns:
        The findings, undocumented parameters first and then one group
        per documented name, as the C checker orders them.
    """
    names = [name for name, _ in entries]
    empty = {name for name, descr in entries if not descr.strip()}
    read = reads(tree)
    seen = set(read) | set(declared)
    # Read ones first, in source order, then the merely declared.
    exists = list(read) + sorted(n for n in declared if n not in set(read))
    findings = [
        f"parameter {name} is undocumented"
        for name in exists if name not in names
    ]
    for name in dict.fromkeys(names):
        if name in empty:
            findings.append(f"empty documentation for parameter {name}")
        if names.count(name) > 1:
            findings.append(f"duplicate documentation for parameter {name}")
        if name not in seen and name not in _EXEMPT:
            findings.append(
                f"stale documentation for parameter {name} (no such read)")
    return findings
