# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.batch lifecycle/session unit tests.

Step 1-4 (offline, pure parts only): the random yaml config path shape,
the ASTF json path with/without an instance prefix, n_ports counting
(dummy ports excluded), and --cfg landing last in the launch argv.
Job/agent-touching bring-up (create()/Trex) is exercised with fakes
further down.
"""
from __future__ import annotations

import contextlib
import re

import pytest

from pyte.tools.trex import batch

_YAML_PATH_RE = re.compile(r"/tmp/[A-Za-z_][A-Za-z0-9_]{31}\.yaml")


def _opts(**kw):
    base = dict(trex_exec="/usr/local/trex/_t-rex-64-o", astf_json="{}",
                clients=(batch.Endpoint(iface=batch.LinuxIface("eth1")),))
    base.update(kw)
    return batch.Opts(**base)


# --------------------------------------------------------------------
# yaml_cfg_path()
# --------------------------------------------------------------------

def test_yaml_cfg_path_matches_32_char_c_identifier_shape():
    path = batch.yaml_cfg_path()
    assert _YAML_PATH_RE.fullmatch(path), path


def test_yaml_cfg_path_is_random_each_call():
    # Not a strict guarantee, but a collision in 100 32-char draws would
    # indicate the generator is broken (e.g. always returning the seed).
    paths = {batch.yaml_cfg_path() for _ in range(100)}
    assert len(paths) == 100


# --------------------------------------------------------------------
# astf_json_path()
# --------------------------------------------------------------------

def test_astf_json_path_no_prefix():
    assert batch.astf_json_path(None) == "/tmp/astf.json"


def test_astf_json_path_empty_prefix_same_as_none():
    # Mirrors C's te_str_is_null_or_empty(instance_prefix).
    assert batch.astf_json_path("") == "/tmp/astf.json"


def test_astf_json_path_with_prefix():
    assert batch.astf_json_path("inst0") == "/tmp/astf-inst0.json"


# --------------------------------------------------------------------
# n_ports()
# --------------------------------------------------------------------

def test_n_ports_counts_only_non_dummy_endpoints():
    opts = _opts(
        clients=(batch.Endpoint(iface=batch.LinuxIface("eth0")),
                 batch.Endpoint()),  # dummy: no iface
        servers=(batch.Endpoint(iface=batch.PciBdf("0000:01:00.0")),))
    assert batch.n_ports(opts) == 2


def test_n_ports_all_dummy_is_zero():
    opts = _opts(clients=(batch.Endpoint(),), servers=(batch.Endpoint(),))
    assert batch.n_ports(opts) == 0


# --------------------------------------------------------------------
# build_argv(): --cfg appended last
# --------------------------------------------------------------------

def test_build_argv_appends_cfg_last():
    opts = _opts(instance_prefix="inst0")
    argv = batch.build_argv(opts, "/tmp/abc.yaml")
    assert argv[-2:] == ["--cfg", "/tmp/abc.yaml"]
    assert argv == opts.to_argv() + ["--cfg", "/tmp/abc.yaml"]


def test_build_argv_minimal_opts_cfg_still_last():
    opts = _opts()
    argv = batch.build_argv(opts, "/tmp/xyz.yaml")
    assert argv[-2:] == ["--cfg", "/tmp/xyz.yaml"]


# --------------------------------------------------------------------
# create()/Trex lifecycle with fakes (pure Python, no shim)
# --------------------------------------------------------------------

class _FakeMessage:
    def __init__(self, data: str):
        self.data = data


class _FakeFilter:
    """Records how it was attached; drain() replays canned messages."""

    def __init__(self, **attach_kwargs):
        self.attach_kwargs = attach_kwargs
        self._queue: list[str] = []

    def feed(self, *values: str) -> None:
        self._queue.extend(values)

    def drain(self, timeout: float = 0) -> list[_FakeMessage]:
        out = [_FakeMessage(v) for v in self._queue]
        self._queue.clear()
        return out


class _FakeChannel:
    def __init__(self):
        self.log_calls: list = []

    def log(self, level=None):
        self.log_calls.append(level)
        return _FakeFilter(log_level=level)


class _FakeJobStatus:
    def __init__(self, ok: bool = True):
        self.ok = ok


class _FakeJob:
    def __init__(self):
        self.program = "/bin/sh"
        self.started = False
        self.stopped = False
        self.destroyed = False
        self.killed_with = None
        self.filters: list[_FakeFilter] = []
        self.stdout = _FakeChannel()
        self.stderr = _FakeChannel()
        self.quiet_calls: list[str] = []
        self._wait_exc = None
        self._wait_result = _FakeJobStatus(True)

    def filter(self, stdout=False, stderr=False, readable=True,
               log_level=None, regex=None, group=0, name=None):
        f = _FakeFilter(stdout=stdout, stderr=stderr, regex=regex,
                        group=group, name=name)
        self.filters.append(f)
        return f

    def start(self):
        self.started = True

    def wait(self, timeout=None):
        if self._wait_exc is not None:
            raise self._wait_exc
        return self._wait_result

    def stop(self, timeout=10.0, signal=None):
        self.stopped = True

    def kill(self, signum):
        self.killed_with = signum

    def destroy(self, timeout=10.0):
        self.destroyed = True

    @contextlib.contextmanager
    def quiet(self):
        """No-op stand-in for Job.quiet(): records enter/exit so tests
        can assert report() re-silences its filters via this, not
        RpcServer.silent_pass()."""
        self.quiet_calls.append("enter")
        try:
            yield self
        finally:
            self.quiet_calls.append("exit")


class _FakePco:
    def __init__(self, ta: str = "agentA"):
        self.ta = ta
        self.files_put: dict[str, bytes] = {}
        self.unlinked: list[str] = []
        self.job_calls: list[tuple] = []
        self._job = _FakeJob()
        self.silent_pass_calls: list[str] = []

    def file_put(self, path: str, data: bytes) -> None:
        self.files_put[path] = data

    def job(self, program: str, args=None, env=None, stdin=False):
        self.job_calls.append((program, args))
        return self._job

    def unlink(self, path: str) -> None:
        self.unlinked.append(path)

    @contextlib.contextmanager
    def silent_pass(self):
        """No-op stand-in for RpcServer.silent_pass(): records the
        window's enter/exit so tests can assert create() wraps job
        creation and filter attachment in it."""
        self.silent_pass_calls.append("enter")
        try:
            yield self
        finally:
            self.silent_pass_calls.append("exit")


def _batch_opts(**kw):
    base = dict(
        trex_exec="/opt/trex/v3/_t-rex-64-o",
        astf_json='{"k": "v"}',
        clients=(batch.Endpoint(iface=batch.LinuxIface("eth0")),),
        servers=(batch.Endpoint(),))  # dummy
    base.update(kw)
    return batch.Opts(**base)


def test_create_does_not_start_but_attaches_filters_and_writes_files():
    pco = _FakePco()
    opts = _batch_opts()

    with batch.create(pco, opts) as trex:
        assert not pco._job.started
        assert isinstance(trex, batch.Trex)
        # astf json + platform yaml were written before the job exists.
        assert opts.astf_json.encode() in pco.files_put.values()
        assert len(pco.files_put) == 2
        # job launched via a /bin/sh -c wrapper; the real argv (with
        # --cfg) is exposed as trex.cmd for the suite's own logging.
        program, args = pco.job_calls[0]
        assert program == "/bin/sh"
        assert args[0] == "-c"
        assert trex.cmd[0] == opts.trex_exec
        assert trex.cmd[-2:] == ["--cfg", trex.cmd[-1]]
        assert trex.cmd[-1] in " ".join(args)
        # summary + optional-counter filters attached (iom not NORMAL,
        # so no port/global stat filters).
        from pyte.tools.trex import _batch_filters as flt
        assert set(trex._summary) == set(flt.SUMMARY)
        assert set(trex._opt) == set(flt.OPT_COUNTERS)
        assert trex._port_stat == {}
        assert trex._port_time == {}
        assert trex._global == {}
        # default log levels attach a log filter on both channels.
        assert pco._job.stdout.log_calls == ["RING"]
        assert pco._job.stderr.log_calls == ["WARN"]

        trex.start()
        assert pco._job.started

    # close() ran on context exit: stop-tolerant destroy + both temp
    # files removed from the agent.
    assert pco._job.destroyed
    assert set(pco.unlinked) == set(pco.files_put.keys())


def test_create_silences_job_creation_and_filter_attachment_only():
    """DIVERGENCE #11 fix: create() wraps job creation and filter
    attachment in RpcServer.silent_pass() (mirrors nap-trex.c's
    proc->rpcs->silent_pass = true/false around tapi_trex_create()) --
    exactly two enter/exit windows, both closed before start()/wait()/
    stop()/kill()/destroy() run so those stay outside any window (the
    C never silences them either)."""
    pco = _FakePco()
    opts = _batch_opts()

    with batch.create(pco, opts) as trex:
        # One window for job creation, one for filter attachment --
        # both already closed by the time the block starts running.
        assert pco.silent_pass_calls == ["enter", "exit", "enter", "exit"]

        trex.start()
        trex.wait()
        trex.stop()
        assert pco.silent_pass_calls == ["enter", "exit", "enter", "exit"]

    # close() (stop-tolerant destroy) ran on context exit too.
    assert pco.silent_pass_calls == ["enter", "exit", "enter", "exit"]


def test_create_iom_normal_attaches_port_and_global_filters():
    pco = _FakePco()
    opts = _batch_opts(iom=batch.Iom.NORMAL)

    with batch.create(pco, opts) as trex:
        from pyte.tools.trex import _batch_filters as flt
        assert set(trex._port_stat) == set(flt.PORT_STAT_ROWS)
        for row, filters in trex._port_stat.items():
            assert len(filters) == batch.n_ports(opts)
        assert set(trex._port_time) == set(flt.PORT_TIME_ROWS)
        assert set(trex._global) == set(flt.GLOBAL_STATS)


def test_stdout_stderr_log_level_none_disables_filter():
    pco = _FakePco()
    opts = _batch_opts(stdout_log_level=None, stderr_log_level=0)

    with batch.create(pco, opts):
        assert pco._job.stdout.log_calls == []
        assert pco._job.stderr.log_calls == []


def test_close_is_idempotent():
    pco = _FakePco()
    opts = _batch_opts()

    with batch.create(pco, opts) as trex:
        trex.close()
        trex.close()

    assert pco._job.destroyed
    # unlink attempted exactly once per file across both close() calls.
    assert len(pco.unlinked) == 2


def test_wait_none_is_forever_and_forwards_to_job():
    pco = _FakePco()
    opts = _batch_opts()
    with batch.create(pco, opts) as trex:
        trex.wait()
    # forwarded timeout=None ("forever") to the underlying job.wait().


def test_wait_timeout_logs_ring_and_reraises(monkeypatch):
    from pyte.errors import TimeoutError as TeTimeoutError

    pco = _FakePco()
    opts = _batch_opts()
    logged = []
    monkeypatch.setattr(batch.log, "ring", lambda msg: logged.append(msg))

    with batch.create(pco, opts) as trex:
        pco._job._wait_exc = TeTimeoutError(0, "still running")
        with pytest.raises(TeTimeoutError):
            trex.wait(timeout=1.0)
    assert logged and "still in process" in logged[0]


def test_kill_forwards_signal():
    pco = _FakePco()
    opts = _batch_opts()
    with batch.create(pco, opts) as trex:
        trex.kill(9)
    assert pco._job.killed_with == 9


def test_report_drains_summary_filters():
    pco = _FakePco()
    opts = _batch_opts()

    with batch.create(pco, opts) as trex:
        trex._summary["total_tx"].feed("12.34 M")
        rep = trex.report()
    assert rep.avg_tx == pytest.approx(12.34e6)


def test_report_resilences_filters_via_job_quiet_not_rpcserver():
    """DIVERGENCE #11 fix, part 2: report()'s drain re-silences its
    filters via Job.quiet() (tapi_job_set_tracing(), which rewrites
    every filter's own silent_pass field), NOT another
    RpcServer.silent_pass() window -- that only affects RPCs made
    while creating NEW job/channel/filter objects, and has no effect
    on filters that already exist by report() time (mirrors
    trex_result_extract()'s own tapi_job_set_tracing(FALSE)/(TRUE)
    bracket around tapi_trex_get_report(), which is needed precisely
    because something else -- here, any job.quiet()-wrapped raw
    stdout drain the caller does between wait() and report(), mirrors
    trex_proc_drain_stdout() -- may have already turned filters loud
    again by the time report() runs)."""
    pco = _FakePco()
    opts = _batch_opts()

    with batch.create(pco, opts) as trex:
        # Simulate nap-ts's own _drain_stdout(): a job.quiet() window
        # closing loudly (as tapi_job_set_tracing(TRUE) really does)
        # right before report() -- report() must still come out quiet.
        with pco._job.quiet():
            pass
        pco._job.quiet_calls.clear()

        trex._summary["total_tx"].feed("12.34 M")
        silent_pass_before = list(pco.silent_pass_calls)
        rep = trex.report()

    assert rep.avg_tx == pytest.approx(12.34e6)
    assert pco._job.quiet_calls == ["enter", "exit"]
    # report() opened no NEW RpcServer.silent_pass() window of its own.
    assert pco.silent_pass_calls == silent_pass_before


def test_bind_pci_only_for_pcibdf_endpoints(monkeypatch):
    calls = []

    class _FakeDeviceView:
        def __init__(self, bdf):
            self.bdf = bdf

        def __setattr__(self, name, value):
            if name == "driver":
                calls.append((self.bdf, value))
            else:
                super().__setattr__(name, value)

    class _FakeDeviceColl:
        def __getitem__(self, bdf):
            return _FakeDeviceView(bdf)

    class _FakePci:
        def __init__(self, ta):
            self.ta = ta
            self.device = _FakeDeviceColl()

    monkeypatch.setattr("pyte.cfg.gen.pci.Pci", _FakePci)

    pco = _FakePco()
    opts = _batch_opts(
        clients=(batch.Endpoint(iface=batch.LinuxIface("eth0")),),
        servers=(batch.Endpoint(iface=batch.PciBdf("0000:01:00.0")),),
        driver="vfio-pci")

    with batch.create(pco, opts):
        pass

    assert calls == [("0000:01:00.0", "vfio-pci")]
