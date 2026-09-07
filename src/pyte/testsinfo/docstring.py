# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Objective and parameter entries out of a module docstring.

A Python test module documents itself the way the C tests document
themselves with a doxygen header: a one-paragraph objective, then a
Google-style parameter section.  This module turns the cleaned
(``ast.get_docstring(..., clean=True)``) text into the two pieces the
tests-info document needs, and reports the lines it could not place.

Nothing here imports anything but the standard library: it runs during
a suite build, under whatever ``python3`` is on the build host.
"""
from __future__ import annotations

import re

#: Section headings that introduce parameter entries.  All four
#: spellings are accepted on purpose: nap-ts test modules say
#: "Parameters:", ts/prologue.py says "Parameter:", and Google style
#: itself says "Args:" or "Arguments:".  The heading must sit at
#: column 0 of the cleaned docstring and carry nothing else.
_HEADING = re.compile(r"(?:Parameters|Parameter|Args|Arguments):")

#: An entry line inside a section: an identifier, a colon, then the
#: first (or only) line of the description.
_ENTRY = re.compile(r"(\w+):\s*(.*)")


def _is_heading(line: str) -> bool:
    """Whether a docstring line opens a parameter section."""
    return _HEADING.fullmatch(line.rstrip()) is not None


def objective(doc: str) -> str:
    """The objective: the docstring's first paragraph, on one line.

    The paragraph ends at the first blank line, as it always has, and
    also at a parameter section heading: ts/prologue.py's ``Parameter:``
    heading is not always preceded by a blank line, and a docstring that
    starts straight into its parameters would otherwise put the whole
    section into the objective.

    Args:
        doc: The cleaned module docstring.

    Returns:
        The objective text, or '' when the docstring opens with a blank
        line or a section heading.
    """
    out: list[str] = []
    for line in doc.splitlines():
        if not line.strip() or _is_heading(line):
            break
        out.append(line.strip())
    return " ".join(out).strip()


def _describe(lines: list[str]) -> str:
    """One entry's description text, dedented, blank edges trimmed.

    The line structure is kept: a value list written as bullets in the
    docstring must reach the log as bullets, so the lines stay lines and
    keep their indentation relative to the description's own first line.
    """
    out = list(lines)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    if not out:
        return ""
    cut = min(len(l) - len(l.lstrip()) for l in out if l.strip())
    return "\n".join(l[cut:] if l.strip() else "" for l in out)


def parameters(doc: str) -> tuple[list[tuple[str, str]], list[str]]:
    """The documented parameters of a test module.

    An entry starts at the section's base indent (the indent of its
    first non-blank line) with ``name:``; every more deeply indented
    line belongs to the entry above it.  The section ends at the next
    non-blank line at column 0, or at the end of the docstring.

    Args:
        doc: The cleaned module docstring.

    Returns:
        The (name, description) entries in docstring order, and the
        findings for lines inside a section that are neither an entry
        nor a continuation of one.  Duplicates are kept, for the
        checker to report.
    """
    lines = doc.splitlines()
    entries: list[tuple[str, str]] = []
    findings: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        if not _is_heading(lines[i]):
            i += 1
            continue
        heading = lines[i].rstrip()[:-1]
        i += 1
        base: int | None = None
        name: str | None = None
        descr: list[str] = []
        while i < n:
            line = lines[i].rstrip()
            i += 1
            if not line:
                if name is not None:
                    descr.append("")
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                i -= 1
                break
            if base is None:
                base = indent
            if indent > base and name is not None:
                descr.append(line[base:])
                continue
            match = _ENTRY.fullmatch(line[base:]) if indent == base else None
            if match is None:
                findings.append(
                    f"malformed line in {heading} section: {line.strip()}")
                continue
            if name is not None:
                entries.append((name, _describe(descr)))
            name, descr = match.group(1), [match.group(2)]
        if name is not None:
            entries.append((name, _describe(descr)))
    return entries, findings
