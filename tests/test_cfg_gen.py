# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the pyte.cfg CM-driven generator core.

Pure Python: inline CM YAML snippets in, data/text out.  No CM files,
no shim, no testbed.
"""
import pytest

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


# -- classify + cvt + naming ------------------------------------------

def test_cvt_for_maps_types():
    assert _gen.cvt_for("int32") == "INT32"
    assert _gen.cvt_for("uint64") == "UINT64"
    assert _gen.cvt_for("integer") == "INT32"   # known typo -> normalised
    assert _gen.cvt_for("bool") == "BOOL"
    assert _gen.cvt_for("address") == "ADDRESS"


def test_knob_class_for_type():
    assert _gen.knob_class("int32") == "IntKnob"
    assert _gen.knob_class("bool") == "BoolKnob"
    assert _gen.knob_class("double") == "DoubleKnob"
    assert _gen.knob_class("string") == "StrKnob"
    assert _gen.knob_class("address") == "AddrKnob"


def test_classify_leaf_singleton_is_knob():
    root = _gen.build_tree(_gen.parse_cm(_SAMPLE))
    mtu = root.children["interface"].children["mtu"]
    assert _gen.classify(mtu) == "knob"


def test_classify_singleton_parent_is_subobject():
    root = _gen.build_tree(_gen.parse_cm(_SAMPLE))
    phy = root.children["interface"].children["phy"]
    assert _gen.classify(phy) == "subobject"


def test_classify_named_parent_is_collection():
    root = _gen.build_tree(_gen.parse_cm(_SAMPLE))
    iface = root.children["interface"]      # name: ifname
    assert _gen.classify(iface) == "collection"


def test_classify_composite():
    entries = _gen.parse_cm('''
- register:
    - oid: "/agent/x"
      type: none
      access: read_only
      name: composite
      d: |
         X.
''')
    root = _gen.build_tree(entries)
    assert _gen.classify(root.children["x"]) == "collection"


def test_class_name_is_path_qualified_pascalcase():
    assert _gen.class_name("/agent/interface", "/agent/interface") == \
        "Interface"
    assert _gen.class_name("/agent/interface/channels/combined",
                           "/agent/interface") == "ChannelsCombined"


def test_attr_name_is_segment():
    assert _gen.attr_name("speed_admin") == "speed_admin"
    assert _gen.attr_name("net_addr") == "net_addr"


# -- emit_module ------------------------------------------------------

_IFACE_YAML = """
- register:
    - oid: "/agent/interface"
      access: read_create
      type: none
      name: ifname
      d: |
         Network interface.
    - oid: "/agent/interface/mtu"
      access: read_write
      type: int32
      d: |
         Maximum transmission unit.
    - oid: "/agent/interface/index"
      access: read_only
      type: int32
      d: |
         Interface index.
    - oid: "/agent/interface/phy"
      access: read_only
      type: none
      d: |
         PHY properties.
    - oid: "/agent/interface/phy/speed_admin"
      access: read_write
      type: int32
      d: |
         Administratively set speed.
    - oid: "/agent/interface/net_addr"
      access: read_create
      type: int32
      name: address
      d: |
         Network address of the interface.
"""


def _emit_iface():
    root = _gen.build_tree(_gen.parse_cm(_IFACE_YAML))
    return _gen.emit_module(root.children["interface"], "interface")


def test_emit_contains_root_class_with_init():
    src = _emit_iface()
    assert "class Interface(CfgObject):" in src
    assert "def __init__(self, ta, ifname):" in src
    assert 'super().__init__(f"/agent:{ta}/interface:{ifname}")' in src


def test_emit_leaf_knobs_with_cvt_and_access():
    src = _emit_iface()
    assert 'mtu = IntKnob("mtu", cvt_name="INT32")' in src
    assert ('index = IntKnob("index", cvt_name="INT32", '
            'access="read_only")' in src)


def test_emit_subobject_and_its_class():
    src = _emit_iface()
    assert 'phy = SubObject("phy", Phy)' in src
    assert "class Phy(CfgObject):" in src
    assert 'speed_admin = IntKnob("speed_admin", cvt_name="INT32")' in src


def test_emit_collection_child():
    src = _emit_iface()
    assert 'net_addr = Collection("net_addr", NetAddr)' in src
    assert "class NetAddr(CfgObject):" in src


def test_emit_imports_engine_and_has_header():
    src = _emit_iface()
    assert src.startswith("# SPDX-License-Identifier: Apache-2.0")
    assert "from pyte.cfg import (" in src
    assert "DO NOT EDIT" in src  # generated-file banner


def test_emit_renders_docstrings_from_d():
    src = _emit_iface()
    assert '"""Network interface.' in src  # class docstring from d:


def test_emit_imports_only_used_names():
    src = _emit_iface()
    # the interface sample uses only these engine names
    for used in ("CfgObject", "IntKnob", "SubObject", "Collection"):
        assert f"    {used}," in src
    # unused knob classes must NOT be imported (else ruff F401)
    for unused in ("BoolKnob", "DoubleKnob", "StrKnob", "AddrKnob",
                   "IpAddrKnob"):
        assert unused not in src


def test_emitted_source_is_ruff_clean():
    # The generated module is checked in and linted in Phase 2b-ii, so it
    # must pass the repo's own ruff configuration.
    import shutil
    import subprocess

    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("ruff not on PATH")
    src = _emit_iface()
    res = subprocess.run(
        [ruff, "check", "--stdin-filename", "gen_interface.py", "-"],
        input=src, text=True, capture_output=True)
    assert res.returncode == 0, res.stdout + res.stderr


def test_emitted_module_imports_and_composes_oids(monkeypatch):
    # Exec the emitted source against the real engine and a fake cfg,
    # then check OID composition end to end.
    from pyte import cfg
    from pyte.cfg import _engine

    src = _emit_iface()
    ns: dict = {}
    exec(compile(src, "<gen interface>", "exec"), ns)  # noqa: S102
    Interface = ns["Interface"]

    sets = []
    monkeypatch.setattr(cfg, "set",
                        lambda oid, value, cvt=None: sets.append((oid, cvt)))
    monkeypatch.setattr(cfg, "get", lambda oid, sync=False: 1500)
    monkeypatch.setattr(_engine, "_cvt_int", lambda name: 6)

    iface = Interface("Agt_A", "eth0")
    assert iface.oid == "/agent:Agt_A/interface:eth0"
    iface.mtu = 1500
    assert sets[-1] == ("/agent:Agt_A/interface:eth0/mtu:", 6)
    assert iface.phy.oid == "/agent:Agt_A/interface:eth0/phy:"
    na = iface.net_addr["192.0.2.1"]
    assert na.oid == "/agent:Agt_A/interface:eth0/net_addr:192.0.2.1"
    assert isinstance(ns["NetAddr"], type)
