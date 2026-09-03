# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.batch.render_cfg_yaml unit tests (offline, golden strings).

Golden strings mirror tapi_trex.c's default_trex_cfg template expansion
(tapi_trex.c:326-334) byte for byte, including the port_limit/version
colon alignment.
"""
import pytest

from pyte.tools.trex import batch


def _opts(**kw):
    base = dict(trex_exec="/usr/local/trex/_t-rex-64-o", astf_json="{}")
    base.update(kw)
    return batch.Opts(**base)


def test_render_one_client_dummy_server():
    o = _opts(clients=(batch.Endpoint(iface=batch.LinuxIface("eth1"),
                                      ip="10.0.0.1", gw="10.0.0.2"),))
    assert batch.render_cfg_yaml(o) == (
        "- port_limit      : 2\n"
        "  version         : 2\n"
        "  interfaces: ['eth1', 'dummy']\n"
        "  port_info:\n"
        "    - ip: 10.0.0.1\n"
        "      default_gw: 10.0.0.2\n"
        "    - ip: 0.0.0.0\n"
        "      default_gw: 0.0.0.0\n"
    )


def test_render_mac_pair():
    o = _opts(clients=(batch.Endpoint(iface=batch.LinuxIface("eth0"),
                                      src_mac="00:00:00:00:00:01",
                                      dst_mac="00:00:00:00:00:02"),),
              servers=(batch.Endpoint(iface=batch.LinuxIface("eth1"),
                                      src_mac="00:00:00:00:00:03",
                                      dst_mac="00:00:00:00:00:04"),))
    assert batch.render_cfg_yaml(o) == (
        "- port_limit      : 2\n"
        "  version         : 2\n"
        "  interfaces: ['eth0', 'eth1']\n"
        "  port_info:\n"
        "    - dest_mac: 00:00:00:00:00:02\n"
        "      src_mac: 00:00:00:00:00:01\n"
        "    - dest_mac: 00:00:00:00:00:04\n"
        "      src_mac: 00:00:00:00:00:03\n"
    )


def test_render_client_and_server_ordering():
    o = _opts(
        clients=(
            batch.Endpoint(iface=batch.LinuxIface("eth0"),
                           ip="10.0.0.1", gw="10.0.0.2"),
            batch.Endpoint(iface=batch.LinuxIface("eth2"),
                           ip="10.0.1.1", gw="10.0.1.2"),
        ),
        servers=(
            batch.Endpoint(iface=batch.LinuxIface("eth1"),
                           ip="10.0.0.3", gw="10.0.0.4"),
            batch.Endpoint(iface=batch.LinuxIface("eth3"),
                           ip="10.0.1.3", gw="10.0.1.4"),
        ),
    )
    assert batch.render_cfg_yaml(o) == (
        "- port_limit      : 4\n"
        "  version         : 2\n"
        "  interfaces: ['eth0', 'eth1', 'eth2', 'eth3']\n"
        "  port_info:\n"
        "    - ip: 10.0.0.1\n"
        "      default_gw: 10.0.0.2\n"
        "    - ip: 10.0.0.3\n"
        "      default_gw: 10.0.0.4\n"
        "    - ip: 10.0.1.1\n"
        "      default_gw: 10.0.1.2\n"
        "    - ip: 10.0.1.3\n"
        "      default_gw: 10.0.1.4\n"
    )


def test_render_cfg_extra_appended_verbatim():
    o = _opts(clients=(batch.Endpoint(iface=batch.LinuxIface("eth1"),
                                      ip="10.0.0.1", gw="10.0.0.2"),),
              cfg_extra="platform:\n  master_thread_id: 0\n")
    assert batch.render_cfg_yaml(o) == (
        "- port_limit      : 2\n"
        "  version         : 2\n"
        "  interfaces: ['eth1', 'dummy']\n"
        "  port_info:\n"
        "    - ip: 10.0.0.1\n"
        "      default_gw: 10.0.0.2\n"
        "    - ip: 0.0.0.0\n"
        "      default_gw: 0.0.0.0\n"
        "platform:\n"
        "  master_thread_id: 0\n"
    )


def test_render_pci_bdf_iface_single_quoted():
    o = _opts(clients=(batch.Endpoint(iface=batch.PciBdf("0000:01:00.0"),
                                      ip="10.0.0.1", gw="10.0.0.2"),))
    assert "interfaces: ['0000:01:00.0', 'dummy']" in batch.render_cfg_yaml(o)


def test_render_mixed_ip_and_dst_mac_raises():
    # DIVERGENCE: C's gen_yaml_config would silently misalign the
    # port_info YAML lists (ip goes to PORTINFO_IP while dst_mac goes to
    # PORTINFO_DST_MAC, splitting one logical port across both groups).
    # pyte requires exactly one address form per port and raises instead.
    o = _opts(clients=(batch.Endpoint(ip="10.0.0.1",
                                      dst_mac="00:00:00:00:00:01"),))
    with pytest.raises(ValueError):
        batch.render_cfg_yaml(o)


def test_render_mixed_src_mac_and_gw_raises():
    o = _opts(clients=(batch.Endpoint(src_mac="00:00:00:00:00:01",
                                      gw="10.0.0.2"),))
    with pytest.raises(ValueError):
        batch.render_cfg_yaml(o)
