# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Resource borrow helpers: OID construction and unwind ordering."""
import pytest

from pyte import cfg, net


@pytest.fixture
def calls(monkeypatch):
    """Record cfg mutations; helpers look the functions up at call time."""
    seq = []
    monkeypatch.setattr(cfg, "add",
                        lambda oid, value=None: seq.append(("add", oid,
                                                            value)))
    monkeypatch.setattr(cfg, "set",
                        lambda oid, value: seq.append(("set", oid, value)))
    monkeypatch.setattr(cfg, "synchronize",
                        lambda oid, subtree=True: seq.append(("sync", oid)))
    return seq


# -- OID construction --------------------------------------------------


def test_grab_rsrc_oid(calls):
    cfg.grab_rsrc("Agt_A", "lo", "/agent:Agt_A/interface:lo")
    assert calls == [("add", "/agent:Agt_A/rsrc:lo",
                      "/agent:Agt_A/interface:lo")]


def test_release_rsrc_oid(calls):
    cfg.release_rsrc("Agt_A", "lo")
    assert calls == [("set", "/agent:Agt_A/rsrc:lo", "")]


def test_iface_grab_release(calls):
    lo = net.Iface("Agt_B", "lo")
    lo.grab()
    lo.release()
    assert calls == [
        ("add", "/agent:Agt_B/rsrc:lo", "/agent:Agt_B/interface:lo"),
        ("set", "/agent:Agt_B/rsrc:lo", ""),
    ]


# -- cfg.borrowed_rsrc unwind ordering ----------------------------------

_RELEASE_OWNER = ("set", "/agent:Agt_A/rsrc:lo", "")
_GRAB_BORROWER = ("add", "/agent:Agt_B/rsrc:lo",
                  "/agent:Agt_B/interface:lo")
_RELEASE_BORROWER = ("set", "/agent:Agt_B/rsrc:lo", "")
_RESTORE_OWNER = ("set", "/agent:Agt_A/rsrc:lo",
                  "/agent:Agt_A/interface:lo")


def test_borrowed_rsrc_happy_order(calls):
    with cfg.borrowed_rsrc("lo", "Agt_A", "Agt_B", "interface:lo"):
        calls.append(("body",))
    assert calls == [_RELEASE_OWNER, _GRAB_BORROWER, ("body",),
                     _RELEASE_BORROWER, _RESTORE_OWNER]


def test_borrowed_rsrc_raising_body_unwinds(calls):
    with pytest.raises(RuntimeError, match="boom"):
        with cfg.borrowed_rsrc("lo", "Agt_A", "Agt_B", "interface:lo"):
            calls.append(("body",))
            raise RuntimeError("boom")
    assert calls == [_RELEASE_OWNER, _GRAB_BORROWER, ("body",),
                     _RELEASE_BORROWER, _RESTORE_OWNER]


def test_borrowed_rsrc_failed_grab_restores_owner(calls, monkeypatch):
    def boom_add(oid, value=None):
        calls.append(("add", oid, value))
        raise RuntimeError("grab failed")

    monkeypatch.setattr(cfg, "add", boom_add)
    with pytest.raises(RuntimeError, match="grab failed"):
        with cfg.borrowed_rsrc("lo", "Agt_A", "Agt_B", "interface:lo"):
            calls.append(("body",))  # pragma: no cover - never reached
    # No borrower release (the grab never happened), owner restored.
    assert calls == [_RELEASE_OWNER, _GRAB_BORROWER, _RESTORE_OWNER]


# -- net.borrowed_iface -------------------------------------------------


def test_borrowed_iface_happy_order(calls):
    with net.borrowed_iface("Agt_A", "Agt_B", "lo") as lo:
        assert isinstance(lo, net.Iface)
        assert (lo.agent, lo.name) == ("Agt_B", "lo")
        calls.append(("body",))
    assert calls == [_RELEASE_OWNER, _GRAB_BORROWER,
                     ("sync", "/agent:Agt_B"), ("body",),
                     _RELEASE_BORROWER, _RESTORE_OWNER]


def test_borrowed_iface_raising_body_unwinds(calls):
    with pytest.raises(RuntimeError, match="boom"):
        with net.borrowed_iface("Agt_A", "Agt_B", "lo"):
            calls.append(("body",))
            raise RuntimeError("boom")
    assert calls == [_RELEASE_OWNER, _GRAB_BORROWER,
                     ("sync", "/agent:Agt_B"), ("body",),
                     _RELEASE_BORROWER, _RESTORE_OWNER]
