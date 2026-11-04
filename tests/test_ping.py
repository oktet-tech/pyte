# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.ping unit tests (offline: argv build + output parse)."""
import re
from pathlib import Path

import pytest

from pyte.errors import PingError
from pyte.job import JobMessage
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


def test_parse_report_with_reply_lines():
    rep = _parse_report((DATA / "ping_replies.txt").read_text())
    assert (rep.transmitted, rep.received, rep.lost_percentage) == (4, 4, 0)
    assert rep.rtt.max == pytest.approx(0.030)


# -- live replies -----------------------------------------------------------

class _GrepFilter:
    """Filter fake: drain() hands out one queued batch per call."""

    def __init__(self, *batches):
        self._batches = list(batches)

    def drain(self, timeout=0):
        return self._batches.pop(0) if self._batches else []


class _Job:
    def stop(self, timeout=10.0, signal="SIGTERM"):
        pass

    def destroy(self, timeout=10.0):
        pass


def _msgs(lines):
    return [JobMessage(raw=line.encode(), eos=False, dropped=0, filter=None)
            for line in lines]


def _agent_grep(name):
    """What the agent's PCRE2 multiline filter hands out: the matches."""
    text = (DATA / name).read_text()
    return [m.group(0) for m in
            re.finditer(ping._REPLY_REGEX, text, re.MULTILINE)]


def test_reply_regex_matches_each_reply_line():
    assert _agent_grep("ping_replies.txt") == [
        f"64 bytes from 127.0.0.1: icmp_seq={i}" for i in (1, 2, 3, 4)]


def test_reply_regex_skips_unreachable_lines():
    # "From 172.18.0.1 icmp_seq=1 Destination Host Unreachable" carries
    # icmp_seq= but is no reply.
    assert _agent_grep("ping_unreachable.txt") == []


def test_ping_replies_count():
    lines = _agent_grep("ping_replies.txt")
    rflt = _GrepFilter(_msgs(lines[:2]), _msgs(lines[2:]))
    p = ping.Ping(_Job(), _GrepFilter(), replies=rflt)
    assert p.replies() == 2
    assert p.replies() == 4      # cumulative
    assert p.replies() == 4      # nothing new: unchanged


def test_replies_after_close_keep_the_last_count():
    rflt = _GrepFilter(_msgs(_agent_grep("ping_replies.txt")))
    p = ping.Ping(_Job(), _GrepFilter(), replies=rflt)
    assert p.replies() == 4
    p.close()

    def _drain(timeout=0):
        raise AssertionError("drained a destroyed job's filter")

    rflt.drain = _drain
    assert p.replies() == 4


def test_replies_without_the_filter_are_refused():
    with pytest.raises(RuntimeError, match="replies"):
        ping.Ping(_Job(), _GrepFilter()).replies()


# -- run(): the reply filter ------------------------------------------------

class _RunChannel:
    def __init__(self):
        self.calls = []

    def attach_filter(self, name=None, readable=True, log_level=None,
                      regex=None, group=0):
        self.calls.append(("attach_filter", name, regex))
        return _GrepFilter()

    def grep(self, regex, group=0, name=None):
        self.calls.append(("grep", name, regex))
        return _GrepFilter()

    def log(self, level="RING"):
        self.calls.append(("log", level))
        return _GrepFilter()


class _RunJob(_Job):
    def __init__(self):
        self.stdout = _RunChannel()
        self.stderr = _RunChannel()

    def start(self):
        pass


class _RunPco:
    def __init__(self):
        self.the_job = _RunJob()

    def job(self, program, args=None, env=None):
        return self.the_job


def test_run_greps_the_reply_lines():
    pco = _RunPco()
    with ping.run(pco, Opts(destination="127.0.0.1")):
        pass
    assert pco.the_job.stdout.calls == [
        ("attach_filter", "ping_stdout", None),
        ("grep", "ping_replies", ping._REPLY_REGEX)]
