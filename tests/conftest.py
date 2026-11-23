# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Shared fixtures: pyte's own doubles, the same a suite would use,
plus the helpers for running a real test.start() in this process."""
import logging
import signal
import sys

import pytest

from pyte import log, test
from pyte.testing import fake_shim, current_test, mi_logger  # noqa: F401

_SIGNALS = (signal.SIGINT, signal.SIGUSR1, signal.SIGUSR2)


@pytest.fixture()
def start_state(monkeypatch):
    """A test command line, and what test.start() changes undone after.

    start() installs signal handlers and a root-logger handler and sets
    test._current; restoring all three keeps tests independent.  The
    shim is not touched: install one separately.
    """
    monkeypatch.setattr(sys, "argv", ["mytest", "te_test_id=7"])
    saved = {s: signal.getsignal(s) for s in _SIGNALS}
    yield
    for s, h in saved.items():
        signal.signal(s, h)
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, log.TeLogHandler):
            root.removeHandler(h)
    test._current = None


@pytest.fixture()
def run_test(start_state):
    """``run_test(body, name=None)``: run ``body(t)`` as the body of a
    test.start() test and return its exit code."""
    def run(body, name=None):
        with pytest.raises(SystemExit) as ei:
            with test.start(name) as t:
                body(t)
        return ei.value.code
    return run
