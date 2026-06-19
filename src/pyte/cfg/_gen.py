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
from dataclasses import dataclass, field


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


@dataclass
class Node:
    """A node in the Configurator object tree."""

    seg: str                       # last OID segment, e.g. "mtu"
    oid: str                       # full object OID, e.g. "/agent/interface/mtu"
    entry: Entry | None = None     # None for synthetic interior nodes
    children: dict[str, Node] = field(default_factory=dict)


def build_tree(entries: list[Entry]) -> Node:
    """Build the object tree from register entries.

    Returns the synthetic root (the first OID segment, normally
    ``agent``).  Interior OIDs missing from `entries` get synthetic
    nodes with ``entry is None``.
    """
    root: Node | None = None
    for e in entries:
        segs = [s for s in e.oid.split("/") if s]
        node = root
        path = ""
        for i, seg in enumerate(segs):
            path = f"{path}/{seg}"
            if i == 0:
                if root is None:
                    root = Node(seg=seg, oid=path)
                node = root
                continue
            if seg not in node.children:
                node.children[seg] = Node(seg=seg, oid=path)
            node = node.children[seg]
        if node is not None and node.oid == e.oid:
            node.entry = e
    assert root is not None, "no entries"
    return root


def is_leaf(node: Node) -> bool:
    """A node with no registered children is a leaf (a value knob)."""
    return not node.children


_CVT_BY_TYPE = {
    "int8": "INT8", "uint8": "UINT8", "int16": "INT16", "uint16": "UINT16",
    "int32": "INT32", "uint32": "UINT32", "int64": "INT64",
    "uint64": "UINT64", "bool": "BOOL", "double": "DOUBLE",
    "string": "STRING", "address": "ADDRESS",
    "integer": "INT32",   # known typo in cm_*.yml; normalise + lint elsewhere
}

_KNOB_CLASS = {
    "BOOL": "BoolKnob", "DOUBLE": "DoubleKnob", "STRING": "StrKnob",
    "ADDRESS": "AddrKnob",
    # all int widths use IntKnob with cvt_name=
}


def cvt_for(cm_type: str) -> str:
    """Map a CM type to its PYTE_CVT_* name."""
    return _CVT_BY_TYPE[cm_type]


def knob_class(cm_type: str) -> str:
    """The engine knob class for a CM type."""
    cvt = cvt_for(cm_type)
    return _KNOB_CLASS.get(cvt, "IntKnob")


def classify(node: Node) -> str:
    """Return 'knob', 'subobject', or 'collection' for a node.

    Uses the entry's name: value (absent ⇒ 'none' ⇒ singleton) and
    its type: a value-typed singleton leaf is a knob; a none-typed
    or multi-child node is a subobject; any named node is a collection.
    """
    name = node.entry.name if node.entry else "none"
    if name != "none":          # ident or 'composite'
        return "collection"
    cm_type = node.entry.type if node.entry else "none"
    if cm_type != "none" and is_leaf(node):
        return "knob"
    return "subobject"


def _pascal(seg: str) -> str:
    return seg.replace("_", " ").title().replace(" ", "")


def class_name(oid: str, root_oid: str) -> str:
    """PascalCase class name.

    The emitted root uses its own last segment; descendants use their
    path RELATIVE to the root (so names are unique within the module and
    a descendant is not prefixed with the root's name).
    """
    if oid == root_oid:
        return _pascal(root_oid.rstrip("/").split("/")[-1])
    tail = oid[len(root_oid):].strip("/")
    return "".join(_pascal(s) for s in tail.split("/"))


def attr_name(seg: str) -> str:
    """Child attribute name (the raw OID segment)."""
    return seg
