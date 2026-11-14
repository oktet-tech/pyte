# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Test.finalize(), Test.failed and the Measurements step (fake shim).

Every test ends in one order: the body ends, ``failed`` is set, the
finalizers run last registered first under a "Collect results" step,
the MI loggers closed in the test are written under a "Measurements"
step, then Cleanup.  The
loggers here are pyte.testing's RecordingMiLogger, which defers like
mi.Logger and records the step it was written under.  Tests run
through conftest's run_test.
"""
import signal
import sys

import pytest

from pyte import log, test
from pyte.testing import FakeShimLib, RecordingMiLogger


@pytest.fixture
def lib(fake_shim, start_state, mi_logger):
    """fake_shim, with a clean RecordingMiLogger registry."""
    return fake_shim


# Ways for a body (or a finalizer: same shape) to end.

def _pass(t):
    pass


def _fail(t):
    t.fail("Traffic stalled")


def _skip(t):
    t.skip("No such device")


def _error(t):
    raise RuntimeError("bug in the test")


def _interrupt(t):
    raise KeyboardInterrupt()


def _signal(t):
    signal.raise_signal(signal.SIGUSR1)


def _exit(code):
    def end(t):
        sys.exit(code)
    return end


def _errors(lib, prefix):
    return [txt for txt in lib.texts(FakeShimLib.TE_LL_ERROR)
            if txt.startswith(prefix)]


def test_finalizers_run_before_measurements_on_fail(lib, run_test):
    seen = {}

    def stop(t):
        seen["failed"] = t.failed
        RecordingMiLogger("sampler").close()

    def body(t):
        t.step("Run traffic")
        t.finalize(stop, t)
        t.cleanup(lambda: None)
        t.fail("Traffic stalled")

    assert run_test(body) == 1
    assert seen["failed"] is True
    logger, = RecordingMiLogger.registry
    assert logger.written_step == "Measurements"
    assert lib.steps == ["Test start", "Run traffic", "Collect results",
                         "Measurements", "Cleanup"]


def test_finalizers_run_last_registered_first_with_their_args(lib,
                                                              run_test):
    """Like cleanups: a sampler registered after a session stops before
    the session's own finalizer reads the console, so what that reads
    cannot land inside a live sampler tick."""
    order = []

    def body(t):
        t.finalize(order.append, "first")
        t.finalize(lambda *a, **kw: order.append((a, kw)), 1, k=2)
        t.finalize(order.append, "last")

    assert run_test(body) == 0
    assert order == ["last", ((1,), {"k": 2}), "first"]


def test_finalizers_run_in_a_collect_results_step(lib, run_test):
    """What the finalizers log is collecting results, not the last body
    step's work: it gets a step of its own."""
    seen = []

    def body(t):
        t.step("Run traffic")
        t.finalize(lambda: seen.append(lib.steps[-1]))
        t.finalize(log.ring, "Sampler stopped")

    assert run_test(body) == 0
    assert lib.steps == ["Test start", "Run traffic", "Collect results"]
    assert seen == ["Collect results"]
    assert "Sampler stopped" in lib.texts(FakeShimLib.TE_LL_RING)


def test_no_finalizers_no_collect_results_step(lib, run_test):
    def body(t):
        t.step("Run traffic")
        t.cleanup(lambda: None)

    assert run_test(body) == 0
    assert lib.steps == ["Test start", "Run traffic", "Cleanup"]


def test_a_failing_collect_results_step_still_runs_the_finalizers(
        lib, run_test, monkeypatch):
    """The step call is guarded on its own, like the Measurements one."""
    step = lib.pyte_step

    def pyte_step(text):
        if text == b"Collect results":
            raise RuntimeError("step lost")
        step(text)

    monkeypatch.setattr(lib, "pyte_step", pyte_step)
    ran = []

    def body(t):
        t.finalize(ran.append, "finalizer")

    assert run_test(body) == 0
    assert ran == ["finalizer"]
    failures = _errors(lib, "Opening the Collect results step failed")
    assert len(failures) == 1 and "step lost" in failures[0]


def test_failed_is_false_while_the_body_runs(lib, run_test):
    seen = {}

    def body(t):
        seen["body"] = t.failed
        t.finalize(lambda: seen.setdefault("finalizer", t.failed))

    assert run_test(body) == 0
    assert seen == {"body": False, "finalizer": False}


@pytest.mark.parametrize("raise_, fails", [
    (_error, False),
    (_interrupt, True),
    (_exit(0), True),
    (_signal, True),
    (_fail, True),
], ids=["error", "interrupt", "exit", "signal", "t.fail"])
@pytest.mark.parametrize("body_end, code", [
    (_pass, 0),
    (_fail, 1),
    (_skip, test.EXIT_SKIP),
], ids=["pass", "fail", "skip"])
def test_failing_finalizer_does_not_stop_others(lib, run_test, raise_,
                                                fails, body_end, code):
    """A raising finalizer is logged and the rest still run.  An
    ordinary error leaves the exit code alone; an interrupt, an exit
    or a TestFail (the signal handler raises one) turns a pass into a
    failure, which is what a cleanup raising it does too."""
    ran = []

    def body(t):
        t.finalize(ran.append, "after")
        t.finalize(raise_, t)              # runs first: last registered
        t.cleanup(ran.append, "cleanup")
        body_end(t)

    assert run_test(body) == (1 if fails and code == 0 else code)
    assert ran == ["after", "cleanup"]
    failures = _errors(lib, "Finalizer failed")
    assert len(failures) == 1
    assert "Traceback" in failures[0]


def test_prologue_gets_measurements_step(lib, run_test, monkeypatch):
    """Prologues and epilogues are tests: nothing keys on the name."""
    monkeypatch.setattr(sys, "argv", ["prologue.py", "te_test_id=7"])

    def body(t):
        t.step("Configure the DUT")
        RecordingMiLogger("dut").close()

    assert run_test(body) == 0
    assert lib.entity == "prologue.py"
    assert lib.steps == ["Test start", "Configure the DUT",
                         "Measurements"]


@pytest.mark.parametrize("body_end, code, failed", [
    (_pass, 0, False),
    (_skip, test.EXIT_SKIP, False),
    (_fail, 1, True),
    (_error, 1, True),
    (_exit(3), 3, True),
    (_exit(0), 0, False),
    (_signal, 1, True),
], ids=["pass", "skip", "fail", "error", "exit-3", "exit-0", "signal"])
def test_every_exit_runs_finalizers_then_measurements_then_cleanup(
        lib, run_test, body_end, code, failed):
    seen = []

    def body(t):
        t.step("Run traffic")
        t.finalize(lambda: seen.append(("failed", t.failed)))
        t.finalize(lambda: RecordingMiLogger("sampler").close())
        t.cleanup(lambda: seen.append("cleanup"))
        body_end(t)

    assert run_test(body) == code
    assert seen == [("failed", failed), "cleanup"]
    assert RecordingMiLogger.registry[0].written_step == "Measurements"
    assert lib.steps[-3:] == ["Collect results", "Measurements",
                              "Cleanup"]


def test_a_failing_measurements_step_still_writes_the_loggers(
        lib, run_test, monkeypatch):
    """The step call is guarded on its own: the writes still run."""
    step = lib.pyte_step

    def pyte_step(text):
        if text == b"Measurements":
            raise RuntimeError("step lost")
        step(text)

    monkeypatch.setattr(lib, "pyte_step", pyte_step)
    ran = []

    def body(t):
        t.step("Run traffic")
        RecordingMiLogger("sampler").close()
        t.cleanup(ran.append, "cleanup")

    assert run_test(body) == 0
    logger, = RecordingMiLogger.registry
    assert logger.written
    assert ran == ["cleanup"]
    assert test._current is None
    failures = _errors(lib, "Opening the Measurements step failed")
    assert len(failures) == 1 and "step lost" in failures[0]


@pytest.mark.parametrize("phase, prefix, early_written", [
    ("_run_finalizers", "Running the finalizers failed", True),
    ("_write_measurements", "Writing the measurements failed", False),
], ids=["finalizers", "measurements"])
def test_an_escape_from_one_phase_does_not_cost_the_rest(
        lib, run_test, monkeypatch, phase, prefix, early_written):
    """What escapes the per-item guards (a signal between two items;
    here the whole phase raising) is logged and fails the test, but the
    next phase and the cleanups still run, and a logger closed in a
    cleanup is written at once, not held for a step that is gone."""
    ran = []

    def escape():
        raise KeyboardInterrupt()

    def body(t):
        monkeypatch.setattr(t, phase, escape)
        RecordingMiLogger("early").close()
        t.cleanup(lambda: RecordingMiLogger("late").close())
        t.cleanup(ran.append, "cleanup")

    assert run_test(body) == 1
    assert ran == ["cleanup"]
    early, late = RecordingMiLogger.registry
    assert early.written is early_written
    assert late.written_step == "Cleanup"
    assert len(_errors(lib, prefix)) == 1


def test_signal_failure_is_reported(lib, run_test):
    """The signal cases above fail through the handler, not by luck."""
    assert run_test(_signal) == 1
    assert any("Test got signal SIGUSR1" in txt
               for txt in lib.texts(FakeShimLib.TE_LL_ERROR))


def test_an_interrupt_in_the_body_still_ends_the_test(lib):
    """A BaseException start() does not catch still gets finalizers,
    Measurements and Cleanup on its way out, as cleanups do today."""
    seen = []

    with pytest.raises(KeyboardInterrupt):
        with test.start() as t:
            t.finalize(lambda: seen.append(("failed", t.failed)))
            t.finalize(lambda: RecordingMiLogger("sampler").close())
            t.cleanup(lambda: seen.append("cleanup"))
            raise KeyboardInterrupt()
    assert seen == [("failed", True), "cleanup"]
    assert lib.steps[-3:] == ["Collect results", "Measurements",
                              "Cleanup"]
    assert test._current is None
