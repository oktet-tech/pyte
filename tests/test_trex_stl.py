# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.stl unit tests (offline: orchestration with fakes)."""
from pyte.errors import TeError, TrexError
from pyte.tools.trex import PktBuilder, Stream, TXCont
from pyte.tools.trex import stl


def test_trexerror_message_path():
    e = TrexError("connect failed: no server")
    assert "connect failed" in str(e)
    assert e.rc == 0
    assert isinstance(e, TeError)


class _FakeRem:
    """Fake pyte.remote session: records (op_name, args), returns canned."""

    def __init__(self, canned):
        self.canned = canned          # op __name__ -> return value
        self.calls = []               # list of (op_name, args, kwargs)

    def call(self, fn, *args, **kwargs):
        self.calls.append((fn.__name__, args, kwargs))
        val = self.canned.get(fn.__name__)
        return val() if callable(val) else val


_STATS = {
    "0": {"opackets": 1000, "ipackets": 998, "obytes": 64000,
          "ibytes": 63872, "tx_pps": 500.0, "rx_pps": 499.0,
          "tx_bps": 256000.0, "rx_bps": 255488.0},
    "global": {"tx_bps": 256000.0, "rx_bps": 255488.0, "tx_pps": 500.0,
               "rx_pps": 499.0, "cpu_util": 5.0, "queue_full": 0},
}


def _client():
    rem = _FakeRem({
        "reset": {"ok": True},
        "add_streams": {"streams": [{"name": "s1",
                                     "summary": "Ether / IP / UDP", "len": 64}]},
        "start": {"started": True},
        "wait_on_traffic": {"done": True},
        "get_stats": _STATS,
        "stop": {"stopped": True},
    })
    # cli sentinel stands in for the remote STLClient RemoteObject
    return stl.Client(rem, cli=object(), ports=[0, 1]), rem


def test_client_add_streams_shipped_and_logged():
    c, rem = _client()
    c.add_streams(Stream(packet=PktBuilder("Ether()/IP()/UDP()"),
                         mode=TXCont(pps=1000), name="s1"), ports=[0])
    op, args, _ = rem.calls[-1]
    assert op == "add_streams"
    # args: (cli, port, [spec, ...])
    assert args[1] == 0
    assert args[2][0]["name"] == "s1"


def test_client_start_passes_params():
    c, rem = _client()
    c.start(ports=[0], mult="10gbps", duration=10)
    op, args, _ = rem.calls[-1]
    assert op == "start"
    assert args[1:] == ([0], "10gbps", 10, False)


def test_client_get_stats_parses():
    c, _ = _client()
    ps = c.get_stats(ports=[0])[0]
    assert ps.tx_pkts == 1000
    assert ps.loss_pkts == 2
