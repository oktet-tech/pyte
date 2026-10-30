# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.testpmd unit tests (offline: builders, parser, handle)."""
import signal
from pathlib import Path

import pytest

from pyte import errors
from pyte.job import JobMessage
from pyte.tools import testpmd
from pyte.tools.testpmd import (
    Opts,
    PortStats,
    StatsParser,
    total_num_mbufs_default,
)


def test_eal_argv_allow_lcores_prefix():
    o = Opts(allow=("0000:03:00.1",), lcores=(2, 3), file_prefix="lane0")
    assert o.eal_argv() == ["--allow=0000:03:00.1", "-n", "4",
                            "--file-prefix", "lane0", "--lcores=2,3"]


def test_app_argv_fixed_knobs_and_passthrough():
    o = Opts(allow=("0000:03:00.1",), lcores=(2, 3), nb_cores=1,
             cmdline_file="/tmp/x", eth_peer=((0, "00:11:22:33:44:55"),),
             passthrough=(("rxfreet", "0"), ("txonly_multi_flow", True),
                          ("skip", False)))
    a = o.app_argv()
    assert a[:5] == ["--", "--disable-device-start", "--nb-cores", "1",
                     "--cmdline-file"]
    assert "--stats-period" in a and a[a.index("--stats-period") + 1] == "1"
    assert "--no-lsc-interrupt" in a
    assert a[a.index("--eth-peer") + 1] == "0,00:11:22:33:44:55"
    assert a[a.index("--rxfreet") + 1] == "0"
    assert "--txonly-multi-flow" in a and "--skip" not in a


def test_cmdline_text_order():
    o = Opts(allow=("x",), lcores=(1,), flow_ctrl=True, mtu=1500,
             txpkts="1700,1700,500")
    assert o.cmdline_text(1) == (
        "set flow_ctrl rx on tx on 0\nport config mtu 0 1500\n"
        "port start all\nshow port info all\n"
        "set txpkts 1700,1700,500\nstart\n")


def test_total_num_mbufs_default_minimum():
    assert total_num_mbufs_default(
        1, Opts(allow=("x",), lcores=(1,))) == 2048


def test_argv_is_eal_plus_app_and_optional_mbuf_knobs():
    o = Opts(allow=("x",), lcores=(1,), mbuf_size=2176,
             total_num_mbufs=4096)
    a = o.app_argv()
    assert a[a.index("--mbuf-size") + 1] == "2176"
    assert a[a.index("--total-num-mbufs") + 1] == "4096"
    assert o.argv() == o.eal_argv() + a
    assert "--no-lsc-interrupt" not in Opts(
        allow=("x",), lcores=(1,), no_lsc_interrupt=False).app_argv()


def test_cmdline_text_flow_ctrl_off_tx_first_multiport():
    o = Opts(allow=("x",), lcores=(1,), flow_ctrl=False, tx_first=4)
    assert o.cmdline_text(2) == (
        "set flow_ctrl rx off tx off 0\nset flow_ctrl rx off tx off 1\n"
        "port start all\nshow port info all\nstart tx_first 4\n")


def test_total_num_mbufs_default_scales():
    o = Opts(allow=("x",), lcores=(1,), rxq=4, txq=4, nb_cores=2)
    assert total_num_mbufs_default(2, o) == (
        2 * (4 * (512 + 32) + 4 * 512) + 500)


def _data():
    return (Path(__file__).parent / "data" / "testpmd_stats.txt").read_text()


def test_parser_extracts_every_complete_block():
    got = StatsParser().feed(_data())
    assert [s.port for s in got] == [0, 1, 0, 1]
    assert got[2].rx_packets > got[0].rx_packets
    assert got[0] == PortStats(
        port=0, rx_packets=123456, rx_bytes=7901184, rx_missed=0,
        rx_errors=0, tx_packets=123400, tx_bytes=7897600, tx_errors=0,
        rx_pps=100000, tx_pps=99950)


def test_stats_block_split_across_messages():
    text = _data()
    cut = text.index("TX-packets")      # inside the first block
    p = StatsParser()
    assert p.feed(text[:cut]) == []
    rest = p.feed(text[cut:])
    assert [s.port for s in rest] == [0, 1, 0, 1]


def test_stats_every_two_way_split():
    text = _data()
    for cut in range(len(text) + 1):
        p = StatsParser()
        got = p.feed(text[:cut]) + p.feed(text[cut:])
        assert [s.port for s in got] == [0, 1, 0, 1], cut


def test_stats_fed_one_character_at_a_time():
    p = StatsParser()
    got = []
    for ch in _data():
        got += p.feed(ch)
    assert [s.port for s in got] == [0, 1, 0, 1]


# ---------------------------------------------------------------------------
# run() handle with fakes (pure Python, no shim); copied from test_fio.py
# ---------------------------------------------------------------------------

#: rx_packets of the last port 0 block in tests/data/testpmd_stats.txt
LAST_RX_PACKETS_PORT0 = 223400


def _msgs(text: str, size: int = 97) -> list[JobMessage]:
    """Split *text* into stdout messages cutting across stats blocks."""
    return [JobMessage(raw=text[i:i + size].encode(), eos=False,
                       dropped=0, filter=None)
            for i in range(0, len(text), size)]


class _FakeFilter:
    """Minimal Filter fake: drain() hands out one queued batch per call."""

    def __init__(self, batches: list[list[JobMessage]] | None = None):
        self._batches = list(batches or [])
        self.log_calls: list = []

    def drain(self, timeout: float | None = 0) -> list[JobMessage]:
        return self._batches.pop(0) if self._batches else []

    def attach_filter(self, name=None, readable=True, log_level=None,
                      regex=None, group=0):
        return self


class _FakeChannel:
    """Fake Channel: attach_filter / log return a FakeFilter."""

    def __init__(self, batches=None):
        self._filter = _FakeFilter(batches)
        self.attach_calls: list[tuple] = []
        self.log_levels: list = []

    def attach_filter(self, name=None, readable=True, log_level=None,
                      regex=None, group=0):
        self.attach_calls.append((name, readable))
        return self._filter

    def log(self, level=None):
        self.log_levels.append(level)
        return self._filter


class _FakeJobStatus:
    def __init__(self, ok: bool = True):
        self._ok = ok

    @property
    def ok(self) -> bool:
        return self._ok

    def __str__(self) -> str:
        return "exited(0)" if self._ok else "exited(1)"


class _FakeJob:
    """Fake Job: records calls, returns fake channels."""

    def __init__(self, batches=None, exit_ok: bool = True):
        self._exit_ok = exit_ok
        self._stdout_ch = _FakeChannel(batches)
        self._stderr_ch = _FakeChannel()
        self.started = False
        self.stopped = False
        self.stop_signal = None
        self.destroyed = False

    @property
    def stdout(self) -> _FakeChannel:
        return self._stdout_ch

    @property
    def stderr(self) -> _FakeChannel:
        return self._stderr_ch

    def start(self) -> None:
        self.started = True

    def wait(self, timeout: float = 10.0) -> _FakeJobStatus:
        return _FakeJobStatus(self._exit_ok)

    def stop(self, timeout: float = 10.0, signal="SIGTERM") -> None:
        self.stopped = True
        self.stop_signal = signal

    def destroy(self, timeout: float = 10.0) -> None:
        self.destroyed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.destroy()
        return False


class _FakePco:
    """Fake RpcServer: job() returns a pre-configured FakeJob."""

    ta = "Agt_A"

    def __init__(self, fake_job: _FakeJob):
        self._fake_job = fake_job
        self.job_calls: list[tuple] = []
        self.file_put_calls: list[tuple] = []

    def job(self, program: str, args: list[str] | None = None,
            env=None) -> _FakeJob:
        self.job_calls.append((program, args))
        return self._fake_job

    def file_put(self, path: str, data: bytes) -> None:
        # RpcServer.file_put writes bytes (a str breaks its memoryview)
        assert isinstance(data, bytes), type(data)
        self.file_put_calls.append((path, data.decode()))


_CFG = {"/agent:Agt_A/dir:": "/tmp/agt", "/agent:Agt_A/tmp_dir:": "/tmp"}


@pytest.fixture
def fake_cfg(monkeypatch):
    monkeypatch.setattr(testpmd.cfg, "get", lambda oid: _CFG[oid])


@pytest.fixture
def fake_pco(fake_cfg):
    return _FakePco(_FakeJob())


@pytest.fixture
def fake_pco_with_stdout(fake_cfg):
    return _FakePco(_FakeJob([_msgs(_data())]))


def _port1_start() -> int:
    """Offset of the first port 1 block's header line in the fixture."""
    text = _data()
    return text.rindex("\n", 0, text.index("for port 1")) + 1


class _FakeClock:
    """Stands in for the time module: sleep() advances monotonic()."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s


def test_run_writes_cmdline_file_and_launches(fake_pco):
    o = Opts(allow=("0000:03:00.1",), lcores=(2, 3), file_prefix="l0")
    with testpmd.run(fake_pco, o) as h:
        assert isinstance(h, testpmd.Testpmd)
    (path, text), = fake_pco.file_put_calls
    assert path == "/tmp/l0_testpmd_commands"
    assert text.endswith("start\n")
    prog, argv = fake_pco.job_calls[0][:2]
    assert prog == "/tmp/agt/dpdk-testpmd"
    assert ("--cmdline-file" in argv
            and argv[argv.index("--cmdline-file") + 1] == path)
    assert "--total-num-mbufs" in argv


def test_run_defaults_mbufs_wires_filters_and_stops_with_sigint(fake_pco):
    o = Opts(allow=("0000:03:00.1",), lcores=(2, 3))
    job = fake_pco._fake_job
    with testpmd.run(fake_pco, o):
        assert job.started and not job.stopped
    argv = fake_pco.job_calls[0][1]
    assert argv[argv.index("--mbuf-size") + 1] == "2176"
    assert argv[argv.index("--total-num-mbufs") + 1] == str(
        total_num_mbufs_default(1, o))
    assert job.stdout.attach_calls == [("testpmd-out", True)]
    assert job.stderr.log_levels == ["WARN"]
    assert job.stop_signal == signal.SIGINT and job.destroyed


def test_run_keeps_explicit_mbufs_and_honours_nports(fake_pco):
    o = Opts(allow=("x",), lcores=(1,), flow_ctrl=True, mbuf_size=9000,
             total_num_mbufs=8192)
    with testpmd.run(fake_pco, o, nports=2):
        pass
    (_, text), = fake_pco.file_put_calls
    assert text == o.cmdline_text(2)
    argv = fake_pco.job_calls[0][1]
    assert argv[argv.index("--mbuf-size") + 1] == "9000"
    assert argv[argv.index("--total-num-mbufs") + 1] == "8192"


def test_run_mbufs_default_scales_with_nports(fake_pco):
    o = Opts(allow=("x",), lcores=(1,), rxq=4, txq=4)
    with testpmd.run(fake_pco, o, nports=2):
        pass
    argv = fake_pco.job_calls[0][1]
    assert argv[argv.index("--total-num-mbufs") + 1] == str(
        total_num_mbufs_default(2, o))


def test_stats_returns_latest_per_port(fake_pco_with_stdout):
    with testpmd.run(fake_pco_with_stdout,
                     Opts(allow=("a", "b"), lcores=(1,))) as h:
        s = h.stats()
        assert set(s) == {0, 1}
        assert s[0].rx_packets == LAST_RX_PACKETS_PORT0
        assert h.stats() == s        # nothing new queued: cached


def test_wait_ports_started_polls_until_every_port_reported(
        fake_cfg, monkeypatch):
    port1 = _port1_start()
    job = _FakeJob([[], _msgs(_data()[:port1]), [], _msgs(_data()[port1:])])
    clock = _FakeClock()
    monkeypatch.setattr(testpmd, "time", clock)
    with testpmd.run(_FakePco(job), Opts(allow=("a", "b"),
                                         lcores=(1,))) as h:
        assert h.stats() == {}          # no block yet
        h.wait_ports_started(10)
        assert set(h.stats()) == {0, 1}
    assert clock.sleeps == [0.5, 0.5]


def test_wait_ports_started_times_out(fake_cfg, monkeypatch):
    job = _FakeJob([_msgs(_data()[:_port1_start()])])
    clock = _FakeClock()
    monkeypatch.setattr(testpmd, "time", clock)
    with testpmd.run(_FakePco(job), Opts(allow=("a", "b"),
                                         lcores=(1,))) as h:
        with pytest.raises(errors.TestpmdError, match=r"\[1\]"):
            h.wait_ports_started(2)
        assert set(h.stats()) == {0}
    assert clock.now == pytest.approx(2.0)
