# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""test.start() lifecycle tests (fake shim).

start() mirrors TEST_START/TEST_END: the with-block never returns,
the process exits via sys.exit(result) at block end.  These tests pin
that protocol and that a failure in start()'s own setup tail (e.g. a
malformed te_rand_seed) flows through the same logged-error/cleanup/
sys.exit path as a test-body failure instead of escaping as a raw
exception that skips cleanup and leaves _current set.
"""
import logging
import signal
import sys
import types

import pytest

from pyte import log, test
from pyte._params import Params
from pyte.errors import TestFail


class FakeLib:
    TE_LL_ERROR = 1
    TE_LL_WARN = 2
    TE_LL_RING = 3
    TE_LL_INFO = 4
    TE_LL_VERB = 5
    te_test_id = 0

    def __init__(self):
        self.logs = []
        self.steps = []

    def pyte_log_init(self, entity):
        pass

    def pyte_step(self, text):
        self.steps.append(bytes(text))

    def pyte_log(self, lvl, user, text):
        self.logs.append((lvl, bytes(text)))


@pytest.fixture()
def lib(monkeypatch):
    lib = FakeLib()
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=None, lib=lib))
    # start() installs signal handlers and a root-logger handler and
    # mutates test._current; undo all of it so tests stay independent.
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


def test_start_success_exits_zero(lib, monkeypatch):
    """The with-block never returns: block end is sys.exit(0)."""
    monkeypatch.setattr(sys, "argv", ["mytest", "te_test_id=7"])
    with pytest.raises(SystemExit) as ei:
        with test.start() as t:
            assert test.current() is t
    assert ei.value.code == 0
    assert test._current is None
    assert lib.steps == [b"Test start"]


def test_start_good_seed_is_logged(lib, monkeypatch):
    monkeypatch.setattr(sys, "argv",
                        ["mytest", "te_test_id=7", "te_rand_seed=42"])
    with pytest.raises(SystemExit) as ei:
        with test.start():
            pass
    assert ei.value.code == 0
    assert any(b"Pseudo-random seed is 42" in txt for _, txt in lib.logs)


def test_start_bad_seed_fails_via_normal_exit_path(lib, monkeypatch):
    """A malformed te_rand_seed must not escape as a raw ValueError:
    the error is logged to TE and the process exits with result 1,
    with _current cleared -- same protocol as a failed test body."""
    monkeypatch.setattr(
        sys, "argv", ["mytest", "te_test_id=7", "te_rand_seed=notanint"])
    with pytest.raises(SystemExit) as ei:
        with test.start():
            raise AssertionError("body must not run")
    assert ei.value.code == 1
    assert test._current is None
    err_logs = [txt for lvl, txt in lib.logs if lvl == FakeLib.TE_LL_ERROR]
    assert any(b"notanint" in txt for txt in err_logs)


# -- expect() / check() -----------------------------------------------
#
# Pure Python, no shim involved: fail() just raises TestFail, so a bare
# Test(Params({})) is enough to exercise these.


@pytest.fixture()
def t():
    return test.Test(Params({}))


def test_expect_passes_silently_on_equal(t):
    t.expect(1, 1)


def test_expect_fails_on_unequal_default_label(t):
    with pytest.raises(TestFail) as ei:
        t.expect(1, 2)
    assert str(ei.value) == "value: expected 2, got 1"


def test_expect_fails_with_label(t):
    with pytest.raises(TestFail) as ei:
        t.expect(1, 2, "count")
    assert str(ei.value) == "count: expected 2, got 1"


def test_expect_message_uses_repr_not_str(t):
    """expected/got must show !r so type mismatches stay visible: a
    passing str "1" vs an int 1 must not read as if they matched."""
    with pytest.raises(TestFail) as ei:
        t.expect("1", 1)
    assert str(ei.value) == "value: expected 1, got '1'"


def test_check_passes_silently_on_true(t):
    t.check(True, "should not raise")


def test_check_fails_with_given_message(t):
    with pytest.raises(TestFail) as ei:
        t.check(False, "port must be open")
    assert str(ei.value) == "port must be open"
