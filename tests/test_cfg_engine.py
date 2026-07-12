# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the pyte.cfg knob engine.

Pure Python: pyte.cfg.{get,set,find,add,delete} are monkeypatched and
the CVT resolver is stubbed, so no shim or testbed is needed.
"""
import types

import pytest

from pyte import cfg
from pyte.cfg import _engine
from pyte.cfg._engine import CfgObject, IntKnob


# -- hand-written domain used to exercise the engine ------------------

class Interface(CfgObject):
    mtu = IntKnob("mtu")
    ttl = IntKnob("ip4_ttl")
    index = IntKnob("index", access="read_only")

    def __init__(self, ta, ifname):
        super().__init__(f"/agent:{ta}/interface:{ifname}")


_CVT = {"INT32": 6, "BOOL": 1, "DOUBLE": 12, "STRING": 10, "ADDRESS": 11,
        "UINT64": 9}


@pytest.fixture
def fake(monkeypatch):
    store = {}
    sets = []
    monkeypatch.setattr(cfg, "get", lambda oid, sync=False: store.get(oid))

    def _set(oid, value, cvt=None):
        sets.append((oid, value, cvt))
        store[oid] = value

    monkeypatch.setattr(cfg, "set", _set)
    monkeypatch.setattr(_engine, "_cvt_int", lambda name: _CVT[name])
    return types.SimpleNamespace(store=store, sets=sets)


# -- knob get/set, oid composition, typing, read-only -----------------

def test_intknob_oid_and_get(fake):
    fake.store["/agent:A/interface:eth0/mtu:"] = 1500
    assert Interface("A", "eth0").mtu == 1500


def test_intknob_set_records_value_and_cvt(fake):
    Interface("A", "eth0").mtu = 9000
    assert fake.sets == [("/agent:A/interface:eth0/mtu:", 9000, 6)]


def test_intknob_set_coerces_to_int(fake):
    Interface("A", "eth0").mtu = "9000"
    assert fake.sets[0][1] == 9000 and isinstance(fake.sets[0][1], int)


def test_read_only_knob_get_works(fake):
    fake.store["/agent:A/interface:eth0/index:"] = 2
    assert Interface("A", "eth0").index == 2


def test_read_only_knob_set_raises(fake):
    with pytest.raises(AttributeError, match="read-only"):
        Interface("A", "eth0").index = 5
    assert fake.sets == []  # nothing written


def test_descriptor_access_on_class_returns_knob():
    assert isinstance(Interface.mtu, IntKnob)


def test_repr_uses_class_and_oid():
    assert repr(Interface("A", "eth0")) == \
        "Interface('/agent:A/interface:eth0')"


# -- saved(): change then restore -------------------------------------

def test_saved_restores_single_knob(fake):
    fake.store["/agent:A/interface:eth0/mtu:"] = 1500
    iface = Interface("A", "eth0")
    with iface.saved("mtu"):
        iface.mtu = 9000
    assert fake.sets == [("/agent:A/interface:eth0/mtu:", 9000, 6),
                         ("/agent:A/interface:eth0/mtu:", 1500, 6)]


def test_saved_restores_on_exception(fake):
    fake.store["/agent:A/interface:eth0/mtu:"] = 1500
    iface = Interface("A", "eth0")
    with pytest.raises(RuntimeError, match="boom"):
        with iface.saved("mtu"):
            iface.mtu = 9000
            raise RuntimeError("boom")
    assert fake.sets[-1] == ("/agent:A/interface:eth0/mtu:", 1500, 6)


def test_saved_multiple_knobs_all_restored(fake):
    fake.store["/agent:A/interface:eth0/mtu:"] = 1500
    fake.store["/agent:A/interface:eth0/ip4_ttl:"] = 64
    iface = Interface("A", "eth0")
    with iface.saved("mtu", "ttl"):
        iface.mtu = 9000
        iface.ttl = 1
    assert fake.store["/agent:A/interface:eth0/mtu:"] == 1500
    assert fake.store["/agent:A/interface:eth0/ip4_ttl:"] == 64
    # both restores were issued, after the two in-block sets
    assert fake.sets[-2:] == [("/agent:A/interface:eth0/mtu:", 1500, 6),
                              ("/agent:A/interface:eth0/ip4_ttl:", 64, 6)]


def test_saved_leaves_unsaved_knob_untouched(fake):
    fake.store["/agent:A/interface:eth0/mtu:"] = 1500
    fake.store["/agent:A/interface:eth0/ip4_ttl:"] = 64
    iface = Interface("A", "eth0")
    with iface.saved("mtu"):
        iface.mtu = 9000
    assert fake.store["/agent:A/interface:eth0/ip4_ttl:"] == 64  # never touched


def test_saved_read_only_knob_raises_up_front(fake):
    iface = Interface("A", "eth0")
    with pytest.raises(TypeError, match="read-only"):
        with iface.saved("index"):
            pass
    assert fake.sets == []  # no snapshot/restore writes happened


def test_knob_rejects_invalid_access():
    with pytest.raises(ValueError, match="invalid access"):
        IntKnob("x", access="readonly")


def test_intknob_accepts_custom_cvt_name(fake):
    class Big(CfgObject):
        n = IntKnob("n", cvt_name="UINT64")

        def __init__(self):
            super().__init__("/agent:A/x:y")

    Big().n = 5
    assert fake.sets[-1] == ("/agent:A/x:y/n:", 5, 9)  # UINT64 -> 9


# -- typed knob subclasses --------------------------------------------

from pyte.cfg._engine import (AddrKnob, BoolKnob, DoubleKnob,  # noqa: E402
                              IpAddrKnob, StrKnob)


class Knobs(CfgObject):
    flag = BoolKnob("flag")
    rate = DoubleKnob("rate")
    name = StrKnob("name")
    mac = AddrKnob("link_addr")
    ip = IpAddrKnob("net_addr")

    def __init__(self):
        super().__init__("/agent:A/x:y")


def test_bool_knob_get_and_set(fake):
    fake.store["/agent:A/x:y/flag:"] = True
    k = Knobs()
    assert k.flag is True
    k.flag = 0
    assert fake.sets[-1] == ("/agent:A/x:y/flag:", False, 1)


def test_double_knob_set_coerces_float(fake):
    Knobs().rate = "2.5"
    assert fake.sets[-1] == ("/agent:A/x:y/rate:", 2.5, 12)


def test_str_knob_set_coerces_str(fake):
    Knobs().name = 7
    assert fake.sets[-1] == ("/agent:A/x:y/name:", "7", 10)


def test_addr_knob_is_plain_string(fake):
    fake.store["/agent:A/x:y/link_addr:"] = "aa:bb:cc:dd:ee:ff"
    assert Knobs().mac == "aa:bb:cc:dd:ee:ff"


def test_ipaddr_knob_get_returns_ip_object(fake):
    import ipaddress
    fake.store["/agent:A/x:y/net_addr:"] = "192.0.2.1"
    assert Knobs().ip == ipaddress.ip_address("192.0.2.1")


def test_ipaddr_knob_set_serialises_to_str(fake):
    import ipaddress
    Knobs().ip = ipaddress.ip_address("192.0.2.9")
    assert fake.sets[-1] == ("/agent:A/x:y/net_addr:", "192.0.2.9", 11)


def test_ipaddr_knob_empty_is_none(fake):
    fake.store["/agent:A/x:y/net_addr:"] = ""
    assert Knobs().ip is None


def test_ipaddr_knob_set_none_writes_empty(fake):
    """from_cfg maps \"\" -> None, so to_cfg must round-trip None -> \"\"
    (saved() restore of an unset address), not write the text \"None\"."""
    Knobs().ip = None
    assert fake.sets[-1] == ("/agent:A/x:y/net_addr:", "", 11)


def test_addr_knob_set_none_writes_empty(fake):
    Knobs().mac = None
    assert fake.sets[-1] == ("/agent:A/x:y/link_addr:", "", 11)


def test_runtime_fallback_knob_passes_cvt_none(fake):
    # A bare _Knob (no cvt_name) lets cfg.set look the type up (cvt=None).
    from pyte.cfg._engine import _Knob

    class Bare(CfgObject):
        thing = _Knob("thing")

        def __init__(self):
            super().__init__("/agent:A/x:y")

    Bare().thing = "v"
    assert fake.sets[-1] == ("/agent:A/x:y/thing:", "v", None)


# -- SubObject: singleton child nesting -------------------------------

from pyte.cfg._engine import SubObject  # noqa: E402


class Phy(CfgObject):
    autoneg = BoolKnob("autoneg")
    speed_admin = IntKnob("speed_admin")


class IfaceWithPhy(CfgObject):
    phy = SubObject("phy", Phy)

    def __init__(self, ta, ifname):
        super().__init__(f"/agent:{ta}/interface:{ifname}")


def test_subobject_returns_bound_child(fake):
    phy = IfaceWithPhy("A", "eth0").phy
    assert isinstance(phy, Phy)
    assert phy.oid == "/agent:A/interface:eth0/phy:"


def test_subobject_knob_oid_has_double_segment(fake):
    # Real TE OID form: /agent:%s/interface:%s/phy:/autoneg:
    fake.store["/agent:A/interface:eth0/phy:/autoneg:"] = True
    assert IfaceWithPhy("A", "eth0").phy.autoneg is True


def test_subobject_knob_set(fake):
    IfaceWithPhy("A", "eth0").phy.speed_admin = 10000
    assert fake.sets[-1] == (
        "/agent:A/interface:eth0/phy:/speed_admin:", 10000, 6)


def test_subobject_on_class_returns_descriptor():
    assert isinstance(IfaceWithPhy.phy, SubObject)


def test_saved_rejects_non_knob_attr(fake):
    # saved() of a SubObject (or a typo) would shadow the class
    # descriptor on restore; reject it up front instead.
    iface = IfaceWithPhy("A", "eth0")
    with pytest.raises(TypeError, match="not a writable knob"):
        with iface.saved("phy"):
            pass
    with pytest.raises(TypeError, match="not a writable knob"):
        with iface.saved("nonexistent"):
            pass


# -- Collection: instance-named children ------------------------------

from pyte.cfg._engine import BoundCollection, Collection  # noqa: E402


class NetAddr(CfgObject):
    broadcast = AddrKnob("broadcast")


class IfaceWithAddrs(CfgObject):
    net_addr = Collection("net_addr", NetAddr)

    def __init__(self, ta, ifname):
        super().__init__(f"/agent:{ta}/interface:{ifname}")


def test_collection_on_class_returns_descriptor():
    assert isinstance(IfaceWithAddrs.net_addr, Collection)


def test_collection_getitem_builds_child(fake):
    a = IfaceWithAddrs("A", "eth0").net_addr["192.0.2.1"]
    assert isinstance(a, NetAddr)
    assert a.oid == "/agent:A/interface:eth0/net_addr:192.0.2.1"


def test_collection_is_bound(fake):
    assert isinstance(IfaceWithAddrs("A", "eth0").net_addr, BoundCollection)


def test_collection_iter_yields_children(fake, monkeypatch):
    nodes = [types.SimpleNamespace(oid="/agent:A/interface:eth0/net_addr:10.0.0.1"),
             types.SimpleNamespace(oid="/agent:A/interface:eth0/net_addr:10.0.0.2")]
    captured = {}

    def _find(pattern):
        captured["pattern"] = pattern
        return nodes

    monkeypatch.setattr(cfg, "find", _find)
    addrs = list(IfaceWithAddrs("A", "eth0").net_addr)
    assert captured["pattern"] == "/agent:A/interface:eth0/net_addr:*"
    assert [a.oid for a in addrs] == [n.oid for n in nodes]
    assert all(isinstance(a, NetAddr) for a in addrs)


def test_collection_add(fake, monkeypatch):
    added = []
    monkeypatch.setattr(cfg, "add",
                        lambda oid, value=None: added.append((oid, value)))
    a = IfaceWithAddrs("A", "eth0").net_addr.add("10.0.0.5")
    assert added == [("/agent:A/interface:eth0/net_addr:10.0.0.5", None)]
    assert isinstance(a, NetAddr)
    assert a.oid == "/agent:A/interface:eth0/net_addr:10.0.0.5"


def test_collection_add_passes_value_through(fake, monkeypatch):
    added = []
    monkeypatch.setattr(cfg, "add",
                        lambda oid, value=None: added.append((oid, value)))
    IfaceWithAddrs("A", "eth0").net_addr.add("10.0.0.6", "192.168.0.255")
    assert added == [("/agent:A/interface:eth0/net_addr:10.0.0.6",
                      "192.168.0.255")]


def test_collection_delitem(fake, monkeypatch):
    deleted = []
    monkeypatch.setattr(cfg, "delete",
                        lambda oid, children=False: deleted.append(
                            (oid, children)))
    del IfaceWithAddrs("A", "eth0").net_addr["10.0.0.5"]
    assert deleted == [("/agent:A/interface:eth0/net_addr:10.0.0.5", True)]


# -- public re-exports from pyte.cfg ----------------------------------

def test_cfgobject_name_is_instance_key():
    assert CfgObject("/agent:A/interface:eth0/net_addr:192.0.2.1").name \
        == "192.0.2.1"


def test_cfgobject_name_empty_for_singleton_segment():
    assert CfgObject("/agent:A/interface:eth0/phy:").name == ""


def test_cfgobject_name_top_level():
    assert CfgObject("/agent:A").name == "A"


def _record_sync_get(monkeypatch, seen):
    def fake_get(oid, sync=False):
        seen["sync"] = sync
        return 5
    monkeypatch.setattr(cfg, "get", fake_get)


def test_knob_sync_reads_with_sync(monkeypatch):
    seen = {}
    _record_sync_get(monkeypatch, seen)

    class Obj(CfgObject):
        v = IntKnob("v", sync=True)

        def __init__(self):
            super().__init__("/agent:A/x:y")

    assert Obj().v == 5
    assert seen["sync"] is True


def test_knob_default_no_sync(monkeypatch):
    seen = {}
    _record_sync_get(monkeypatch, seen)

    class Obj(CfgObject):
        v = IntKnob("v")

        def __init__(self):
            super().__init__("/agent:A/x:y")

    _ = Obj().v
    assert seen["sync"] is False


def test_engine_names_reexported_from_pyte_cfg():
    import pyte.cfg as cfgpkg
    for name in ("CfgObject", "IntKnob", "BoolKnob", "DoubleKnob",
                 "StrKnob", "AddrKnob", "IpAddrKnob", "SelfKnob",
                 "SubObject", "Collection"):
        assert hasattr(cfgpkg, name), name


# -- SelfKnob: the object's own value ---------------------------------

from pyte.cfg._engine import SelfKnob  # noqa: E402


class NetAddr2(CfgObject):
    value = SelfKnob(cvt_name="INT32")        # the prefix length
    broadcast = AddrKnob("broadcast")


def test_selfknob_get_reads_own_oid(fake):
    fake.store["/agent:A/interface:eth0/net_addr:10.0.0.1"] = 24
    na = NetAddr2("/agent:A/interface:eth0/net_addr:10.0.0.1")
    assert na.value == 24                       # reads the base OID itself
    assert na.broadcast is None                 # child not set


def test_selfknob_set_writes_own_oid(fake):
    na = NetAddr2("/agent:A/interface:eth0/net_addr:10.0.0.1")
    na.value = 25
    # the own-OID write has NO trailing /subid: segment
    assert fake.sets[-1] == ("/agent:A/interface:eth0/net_addr:10.0.0.1",
                             25, 6)


def test_selfknob_read_only_rejects(fake):
    class RO(CfgObject):
        value = SelfKnob(cvt_name="INT32", access="read_only")

    with pytest.raises(AttributeError, match="read-only"):
        RO("/agent:A/x:y").value = 1
