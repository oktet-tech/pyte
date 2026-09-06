# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Tester interaction: runtime requirements and TRC tags.

Everything here is meant for the suite's ROOT PROLOGUE:

- add_trc_tag() is enforced by TE (TE_EPERM elsewhere): TRC tags must
  land before the TRC snapshot.  try_add_trc_tag() is the non-fatal
  form, and the tags_*() collectors declare a whole family of tags
  describing the rig, returning the display names accepted.
- modify_reqs() ANDs an expression into the session's requirement
  filter (same syntax as --tester-req); the Tester applies it when
  the calling prologue exits, so it cannot affect the caller itself.

Usage (in ts/prologue.py)::

    from pyte import tester

    tester.add_trc_tag("no_fio")
    tester.modify_reqs("!FIO")     # exclude tests requiring FIO

    tags = tester.tags_cpus(iut_ta, "iut")
    tags += tester.tags_tool_version(rpcs, "nginx", "nginx -v 2>&1")
    log.ring("TRC tags:" + "".join(f" {t}" for t in tags))
"""
from __future__ import annotations

from pyte import log
from pyte._util import shim_lib as _shim_lib
from pyte.errors import RpcError, TeError, check
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


def try_add_trc_tag(name: str, value: str | None = None) -> bool:
    """:func:`add_trc_tag` made non-fatal; True when it was accepted.

    Tag collection describes the rig, it does not test it: a tag TE
    refuses must never fail the prologue and take the whole run with
    it.  The failure is logged and that single tag is skipped.
    """
    try:
        add_trc_tag(name, value)
        return True
    except TeError as e:
        log.error(f"add_trc_tag({name!r}) failed: {e}")
        return False


def tags_cpus(ta: str, prefix: str) -> list[str]:
    """Declare the CPU tags for one agent; return what was accepted.

    Two tags: the machine type as ``"<prefix>-<machine>"``, and the
    number of CPU threads as ``"<prefix>-cpus"`` carrying the count as
    its value.  The returned display names spell the second one
    ``"<prefix>-cpus:<n>"``, i.e. the way a tag with a value is
    written in a TRC database, so a caller can log the whole list as
    it stands.
    """
    from pyte import cfg, net

    tags = []
    machine = cfg.get(f"/agent:{ta}/uname:/machine:")
    name = f"{prefix}-{machine}"
    if try_add_trc_tag(name):
        tags.append(name)

    _, threads = net.agent(ta).cpu_counts()
    name = f"{prefix}-cpus"
    if try_add_trc_tag(name, str(threads)):
        tags.append(f"{name}:{threads}")

    return tags


def tags_tool_version(rpcs, tool: str, cmd: str) -> list[str]:
    """Declare a ``"<tool>-<version>"`` tag; return what was accepted.

    The version comes from running ``cmd`` on ``rpcs``' agent.  A tool
    that is not installed there is only warned about and yields no tag:
    the tests needing it may simply never run.
    """
    try:
        out = rpcs.sh(cmd)
    except RpcError:
        log.warn(f"Cannot get '{tool}' version (is it installed on "
                 f"{rpcs.ta}?)")
        return []
    name = f"{tool}-{out}"
    return [name] if try_add_trc_tag(name) else []
