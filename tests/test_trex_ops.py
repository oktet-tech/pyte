# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex._ops: agent-side functions must be shippable.

We cannot execute them offline (they need TRex + Scapy on the agent), but
pyte.remote ships them by source with inspect.getsource and rejects
closures/lambdas. _extract_source raising would mean a runtime failure on
the agent, so assert every op passes it now.
"""
from pyte.remote import _extract_source
from pyte.tools.trex import _ops

OPS = [_ops.write_cfg, _ops.bootstrap, _ops.reset, _ops.add_streams,
       _ops.start, _ops.wait_on_traffic, _ops.get_stats,
       _ops.get_pgid_stats, _ops.stop, _ops.disconnect]


def test_all_ops_are_shippable():
    for fn in OPS:
        src, name = _extract_source(fn)
        assert name == fn.__name__
        assert "def " in src
