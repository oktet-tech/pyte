# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.iperf3 unit tests (offline: argv build + JSON parse)."""
import json
from pathlib import Path

import pytest

from pyte.errors import IperfError
from pyte.tools import iperf3  # noqa: F401  (import-smoke check)
from pyte.tools.iperf3 import Opts, _parse_report

DATA = Path(__file__).parent / "data"


# -- server argv ------------------------------------------------------------

def test_server_argv_minimal():
    assert Opts().server_argv() == ["-s", "-J"]


def test_server_argv_port_interval():
    assert Opts(port=5201, interval=1).server_argv() == [
        "-s", "-J", "-p5201", "-i1"]


# -- client argv ------------------------------------------------------------

def test_client_argv_requires_host():
    with pytest.raises(ValueError, match="host"):
        Opts().client_argv()


def test_client_argv_tcp_minimal():
    assert Opts(host="127.0.0.1").client_argv() == ["-c", "127.0.0.1", "-J"]


def test_client_argv_full_order():
    argv = Opts(
        host="192.0.2.1", src_host="192.0.2.9", port=5201, ipversion="4",
        protocol="udp", bandwidth_bits=1000000, length=1400, num_bytes=2048,
        duration=20, interval=2, streams=4, reverse=True, dual=True,
    ).client_argv()
    assert argv == [
        "-c", "192.0.2.1", "-J", "-B192.0.2.9", "-p5201", "-4", "-u",
        "-b1000000", "-l1400", "-n2048", "-t20", "-i2", "-P4", "-R", "--bidir",
    ]


def test_client_argv_tcp_has_no_u_flag():
    assert "-u" not in Opts(host="127.0.0.1", protocol="tcp").client_argv()


# -- JSON report parsing ----------------------------------------------------

def test_parse_report_tcp():
    obj = json.loads((DATA / "iperf3_tcp.json").read_text())
    rep = _parse_report(obj)
    assert rep.sent.bits_per_second == pytest.approx(9.4e9)
    assert rep.sent.bytes == 11750000000
    assert rep.sent.seconds == pytest.approx(10.0)
    assert rep.sent.retransmits == 12
    assert rep.received.bits_per_second == pytest.approx(9.37e9)
    assert rep.received.retransmits is None
    # min over the two senders' bits_per_second
    assert rep.min_bps_per_stream == pytest.approx(4.6e9)


def test_parse_report_error_raises():
    obj = json.loads((DATA / "iperf3_error.json").read_text())
    with pytest.raises(IperfError, match="Connection refused"):
        _parse_report(obj)
