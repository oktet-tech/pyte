# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""CSAP wrappers over tapi_tad: create, send, receive packets.

Memory model: each received packet is an asn_value owned by Python
(the tapi_tad receive callback hands over ownership); a Packet frees
its handle explicitly via free() or in __del__.
"""
from __future__ import annotations

from pyte.errors import check
from pyte.log import _enc
from pyte.tad.dsl import Layer, Stack, stack

#: Default receive timeout (seconds).
DEFAULT_TIMEOUT = 10.0

#: Cached RCF session per agent (one session is enough for a suite).
_sessions: dict[str, int] = {}


def _session(ta: str) -> int:
    """Get (or create and cache) an RCF session on the agent."""
    if ta not in _sessions:
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        check(lib.pyte_ta_session(_enc(ta), out), f"ta_session({ta})")
        _sessions[ta] = out[0]
    return _sessions[ta]


class Packet:
    """One received packet (NDN Raw-Packet asn_value owned by Python).

    Field labels follow NDN read syntax, e.g.
    ``pdus.0.#udp.src-port.#plain``; the payload is available as bytes.
    """

    def __init__(self, handle):
        self._h = handle

    def int_field(self, labels: str) -> int:
        """Read an integer field by its NDN labels."""
        from pyte._shim import ffi, lib
        out = ffi.new("int64_t *")
        check(lib.pyte_pkt_read_int(self._h, _enc(labels), out),
              f"pkt.int_field({labels})")
        return out[0]

    @property
    def payload(self) -> bytes:
        """Packet payload (b"" when absent or empty)."""
        from pyte._shim import ffi, lib
        ln = ffi.new("size_t *", 0)
        rc = lib.pyte_pkt_payload(self._h, ffi.NULL, ln)
        if rc == 0:
            return b""
        if lib.pyte_rc_error(rc) != lib.pyte_rc_error(lib.PYTE_ESMALLBUF):
            check(rc, "pkt.payload")
        buf = ffi.new("uint8_t[]", ln[0])
        check(lib.pyte_pkt_payload(self._h, buf, ln), "pkt.payload")
        return bytes(ffi.buffer(buf, ln[0]))

    def free(self) -> None:
        """Free the underlying asn_value (idempotent)."""
        if self._h is not None:
            from pyte._shim import lib
            lib.pyte_pkt_free(self._h)
            self._h = None

    def __del__(self):
        try:
            self.free()
        except Exception:
            pass

    def __repr__(self) -> str:
        state = "freed" if self._h is None else "live"
        return f"<Packet {state}>"


class Receiver:
    """An in-progress receive operation started by Csap.listen()."""

    def __init__(self, csap: "Csap"):
        self._csap = csap
        self._done = False

    def _finish(self, wait: bool) -> list[Packet]:
        from pyte._shim import ffi, lib
        if self._done:
            raise RuntimeError("receive operation already finished")
        self._done = True
        self._csap._rx = None
        out = ffi.new("pyte_pkts *")
        fn = lib.pyte_csap_recv_wait if wait else lib.pyte_csap_recv_stop
        rc = fn(_enc(self._csap.ta), self._csap._session,
                self._csap._handle, out)
        pkts = [Packet(out.pkts[i]) for i in range(out.n)]
        lib.pyte_pkts_free(out)
        # A timeout only means fewer packets matched than requested;
        # report what arrived and let the test judge the count.
        if (rc != 0 and lib.pyte_rc_error(rc) !=
                lib.pyte_rc_error(lib.PYTE_ETIMEDOUT)):
            check(rc, "csap.recv")
        return pkts

    def stop(self) -> list[Packet]:
        """Stop receiving now; return the packets collected so far."""
        return self._finish(wait=False)

    def wait(self) -> list[Packet]:
        """Block until ``count`` packets arrive or the listen timeout
        expires, then return what was received (a timeout is not an
        error — fewer packets than requested may come back).
        """
        return self._finish(wait=True)

    def __repr__(self) -> str:
        state = "finished" if self._done else "active"
        return f"<Receiver {state} on {self._csap!r}>"


class Csap:
    """A CSAP on a test agent, described by the pyte.tad layer DSL.

    Csap(ta, Socket(udp=True, local="127.0.0.1", local_port=9)) or
    Csap(ta, UDP() / IP4() / Ether(device="eth0")).  A context
    manager; destroy() is idempotent.
    """

    def __init__(self, ta: str, spec: Layer | Stack):
        st = stack(spec)
        self._setup(ta, st.stack_id, st.csap_spec())

    @classmethod
    def from_asn(cls, ta: str, stack_id: str, spec_text: str) -> "Csap":
        """Escape hatch: create a CSAP from raw NDN spec text."""
        obj = cls.__new__(cls)
        obj._setup(ta, stack_id, spec_text)
        return obj

    def _setup(self, ta: str, stack_id: str, spec_text: str) -> None:
        from pyte._shim import ffi, lib
        self.ta = ta
        self.stack_id = stack_id
        self._session = _session(ta)
        self._handle: int | None = None
        self._rx: Receiver | None = None
        out = ffi.new("unsigned int *")
        check(lib.pyte_csap_create(_enc(ta), self._session,
                                   _enc(stack_id), _enc(spec_text), out),
              f"csap_create({stack_id})")
        self._handle = out[0]

    def _pdus(self) -> str:
        """Empty pdus matching this CSAP's layers: "udp:{}, ip4:{}"."""
        return ", ".join(f"{name}:{{}}"
                         for name in self.stack_id.split("."))

    # -- traffic -------------------------------------------------------
    def send(self, templ: Layer | Stack | bytes,
             blocking: bool = True) -> None:
        """Send one packet built from a layer stack or raw payload.

        bytes become a payload-only template over this CSAP's layers.
        """
        if isinstance(templ, (bytes, bytearray)):
            text = ("{ pdus { " + self._pdus() + " }, payload bytes:'"
                    + bytes(templ).hex().upper() + "'H }")
        elif isinstance(templ, (Layer, Stack)):
            text = stack(templ).template()
        else:
            raise TypeError(
                f"expected Layer, Stack or bytes, got "
                f"{type(templ).__name__}")
        self.send_asn(text, blocking=blocking)

    def send_asn(self, text: str, blocking: bool = True) -> None:
        """Send one packet from raw NDN template text."""
        from pyte._shim import lib
        check(lib.pyte_csap_send(_enc(self.ta), self._session,
                                 self._handle, _enc(text),
                                 1 if blocking else 0),
              f"csap.send({self.stack_id})")

    def listen(self, pattern: Layer | Stack | str | None = None,
               timeout: float = DEFAULT_TIMEOUT,
               count: int = 0) -> Receiver:
        """Start receiving packets matching pattern (None = match any
        packet on this CSAP's layers: ``{ { pdus { socket:{} } } }``
        for a socket CSAP — the pattern unit must still name every
        layer choice).  count = 0 means no packet limit; collect the
        result with the returned Receiver's wait() or stop().
        """
        from pyte._shim import lib
        if self._rx is not None and not self._rx._done:
            raise RuntimeError("a receive operation is already active")
        if pattern is None:
            text = "{ { pdus { " + self._pdus() + " } } }"
        elif isinstance(pattern, (Layer, Stack)):
            text = stack(pattern).pattern()
        elif isinstance(pattern, str):
            text = pattern
        else:
            raise TypeError(
                f"expected Layer, Stack, str or None, got "
                f"{type(pattern).__name__}")
        check(lib.pyte_csap_recv_start(_enc(self.ta), self._session,
                                       self._handle, _enc(text),
                                       int(timeout * 1000), count),
              f"csap.listen({self.stack_id})")
        self._rx = Receiver(self)
        return self._rx

    # -- lifecycle -----------------------------------------------------
    def destroy(self) -> None:
        """Destroy the CSAP (idempotent); stops any active receive."""
        from pyte._shim import lib
        if self._handle is None:
            return
        if self._rx is not None and not self._rx._done:
            try:
                self._rx.stop()
            except Exception:
                pass
        check(lib.pyte_csap_destroy(_enc(self.ta), self._session,
                                    self._handle),
              f"csap_destroy({self.stack_id})")
        self._handle = None

    def __enter__(self) -> "Csap":
        return self

    def __exit__(self, *exc) -> bool:
        self.destroy()
        return False

    def __repr__(self) -> str:
        h = "destroyed" if self._handle is None else f"#{self._handle}"
        return f"<Csap {self.stack_id} {h} on {self.ta}>"
