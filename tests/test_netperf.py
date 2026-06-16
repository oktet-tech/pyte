# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.netperf unit tests (offline: argv build + text parse)."""
from pathlib import Path

import pytest

from pyte.errors import NetperfError
from pyte.tools import netperf  # noqa: F401  (import-smoke check)
from pyte.tools.netperf import Opts, _parse_report

DATA = Path(__file__).parent / "data"


# -- server argv ------------------------------------------------------------

def test_server_argv():
    argv = Opts(port=12865).server_argv(bind="127.0.0.1")
    assert argv == ["-L", "127.0.0.1", "-p", "12865", "-D"]


def test_server_argv_ipversion():
    argv = Opts(port=12865, ipversion="6").server_argv(bind="::1")
    assert argv == ["-L", "::1", "-p", "12865", "-6", "-D"]


# -- client argv ------------------------------------------------------------

def test_client_argv_requires_host():
    with pytest.raises(ValueError, match="host"):
        Opts().client_argv()


def test_client_argv_stream_minimal():
    argv = Opts(host="127.0.0.1").client_argv()
    assert argv == ["-t", "TCP_STREAM", "-H", "127.0.0.1"]


def test_client_argv_stream_full():
    argv = Opts(
        host="192.0.2.1", test_name="TCP_STREAM", src_host="192.0.2.9",
        port=12865, ipversion="4", duration=10,
        buffer_send=1400, buffer_recv=1400,
        local_sock_buf=65536, remote_sock_buf=65536,
    ).client_argv()
    assert argv == [
        "-t", "TCP_STREAM", "-H", "192.0.2.1", "-4", "-L", "192.0.2.9",
        "-p", "12865", "-l", "10",
        "--", "-m", "1400", "-M", "1400", "-s", "65536", "-S", "65536",
    ]


def test_client_argv_rr_request_response():
    argv = Opts(host="h", test_name="TCP_RR",
                request_size=100, response_size=200).client_argv()
    assert argv == ["-t", "TCP_RR", "-H", "h", "--", "-r", "100,200"]


def test_client_argv_rr_request_only():
    argv = Opts(host="h", test_name="UDP_RR", request_size=64).client_argv()
    assert argv == ["-t", "UDP_RR", "-H", "h", "--", "-r", "64"]


def test_client_argv_rr_response_only():
    argv = Opts(host="h", test_name="UDP_RR", response_size=200).client_argv()
    assert argv == ["-t", "UDP_RR", "-H", "h", "--", "-r", ",200"]


def test_unknown_test_name_rejected():
    with pytest.raises(ValueError, match="test_name"):
        Opts(host="h", test_name="BOGUS")


# -- output parsing ---------------------------------------------------------

def test_parse_tcp_stream():
    rep = _parse_report((DATA / "netperf_tcp_stream.txt").read_text(),
                        "TCP_STREAM")
    assert rep.test_type == "stream"
    assert rep.mbps_send == pytest.approx(9385.43)
    assert rep.mbps_recv == pytest.approx(9385.43)   # TCP copies send→recv
    assert rep.trps is None


def test_parse_tcp_rr():
    rep = _parse_report((DATA / "netperf_tcp_rr.txt").read_text(), "TCP_RR")
    assert rep.test_type == "rr"
    assert rep.trps == pytest.approx(28746.32)
    assert rep.mbps_send is None


def test_parse_udp_stream():
    rep = _parse_report((DATA / "netperf_udp_stream.txt").read_text(),
                        "UDP_STREAM")
    assert rep.test_type == "stream"
    assert rep.mbps_send == pytest.approx(7864.32)
    assert rep.mbps_recv == pytest.approx(7864.21)


def test_parse_tcp_maerts_routes_to_stream():
    rep = _parse_report((DATA / "netperf_tcp_stream.txt").read_text(),
                        "TCP_MAERTS")
    assert rep.test_type == "stream"
    assert rep.mbps_send == pytest.approx(9385.43)
    assert rep.mbps_recv == pytest.approx(9385.43)


def test_parse_unparseable_raises():
    with pytest.raises(NetperfError, match="parse"):
        _parse_report("no metrics here", "TCP_STREAM")
