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
        "    - ip: '1.1.1.1'\n"
        "      default_gw: '1.1.1.2'\n"
        "    - ip: '2.2.2.2'\n"
        "      default_gw: '2.2.2.1'\n")


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
        "    - src_mac: 'aa:bb:cc:dd:ee:01'\n"
        "      dest_mac: 'aa:bb:cc:dd:ee:02'\n"
        "    - src_mac: 'aa:bb:cc:dd:ee:02'\n"
        "      dest_mac: 'aa:bb:cc:dd:ee:01'\n")


def test_software_shell_command_adds_flag():
    opts = ServerOpts(
        trex_exec="/home/kostik/trex/t-rex-64", ports=["trex0", "trex1"],
        software=True,
        port_macs=[("aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"),
                   ("aa:bb:cc:dd:ee:02", "aa:bb:cc:dd:ee:01")])
    assert opts.shell_command("/tmp/x.yaml") == (
        "cd /home/kostik/trex && exec /home/kostik/trex/t-rex-64 "
        "-i --cfg /tmp/x.yaml -c 1 --software")


def test_shell_command_quotes_paths():
    """Paths reach sh -c: a space (or metacharacter) in the install dir
    must not split the command or execute something else."""
    opts = ServerOpts(trex_exec="/opt/my trex/t-rex-64",
                      ports=["0000:04:00.0"])
    cmd = opts.shell_command("/tmp/dir with space/x.yaml")
    assert "'/opt/my trex'" in cmd
    assert "'/opt/my trex/t-rex-64'" in cmd
    assert "'/tmp/dir with space/x.yaml'" in cmd


def test_astf_launch_line_has_astf_and_offload_flags():
    o = ServerOpts(trex_exec="/usr/local/trex/t-rex-64",
                   ports=["0000:03:00.0", "0000:03:00.1"],
                   astf=True, tso_disable=True, lro_disable=True)
    cmd = o.shell_command("/tmp/x.yaml")
    assert " --astf" in cmd
    assert " --tso-disable" in cmd
    assert " --lro-disable" in cmd


def test_non_astf_launch_line_unchanged():
    o = ServerOpts(trex_exec="/usr/local/trex/t-rex-64", ports=["eth1"],
                   software=True, port_macs=[("00:11:22:33:44:55",
                                              "00:11:22:33:44:66")])
    cmd = o.shell_command("/tmp/x.yaml")
    assert "--astf" not in cmd
    assert "--tso-disable" not in cmd


def test_so_flags_are_emitted_in_order():
    o = ServerOpts(trex_exec="/usr/local/trex/t-rex-64", ports=["x"],
                   so=("--mlx5-so",))
    assert " --mlx5-so" in o.shell_command("/tmp/x.yaml")


def test_mac_form_port_info_is_legal_in_dpdk_mode():
    o = ServerOpts(trex_exec="/usr/local/trex/t-rex-64",
                   ports=["0000:03:00.0"],
                   port_macs=[("00:11:22:33:44:55",
                               "00:11:22:33:44:66")])
    yaml = o.cfg_yaml()
    assert "src_mac: '00:11:22:33:44:55'" in yaml
    assert "dest_mac: '00:11:22:33:44:66'" in yaml
    assert "--software" not in o.shell_command("/tmp/x.yaml")


def test_cfg_extra_is_appended_verbatim():
    extra = "\n  platform:\n      master_thread_id: 0\n"
    o = ServerOpts(trex_exec="/usr/local/trex/t-rex-64", ports=["x"],
                   cfg_extra=extra)
    assert o.cfg_yaml().endswith(extra)


def test_port_info_and_port_macs_are_mutually_exclusive():
    with pytest.raises(ValueError, match="port_info"):
        ServerOpts(trex_exec="/usr/local/trex/t-rex-64", ports=["x"],
                   port_info=[("10.0.0.1", "10.0.0.2")],
                   port_macs=[("00:11:22:33:44:55",
                               "00:11:22:33:44:66")])


def test_cfg_yaml_macs_parse_as_strings():
    """Unquoted colon-separated MACs are sexagesimal integers under
    YAML 1.1 -- the rendered YAML must quote them."""
    import yaml
    opts = ServerOpts(
        trex_exec="/x/t-rex-64", ports=["trex0"], software=True,
        port_macs=[("00:11:22:33:44:55", "00:11:22:33:44:66")])
    doc = yaml.safe_load(opts.cfg_yaml())
    info = doc[0]["port_info"][0]
    assert info["src_mac"] == "00:11:22:33:44:55"
    assert isinstance(info["src_mac"], str)
