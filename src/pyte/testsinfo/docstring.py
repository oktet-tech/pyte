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

#: A list item opening a line.  Only these two markers count: a
#: description is prose, and a line starting with a digit or a word is
#: overwhelmingly a wrapped sentence, not an enumerated value.
_MARKER = re.compile(r"[-*](?:\s|$)")


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
    """One entry's description, filled: logical lines, not source ones.

    A docstring wraps at whatever column the source file's style rule
    says, here 72.  That wrap is a formatting artifact of this
    repository and nothing downstream wants it: rgt carries the
    description into the log and the viewer wraps it at its own width,
    so shipping our column count would bake our source style into every
    reader's display.  The C side does not do it either -- adjacent
    string literals inside TEST_PARAM_DOC exist precisely so a long
    logical line can be wrapped in source without becoming several
    output lines.

    So consecutive non-blank lines join with a single space.  What
    survives as a line break is what the author meant as one: a blank
    line stays a paragraph break, and a list item starts a line of its
    own, absorbing its own wrapped continuations.

    The block then loses its docstring indent.  List items keep their
    indent relative to the shallowest item, so a list nested inside a
    list still reads as nested; everything else is flush left.
    """
    # [indent, is_item, parts, preceded by a blank line]
    chunks: list[tuple[int, bool, list[str], bool]] = []
    blank = False
    for line in lines:
        text = line.strip()
        if not text:
            # Only between chunks: leading and trailing blanks go.
            blank = bool(chunks)
            continue
        indent = len(line) - len(line.lstrip())
        item = _MARKER.match(text) is not None
        if item or blank or not chunks:
            chunks.append((indent, item, [text], blank))
            blank = False
        else:
            chunks[-1][2].append(text)
    if not chunks:
        return ""
    items = [indent for indent, item, _, _ in chunks if item]
    cut = min(items) if items else 0
    out: list[str] = []
    for indent, item, parts, lead in chunks:
        if lead:
            out.append("")
        pad = " " * max(0, indent - cut) if item else ""
        out.append(pad + " ".join(parts))
    return "\n".join(out)


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
