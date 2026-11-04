# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.iperf3 unit tests (offline: argv build, JSON/text parse)."""
import json
import re
from pathlib import Path

import pytest

from pyte.errors import IperfError
from pyte.job import JobMessage, JobStatus, StatusKind
from pyte.testing import fake_shim  # noqa: F401
from pyte.tools import iperf3
from pyte.tools.iperf3 import Direction, Opts, _parse_report

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

    def stop(self, timeout=10.0, signal="SIGTERM"):
        pass

    def destroy(self, timeout=10.0):
        pass


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


# -- text mode (Opts.json=False): argv --------------------------------------

def test_text_client_argv_has_no_json():
    assert "-J" not in Opts(host="h", json=False).client_argv()


def test_text_client_argv_flushes_each_line():
    # Text into a pipe is block-buffered: without --forceflush the
    # interval lines reach the agent only when the client exits.
    assert Opts(host="h", json=False).client_argv() == [
        "-c", "h", "--forceflush"]


def test_text_client_argv_keeps_the_bind_order():
    kw = dict(
        host="192.0.2.1", src_host="192.0.2.9", port=5201, ipversion="4",
        protocol="udp", bandwidth_bits=1000000, length=1400, num_bytes=2048,
        duration=20, interval=2, streams=4, reverse=True, dual=True)
    json_argv = Opts(**kw).client_argv()
    assert Opts(**kw, json=False).client_argv() == [
        "--forceflush" if a == "-J" else a for a in json_argv]


def test_json_applies_to_the_client_only():
    assert Opts(port=5201, json=False).server_argv() == [
        "-s", "-J", "-p5201"]


# -- text mode: summary parsing (real iperf 3.18 output) --------------------

G = 2 ** 30     # iperf3 prints byte sizes in powers of 1024
M = 2 ** 20


def _text(name):
    return (DATA / name).read_text()


def test_parse_text_report():
    rep = iperf3._parse_text_report(_text("iperf3_text_client.txt"))
    assert rep.sent.bytes > 0 and rep.received.bits_per_second > 0
    assert rep.min_bps_per_stream <= rep.sent.bits_per_second
    # [SUM]   0.00-3.00   sec  71.0 GBytes   203 Gbits/sec    0   sender
    assert rep.sent == Direction(bits_per_second=pytest.approx(203e9),
                                 bytes=round(71.0 * G),
                                 seconds=pytest.approx(3.0), retransmits=0)
    # [SUM]   0.00-3.00   sec  71.0 GBytes   203 Gbits/sec       receiver
    assert rep.received == Direction(bits_per_second=pytest.approx(203e9),
                                     bytes=round(71.0 * G),
                                     seconds=pytest.approx(3.0),
                                     retransmits=None)
    # per-stream sender lines: 101 and 102 Gbits/sec
    assert rep.min_bps_per_stream == pytest.approx(101e9)
    assert rep.error is None


def test_parse_text_report_single_stream_has_no_sum_block():
    rep = iperf3._parse_text_report(_text("iperf3_text_client_p1.txt"))
    # [  5]   0.00-3.00   sec  37.8 GBytes   108 Gbits/sec    0   sender
    assert rep.sent.bytes == round(37.8 * G)
    assert rep.sent.bits_per_second == pytest.approx(108e9)
    assert rep.sent.seconds == pytest.approx(3.0)
    assert rep.sent.retransmits == 0
    assert rep.received.bytes == round(37.8 * G)
    assert rep.received.retransmits is None
    assert rep.min_bps_per_stream == pytest.approx(108e9)


def test_parse_text_report_udp_prints_no_retransmits():
    rep = iperf3._parse_text_report(_text("iperf3_text_client_udp.txt"))
    # [SUM] 0.00-3.01 sec 7.19 MBytes 20.1 Mbits/sec 0.000 ms 0/230 (0%)
    assert rep.sent.bytes == round(7.19 * M)
    assert rep.sent.bits_per_second == pytest.approx(20.1e6)
    assert rep.sent.seconds == pytest.approx(3.01)
    assert rep.sent.retransmits is None
    assert rep.received.bits_per_second == pytest.approx(20.1e6)
    assert rep.min_bps_per_stream == pytest.approx(10.0e6)


def test_parse_text_report_bidir_reads_the_client_tx_block():
    # Mirrors JSON end.sum_sent/sum_received: the [TX-C] direction.
    rep = iperf3._parse_text_report(_text("iperf3_text_client_bidir.txt"))
    # [SUM][TX-C]   0.00-3.00   sec  28.0 GBytes  80.0 Gbits/sec    2  sender
    assert rep.sent.bytes == round(28.0 * G)
    assert rep.sent.bits_per_second == pytest.approx(80.0e9)
    assert rep.sent.retransmits == 2
    assert rep.received.bytes == round(28.0 * G)
    # per-stream senders of both directions: 42.9, 37.1, 45.6, 48.5 Gbits
    assert rep.min_bps_per_stream == pytest.approx(37.1e9)


def test_parse_text_report_reverse_reads_the_server_as_sender():
    # -R: the server sends; the client still prints sender/receiver.
    rep = iperf3._parse_text_report(_text("iperf3_text_client_reverse.txt"))
    # [SUM]   0.00-2.00   sec  47.8 GBytes   205 Gbits/sec    0   sender
    assert (rep.sent.bytes, rep.sent.retransmits) == (round(47.8 * G), 0)
    assert rep.received.bits_per_second == pytest.approx(205e9)


def test_parse_text_report_interrupted_keeps_the_summary_and_the_error():
    # SIGINT at 2.5 s: the summary of what ran so far on stdout, the
    # interrupt line on stderr, exit 1.
    rep = iperf3._parse_text_report(
        _text("iperf3_text_interrupted.txt")
        + _text("iperf3_text_interrupted_stderr.txt"))
    assert rep.error == "interrupt - the client has terminated"
    assert rep.sent.bytes == round(57.2 * G)
    assert rep.sent.seconds == pytest.approx(2.5)
    assert rep.received.bytes == 0      # "0.00 Bytes  0.00 bits/sec"
    assert rep.received.bits_per_second == 0.0
    assert rep.min_bps_per_stream == pytest.approx(97.5e9)


def test_parse_text_report_error_without_a_summary_raises():
    with pytest.raises(IperfError, match="reported error.*Connection refused"):
        iperf3._parse_text_report(_text("iperf3_text_error_stderr.txt"))


def test_parse_text_report_without_a_summary_raises():
    head = _text("iperf3_text_client.txt").split("[ ID] Interval")[1]
    with pytest.raises(IperfError, match="no summary"):
        iperf3._parse_text_report(head)


# -- text mode: live progress -----------------------------------------------

class _GrepFilter:
    """Filter fake: drain() hands out one queued batch per call."""

    def __init__(self, *batches):
        self._batches = list(batches)

    def drain(self, timeout=0):
        return self._batches.pop(0) if self._batches else []


def _msgs(*lines):
    return [JobMessage(raw=line.encode(), eos=False, dropped=0, filter=None)
            for line in lines]


def _agent_grep(text):
    """What the agent's PCRE2 multiline filter hands out: the matches."""
    return [m.group(0) for m in
            re.finditer(iperf3._INTERVAL_REGEX, text, re.MULTILINE)]


def _text_client(status=None, out="", err="", intervals=None):
    return iperf3.Iperf3(_Job(status), _Filter(out), _Filter(err),
                         intervals=intervals or _GrepFilter())


def test_progress_counts_interval_lines():
    flt = _GrepFilter(_msgs(
        "[  5]   0.00-1.00   sec  11.8 GBytes   101 Gbits/sec    0   "
        "1023 KBytes       ",
        "[  7]   0.00-1.00   sec  11.9 GBytes   102 Gbits/sec    0   "
        "1.12 MBytes       ",
        "[  5]   1.00-2.00   sec  11.8 GBytes   101 Gbits/sec    0   "
        "1023 KBytes       ",
        # a per-stream summary line matches the regex too: not counted
        "[  5]   0.00-3.00   sec  35.4 GBytes   101 Gbits/sec    0   "
        "         sender"))
    h = _text_client(intervals=flt)
    want = 2 * round(11.8 * G) + round(11.9 * G)
    assert h.progress() == (3, want, 3)
    assert h.progress() == (3, want, 3)   # nothing new: unchanged


def test_progress_is_cumulative_across_calls():
    lines = _agent_grep(_text("iperf3_text_client.txt"))
    h = _text_client(intervals=_GrepFilter(_msgs(*lines[:2]),
                                           _msgs(*lines[2:])))
    assert h.progress() == (2, round(11.8 * G) + round(11.9 * G), 2)
    # 11.8, 11.9 | 11.8, 11.9, 11.8, 11.8 GBytes, then the summary lines
    assert h.progress() == (6, 4 * round(11.8 * G) + 2 * round(11.9 * G), 6)


def test_progress_over_the_captured_run_skips_sum_and_summary_lines():
    text = _text("iperf3_text_client.txt")
    assert len(_agent_grep(text)) == 10     # 6 intervals + 4 summaries
    h = _text_client(intervals=_GrepFilter(_msgs(*_agent_grep(text))))
    assert h.progress() == (6, 4 * round(11.8 * G) + 2 * round(11.9 * G), 6)


def test_progress_counts_both_directions_of_bidir():
    text = _text("iperf3_text_client_bidir.txt")
    h = _text_client(intervals=_GrepFilter(_msgs(*_agent_grep(text))))
    sizes = [5.25, 4.84, 4.54, 6.36, 4.59, 4.02, 5.63, 5.23,
             5.17, 4.10, 5.77, 5.34]
    assert h.progress() == (12, sum(round(v * G) for v in sizes), 12)


def test_progress_counts_intervals_that_moved_nothing_apart():
    # Server SIGSTOPped from 2.2 s to 6.2 s: three "0.00 Bytes" lines.
    lines = _agent_grep(_text("iperf3_text_client_stalled.txt"))
    assert [line.split()[4:6] for line in lines[3:6]] == [
        ["0.00", "Bytes"]] * 3
    h = _text_client(intervals=_GrepFilter(
        _msgs(*lines[:3]), _msgs(*lines[3:6]), _msgs(*lines[6:])))
    moved = round(15.5 * G) + round(15.2 * G) + round(3.00 * G)
    assert h.progress() == (3, moved, 3)
    # the stalled intervals: the total keeps growing, the moving count
    # and the bytes stay flat
    assert h.progress() == (3, moved, 6)
    # 12.4 and 15.3 GBytes after SIGCONT, then the summary rows
    assert h.progress() == (5, moved + round(12.4 * G) + round(15.3 * G), 8)


def test_progress_converts_mbytes_of_udp():
    text = _text("iperf3_text_client_udp.txt")
    h = _text_client(intervals=_GrepFilter(_msgs(*_agent_grep(text))))
    sizes = [1.22, 1.22, 1.19, 1.16, 1.19, 1.22]
    assert h.progress() == (6, sum(round(v * M) for v in sizes), 6)


def test_progress_after_close_keeps_the_last_counts():
    lines = _agent_grep(_text("iperf3_text_client_p1.txt"))
    flt = _GrepFilter(_msgs(*lines))
    h = _text_client(intervals=flt)
    want = (3, 2 * round(12.6 * G) + round(12.5 * G), 3)
    assert h.progress() == want
    h.close()

    def _drain(timeout=0):
        raise AssertionError("drained a destroyed job's filter")

    flt.drain = _drain
    assert h.progress() == want


def test_progress_in_json_mode_is_refused():
    with pytest.raises(RuntimeError, match="json=False"):
        _client("iperf3_tcp.json", JobStatus(StatusKind.EXITED, 0)).progress()


# -- text mode: wait() ------------------------------------------------------

def test_text_client_wait_parses_the_text_summary(fake_shim):  # noqa: F811
    rep = _text_client(JobStatus(StatusKind.EXITED, 0),
                       _text("iperf3_text_client.txt")).wait()
    assert rep.sent.bytes == round(71.0 * G)
    assert rep.min_bps_per_stream == pytest.approx(101e9)


def test_interrupted_text_client_reads_the_error_from_stderr(
        fake_shim):  # noqa: F811
    rep = _text_client(JobStatus(StatusKind.EXITED, 1),
                       _text("iperf3_text_interrupted.txt"),
                       _text("iperf3_text_interrupted_stderr.txt")).wait()
    assert rep.error == "interrupt - the client has terminated"
    assert rep.sent.bytes == round(57.2 * G)


def test_text_client_error_raises(fake_shim):  # noqa: F811
    with pytest.raises(IperfError, match="Connection refused"):
        _text_client(JobStatus(StatusKind.EXITED, 1), "",
                     _text("iperf3_text_error_stderr.txt")).wait()


def test_killed_text_client_raises_even_with_a_summary(
        fake_shim):  # noqa: F811
    with pytest.raises(IperfError, match="exited with"):
        _text_client(JobStatus(StatusKind.SIGNALED, 9),
                     _text("iperf3_text_interrupted.txt"),
                     _text("iperf3_text_interrupted_stderr.txt")).wait()


# -- run(): which filters the client gets -----------------------------------

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


class _RunJob:
    def __init__(self):
        self.stdout = _RunChannel()
        self.stderr = _RunChannel()

    def start(self):
        pass

    def stop(self, timeout=10.0, signal="SIGTERM"):
        pass

    def destroy(self, timeout=10.0):
        pass


class _RunPco:
    def __init__(self):
        self.the_job = _RunJob()
        self.job_calls = []

    def job(self, program, args=None, env=None):
        self.job_calls.append((program, args))
        return self.the_job


def test_run_text_mode_greps_the_interval_lines():
    pco = _RunPco()
    with iperf3.run(pco, Opts(host="h", interval=1, json=False)):
        pass
    assert pco.job_calls == [("iperf3", ["-c", "h", "--forceflush", "-i1"])]
    assert pco.the_job.stdout.calls == [
        ("attach_filter", "iperf3_stdout", None),
        ("grep", "iperf3_intervals", iperf3._INTERVAL_REGEX)]


def test_run_json_mode_attaches_no_grep():
    pco = _RunPco()
    with iperf3.run(pco, Opts(host="h", interval=1)):
        pass
    assert pco.job_calls == [("iperf3", ["-c", "h", "-J", "-i1"])]
    assert pco.the_job.stdout.calls == [
        ("attach_filter", "iperf3_stdout", None)]
