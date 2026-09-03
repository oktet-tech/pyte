# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex — drive the TRex traffic generator.

Stateless (STL) support lives in :mod:`pyte.tools.trex.stl` and mirrors
the native ``trex_stl_lib.api`` surface. The native bundled client runs
agent-local via :mod:`pyte.remote`; pyte owns all TE logging. Engine-side
option/stream/stats types are pure dataclasses (no shim imports).

Batch (ASTF) support -- a port of ``tapi_trex`` (options, platform YAML,
stdout filter tables, report/series math and the create/start/wait/
stop/kill/report/close job lifecycle) -- lives in
:mod:`pyte.tools.trex.batch`; see its module docstring for a runnable
example.
"""
from pyte.tools.trex._config import ServerOpts
from pyte.tools.trex._stream import (PktBuilder, Stream, TXCont,
                                     TXMultiBurst, TXSingleBurst)
from pyte.tools.trex._stats import GlobalStats, LatencyStats, PortStats

__all__ = ["ServerOpts", "PktBuilder", "Stream", "TXCont", "TXSingleBurst",
           "TXMultiBurst", "PortStats", "GlobalStats", "LatencyStats"]

from pyte.tools.trex import stl  # noqa: E402,F401  (submodule re-export)
from pyte.tools.trex import batch  # noqa: E402,F401  (submodule re-export)

__all__ += ["stl", "batch"]
