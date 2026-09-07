# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools._tool / _units shared-helper unit tests (offline)."""
import enum

import pytest

from pyte.tools import _tool, _units


# -- argv builders ------------------------------------------------------

def test_opt_emits_flag_value_pair():
    assert _tool.opt("-p", 8080) == ["-p", "8080"]
    assert _tool.opt("-t", "tcp") == ["-t", "tcp"]


def test_opt_none_emits_nothing():
    assert _tool.opt("-p", None) == []


def test_opt_eq_emits_joined_form():
    assert _tool.opt_eq("--threads=", 4) == ["--threads=4"]
    assert _tool.opt_eq("--key-prefix=", "k") == ["--key-prefix=k"]
    assert _tool.opt_eq("--requests=", None) == []


def test_switch_emits_flag_when_on():
    assert _tool.switch("-D", True) == ["-D"]
    assert _tool.switch("-D", False) == []
    assert _tool.switch("--random-data", None) == []


def test_suffixed_appends_unit():
    assert _tool.suffixed("--time=", 30, "s") == ["--time=30s"]
    assert _tool.suffixed("--time=", None, "s") == []


def test_builders_compose_argv_in_explicit_order():
    argv = [*_tool.opt("-p", 1), *_tool.switch("-D", True),
            *_tool.opt_eq("--x=", None), *_tool.opt("-c", 4)]
    assert argv == ["-p", "1", "-D", "-c", "4"]


# -- coerce_enum (promoted from fio) -----------------------------------

class Mode(enum.Enum):
    READ = "read"
    RANDWRITE = "randwrite"


def test_coerce_enum_passthrough_and_string():
    assert _tool.coerce_enum(Mode, "mode", Mode.READ) is Mode.READ
    assert _tool.coerce_enum(Mode, "mode", "read") is Mode.READ
    assert _tool.coerce_enum(Mode, "mode", "RANDWRITE") is Mode.RANDWRITE


def test_coerce_enum_bad_name_lists_valid():
    with pytest.raises(ValueError, match="randwrite"):
        _tool.coerce_enum(Mode, "mode", "sideways")


def test_coerce_enum_bad_type():
    with pytest.raises(TypeError, match="mode must be Mode or str"):
        _tool.coerce_enum(Mode, "mode", 3)


# -- address helpers (promoted from memcached/memaslap) -----------------

class _Addr:
    """Duck-typed pyte.env.Addr: exposes .pair."""

    def __init__(self, host, port):
        self.pair = (host, port)


def test_addr_host_port_accepts_tuple_and_addr():
    assert _tool.addr_host_port(("10.0.0.1", 11211)) == ("10.0.0.1", 11211)
    assert _tool.addr_host_port(_Addr("h", 5)) == ("h", 5)


def test_addr_host_port_rejects_bare_port():
    with pytest.raises(TypeError, match="host"):
        _tool.addr_host_port(11211)


def test_addr_port_accepts_int_tuple_and_addr():
    assert _tool.addr_port(11211) == 11211
    assert _tool.addr_port(("10.0.0.1", 11211)) == 11211
    assert _tool.addr_port(_Addr("h", 5)) == 5


# -- ipversion validation (dedup of three frozenset copies) -------------

def test_check_ipversion_accepts_4_6_none():
    _tool.check_ipversion(None)
    _tool.check_ipversion("4")
    _tool.check_ipversion("6")


def test_check_ipversion_rejects_others():
    with pytest.raises(ValueError, match="ipversion"):
        _tool.check_ipversion("5")
    with pytest.raises(ValueError, match="ipversion"):
        _tool.check_ipversion(4)      # int is not the tool flag form


# -- unit parsing (promoted from wrk/fio) --------------------------------

def test_parse_unit_time():
    assert _units.parse_unit("456.78us", _units.TIME_US) == 456.78
    assert _units.parse_unit("2.50ms", _units.TIME_US) == 2500.0
    assert _units.parse_unit("1.5s", _units.TIME_US) == 1.5e6


def test_parse_unit_metric_binary_percent():
    assert _units.parse_unit("12.34k", _units.METRIC) == 12340.0
    assert _units.parse_unit("3.50M", _units.BINARY) == 3.5 * 1024 ** 2
    assert _units.parse_unit("89.00%", _units.TIME_US) == 89.0


def test_parse_unit_unknown_suffix():
    with pytest.raises(ValueError, match="unknown unit"):
        _units.parse_unit("3fortnights", _units.TIME_US)


def test_parse_size_fio_semantics():
    assert _units.parse_size(None) is None
    assert _units.parse_size(4096) == 4096
    assert _units.parse_size("4k") == 4096
    assert _units.parse_size("16M") == 16 * 1024 ** 2
    assert _units.parse_size("1g") == 1024 ** 3


def test_parse_size_rejects_bad_input():
    with pytest.raises(ValueError):
        _units.parse_size("1.5g")     # whole numbers only
    with pytest.raises(ValueError):
        _units.parse_size("4x")
    with pytest.raises(ValueError):
        _units.parse_size(0)
    with pytest.raises(ValueError):
        _units.parse_size("-4k")


# -- ToolHandle: shared lifecycle with per-tool hooks --------------------

from pyte.errors import TeError, ToolError  # noqa: E402
from pyte.job import JobStatus, StatusKind  # noqa: E402

OK = JobStatus(StatusKind.EXITED, 0)
BAD = JobStatus(StatusKind.EXITED, 3)


class FakeJob:
    def __init__(self, status=OK, stop_error=False):
        self.status = status
        self.stop_error = stop_error
        self.events = []

    def wait(self, timeout=None):
        self.events.append(("wait", timeout))
        return self.status

    def start(self):
        self.events.append(("start",))

    def stop(self, *a, **k):
        self.events.append(("stop",))
        if self.stop_error:
            raise TeError(12)

    def destroy(self, *a, **k):
        self.events.append(("destroy",))


class FakeFilter:
    def __init__(self, text="raw output"):
        self.text = text
        self.reads = 0

    def read_all(self, timeout=None):
        self.reads += 1
        return self.text


class DemoError(ToolError):
    """demo tool failed."""


class Demo(_tool.ToolHandle):
    tool = "demo"
    error_cls = DemoError
    default_timeout = 33.0

    def _parse(self, raw):
        if "garbage" in raw:
            raise DemoError(f"cannot parse: {raw!r}")
        return {"parsed": raw}


def test_wait_parses_and_caches():
    job, flt = FakeJob(), FakeFilter("data")
    h = Demo(job, flt)
    assert h.wait() == {"parsed": "data"}
    assert h.wait() == {"parsed": "data"}
    assert flt.reads == 1                      # cached, no second read
    assert job.events[0] == ("wait", 33.0)     # class default timeout


def test_parse_first_reports_status_when_parse_fails():
    h = Demo(FakeJob(status=BAD), FakeFilter("garbage"))
    with pytest.raises(DemoError, match="exited with"):
        h.wait()


def test_parse_first_propagates_parse_error_on_ok_exit():
    h = Demo(FakeJob(status=OK), FakeFilter("garbage"))
    with pytest.raises(DemoError, match="cannot parse"):
        h.wait()


def test_parse_first_default_check_raises_on_bad_exit():
    """Parse succeeded but the run failed: default policy raises."""
    h = Demo(FakeJob(status=BAD), FakeFilter("data"))
    with pytest.raises(DemoError, match="exited with"):
        h.wait()


def test_check_status_hook_can_tolerate_bad_exit():
    """ping's 100%-loss case: parseable output on a non-zero exit."""
    class Tolerant(Demo):
        def _check_status(self, status, raw):
            pass

    h = Tolerant(FakeJob(status=BAD), FakeFilter("data"))
    assert h.wait() == {"parsed": "data"}


def test_status_first_raises_before_parse():
    class Json(Demo):
        wait_policy = "status-first"

        def _parse(self, raw):
            raise AssertionError("must not parse a failed run")

    h = Json(FakeJob(status=BAD), FakeFilter("whatever"))
    with pytest.raises(DemoError, match="exited with"):
        h.wait()


def test_read_output_hook_feeds_parse():
    """Tools that read via messages()/regex filters override the read."""
    class Rows(Demo):
        def _read_output(self, timeout):
            return ["row1", "row2"]

        def _parse(self, rows):
            return rows

    h = Rows(FakeJob(), None)          # no stdout filter needed
    assert h.wait() == ["row1", "row2"]


def test_wait_silent_checks_status_only():
    h = Demo(FakeJob(status=BAD), FakeFilter())
    with pytest.raises(DemoError, match="exited with"):
        h.wait_silent()
    Demo(FakeJob(), FakeFilter()).wait_silent()    # ok run: no raise


def test_close_stops_destroys_idempotent():
    job = FakeJob(stop_error=True)     # stop failure tolerated
    h = Demo(job, FakeFilter())
    h.close()
    h.close()
    assert job.events == [("stop",), ("destroy",)]


def test_close_hooks_overridable():
    events = []

    class Custom(Demo):
        def _stop_for_close(self):
            events.append("custom-stop")

        def _after_close(self):
            events.append("after")

    job = FakeJob()
    Custom(job, FakeFilter()).close()
    assert events == ["custom-stop", "after"]
    assert job.events == [("destroy",)]


def test_mi_report_auto_waits(monkeypatch):
    """mi_report() no longer demands a prior wait() call."""
    import pyte.mi

    class FakeLogger:
        def __init__(self, tool):
            self.tool = tool
            self.adds = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(pyte.mi, "Logger", FakeLogger)
    seen = []

    class WithMi(Demo):
        def _mi(self, logger, rep):
            seen.append((logger.tool, rep))

    WithMi(FakeJob(), FakeFilter("data")).mi_report()
    assert seen == [("demo", {"parsed": "data"})]


# -- launch()/running(): the hardened job bring-up ------------------------

class FakePco:
    def __init__(self, job):
        self._job = job
        self.created = None

    def job(self, program, args=None):
        self.created = (program, args)
        return self._job


def test_launch_creates_sets_up_starts():
    job = FakeJob()
    pco = FakePco(job)

    got_job, extras = _tool.launch(
        pco, "fio", ["--a"],
        setup=lambda j: (j.events.append(("setup",)), {"flt": "s"})[1])

    assert got_job is job and extras == {"flt": "s"}
    assert pco.created == ("fio", ["--a"])
    # setup (filter attachment) must run BEFORE start
    assert job.events == [("setup",), ("start",)]


def test_launch_destroys_on_setup_failure():
    job = FakeJob()

    def boom(j):
        raise RuntimeError("attach failed")

    with pytest.raises(RuntimeError, match="attach failed"):
        _tool.launch(FakePco(job), "t", [], setup=boom)
    assert job.events == [("destroy",)]


def test_launch_destroys_on_start_failure():
    class NoStartJob(FakeJob):
        def start(self):
            raise TeError(12)

    job = NoStartJob()
    with pytest.raises(TeError):
        _tool.launch(FakePco(job), "t", [])
    assert job.events == [("destroy",)]


def test_launch_preserves_body_error_when_destroy_also_fails():
    """A destroy() failure during launch() teardown must not replace
    the real bring-up failure (start() here)."""
    boom = RuntimeError("bring-up failed")

    class NoStartFlakyDestroy(FakeJob):
        def start(self):
            raise boom

        def destroy(self, *a, **k):
            self.events.append(("destroy",))
            raise RuntimeError("destroy failed")

    job = NoStartFlakyDestroy()
    with pytest.raises(RuntimeError) as info:
        _tool.launch(FakePco(job), "t", [])
    assert info.value is boom            # identity, not a message match
    assert info.value.cleanup_errors     # destroy failure attached
    assert job.events == [("destroy",)]


def test_running_closes_on_exit_and_exception():
    class H:
        closed = 0

        def close(self):
            self.closed += 1

    h = H()
    with _tool.running(h) as got:
        assert got is h
    assert h.closed == 1

    h2 = H()
    with pytest.raises(RuntimeError, match="body"):
        with _tool.running(h2):
            raise RuntimeError("body failed")
    assert h2.closed == 1


def test_wait_shares_one_deadline_across_wait_and_read(monkeypatch):
    """P1.5: a 30 s wait() must not spend 30 s in job.wait and then
    ANOTHER 30 s reading output — the read gets the remaining budget."""
    import itertools

    ticks = itertools.chain([0.0, 20.0], itertools.repeat(20.0))
    monkeypatch.setattr(_tool.time, "monotonic", lambda: next(ticks))

    reads = []

    class F:
        def read_all(self, timeout=None):
            reads.append(timeout)
            return "data"

    Demo(FakeJob(), F()).wait(timeout=30.0)
    assert reads == [10.0]     # 30 - 20 consumed by job.wait


def test_wait_none_timeout_blocks_everywhere():
    reads = []

    class F:
        def read_all(self, timeout="unset"):
            reads.append(timeout)
            return "data"

    job = FakeJob()
    Demo(job, F()).wait(timeout=None)
    assert job.events[0] == ("wait", None)
    assert reads == [None]


# -- close(): retryable, non-masking teardown ----------------------------

class _FlakyJob(FakeJob):
    """FakeJob whose destroy() fails until told otherwise."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.destroy_fails = True
        self.destroys = 0

    def destroy(self, *a, **k):
        self.destroys += 1
        self.events.append(("destroy",))
        if self.destroy_fails:
            raise TeError(12)


def test_failed_close_can_be_retried():
    job = _FlakyJob()
    handle = Demo(job, FakeFilter())
    with pytest.raises(TeError):
        handle.close()
    job.destroy_fails = False
    handle.close()
    assert job.destroys == 2      # actually retried


def test_close_runs_after_close_even_if_destroy_fails():
    job = _FlakyJob()
    handle = Demo(job, FakeFilter())
    ran = []
    handle._after_close = lambda: ran.append("after")
    with pytest.raises(TeError):
        handle.close()
    assert ran == ["after"]


def test_successful_close_is_still_idempotent():
    job = FakeJob()
    handle = Demo(job, FakeFilter())
    handle.close()
    handle.close()
    assert [e for e in job.events if e == ("destroy",)] == [("destroy",)]


def test_running_does_not_mask_the_body_error():
    """running() is the tail of every tool run() CM: a failing close()
    must not replace the exception the block raised."""
    class _FailingCloseHandle:
        def __init__(self):
            self.closed = 0

        def close(self):
            self.closed += 1
            raise RuntimeError("close failed")

    handle = _FailingCloseHandle()
    boom = RuntimeError("BODY BOOM")
    with pytest.raises(RuntimeError) as info:
        with _tool.running(handle):
            raise boom
    assert info.value is boom            # identity, not a message match
    assert info.value.cleanup_errors     # close failure attached
    assert handle.closed == 1            # close still ran


def test_running_still_raises_a_close_failure_on_a_clean_block():
    """With nothing to mask, a failing close() must still surface."""
    class _FailingCloseHandle:
        def close(self):
            raise RuntimeError("close failed")

    with pytest.raises(RuntimeError, match="close failed"):
        with _tool.running(_FailingCloseHandle()):
            pass
