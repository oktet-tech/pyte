# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.batch Opts/Endpoint unit tests (offline: argv only)."""
import pytest

from pyte.tools.trex import batch


def _opts(**kw):
    base = dict(trex_exec="/usr/local/trex/_t-rex-64-o",
                astf_json="{}",
                clients=(batch.Endpoint(iface=batch.LinuxIface("eth1"),
                                        ip="10.0.0.1", gw="10.0.0.2"),))
    base.update(kw)
    return batch.Opts(**base)


def test_argv_matches_c_server_example():
    o = _opts(astf_server_only=True, n_threads=8, tso_disable=True,
              lro_disable=True, duration=60.0, rate_multiplier=1.5,
              force_close_at_end=True, no_monitors=True,
              queue_drop=True, iom=batch.Iom.NORMAL,
              so=(batch.So.MLX5,))
    assert o.to_argv() == [
        "/usr/local/trex/_t-rex-64-o", "-f", "default.py", "--astf",
        "--astf-server-only", "-c", "8", "--tso-disable",
        "--lro-disable", "-d", "60.000000", "-m", "1.500000", "--nc",
        "-pubd", "--queue-drop", "--iom", "1", "--mlx5-so"]


def test_astf_json_required():
    with pytest.raises(ValueError):
        _opts(astf_json="")


def test_argv_minimal_defaults_omit_all_optional_flags():
    o = _opts()
    assert o.to_argv() == [
        "/usr/local/trex/_t-rex-64-o", "-f", "default.py", "--astf"]


def test_argv_covers_remaining_bind_order_tail():
    o = _opts(flip=True, hdrh=True, ipv6=True,
              no_flow_control_change=True, no_watchdog=True,
              rt_prio=True, sleeps=True, verbose=batch.Verbose.MAX,
              init_wait_sec=5, instance_prefix="inst0")
    assert o.to_argv() == [
        "/usr/local/trex/_t-rex-64-o", "-f", "default.py", "--astf",
        "--flip", "--hdrh", "--ipv6", "--no-flow-control-change",
        "--no-watchdog", "--rt", "--sleeps", "-v", "3", "-w", "5",
        "--prefix", "inst0"]


def test_argv_multiple_so_flags_each_own_element():
    o = _opts(so=(batch.So.MLX4, batch.So.MLX5))
    assert o.to_argv() == [
        "/usr/local/trex/_t-rex-64-o", "-f", "default.py", "--astf",
        "--mlx4-so", "--mlx5-so"]


def test_endpoint_ip_src_mac_exclusive():
    with pytest.raises(ValueError):
        batch.Endpoint(ip="10.0.0.1", src_mac="00:11:22:33:44:55")


def test_endpoint_gw_dst_mac_exclusive():
    with pytest.raises(ValueError):
        batch.Endpoint(gw="10.0.0.1", dst_mac="00:11:22:33:44:55")


def test_opts_requires_at_least_one_endpoint_group():
    with pytest.raises(ValueError):
        batch.Opts(trex_exec="/usr/local/trex/_t-rex-64-o",
                   astf_json="{}")


def test_opts_servers_only_is_sufficient():
    o = batch.Opts(trex_exec="/usr/local/trex/_t-rex-64-o",
                   astf_json="{}",
                   servers=(batch.Endpoint(iface=batch.PciBdf(
                       "0000:01:00.0")),))
    assert o.to_argv() == [
        "/usr/local/trex/_t-rex-64-o", "-f", "default.py", "--astf"]
