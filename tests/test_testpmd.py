# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.testpmd unit tests (offline: argv and cmdline builders)."""
from pathlib import Path

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
