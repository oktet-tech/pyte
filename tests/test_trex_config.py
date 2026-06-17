# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex ServerOpts unit tests (offline: yaml + cmdline)."""
import pytest

from pyte.tools.trex import ServerOpts


def test_requires_exec_and_ports():
    with pytest.raises(ValueError, match="trex_exec"):
        ServerOpts(trex_exec="", ports=["0000:04:00.0"])
    with pytest.raises(ValueError, match="port"):
        ServerOpts(trex_exec="/x/t-rex-64", ports=[])


def test_cfg_yaml_minimal():
    opts = ServerOpts(trex_exec="/usr/local/trex/t-rex-64",
                      ports=["0000:04:00.0", "0000:04:00.1"])
    assert opts.cfg_yaml() == (
        "- port_limit: 2\n"
        "  version: 2\n"
        "  interfaces: ['0000:04:00.0', '0000:04:00.1']\n")


def test_cfg_yaml_with_port_info():
    opts = ServerOpts(trex_exec="/usr/local/trex/t-rex-64",
                      ports=["0000:04:00.0", "0000:04:00.1"],
                      port_info=[("1.1.1.1", "1.1.1.2"),
                                 ("2.2.2.2", "2.2.2.1")])
    assert opts.cfg_yaml() == (
        "- port_limit: 2\n"
        "  version: 2\n"
        "  interfaces: ['0000:04:00.0', '0000:04:00.1']\n"
        "  port_info:\n"
        "    - ip: 1.1.1.1\n"
        "      default_gw: 1.1.1.2\n"
        "    - ip: 2.2.2.2\n"
        "      default_gw: 2.2.2.1\n")


def test_shell_command_derives_workdir():
    opts = ServerOpts(trex_exec="/usr/local/trex/t-rex-64",
                      ports=["0000:04:00.0"], cores=4)
    assert opts.shell_command("/tmp/x.yaml") == (
        "cd /usr/local/trex && exec /usr/local/trex/t-rex-64 "
        "-i --cfg /tmp/x.yaml -c 4")


def test_software_requires_port_macs():
    with pytest.raises(ValueError, match="port_macs"):
        ServerOpts(trex_exec="/x/t-rex-64", ports=["trex0", "trex1"],
                   software=True)


def test_port_macs_length_must_match():
    with pytest.raises(ValueError, match="port_macs length"):
        ServerOpts(trex_exec="/x/t-rex-64", ports=["trex0", "trex1"],
                   software=True, port_macs=[("aa:bb:cc:dd:ee:01",
                                              "aa:bb:cc:dd:ee:02")])


def test_software_cfg_yaml_uses_ifaces_and_macs():
    opts = ServerOpts(
        trex_exec="/home/kostik/trex/t-rex-64",
        ports=["trex0", "trex1"], software=True,
        port_macs=[("aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"),
                   ("aa:bb:cc:dd:ee:02", "aa:bb:cc:dd:ee:01")])
    assert opts.cfg_yaml() == (
        "- port_limit: 2\n"
        "  version: 2\n"
        "  interfaces: ['trex0', 'trex1']\n"
        "  port_info:\n"
        "    - src_mac: aa:bb:cc:dd:ee:01\n"
        "      dest_mac: aa:bb:cc:dd:ee:02\n"
        "    - src_mac: aa:bb:cc:dd:ee:02\n"
        "      dest_mac: aa:bb:cc:dd:ee:01\n")


def test_software_shell_command_adds_flag():
    opts = ServerOpts(
        trex_exec="/home/kostik/trex/t-rex-64", ports=["trex0", "trex1"],
        software=True,
        port_macs=[("aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"),
                   ("aa:bb:cc:dd:ee:02", "aa:bb:cc:dd:ee:01")])
    assert opts.shell_command("/tmp/x.yaml") == (
        "cd /home/kostik/trex && exec /home/kostik/trex/t-rex-64 "
        "-i --cfg /tmp/x.yaml -c 1 --software")
