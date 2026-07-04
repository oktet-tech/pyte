# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RpcSocket enum-API unit tests (type guards need no shim)."""
import pytest

from pyte.rpc.socket import Family, RpcSocket, Shut, SockOpt, SockType


def test_enum_values_map_to_shim_consts():
    assert Family.INET.value == "PYTE_PF_INET"
    assert SockType.STREAM.value == "PYTE_SOCK_STREAM"
    assert SockType.DGRAM.value == "PYTE_SOCK_DGRAM"
    assert SockOpt.SO_REUSEADDR.value == "PYTE_SO_REUSEADDR"
    assert SockOpt.IP_PKTINFO.value == "PYTE_IP_PKTINFO"


def test_open_rejects_non_enum():
    # Type guards run before any shim import, so no TE is needed.
    with pytest.raises(TypeError, match="family must be a Family"):
        RpcSocket.open(object(), family="inet")
    with pytest.raises(TypeError, match="type must be a SockType"):
        RpcSocket.open(object(), type="dgram")


def test_setsockopt_rejects_non_enum():
    sock = RpcSocket(object(), 5)
    with pytest.raises(TypeError, match="opt must be a SockOpt"):
        sock.setsockopt("SO_REUSEADDR", 1)


def test_new_enum_values():
    assert Shut.RD.value == "PYTE_SHUT_RD"
    assert Shut.RDWR.value == "PYTE_SHUT_RDWR"
    assert SockOpt.SO_RCVBUF.value == "PYTE_SO_RCVBUF"
    assert SockOpt.TCP_NODELAY.value == "PYTE_TCP_NODELAY"


def test_shutdown_rejects_non_enum():
    with pytest.raises(TypeError, match="how must be a Shut"):
        RpcSocket(object(), 5).shutdown("rdwr")


def test_getsockopt_rejects_non_enum():
    with pytest.raises(TypeError, match="opt must be a SockOpt"):
        RpcSocket(object(), 5).getsockopt("SO_ERROR")
