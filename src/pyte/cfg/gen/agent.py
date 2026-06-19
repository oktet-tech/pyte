# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
# DO NOT EDIT - generated from TE CM YAML by pyte.cfg._gen.
"""agent"""
from pyte.cfg import (
    BoolKnob,
    CfgObject,
    IntKnob,
    SelfKnob,
    StrKnob,
    SubObject,
)


class Uname(CfgObject):
    """uname value for the system"""
    value = SelfKnob(cvt_name="STRING")
    version = StrKnob("version", access="read_only")
    release = StrKnob("release", access="read_only")
    machine = StrKnob("machine", access="read_only")


class Agent(CfgObject):
    platform = StrKnob("platform", access="read_only")
    dir = StrKnob("dir", access="read_only", sync=True)
    tmp_dir = StrKnob("tmp_dir", access="read_only", sync=True)
    lib_mod_dir = StrKnob("lib_mod_dir", access="read_only", sync=True)
    lib_bin_dir = StrKnob("lib_bin_dir", access="read_only", sync=True)
    ip4_fw = IntKnob("ip4_fw", cvt_name="INT32")
    ip6_fw = BoolKnob("ip6_fw")
    ip4_rt_default_if = StrKnob(
        "ip4_rt_default_if",
        access="read_only",
        sync=True)
    ip6_rt_default_if = StrKnob(
        "ip6_rt_default_if",
        access="read_only",
        sync=True)
    rpcprovider = StrKnob("rpcprovider")
    rpc_default_timeout = IntKnob("rpc_default_timeout", cvt_name="INT32")
    rp_filter_all = IntKnob("rp_filter_all", cvt_name="INT32")
    uname = SubObject("uname", Uname)

    def __init__(self, ta):
        super().__init__(f"/agent:{ta}")
