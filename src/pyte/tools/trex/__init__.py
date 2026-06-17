# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex — drive the TRex traffic generator.

Stateless (STL) support lives in :mod:`pyte.tools.trex.stl` and mirrors
the native ``trex_stl_lib.api`` surface. The native bundled client runs
agent-local via :mod:`pyte.remote`; pyte owns all TE logging. Engine-side
option/stream/stats types are pure dataclasses (no shim imports).
"""
from pyte.tools.trex._config import ServerOpts
from pyte.tools.trex._stream import (PktBuilder, Stream, TXCont,
                                     TXMultiBurst, TXSingleBurst)
from pyte.tools.trex._stats import GlobalStats, LatencyStats, PortStats

__all__ = ["ServerOpts", "PktBuilder", "Stream", "TXCont", "TXSingleBurst",
           "TXMultiBurst", "PortStats", "GlobalStats", "LatencyStats"]

from pyte.tools.trex import stl  # noqa: E402,F401  (submodule re-export)

__all__ += ["stl"]
