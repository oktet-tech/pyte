# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Multiplexed waiting on remote sockets (tapi_iomux)."""
from __future__ import annotations

from pyte.errors import RpcError, check

#: Ordered event names (human-friendly aliases for tapi_iomux_evt bits).
_EVENT_NAMES = ("in", "pri", "out", "exc", "err", "hup", "rdhup",
                "et", "oneshot", "nval")

#: Map from user-facing event name to the corresponding PYTE_IOMUX_EVT_*
#: constant name in the shim.
_BIT_CONSTS = {
    "in":      "PYTE_IOMUX_EVT_RD",
    "pri":     "PYTE_IOMUX_EVT_PRI",
    "out":     "PYTE_IOMUX_EVT_WR",
    "exc":     "PYTE_IOMUX_EVT_EXC",
    "err":     "PYTE_IOMUX_EVT_ERR",
    "hup":     "PYTE_IOMUX_EVT_HUP",
    "rdhup":   "PYTE_IOMUX_EVT_RDHUP",
    "et":      "PYTE_IOMUX_EVT_ET",
    "oneshot": "PYTE_IOMUX_EVT_ONESHOT",
    "nval":    "PYTE_IOMUX_EVT_NVAL",
}

#: Map from user-facing iomux kind name to PYTE_IOMUX_* constant name.
_KINDS = {
    "select":       "PYTE_IOMUX_SELECT",
    "pselect":      "PYTE_IOMUX_PSELECT",
    "poll":         "PYTE_IOMUX_POLL",
    "ppoll":        "PYTE_IOMUX_PPOLL",
    "epoll":        "PYTE_IOMUX_EPOLL",
    "epoll_pwait":  "PYTE_IOMUX_EPOLL_PWAIT",
    "epoll_pwait2": "PYTE_IOMUX_EPOLL_PWAIT2",
}

#: Lazy dict: event-name -> integer bit value (populated from shim on first
#: access so that unit tests using a fake shim can supply the values directly).
EVENT_BITS: dict[str, int] = {}


def _ensure_event_bits() -> None:
    """Populate EVENT_BITS lazily from the shim constants."""
    if EVENT_BITS:
        return
    from pyte._shim import lib
    for name, const in _BIT_CONSTS.items():
        EVENT_BITS[name] = int(getattr(lib, const))


def _evt_bits(spec: str) -> int:
    """Parse a comma-separated event spec like ``"in,out"`` into a bit mask.

    Raises ``ValueError`` for unrecognised event names.
    """
    _ensure_event_bits()
    bits = 0
    for token in spec.split(","):
        token = token.strip()
        if token not in EVENT_BITS:
            raise ValueError(
                f"unknown iomux event {token!r}; "
                f"valid names: {sorted(EVENT_BITS)}")
        bits |= EVENT_BITS[token]
    return bits


def _evt_names(bits: int) -> set[str]:
    """Decode a bit mask back into a set of event-name strings."""
    _ensure_event_bits()
    return {name for name, bit in EVENT_BITS.items() if bits & bit}


class IoMux:
    """A remote select/poll/epoll multiplexer.

    Use as a context manager or call ``close()`` explicitly::

        with pco.iomux("epoll") as mux:
            mux.add(sock, "in")
            events = mux.wait(1.0)   # [(fd, {"in", ...}), ...]

    ``wait()`` returns an empty list on timeout (n == 0 from
    tapi_iomux_call); this is NOT an error — callers should check for ``[]``
    explicitly when they care about the distinction.

    ``add()`` / ``mod()`` accept either an int fd or any object with a
    ``.fd`` attribute (e.g. an ``RpcSocket``).
    """

    def __init__(self, server, handle):
        self._server = server
        self._h = handle

    @classmethod
    def create(cls, server, kind: str = "epoll") -> "IoMux":
        """Create a new iomux of the given *kind* on *server*."""
        from pyte._shim import ffi, lib
        try:
            kind_const = getattr(lib, _KINDS[kind])
        except KeyError:
            raise ValueError(
                f"unknown iomux kind {kind!r}; "
                f"valid kinds: {sorted(_KINDS)}") from None
        out = ffi.new("tapi_iomux_handle **")
        check(lib.pyte_iomux_create(server._h, kind_const, out),
              f"iomux_create({kind})", RpcError)
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

    def add(self, sock_or_fd, events: str) -> None:
        """Add *sock_or_fd* to the multiplexer watching *events*."""
        if self._h is None:
            raise RuntimeError("IoMux is closed")
        from pyte._shim import lib
        fd = self._fd(sock_or_fd)
        bits = _evt_bits(events)
        check(lib.pyte_iomux_add(self._h, fd, bits),
              f"iomux_add(fd={fd}, events={events!r})", RpcError)

    def mod(self, sock_or_fd, events: str) -> None:
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

    def wait(self, timeout: float = -1.0) -> list[tuple[int, set[str]]]:
        """Wait up to *timeout* seconds for events.

        Returns a list of ``(fd, event_names_set)`` pairs — one per ready
        file descriptor.  Returns an empty list on timeout (n == 0).

        *timeout* < 0 means block indefinitely (passed as -1 ms to the TAPI).

        The shim returns a single malloc'ed int[2*n] array with interleaved
        [fd0, evt0, fd1, evt1, ...] pairs.  We unpack fds from even indices
        and evts from odd indices, then free the array with one pyte_free_ints
        call.
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
            _ensure_event_bits()
            result = [
                (flat[2 * i], _evt_names(flat[2 * i + 1]))
                for i in range(n)
            ]
        finally:
            lib.pyte_free_ints(revts_arr)
        return result
