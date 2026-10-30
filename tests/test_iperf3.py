# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.iperf3 unit tests (offline: argv build + JSON parse)."""
import json
from pathlib import Path

import pytest

from pyte.errors import IperfError
from pyte.job import JobStatus, StatusKind
from pyte.testing import fake_shim  # noqa: F401
from pyte.tools import iperf3
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


def test_parse_report_tcp_has_no_error():
    obj = json.loads((DATA / "iperf3_tcp.json").read_text())
    assert _parse_report(obj).error is None


def test_parse_report_interrupted_keeps_the_summary_and_the_error():
    # SIGINT to a client: iperf3 prints the summary of what ran so
    # far, with an "error" key, and exits 1.
    obj = json.loads((DATA / "iperf3_interrupted.json").read_text())
    rep = _parse_report(obj)
    assert rep.error == "interrupt - the client has terminated"
    assert rep.sent.bits_per_second == pytest.approx(2.1e9)
    assert rep.sent.seconds == pytest.approx(37.2)
    assert rep.received.bytes == 9760000000
    assert rep.min_bps_per_stream == pytest.approx(2.1e9)


# -- client handle: exit status against the parsed report ---------------

class _Filter:
    def __init__(self, text):
        self.text = text

    def read_all(self, timeout=None):
        return self.text


class _Job:
    def __init__(self, status):
        self.status = status

    def wait(self, timeout=None):
        return self.status


def _client(name, status):
    text = (DATA / name).read_text()
    return iperf3.Iperf3(_Job(status), _Filter(text), _Filter(""))


def test_interrupted_client_yields_its_report_despite_exit_1(
        fake_shim):  # noqa: F811
    rep = _client("iperf3_interrupted.json",
                  JobStatus(StatusKind.EXITED, 1)).wait()
    assert rep.error.startswith("interrupt")
    assert rep.sent.bytes == 9765000000


def test_bad_exit_without_an_error_in_the_report_still_raises(
        fake_shim):  # noqa: F811
    with pytest.raises(IperfError, match="exited with"):
        _client("iperf3_tcp.json", JobStatus(StatusKind.EXITED, 1)).wait()


def test_killed_client_raises_even_with_a_summary(fake_shim):  # noqa: F811
    with pytest.raises(IperfError, match="exited with"):
        _client("iperf3_interrupted.json",
                JobStatus(StatusKind.SIGNALED, 9)).wait()
