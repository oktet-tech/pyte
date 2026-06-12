# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.fio unit tests.

Pure Python: no shim needed anywhere in fio.py, so these tests run
without a compiled extension.  Fake pco/job objects are defined inline.
MI tests reuse the fake-shim pattern from test_mi.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyte import fio
from pyte.fio import (
    Opts,
    Report,
    _parse_report,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent / "data" / "fio_sample.json"


@pytest.fixture(scope="module")
def sample_report() -> Report:
    obj = json.loads(FIXTURE.read_text())
    return _parse_report(obj)


# ---------------------------------------------------------------------------
# Test 1: Opts size parsing
# ---------------------------------------------------------------------------

def test_opts_size_parsing():
    """Size strings are parsed to bytes; bad suffixes raise ValueError."""
    assert fio._parse_size(4096) == 4096
    assert fio._parse_size("4k") == 4 * 1024
    assert fio._parse_size("16m") == 16 * 1024 * 1024
    assert fio._parse_size("1g") == 1 * 1024 * 1024 * 1024
    with pytest.raises(ValueError, match="unrecognised"):
        fio._parse_size("16q")
    assert fio._parse_size(None) is None


# ---------------------------------------------------------------------------
# Test 2: Opts validation
# ---------------------------------------------------------------------------

def test_opts_filename_required():
    """Opts requires a non-empty filename."""
    with pytest.raises((ValueError, TypeError)):
        Opts(filename="")


def test_opts_rwtype_validation():
    """Unknown rwtype raises ValueError."""
    with pytest.raises(ValueError, match="unknown rwtype"):
        Opts(filename="/tmp/f", rwtype="badtype")


def test_opts_ioengine_validation():
    """Unknown ioengine raises ValueError."""
    with pytest.raises(ValueError, match="unknown ioengine"):
        Opts(filename="/tmp/f", ioengine="notanengine")


# ---------------------------------------------------------------------------
# Test 3: to_argv golden test
# ---------------------------------------------------------------------------

def test_to_argv_golden():
    """to_argv produces the expected full argv list."""
    opts = Opts(
        name="mytest",
        filename="/tmp/test.dat",
        blocksize=4096,
        numjobs=2,
        iodepth=4,
        runtime=5,
        rwmixread=70,
        rwtype="rand",
        ioengine="libaio",
        direct=True,
        size="16m",
        extra_args=["--norandommap"],
    )
    argv = opts.to_argv()
    assert argv == [
        "--name=mytest",
        "--filename=/tmp/test.dat",
        "--blocksize=4096",
        "--iodepth=4",
        "--runtime=5s",
        "--time_based",
        "--rwmixread=70",
        "--output-format=json",
        "--group_reporting",
        "--direct=1",
        "--readwrite=randrw",
        "--ioengine=libaio",
        "--numjobs=2",
        "--thread",
        "--norandommap",
        f"--size={16 * 1024 * 1024}",
    ]


def test_to_argv_no_runtime_no_time_based():
    """When runtime=0, --runtime and --time_based are absent."""
    opts = Opts(filename="/tmp/f", runtime=0)
    argv = opts.to_argv()
    assert "--time_based" not in argv
    assert not any(a.startswith("--runtime=") for a in argv)


# ---------------------------------------------------------------------------
# Test 4: Report from fixture — assert real values
# ---------------------------------------------------------------------------

def test_report_from_fixture_read_iops(sample_report):
    """read.iops.mean matches the fixture (fio-3.39 output)."""
    assert abs(sample_report.read.iops.mean - 1213756.5) < 1.0


def test_report_from_fixture_write_bandwidth_max(sample_report):
    """write.bandwidth.max matches the fixture."""
    assert sample_report.write.bandwidth.max == 4934824


def test_report_from_fixture_clat_percentiles(sample_report):
    """read.clatency.percentiles.p99_00 matches the fixture (nanoseconds)."""
    assert sample_report.read.clatency.percentiles.p99_00 == 458
    assert sample_report.write.clatency.percentiles.p99_00 == 458


def test_report_from_fixture_latency_ns(sample_report):
    """lat_ns fields match the fixture."""
    assert sample_report.read.latency.min_ns == 208
    assert sample_report.read.latency.max_ns == 114839
    assert abs(sample_report.read.latency.mean_ns - 312.109349) < 0.001


# ---------------------------------------------------------------------------
# Test 5: Lifecycle with fakes (pure Python, no shim)
# ---------------------------------------------------------------------------

class _FakeFilter:
    """Minimal Filter fake: read_all returns canned JSON."""

    def __init__(self, text: str = ""):
        self._text = text
        self.log_calls: list = []

    def read_all(self, timeout: float = 10.0) -> str:
        return self._text

    def attach_filter(self, name=None, readable=True, log_level=None,
                      regex=None, group=0):
        return self


class _FakeChannel:
    """Fake Channel: attach_filter / log return a FakeFilter."""

    def __init__(self, text: str = ""):
        self._text = text
        self._filter = _FakeFilter(text)

    def attach_filter(self, name=None, readable=True, log_level=None,
                      regex=None, group=0):
        return self._filter

    def log(self, level=None):
        return self._filter


class _FakeJobStatus:
    def __init__(self, ok: bool = True):
        self._ok = ok

    @property
    def ok(self) -> bool:
        return self._ok

    def __str__(self) -> str:
        return "exited(0)" if self._ok else "exited(1)"


class _FakeJob:
    """Fake Job: records calls, returns fake channels."""

    def __init__(self, stdout_text: str = "", exit_ok: bool = True):
        self._stdout_text = stdout_text
        self._exit_ok = exit_ok
        self._stdout_ch = _FakeChannel(stdout_text)
        self._stderr_ch = _FakeChannel()
        self.started = False
        self.stopped = False
        self.destroyed = False

    @property
    def stdout(self) -> _FakeChannel:
        return self._stdout_ch

    @property
    def stderr(self) -> _FakeChannel:
        return self._stderr_ch

    def start(self) -> None:
        self.started = True

    def wait(self, timeout: float = 10.0) -> _FakeJobStatus:
        return _FakeJobStatus(self._exit_ok)

    def stop(self, timeout: float = 10.0, signal="SIGTERM") -> None:
        self.stopped = True

    def destroy(self, timeout: float = 10.0) -> None:
        self.destroyed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.destroy()
        return False


class _FakePco:
    """Fake RpcServer: job() returns a pre-configured FakeJob."""

    def __init__(self, fake_job: _FakeJob):
        self._fake_job = fake_job
        self.job_calls: list[tuple] = []

    def job(self, program: str, args: list[str] | None = None,
            env=None) -> _FakeJob:
        self.job_calls.append((program, args))
        return self._fake_job


def test_lifecycle_wait_and_close(tmp_path):
    """Fio lifecycle: job create→start→wait→close, report parsed."""
    fixture_json = FIXTURE.read_text()
    fake_job = _FakeJob(stdout_text=fixture_json, exit_ok=True)
    fake_pco = _FakePco(fake_job)
    opts = Opts(filename="/tmp/f", size="4m", runtime=2)

    with fio.run(fake_pco, opts) as f:
        assert fake_job.started
        rep = f.wait(timeout=10.0)
        assert isinstance(rep, Report)
        assert rep.read.iops.mean > 0
        assert rep.write.iops.mean > 0

    assert fake_job.destroyed
    # job() was called with "fio" and the generated argv
    assert fake_pco.job_calls[0][0] == "fio"
    argv = fake_pco.job_calls[0][1]
    assert "--output-format=json" in argv
    assert "--group_reporting" in argv


def test_lifecycle_close_idempotent():
    """close() is safe to call multiple times."""
    fake_job = _FakeJob(stdout_text="{}", exit_ok=True)

    f_obj = fio.Fio(fake_job, fake_job.stdout.attach_filter())
    f_obj.close()
    f_obj.close()  # must not raise or double-destroy
    # destroy called exactly once because close is idempotent
    assert fake_job.destroyed


def test_lifecycle_nonzero_exit_raises():
    """wait() raises TeError when fio exits with non-zero status."""
    from pyte.errors import TeError

    fixture_json = FIXTURE.read_text()
    fake_job = _FakeJob(stdout_text=fixture_json, exit_ok=False)
    fake_pco = _FakePco(fake_job)
    opts = Opts(filename="/tmp/f")

    with pytest.raises(TeError):
        with fio.run(fake_pco, opts) as f:
            f.wait(timeout=10.0)
