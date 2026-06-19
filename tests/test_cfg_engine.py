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


_CVT = {"INT32": 6, "BOOL": 1, "DOUBLE": 12, "STRING": 10, "ADDRESS": 11}


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
