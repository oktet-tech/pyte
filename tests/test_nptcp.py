# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.nptcp unit tests (offline: argv build + table parse)."""
from pathlib import Path

import pytest

from pyte.errors import NptcpError
from pyte.tools import nptcp  # noqa: F401  (import-smoke check)
from pyte.tools.nptcp import Opts, _parse_report

DATA = Path(__file__).parent / "data"


# -- argv building ----------------------------------------------------------

def test_server_argv_minimal():
    # receiver: no -h, no options set
    assert Opts().server_argv() == []


def test_client_argv_requires_host():
    with pytest.raises(ValueError, match="host"):
        Opts().client_argv()


def test_client_argv_minimal():
    assert Opts(host="127.0.0.1").client_argv() == ["-h", "127.0.0.1"]


def test_server_argv_full_order_no_host():
    argv = Opts(
        tcp_buffer_size=65536, invalidate_cache=True, starting_msg_size=1,
        nrepeats=100, offsets="0", output_filename="/tmp/np.out",
        perturbation_size=3, reset_sockets=True, streaming_mode=True,
        upper_bound=8192, bi_directional_mode=True,
    ).server_argv()
    assert argv == [
        "-b", "65536", "-I", "-l", "1", "-n", "100", "-O", "0",
        "-o", "/tmp/np.out", "-p", "3", "-r", "-s", "-u", "8192", "-2",
    ]


def test_client_argv_full_order_with_host():
    argv = Opts(
        host="192.0.2.1", tcp_buffer_size=65536, starting_msg_size=1,
        upper_bound=8192,
    ).client_argv()
    assert argv == [
        "-b", "65536", "-h", "192.0.2.1", "-l", "1", "-u", "8192",
    ]


# -- table parsing ----------------------------------------------------------

def test_parse_report_entries():
    rep = _parse_report((DATA / "nptcp_sample.txt").read_text())
    assert len(rep.entries) == 4
    e0 = rep.entries[0]
    assert (e0.number, e0.bytes, e0.times) == (0, 1, 23259)
    assert e0.throughput == pytest.approx(0.18)
    assert e0.rtt == pytest.approx(42.30)
    e3 = rep.entries[3]
    assert (e3.number, e3.bytes, e3.times) == (3, 8192, 4034)
    assert e3.throughput == pytest.approx(1175.42)
    assert e3.rtt == pytest.approx(53.17)


def test_parse_report_no_entries_raises():
    with pytest.raises(NptcpError, match="parse"):
        _parse_report("Send and receive buffers are 1 and 2 bytes\n")
