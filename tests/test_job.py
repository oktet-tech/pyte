# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Job helper unit tests (fake shim where one is needed)."""
import signal
import sys
import types

import pytest

from pyte.job import Job, _signo


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
    """Minimal shim surface that Job.wrap()/Wrapper.delete() use."""

    PYTE_JOB_WRAPPER_PRIORITY_LOW     = 0
    PYTE_JOB_WRAPPER_PRIORITY_DEFAULT = 1
    PYTE_JOB_WRAPPER_PRIORITY_HIGH    = 2

    def __init__(self):
        self.calls = []
        self._wrapper = object()  # sentinel handle

    def pyte_job_wrapper_add(self, job_h, tool, argv, prio, out):
        self.calls.append(("wrapper_add", job_h, bytes(tool),
                           list(argv), prio))
        out[0] = self._wrapper
        return 0

    def pyte_job_wrapper_delete(self, wrapper_h):
        self.calls.append(("wrapper_delete", wrapper_h))
        return 0


class FakeFfi:
    """Minimal cffi-like façade used by Job.wrap()."""

    NULL = object()

    def new(self, spec, init=None):
        if spec == "char[]":
            return bytes(init)
        if spec == "const char *[]":
            return list(init)
        if spec == "tapi_job_wrapper_t **":
            return [None]
        raise NotImplementedError(f"FakeFfi.new({spec!r})")


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
