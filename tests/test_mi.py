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
from pyte.mi import Aggr, Meas, Mult


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
    PYTE_MI_AGGR_MEDIAN     = 6
    PYTE_MI_AGGR_PERCENTILE = 10

    # Multiplier constants (mirror PYTE_MI_MULT_*)
    PYTE_MI_MULT_NANO  = 0
    PYTE_MI_MULT_MICRO = 1
    PYTE_MI_MULT_MILLI = 2
    PYTE_MI_MULT_PLAIN = 3
    PYTE_MI_MULT_MEGA  = 6
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
    """Inject fake shim into sys.modules and clear mi's lazy cache."""
    monkeypatch.setitem(
        sys.modules, "pyte._shim",
        types.SimpleNamespace(ffi=FakeFfi(), lib=lib))
    # Clear lazy cache so each test starts fresh
    mi._BITS.clear()


# ---------------------------------------------------------------------------
# Autouse fixture: clear _BITS after every test so cached ints don't bleed.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_bits():
    """Clear pyte.mi._BITS before and after each test."""
    mi._BITS.clear()
    yield
    mi._BITS.clear()


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


def test_add_meas_maps_enums_to_ints(monkeypatch):
    """add() maps Meas/Aggr/Mult enums to shim int constants and passes value."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("fio") as logger:
        logger.add(Meas.LATENCY, "lat-mean", Aggr.MEAN, 12.5, Mult.NANO)

    add_calls = [c for c in lib.calls if c[0] == "add"]
    assert len(add_calls) == 1
    typ, name, aggr, val, mult = add_calls[0][1:]
    assert typ  == lib.PYTE_MI_MEAS_LATENCY
    assert name == b"lat-mean"
    assert aggr == lib.PYTE_MI_AGGR_MEAN
    assert val  == 12.5
    assert mult == lib.PYTE_MI_MULT_NANO


def test_string_type_raises_type_error(monkeypatch):
    """add() raises TypeError when passed a string type instead of Meas."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("fio") as logger:
        with pytest.raises(TypeError, match="Meas"):
            logger.add("latency", "n", Aggr.MEAN, 1.0)


def test_string_aggr_raises_type_error(monkeypatch):
    """add() raises TypeError when passed a string aggr instead of Aggr."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("fio") as logger:
        with pytest.raises(TypeError, match="Aggr"):
            logger.add(Meas.LATENCY, "n", "mean", 1.0)


def test_string_multiplier_raises_type_error(monkeypatch):
    """add() raises TypeError when passed a string multiplier instead of Mult."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("fio") as logger:
        with pytest.raises(TypeError, match="Mult"):
            logger.add(Meas.LATENCY, "n", Aggr.MEAN, 1.0, "nano")


def test_add_after_close_raises_runtime_error(monkeypatch):
    """add() on a closed Logger raises RuntimeError."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    logger = mi.Logger("fio")
    with logger:
        pass  # CM exits, logger is closed

    with pytest.raises(RuntimeError, match="closed"):
        logger.add(Meas.LATENCY, "x", Aggr.MEAN, 1.0)


def test_perf_meas_types_resolve(monkeypatch):
    """Meas.RETRANS / RTT / PERCENTAGE / RPS map to their shim int constants."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    cases = [
        (Meas.RETRANS,    Aggr.SINGLE, lib.PYTE_MI_MEAS_RETRANS),
        (Meas.RTT,        Aggr.MEAN,   lib.PYTE_MI_MEAS_RTT),
        (Meas.PERCENTAGE, Aggr.SINGLE, lib.PYTE_MI_MEAS_PERCENTAGE),
        (Meas.RPS,        Aggr.MEAN,   lib.PYTE_MI_MEAS_RPS),
    ]
    with mi.Logger("perf") as logger:
        for meas, aggr, _ in cases:
            logger.add(meas, f"{meas.name}-x", aggr, 1.0)

    add_calls = [c for c in lib.calls if c[0] == "add"]
    assert [c[1] for c in add_calls] == [expected for _, _, expected in cases]


def test_median_aggr_and_mega_mult_resolve(monkeypatch):
    """Aggr.MEDIAN and Mult.MEGA map to their shim constants."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("perf") as logger:
        logger.add(Meas.THROUGHPUT, "x", Aggr.MEDIAN, 1.0, Mult.MEGA)

    add = [c for c in lib.calls if c[0] == "add"][0]
    # add tuple: ("add", typ, name, aggr, val, mult)
    assert add[3] == lib.PYTE_MI_AGGR_MEDIAN
    assert add[5] == lib.PYTE_MI_MULT_MEGA
