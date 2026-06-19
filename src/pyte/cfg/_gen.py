# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""CM-driven generator for the pyte.cfg knob engine.

Pure functions parse TE's Configurator-model YAML into an object tree,
classify each node, and emit a Python module of engine shapes (CfgObject
+ typed knobs + SubObject + Collection).  ``cm_dir()``/``generate()``/
``main()`` read the real CM source (te/doc/cm) and write the checked-in
modules under ``pyte/cfg/gen/``; everything else is filesystem/shim/
testbed-free and unit-tested on inline YAML.
"""
from __future__ import annotations

import keyword
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Entry:
    """One CM register entry."""

    oid: str
    type: str
    access: str
    name: str       # "none" (default/singleton) | "composite" | <ident>
    doc: str        # human prose from d:, structural trailer stripped
    raw_name: str = ""  # text after "Name:" in d: block; "" if not kept
    volatile: bool = False  # True when the CM entry carries volatile: true


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


def _name_prose(d: str) -> str:
    """The text after the first 'Name:' label in a d: block ("" if none)."""
    for line in d.splitlines():
        m = re.match(r"\s*Name\s*:\s*(.*)", line)
        if m:
            return m.group(1).strip()
    return ""


def _make_entry(raw: dict, keep_raw: bool) -> Entry:
    """Build an Entry from a raw CM register dict.

    When *keep_raw* is True the ``raw_name`` field is populated from the
    ``d:`` block's first ``Name:`` label (used by ``parse_cm_raw``).
    """
    d = raw.get("d", "")
    return Entry(
        oid=raw["oid"],
        type=raw.get("type", "none"),
        access=raw.get("access", "read_only"),
        name=str(raw.get("name", "none")),
        doc=_strip_doc(d),
        raw_name=_name_prose(d) if keep_raw else "",
        volatile=bool(raw.get("volatile", False)),
    )


def _parse(text: str, keep_raw: bool) -> list[Entry]:
    """Shared parser loop; *keep_raw* controls ``raw_name`` population."""
    import yaml

    entries: list[Entry] = []
    for doc in yaml.safe_load_all(text):
        if not isinstance(doc, list):
            continue
        for block in doc:
            if not isinstance(block, dict) or "register" not in block:
                continue
            for raw in block["register"]:
                entries.append(_make_entry(raw, keep_raw))
    return entries


def parse_cm(text: str) -> list[Entry]:
    """Parse CM YAML text into a flat list of register Entry objects.

    The ``raw_name`` field of each Entry is left empty; use
    ``parse_cm_raw`` when the lint check for defaulted collections is
    needed.
    """
    return _parse(text, keep_raw=False)


def parse_cm_raw(text: str) -> list[Entry]:
    """Like ``parse_cm`` but also populates ``Entry.raw_name``.

    ``raw_name`` holds the prose after the first ``Name:`` label in the
    ``d:`` block.  Required for the ``lint`` collection-probe check.
    """
    return _parse(text, keep_raw=True)


_NAME_RE = re.compile(
    r"^(none|composite|[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)*)$")
_SINGLETON_NAMEPROSE = {"", "empty", "none"}


def lint(entries: list[Entry]) -> list[str]:
    """Return human-readable warnings about unreliable/ambiguous CM."""
    warns: list[str] = []
    for e in entries:
        if not _NAME_RE.match(e.name):
            warns.append(f"{e.oid}: invalid name {e.name!r}")
        if e.type == "integer":
            warns.append(
                f"{e.oid}: type 'integer' typo -> normalised INT32")
        if e.name == "none" and e.raw_name and \
                e.raw_name.lower() not in _SINGLETON_NAMEPROSE:
            warns.append(
                f"{e.oid}: name defaulted to none but d: Name "
                f"{e.raw_name!r} looks like a collection key")
    return warns


@dataclass
class Node:
    """A node in the Configurator object tree."""

    seg: str                       # last OID segment, e.g. "mtu"
    oid: str                       # full object OID, e.g. "/agent/interface/mtu"
    entry: Entry | None = None     # None for synthetic interior nodes
    children: dict[str, Node] = field(default_factory=dict)
    parent: Node | None = None     # tree parent (None for the root)


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
                node.children[seg] = Node(seg=seg, oid=path, parent=node)
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
    # Split on any non-alphanumeric (OID segments may contain '-'), then
    # CamelCase, so e.g. "file-max" -> "FileMax".
    return re.sub(r"[^0-9a-zA-Z]+", " ", seg).title().replace(" ", "")


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
    """A valid Python attribute name for an OID segment.

    The raw segment stays the OID subid; only the Python attribute name
    is sanitized: non-identifier chars (e.g. '-') become '_', a leading
    digit is prefixed with '_', and a Python keyword gets a trailing '_'
    (so e.g. "file-max" -> "file_max", "global" -> "global_").
    """
    a = re.sub(r"\W", "_", seg)
    if a[:1].isdigit():
        a = "_" + a
    if keyword.iskeyword(a):
        a += "_"
    return a


_HEADER = '''# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
# DO NOT EDIT - generated from TE CM YAML by pyte.cfg._gen.
"""{title}"""
{imports}'''

# Engine names the emitter may reference; imported only when actually used
# (an unconditional import would trip ruff F401 on the generated module).
_ENGINE_NAMES = ("AddrKnob", "BoolKnob", "CfgObject", "Collection",
                 "DoubleKnob", "IntKnob", "IpAddrKnob", "SelfKnob",
                 "StrKnob", "SubObject")


def _imports_for(used: set[str]) -> str:
    """Render `from pyte.cfg import (...)` for the engine names used.

    `used` is collected deterministically while emitting (not by scanning
    the rendered text), so docstring prose containing an engine word
    cannot introduce a spurious -> unused (ruff F401) import.
    """
    names = [n for n in _ENGINE_NAMES if n in used]
    inner = "\n".join(f"    {n}," for n in names)
    return f"from pyte.cfg import (\n{inner}\n)\n"


def _esc_doc(text: str) -> str:
    """Escape triple quotes so doc text cannot break a generated docstring."""
    return text.replace('"""', r'\"\"\"')


def _docstring(node: Node, indent: str) -> list[str]:
    """Render a node's d: prose as a docstring, indented."""
    doc = _esc_doc(node.entry.doc) if node.entry else ""
    if not doc:
        return []
    lines = doc.splitlines()
    if len(lines) == 1:
        return [f'{indent}"""{lines[0]}"""']
    return [f'{indent}"""{lines[0]}',
            *[f"{indent}{ln}".rstrip() for ln in lines[1:]],
            f'{indent}"""']


def _knob_line(seg: str, node: Node) -> str:
    """Render one leaf-knob descriptor assignment line (wrapped if long)."""
    cm_type = node.entry.type
    cls = knob_class(cm_type)
    args = [f'"{seg}"']
    if cls == "IntKnob":
        args.append(f'cvt_name="{cvt_for(cm_type)}"')
    if node.entry.access == "read_only":
        args.append('access="read_only"')
    if node.entry.volatile:
        args.append("sync=True")
    attr = attr_name(seg)
    one = f'    {attr} = {cls}({", ".join(args)})'
    if len(one) <= 79:
        return one
    # Wrap: one arg per continuation line (guarantees <=79 for any real arg).
    inner = ",\n".join(f"        {a}" for a in args)
    return f"    {attr} = {cls}(\n{inner})"


def emit_module(root: Node, module_name: str) -> str:
    """Emit a Python module (source text) for the root subtree.

    The emitted root class gets a convenience __init__ taking ``ta`` plus
    the root's own collection key (when the root is a collection).
    """
    root_oid = root.oid
    title = _esc_doc(root.entry.doc.splitlines()[0]
                     if root.entry and root.entry.doc else module_name)

    params = ["ta"]
    oid_fmt = "/agent:{ta}"
    if classify(root) == "collection":
        key = root.entry.name if root.entry.name != "composite" else "name"
        params.append(key)
        oid_fmt += f"/{root.seg}:{{{key}}}"
    else:
        oid_fmt += f"/{root.seg}:"

    blocks: list[str] = []
    used: set[str] = {"CfgObject"}   # every emitted class subclasses it
    _emit_class(root, root_oid, params, oid_fmt, blocks, used)
    header = _HEADER.format(title=title, imports=_imports_for(used))
    # Two blank lines before the first class and between classes (PEP 8 /
    # ruff E302) so the generated module is lint-clean.
    return header + "\n\n" + "\n\n\n".join(blocks) + "\n"


def _emit_class(node: Node, root_oid: str, root_params: list[str],
                root_oid_fmt: str, blocks: list[str],
                used: set[str]) -> None:
    """Append the class block for `node`; recurse into object children.

    Child object classes are appended BEFORE the parent's block so that
    SubObject/Collection references are already defined.  `used`
    accumulates the engine names actually emitted (for the import block).
    """
    cname = class_name(node.oid, root_oid)
    body: list[str] = [f"class {cname}(CfgObject):"]
    body.extend(_docstring(node, "    "))

    members: list[str] = []
    # Any node emitted as its own class (collection element or value-
    # bearing subobject) that carries a scalar value gets a self-value,
    # whether or not it also has children -- otherwise a childless
    # value-typed collection (e.g. a string macvlan keyed by name) would
    # lose its value.  Pure none-typed containers get none.
    if node.entry is not None and node.entry.type != "none":
        used.add("SelfKnob")
        sync = ", sync=True" if node.entry.volatile else ""
        members.append(
            f'    value = SelfKnob(cvt_name="{cvt_for(node.entry.type)}"'
            f'{sync})')
    for seg, child in node.children.items():
        kind = classify(child)
        if kind == "knob":
            used.add(knob_class(child.entry.type))
            members.append(_knob_line(seg, child))
        elif kind == "subobject":
            used.add("SubObject")
            members.append(
                f'    {attr_name(seg)} = SubObject('
                f'"{seg}", {class_name(child.oid, root_oid)})')
            _emit_class(child, root_oid, root_params, root_oid_fmt,
                        blocks, used)
        else:  # collection
            used.add("Collection")
            members.append(
                f'    {attr_name(seg)} = Collection('
                f'"{seg}", {class_name(child.oid, root_oid)})')
            _emit_class(child, root_oid, root_params, root_oid_fmt,
                        blocks, used)

    has_init = node.oid == root_oid
    if members:
        body.extend(members)
    elif not has_init:
        body.append("    pass")   # __init__ (if any) supplies the body

    if has_init:
        sig = ", ".join(root_params)
        body.append("")
        body.append(f"    def __init__(self, {sig}):")
        body.append(f'        super().__init__(f"{root_oid_fmt}")')

    blocks.append("\n".join(body))


@dataclass
class Target:
    """One generation target: a CM file, a root OID, an output module."""

    cm_file: str   # e.g. "cm_sys.yml"
    root_oid: str  # e.g. "/agent/sys"
    module: str    # e.g. "sys" -> gen/sys.py


TARGETS = [
    Target("cm_sys.yml", "/agent/sys", "sys"),
    Target("cm_base.yml", "/agent/interface", "interface"),
]


def cm_dir() -> Path:
    """Locate the TE CM SOURCE directory (te/doc/cm).

    Prefers $TE_BASE/doc/cm; falls back to the sibling ``te`` checkout in
    the workspace (``<repo>/../te/doc/cm``).  Raises FileNotFoundError if
    neither exists.
    """
    candidates = []
    base = os.environ.get("TE_BASE")
    if base:
        candidates.append(Path(base) / "doc" / "cm")
    repo = Path(__file__).resolve().parents[5]   # .../python-ts
    candidates.append(repo.parent / "te" / "doc" / "cm")
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError(
        f"TE CM source not found; tried {[str(c) for c in candidates]}")


def _root_node(entries: list[Entry], root_oid: str) -> Node:
    root = build_tree(entries)
    node = root
    for seg in [s for s in root_oid.split("/") if s][1:]:
        node = node.children[seg]
    return node


def generate_from(files: dict[str, str],
                  targets: list[Target]) -> dict[str, str]:
    """Emit modules from an in-memory {cm_file: yaml_text} map.

    Pure: no disk access, so unit-testable.  Returns {module: source}.
    """
    out: dict[str, str] = {}
    for t in targets:
        node = _root_node(parse_cm(files[t.cm_file]), t.root_oid)
        out[t.module] = emit_module(node, t.module)
    return out


def generate(targets: list[Target] | None = None) -> dict[str, str]:
    """Emit modules from the real CM source (see cm_dir())."""
    targets = targets or TARGETS
    cm = cm_dir()
    files = {t.cm_file: (cm / t.cm_file).read_text()
             for t in {x.cm_file: x for x in targets}.values()}
    return generate_from(files, targets)


def main() -> None:
    """Write the generated modules into pyte/cfg/gen/ (run by a dev)."""
    gen_dir = Path(__file__).resolve().parent / "gen"
    for module, src in generate().items():
        (gen_dir / f"{module}.py").write_text(src)
        print(f"wrote {gen_dir / f'{module}.py'}")


if __name__ == "__main__":
    main()
