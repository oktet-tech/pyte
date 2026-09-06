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


def test_start_cleanup_emits_step_frame_when_registered(lib, monkeypatch):
    """When the test registers a cleanup, a "Cleanup" step must be
    emitted before it runs, so the cleanup's own log lines land in a
    truthful frame instead of the test's last t.step()."""
    monkeypatch.setattr(sys, "argv", ["mytest", "te_test_id=7"])
    with pytest.raises(SystemExit) as ei:
        with test.start() as t:
            t.step("Do the thing")
            t.cleanup(lambda: None)
    assert ei.value.code == 0
    assert lib.steps == [b"Test start", b"Do the thing", b"Cleanup"]


def test_start_no_cleanup_emits_no_extra_step(lib, monkeypatch):
    """No cleanups registered: no "Cleanup" step frame is emitted."""
    monkeypatch.setattr(sys, "argv", ["mytest", "te_test_id=7"])
    with pytest.raises(SystemExit) as ei:
        with test.start() as t:
            t.step("Do the thing")
    assert ei.value.code == 0
    assert lib.steps == [b"Test start", b"Do the thing"]


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


# -- default_param() / default_uint() ----------------------------------
#
# Per-test defaults live in the Configurator, so these need nothing but
# a monkeypatched pyte.cfg.get (test.py imports cfg lazily).


@pytest.fixture()
def cfg_get(monkeypatch):
    """Record the OIDs asked for; answer from a settable value."""
    from pyte import cfg

    class Recorder:
        def __init__(self):
            self.oids = []
            self.value = "42"

        def __call__(self, oid, sync=False):
            self.oids.append(oid)
            if isinstance(self.value, Exception):
                raise self.value
            return self.value

    rec = Recorder()
    monkeypatch.setattr(cfg, "get", rec)
    return rec


def test_default_param_returns_the_value_as_string(t, cfg_get):
    cfg_get.value = 65
    assert t.default_param("duration", "trex/trex") == "65"


def test_default_param_mangles_slashes_in_the_test_name(t, cfg_get):
    t.default_param("duration", "trex/trex")
    assert cfg_get.oids == [
        "/local:/test:/testname:trex_trex/default:duration"]


def test_default_param_propagates_the_configurator_error(t, cfg_get):
    class Boom(Exception):
        """Stands in for CfgError, which needs a live shim to build."""

    cfg_get.value = Boom("no such instance")
    with pytest.raises(Boom):
        t.default_param("duration", "trex/trex")


def test_default_uint_parses_decimal(t, cfg_get):
    cfg_get.value = "65"
    assert t.default_uint("duration", "trex/trex") == 65


def test_default_uint_parses_base_zero_prefixes(t, cfg_get):
    cfg_get.value = "0x10"
    assert t.default_uint("duration", "trex/trex") == 16


def test_default_uint_rejects_a_negative_value(t, cfg_get):
    cfg_get.value = "-1"
    with pytest.raises(ValueError, match="unsigned integer"):
        t.default_uint("duration", "trex/trex")


def test_default_uint_rejects_junk(t, cfg_get):
    cfg_get.value = "soon"
    with pytest.raises(ValueError, match="unsigned integer"):
        t.default_uint("duration", "trex/trex")
