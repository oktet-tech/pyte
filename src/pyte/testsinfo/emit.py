# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""The tests-info.xml document.

The shape is TE's own (``te/scripts/scenario/tests_info.py``), because
the Tester parses both with the same code: two-space indent for
``<test>``, four for its children, six for a ``<step>``.

Everything is element text or an attribute value, never CDATA: the
Tester requires ``<objective>`` -- and equally ``<param>`` -- to have
exactly one text-node child, and a CDATA section is not one.  Escaping
goes through ``xml.sax.saxutils`` rather than hand-rolled replaces, so
a description holding a quote, an ampersand or an angle bracket comes
back out of the log the way it went in.
"""
from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr


def render_test(name: str, objective: str,
                params: list[tuple[str, str]],
                steps: list[tuple[int, str]]) -> str:
    """The ``<test>`` block for one test module.

    Args:
        name: The test name, as the package refers to it.
        objective: The one-line objective.
        params: The (name, description) documentation entries.
        steps: The (depth, text) scenario steps, in order.

    Returns:
        The block, newline-terminated.
    """
    out = [f"  <test name={quoteattr(name)}>"]
    out.append(f"    <objective>{escape(objective)}</objective>")
    for param, descr in params:
        out.append(f"    <param name={quoteattr(param)}>"
                   f"{escape(descr)}</param>")
    if steps:
        out.append("    <scenario>")
        out.extend(
            f'      <step depth="{depth}">{escape(text)}</step>'
            for depth, text in steps
        )
        out.append("    </scenario>")
    out.append("  </test>")
    return "\n".join(out) + "\n"


def render_document(blocks: list[str]) -> str:
    """The whole ``<tests-info>`` document around rendered blocks."""
    return ('<?xml version="1.0"?>\n<tests-info>\n'
            + "".join(blocks)
            + "</tests-info>\n")
