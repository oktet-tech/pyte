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
    raw_volatile: object = None  # the raw YAML volatile value (for lint)


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
    entry = Entry(
        oid=raw["oid"],
        type=raw.get("type", "none"),
        access=raw.get("access", "read_only"),
        name=str(raw.get("name", "none")),
        doc=_strip_doc(d),
        raw_name=_name_prose(d) if keep_raw else "",
        # strictly YAML true: cm_base.yml has templated string
        # values like ${TE_VOLATILE_ROUTES:-false} (truthy!).
        volatile=raw.get("volatile") is True,
    )
    entry.raw_volatile = raw.get("volatile")
    return entry


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
        if e.raw_volatile is not None and not isinstance(e.raw_volatile,
                                                         bool):
            warns.append(
                f"{e.oid}: volatile is {e.raw_volatile!r} (not a YAML "
                f"bool); treated as False")
        seg = e.oid.rstrip("/").split("/")[-1]
        if seg in _RESERVED_ATTRS:
            warns.append(
                f"{e.oid}: segment {seg!r} is a reserved engine name; "
                f"emitted as attribute {seg}_")
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
                elif root.seg != seg:
                    # Silently grafting a foreign-rooted entry under the
                    # first root corrupts the tree; refuse loudly.
                    raise ValueError(
                        f"entry {e.oid} is rooted at /{seg}, not "
                        f"/{root.seg}; one tree per root")
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


#: Names every generated class inherits or gets from the engine:
#: CfgObject.oid (instance attribute -- a knob descriptor named "oid"
#: even recurses infinitely: knob.__set__ -> _oid -> obj.oid -> knob),
#: CfgObject.name (the instance-key property), CfgObject.saved(), and
#: the SelfKnob emitted as "value".  A CM segment with one of these
#: names must not shadow the engine API (live case: the real CM leaf
#: /agent/interface/irq/name).
_RESERVED_ATTRS = frozenset({"oid", "name", "saved", "value"})


def attr_name(seg: str) -> str:
    """A valid Python attribute name for an OID segment.

    The raw segment stays the OID subid; only the Python attribute name
    is sanitized: non-identifier chars (e.g. '-') become '_', a leading
    digit is prefixed with '_', and a Python keyword or a reserved
    engine name gets a trailing '_' (so e.g. "file-max" -> "file_max",
    "global" -> "global_", "name" -> "name_").
    """
    a = re.sub(r"\W", "_", seg)
    if a[:1].isdigit():
        a = "_" + a
    if keyword.iskeyword(a) or a in _RESERVED_ATTRS:
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
    """Escape doc text so it cannot break out of a generated docstring.

    Backslashes are doubled (a trailing one would swallow the closing
    quotes), triple quotes are escaped, and a trailing single quote is
    escaped so it cannot fuse with the closing triple quote.
    """
    text = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    if text.endswith('"'):
        text = text[:-1] + '\\"'
    return text


def _blank_before_lists(lines: list[str]) -> list[str]:
    """Insert a blank line before a "- " bullet list that directly follows
    prose (CM ``d:`` blocks routinely do this; reST requires the blank
    line, or a wrapped bullet item breaks docutils' block-quote parsing).

    Only fires on the prose -> list transition, not between a list item
    and its own wrapped continuation (deeper-indented) or its next
    sibling item (same indent, also starting with "- ").
    """
    def indent(s: str) -> int:
        return len(s) - len(s.lstrip())

    out: list[str] = []
    for ln in lines:
        prev = out[-1] if out else ""
        if (ln.lstrip().startswith("- ") and prev.strip()
                and not prev.lstrip().startswith("- ")
                and indent(prev) <= indent(ln)):
            out.append("")
        out.append(ln)
    return out


def _docstring(node: Node, indent: str) -> list[str]:
    """Render a node's d: prose as a docstring, indented."""
    doc = _esc_doc(node.entry.doc) if node.entry else ""
    if not doc:
        return []
    lines = _blank_before_lists(doc.splitlines())
    if len(lines) == 1:
        return [f'{indent}"""{lines[0]}"""']
    return [f'{indent}"""{lines[0]}',
            *[f"{indent}{ln}".rstrip() for ln in lines[1:]],
            f'{indent}"""']


def _wrap_member(attr: str, cls: str, args: list[str]) -> str:
    """Render `attr = Cls(args...)`, wrapped to <=79 columns if needed.

    Used for ALL member kinds (knobs, SubObject, Collection): the
    per-kind emitters used to wrap only knob lines, so long
    SubObject/Collection lines exceeded 79 (live in the old pci.py).
    """
    one = f'    {attr} = {cls}({", ".join(args)})'
    if len(one) <= 79:
        return one
    inner = ",\n".join(f"        {a}" for a in args)
    return f"    {attr} = {cls}(\n{inner})"


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
    return _wrap_member(attr_name(seg), cls, args)


def _init_spec(root: Node) -> tuple[list[str], str]:
    """Derive (init params, base-OID f-string) from the root's path.

    Walks tree-root -> emitted root via parent links.  The universal TA
    root segment ``agent`` contributes ``ta`` (-> ``/agent:{ta}``); each
    other collection level contributes its key (``/{seg}:{key}``);
    singleton levels contribute ``/{seg}:``.

    Limitation: an ancestor missing from the parsed input has ``entry is
    None`` and is treated as a singleton; only ``agent`` is recognized
    without an entry.  So a deeper root's collection ancestors must be in
    the same parse input (the per-file targets satisfy this).
    """
    path: list[Node] = []
    node: Node | None = root
    while node is not None:
        path.append(node)
        node = node.parent
    path.reverse()

    params: list[str] = []
    parts: list[str] = []
    for n in path:
        if n.seg == "agent":
            params.append("ta")
            parts.append("/agent:{ta}")
        elif classify(n) == "collection":
            key = (n.entry.name
                   if n.entry and n.entry.name != "composite" else "name")
            params.append(key)
            parts.append(f"/{n.seg}:{{{key}}}")
        else:
            parts.append(f"/{n.seg}:")
    return params, "".join(parts)


def emit_module(root: Node, module_name: str,
                include: tuple[str, ...] | None = None) -> str:
    """Emit a Python module (source text) for the root subtree.

    The emitted root class gets a convenience __init__ taking ``ta`` plus
    the root's own collection key (when the root is a collection).  When
    ``include`` is given, the root class emits ONLY those named direct
    children (each by its normal classification, recursing into named
    subobjects/collections); otherwise all children are emitted.
    """
    root_oid = root.oid
    title = _esc_doc(root.entry.doc.splitlines()[0]
                     if root.entry and root.entry.doc else module_name)

    params, oid_fmt = _init_spec(root)

    blocks: list[str] = []
    used: set[str] = {"CfgObject"}   # every emitted class subclasses it
    cnames: dict[str, str] = {}      # class name -> defining OID
    _emit_class(root, root_oid, params, oid_fmt, blocks, used, cnames,
                include)
    header = _HEADER.format(title=title, imports=_imports_for(used))
    # Two blank lines before the first class and between classes (PEP 8 /
    # ruff E302) so the generated module is lint-clean.
    return header + "\n\n" + "\n\n\n".join(blocks) + "\n"


def _emit_class(node: Node, root_oid: str, root_params: list[str],
                root_oid_fmt: str, blocks: list[str],
                used: set[str], cnames: dict[str, str],
                include: tuple[str, ...] | None = None) -> None:
    """Append the class block for `node`; recurse into object children.

    Child object classes are appended BEFORE the parent's block so that
    SubObject/Collection references are already defined.  `used`
    accumulates the engine names actually emitted (for the import block);
    `cnames` maps emitted class names to their defining OID so a
    collision (e.g. /a/foo/bar vs /a/foo-bar, both FooBar) raises
    instead of the second class silently rebinding the first.
    `include`, honored only at this (root) call, restricts the emitted
    children to the named ones; recursive calls pass None so named
    subtrees emit in full.
    """
    cname = class_name(node.oid, root_oid)
    if cname in cnames:
        raise ValueError(
            f"class name collision: {node.oid} and {cnames[cname]} "
            f"both emit class {cname}")
    cnames[cname] = node.oid
    body: list[str] = [f"class {cname}(CfgObject):"]
    body.extend(_docstring(node, "    "))

    members: list[str] = []
    attrs: dict[str, str] = {}       # attribute name -> child segment
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
    if include is None:
        items = list(node.children.items())
    else:
        items = []
        for seg in include:
            child = node.children.get(seg)
            if child is None:
                raise ValueError(
                    f"include lists {seg!r}, not a child of {node.oid}")
            items.append((seg, child))
    for seg, child in items:
        attr = attr_name(seg)
        if attr in attrs:
            raise ValueError(
                f"attribute name collision under {node.oid}: segments "
                f"{attrs[attr]!r} and {seg!r} both map to {attr!r}")
        attrs[attr] = seg
        kind = classify(child)
        if kind == "knob":
            used.add(knob_class(child.entry.type))
            members.append(_knob_line(seg, child))
        elif kind == "subobject":
            used.add("SubObject")
            members.append(_wrap_member(
                attr, "SubObject",
                [f'"{seg}"', class_name(child.oid, root_oid)]))
            _emit_class(child, root_oid, root_params, root_oid_fmt,
                        blocks, used, cnames)
        else:  # collection
            used.add("Collection")
            args = [f'"{seg}"', class_name(child.oid, root_oid)]
            if child.entry is not None and \
                    child.entry.access == "read_only":
                args.append('access="read_only"')
            members.append(_wrap_member(attr, "Collection", args))
            _emit_class(child, root_oid, root_params, root_oid_fmt,
                        blocks, used, cnames)

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

    #: CM files to parse, in include order.  A subtree can be split
    #: across several: TE moved the interface IRQ nodes out of
    #: cm_base.yml into cm_if_irq.yml ("You need to include cm_base.yml
    #: first to use this"), and sourcing only the first file silently
    #: DELETES the missing nodes from the generated module.
    cm_files: tuple[str, ...]   # e.g. ("cm_sys.yml",)
    root_oid: str               # e.g. "/agent/sys"
    module: str    # e.g. "sys" -> gen/sys.py
    include: tuple[str, ...] | None = None  # root emits ONLY these
    #                                       # direct children (else all)
    #: OID -> instance-key parameter name, for CM entries whose ``name:``
    #: is missing although the runtime node is a collection.  The CM YAML
    #: is documentation-grade: e.g. /agent/sys/net/ipv4/conf carries no
    #: name: yet the agent lists instances keyed by interface
    #: (all/default/<ifname>, conf_sys_tree.c) -- without the override
    #: every knob under it would compose an OID that never exists.
    force_collection: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        # A bare string is iterable, so cm_files="cm_sys.yml" would walk
        # it character by character and fail far away with KeyError: 'c'.
        if isinstance(self.cm_files, str):
            raise TypeError(
                "Target.cm_files must be a tuple of file names, not the "
                f"bare string {self.cm_files!r} -- did you mean "
                f"({self.cm_files!r},)?")
        self.cm_files = tuple(self.cm_files)


# The /agent root mixes agent-wide scalars with large separate subtrees
# (interface, route, hardware, rsrc, ...) and several collection-leaves
# carrying a defaulted name: none.  An explicit allow-list emits exactly
# the intended members without touching cm_base's annotations.  uname is a
# value-bearing subobject (string value + version/release/machine).
AGENT_MEMBERS = (
    "platform", "dir", "tmp_dir", "lib_mod_dir", "lib_bin_dir",
    "ip4_fw", "ip6_fw", "ip4_rt_default_if", "ip6_rt_default_if",
    "rpcprovider", "rpc_default_timeout", "rp_filter_all", "uname",
)

TARGETS = [
    Target(("cm_sys.yml",), "/agent/sys", "sys",
           force_collection={
               "/agent/sys/net/ipv4/conf": "ifname",
               "/agent/sys/net/ipv4/neigh": "ifname",
               "/agent/sys/net/ipv6/conf": "ifname",
               "/agent/sys/net/ipv6/neigh": "ifname",
           }),
    Target(("cm_base.yml", "cm_if_irq.yml"), "/agent/interface",
           "interface"),
    Target(("cm_base.yml",), "/agent", "agent", include=AGENT_MEMBERS),
    Target(("cm_pci.yml",), "/agent/hardware/pci", "pci"),
    Target(("cm_module.yml",), "/agent/module", "module"),
]


def cm_dir() -> Path:
    """Locate the TE CM SOURCE directory (te/doc/cm).

    Prefers $TE_BASE/doc/cm; otherwise looks for a ``te`` checkout
    sibling to ANY ancestor of this file, which covers both known
    layouts without hardcoding either: the standalone pyte repo
    (``ws/pyte`` + ``ws/te``) and the suite submodule
    (``ws/python-ts/lib/pyte`` + ``ws/te``).  A fixed parents[N]
    index would silently pick the wrong root in the other layout —
    and a wrong root here silently disables the drift gate (the
    tests skip when the CM source is "absent").  Raises
    FileNotFoundError when nothing is found.
    """
    candidates = []
    base = os.environ.get("TE_BASE")
    if base:
        candidates.append(Path(base) / "doc" / "cm")
    candidates += [p / "te" / "doc" / "cm"
                   for p in Path(__file__).resolve().parents]
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
        entries = [e for f in t.cm_files for e in parse_cm(files[f])]
        for e in entries:
            key = t.force_collection.get(e.oid)
            if key:
                # Correct documentation-grade CM: treat the entry as a
                # collection keyed by *key* (see Target.force_collection).
                e.name = key
        node = _root_node(entries, t.root_oid)
        out[t.module] = emit_module(node, t.module, include=t.include)
    return out


def generate(targets: list[Target] | None = None) -> dict[str, str]:
    """Emit modules from the real CM source (see cm_dir())."""
    targets = targets or TARGETS
    cm = cm_dir()
    files = {f: (cm / f).read_text()
             for t in targets for f in t.cm_files}
    return generate_from(files, targets)


def main() -> None:
    """Write the generated modules into pyte/cfg/gen/ (run by a dev)."""
    gen_dir = Path(__file__).resolve().parent / "gen"
    for module, src in generate().items():
        (gen_dir / f"{module}.py").write_text(src)
        print(f"wrote {gen_dir / f'{module}.py'}")


if __name__ == "__main__":
    main()
