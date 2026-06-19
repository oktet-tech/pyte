# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
# DO NOT EDIT - generated from TE CM YAML by pyte.cfg._gen.
"""System settings from /proc/sys/."""
from pyte.cfg import (
    CfgObject,
    IntKnob,
    StrKnob,
    SubObject,
)


class Vm(CfgObject):
    """System settings from /proc/sys/vm."""
    nr_hugepages = IntKnob("nr_hugepages", cvt_name="INT32")
    overcommit_memory = IntKnob("overcommit_memory", cvt_name="INT32")


class Fs(CfgObject):
    """System settings from /proc/sys/fs."""
    file_max = IntKnob("file-max", cvt_name="UINT64")
    file_nr = IntKnob(
        "file-nr",
        cvt_name="UINT64",
        access="read_only",
        sync=True)


class NetCore(CfgObject):
    """System settings from /proc/sys/net/core/."""
    busy_read = IntKnob("busy_read", cvt_name="INT32")
    busy_poll = IntKnob("busy_poll", cvt_name="INT32")
    somaxconn = IntKnob("somaxconn", cvt_name="INT32")
    wmem_default = IntKnob("wmem_default", cvt_name="INT32")
    wmem_max = IntKnob("wmem_max", cvt_name="INT32")
    rmem_default = IntKnob("rmem_default", cvt_name="INT32")
    rmem_max = IntKnob("rmem_max", cvt_name="INT32")
    optmem_max = IntKnob("optmem_max", cvt_name="INT32")


class NetNetfilter(CfgObject):
    """System settings from /proc/sys/net/netfilter/."""
    nf_conntrack_max = IntKnob("nf_conntrack_max", cvt_name="INT32")
    nf_conntrack_tcp_loose = IntKnob(
        "nf_conntrack_tcp_loose",
        cvt_name="INT32")


class NetIpv4Conf(CfgObject):
    """System settings from /proc/sys/net/ipv4/conf/."""
    forwarding = IntKnob("forwarding", cvt_name="INT32")
    rp_filter = IntKnob("rp_filter", cvt_name="INT32")
    arp_ignore = IntKnob("arp_ignore", cvt_name="INT32")
    proxy_arp = IntKnob("proxy_arp", cvt_name="INT32")


class NetIpv4Neigh(CfgObject):
    """System settings from /proc/sys/net/ipv4/neigh/."""
    gc_thresh3 = IntKnob("gc_thresh3", cvt_name="INT32")


class NetIpv4Route(CfgObject):
    """System settings from /proc/sys/net/ipv4/route/."""
    mtu_expires = IntKnob("mtu_expires", cvt_name="INT32")


class NetIpv4(CfgObject):
    """System settings from /proc/sys/net/ipv4/."""
    ip_forward = IntKnob("ip_forward", cvt_name="INT32")
    ipfrag_max_dist = IntKnob("ipfrag_max_dist", cvt_name="INT32")
    ipfrag_high_thresh = IntKnob("ipfrag_high_thresh", cvt_name="INT32")
    tcp_timestamps = IntKnob("tcp_timestamps", cvt_name="INT32")
    tcp_syncookies = IntKnob("tcp_syncookies", cvt_name="INT32")
    tcp_max_syn_backlog = IntKnob("tcp_max_syn_backlog", cvt_name="INT32")
    tcp_keepalive_time = IntKnob("tcp_keepalive_time", cvt_name="INT32")
    tcp_keepalive_probes = IntKnob("tcp_keepalive_probes", cvt_name="INT32")
    tcp_keepalive_intvl = IntKnob("tcp_keepalive_intvl", cvt_name="INT32")
    tcp_retries2 = IntKnob("tcp_retries2", cvt_name="INT32")
    tcp_orphan_retries = IntKnob("tcp_orphan_retries", cvt_name="INT32")
    tcp_syn_retries = IntKnob("tcp_syn_retries", cvt_name="INT32")
    tcp_synack_retries = IntKnob("tcp_synack_retries", cvt_name="INT32")
    tcp_fin_timeout = IntKnob("tcp_fin_timeout", cvt_name="INT32")
    tcp_wmem = IntKnob("tcp_wmem", cvt_name="INT32")
    tcp_rmem = IntKnob("tcp_rmem", cvt_name="INT32")
    tcp_sack = IntKnob("tcp_sack", cvt_name="INT32")
    tcp_dsack = IntKnob("tcp_dsack", cvt_name="INT32")
    igmp_max_memberships = IntKnob("igmp_max_memberships", cvt_name="INT32")
    tcp_early_retrans = IntKnob("tcp_early_retrans", cvt_name="INT32")
    fib_multipath_hash_policy = IntKnob(
        "fib_multipath_hash_policy",
        cvt_name="INT32")
    ip_default_ttl = IntKnob("ip_default_ttl", cvt_name="INT32")
    tcp_congestion_control = StrKnob("tcp_congestion_control")
    icmp_ratelimit = IntKnob("icmp_ratelimit", cvt_name="INT32")
    conf = SubObject("conf", NetIpv4Conf)
    neigh = SubObject("neigh", NetIpv4Neigh)
    route = SubObject("route", NetIpv4Route)


class NetIpv6Neigh(CfgObject):
    pass


class NetIpv6Conf(CfgObject):
    """System settings from /proc/sys/net/ipv6/conf/."""
    disable_ipv6 = IntKnob("disable_ipv6", cvt_name="INT32")
    forwarding = IntKnob("forwarding", cvt_name="INT32")
    proxy_ndp = IntKnob("proxy_ndp", cvt_name="INT32")
    keep_addr_on_down = IntKnob("keep_addr_on_down", cvt_name="INT32")
    hop_limit = IntKnob("hop_limit", cvt_name="INT32")


class NetIpv6Route(CfgObject):
    mtu_expires = IntKnob("mtu_expires", cvt_name="INT32")


class NetIpv6(CfgObject):
    neigh = SubObject("neigh", NetIpv6Neigh)
    auto_flowlabels = IntKnob("auto_flowlabels", cvt_name="INT32")
    conf = SubObject("conf", NetIpv6Conf)
    route = SubObject("route", NetIpv6Route)
    fib_multipath_hash_policy = IntKnob(
        "fib_multipath_hash_policy",
        cvt_name="INT32")


class Net(CfgObject):
    """System settings from /proc/sys/net/.

    Objects corresponding to files under /proc/sys/net.

    To make particular parameter from /proc/sys/net/* paths
    available, you should also register an object named after
    that parameter under appropriate object corresponding
    to a directory.
    """
    core = SubObject("core", NetCore)
    netfilter = SubObject("netfilter", NetNetfilter)
    ipv4 = SubObject("ipv4", NetIpv4)
    ipv6 = SubObject("ipv6", NetIpv6)


class Debug(CfgObject):
    """System settings from /proc/sys/debug."""
    exception_trace = IntKnob("exception-trace", cvt_name="INT32")


class Sys(CfgObject):
    """System settings from /proc/sys/."""
    console_loglevel = IntKnob("console_loglevel", cvt_name="INT32")
    core_pattern = StrKnob("core_pattern")
    vm = SubObject("vm", Vm)
    fs = SubObject("fs", Fs)
    net = SubObject("net", Net)
    debug = SubObject("debug", Debug)

    def __init__(self, ta):
        super().__init__(f"/agent:{ta}/sys:")
