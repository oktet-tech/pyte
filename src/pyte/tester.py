# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Tester interaction: runtime requirements and TRC tags.

Both calls are meant for the suite's ROOT PROLOGUE:

- add_trc_tag() is enforced by TE (TE_EPERM elsewhere): TRC tags must
  land before the TRC snapshot.
- modify_reqs() ANDs an expression into the session's requirement
  filter (same syntax as --tester-req); the Tester applies it when
  the calling prologue exits, so it cannot affect the caller itself.

Usage (in ts/prologue.py)::

    from pyte import tester

    tester.add_trc_tag("no_fio")
    tester.modify_reqs("!FIO")     # exclude tests requiring FIO
"""
from __future__ import annotations

from pyte._util import shim_lib as _shim_lib
from pyte.errors import check
from pyte._util import enc as _enc


def modify_reqs(expr: str) -> None:
    """AND a requirement expression into the session filter."""
    lib = _shim_lib()
    check(lib.pyte_reqs_modify(_enc(expr)), f"modify_reqs({expr!r})")


def add_trc_tag(name: str, value: str | None = None) -> None:
    """Add a runtime TRC tag (root prologue only, enforced by TE)."""
    lib = _shim_lib()
    check(lib.pyte_tags_add_tag(_enc(name), _enc(value or "")),
          f"add_trc_tag({name!r})")
