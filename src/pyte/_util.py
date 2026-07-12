# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Shared internal plumbing: shim access, C-string helpers.

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
