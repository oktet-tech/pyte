# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Agent shell environment (the tapi_sh_env family).

The environment a test agent hands to the programs it starts lives in
``/agent:<ta>/env:<NAME>``.  This module holds the composite
operations on it that a suite prologue performs; single variables are
plain :func:`pyte.cfg.get`/:func:`pyte.cfg.set` calls on that OID and
need no wrapper.

Everything here is a plain value change, so nothing needs undoing: the
configuration backup restores each agent's environment after the run.
"""
from __future__ import annotations

from typing import Sequence

from pyte import cfg

#: Directories holding system binaries that a login shell's PATH often
#: omits, appended by :func:`expand_path_all_ta`.
DEFAULT_SBIN_DIRS = ("/usr/local/sbin", "/usr/sbin", "/sbin")


def ta_path_append(ta: str, dirs: Sequence[str]) -> None:
    """Append ``dirs`` to one agent's PATH, one directory at a time.

    PATH is re-read from the Configurator before each append, so the
    agent keeps whatever value it already had (including anything the
    configuration files put there).

    Not idempotent by design: a directory already in PATH is appended
    again.  Keeping the operation dumb keeps it a single pass; undoing
    it is the configuration backup's job, not a membership check's.
    """
    oid = f"/agent:{ta}/env:PATH"
    for d in dirs:
        path = cfg.get(oid)
        cfg.set(oid, f"{path}:{d}")


def expand_path_all_ta(dirs: Sequence[str] = DEFAULT_SBIN_DIRS) -> None:
    """Append ``dirs`` to the PATH of every agent in the configuration.

    The Python counterpart of TE's ``tapi_expand_path_all_ta()``: a
    prologue calls it so that tests can start sbin tools by name on any
    agent, including those a suite's own configuration files do not
    mention.
    """
    for agt in cfg.find("/agent:*"):
        ta_path_append(agt.name, dirs)
