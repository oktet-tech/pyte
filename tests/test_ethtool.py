# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.ethtool unit tests (offline: argv build + output parse)."""
from pathlib import Path

import pytest

from pyte.errors import EthtoolError
from pyte.tools import ethtool  # noqa: F401  (import-smoke check)
from pyte.tools.ethtool import Cmd, ErrCode, Opts, _build_report

DATA = Path(__file__).parent / "data"


# -- argv building ----------------------------------------------------------

def test_to_argv_none():
    assert Opts(if_name="eth0").to_argv() == ["eth0"]


def test_to_argv_stats_command():
    assert Opts(if_name="eth0", cmd=Cmd.STATS).to_argv() == \
        ["--statistics", "eth0"]


def test_to_argv_include_statistics_flag():
    assert Opts(if_name="eth0", cmd=Cmd.SHOW_PAUSE, stats=True).to_argv() == \
        ["--include-statistics", "--show-pause", "eth0"]


def test_to_argv_show_commands():
    assert Opts(if_name="e", cmd=Cmd.SHOW_RING).to_argv() == \
        ["--show-ring", "e"]
    assert Opts(if_name="e", cmd=Cmd.SHOW_FEC).to_argv() == \
        ["--show-fec", "e"]
    assert Opts(if_name="e", cmd=Cmd.SHOW_MODULE).to_argv() == \
        ["--show-module", "e"]
    assert Opts(if_name="e", cmd=Cmd.REG_DUMP).to_argv() == \
        ["--register-dump", "e"]


def test_to_argv_eeprom_dump_subargs():
    argv = Opts(if_name="eth0", cmd=Cmd.EEPROM_DUMP,
                raw=True, offset=0, length=16).to_argv()
    assert argv == ["--eeprom-dump", "eth0",
                    "raw", "on", "offset", "0", "length", "16"]


def test_to_argv_module_eeprom_subargs():
    argv = Opts(if_name="eth0", cmd=Cmd.DUMP_MODULE_EEPROM,
                raw=False, hex=True, offset=2, length=8,
                page=1, bank=0, i2c=80).to_argv()
    assert argv == ["--dump-module-eeprom", "eth0",
                    "raw", "off", "hex", "on", "offset", "2",
                    "length", "8", "page", "1", "bank", "0", "i2c", "80"]


def test_subargs_ignored_for_non_dump_commands():
    # raw/offset are dump-only; they must not leak into a SHOW_RING argv.
    assert Opts(if_name="e", cmd=Cmd.SHOW_RING,
                raw=True, offset=4).to_argv() == ["--show-ring", "e"]


def test_if_name_required():
    with pytest.raises(ValueError, match="if_name"):
        Opts(if_name="")


# -- output parsing ---------------------------------------------------------

def test_parse_if_props_lo():
    rep = _build_report(Cmd.NONE,
                        (DATA / "ethtool_props_lo.txt").read_text(), "")
    assert rep.err_code is ErrCode.OK
    assert rep.if_props.link is True
    assert rep.if_props.autoneg is False  # no Auto-negotiation line


def test_parse_if_props_nic():
    rep = _build_report(Cmd.NONE,
                        (DATA / "ethtool_props.txt").read_text(), "")
    assert rep.if_props.link is True
    assert rep.if_props.autoneg is False  # "Auto-negotiation: off"


def test_parse_stats_and_get_stat():
    rep = _build_report(Cmd.STATS,
                        (DATA / "ethtool_stats.txt").read_text(), "")
    assert rep.get_stat("rx_kicks") == 525
    assert rep.get_stat("tx_kicks") == 13143378
    assert rep.get_stat("rx_drops") == 0
    with pytest.raises(EthtoolError, match="no statistic"):
        rep.get_stat("does_not_exist")


def test_parse_pause():
    rep = _build_report(Cmd.SHOW_PAUSE,
                        (DATA / "ethtool_pause.txt").read_text(), "")
    p = rep.pause
    assert p.autoneg is True
    assert p.rx is True
    assert p.tx is False
    assert p.rx_pause_frames == 12
    assert p.tx_pause_frames == 34


def test_parse_ring():
    rep = _build_report(Cmd.SHOW_RING,
                        (DATA / "ethtool_ring.txt").read_text(), "")
    r = rep.ring
    assert r.rx_max == 4096
    assert r.tx_max == 4096
    assert r.rx == 256
    assert r.tx == 512


def test_eopnotsupp_skips_parse():
    rep = _build_report(Cmd.SHOW_RING, "",
                        "netlink error: Operation not supported")
    assert rep.err_code is ErrCode.EOPNOTSUPP
    assert rep.ring is None


def test_unparsed_command_keeps_raw_out():
    rep = _build_report(Cmd.SHOW_FEC, "FEC parameters for eth0:\nblah\n", "")
    assert rep.err_code is ErrCode.OK
    assert rep.if_props is None and rep.ring is None
    assert "FEC parameters" in rep.out


# -- exit status handling (run() no-raise policy keeps the status) ----------

from pyte.job import JobStatus, StatusKind  # noqa: E402


def test_failed_run_is_not_a_confident_parse():
    """ethtool exit 71 (\"no such device\"): empty stdout must not parse
    into IfProps(link=False) with err_code OK — indistinguishable from a
    real link-down.  The failure surfaces as ErrCode.FAIL + status."""
    st = JobStatus(StatusKind.EXITED, 71)
    rep = _build_report(Cmd.NONE, "",
                        "Cannot get device settings: No such device",
                        status=st)
    assert rep.err_code is ErrCode.FAIL
    assert rep.if_props is None
    assert rep.status == st


def test_eopnotsupp_recognised_before_fail():
    rep = _build_report(Cmd.SHOW_RING, "",
                        "netlink error: Operation not supported",
                        status=JobStatus(StatusKind.EXITED, 76))
    assert rep.err_code is ErrCode.EOPNOTSUPP
    assert rep.ring is None


def test_ok_run_records_status():
    rep = _build_report(Cmd.NONE,
                        (DATA / "ethtool_props_lo.txt").read_text(), "",
                        status=JobStatus(StatusKind.EXITED, 0))
    assert rep.err_code is ErrCode.OK
    assert rep.status.ok


# -- run() teardown hygiene --------------------------------------------------

class _FakeChannel:
    def __init__(self, fail=False):
        self.fail = fail

    def attach_filter(self, name=None, readable=True):
        if self.fail:
            raise RuntimeError("attach failed")
        return self


class _FakeJob:
    def __init__(self):
        self.events = []
        self.stdout = _FakeChannel()
        self.stderr = _FakeChannel(fail=True)

    def destroy(self, *a, **k):
        self.events.append("destroy")


class _FakePco:
    def __init__(self, job):
        self._job = job

    def job(self, program, args=None):
        return self._job


def test_run_destroys_job_when_filter_attach_fails():
    from pyte.tools import ethtool
    job = _FakeJob()
    with pytest.raises(RuntimeError, match="attach failed"):
        ethtool.run(_FakePco(job), Opts(if_name="eth0"))
    assert job.events == ["destroy"]
