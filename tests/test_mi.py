# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.mi unit tests with a fake shim.

Uses the same fake-shim pattern as test_tester.py: inject a SimpleNamespace
into sys.modules["pyte._shim"] so mi.py's lazy imports never touch the real
compiled extension.
"""
import sys
import types

import pytest

from pyte import mi


# ---------------------------------------------------------------------------
# Fake shim objects
# ---------------------------------------------------------------------------

class FakeLib:
    """Minimal shim surface that pyte.mi uses."""

    # MI meas-type constants (mirror PYTE_MI_MEAS_* numeric values in shim)
    PYTE_MI_MEAS_LATENCY    = 2
    PYTE_MI_MEAS_THROUGHPUT = 3
    PYTE_MI_MEAS_IOPS       = 12
    # Perf-tool meas types (mirror PYTE_MI_MEAS_* numeric values in shim)
    PYTE_MI_MEAS_PERCENTAGE = 14
    PYTE_MI_MEAS_RPS        = 7
    PYTE_MI_MEAS_RTT        = 8
    PYTE_MI_MEAS_RETRANS    = 9

    # Aggr constants (mirror PYTE_MI_AGGR_*)
    PYTE_MI_AGGR_SINGLE     = 1
    PYTE_MI_AGGR_MIN        = 3
    PYTE_MI_AGGR_MAX        = 4
    PYTE_MI_AGGR_MEAN       = 5
    PYTE_MI_AGGR_STDEV      = 8
    PYTE_MI_AGGR_PERCENTILE = 10

    # Multiplier constants (mirror PYTE_MI_MULT_*)
    PYTE_MI_MULT_NANO  = 0
    PYTE_MI_MULT_MICRO = 1
    PYTE_MI_MULT_MILLI = 2
    PYTE_MI_MULT_PLAIN = 3
    PYTE_MI_MULT_MEBI  = 7

    PYTE_ETIMEDOUT = 110

    def __init__(self, create_rc=0, add_rc=0, destroy_rc=0):
        self.create_rc  = create_rc
        self.add_rc     = add_rc
        self.destroy_rc = destroy_rc
        self.calls      = []
        self._logger    = object()  # sentinel pointer

    # --- shim functions ---

    def pyte_mi_meas_create(self, tool, out_ptr):
        self.calls.append(("create", bytes(tool)))
        out_ptr[0] = self._logger
        return self.create_rc

    def pyte_mi_add_meas(self, logger, typ, name, aggr, val, mult):
        self.calls.append(("add", typ, bytes(name), aggr, float(val), mult))
        return self.add_rc

    def pyte_mi_destroy(self, logger):
        self.calls.append(("destroy",))
        return self.destroy_rc

    # TeError construction helpers
    def pyte_rc_module(self, rc):
        return 0

    def pyte_rc_error(self, rc):
        return rc

    def te_rc_mod2str(self, rc):
        return b"TAPI"

    def te_rc_err2str(self, rc):
        return b"EFAIL"


class FakeFfi:
    """Minimal cffi-like façade used by pyte.mi."""

    def new(self, spec):
        """Return a tiny mutable container that supports ptr[0] = val."""
        if spec == "te_mi_logger **":
            return [None]
        raise NotImplementedError(f"FakeFfi.new({spec!r})")

    @staticmethod
    def string(b):
        return b


def _fake_shim(monkeypatch, lib):
    """Inject fake shim into sys.modules and clear mi's lazy maps."""
    monkeypatch.setitem(
        sys.modules, "pyte._shim",
        types.SimpleNamespace(ffi=FakeFfi(), lib=lib))
    # Clear lazy caches so each test starts fresh
    mi._TYPES.clear()
    mi._AGGRS.clear()
    mi._MULTS.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_logger_create_and_destroy(monkeypatch):
    """Logger CM calls create once and destroy once on normal exit."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("fio"):
        pass

    assert lib.calls[0] == ("create", b"fio")
    assert lib.calls[-1] == ("destroy",)
    assert lib.calls.count(("destroy",)) == 1


def test_add_meas_maps_names_to_ints(monkeypatch):
    """add() maps friendly names to shim int constants and passes value."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("fio") as logger:
        logger.add("latency", "lat-mean", "mean", 12.5, "nano")

    add_calls = [c for c in lib.calls if c[0] == "add"]
    assert len(add_calls) == 1
    typ, name, aggr, val, mult = add_calls[0][1:]
    assert typ  == lib.PYTE_MI_MEAS_LATENCY
    assert name == b"lat-mean"
    assert aggr == lib.PYTE_MI_AGGR_MEAN
    assert val  == 12.5
    assert mult == lib.PYTE_MI_MULT_NANO


def test_unknown_names_raise_value_error(monkeypatch):
    """Unknown type / aggr / multiplier names raise ValueError listing valid names."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("fio") as logger:
        with pytest.raises(ValueError, match="unknown.*type"):
            logger.add("no_such_type", "x", "mean", 1.0)
        with pytest.raises(ValueError, match="unknown.*aggr"):
            logger.add("latency", "x", "no_such_aggr", 1.0)
        with pytest.raises(ValueError, match="unknown.*multiplier"):
            logger.add("latency", "x", "mean", 1.0, "no_such_mult")


def test_add_after_close_raises_runtime_error(monkeypatch):
    """add() on a closed Logger raises RuntimeError."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    logger = mi.Logger("fio")
    with logger:
        pass  # CM exits, logger is closed

    with pytest.raises(RuntimeError, match="closed"):
        logger.add("latency", "x", "mean", 1.0)


def test_perf_meas_types_resolve(monkeypatch):
    """retrans / rtt / percentage / rps map to their shim int constants."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    # (type_name, aggr, expected shim int) — aggr names must be valid
    cases = [
        ("retrans",    "single", lib.PYTE_MI_MEAS_RETRANS),
        ("rtt",        "mean",   lib.PYTE_MI_MEAS_RTT),
        ("percentage", "single", lib.PYTE_MI_MEAS_PERCENTAGE),
        ("rps",        "mean",   lib.PYTE_MI_MEAS_RPS),
    ]
    with mi.Logger("perf") as logger:
        for type_name, aggr, _ in cases:
            logger.add(type_name, f"{type_name}-x", aggr, 1.0)

    add_calls = [c for c in lib.calls if c[0] == "add"]
    assert [c[1] for c in add_calls] == [expected for _, _, expected in cases]
