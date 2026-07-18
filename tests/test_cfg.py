# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for pyte.cfg value decoding and backup orchestration.

Pure Python — the shim is never imported; lib-touching code is exercised
through monkeypatched seams.
"""
import pytest

from pyte import cfg


# -- _to_py_kind: pure decode -----------------------------------------

def test_to_py_kind_none():
    assert cfg._to_py_kind("", "none") is None


def test_to_py_kind_bool_true_false():
    assert cfg._to_py_kind("1", "bool") is True
    assert cfg._to_py_kind("0", "bool") is False


def test_to_py_kind_int():
    assert cfg._to_py_kind("-7", "int") == -7
    assert isinstance(cfg._to_py_kind("-7", "int"), int)


def test_to_py_kind_float():
    assert cfg._to_py_kind("1.5", "float") == 1.5


def test_to_py_kind_str_passthrough():
    # ADDRESS and STRING both arrive as kind "str": MAC/IP/text untouched.
    assert cfg._to_py_kind("aa:bb:cc:dd:ee:ff", "str") == "aa:bb:cc:dd:ee:ff"
    assert cfg._to_py_kind("192.0.2.1", "str") == "192.0.2.1"


# -- get(): typing + sync via monkeypatched shim ----------------------

def _install_fake_get(monkeypatch, value: str, cvt: int):
    """Make cfg.get decode `value`/`cvt` without touching the real shim."""
    # CVT ints mirror the shim: NONE=0, BOOL=1, INT32=6, STRING=10,
    # DOUBLE=12 (see PYTE_CVT_* in shim/pyte_shim.h).
    monkeypatch.setattr(cfg, "_cvt_kind",
                        lambda c: {0: "none", 1: "bool", 6: "int",
                                   12: "float", 10: "str"}[c])
    monkeypatch.setattr(cfg, "_raw_get", lambda oid: (value, cvt))
    recorder = {}
    monkeypatch.setattr(cfg, "synchronize",
                        lambda oid, subtree=True: recorder.setdefault(
                            "sync", (oid, subtree)))
    return recorder


def test_get_bool_returns_bool(monkeypatch):
    _install_fake_get(monkeypatch, "1", 1)
    v = cfg.get("/agent:A/x:")
    assert v is True


def test_get_double_returns_float(monkeypatch):
    _install_fake_get(monkeypatch, "2.5", 12)
    assert cfg.get("/agent:A/x:") == 2.5


def test_get_sync_calls_synchronize_subtree_false(monkeypatch):
    rec = _install_fake_get(monkeypatch, "5", 6)
    cfg.get("/agent:A/x:", sync=True)
    assert rec["sync"] == ("/agent:A/x:", False)


def test_get_no_sync_does_not_synchronize(monkeypatch):
    rec = _install_fake_get(monkeypatch, "5", 6)
    cfg.get("/agent:A/x:")
    assert "sync" not in rec


# -- set(): cvt passthrough vs lookup ---------------------------------

def test_set_uses_given_cvt_without_lookup(monkeypatch):
    calls = []
    monkeypatch.setattr(cfg, "_get_type",
                        lambda oid: calls.append(("lookup", oid)) or 6)
    monkeypatch.setattr(cfg, "_raw_set",
                        lambda oid, cvt, wire: calls.append(
                            ("set", oid, cvt, wire)))
    cfg.set("/agent:A/x:", 5, cvt=6)
    assert calls == [("set", "/agent:A/x:", 6, "5")]  # no ("lookup", ...)


def test_set_without_cvt_looks_up_type(monkeypatch):
    calls = []
    monkeypatch.setattr(cfg, "_get_type",
                        lambda oid: calls.append(("lookup", oid)) or 6)
    monkeypatch.setattr(cfg, "_raw_set",
                        lambda oid, cvt, wire: calls.append(
                            ("set", oid, cvt, wire)))
    cfg.set("/agent:A/x:", 5)
    assert calls == [("lookup", "/agent:A/x:"),
                     ("set", "/agent:A/x:", 6, "5")]


def test_set_bool_becomes_01(monkeypatch):
    calls = []
    monkeypatch.setattr(cfg, "_raw_set",
                        lambda oid, cvt, wire: calls.append(wire))
    cfg.set("/agent:A/x:", True, cvt=1)
    assert calls == ["1"]


def test_set_none_becomes_empty_string(monkeypatch):
    """set(oid, None) must clear the value, not write the text \"None\"."""
    calls = []
    monkeypatch.setattr(cfg, "_raw_set",
                        lambda oid, cvt, wire: calls.append(wire))
    cfg.set("/agent:A/x:", None, cvt=9)
    assert calls == [""]


# -- add(): heuristic type fallback (descriptor unavailable) -----------

def _install_fake_add(monkeypatch):
    """Fake shim for add(): _get_type fails so the heuristic runs."""
    import sys
    import types

    from pyte.errors import CfgError

    class FakeLib:
        PYTE_CVT_UNSPECIFIED = 0
        PYTE_CVT_NONE = 1
        PYTE_CVT_BOOL = 2
        PYTE_CVT_INT32 = 6
        PYTE_CVT_DOUBLE = 12
        PYTE_CVT_STRING = 13

        # TeError construction helpers (CfgError takes an rc int)
        PYTE_ETIMEDOUT = 110

        def __init__(self):
            self.adds = []

        def pyte_cfg_add_str(self, oid, t, wire, handle):
            self.adds.append((bytes(oid), t, bytes(wire)))
            return 0

        def pyte_rc_error(self, rc):
            return rc

        def pyte_rc_module(self, rc):
            return 0

        def te_rc_mod2str(self, rc):
            return b"CS"

        def te_rc_err2str(self, rc):
            return b"EFAIL"

    class FakeFfi:
        def new(self, spec, *a):
            return [None]

        @staticmethod
        def string(b):
            return b

    lib = FakeLib()
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=FakeFfi(), lib=lib))

    def no_type(oid):
        raise CfgError(12)
    monkeypatch.setattr(cfg, "_get_type", no_type)
    return lib


def test_add_heuristic_bool_uses_cvt_bool(monkeypatch):
    """bool must map to CVT_BOOL, not INT32 (silently wrong type)."""
    lib = _install_fake_add(monkeypatch)
    cfg.add("/agent:A/x:i", True)
    assert lib.adds == [(b"/agent:A/x:i", lib.PYTE_CVT_BOOL, b"1")]
    lib.adds.clear()
    cfg.add("/agent:A/x:i", False)
    assert lib.adds == [(b"/agent:A/x:i", lib.PYTE_CVT_BOOL, b"0")]


def test_add_heuristic_float_uses_cvt_double(monkeypatch):
    """float must not fall through to CVT_STRING."""
    lib = _install_fake_add(monkeypatch)
    cfg.add("/agent:A/x:i", 2.5)
    assert lib.adds == [(b"/agent:A/x:i", lib.PYTE_CVT_DOUBLE, b"2.5")]


def test_add_heuristic_int_and_str_unchanged(monkeypatch):
    lib = _install_fake_add(monkeypatch)
    cfg.add("/agent:A/x:i", 7)
    cfg.add("/agent:A/x:j", "text")
    assert lib.adds == [
        (b"/agent:A/x:i", lib.PYTE_CVT_INT32, b"7"),
        (b"/agent:A/x:j", lib.PYTE_CVT_STRING, b"text"),
    ]


# -- grab_rsrc(): re-entrant after release_rsrc ------------------------

def test_grab_rsrc_repoints_existing_instance(monkeypatch):
    """release_rsrc leaves the rsrc instance in place with value \"\";
    a second grab must set() it instead of failing EEXIST on add()."""
    from pyte.errors import CfgError

    calls = []

    def fake_add(oid, value=None):
        calls.append(("add", oid, value))
        raise CfgError(12)   # what an existing instance produces

    monkeypatch.setattr(cfg, "add", fake_add)
    monkeypatch.setattr(cfg, "set",
                        lambda oid, value, cvt=None:
                        calls.append(("set", oid, value)))

    node = cfg.grab_rsrc("B", "net:lo", "/agent:B/interface:lo")

    assert calls == [
        ("add", "/agent:B/rsrc:net:lo", "/agent:B/interface:lo"),
        ("set", "/agent:B/rsrc:net:lo", "/agent:B/interface:lo"),
    ]
    assert node.oid == "/agent:B/rsrc:net:lo"


# -- backup(): order + always-release ---------------------------------

@pytest.fixture
def backup_seam(monkeypatch):
    seq = []
    monkeypatch.setattr(cfg, "_backup_create", lambda: (seq.append("create")
                                                        or "BK"))
    monkeypatch.setattr(cfg, "_backup_restore",
                        lambda name: seq.append(("restore", name)))
    monkeypatch.setattr(cfg, "_backup_release",
                        lambda name: seq.append(("release", name)))
    return seq


def test_backup_happy_path(backup_seam):
    with cfg.backup():
        backup_seam.append("body")
    assert backup_seam == ["create", "body",
                           ("restore", "BK"), ("release", "BK")]


def test_backup_restores_and_releases_on_exception(backup_seam):
    with pytest.raises(RuntimeError, match="boom"):
        with cfg.backup():
            backup_seam.append("body")
            raise RuntimeError("boom")
    assert backup_seam == ["create", "body",
                           ("restore", "BK"), ("release", "BK")]


def test_backup_yields_name(backup_seam):
    with cfg.backup() as name:
        assert name == "BK"


def test_backup_releases_even_if_restore_raises(backup_seam, monkeypatch):
    # The inner finally must release the backup even when restore itself
    # raises -- otherwise a failed restore would leak the snapshot.
    def boom_restore(name):
        backup_seam.append(("restore", name))
        raise RuntimeError("restore failed")

    monkeypatch.setattr(cfg, "_backup_restore", boom_restore)
    with pytest.raises(RuntimeError, match="restore failed"):
        with cfg.backup():
            backup_seam.append("body")
    assert backup_seam == ["create", "body",
                           ("restore", "BK"), ("release", "BK")]


# -- transaction(): keep on success, roll back on failure --------------

def test_transaction_keeps_changes_on_success(backup_seam):
    with cfg.transaction():
        backup_seam.append("body")
    # create, body, then release -- NO restore (changes kept)
    assert backup_seam == ["create", "body", ("release", "BK")]


def test_transaction_rolls_back_on_exception(backup_seam):
    with pytest.raises(RuntimeError, match="boom"):
        with cfg.transaction():
            backup_seam.append("body")
            raise RuntimeError("boom")
    assert backup_seam == ["create", "body",
                           ("restore", "BK"), ("release", "BK")]


def test_transaction_releases_even_if_restore_raises(backup_seam,
                                                     monkeypatch):
    # The inner finally must still release; and a restore failure during
    # unwind replaces the body's exception (standard finally semantics).
    def boom_restore(name):
        backup_seam.append(("restore", name))
        raise RuntimeError("restore failed")

    monkeypatch.setattr(cfg, "_backup_restore", boom_restore)
    with pytest.raises(RuntimeError, match="restore failed"):
        with cfg.transaction():
            backup_seam.append("body")
            raise RuntimeError("boom")
    assert backup_seam == ["create", "body",
                           ("restore", "BK"), ("release", "BK")]


# -- CfgNotFoundError + exists() (P1.7) ---------------------------------

def test_check_maps_enoent_to_not_found(monkeypatch):
    import sys
    import types

    from pyte.errors import CfgError, CfgNotFoundError, check

    class Lib:
        PYTE_ETIMEDOUT = 110
        PYTE_ENOENT = 2

        def pyte_rc_error(self, rc):
            return rc

        def pyte_rc_module(self, rc):
            return 0

        def te_rc_mod2str(self, rc):
            return b"CS"

        def te_rc_err2str(self, rc):
            return b"ENOENT"

    class Ffi:
        @staticmethod
        def string(b):
            return b

    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=Ffi(), lib=Lib()))
    with pytest.raises(CfgNotFoundError):
        check(2, "cfg get /x", CfgError)
    # non-ENOENT stays plain CfgError; non-cfg classes unaffected
    with pytest.raises(CfgError) as ei:
        check(5, "cfg get /x", CfgError)
    assert not isinstance(ei.value, CfgNotFoundError)
    from pyte.errors import RpcError
    with pytest.raises(RpcError) as ei:
        check(2, "call", RpcError)
    assert not isinstance(ei.value, CfgNotFoundError)


def test_exists_via_find(monkeypatch):
    monkeypatch.setattr(cfg, "find",
                        lambda pattern: [object()]
                        if pattern == "/agent:A/rsrc:x" else [])
    assert cfg.exists("/agent:A/rsrc:x") is True
    assert cfg.exists("/agent:A/rsrc:y") is False


# -- CfgSubtree: container protocol (A1) --------------------------------
#
# Regression: "x" in subtree used to iterate-and-compare CfgNode objects
# (no __eq__), so membership was silently always False even for an
# existing entry.  __contains__ must instead do a real exact-OID probe.

def _subtree(monkeypatch, present: set[str]):
    """A net_addr subtree of /agent:A/interface:eth0, backed by a fake
    cfg.find that reports only the OIDs in `present` as existing."""
    node = cfg.CfgNode("/agent:A/interface:eth0")
    monkeypatch.setattr(
        cfg, "find",
        lambda pattern: [object()] if pattern in present else [])
    return node["net_addr"]


def test_cfgsubtree_contains_true_for_existing_child(monkeypatch):
    sub = _subtree(monkeypatch,
                   {"/agent:A/interface:eth0/net_addr:192.0.2.1"})
    assert "192.0.2.1" in sub


def test_cfgsubtree_contains_false_for_missing_child(monkeypatch):
    sub = _subtree(monkeypatch, set())
    assert "192.0.2.1" not in sub


def test_cfgsubtree_get_hit_returns_cfgnode(monkeypatch):
    sub = _subtree(monkeypatch,
                   {"/agent:A/interface:eth0/net_addr:192.0.2.1"})
    got = sub.get("192.0.2.1")
    assert isinstance(got, cfg.CfgNode)
    assert got.oid == "/agent:A/interface:eth0/net_addr:192.0.2.1"


def test_cfgsubtree_get_miss_returns_none_by_default(monkeypatch):
    sub = _subtree(monkeypatch, set())
    assert sub.get("192.0.2.1") is None


def test_cfgsubtree_get_miss_returns_given_default(monkeypatch):
    sub = _subtree(monkeypatch, set())
    assert sub.get("192.0.2.1", "dflt") == "dflt"


def test_cfgsubtree_delitem_deletes_child(monkeypatch):
    node = cfg.CfgNode("/agent:A/interface:eth0")
    sub = node["net_addr"]
    deleted = []
    monkeypatch.setattr(
        cfg, "delete",
        lambda oid, children=False: deleted.append((oid, children)))
    del sub["192.0.2.1"]
    assert deleted == [
        ("/agent:A/interface:eth0/net_addr:192.0.2.1", True)]


def test_cfgsubtree_delitem_missing_propagates_engine_error(monkeypatch):
    """CfgSubtree carries no access metadata (unlike BoundCollection,
    whose owning Collection declares access=), so there is no read-only
    guard and no not-found -> KeyError translation here: whatever error
    the engine raises propagates as-is."""
    from pyte.errors import CfgNotFoundError

    node = cfg.CfgNode("/agent:A/interface:eth0")
    sub = node["net_addr"]

    def missing(oid, children=False):
        raise CfgNotFoundError(12, f"cfg delete {oid}")

    monkeypatch.setattr(cfg, "delete", missing)
    with pytest.raises(CfgNotFoundError):
        del sub["192.0.2.1"]
