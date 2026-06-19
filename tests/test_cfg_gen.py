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


def test_attr_name_sanitizes_non_identifiers():
    assert _gen.attr_name("file-max") == "file_max"      # hyphen -> _
    assert _gen.attr_name("global") == "global_"          # keyword -> _
    assert _gen.attr_name("exception-trace") == "exception_trace"


def test_class_name_handles_hyphen_segment():
    assert _gen.class_name("/a/file-max", "/a") == "FileMax"


def test_emit_keeps_raw_subid_with_sanitized_attr():
    # A hyphenated leaf -> attr file_max but OID subid stays "file-max".
    y = """
- register:
    - oid: "/agent/sys"
      type: none
      access: read_only
      d: |
         System.
    - oid: "/agent/sys/file-max"
      type: uint64
      access: read_write
      d: |
         Max files.
"""
    root = _gen.build_tree(_gen.parse_cm(y))
    src = _gen.emit_module(root.children["sys"], "sys")
    assert 'file_max = IntKnob("file-max", cvt_name="UINT64")' in src


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


def test_emit_docstring_word_does_not_add_import():
    # Engine words appearing in d: prose must NOT pull in an import (which
    # would then be unused -> ruff F401). Imports are tracked from emitted
    # code, not by scanning rendered text.
    y = """
- register:
    - oid: "/agent/thing"
      type: none
      access: read_only
      d: |
         A Collection of SubObject-like AddrKnob words.
    - oid: "/agent/thing/n"
      type: int32
      access: read_write
      d: |
         A number.
"""
    root = _gen.build_tree(_gen.parse_cm(y))
    src = _gen.emit_module(root.children["thing"], "thing")
    for spurious in ("    Collection,", "    SubObject,", "    AddrKnob,"):
        assert spurious not in src
    assert "    IntKnob," in src   # the only real engine name used


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


# -- lint -------------------------------------------------------------

def test_lint_flags_invalid_name_token():
    entries = _gen.parse_cm('''
- register:
    - oid: "/agent/x"
      type: none
      access: read_only
      name: "Bad Name"
      d: |
         X.
''')
    warns = _gen.lint(entries)
    assert any("invalid name" in w for w in warns)


def test_lint_flags_integer_typo():
    entries = _gen.parse_cm('''
- register:
    - oid: "/agent/x"
      type: integer
      access: read_write
      d: |
         X.
''')
    warns = _gen.lint(entries)
    assert any("integer" in w for w in warns)


def test_lint_flags_likely_collection_defaulted_to_none():
    # name: absent (=> none) but the d: prose names a key.
    entries = _gen.parse_cm_raw('''
- register:
    - oid: "/agent/iface2"
      type: none
      access: read_create
      d: |
         Some interface.
         Name: interface name
''')
    warns = _gen.lint(entries)
    assert any("looks like a collection" in w for w in warns)


def test_lint_clean_input_has_no_warnings():
    entries = _gen.parse_cm(_IFACE_YAML)
    assert _gen.lint(entries) == []


# -- self-value emission (value + children objects) -------------------

_NETADDR_YAML = """
- register:
    - oid: "/agent/interface"
      type: none
      name: ifname
      access: read_create
      d: |
         Network interface.
    - oid: "/agent/interface/net_addr"
      type: int32
      name: address
      access: read_create
      d: |
         Network address of the interface.
    - oid: "/agent/interface/net_addr/broadcast"
      type: address
      access: read_write
      d: |
         Broadcast address.
"""


def _emit_netaddr():
    root = _gen.build_tree(_gen.parse_cm(_NETADDR_YAML))
    return _gen.emit_module(root.children["interface"], "interface")


def test_emit_self_value_for_value_typed_parent():
    src = _emit_netaddr()
    assert "class NetAddr(CfgObject):" in src
    assert 'value = SelfKnob(cvt_name="INT32")' in src       # own prefix value
    assert 'broadcast = AddrKnob("broadcast")' in src        # the child
    assert "    SelfKnob," in src                            # imported


def test_emit_no_self_value_for_pure_container():
    # phy is type none -> its own class carries no self-value (only the
    # value-typed nodes do).
    src = _emit_iface()
    phy_block = src.split("class Phy(CfgObject):")[1].split("\nclass ")[0]
    assert "SelfKnob" not in phy_block


def test_emit_self_value_for_childless_value_collection():
    # A value-typed collection with NO children (e.g. a string macvlan
    # keyed by name) must still expose its own value.
    y = """
- register:
    - oid: "/agent/interface"
      type: none
      name: ifname
      access: read_create
      d: |
         Network interface.
    - oid: "/agent/interface/macvlan"
      type: string
      name: ifname
      access: read_create
      d: |
         MAC VLAN.
"""
    root = _gen.build_tree(_gen.parse_cm(y))
    src = _gen.emit_module(root.children["interface"], "interface")
    assert "class Macvlan(CfgObject):" in src
    assert 'value = SelfKnob(cvt_name="STRING")' in src
    assert 'macvlan = Collection("macvlan", Macvlan)' in src


def test_emitted_netaddr_self_value_roundtrips(monkeypatch):
    from pyte import cfg
    from pyte.cfg import _engine
    src = _emit_netaddr()
    ns: dict = {}
    exec(compile(src, "<gen>", "exec"), ns)  # noqa: S102
    sets = []
    monkeypatch.setattr(cfg, "set",
                        lambda oid, value, cvt=None: sets.append((oid, cvt)))
    monkeypatch.setattr(cfg, "get", lambda oid, sync=False: 24)
    monkeypatch.setattr(_engine, "_cvt_int", lambda name: 6)
    iface = ns["Interface"]("A", "eth0")
    na = iface.net_addr["10.0.0.1"]
    assert na.value == 24
    na.value = 25
    # own-OID write: no trailing /value: segment
    assert sets[-1] == ("/agent:A/interface:eth0/net_addr:10.0.0.1", 6)


def test_emitted_netaddr_is_ruff_clean():
    import shutil
    import subprocess
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("ruff not on PATH")
    src = _emit_netaddr()
    res = subprocess.run(
        [ruff, "check", "--stdin-filename", "gen_netaddr.py", "-"],
        input=src, text=True, capture_output=True)
    assert res.returncode == 0, res.stdout + res.stderr


# -- real-CM wiring ---------------------------------------------------

def test_targets_cover_sys_and_interface():
    names = {t.module for t in _gen.TARGETS}
    assert {"sys", "interface"} <= names


def test_generate_from_text_map_emits_modules():
    # generate_from() takes a {filename: yaml_text} map so it is testable
    # without the real CM files on disk.
    files = {
        "cm_sys.yml": """
- register:
    - oid: "/agent/sys"
      type: none
      access: read_only
      d: |
         System settings.
    - oid: "/agent/sys/console_loglevel"
      type: int32
      access: read_write
      d: |
         Console log level.
""",
    }
    out = _gen.generate_from(files, [
        _gen.Target("cm_sys.yml", "/agent/sys", "sys")])
    assert "sys" in out
    assert "class Sys(CfgObject):" in out["sys"]
    assert 'console_loglevel = IntKnob("console_loglevel", cvt_name="INT32")' \
        in out["sys"]


# -- volatile -> sync=True --------------------------------------------

def test_parse_captures_volatile():
    e = {x.oid: x for x in _gen.parse_cm("""
- register:
    - oid: "/agent/x"
      type: none
      access: read_only
      d: |
         X.
    - oid: "/agent/x/counter"
      type: uint64
      access: read_only
      volatile: true
      d: |
         A counter.
""")}
    assert e["/agent/x/counter"].volatile is True
    assert e["/agent/x"].volatile is False


def test_emit_sync_for_volatile_knob():
    root = _gen.build_tree(_gen.parse_cm("""
- register:
    - oid: "/agent/x"
      type: none
      access: read_only
      d: |
         X.
    - oid: "/agent/x/nm"
      type: string
      access: read_write
      d: |
         A name.
    - oid: "/agent/x/c"
      type: int32
      access: read_write
      volatile: true
      d: |
         A volatile counter.
"""))
    src = _gen.emit_module(root.children["x"], "x")
    assert 'c = IntKnob("c", cvt_name="INT32", sync=True)' in src
    assert 'nm = StrKnob("nm")' in src   # non-volatile: no sync


def test_emit_sync_for_volatile_self_value():
    root = _gen.build_tree(_gen.parse_cm("""
- register:
    - oid: "/agent/x"
      type: none
      access: read_only
      d: |
         X.
    - oid: "/agent/x/stat"
      type: uint64
      name: name
      access: read_only
      volatile: true
      d: |
         A keyed volatile stat.
"""))
    src = _gen.emit_module(root.children["x"], "x")
    assert 'value = SelfKnob(cvt_name="UINT64", sync=True)' in src


def test_emit_wraps_long_knob_line():
    # A volatile read-only uint64 knob with a long name exceeds 79 chars
    # on one line; it must be emitted wrapped (each line <= 79).
    root = _gen.build_tree(_gen.parse_cm("""
- register:
    - oid: "/agent/x"
      type: none
      access: read_only
      d: |
         X.
    - oid: "/agent/x/in_unknown_protos_counter"
      type: uint64
      access: read_only
      volatile: true
      d: |
         Long volatile counter.
"""))
    src = _gen.emit_module(root.children["x"], "x")
    assert all(len(line) <= 79 for line in src.splitlines()), \
        [ln for ln in src.splitlines() if len(ln) > 79]
    # the knob is still present (wrapped form)
    assert "in_unknown_protos_counter = IntKnob(" in src
    assert 'sync=True' in src
