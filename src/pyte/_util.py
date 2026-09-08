# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Shared internal plumbing: shim access, C-string helpers, tracebacks.

Why shim access is a function and not a module-level import: the
compiled extension must load lazily (pure-Python modules stay
importable without a TE build), and the unit tests inject fake shims
by setting ``sys.modules["pyte._shim"]``.  Both properties depend on
resolving the module THROUGH ``sys.modules`` at call time — which is
what a ``from pyte._shim import ...`` inside a function does, and what
these accessors do in exactly one place.  Do NOT "optimize" them into
module-level imports or ``pyte._shim`` attribute access (the parent
package attribute bypasses an injected fake).
"""
from __future__ import annotations

import sys
import traceback

#: Heading printed before each agent-side traceback appended to a
#: local one.  Its wording is not matched by anything; it exists so a
#: reader can tell whose frames follow.
REMOTE_TB_HEADING = "Remote (agent-side) traceback:"


def remote_tracebacks(exc: BaseException | None) -> list[str]:
    """Agent-side tracebacks carried by *exc* and the exceptions it
    chains to, each distinct one exactly once, outermost first.

    :class:`~pyte.errors.RemotePythonError` keeps the agent-side
    traceback in its ``remote_traceback`` attribute and NOT in its
    message, so that a caller wrapping it (``raise TrexError(f"...
    {exc}") from exc``) still produces a one-line message.  The
    frames are recovered here, at the one place that reports the
    failure, instead of being carried by every message that quotes it.

    Both edges of the chain are followed: ``raise ... from exc`` sets
    ``__cause__``, while an exception raised inside an ``except``
    block without ``from`` chains through ``__context__``, and both
    shapes occur.  Already-visited exceptions are skipped, so a
    self-referential chain terminates instead of hanging the failure
    path.
    """
    out: list[str] = []
    seen_exc: set[int] = set()
    seen_tb: set[str] = set()
    queue: list[BaseException | None] = [exc]
    while queue:
        cur = queue.pop(0)
        if cur is None or id(cur) in seen_exc:
            continue
        seen_exc.add(id(cur))
        tb = getattr(cur, "remote_traceback", None)
        if isinstance(tb, str) and tb.strip() and tb not in seen_tb:
            seen_tb.add(tb)
            out.append(tb)
        queue.append(cur.__cause__)
        queue.append(cur.__context__)
    return out


def format_remote_tracebacks(exc: BaseException | None) -> str:
    """:func:`remote_tracebacks` rendered under a heading, or "".

    Never raises: it is called from handlers that are already
    reporting a failure, and a formatting bug there must not replace
    the diagnosis with a worse one.
    """
    try:
        return "".join(f"\n{REMOTE_TB_HEADING}\n{tb.rstrip()}\n"
                       for tb in remote_tracebacks(exc))
    except Exception:  # noqa: BLE001  never worsen a failure report
        return ""


def format_exc_chain() -> str:
    """``traceback.format_exc()`` plus any agent-side tracebacks.

    Drop-in for :func:`traceback.format_exc` in an ``except`` block:
    identical output when nothing in the chain came from
    :mod:`pyte.remote`.
    """
    return traceback.format_exc() + format_remote_tracebacks(
        sys.exc_info()[1])


def shim():
    """The shim's ``(ffi, lib)`` pair, resolved through sys.modules."""
    from pyte._shim import ffi, lib
    return ffi, lib


def shim_lib():
    """Just the shim ``lib``, resolved through sys.modules."""
    from pyte._shim import lib
    return lib


def enc(text: str) -> bytes:
    """Encode for the C side; never let bad text break the call."""
    return text.encode("utf-8", "backslashreplace")


def take_str(out) -> str:
    """Decode and free a C-allocated char* held in a char** out-param."""
    ffi, lib = shim()
    s = ffi.string(out[0]).decode("utf-8", errors="replace")
    lib.pyte_free_string(out[0])
    out[0] = ffi.NULL
    return s
