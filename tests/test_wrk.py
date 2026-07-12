# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.wrk unit tests (offline: argv build + text parse)."""
from pathlib import Path

import pytest

from pyte.errors import WrkError
from pyte.tools import wrk  # noqa: F401  (import-smoke check)
from pyte.tools.wrk import Opts, _parse_report

DATA = Path(__file__).parent / "data"


# -- argv building ----------------------------------------------------------

def test_to_argv_minimal():
    assert Opts(url="http://127.0.0.1/").to_argv() == ["http://127.0.0.1/"]


def test_to_argv_full_order():
    argv = Opts(
        url="http://h:8080/", connections=10, threads=2, duration=5,
        latency=True, headers=["Host: x", "Accept: */*"],
        script="/tmp/s.lua", rate=1000, affinity="0,2",
        script_args=["a", "b"],
    ).to_argv()
    assert argv == [
        "--connections", "10", "--threads", "2", "--duration", "5s",
        "--latency", "http://h:8080/",
        "--header", "Host: x", "--header", "Accept: */*",
        "--script", "/tmp/s.lua", "--rate", "1000", "--affinity", "0,2",
        "a", "b",
    ]


def test_url_required():
    with pytest.raises(ValueError, match="url"):
        Opts(url="")


# -- output parsing ---------------------------------------------------------

def test_parse_report():
    rep = _parse_report((DATA / "wrk_sample.txt").read_text())
    assert rep.req_count == 246000
    assert rep.req_per_sec == pytest.approx(24600.0)
    # Transfer/sec 3.50MB -> binary MiB -> bytes/s
    assert rep.bytes_per_sec == pytest.approx(3.50 * 1024 * 1024)
    # thread latency: 456.78us / 123.45us / 2.50ms / 89.00%
    assert rep.thread_latency.mean == pytest.approx(456.78)        # µs
    assert rep.thread_latency.stdev == pytest.approx(123.45)       # µs
    assert rep.thread_latency.max == pytest.approx(2500.0)         # 2.50ms → µs
    assert rep.thread_latency.within_stdev == pytest.approx(89.0)  # %
    # thread req/sec: 12.34k / 1.23k / 15.00k / 75.00%
    assert rep.thread_req_per_sec.mean == pytest.approx(12340.0)
    assert rep.thread_req_per_sec.max == pytest.approx(15000.0)
    assert rep.thread_req_per_sec.within_stdev == pytest.approx(75.0)
    # latency distribution (4 entries)
    assert len(rep.lat_distr) == 4
    assert rep.lat_distr[0].percentile == pytest.approx(50.0)
    assert rep.lat_distr[0].latency == pytest.approx(450.0)        # µs
    assert rep.lat_distr[3].percentile == pytest.approx(99.0)
    assert rep.lat_distr[3].latency == pytest.approx(1200.0)       # 1.20ms → µs
    # responses + socket errors
    assert rep.unexpected_resp == 5
    assert rep.socket_errors.connect == 0
    assert rep.socket_errors.write == 1
    assert rep.socket_errors.timeout == 2


def test_parse_report_minimal_defaults():
    """Output without latency-distribution/socket-errors/non-2xx defaults cleanly."""
    rep = _parse_report((DATA / "wrk_minimal.txt").read_text())
    assert rep.req_count == 25000
    assert rep.req_per_sec == pytest.approx(5000.0)
    assert rep.bytes_per_sec == pytest.approx(600.0 * 1024)          # 600.00KB -> bytes/s
    assert rep.lat_distr == ()                              # no distribution block
    assert rep.unexpected_resp == 0
    assert rep.socket_errors.connect == 0
    assert rep.socket_errors.read == 0
    assert rep.socket_errors.write == 0
    assert rep.socket_errors.timeout == 0


def test_parse_report_unparseable_raises():
    with pytest.raises(WrkError, match="parse"):
        _parse_report("not wrk output")
