# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.stress unit tests (offline: argv build + validation)."""
import pytest

from pyte.tools import stress  # noqa: F401  (import-smoke check)
from pyte.tools.stress import Opts


def test_to_argv_full_order():
    argv = Opts(cpu=2, io=1, vm=3, duration=5).to_argv()
    assert argv == ["--cpu", "2", "--io", "1", "--vm", "3", "--timeout", "5"]


def test_to_argv_omits_unset():
    assert Opts(cpu=1).to_argv() == ["--cpu", "1"]
    assert Opts(io=4, duration=10).to_argv() == ["--io", "4", "--timeout", "10"]


def test_requires_at_least_one_target():
    with pytest.raises(ValueError, match="cpu/io/vm"):
        Opts(duration=5)
    with pytest.raises(ValueError, match="cpu/io/vm"):
        Opts()


def test_wait_returns_job_status():
    """BREAKING (P1.1 sweep): wait() returns the JobStatus, not a bool
    -- the status says which signal killed the run, not just success."""
    from pyte.job import JobStatus, StatusKind
    from pyte.tools.stress import Stress

    class FakeJob:
        def wait(self, timeout=None):
            return JobStatus(StatusKind.SIGNALED, 9)

    st = Stress(FakeJob()).wait()
    assert isinstance(st, JobStatus)
    assert not st.ok and st.value == 9


# -- wait() timeout convention (A2) ------------------------------------------

def test_wait_omitted_uses_default_timeout():
    from pyte.job import JobStatus, StatusKind
    from pyte.tools.stress import Stress

    class FakeJob:
        def __init__(self):
            self.wait_calls = []

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            return JobStatus(StatusKind.EXITED, 0)

    job = FakeJob()
    Stress(job).wait()
    assert job.wait_calls == [Stress.default_timeout]


def test_wait_none_blocks_forever():
    """A2: timeout=None must mean 'forever', not 'default'."""
    from pyte.job import JobStatus, StatusKind
    from pyte.tools.stress import Stress

    class FakeJob:
        def __init__(self):
            self.wait_calls = []

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            return JobStatus(StatusKind.EXITED, 0)

    job = FakeJob()
    Stress(job).wait(timeout=None)
    assert job.wait_calls == [None]


# -- run() docstring example (A11) -------------------------------------------

def test_run_docstring_example_opts_is_valid():
    """A11: stress.run()'s docstring example used the pre-rename
    ``timeout=`` field name (renamed to ``duration``), which raised
    TypeError if anyone actually ran it. Guard against the same drift
    recurring: the example's Opts call must construct cleanly."""
    Opts(cpu=1, duration=2)
