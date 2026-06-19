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
