# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
# DO NOT EDIT - generated from TE CM YAML by pyte.cfg._gen.
"""Network interface"""
from pyte.cfg import (
    AddrKnob,
    BoolKnob,
    CfgObject,
    Collection,
    IntKnob,
    SelfKnob,
    StrKnob,
    SubObject,
)


class NetAddr(CfgObject):
    """Network address (IPv4 or IPv6) of the interface."""
    value = SelfKnob(cvt_name="INT32")
    broadcast = AddrKnob("broadcast")


class McastLinkAddr(CfgObject):
    """Multicasting MAC address."""
    pass


class Hwtstamp(CfgObject):
    """Hardware timestamping configuration."""
    tx_type = StrKnob("tx_type")
    rx_filter = StrKnob("rx_filter")


class NeighStatic(CfgObject):
    """Static neighbour entries."""
    value = SelfKnob(cvt_name="ADDRESS")


class NeighDynamic(CfgObject):
    """Dynamic neighbour entries."""
    value = SelfKnob(cvt_name="ADDRESS", sync=True)
    state = IntKnob("state", cvt_name="INT32", access="read_only", sync=True)


class NeighProxy(CfgObject):
    """Neighbour proxy entries."""
    pass


class Stats(CfgObject):
    """Interface statistics."""
    value = SelfKnob(cvt_name="STRING", sync=True)
    in_octets = IntKnob(
        "in_octets",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    in_ucast_pkts = IntKnob(
        "in_ucast_pkts",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    in_nucast_pkts = IntKnob(
        "in_nucast_pkts",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    in_discards = IntKnob(
        "in_discards",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    in_errors = IntKnob(
        "in_errors",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    in_unknown_protos = IntKnob(
        "in_unknown_protos",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    out_octets = IntKnob(
        "out_octets",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    out_ucast_pkts = IntKnob(
        "out_ucast_pkts",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    out_nucast_pkts = IntKnob(
        "out_nucast_pkts",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    out_discards = IntKnob(
        "out_discards",
        cvt_name="UINT64",
        access="read_only",
        sync=True)
    out_errors = IntKnob(
        "out_errors",
        cvt_name="UINT64",
        access="read_only",
        sync=True)


class Vlans(CfgObject):
    """Network interface VLANs"""
    value = SelfKnob(cvt_name="STRING")
    ifname = StrKnob("ifname", access="read_only")


class Macvlan(CfgObject):
    """Virtual interface based on link layer address (MAC)"""
    value = SelfKnob(cvt_name="STRING")


class Ipvlan(CfgObject):
    """Virtual IP VLAN interface"""
    value = SelfKnob(cvt_name="STRING")


class CoalesceGlobalParam(CfgObject):
    value = SelfKnob(cvt_name="UINT64")


class CoalesceGlobal(CfgObject):
    """Interrupt coalescing parameters at interface level"""
    param = Collection("param", CoalesceGlobalParam)


class CoalesceQueuesQueueParam(CfgObject):
    value = SelfKnob(cvt_name="UINT64")


class CoalesceQueuesQueue(CfgObject):
    """Interrupt coalescing parameters for a specific queue"""
    param = Collection("param", CoalesceQueuesQueueParam)


class CoalesceQueues(CfgObject):
    """Interrupt coalescing parameters for network interface queues"""
    queue = Collection("queue", CoalesceQueuesQueue, access="read_only")


class Coalesce(CfgObject):
    """Network interface interrupt coalescing parameters"""
    global_ = SubObject("global", CoalesceGlobal)
    queues = SubObject("queues", CoalesceQueues)


class FlowControl(CfgObject):
    """Network interface flow control parameters"""
    autoneg = IntKnob("autoneg", cvt_name="INT32")
    rx = IntKnob("rx", cvt_name="INT32")
    tx = IntKnob("tx", cvt_name="INT32")


class PhyMode(CfgObject):
    """Supported link mode"""
    value = SelfKnob(cvt_name="INT32")


class PhyLpAdvertised(CfgObject):
    """Link mode advertised by link partner"""
    pass


class Phy(CfgObject):
    """Network interface PHY parameters"""
    port = StrKnob("port", access="read_only")
    autoneg = IntKnob("autoneg", cvt_name="INT32")
    duplex_admin = StrKnob("duplex_admin")
    duplex_oper = StrKnob("duplex_oper", access="read_only", sync=True)
    speed_admin = IntKnob("speed_admin", cvt_name="INT32")
    speed_oper = IntKnob(
        "speed_oper",
        cvt_name="INT32",
        access="read_only",
        sync=True)
    mode = Collection("mode", PhyMode)
    lp_advertised = Collection(
        "lp_advertised",
        PhyLpAdvertised,
        access="read_only")
    state = IntKnob("state", cvt_name="INT32", access="read_only", sync=True)
    set_supported = IntKnob(
        "set_supported",
        cvt_name="INT32",
        access="read_only",
        sync=True)


class Eee(CfgObject):
    """Network interface Energy Efficient Ethernet parameters"""
    eee_active = BoolKnob("eee_active", access="read_only", sync=True)
    eee_enabled = BoolKnob("eee_enabled")
    tx_lpi_enabled = IntKnob("tx_lpi_enabled", cvt_name="UINT64")
    tx_lpi_timer = IntKnob("tx_lpi_timer", cvt_name="UINT32")


class Feature(CfgObject):
    """Network interface features"""
    value = SelfKnob(cvt_name="INT32")
    readonly = IntKnob("readonly", cvt_name="INT32", access="read_only")


class PrivateFlag(CfgObject):
    """Network interface private flag"""
    value = SelfKnob(cvt_name="BOOL")


class Private(CfgObject):
    """Network interface private flags"""
    flag = Collection("flag", PrivateFlag)


class ChannelsCombined(CfgObject):
    """NIC combined channel count controls"""
    current = IntKnob("current", cvt_name="INT32")
    maximum = IntKnob(
        "maximum",
        cvt_name="INT32",
        access="read_only",
        sync=True)


class ChannelsOther(CfgObject):
    """NIC other channel count controls"""
    current = IntKnob("current", cvt_name="INT32")
    maximum = IntKnob(
        "maximum",
        cvt_name="INT32",
        access="read_only",
        sync=True)


class ChannelsRx(CfgObject):
    """NIC Rx channel count controls"""
    current = IntKnob("current", cvt_name="INT32")
    maximum = IntKnob(
        "maximum",
        cvt_name="INT32",
        access="read_only",
        sync=True)


class ChannelsTx(CfgObject):
    """NIC Tx channel count controls"""
    current = IntKnob("current", cvt_name="INT32")
    maximum = IntKnob(
        "maximum",
        cvt_name="INT32",
        access="read_only",
        sync=True)


class Channels(CfgObject):
    """NIC channel count controls"""
    combined = SubObject("combined", ChannelsCombined)
    other = SubObject("other", ChannelsOther)
    rx = SubObject("rx", ChannelsRx)
    tx = SubObject("tx", ChannelsTx)


class RingRx(CfgObject):
    """NIC Rx ring size configuration."""
    max = IntKnob("max", cvt_name="INT64", access="read_only")
    current = IntKnob("current", cvt_name="INT64")


class RingTx(CfgObject):
    """NIC Tx ring size configuration."""
    max = IntKnob("max", cvt_name="INT64", access="read_only")
    current = IntKnob("current", cvt_name="INT64")


class Ring(CfgObject):
    """NIC ring size configuration."""
    rx = SubObject("rx", RingRx)
    tx = SubObject("tx", RingTx)


class Deviceinfo(CfgObject):
    """Network interface info"""
    drivername = StrKnob("drivername", access="read_only")
    driverversion = StrKnob("driverversion", access="read_only")
    firmwareversion = StrKnob("firmwareversion", access="read_only")


class XstatsXstat(CfgObject):
    """Network interface certain extended statistic"""
    value = SelfKnob(cvt_name="UINT64", sync=True)


class Xstats(CfgObject):
    """Network interface extended statistics"""
    xstat = Collection("xstat", XstatsXstat, access="read_only")


class IrqCpu(CfgObject):
    """Interrupt counter per CPU"""
    value = SelfKnob(cvt_name="UINT64", sync=True)


class Irq(CfgObject):
    """Network interface interrupt information"""
    name_ = StrKnob("name", access="read_only")
    cpu = Collection("cpu", IrqCpu, access="read_only")
    smp_affinity = StrKnob("smp_affinity")


class Interface(CfgObject):
    """Network interface"""
    switch_id = StrKnob("switch_id", access="read_only", sync=True)
    port_id = StrKnob("port_id", access="read_only", sync=True)
    port_name = StrKnob("port_name", access="read_only", sync=True)
    index = IntKnob("index", cvt_name="INT32", access="read_only", sync=True)
    net_addr = Collection("net_addr", NetAddr)
    mcast_link_addr = Collection("mcast_link_addr", McastLinkAddr)
    link_addr = AddrKnob("link_addr")
    bcast_link_addr = AddrKnob("bcast_link_addr")
    min_mtu = IntKnob("min_mtu", cvt_name="UINT16", access="read_only")
    max_mtu = IntKnob("max_mtu", cvt_name="UINT16", access="read_only")
    mtu = IntKnob("mtu", cvt_name="INT32")
    ip4_ttl = IntKnob("ip4_ttl", cvt_name="INT32")
    status = IntKnob("status", cvt_name="INT32")
    oper_status = IntKnob(
        "oper_status",
        cvt_name="INT32",
        access="read_only",
        sync=True)
    hwtstamp = SubObject("hwtstamp", Hwtstamp)
    promisc = IntKnob("promisc", cvt_name="INT32")
    allmulti = BoolKnob("allmulti")
    arp = IntKnob("arp", cvt_name="INT32")
    neigh_static = Collection("neigh_static", NeighStatic)
    neigh_dynamic = Collection("neigh_dynamic", NeighDynamic)
    neigh_proxy = Collection("neigh_proxy", NeighProxy)
    stats = SubObject("stats", Stats)
    vlans = Collection("vlans", Vlans)
    macvlan = Collection("macvlan", Macvlan)
    ipvlan = Collection("ipvlan", Ipvlan)
    parent = StrKnob("parent", access="read_only")
    kind = StrKnob("kind", access="read_only")
    coalesce = SubObject("coalesce", Coalesce)
    flow_control = SubObject("flow_control", FlowControl)
    phy = SubObject("phy", Phy)
    eee = SubObject("eee", Eee)
    feature = Collection("feature", Feature)
    private = SubObject("private", Private)
    channels = SubObject("channels", Channels)
    ring = SubObject("ring", Ring)
    msglvl = IntKnob("msglvl", cvt_name="UINT64")
    deviceinfo = SubObject("deviceinfo", Deviceinfo)
    reset = IntKnob("reset", cvt_name="INT32", sync=True)
    xstats = SubObject("xstats", Xstats)
    irq = Collection("irq", Irq, access="read_only")

    def __init__(self, ta, ifname):
        super().__init__(f"/agent:{ta}/interface:{ifname}")
