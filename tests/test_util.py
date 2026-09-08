# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte._util: shim accessors and agent-side traceback recovery.

The shim accessors must resolve through sys.modules; the traceback
helpers must recover a remote traceback from an exception chain
without ever raising themselves.
"""
import sys
import traceback
import types

from pyte import _util
from pyte.errors import RemotePythonError


def test_shim_resolves_injected_fake(monkeypatch):
    """Fake-shim injection (the whole unit-test strategy) must keep
    working through the accessor: it resolves via sys.modules at call
    time, not via the pyte package attribute."""
    fake = types.SimpleNamespace(ffi="fake-ffi", lib="fake-lib")
    monkeypatch.setitem(sys.modules, "pyte._shim", fake)
    assert _util.shim() == ("fake-ffi", "fake-lib")
    assert _util.shim_lib() == "fake-lib"


def test_shim_sees_replacement_per_call(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=1, lib=1))
    assert _util.shim() == (1, 1)
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=2, lib=2))
    assert _util.shim() == (2, 2)


def test_enc_never_raises():
    assert _util.enc("café") == "café".encode()
    assert _util.enc("\udcff") == b"\\udcff"    # backslashreplace


def test_take_str_decodes_frees_and_nulls(monkeypatch):
    freed = []

    class Ffi:
        NULL = object()

        @staticmethod
        def string(b):
            return b

    class Lib:
        @staticmethod
        def pyte_free_string(p):
            freed.append(p)

    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=Ffi(), lib=Lib()))
    out = [b"hello"]
    assert _util.take_str(out) == "hello"
    assert freed == [b"hello"]
    assert out[0] is Ffi.NULL


# -- agent-side traceback recovery -----------------------------------
#
# pyte.remote keeps the remote traceback in the exception attribute
# and out of the message, so it must be recovered from the chain
# wherever the failure is finally reported.

#: Stand-in agent-side traceback texts.  Held in constants, not
#: inlined at the raise: a literal there is echoed by
#: traceback.format_exc() as the failing source line, which would let
#: a "printed once" assertion pass (or fail) for the wrong reason.
TB_A = "Traceback (agent):\n  op(); RuntimeError: A"
TB_B = "Traceback (agent):\n  op(); RuntimeError: B"


def _remote(msg: str, tb: str) -> RemotePythonError:
    return RemotePythonError(msg, remote_traceback=tb)


def test_remote_traceback_found_through_a_cause_chain():
    """`raise TrexError(...) from exc` is what the TRex client does."""
    try:
        try:
            raise _remote("remote KeyError: 'k'", TB_A)
        except RemotePythonError as exc:
            raise RuntimeError("op failed") from exc
    except RuntimeError as outer:
        assert outer.__cause__ is not None
        assert _util.remote_tracebacks(outer) == [TB_A]
    # `raise ... from` inside an `except` sets BOTH edges, so the
    # above passes even for a walk that follows __context__ alone:
    # the cause edge needs a chain that has nothing else.
    lone = RuntimeError("op failed")
    lone.__cause__ = _remote("remote KeyError: 'k'", TB_A)
    assert lone.__context__ is None
    assert _util.remote_tracebacks(lone) == [TB_A]


def test_remote_traceback_found_through_a_context_chain():
    """An exception raised inside `except` without `from` chains
    through __context__ only; both shapes occur in the tree."""
    try:
        try:
            raise _remote("remote KeyError: 'k'", TB_A)
        except RemotePythonError:
            raise RuntimeError("op failed")
    except RuntimeError as outer:
        assert outer.__cause__ is None
        assert _util.remote_tracebacks(outer) == [TB_A]


def test_remote_traceback_found_through_a_mixed_chain():
    """A cause edge above a context edge: following one kind only
    would miss the remote error."""
    inner = _remote("remote ValueError: bad", TB_A)
    middle = RuntimeError("op failed")
    middle.__context__ = inner
    outer = RuntimeError("test step failed")
    outer.__cause__ = middle
    assert _util.remote_tracebacks(outer) == [TB_A]


def test_identical_remote_tracebacks_are_reported_once():
    """Undoing one duplication only to add another would be a poor
    trade: the same text twice in one chain prints once."""
    inner = _remote("remote KeyError: 'k'", TB_A)
    outer = _remote("session unusable", TB_A)
    outer.__cause__ = inner
    assert _util.remote_tracebacks(outer) == [TB_A]


def test_distinct_remote_tracebacks_are_all_reported():
    inner = _remote("remote KeyError: 'k'", TB_A)
    outer = _remote("stop failed", TB_B)
    outer.__cause__ = inner
    assert _util.remote_tracebacks(outer) == [TB_B, TB_A]


def test_a_cyclic_chain_terminates():
    """A self-referential chain must not hang the failure path --
    the worst possible place to hang."""
    a = _remote("a", TB_A)
    b = _remote("b", TB_B)
    a.__context__ = b
    b.__context__ = a
    assert _util.remote_tracebacks(a) == [TB_A, TB_B]


def test_self_referential_exception_terminates():
    a = _remote("a", TB_A)
    a.__cause__ = a
    assert _util.remote_tracebacks(a) == [TB_A]


def test_empty_and_missing_remote_tracebacks_are_ignored():
    assert _util.remote_tracebacks(None) == []
    assert _util.remote_tracebacks(ValueError("plain")) == []
    assert _util.remote_tracebacks(_remote("no tb", "")) == []
    assert _util.remote_tracebacks(_remote("blank tb", "  \n")) == []


def test_format_exc_chain_appends_the_remote_frames_once():
    try:
        try:
            raise _remote("remote KeyError: 'k'", TB_A)
        except RemotePythonError as exc:
            raise RuntimeError("op failed") from exc
    except RuntimeError:
        text = _util.format_exc_chain()
    assert text.count(TB_A) == 1
    assert _util.REMOTE_TB_HEADING in text
    assert "RuntimeError: op failed" in text


def test_format_exc_chain_is_format_exc_without_a_remote_error():
    """No pyte.remote failure in the chain: byte-identical to what
    the report sites printed before."""
    try:
        raise ValueError("plain")
    except ValueError:
        assert _util.format_exc_chain() == traceback.format_exc()


def test_format_exc_chain_falls_back_when_the_walk_raises(monkeypatch):
    """A bug in the traceback formatting must not replace the
    diagnosis with a worse one."""
    def boom(exc):
        raise RuntimeError("walker is broken")

    monkeypatch.setattr(_util, "remote_tracebacks", boom)
    try:
        raise _remote("remote KeyError: 'k'", TB_A)
    except RemotePythonError:
        text = _util.format_exc_chain()
        assert text == traceback.format_exc()
    assert TB_A not in text
    assert "walker is broken" not in text
