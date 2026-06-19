# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the pyte.cfg CM-driven generator core.

Pure Python: inline CM YAML snippets in, data/text out.  No CM files,
no shim, no testbed.
"""
from pyte.cfg import _gen

_SAMPLE = """
- comment: |
    ignored comment block
- register:
    - oid: "/agent/interface"
      access: read_create
      type: none
      name: ifname
      d: |
         Network interface.
         Name: interface name
    - oid: "/agent/interface/mtu"
      access: read_write
      type: int32
      d: |
         Maximum transmission unit.
         Name: empty
         Value: the MTU in bytes
    - oid: "/agent/interface/phy"
      access: read_only
      type: none
      d: |
         PHY properties.
"""


def test_parse_collects_register_entries_only():
    entries = _gen.parse_cm(_SAMPLE)
    assert [e.oid for e in entries] == [
        "/agent/interface", "/agent/interface/mtu", "/agent/interface/phy"]


def test_parse_reads_type_and_access():
    e = {x.oid: x for x in _gen.parse_cm(_SAMPLE)}
    assert e["/agent/interface/mtu"].type == "int32"
    assert e["/agent/interface/mtu"].access == "read_write"


def test_parse_name_defaults_to_none_when_absent():
    e = {x.oid: x for x in _gen.parse_cm(_SAMPLE)}
    assert e["/agent/interface/mtu"].name == "none"   # no name: key
    assert e["/agent/interface"].name == "ifname"     # explicit


def test_parse_doc_strips_structural_trailer():
    e = {x.oid: x for x in _gen.parse_cm(_SAMPLE)}
    # Name:/Value: lines removed; only the human prose remains.
    assert e["/agent/interface/mtu"].doc == "Maximum transmission unit."
    assert e["/agent/interface"].doc == "Network interface."


# -- build_tree -------------------------------------------------------

def test_build_tree_nests_by_oid_segments():
    root = _gen.build_tree(_gen.parse_cm(_SAMPLE))
    iface = root.children["interface"]
    assert iface.oid == "/agent/interface"
    assert set(iface.children) == {"mtu", "phy"}
    assert iface.children["mtu"].entry.type == "int32"


def test_build_tree_root_is_agent():
    root = _gen.build_tree(_gen.parse_cm(_SAMPLE))
    assert root.seg == "agent"
    assert root.entry is None  # /agent itself is synthetic here


def test_is_leaf_vs_parent():
    root = _gen.build_tree(_gen.parse_cm(_SAMPLE))
    iface = root.children["interface"]
    assert not _gen.is_leaf(iface)            # has children
    assert _gen.is_leaf(iface.children["mtu"])  # no children
    assert _gen.is_leaf(iface.children["phy"])  # none-typed but no children here


def test_build_tree_is_order_independent():
    # A child entry arriving BEFORE its parent must still produce a tree
    # with the parent's own entry attached (CM cross-file merges do not
    # guarantee parent-before-child order).
    child_first = """
- register:
    - oid: "/agent/interface/mtu"
      access: read_write
      type: int32
      d: |
         Maximum transmission unit.
    - oid: "/agent/interface"
      access: read_create
      type: none
      name: ifname
      d: |
         Network interface.
"""
    root = _gen.build_tree(_gen.parse_cm(child_first))
    iface = root.children["interface"]
    assert iface.entry is not None and iface.entry.name == "ifname"
    assert iface.children["mtu"].entry.type == "int32"
