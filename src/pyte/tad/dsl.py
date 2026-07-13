# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Scapy-inspired layered packet DSL compiling to TE NDN ASN.1 text.

Pure Python on purpose: this module must stay importable (and unit
testable) with no TE installation and no pyte shim at all.

Composition is payload-side first, outermost last::

    UDP(dst_port=5) / IP4(dst="127.0.0.1") / Ether() / b"data"

which yields stack_id ``"udp.ip4.eth"`` and renders pdus in the same
order (TE convention: ``pdus`` index 0 is the uppermost protocol).

NDN text shapes (calibrated against TE's asn_parse_value_text() via
the pyte_asn_check() shim; authoritative field tables live in
te/lib/ndn/ndn_ipstack.c, ndn_eth.c, ndn_socket.c):

- CSAP spec:  ``{ layers { udp:{ local-port plain:7 }, ip4:{} } }``
- Template:   ``{ pdus { udp:{ dst-port plain:5 }, ip4:{} },
  payload bytes:'6869'H }``
- Pattern:    ``{ { pdus { udp:{ src-port plain:5 }, ip4:{} } } }``
  (one Generic-Pattern-Unit; the extra braces are the unit sequence).

Syntax notes discovered during calibration:

- Data-unit fields take a choice prefix: ``plain:5``, octet strings
  are ``plain:'7F000001'H``, char strings ``plain:"lo"``.
- Plain-integer fields (eth ``receive-mode``) take a bare integer.
- The socket CSAP ``type`` field is a choice of NULLs:
  ``type udp:NULL`` (or ``file-descr:3`` for an fd-based CSAP).
- An empty layer must still name its choice: ``udp:{}``.
- Sequence fields may not repeat; field order follows the C tables.
"""
from __future__ import annotations

import ipaddress
from typing import Callable, Union

__all__ = ["Layer", "Ether", "IP4", "UDP", "TCP", "ICMP4", "Socket",
           "Stack", "stack"]


# ---------------------------------------------------------------------
# Field value formatters (value -> NDN value text)

def _du_int(v) -> str:
    """Data-unit integer: ``plain:5``."""
    return f"plain:{int(v)}"


def _int(v) -> str:
    """Bare integer (non-data-unit fields like eth receive-mode)."""
    return f"{int(v)}"


def _du_str(v) -> str:
    """Data-unit character string: ``plain:"lo"``.

    Backslashes and double quotes are escaped (``\\`` → ``\\\\``,
    ``"`` → ``\\"``); TE's ASN.1 charstring parser (asn_text.c)
    recognises both sequences.
    """
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'plain:"{s}"'


def _du_ip4(v) -> str:
    """IPv4 address as a 4-byte octet string: ``plain:'7F000001'H``."""
    return f"plain:'{ipaddress.IPv4Address(v).packed.hex().upper()}'H"


def _du_mac(v) -> str:
    """MAC address as a 6-byte octet string: ``plain:'02..01'H``."""
    if isinstance(v, (bytes, bytearray)):
        raw = bytes(v)
    else:
        raw = bytes.fromhex(str(v).replace(":", "").replace("-", ""))
    if len(raw) != 6:
        raise ValueError(f"MAC address must be 6 bytes: {v!r}")
    return f"plain:'{raw.hex().upper()}'H"


def _socket_type(choice: str) -> Callable[[object], str]:
    """Socket CSAP ``type`` choice: ``udp:NULL``/``tcp-server:NULL``."""
    def fmt(v) -> str:
        if v is not True:
            raise ValueError(f"{choice} flag must be True if given")
        return f"{choice}:NULL"
    return fmt


def _socket_fd(v) -> str:
    """Socket CSAP ``type`` choice over an existing fd."""
    return f"file-descr:{int(v)}"


# ---------------------------------------------------------------------
# Layers

class Layer:
    """One protocol layer; subclasses define NAME/FIELDS/CSAP_ONLY.

    FIELDS maps a Python kwarg to ``(ndn-field-name, formatter)``;
    kwargs listed in CSAP_ONLY render only into CSAP specs, all other
    kwargs render only into PDUs (templates/patterns).  Several kwargs
    may map to the same NDN field (socket udp/fd); giving more than
    one of them at once is an error.
    """

    NAME: str = ""
    FIELDS: dict[str, tuple[str, Callable[[object], str]]] = {}
    CSAP_ONLY: frozenset[str] = frozenset()

    def __init__(self, **fields):
        unknown = sorted(set(fields) - set(self.FIELDS))
        if unknown:
            raise TypeError(f"{type(self).__name__}: unknown field(s): "
                            + ", ".join(unknown))
        self._fields = fields

    def _text(self, csap: bool) -> str:
        """Render the layer body for a CSAP spec or a PDU."""
        parts = []
        seen: set[str] = set()
        for kwarg, (ndn, fmt) in self.FIELDS.items():
            if (kwarg in self.CSAP_ONLY) != csap:
                continue
            if kwarg not in self._fields:
                continue
            if ndn in seen:
                raise ValueError(
                    f"{type(self).__name__}: conflicting values for "
                    f"NDN field {ndn!r}")
            seen.add(ndn)
            parts.append(f"{ndn} {fmt(self._fields[kwarg])}")
        return "{ " + ", ".join(parts) + " }" if parts else "{}"

    def __truediv__(self, other: "Layer | bytes") -> "Stack":
        return Stack((self,)) / other

    # Single-layer conveniences (Socket(...).csap_spec() etc.)
    def csap_spec(self) -> str:
        return Stack((self,)).csap_spec()

    def template(self) -> str:
        return Stack((self,)).template()

    def pattern(self) -> str:
        return Stack((self,)).pattern()

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self._fields.items())
        return f"{type(self).__name__}({args})"


class Ether(Layer):
    """Ethernet (IEEE 802.3) layer; PDU dst/src/ether_type, CSAP
    device/recv_mode/local_mac/remote_mac (ndn_eth.c tables)."""
    NAME = "eth"
    FIELDS = {
        # CSAP spec fields (Ethernet-CSAP)
        "device": ("device-id", _du_str),
        "recv_mode": ("receive-mode", _int),
        "local_mac": ("local-addr", _du_mac),
        "remote_mac": ("remote-addr", _du_mac),
        # PDU fields (IEEE-Std-802.3-Header) — dst before src!
        "dst": ("dst-addr", _du_mac),
        "src": ("src-addr", _du_mac),
        "ether_type": ("ether-type", _du_int),
    }
    CSAP_ONLY = frozenset({"device", "recv_mode", "local_mac",
                           "remote_mac"})


class IP4(Layer):
    """IPv4 layer; PDU ttl/protocol/src/dst, CSAP local/remote."""
    NAME = "ip4"
    FIELDS = {
        "local": ("local-addr", _du_ip4),
        "remote": ("remote-addr", _du_ip4),
        "ttl": ("time-to-live", _du_int),
        "protocol": ("protocol", _du_int),
        "src": ("src-addr", _du_ip4),
        "dst": ("dst-addr", _du_ip4),
    }
    CSAP_ONLY = frozenset({"local", "remote"})


class UDP(Layer):
    """UDP layer; PDU src_port/dst_port, CSAP local_port/remote_port."""
    NAME = "udp"
    FIELDS = {
        "local_port": ("local-port", _du_int),
        "remote_port": ("remote-port", _du_int),
        "src_port": ("src-port", _du_int),
        "dst_port": ("dst-port", _du_int),
    }
    CSAP_ONLY = frozenset({"local_port", "remote_port"})


class TCP(Layer):
    """TCP layer; like UDP plus seqn/ackn/flags/win_size."""
    NAME = "tcp"
    FIELDS = {
        "local_port": ("local-port", _du_int),
        "remote_port": ("remote-port", _du_int),
        "src_port": ("src-port", _du_int),
        "dst_port": ("dst-port", _du_int),
        "seqn": ("seqn", _du_int),
        "ackn": ("ackn", _du_int),
        "flags": ("flags", _du_int),
        "win_size": ("win-size", _du_int),
    }
    CSAP_ONLY = frozenset({"local_port", "remote_port"})


class ICMP4(Layer):
    """ICMPv4 layer; PDU type/code."""
    NAME = "icmp4"
    FIELDS = {
        "type": ("type", _du_int),
        "code": ("code", _du_int),
    }


class Socket(Layer):
    """Data-level 'socket' TAD layer (CSAP-only fields, no root
    needed): a CSAP over a normal kernel socket (ndn_socket.c).

    ``udp=True`` selects a UDP socket; ``fd=N`` wraps an existing fd.
    A udp (or tcp_client) CSAP is a *connected* socket: the agent
    connect()s it, so ``remote`` and ``remote_port`` are mandatory
    for those types (tad_socket_stack.c returns ETADWRONGNDS
    otherwise) and only traffic from that peer is received.
    """
    NAME = "socket"
    FIELDS = {
        "udp": ("type", _socket_type("udp")),
        "tcp_server": ("type", _socket_type("tcp-server")),
        "tcp_client": ("type", _socket_type("tcp-client")),
        "fd": ("type", _socket_fd),
        "local": ("local-addr", _du_ip4),
        "remote": ("remote-addr", _du_ip4),
        "local_port": ("local-port", _du_int),
        "remote_port": ("remote-port", _du_int),
    }
    CSAP_ONLY = frozenset(FIELDS)


# ---------------------------------------------------------------------
# Stack

class Stack:
    """An ordered pile of layers plus an optional payload.

    Immutable: ``/`` returns a new Stack.  Layer order is payload-side
    first (uppermost protocol at index 0), matching NDN pdus order.
    """

    def __init__(self, layers: tuple[Layer, ...] | list[Layer],
                 payload: bytes | None = None):
        self.layers: tuple[Layer, ...] = tuple(layers)
        self.payload = payload

    def __truediv__(self, other: Union[Layer, "Stack", bytes]) -> "Stack":
        if isinstance(other, Layer):
            return Stack(self.layers + (other,), self.payload)
        if isinstance(other, Stack):
            if self.payload is not None and other.payload is not None:
                raise ValueError("both stacks carry a payload")
            payload = other.payload if other.payload is not None \
                else self.payload
            return Stack(self.layers + other.layers, payload)
        if isinstance(other, (bytes, bytearray)):
            return Stack(self.layers, bytes(other))
        return NotImplemented

    @property
    def stack_id(self) -> str:
        """CSAP stack id for tapi_tad_csap_create(): "udp.ip4.eth"."""
        return ".".join(layer.NAME for layer in self.layers)

    def _pdus(self) -> str:
        inner = ", ".join(f"{lr.NAME}:{lr._text(csap=False)}"
                          for lr in self.layers)
        return "pdus { " + inner + " }"

    def csap_spec(self) -> str:
        """NDN CSAP spec text: ``{ layers { ... } }``."""
        inner = ", ".join(f"{lr.NAME}:{lr._text(csap=True)}"
                          for lr in self.layers)
        return "{ layers { " + inner + " } }"

    def template(self) -> str:
        """NDN traffic template text: ``{ pdus { ... } }``."""
        if self.payload is None:
            return "{ " + self._pdus() + " }"
        return ("{ " + self._pdus()
                + f", payload bytes:'{self.payload.hex().upper()}'H }}")

    def pattern(self) -> str:
        """NDN traffic pattern text (one pattern unit)."""
        return "{ { " + self._pdus() + " } }"

    def __repr__(self) -> str:
        body = " / ".join(repr(lr) for lr in self.layers)
        if self.payload is not None:
            body += f" / {self.payload!r}"
        return f"<Stack {body}>"


def stack(obj: Layer | Stack) -> Stack:
    """Coerce a Layer or Stack to a Stack."""
    if isinstance(obj, Stack):
        return obj
    if isinstance(obj, Layer):
        return Stack((obj,))
    raise TypeError(f"expected Layer or Stack, got {type(obj).__name__}")
