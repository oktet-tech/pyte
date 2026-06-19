# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
# DO NOT EDIT - generated from TE CM YAML by pyte.cfg._gen.
"""System module."""
from pyte.cfg import (
    CfgObject,
    Collection,
    IntKnob,
    SelfKnob,
    StrKnob,
    SubObject,
)


class Filename(CfgObject):
    """Name of the file containing the module or 'unknown'.
    modinfo integration is not yet there.
    """
    value = SelfKnob(cvt_name="STRING", sync=True)
    load_dependencies = IntKnob("load_dependencies", cvt_name="INT32")
    fallback = IntKnob("fallback", cvt_name="INT32")


class Parameter(CfgObject):
    """Parameter of a system module."""
    value = SelfKnob(cvt_name="STRING")


class DriverDevice(CfgObject):
    """Reference to a device of a given driver"""
    value = SelfKnob(cvt_name="STRING", sync=True)


class Driver(CfgObject):
    """Driver implemented by a system module."""
    device = Collection("device", DriverDevice)


class Module(CfgObject):
    """System module."""
    loaded = IntKnob("loaded", cvt_name="INT32")
    loaded_oper = IntKnob(
        "loaded_oper",
        cvt_name="INT32",
        access="read_only",
        sync=True)
    unload_holders = IntKnob("unload_holders", cvt_name="INT32")
    filename = SubObject("filename", Filename)
    version = StrKnob("version", access="read_only")
    parameter = Collection("parameter", Parameter)
    driver = Collection("driver", Driver)

    def __init__(self, ta, name):
        super().__init__(f"/agent:{ta}/module:{name}")
