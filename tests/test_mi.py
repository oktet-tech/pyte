# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.mi unit tests with a fake shim.

Uses the same fake-shim pattern as test_tester.py: inject a SimpleNamespace
into sys.modules["pyte._shim"] so mi.py's lazy imports never touch the real
compiled extension.
"""
import gc
import logging
import re
import signal
import sys
import types
import warnings
from pathlib import Path

import pytest

from pyte import log, mi, test
from pyte.mi import Aggr, Meas, Mult
from pyte.testing import FakeShimLib


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
    PYTE_MI_MEAS_LOADAVG    = 13
    PYTE_MI_MEAS_TIME       = 15
    # TRex meas types (mirror PYTE_MI_MEAS_* numeric values in shim)
    PYTE_MI_MEAS_CPS             = 6
    PYTE_MI_MEAS_PPS             = 1
    PYTE_MI_MEAS_EPE             = 11
    PYTE_MI_MEAS_UNITLESS_VALUE  = 0

    # View type / graph axis constants (mirror PYTE_MI_VIEW_* / AXIS_*)
    PYTE_MI_VIEW_LINE_GRAPH = 0
    PYTE_MI_GRAPH_AXIS_X    = 0
    PYTE_MI_GRAPH_AXIS_Y    = 1

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
        dname = None if name is FakeFfi.NULL else bytes(name)
        self.calls.append(("add", typ, dname, aggr, float(val), mult))
        return self.add_rc

    def pyte_mi_add_comment(self, logger, name, value):
        self.calls.append(("comment", bytes(name), bytes(value)))
        return self.add_rc

    def pyte_mi_add_view(self, logger, view_type, name, title):
        self.calls.append(("view", view_type, bytes(name), bytes(title)))
        return 0

    def pyte_mi_graph_axis_add(self, logger, view_type, view_name, axis,
                               meas_type):
        self.calls.append(("axis", view_type, bytes(view_name), axis,
                           meas_type))
        return 0

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

    #: NULL sentinel (cffi exposes ffi.NULL; a unique object suffices here).
    NULL = object()

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


def test_meas_has_trex_types():
    """Meas.CPS / PPS / EPE / UNITLESS map to PYTE_MI_MEAS_* names."""
    assert Meas.CPS.value == "PYTE_MI_MEAS_CPS"
    assert Meas.PPS.value == "PYTE_MI_MEAS_PPS"
    assert Meas.EPE.value == "PYTE_MI_MEAS_EPE"
    assert Meas.UNITLESS.value == "PYTE_MI_MEAS_UNITLESS_VALUE"


def test_trex_meas_types_resolve(monkeypatch):
    """Meas.CPS / PPS / EPE / UNITLESS map to their shim int constants."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    cases = [
        (Meas.CPS,      Aggr.SINGLE, lib.PYTE_MI_MEAS_CPS),
        (Meas.PPS,      Aggr.MEAN,   lib.PYTE_MI_MEAS_PPS),
        (Meas.EPE,      Aggr.SINGLE, lib.PYTE_MI_MEAS_EPE),
        (Meas.UNITLESS, Aggr.SINGLE, lib.PYTE_MI_MEAS_UNITLESS_VALUE),
    ]
    with mi.Logger("trex") as logger:
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


def test_add_none_name_passes_null(monkeypatch):
    """add(name=None) passes ffi.NULL (an unnamed measurement)."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("ifstat") as logger:
        logger.add(Meas.TIME, None, Aggr.SINGLE, 1.5)

    add = [c for c in lib.calls if c[0] == "add"][0]
    assert add[1] == lib.PYTE_MI_MEAS_TIME
    assert add[2] is None          # fake decodes ffi.NULL to None
    assert add[4] == 1.5


def test_comment_passes_encoded_name_and_value(monkeypatch):
    """comment() forwards encoded name/value to pyte_mi_add_comment."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("memaslap") as logger:
        logger.comment("command", "memaslap --foo")

    comments = [c for c in lib.calls if c[0] == "comment"]
    assert comments == [("comment", b"command", b"memaslap --foo")]


def test_comment_after_close_raises_runtime_error(monkeypatch):
    """comment() on a closed Logger raises RuntimeError, like add()."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    logger = mi.Logger("memaslap")
    logger.close()
    with pytest.raises(RuntimeError, match="closed"):
        logger.comment("command", "memaslap --foo")
    assert [c for c in lib.calls if c[0] == "comment"] == []


def test_line_graph_adds_view_and_x_axis(monkeypatch):
    """line_graph() creates a LINE_GRAPH view and keys X on the Meas type."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("ifstat") as logger:
        logger.line_graph("ifstat-throughputs",
                          "ifstat throughput statistics, bps",
                          x_axis=Meas.TIME)

    view = [c for c in lib.calls if c[0] == "view"][0]
    axis = [c for c in lib.calls if c[0] == "axis"][0]
    assert view == ("view", lib.PYTE_MI_VIEW_LINE_GRAPH,
                    b"ifstat-throughputs",
                    b"ifstat throughput statistics, bps")
    assert axis == ("axis", lib.PYTE_MI_VIEW_LINE_GRAPH,
                    b"ifstat-throughputs", lib.PYTE_MI_GRAPH_AXIS_X,
                    lib.PYTE_MI_MEAS_TIME)


def test_line_graph_after_close_raises(monkeypatch):
    """line_graph() on a closed Logger raises RuntimeError."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    logger = mi.Logger("ifstat")
    logger.close()
    with pytest.raises(RuntimeError, match="closed"):
        logger.line_graph("g", "t", x_axis=Meas.TIME)


def test_line_graph_wrong_x_axis_type_raises(monkeypatch):
    """line_graph() raises TypeError for a non-Meas x_axis."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)

    with mi.Logger("ifstat") as logger:
        with pytest.raises(TypeError, match="Meas"):
            logger.line_graph("g", "t", x_axis="time")


def test_logger_dropped_without_close_warns(monkeypatch):
    """A forgotten close() means the MI data silently never flushes;
    the finalizer warns (never calls the shim at GC time)."""
    import gc
    import warnings

    _fake_shim(monkeypatch, FakeLib())
    logger = mi.Logger("fio")
    with warnings.catch_warnings(record=True) as got:
        warnings.simplefilter("always")
        del logger
        gc.collect()
    assert any("never closed" in str(w.message) for w in got)
    # a properly closed logger must NOT warn
    logger = mi.Logger("fio")
    logger.close()
    with warnings.catch_warnings(record=True) as got:
        warnings.simplefilter("always")
        del logger
        gc.collect()
    assert not got


# ---------------------------------------------------------------------------
# Deferred writes: one "Measurements" step per test
# ---------------------------------------------------------------------------
#
# Inside a running test close() hands the logger to the test, which
# writes all of them under one "Measurements" step after the body and
# before Cleanup.  These run a real test.start() over a shim that has
# both the test surface (FakeShimLib) and the MI calls (FakeLib), with
# steps and MI writes on one timeline in ``calls``.

class LifecycleLib(FakeLib, FakeShimLib):
    """FakeLib plus what test.start() needs; steps join ``calls``.

    Each logger's "pointer" is its tool name, so a ``("destroy",
    tool)`` entry says which logger was written; a tool named in
    *fail_tools* fails its write.
    """

    def __init__(self, fail_tools=()):
        FakeShimLib.__init__(self)
        FakeLib.__init__(self)
        self.fail_tools = set(fail_tools)

    def pyte_step(self, text):
        FakeShimLib.pyte_step(self, text)
        self.calls.append(("step", bytes(text).decode()))

    def pyte_mi_meas_create(self, tool, out_ptr):
        self.calls.append(("create", bytes(tool)))
        out_ptr[0] = bytes(tool)
        return self.create_rc

    def pyte_mi_destroy(self, logger):
        self.calls.append(("destroy", logger))
        return 1 if logger in self.fail_tools else 0

    def timeline(self):
        """Steps and MI writes, in the order they happened."""
        return [c for c in self.calls if c[0] in ("step", "destroy")]


@pytest.fixture()
def run_lib(monkeypatch):
    """A LifecycleLib installed for test.start(); its state restored."""
    lib = LifecycleLib()
    _fake_shim(monkeypatch, lib)
    monkeypatch.setattr(sys, "argv", ["mytest", "te_test_id=7"])
    saved = {s: signal.getsignal(s)
             for s in (signal.SIGINT, signal.SIGUSR1, signal.SIGUSR2)}
    yield lib
    for s, h in saved.items():
        signal.signal(s, h)
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, log.TeLogHandler):
            root.removeHandler(h)
    test._current = None


def _run(body):
    """Run ``body(t)`` as a test body; return the exit code."""
    with pytest.raises(SystemExit) as ei:
        with test.start() as t:
            body(t)
    return ei.value.code


def test_close_defers_inside_test(run_lib):
    seen = {}

    def body(t):
        t.step("Run fio")
        t.cleanup(lambda: None)
        with mi.Logger("fio") as logger:
            logger.add(Meas.IOPS, "Read iops", Aggr.MEAN, 1.0)
        seen["written in body"] = ("destroy", b"fio") in run_lib.calls
        t.step("Check the result")

    assert _run(body) == 0
    assert seen["written in body"] is False
    assert run_lib.timeline() == [
        ("step", "Test start"), ("step", "Run fio"),
        ("step", "Check the result"), ("step", "Measurements"),
        ("destroy", b"fio"), ("step", "Cleanup")]


def test_close_immediate_writes_now(run_lib):
    def body(t):
        t.step("Run fio")
        mi.Logger("fio").close(immediate=True)
        t.step("Check the result")

    assert _run(body) == 0
    assert run_lib.timeline() == [
        ("step", "Test start"), ("step", "Run fio"), ("destroy", b"fio"),
        ("step", "Check the result")]


def test_close_outside_test_writes_now(monkeypatch):
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    assert test._current is None

    logger = mi.Logger("fio")
    logger.close()
    assert lib.calls[-1] == ("destroy",)


def test_no_loggers_no_measurements_step(run_lib):
    def body(t):
        t.step("Run fio")
        t.cleanup(lambda: None)

    assert _run(body) == 0
    assert run_lib.steps == ["Test start", "Run fio", "Cleanup"]


def test_loggers_written_in_close_order(run_lib):
    def body(t):
        with mi.Logger("outer"):
            with mi.Logger("inner"):
                pass
        mi.Logger("last").close()

    assert _run(body) == 0
    assert run_lib.timeline()[-4:] == [
        ("step", "Measurements"), ("destroy", b"inner"),
        ("destroy", b"outer"), ("destroy", b"last")]


def test_failing_logger_does_not_stop_others(run_lib):
    run_lib.fail_tools = {b"bad"}

    def body(t):
        t.cleanup(lambda: None)
        for tool in ("first", "bad", "last"):
            mi.Logger(tool).close()

    assert _run(body) == 0
    assert run_lib.timeline()[-5:] == [
        ("step", "Measurements"), ("destroy", b"first"),
        ("destroy", b"bad"), ("destroy", b"last"), ("step", "Cleanup")]
    errors = run_lib.texts(FakeShimLib.TE_LL_ERROR)
    assert len(errors) == 1
    assert "Traceback" in errors[0] and "'bad'" in errors[0]


def test_with_body_raising_still_hands_the_logger_over(run_lib):
    """Partial data is wanted on failure: a `with` block left by
    t.fail() still gets its logger written under Measurements."""
    def body(t):
        with mi.Logger("fio") as logger:
            logger.add(Meas.IOPS, "Read iops", Aggr.MEAN, 1.0)
            t.fail("Traffic stalled")

    assert _run(body) == 1
    assert run_lib.timeline()[-2:] == [
        ("step", "Measurements"), ("destroy", b"fio")]


def test_deferred_logger_is_closed_for_the_caller(run_lib):
    seen = {}

    def body(t):
        logger = mi.Logger("fio")
        logger.close()
        try:
            logger.add(Meas.IOPS, "Read iops", Aggr.MEAN, 1.0)
        except RuntimeError as exc:
            seen["error"] = str(exc)

    assert _run(body) == 0
    assert "closed" in seen["error"]
    assert [c for c in run_lib.calls if c[0] == "add"] == []


def test_deferred_logger_dropped_by_its_caller_is_still_written(run_lib):
    """The test holds the logger, so dropping the caller's reference
    neither fires the never-closed warning nor loses the data."""
    def body(t):
        mi.Logger("fio").close()
        gc.collect()

    with warnings.catch_warnings(record=True) as got:
        warnings.simplefilter("always")
        assert _run(body) == 0
        gc.collect()
    assert not [w for w in got if "never closed" in str(w.message)]
    assert ("destroy", b"fio") in run_lib.calls


def test_logger_closed_in_cleanup_is_written_at_once(run_lib):
    """Past the Measurements step a close() writes where it happens."""
    def body(t):
        t.cleanup(lambda: mi.Logger("late").close())

    assert _run(body) == 0
    assert run_lib.timeline() == [
        ("step", "Test start"), ("step", "Cleanup"), ("destroy", b"late")]


# ---------------------------------------------------------------------------
# Shim-header consistency
# ---------------------------------------------------------------------------
#
# Every test above resolves its constants through FakeLib, whose values
# are hand-mirrored from the shim by whoever adds an enum member. That
# makes both halves agree by construction: an enum member added to
# mi.py and forgotten in the shim header passes here and raises
# AttributeError on a rig, at the first logger.add(). The checks below
# read the header text instead, so they need no compiled shim and
# cannot be satisfied by the same oversight twice.

_CDEF_H = Path(__file__).resolve().parents[1] / "shim" / "pyte_shim_cdef.h"
_SHIM_H = Path(__file__).resolve().parents[1] / "shim" / "pyte_shim.h"


def _declared(path):
    """The PYTE_* names #define'd in one shim header."""
    return set(re.findall(r"^#define\s+(PYTE_MI_\w+)", path.read_text(),
                          re.M))


@pytest.mark.parametrize("enum_cls", [Meas, Aggr, Mult],
                         ids=["Meas", "Aggr", "Mult"])
def test_every_enum_member_is_declared_in_the_cdef_header(enum_cls):
    """cffi only exposes constants named in pyte_shim_cdef.h."""
    declared = _declared(_CDEF_H)
    missing = sorted(m.value for m in enum_cls
                     if m.value not in declared)
    assert not missing, (
        f"{enum_cls.__name__} members name shim constants absent from "
        f"{_CDEF_H.name}: {missing}")


@pytest.mark.parametrize("enum_cls", [Meas, Aggr, Mult],
                         ids=["Meas", "Aggr", "Mult"])
def test_every_enum_member_is_defined_in_the_shim_header(enum_cls):
    """...and the cdef declaration needs a real #define behind it."""
    declared = _declared(_SHIM_H)
    missing = sorted(m.value for m in enum_cls
                     if m.value not in declared)
    assert not missing, (
        f"{enum_cls.__name__} members name shim constants absent from "
        f"{_SHIM_H.name}: {missing}")
