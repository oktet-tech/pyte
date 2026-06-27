# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Multiplexed waiting on remote sockets (tapi_iomux)."""
from __future__ import annotations

import enum

from pyte.errors import RpcError, check


class Evt(enum.Flag):
    """Event flags for :class:`IoMux`; compose with ``|``.

    Symbolic, pyte-local values; the integer bits the TAPI uses are
    resolved lazily from the shim (see :data:`EVENT_BITS`).
    """

    IN = enum.auto()
    PRI = enum.auto()
    OUT = enum.auto()
    EXC = enum.auto()
    ERR = enum.auto()
    HUP = enum.auto()
    RDHUP = enum.auto()
    ET = enum.auto()
    ONESHOT = enum.auto()
    NVAL = enum.auto()


class Kind(enum.Enum):
    """Multiplexer kind (which syscall family tapi_iomux uses).

    Each value is the name of the corresponding PYTE_IOMUX_* shim constant.
    """

    SELECT = "PYTE_IOMUX_SELECT"
    PSELECT = "PYTE_IOMUX_PSELECT"
    POLL = "PYTE_IOMUX_POLL"
    PPOLL = "PYTE_IOMUX_PPOLL"
    EPOLL = "PYTE_IOMUX_EPOLL"
    EPOLL_PWAIT = "PYTE_IOMUX_EPOLL_PWAIT"
    EPOLL_PWAIT2 = "PYTE_IOMUX_EPOLL_PWAIT2"


#: Map from Evt member to the corresponding PYTE_IOMUX_EVT_* shim constant.
_EVT_CONSTS = {
    Evt.IN:      "PYTE_IOMUX_EVT_RD",
    Evt.PRI:     "PYTE_IOMUX_EVT_PRI",
    Evt.OUT:     "PYTE_IOMUX_EVT_WR",
    Evt.EXC:     "PYTE_IOMUX_EVT_EXC",
    Evt.ERR:     "PYTE_IOMUX_EVT_ERR",
    Evt.HUP:     "PYTE_IOMUX_EVT_HUP",
    Evt.RDHUP:   "PYTE_IOMUX_EVT_RDHUP",
    Evt.ET:      "PYTE_IOMUX_EVT_ET",
    Evt.ONESHOT: "PYTE_IOMUX_EVT_ONESHOT",
    Evt.NVAL:    "PYTE_IOMUX_EVT_NVAL",
}

#: Lazy dict: Evt member -> integer bit value (populated from the shim on
#: first use so unit tests with a fake shim can supply the values).
EVENT_BITS: dict[Evt, int] = {}


def _ensure_event_bits() -> None:
    """Populate EVENT_BITS lazily from the shim constants."""
    if EVENT_BITS:
        return
    from pyte._shim import lib
    for member, const in _EVT_CONSTS.items():
        EVENT_BITS[member] = int(getattr(lib, const))


def _evt_bits(events: Evt) -> int:
    """Convert an :class:`Evt` flag into the TAPI integer bit mask."""
    if not isinstance(events, Evt):
        raise TypeError(
            f"events must be an Evt flag, not {type(events).__name__}")
    _ensure_event_bits()
    bits = 0
    for member in events:
        bits |= EVENT_BITS[member]
    return bits


def _evt_flag(bits: int) -> Evt:
    """Decode a TAPI integer bit mask back into an :class:`Evt` flag."""
    _ensure_event_bits()
    flag = Evt(0)
    for member, bit in EVENT_BITS.items():
        if bits & bit:
            flag |= member
    return flag


class IoMux:
    """A remote select/poll/epoll multiplexer.

    Use as a context manager or call ``close()`` explicitly::

        from pyte.rpc.iomux import Evt, Kind

        with pco.iomux(Kind.EPOLL) as mux:
            mux.add(sock, Evt.IN)
            events = mux.wait(1.0)   # [(fd, Evt.IN|...), ...]

    ``wait()`` returns an empty list on timeout (n == 0 from
    tapi_iomux_call); this is NOT an error — callers should check for ``[]``
    explicitly when they care about the distinction.

    ``add()`` / ``mod()`` accept either an int fd or any object with a
    ``.fd`` attribute (e.g. an ``RpcSocket``), plus an :class:`Evt` flag.
    """

    def __init__(self, server, handle):
        self._server = server
        self._h = handle

    @classmethod
    def create(cls, server, kind: Kind = Kind.EPOLL) -> "IoMux":
        """Create a new iomux of the given *kind* on *server*."""
        from pyte._shim import ffi, lib
        if not isinstance(kind, Kind):
            raise TypeError(
                f"kind must be a Kind, not {type(kind).__name__}")
        kind_const = getattr(lib, kind.value)
        out = ffi.new("tapi_iomux_handle **")
        check(lib.pyte_iomux_create(server._h, kind_const, out),
              f"iomux_create({kind.name})", RpcError)
        return cls(server, out[0])

    # -- fd helpers -------------------------------------------------------

    @staticmethod
    def _fd(sock_or_fd) -> int:
        return getattr(sock_or_fd, "fd", sock_or_fd)

    # -- lifecycle --------------------------------------------------------

    def close(self) -> None:
        """Destroy the remote multiplexer (idempotent)."""
        if self._h is None:
            return
        from pyte._shim import lib
        check(lib.pyte_iomux_destroy(self._h),
              f"iomux_destroy on {self._server!r}", RpcError)
        self._h = None

    def __enter__(self) -> "IoMux":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    # -- fd management ----------------------------------------------------

    def add(self, sock_or_fd, events: Evt) -> None:
        """Add *sock_or_fd* to the multiplexer watching *events*."""
        if self._h is None:
            raise RuntimeError("IoMux is closed")
        from pyte._shim import lib
        fd = self._fd(sock_or_fd)
        bits = _evt_bits(events)
        check(lib.pyte_iomux_add(self._h, fd, bits),
              f"iomux_add(fd={fd}, events={events!r})", RpcError)

    def mod(self, sock_or_fd, events: Evt) -> None:
        """Modify the watched *events* for *sock_or_fd*."""
        if self._h is None:
            raise RuntimeError("IoMux is closed")
        from pyte._shim import lib
        fd = self._fd(sock_or_fd)
        bits = _evt_bits(events)
        check(lib.pyte_iomux_mod(self._h, fd, bits),
              f"iomux_mod(fd={fd}, events={events!r})", RpcError)

    def delete(self, sock_or_fd) -> None:
        """Remove *sock_or_fd* from the multiplexer."""
        if self._h is None:
            raise RuntimeError("IoMux is closed")
        from pyte._shim import lib
        fd = self._fd(sock_or_fd)
        check(lib.pyte_iomux_del(self._h, fd),
              f"iomux_del(fd={fd})", RpcError)

    # -- waiting ----------------------------------------------------------

    def wait(self, timeout: float = -1.0) -> list[tuple[int, Evt]]:
        """Wait up to *timeout* seconds for events.

        Returns a list of ``(fd, Evt)`` pairs — one per ready file
        descriptor.  Returns an empty list on timeout (n == 0).

        *timeout* < 0 means block indefinitely (passed as -1 ms to the TAPI).
        """
        if self._h is None:
            raise RuntimeError("IoMux is closed")
        from pyte._shim import ffi, lib
        timeout_ms = -1 if timeout < 0 else int(timeout * 1000)
        n_out = ffi.new("int *")
        revts_p = ffi.new("int **")
        check(lib.pyte_iomux_call(self._h, timeout_ms, n_out, revts_p),
              f"iomux_call(timeout={timeout}s)", RpcError)
        n = n_out[0]
        if n == 0:
            return []
        revts_arr = revts_p[0]
        try:
            flat = ffi.unpack(revts_arr, 2 * n)
            result = [
                (flat[2 * i], _evt_flag(flat[2 * i + 1]))
                for i in range(n)
            ]
        finally:
            lib.pyte_free_ints(revts_arr)
        return result
