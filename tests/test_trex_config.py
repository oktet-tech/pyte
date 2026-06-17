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
