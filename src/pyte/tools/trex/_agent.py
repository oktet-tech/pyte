# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Where a TRex session puts its temporary files on the agent host.

The platform cfg-YAML and the ASTF profile source are written on the
agent by op-functions from :mod:`pyte.tools.trex._ops` and
:mod:`pyte.tools.trex._astf_ops`. Those are shipped as source and must
stay self-contained -- no module-level references, no Configurator
access -- so they cannot look a directory up themselves. The engine
side reads it here and passes it in.
"""
from __future__ import annotations

from pyte import log


def tmp_dir(ta: str) -> str | None:
    """The agent's own temp directory, or None when it is unavailable.

    TE agents publish ``/agent:<ta>/tmp_dir:``, a directory owned by
    the agent's lifecycle. Writing there instead of /tmp matters on a
    shared lab host, where every run of every session otherwise drops
    files into a directory nothing owns.

    A missing or empty knob is not worth failing bring-up over: None
    tells the caller to fall back on mkstemp's default, which is what
    every session did before. The fallback is warned about rather than
    taken in silence, so files landing in /tmp are explained where it
    happens.
    """
    from pyte.cfg.gen.agent import Agent
    try:
        value = Agent(ta).tmp_dir
    except Exception as exc:        # noqa: BLE001  optional lookup
        log.warn(f"could not read /agent:{ta}/tmp_dir: ({exc}); TRex "
                 f"temp files go to the default temp directory")
        return None
    if not value:
        log.warn(f"/agent:{ta}/tmp_dir: is empty; TRex temp files go "
                 f"to the default temp directory")
        return None
    return value
