# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Test.finalize(), Test.failed and the Measurements step (fake shim).

Every test ends in one order: the body ends, ``failed`` is set, the
finalizers run in registration order, the MI loggers closed in the
test are written under a "Measurements" step, then Cleanup.  The
loggers here are pyte.testing's RecordingMiLogger, which defers like
mi.Logger and records the step it was written under.
"""
import logging
import signal
import sys

import pytest

from pyte import log, test
from pyte.testing import FakeShimLib, RecordingMiLogger


@pytest.fixture()
def lib(fake_shim, monkeypatch):
    """fake_shim, plus the process state test.start() changes restored."""
    monkeypatch.setattr(sys, "argv", ["mytest", "te_test_id=7"])
    saved = {s: signal.getsignal(s)
             for s in (signal.SIGINT, signal.SIGUSR1, signal.SIGUSR2)}
    RecordingMiLogger.reset()
    yield fake_shim
    RecordingMiLogger.reset()
    for s, h in saved.items():
        signal.signal(s, h)
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, log.TeLogHandler):
            root.removeHandler(h)
    test._current = None


def _run(body, name=None):
    """Run ``body(t)`` as a test body; return the exit code."""
    with pytest.raises(SystemExit) as ei:
        with test.start(name) as t:
            body(t)
    return ei.value.code


def _fail(t):
    t.fail("Traffic stalled")


def _boom():
    raise RuntimeError("sampler lost")


def _interrupt():
    raise KeyboardInterrupt()


def _exit_zero():
    sys.exit(0)


def test_finalizers_run_before_measurements_on_fail(lib):
    seen = {}

    def stop(t):
        seen["failed"] = t.failed
        RecordingMiLogger("sampler").close()

    def body(t):
        t.step("Run traffic")
        t.finalize(stop, t)
        t.cleanup(lambda: None)
        t.fail("Traffic stalled")

    assert _run(body) == 1
    assert seen["failed"] is True
    logger, = RecordingMiLogger.registry
    assert logger.written_step == "Measurements"
    assert lib.steps == ["Test start", "Run traffic", "Measurements",
                         "Cleanup"]


def test_finalizers_run_in_registration_order_with_their_args(lib):
    order = []

    def body(t):
        t.finalize(order.append, "first")
        t.finalize(lambda *a, **kw: order.append((a, kw)), 1, k=2)
        t.finalize(order.append, "last")

    assert _run(body) == 0
    assert order == ["first", ((1,), {"k": 2}), "last"]


def test_finalizers_get_no_step_of_their_own(lib):
    """What a finalizer logs lands at the end of the last body step."""
    def body(t):
        t.step("Run traffic")
        t.finalize(log.ring, "Sampler stopped")

    assert _run(body) == 0
    assert lib.steps == ["Test start", "Run traffic"]
    assert "Sampler stopped" in lib.texts(FakeShimLib.TE_LL_RING)


def test_failed_is_false_while_the_body_runs(lib):
    seen = {}

    def body(t):
        seen["body"] = t.failed
        t.finalize(lambda: seen.setdefault("finalizer", t.failed))

    assert _run(body) == 0
    assert seen == {"body": False, "finalizer": False}


@pytest.mark.parametrize("raise_", [_boom, _interrupt, _exit_zero],
                         ids=["error", "interrupt", "exit"])
@pytest.mark.parametrize("body_end, code", [
    (lambda t: None, 0),
    (_fail, 1),
], ids=["pass", "fail"])
def test_failing_finalizer_does_not_stop_others(lib, raise_, body_end,
                                                code):
    ran = []

    def body(t):
        t.finalize(raise_)
        t.finalize(ran.append, "second")
        t.cleanup(ran.append, "cleanup")
        body_end(t)

    assert _run(body) == code
    assert ran == ["second", "cleanup"]
    failures = [txt for txt in lib.texts(FakeShimLib.TE_LL_ERROR)
                if txt.startswith("Finalizer failed")]
    assert len(failures) == 1
    assert "Traceback" in failures[0]


def test_prologue_gets_measurements_step(lib, monkeypatch):
    """Prologues and epilogues are tests: nothing keys on the name."""
    monkeypatch.setattr(sys, "argv", ["prologue.py", "te_test_id=7"])

    def body(t):
        t.step("Configure the DUT")
        RecordingMiLogger("dut").close()

    assert _run(body) == 0
    assert lib.entity == "prologue.py"
    assert lib.steps == ["Test start", "Configure the DUT",
                         "Measurements"]


def _signal(t):
    signal.raise_signal(signal.SIGUSR1)


def _skip(t):
    t.skip("No such device")


def _error(t):
    raise RuntimeError("bug in the test")


def _exit(code):
    def end(t):
        sys.exit(code)
    return end


@pytest.mark.parametrize("body_end, code, failed", [
    (lambda t: None, 0, False),
    (_skip, test.EXIT_SKIP, False),
    (_fail, 1, True),
    (_error, 1, True),
    (_exit(3), 3, True),
    (_exit(0), 0, False),
    (_signal, 1, True),
], ids=["pass", "skip", "fail", "error", "exit-3", "exit-0", "signal"])
def test_every_exit_runs_finalizers_then_measurements_then_cleanup(
        lib, body_end, code, failed):
    seen = []

    def body(t):
        t.step("Run traffic")
        t.finalize(lambda: seen.append(("failed", t.failed)))
        t.finalize(lambda: RecordingMiLogger("sampler").close())
        t.cleanup(lambda: seen.append("cleanup"))
        body_end(t)

    assert _run(body) == code
    assert seen == [("failed", failed), "cleanup"]
    assert RecordingMiLogger.registry[0].written_step == "Measurements"
    assert lib.steps[-2:] == ["Measurements", "Cleanup"]


def test_a_failure_between_the_writes_does_not_skip_cleanup(
        lib, monkeypatch):
    """Something escaping the per-item guards (a signal between two
    items, here a step that raises) is logged; Cleanup still runs."""
    step = lib.pyte_step

    def pyte_step(text):
        if text == b"Measurements":
            raise RuntimeError("step lost")
        step(text)

    monkeypatch.setattr(lib, "pyte_step", pyte_step)
    ran = []

    def body(t):
        RecordingMiLogger("sampler").close()
        t.cleanup(ran.append, "cleanup")

    assert _run(body) == 0
    assert ran == ["cleanup"]
    assert test._current is None
    assert any("step lost" in txt
               for txt in lib.texts(FakeShimLib.TE_LL_ERROR))


def test_signal_failure_is_reported(lib):
    """The signal case above fails through the handler, not by luck."""
    assert _run(_signal) == 1
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
    assert lib.steps[-2:] == ["Measurements", "Cleanup"]
    assert test._current is None
