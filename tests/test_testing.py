# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.testing: the shared doubles must record what they claim to.

The fake_shim/current_test fixtures come from tests/conftest.py, which
re-exports them exactly as a suite's own conftest would.
"""
import pytest

from pyte import log, test as pyte_test
from pyte.errors import TeError, TestFail, TestSkip
from pyte.testing import (FakeShimLib, FakeTrexReport, RecordingMiLogger,
                          VerdictRecorder)


# -- FakeShimLib -------------------------------------------------------

def test_log_calls_are_recorded_with_level_and_text(fake_shim):
    log.ring("hello")
    log.error("boom")
    assert fake_shim.logs == [(FakeShimLib.TE_LL_RING, "hello"),
                              (FakeShimLib.TE_LL_ERROR, "boom")]


def test_log_records_keep_the_user(fake_shim):
    log.warn("careful", user="Tool")
    assert fake_shim.records == [(FakeShimLib.TE_LL_WARN, "Tool",
                                  "careful")]


def test_texts_filters_by_level(fake_shim):
    log.ring("a")
    log.warn("b")
    log.ring("c")
    assert fake_shim.texts(FakeShimLib.TE_LL_RING) == ["a", "c"]


def test_step_push_pop_land_in_the_log_stream(fake_shim):
    log.step_push("outer")
    log.ring("inner")
    log.step_pop("done")
    assert fake_shim.logs == [("STEP_PUSH", "outer"),
                              (FakeShimLib.TE_LL_RING, "inner"),
                              ("STEP_POP", "done")]


def test_structural_calls_are_recorded(current_test, fake_shim):
    current_test.step("do a thing")
    current_test.substep("part of it")
    current_test.verdict("all good")
    current_test.verdict("not good", error=True)
    current_test.artifact("some text")
    assert fake_shim.steps == ["do a thing"]
    assert fake_shim.substeps == ["part of it"]
    assert fake_shim.verdicts == [(FakeShimLib.TE_LL_RING, "all good"),
                                  (FakeShimLib.TE_LL_ERROR, "not good")]
    assert fake_shim.artifacts == [(FakeShimLib.TE_LL_RING, "some text")]


def test_tester_calls_are_recorded(fake_shim):
    from pyte import tester
    tester.modify_reqs("!FIO")
    tester.add_trc_tag("linux", "6.17")
    assert fake_shim.calls == [("reqs", "!FIO"), ("tag", "linux", "6.17")]


def test_nonzero_rc_surfaces_as_a_teerror(fake_shim):
    """rc makes every recorded call fail, for the failure paths."""
    from pyte import tester

    fake_shim.rc = 0xBEEF
    with pytest.raises(TeError, match="add_trc_tag"):
        tester.add_trc_tag("x")


def test_err_names_steer_the_error_name(fake_shim):
    fake_shim.err_names[0x42] = b"EOPNOTSUPP"
    assert fake_shim.te_rc_err2str(0x42) == b"EOPNOTSUPP"
    assert fake_shim.te_rc_err2str(0x43) == b"EUNKNOWN"


# -- fixtures ----------------------------------------------------------

def test_current_test_is_installed_and_restored(current_test):
    assert pyte_test.current() is current_test


def test_current_test_was_restored_afterwards():
    """The previous value is back: no current test outside the fixture."""
    assert pyte_test._current is None


# -- VerdictRecorder ---------------------------------------------------

def test_verdict_recorder_records_verdicts():
    t = VerdictRecorder()
    t.verdict("fine")
    t.verdict("broken", error=True)
    assert t.verdicts == [("fine", False), ("broken", True)]


def test_verdict_recorder_fail_and_skip_raise():
    t = VerdictRecorder()
    with pytest.raises(TestFail, match="nope"):
        t.fail("nope")
    with pytest.raises(TestSkip):
        t.skip("not applicable")


# -- RecordingMiLogger -------------------------------------------------

def test_recording_mi_logger_records_in_creation_order():
    RecordingMiLogger.reset()
    with RecordingMiLogger("trex") as lg:
        lg.add("throughput", "tx", "mean", 1.5)
        lg.comment("note", "text")
        lg.line_graph("g", "Graph", "time")
    with RecordingMiLogger("other"):
        pass

    first, second = RecordingMiLogger.registry
    assert [lg.tool for lg in (first, second)] == ["trex", "other"]
    assert first.adds == [("throughput", "tx", "mean", 1.5, None)]
    assert first.comments == [("note", "text")]
    assert first.graphs == [("g", "Graph", "time")]
    assert first.closed and second.closed


def test_recording_mi_logger_reset_empties_the_registry():
    RecordingMiLogger("x")
    RecordingMiLogger.reset()
    assert RecordingMiLogger.registry == []


# -- FakeTrexReport ----------------------------------------------------

def test_fake_report_records_window_calls():
    rep = FakeTrexReport(value=(1.0, 2.0, 3.0, 4.0))
    assert rep.window("CURR_TIME", 0, 10.0, 65.0) == (1.0, 2.0, 3.0, 4.0)
    assert rep.calls == [("CURR_TIME", 0, 10.0, 65.0)]


def test_fake_report_warns_for_a_clamped_parameter():
    from pyte.tools.trex._batch_report import WindowClamped

    rep = FakeTrexReport(clamp_params=("CURR_TIME",))
    with pytest.warns(WindowClamped):
        rep.window("CURR_TIME", 0, 0.0, 1.0)


def test_fake_report_series_accessors():
    rep = FakeTrexReport(time_series_vals=(0.0, 1.0),
                         series_vals={("TX", 0): [3.0, 4.0]})
    assert rep.time_series() == [0.0, 1.0]
    assert rep.series_by_time("TX", 0) == [3.0, 4.0]


def test_mi_logger_fixture_resets_the_registry(mi_logger):
    assert mi_logger.registry == []
    with mi_logger("tool"):
        pass
    assert len(mi_logger.registry) == 1
