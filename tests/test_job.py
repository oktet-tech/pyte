# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Job helper unit tests (fake shim where one is needed)."""
import signal
import sys
import types

import pytest

from pyte.job import Filter, Job, _signo


def test_signo_accepts_int_and_stdlib_signal():
    assert _signo(9) == 9
    assert _signo(signal.SIGKILL) == int(signal.SIGKILL)
    assert _signo(signal.SIGTERM) == int(signal.SIGTERM)


def test_signo_rejects_string():
    with pytest.raises(TypeError, match="signal must be an int or signal"):
        _signo("SIGKILL")


# ---------------------------------------------------------------------------
# Fake shim (same pattern as test_mi.py / test_tester.py: SimpleNamespace
# injected as sys.modules["pyte._shim"] so job.py's lazy imports never
# touch the real compiled extension).
# ---------------------------------------------------------------------------

class FakeLib:
    """Minimal shim surface for Job.wrap()/tracing/Filter bulk reads."""

    PYTE_JOB_WRAPPER_PRIORITY_LOW     = 0
    PYTE_JOB_WRAPPER_PRIORITY_DEFAULT = 1
    PYTE_JOB_WRAPPER_PRIORITY_HIGH    = 2

    def __init__(self):
        self.calls = []
        self._wrapper = object()  # sentinel handle
        #: queued (data: bytes, eos: bool) pairs for receive_many
        self.recv_bufs = []
        self.recv_rc = 0

    def pyte_job_wrapper_add(self, job_h, tool, argv, prio, out):
        self.calls.append(("wrapper_add", job_h, bytes(tool),
                           list(argv), prio))
        out[0] = self._wrapper
        return 0

    def pyte_job_wrapper_delete(self, wrapper_h):
        self.calls.append(("wrapper_delete", wrapper_h))
        return 0

    def pyte_job_receive_many(self, flts, n, timeout_ms, max_count,
                              datas, lens, eos, count):
        self.calls.append(("receive_many", list(flts), n, timeout_ms,
                           max_count))
        bufs = self.recv_bufs if max_count == 0 \
            else self.recv_bufs[:max_count]
        datas[0] = [d for d, _ in bufs]
        lens[0] = [len(d) for d, _ in bufs]
        eos[0] = [1 if e else 0 for _, e in bufs]
        count[0] = len(bufs)
        return self.recv_rc

    def pyte_job_receive_many_free(self, datas, lens, eos, count):
        self.calls.append(("receive_many_free", datas, lens, eos, count))

    def pyte_job_set_tracing(self, job_h, trace):
        self.calls.append(("set_tracing", job_h, trace))

    # TeError construction helpers (required by pyte.errors.check())
    PYTE_ETIMEDOUT = 110

    def pyte_rc_error(self, rc):
        return rc

    def pyte_rc_module(self, rc):
        return 0

    def te_rc_mod2str(self, rc):
        return b"TAPI"

    def te_rc_err2str(self, rc):
        return b"EFAIL"


class FakeFfi:
    """Minimal cffi-like façade used by Job.wrap()/Filter bulk reads."""

    NULL = object()

    def new(self, spec, init=None):
        if spec == "char[]":
            return bytes(init)
        if spec == "const char *[]":
            return list(init)
        if spec == "tapi_job_wrapper_t **":
            return [None]
        if spec == "tapi_job_channel_t *[]":
            return list(init)
        if spec in ("char ***", "size_t **", "int **"):
            return [None]
        if spec == "unsigned int *":
            return [0]
        raise NotImplementedError(f"FakeFfi.new({spec!r})")

    @staticmethod
    def buffer(data, length):
        """Emulate ffi.buffer(ptr, len): the fake 'pointer' is bytes."""
        return data[:length]

    @staticmethod
    def string(b):
        """Emulate ffi.string(cdata): the fake cdata is already bytes."""
        return b


def _fake_shim(monkeypatch):
    lib = FakeLib()
    monkeypatch.setitem(
        sys.modules, "pyte._shim",
        types.SimpleNamespace(ffi=FakeFfi(), lib=lib))
    return lib


def _fake_job(handle=object()):
    """A Job with a dummy handle, bypassing shim-backed create()."""
    return Job(None, handle, "prog")


def test_job_wrap_marshalling(monkeypatch):
    """wrap() duplicates the tool as argv[0] and NULL-terminates argv."""
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    w = job.wrap("onload", ["--profile=x"])
    assert lib.calls == [
        ("wrapper_add", "job-h", b"onload",
         [b"onload", b"--profile=x", FakeFfi.NULL],
         lib.PYTE_JOB_WRAPPER_PRIORITY_DEFAULT),
    ]
    assert w._h is lib._wrapper
    assert w._job is job


def test_job_wrap_invalid_priority(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job()
    with pytest.raises(ValueError,
                       match="priority must be 'low', 'default' or 'high'"):
        job.wrap("onload", priority="urgent")
    assert lib.calls == []


def test_wrapper_delete_idempotent_and_guarded(monkeypatch):
    """delete() calls the shim once; no-op after job destruction."""
    lib = _fake_shim(monkeypatch)
    job = _fake_job()
    w = job.wrap("valgrind")
    lib.calls.clear()

    w.delete()
    w.delete()  # idempotent: second call must not reach the shim
    assert lib.calls == [("wrapper_delete", lib._wrapper)]

    w2 = job.wrap("strace")
    lib.calls.clear()
    job._h = None  # as Job.destroy() leaves it
    w2.delete()  # owning job gone: TE freed the wrapper already
    assert lib.calls == []


# ---------------------------------------------------------------------------
# Filter.drain() / Filter.read_many() — shim-backed bulk reads
# ---------------------------------------------------------------------------

def _fake_filter(lib, handle="flt-h"):
    return Filter(_fake_job(handle="job-h"), handle, "out")


def test_drain_reads_all_in_one_call(monkeypatch):
    """drain() makes ONE receive_many call (max_count=0 = all queued),
    consumes eos entries without returning them."""
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_bufs = [(b"line1\n", False), (b"line2\n", False), (b"", True)]

    msgs = flt.drain(timeout=3.0)

    recv = [c for c in lib.calls if c[0] == "receive_many"]
    assert recv == [("receive_many", ["flt-h"], 1, 3000, 0)]
    assert [m.data for m in msgs] == ["line1\n", "line2\n"]
    assert all(not m.eos for m in msgs)
    assert all(m.filter is flt for m in msgs)


def test_drain_frees_shim_arrays(monkeypatch):
    """drain() hands the out-arrays back to pyte_job_receive_many_free."""
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_bufs = [(b"x", False), (b"", True)]

    flt.drain()

    frees = [c for c in lib.calls if c[0] == "receive_many_free"]
    assert len(frees) == 1
    assert frees[0][1:] == ([b"x", b""], [1, 0], [0, 1], 2)


def test_drain_empty_queue(monkeypatch):
    """drain() with nothing queued returns an empty list."""
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_bufs = []

    assert flt.drain() == []


def test_read_many_limits_count_single_call(monkeypatch):
    """read_many(2) passes max_count=2 to ONE receive_many call."""
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_bufs = [(b"a", False), (b"b", False), (b"c", False)]

    msgs = flt.read_many(2, timeout=3.0)

    recv = [c for c in lib.calls if c[0] == "receive_many"]
    assert recv == [("receive_many", ["flt-h"], 1, 3000, 2)]
    assert [m.data for m in msgs] == ["a", "b"]


def test_read_many_error_no_free(monkeypatch):
    """When pyte_job_receive_many returns non-zero, check() raises and
    pyte_job_receive_many_free is NOT called (the shim freed server-side)."""
    from pyte.errors import TeError
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_bufs = [(b"x", False)]
    lib.recv_rc = 12  # TE_ENOENT — any non-zero te_errno

    with pytest.raises(TeError):
        flt.read_many(0)

    frees = [c for c in lib.calls if c[0] == "receive_many_free"]
    assert frees == [], "receive_many_free must not be called when rc != 0"


# ---------------------------------------------------------------------------
# Job.tracing() / Job.quiet()
# ---------------------------------------------------------------------------

def test_tracing_calls_shim(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")

    job.tracing(False)
    job.tracing(True)

    assert lib.calls == [("set_tracing", "job-h", 0),
                         ("set_tracing", "job-h", 1)]


def test_quiet_toggles_tracing(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")

    with job.quiet() as j:
        assert j is job
        assert lib.calls == [("set_tracing", "job-h", 0)]
    assert lib.calls == [("set_tracing", "job-h", 0),
                         ("set_tracing", "job-h", 1)]


def test_quiet_restores_tracing_on_exception(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")

    with pytest.raises(RuntimeError, match="boom"):
        with job.quiet():
            raise RuntimeError("boom")
    assert lib.calls == [("set_tracing", "job-h", 0),
                         ("set_tracing", "job-h", 1)]


def test_tracing_noop_after_destroy(monkeypatch):
    """tracing() after destroy() is a no-op — no crash, no shim call."""
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")

    job._h = None  # simulate destroy()
    job.tracing(False)
    job.tracing(True)

    assert lib.calls == []


def test_quiet_noop_after_destroy(monkeypatch):
    """quiet() whose finally fires after destroy() must not call the shim.

    The context manager's finally block calls tracing(True); with the
    NULL guard that restore is silently skipped.  Two scenarios:
      1. destroy() called inside the with-block.
      2. destroy() called before entering quiet() at all.
    """
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")

    # Scenario 1: destroy() inside the quiet() block
    with job.quiet():
        assert lib.calls == [("set_tracing", "job-h", 0)]
        job._h = None  # simulate destroy() mid-block
    # finally: tracing(True) fires but _h is None → no additional shim call
    assert lib.calls == [("set_tracing", "job-h", 0)]

    # Scenario 2: quiet() entered when already destroyed
    lib.calls.clear()
    job2 = _fake_job(handle="job2-h")
    job2._h = None  # destroyed before entering quiet()
    with job2.quiet():
        pass
    assert lib.calls == []
