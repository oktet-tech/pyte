# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.sfnt_pingpong unit tests (offline: argv build + table parse)."""
from pathlib import Path

import pytest

from pyte.errors import SfntError
from pyte.tools import sfnt_pingpong  # noqa: F401  (import-smoke check)
from pyte.tools.sfnt_pingpong import Opts, _parse_report

DATA = Path(__file__).parent / "data"


# -- client argv ------------------------------------------------------------

def test_client_argv_requires_server():
    with pytest.raises(ValueError, match="server"):
        Opts().client_argv()


def test_client_argv_minimal():
    # default proto is udp; just the bare proto + server positional
    assert Opts(server="127.0.0.1").client_argv() == ["udp", "127.0.0.1"]


def test_client_argv_full_order():
    argv = Opts(
        server="192.0.2.1", proto="tcp", ipversion="4",
        sizes=[64, 128, 256], min_msg=64, max_msg=1024,
        min_ms=1000, max_ms=3000, min_iter=1000, max_iter=100000,
        spin=True, muxer="epoll", timeout_ms=500,
    ).client_argv()
    assert argv == [
        "--sizes=64,128,256", "--minmsg=64", "--maxmsg=1024",
        "--minms=1000", "--maxms=3000", "--miniter=1000", "--maxiter=100000",
        "--spin", "--muxer=epoll", "--timeout=500", "--ipv4",
        "tcp", "192.0.2.1",
    ]


def test_invalid_proto_rejected():
    with pytest.raises(ValueError, match="proto"):
        Opts(server="h", proto="sctp")


def test_invalid_muxer_rejected():
    with pytest.raises(ValueError, match="muxer"):
        Opts(server="h", muxer="kqueue")


def test_server_argv_empty():
    assert Opts().server_argv() == []


# -- table parsing ----------------------------------------------------------

def test_parse_report_rows():
    rep = _parse_report((DATA / "sfnt_pingpong_sample.txt").read_text())
    assert len(rep.rows) == 3
    r0 = rep.rows[0]
    assert (r0.size, r0.mean, r0.min, r0.median, r0.max,
            r0.percentile, r0.stddev) == (0, 1234, 1000, 1200, 5000, 2500, 300)
    r1 = rep.rows[1]
    assert (r1.size, r1.mean, r1.median, r1.max) == (64, 1500, 1450, 6000)
    r2 = rep.rows[2]
    assert (r2.size, r2.mean, r2.stddev) == (1024, 3000, 600)


def test_parse_report_no_rows_raises():
    with pytest.raises(SfntError, match="parse"):
        _parse_report("# header only\nno data rows here\n")
