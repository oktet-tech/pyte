# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the pyte.tad packet DSL.

The exact NDN text shapes asserted here were calibrated against TE's
real ASN.1 parser (asn_parse_value_text via the pyte_asn_check shim):
every pinned string parses with rc=0 against the matching ndn_* type.
Pure Python — no TE or shim required to run these tests.
"""
import pytest

from pyte.tad.dsl import ICMP4, IP4, TCP, UDP, Ether, Socket, Stack, stack


# -- composition ------------------------------------------------------

def test_stack_id_composition():
    s = UDP() / IP4() / Ether()
    assert isinstance(s, Stack)
    assert s.stack_id == "udp.ip4.eth"


def test_layer_div_bytes_sets_payload():
    s = UDP() / b"abc"
    assert s.stack_id == "udp"
    assert s.payload == b"abc"


def test_div_does_not_mutate():
    base = UDP() / IP4()
    with_payload = base / b"xy"
    assert base.payload is None
    assert with_payload.payload == b"xy"
    assert with_payload.layers == base.layers


def test_stack_helper():
    assert stack(UDP()).stack_id == "udp"
    s = UDP() / IP4()
    assert stack(s) is s
    with pytest.raises(TypeError):
        stack(b"payload")


def test_unknown_field_raises_typeerror():
    with pytest.raises(TypeError):
        UDP(bogus=1)
    with pytest.raises(TypeError):
        Ether(mac="02:00:00:00:00:01")


# -- csap specs -------------------------------------------------------

def test_csap_spec_udp_ip4():
    s = UDP(local_port=7) / IP4()
    assert s.csap_spec() == \
        "{ layers { udp:{ local-port plain:7 }, ip4:{} } }"


def test_csap_fields_do_not_leak_into_pdus():
    s = UDP(local_port=7) / IP4(local="10.0.0.1")
    assert s.template() == "{ pdus { udp:{}, ip4:{} } }"
    assert s.pattern() == "{ { pdus { udp:{}, ip4:{} } } }"


def test_pdu_fields_do_not_leak_into_csap_spec():
    s = UDP(src_port=5) / IP4(dst="127.0.0.1")
    assert s.csap_spec() == "{ layers { udp:{}, ip4:{} } }"


def test_csap_spec_socket_udp():
    text = Socket(udp=True, local="127.0.0.1",
                  local_port=9).csap_spec()
    assert text == ("{ layers { socket:{ type udp:NULL, "
                    "local-addr plain:'7F000001'H, "
                    "local-port plain:9 } } }")


def test_csap_spec_eth_device():
    text = Ether(device="lo", recv_mode=0x1F).csap_spec()
    assert text == ('{ layers { eth:{ device-id plain:"lo", '
                    "receive-mode 31 } } }")


# -- templates --------------------------------------------------------

def test_template_with_payload():
    s = UDP(dst_port=5) / IP4(dst="127.0.0.1") / b"hi"
    assert s.template() == ("{ pdus { udp:{ dst-port plain:5 }, "
                            "ip4:{ dst-addr plain:'7F000001'H } }, "
                            "payload bytes:'6869'H }")


def test_template_eth_frame():
    s = (Ether(src="02:00:00:00:00:01", dst="02:00:00:00:00:02",
               ether_type=0x88B5) / b"\x01\x02\x03\x04")
    assert s.template() == ("{ pdus { eth:{ "
                            "dst-addr plain:'020000000002'H, "
                            "src-addr plain:'020000000001'H, "
                            "ether-type plain:34997 } }, "
                            "payload bytes:'01020304'H }")


def test_template_empty_payload():
    assert (Socket() / b"").template() == \
        "{ pdus { socket:{} }, payload bytes:''H }"


def test_template_tcp_icmp4():
    assert (TCP(src_port=1, dst_port=2, flags=2) / IP4()).template() == \
        ("{ pdus { tcp:{ src-port plain:1, dst-port plain:2, "
         "flags plain:2 }, ip4:{} } }")
    assert (ICMP4(type=8, code=0) / IP4()).template() == \
        "{ pdus { icmp4:{ type plain:8, code plain:0 }, ip4:{} } }"


# -- patterns ---------------------------------------------------------

def test_pattern_udp_ip4():
    s = UDP(src_port=5) / IP4()
    assert s.pattern() == \
        "{ { pdus { udp:{ src-port plain:5 }, ip4:{} } } }"


def test_pattern_socket_match_all():
    assert Socket().pattern() == "{ { pdus { socket:{} } } }"


# -- field formatting -------------------------------------------------

def test_mac_accepts_bytes_and_separators():
    a = Ether(src=b"\x02\x00\x00\x00\x00\x01").template()
    b = Ether(src="02-00-00-00-00-01").template()
    assert a == b == \
        "{ pdus { eth:{ src-addr plain:'020000000001'H } } }"


def test_mac_wrong_length_rejected():
    with pytest.raises(ValueError):
        Ether(src="02:00:01").template()


def test_socket_type_conflict_rejected():
    with pytest.raises(ValueError):
        Socket(udp=True, fd=3).csap_spec()


def test_socket_fd_type():
    assert Socket(fd=5).csap_spec() == \
        "{ layers { socket:{ type file-descr:5 } } }"


# -- _du_str escaping -------------------------------------------------

def test_du_str_double_quote_escaped():
    """Device name containing a double quote must be escaped, not rejected."""
    text = Ether(device='a"b').csap_spec()
    assert text == '{ layers { eth:{ device-id plain:"a\\"b" } } }'


def test_du_str_backslash_escaped():
    """Backslash in device name must be doubled."""
    text = Ether(device='a\\b').csap_spec()
    assert text == '{ layers { eth:{ device-id plain:"a\\\\b" } } }'


def test_du_str_both_escaped():
    """Backslash followed by double quote: both are escaped in order."""
    text = Ether(device='a\\"b').csap_spec()
    assert text == '{ layers { eth:{ device-id plain:"a\\\\\\"b" } } }'


# -- Stack dual-payload ambiguity -------------------------------------

def test_stack_div_stack_both_payload_raises():
    """Composing two payload-carrying stacks is ambiguous: must raise."""
    s1 = Stack((UDP(),), payload=b"left")
    s2 = Stack((IP4(),), payload=b"right")
    with pytest.raises(ValueError, match="both stacks carry a payload"):
        _ = s1 / s2


def test_stack_div_stack_one_payload_ok():
    """Single-payload composition: payload is preserved (whichever side)."""
    s_left = Stack((UDP(),), payload=b"data")
    s_right = Stack((IP4(),))
    assert (s_left / s_right).payload == b"data"

    s_right2 = Stack((IP4(),), payload=b"data2")
    s_left2 = Stack((UDP(),))
    assert (s_left2 / s_right2).payload == b"data2"
