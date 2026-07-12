# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
# DO NOT EDIT - generated from TE CM YAML by pyte.cfg._gen.
"""The root of all PCI related information."""
from pyte.cfg import (
    CfgObject,
    Collection,
    IntKnob,
    SelfKnob,
    StrKnob,
    SubObject,
)


class DeviceVpd(CfgObject):
    """VPD tag. Since a set of VPD tags is open, we use a list of tags indexed
    by their two character-name (e.g. 'PN' or 'SN'), not a subtree with
    fixed set of nodes.
    """
    value = SelfKnob(cvt_name="STRING")


class DeviceInterrupt(CfgObject):
    """Allocated device interrupts"""
    value = SelfKnob(cvt_name="STRING")


class DeviceNet(CfgObject):
    """Device's network interfaces"""
    value = SelfKnob(cvt_name="STRING")


class DeviceDev(CfgObject):
    """Block/char device's"""
    pass


class DeviceSriovVf(CfgObject):
    """An OID (/agent/hardware/pci/device) of a virtual function allocated
    for a given PF.
    """
    value = SelfKnob(cvt_name="STRING")


class DeviceSriov(CfgObject):
    """Virtual function management"""
    value = SelfKnob(cvt_name="INT32")
    num_vfs = IntKnob("num_vfs", cvt_name="INT32")
    pf = StrKnob("pf", access="read_only")
    vf = Collection("vf", DeviceSriovVf)


class DeviceEswitch(CfgObject):
    """Availability of eswitch interface on a given PCI device"""
    value = SelfKnob(cvt_name="BOOL")
    mode = StrKnob("mode")


class DeviceParamValue(CfgObject):
    """Parameter value"""
    value = SelfKnob(cvt_name="STRING")


class DeviceParam(CfgObject):
    """Device parameter"""
    driver_specific = IntKnob(
        "driver_specific",
        cvt_name="INT32",
        access="read_only")
    type = StrKnob("type", access="read_only")
    value_ = Collection("value", DeviceParamValue)


class DevicePower(CfgObject):
    """@todo Power management"""
    pass


class DeviceSpdkConfig(CfgObject):
    """SPDK configuration associated with a device.

    @note This may only be created if the device is an NVMe device.
    """
    filename = StrKnob("filename", access="read_only")


class DevicePcie(CfgObject):
    """PCIe-specific subtree"""
    value = SelfKnob(cvt_name="INT32")
    max_supported_payload_size = IntKnob(
        "max_supported_payload_size",
        cvt_name="INT32",
        access="read_only")
    max_payload_size = IntKnob(
        "max_payload_size",
        cvt_name="INT32",
        access="read_only")
    max_read_req_size = IntKnob(
        "max_read_req_size",
        cvt_name="INT32",
        access="read_only")
    max_link_speed = IntKnob(
        "max_link_speed",
        cvt_name="INT32",
        access="read_only")
    max_link_width = IntKnob(
        "max_link_width",
        cvt_name="INT32",
        access="read_only")
    link_speed = IntKnob("link_speed", cvt_name="INT32", access="read_only")
    link_width = IntKnob("link_width", cvt_name="INT32", access="read_only")


class DeviceStatus(CfgObject):
    """Basic error reporting container
    @todo Both plain error status report and ARE support various
    configuration option, like changing
    the severity of an error or enabling/disabling its reporting.
    Corresponding nodes may be defined here read-write, but it needs
    further investigation how it can interact with kernel/drivers.
    """
    correctable_error = IntKnob(
        "correctable_error",
        cvt_name="INT32",
        access="read_only")
    uncorrectable_error = IntKnob(
        "uncorrectable_error",
        cvt_name="INT32",
        access="read_only")
    fatal_error = IntKnob("fatal_error", cvt_name="INT32", access="read_only")
    unsupported_request = IntKnob(
        "unsupported_request",
        cvt_name="INT32",
        access="read_only")


class DeviceAerUncorrectableError(CfgObject):
    """A specific uncorrectable error happened. This is a list of values
    indexed by an error name.
    The following error names are defined as per PCIe spec:
    - unsupported_request
    - data_link_protocol_error
    - poisoned_tlp
    - flow_control_protocol_error
    - completion_timeout
    - completer_abort
    - unexpected_completion
    - receiver_overflow
    - malformed_tlp
    - ecrc_error
    - unsupported_request_error
    """
    value = SelfKnob(cvt_name="INT32")


class DeviceAerCorrectableError(CfgObject):
    """A specific correctable error happened.  This is a list of values
    indexed by an error name.
    The following error names are defined as per PCIe spec:
    - receiver_error
    - bad_tlp
    - bad_dllp
    - replay_num_rollover
    - replay_timer_timeout
    """
    value = SelfKnob(cvt_name="INT32")


class DeviceAer(CfgObject):
    """Advanced Error Reporting container"""
    value = SelfKnob(cvt_name="INT32")
    uncorrectable_error = Collection(
        "uncorrectable_error",
        DeviceAerUncorrectableError,
        access="read_only")
    correctable_error = Collection(
        "correctable_error",
        DeviceAerCorrectableError,
        access="read_only")


class Device(CfgObject):
    """A node for a specific PCI device.

    @todo Do we need any support for Virtual Channel capabilities?
    """
    domain = StrKnob("domain", access="read_only")
    bus = StrKnob("bus", access="read_only")
    slot = StrKnob("slot", access="read_only")
    fn = IntKnob("fn", cvt_name="INT32", access="read_only")
    vendor_id = StrKnob("vendor_id", access="read_only")
    device_id = StrKnob("device_id", access="read_only")
    revision_id = IntKnob("revision_id", cvt_name="INT32", access="read_only")
    subsystem_vendor = StrKnob("subsystem_vendor", access="read_only")
    subsystem_device = StrKnob("subsystem_device", access="read_only")
    class_ = StrKnob("class", access="read_only")
    vpd = Collection("vpd", DeviceVpd, access="read_only")
    interrupt = Collection("interrupt", DeviceInterrupt, access="read_only")
    node = StrKnob("node", access="read_only")
    driver = StrKnob("driver")
    net = Collection("net", DeviceNet, access="read_only")
    dev = Collection("dev", DeviceDev, access="read_only")
    sriov = SubObject("sriov", DeviceSriov)
    eswitch = SubObject("eswitch", DeviceEswitch)
    param = Collection("param", DeviceParam, access="read_only")
    serialno = StrKnob("serialno", access="read_only")
    power = SubObject("power", DevicePower)
    spdk_config = Collection("spdk_config", DeviceSpdkConfig)
    pcie = SubObject("pcie", DevicePcie)
    status = SubObject("status", DeviceStatus)
    aer = SubObject("aer", DeviceAer)


class VendorDeviceInstance(CfgObject):
    """Reference to PCI devices with given vendor/device ID"""
    value = SelfKnob(cvt_name="STRING")


class VendorDevice(CfgObject):
    """List of PCI devices IDs for a given vendor for installed devices"""
    instance = Collection("instance", VendorDeviceInstance, access="read_only")


class Vendor(CfgObject):
    """The list of PCI vendor IDs for installed devices.
    We do not want the agent exposes the whole PCI tree to tests
    because it's an unnecessary overhead for agents and configurator:
    On a modern system, there are tons of PCI devices, most of which are
    system support devices which should not be ever useful for testing
    purposes; and trying to obtain information from all these devices
    takes a lot of time.

    The second consideration is that we want to reserve PCI devices
    using the configurator /agent/rsrc. It is not convenient to specify
    direct PCI address, because it makes configuration too fragile.
    It would be preferable to specify just "the first function of a
    certain NIC" etc.

    On the other hand, using vendor+device+ordinal as a sole identifier
    for PCI devices is also not convenient, because in several places we
    have a system-provided PCI address, and to map it to
    vendor+device+ordinal requires scanning the whole PCI tree.

    So the procedure is as follows: if a test is interested in some
    devices, it makes a resource with
    /agent/hardware/pci/vendor:VENDOR/device:DEVICE/instance:NTH as value.
    The agent then will do PCI scanning and:
    - create /agent/hardware/pci/vendor:VENDOR/device:DEVICE/instance:NTH
      having the real OID of the PCI device
    - create /agent/hardware/pci/device:ADDRESS node corresponding to
      the real device

    All levels of the hierarchy may be used for locking. That is,
    assigning /agent/hardware/pci to /agent/rsrc would lock the whole
    PCI tree (which is only possible if nobody else is holding any PCI
    device locks), and the whole PCI tree will be made accessible
    Locking /agent/hardware/pci/vendor and
    /agent/hardware/pci/vendor/device will, in the same manner, result
    in a set of devices being made accessible.

    Locking /agent/hardware/pci/vendor is necessary for SRIOV support,
    because normally one would like to access VFs just created.
    """
    device = Collection("device", VendorDevice, access="read_only")


class Pci(CfgObject):
    """The root of all PCI related information.

    @note This subtree is not intended for low-level operations with
    PCI devices, the configurator is not deterministic enough for it
    to be safe. So most of the underlying nodes are read-only, even
    if PCI technically allows read-write access.  The only exceptions
    are driver binding (/agent/hardware/pci/device/driver) and
    VF management (/agent/hardware/pci/device/sriov/vf).
    """
    device = Collection("device", Device, access="read_only")
    vendor = Collection("vendor", Vendor, access="read_only")

    def __init__(self, ta):
        super().__init__(f"/agent:{ta}/hardware:/pci:")
