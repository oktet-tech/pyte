# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Job helper unit tests (no shim needed)."""
import signal

import pytest

from pyte.job import _signo


def test_signo_accepts_int_and_stdlib_signal():
    assert _signo(9) == 9
    assert _signo(signal.SIGKILL) == int(signal.SIGKILL)
    assert _signo(signal.SIGTERM) == int(signal.SIGTERM)


def test_signo_rejects_string():
    with pytest.raises(TypeError, match="signal must be an int or signal"):
        _signo("SIGKILL")


def test_job_wrap_surface():
    from pyte.job import Job, Wrapper
    assert callable(Job.wrap)
    assert callable(Wrapper.delete)
