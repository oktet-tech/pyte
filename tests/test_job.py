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
        #: queued (data: bytes, eos: bool) pairs for single receive
        self.recv_queue = []

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

    def pyte_job_receive(self, arr, n, timeout_ms, last,
                         data, dlen, eos, dropped, src):
        self.calls.append(("receive", list(arr), timeout_ms))
        chunk, is_eos = self.recv_queue.pop(0)
        data[0] = chunk
        dlen[0] = len(chunk)
        eos[0] = 1 if is_eos else 0
        dropped[0] = 0
        src[0] = arr[0]
        return 0

    def pyte_free_string(self, p):
        self.calls.append(("free_string",))

    def pyte_job_set_tracing(self, job_h, trace):
        self.calls.append(("set_tracing", job_h, trace))

    def pyte_job_destroy(self, job_h, timeout_ms):
        self.calls.append(("destroy", job_h, timeout_ms))
        return 0

    def pyte_job_out_channels(self, job_h, o, e):
        self.calls.append(("out_channels", job_h))
        o[0] = "out-h"
        e[0] = "err-h"
        return 0

    def pyte_job_in_channel(self, job_h, i):
        self.calls.append(("in_channel", job_h))
        i[0] = "in-h"
        return 0

    def pyte_job_attach_filter(self, arr, n, name, readable, level, out):
        self.calls.append(("attach_filter", list(arr), n, readable, level))
        out[0] = "flt-h"
        return 0

    def pyte_job_filter_remove(self, flt_h, arr, n):
        self.calls.append(("filter_remove", flt_h, list(arr), n))
        return 0

    def pyte_job_send(self, chan_h, raw, length):
        self.calls.append(("send", chan_h, bytes(raw), length))
        return 0

    def pyte_job_factory_rpc(self, srv_h, fac):
        self.calls.append(("factory_rpc", srv_h))
        fac[0] = "fac-h"
        return 0

    def pyte_job_create(self, fac_h, program, argv, envp, out):
        self.calls.append(("create", fac_h, bytes(program)))
        out[0] = "job-h"
        return 0

    def pyte_job_factory_destroy(self, fac_h):
        self.calls.append(("factory_destroy", fac_h))
        return 0

    def pyte_job_start(self, job_h):
        self.calls.append(("start", job_h))
        return 0

    def pyte_job_stop(self, job_h, signo, timeout_ms):
        self.calls.append(("stop", job_h, signo, timeout_ms))
        return 0

    def pyte_job_kill(self, job_h, signo):
        self.calls.append(("kill", job_h, signo))
        return 0

    PYTE_JOB_EXITED = 1
    PYTE_JOB_SIGNALED = 2
    PYTE_EINPROGRESS = 114
    TE_LL_RING = 4
    TE_LL_WARN = 3
    #: (otype, oval) reported by pyte_job_wait
    wait_result = (PYTE_JOB_EXITED, 0)

    def pyte_job_wait(self, job_h, timeout_ms, otype, oval):
        self.calls.append(("wait", job_h, timeout_ms))
        otype[0], oval[0] = self.wait_result
        return 0

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
        if spec in ("tapi_job_wrapper_t **", "tapi_job_factory_t **",
                    "tapi_job_t **"):
            return [None]
        if spec == "tapi_job_channel_t *[]":
            return list(init)
        if spec == "tapi_job_channel_t **":
            return [None]
        if spec in ("char ***", "size_t **", "int **", "char **"):
            return [None]
        if spec in ("unsigned int *", "size_t *", "int *"):
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
# UTF-8 across chunk boundaries: filter messages are arbitrary stream
# chunks (agent pipe-read boundaries), so a multibyte character can be
# split between two messages.  read_all() must join the raw bytes and
# decode ONCE; per-message .data decoding is inherently lossy at the
# boundary and is documented as such.
# ---------------------------------------------------------------------------

def test_read_all_decodes_across_chunk_boundaries(monkeypatch):
    """b"caf\\xc3" + b"\\xa9!" is valid UTF-8 "café!" once joined."""
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_queue = [(b"caf\xc3", False), (b"\xa9!", False), (b"", True)]

    assert flt.read_all() == "café!"


def test_message_exposes_raw_bytes(monkeypatch):
    """JobMessage carries the exact received bytes; .data decodes this
    message's bytes alone (U+FFFD at a split boundary)."""
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_queue = [(b"caf\xc3", False)]

    msg = flt.receive()

    assert msg.raw == b"caf\xc3"
    assert msg.data == "caf�"


def test_read_many_preserves_raw_bytes(monkeypatch):
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_bufs = [(b"a\xc3", False), (b"\xa9b", False), (b"", True)]

    msgs = flt.read_many(0)

    assert [m.raw for m in msgs] == [b"a\xc3", b"\xa9b"]
    assert b"".join(m.raw for m in msgs).decode() == "aéb"


# ---------------------------------------------------------------------------
# Use-after-destroy guards: a destroyed job (and its channels/filters)
# must raise a clear RuntimeError, never pass a NULL handle into C
# (pyte_shim passes handles straight to tapi_job_* which dereferences).
# ---------------------------------------------------------------------------

def test_lifecycle_methods_raise_after_destroy(monkeypatch):
    """start/wait/stop/kill/wrap on a destroyed job raise, no shim call."""
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    job.destroy()
    lib.calls.clear()

    for op in (job.start,
               job.wait,
               job.stop,
               job.kill,
               lambda: job.wrap("strace")):
        with pytest.raises(RuntimeError, match="destroyed"):
            op()
    assert lib.calls == []


def test_channel_allocation_raises_after_destroy(monkeypatch):
    """stdout/stderr/stdin properties on a destroyed job raise."""
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    job.destroy()
    lib.calls.clear()

    for prop in ("stdout", "stderr", "stdin"):
        with pytest.raises(RuntimeError, match="destroyed"):
            getattr(job, prop)
    assert lib.calls == []


def test_destroy_invalidates_held_channels_and_filters(monkeypatch):
    """Channel/Filter/InputChannel objects held across destroy() raise
    instead of passing dangling pointers into C."""
    from pyte.job import receive_any
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    out = job.stdout
    stdin = job.stdin
    flt = out.attach_filter(name="f")
    job.destroy()
    lib.calls.clear()

    with pytest.raises(RuntimeError, match="destroyed"):
        stdin.send("data")
    with pytest.raises(RuntimeError, match="destroyed"):
        out.attach_filter(name="g")
    with pytest.raises(RuntimeError, match="destroyed"):
        flt.receive()
    with pytest.raises(RuntimeError, match="destroyed"):
        flt.read_many(0)
    with pytest.raises(RuntimeError, match="destroyed"):
        receive_any([flt])
    assert lib.calls == []


def test_destroy_remains_idempotent(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    job.destroy()
    lib.calls.clear()
    job.destroy()   # second destroy: no shim call, no error
    assert lib.calls == []


def test_filter_detached_from_all_channels_is_dead(monkeypatch):
    """Once detach() drops the last channel, TAPI frees the filter;
    the Python object must refuse further use instead of crashing."""
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    out = job.stdout
    flt = out.attach_filter(name="f")

    flt.detach(out)
    lib.calls.clear()

    with pytest.raises(RuntimeError, match="detached|destroyed"):
        flt.receive()
    assert lib.calls == []


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


# ---------------------------------------------------------------------------
# Timeout convention (P1.5): float | None, None = block forever (-1 ms);
# negatives rejected instead of silently meaning "forever" in C.
# ---------------------------------------------------------------------------

def test_ms_none_means_block_forever():
    from pyte.job import _ms
    assert _ms(None) == -1
    assert _ms(2.5) == 2500


def test_ms_rejects_negative():
    from pyte.job import _ms
    with pytest.raises(ValueError, match="negative"):
        _ms(-3)


def test_drain_defaults_to_no_wait(monkeypatch):
    """drain() means "what's queued NOW": it must not inherit the 10 s
    first-message wait (a drain of an empty queue blocked 10 seconds)."""
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_bufs = []
    flt.drain()
    recv = [c for c in lib.calls if c[0] == "receive_many"]
    assert recv == [("receive_many", ["flt-h"], 1, 0, 0)]


# ---------------------------------------------------------------------------
# One-shot run: Job.run() = start + wait; module-level run() is the
# subprocess.run() of tapi_job (create, capture, start, wait, destroy).
# ---------------------------------------------------------------------------

def test_job_run_starts_and_waits(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")

    status = job.run(timeout=2.0)

    assert status.ok
    assert lib.calls == [("start", "job-h"), ("wait", "job-h", 2000)]


def test_run_one_shot_captures_output(monkeypatch):
    """run() returns a CompletedJob with status and both streams; the
    job (and its factory) are destroyed before it returns."""
    from pyte.job import run
    lib = _fake_shim(monkeypatch)
    server = types.SimpleNamespace(_h="srv-h", name="pco")
    # stdout read_all() drains first, then stderr
    lib.recv_queue = [(b"out!", False), (b"", True),
                      (b"err!", False), (b"", True)]

    result = run(server, "prog", ["arg"], timeout=5.0)

    assert result.ok and result.status.ok
    assert result.stdout == "out!"
    assert result.stderr == "err!"
    names = [c[0] for c in lib.calls]
    assert names.index("start") < names.index("wait")
    assert "destroy" in names and "factory_destroy" in names


def test_run_one_shot_reports_failure_status(monkeypatch):
    """A non-zero exit is a result, not an exception (subprocess.run
    parity without check=True)."""
    from pyte.job import run, StatusKind
    lib = _fake_shim(monkeypatch)
    lib.wait_result = (FakeLib.PYTE_JOB_EXITED, 3)
    server = types.SimpleNamespace(_h="srv-h", name="pco")
    lib.recv_queue = [(b"", True), (b"", True)]

    result = run(server, "prog")

    assert not result.ok
    assert result.status.kind is StatusKind.EXITED
    assert result.status.value == 3


# ---------------------------------------------------------------------------
# stdin allocate-before-start: a stdin channel allocated after the
# process was spawned is not bound to it; TE only reports that later,
# as a cryptic TE_EBADFD from send().  Fail fast at allocation instead.
# ---------------------------------------------------------------------------

def test_stdin_after_start_raises(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    job.start()
    lib.calls.clear()

    with pytest.raises(RuntimeError, match="before start"):
        job.stdin
    assert lib.calls == [], "no channel must be allocated for a live process"


def test_stdin_allocated_before_start_stays_usable(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    stdin = job.stdin
    job.start()

    assert job.stdin is stdin       # property still returns the channel
    stdin.send("ok\n")
    assert ("send", "in-h", b"ok\n", 3) in lib.calls


def test_create_with_stdin_kwarg_allocates_upfront(monkeypatch):
    """Job.create(..., stdin=True) allocates the input channel at
    creation, before any chance to start() — no ordering footgun."""
    lib = _fake_shim(monkeypatch)
    server = types.SimpleNamespace(_h="srv-h", name="pco")

    job = Job.create(server, "cat", [], stdin=True)

    assert ("in_channel", "job-h") in lib.calls
    job.start()
    job.stdin.send("x")             # allocated: no RuntimeError
    assert ("send", "in-h", b"x", 1) in lib.calls


def test_channel_log_defaults_to_ring(monkeypatch):
    """log() attaches an unreadable filter at RING level by default."""
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")

    job.stdout.log()
    job.stderr.log(level="WARN")

    attaches = [c for c in lib.calls if c[0] == "attach_filter"]
    assert [(c[3], c[4]) for c in attaches] == \
        [(0, lib.TE_LL_RING), (0, lib.TE_LL_WARN)]


def test_filter_receive_reads_next_message(monkeypatch):
    """receive() pops the next queued message (renamed from next():
    the old name faked the Python-2 iterator spelling without
    implementing the protocol — next(flt) failed while flt.next()
    worked)."""
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_queue = [(b"hello\n", False)]

    msg = flt.receive(timeout=2.0)

    assert msg.data == "hello\n"
    assert not msg.eos
    assert not hasattr(flt, "next"), \
        "next() must be gone: it shadowed the iterator protocol"


def test_filter_is_iterable(monkeypatch):
    """for msg in flt: iterates messages until end-of-stream."""
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_queue = [(b"a", False), (b"b", False), (b"", True)]

    assert [m.data for m in flt] == ["a", "b"]


def test_wait_accepts_none(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")

    def wait_ok(h, ms, otype, oval):
        lib.calls.append(("job_wait", ms))
        otype[0] = lib.PYTE_JOB_EXITED
        oval[0] = 0
        return 0
    lib.pyte_job_wait = wait_ok
    lib.PYTE_JOB_EXITED = 1
    lib.PYTE_JOB_SIGNALED = 2
    lib.PYTE_EINPROGRESS = 114

    job.wait(timeout=None)
    assert ("job_wait", -1) in lib.calls
