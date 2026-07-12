# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex._ops: agent-side functions must be shippable.

We cannot execute them offline (they need TRex + Scapy on the agent), but
pyte.remote ships them by source with inspect.getsource and rejects
closures/lambdas. _extract_source raising would mean a runtime failure on
the agent, so assert every op passes it now.
"""
import sys
import types

import pytest

from pyte.remote import _extract_source
from pyte.tools.trex import _ops

OPS = [_ops.write_cfg, _ops.remove_file, _ops.bootstrap, _ops.reset,
       _ops.add_streams, _ops.start, _ops.wait_on_traffic, _ops.get_stats,
       _ops.get_pgid_stats, _ops.stop, _ops.disconnect]


def test_all_ops_are_shippable():
    for fn in OPS:
        src, name = _extract_source(fn)
        assert name == fn.__name__
        assert "def " in src


# -- add_streams VM eval containment -----------------------------------------


def _install_fake_trex(monkeypatch):
    """Minimal fake trex.stl.api so add_streams runs without TRex."""
    api = types.ModuleType("trex.stl.api")

    class _Rec:
        def __init__(self, **kw):
            self.kw = kw

    for name in ("STLStream", "STLPktBuilder", "STLTXCont",
                 "STLTXSingleBurst", "STLTXMultiBurst", "STLFlowStats",
                 "STLFlowLatencyStats", "STLVmFlowVar"):
        setattr(api, name, type(name, (_Rec,), {}))

    trex_pkg = types.ModuleType("trex")
    stl_pkg = types.ModuleType("trex.stl")
    monkeypatch.setitem(sys.modules, "trex", trex_pkg)
    monkeypatch.setitem(sys.modules, "trex.stl", stl_pkg)
    monkeypatch.setitem(sys.modules, "trex.stl.api", api)
    return api


class _FakeCli:
    def __init__(self):
        self.added = None

    def add_streams(self, streams, ports):
        self.added = (streams, ports)


def _spec(vm):
    import base64
    return {"pkt_b64": base64.b64encode(b"\x00" * 14).decode(),
            "vm": vm, "mode": {"type": "continuous"},
            "name": "s0", "pgid": None, "latency": False}


def test_add_streams_evals_stlvm_expressions(monkeypatch):
    _install_fake_trex(monkeypatch)
    cli = _FakeCli()
    out = _ops.add_streams(cli, 0, [_spec(["STLVmFlowVar(name='ip')"])])
    assert out == {"count": 1}
    assert cli.added[1] == [0]


def test_add_streams_rejects_non_stlvm_expression(monkeypatch):
    """The docstring promises STLVm*-only evaluation; enforce it."""
    _install_fake_trex(monkeypatch)
    with pytest.raises(ValueError, match="STLVm"):
        _ops.add_streams(_FakeCli(), 0,
                         [_spec(["__import__('os').system('true')"])])


def test_add_streams_eval_has_no_builtins(monkeypatch):
    """eval() with a globals dict lacking __builtins__ injects the FULL
    builtins module; the sandbox claim is real only with it emptied."""
    _install_fake_trex(monkeypatch)
    with pytest.raises(NameError):
        _ops.add_streams(
            _FakeCli(), 0,
            [_spec(["STLVmFlowVar(name=__import__('os').getcwd())"])])
