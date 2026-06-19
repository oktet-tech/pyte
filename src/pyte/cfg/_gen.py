# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""CM-driven generator core for the pyte.cfg knob engine.

Pure functions: parse TE's Configurator-model YAML into an object tree,
classify each node, and emit a Python module of engine shapes
(CfgObject + typed knobs + SubObject + Collection).  No filesystem, shim
or testbed access here; wiring to real CM files lives in Phase 2b-ii.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Entry:
    """One CM register entry."""

    oid: str
    type: str
    access: str
    name: str   # "none" (default/singleton) | "composite" | <ident>
    doc: str    # human prose from d:, structural trailer stripped


def _strip_doc(d: str) -> str:
    """Return the human prose of a d: block.

    Drops the trailing structural paragraphs (lines from the first
    ``Name:`` or ``Value:`` label onward) and collapses surrounding
    whitespace.
    """
    if not d:
        return ""
    out = []
    for line in d.splitlines():
        if re.match(r"\s*(Name|Value)\s*:", line):
            break
        out.append(line.rstrip())
    return "\n".join(out).strip()


def parse_cm(text: str) -> list[Entry]:
    """Parse CM YAML text into a flat list of register Entry objects."""
    import yaml

    entries: list[Entry] = []
    for doc in yaml.safe_load_all(text):
        if not isinstance(doc, list):
            continue
        for block in doc:
            if not isinstance(block, dict) or "register" not in block:
                continue
            for raw in block["register"]:
                entries.append(Entry(
                    oid=raw["oid"],
                    type=raw.get("type", "none"),
                    access=raw.get("access", "read_only"),
                    name=str(raw.get("name", "none")),
                    doc=_strip_doc(raw.get("d", "")),
                ))
    return entries
