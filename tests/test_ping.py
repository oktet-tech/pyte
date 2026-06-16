# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.ping unit tests (offline: argv build + output parse)."""
from pathlib import Path

import pytest

from pyte.errors import PingError
from pyte.tools import ping  # noqa: F401  (import-smoke check)
from pyte.tools.ping import Opts, _parse_report

DATA = Path(__file__).parent / "data"


# -- argv building ----------------------------------------------------------

def test_to_argv_minimal():
    """Only the required destination is positional; nothing else emitted."""
    assert Opts(destination="127.0.0.1").to_argv() == ["127.0.0.1"]


def test_to_argv_full_order():
    """Flags appear in ping_binds order: -c, -s, -i, -I, then destination."""
    argv = Opts(
        destination="192.0.2.1",
        packet_count=4,
        packet_size=56,
        interval=0.2,
        interface="eth0",
    ).to_argv()
    assert argv == [
        "-c", "4", "-s", "56", "-i", "0.2", "-I", "eth0", "192.0.2.1",
    ]


def test_to_argv_omits_unset():
    """Unset optionals are omitted; set ones appear before the destination."""
    argv = Opts(destination="::1", packet_count=2).to_argv()
    assert argv == ["-c", "2", "::1"]


def test_destination_required():
    with pytest.raises(ValueError, match="destination"):
        Opts(destination="")


# -- output parsing ---------------------------------------------------------

def test_parse_report_with_rtt():
    rep = _parse_report((DATA / "ping_sample.txt").read_text())
    assert rep.transmitted == 4
    assert rep.received == 4
    assert rep.lost_percentage == 0
    assert rep.with_rtt is True
    assert rep.rtt.min == pytest.approx(0.028)
    assert rep.rtt.avg == pytest.approx(0.041)
    assert rep.rtt.max == pytest.approx(0.055)
    assert rep.rtt.mdev == pytest.approx(0.011)


def test_parse_report_loss_no_rtt():
    rep = _parse_report((DATA / "ping_sample_loss.txt").read_text())
    assert rep.transmitted == 5
    assert rep.received == 0
    assert rep.lost_percentage == 100
    assert rep.with_rtt is False


def test_parse_report_unparseable_raises():
    with pytest.raises(PingError, match="parse"):
        _parse_report("this is not ping output")
