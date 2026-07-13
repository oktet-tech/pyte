# pyte.rpc — RPC sockets, iomux and scatter/gather I/O

`pyte.rpc.RpcServer` creates and owns remote socket file descriptors
through `RpcSocket`.  A complete TCP echo between two RPC servers
(from the showcase test `ts/rpc/socket_echo.py`):

```{literalinclude} /_snippets/rpc-socket-echo.py
:language: python
```

## Socket operations — shutdown, peer address, options, blocking mode

`Shut` (importable from `pyte.rpc`) enumerates shutdown directions:

- `sock.shutdown(Shut.RDWR)` — shut down sending, receiving, or both
  (`Shut.RD`, `Shut.WR`, `Shut.RDWR`).
- `sock.getpeername()` — return `(ip, port)` of the connected peer, or
  `None` when the call was suppressed.
- `sock.getsockopt(SockOpt.SO_RCVBUF) -> int` — read an int-valued
  socket option; round-trips with `setsockopt`.  Supported options
  include `SO_REUSEADDR`, `SO_REUSEPORT`, `SO_KEEPALIVE`,
  `SO_BROADCAST`, `SO_RCVBUF`, `SO_SNDBUF`, `SO_ERROR`,
  `TCP_NODELAY`, `IP_PKTINFO`.
- `sock.set_blocking(False)` / `sock.get_blocking() -> bool` — toggle
  non-blocking mode via `fcntl(F_GETFL/F_SETFL, O_NONBLOCK)`.

## IoMux — multiplexed waiting (select/poll/epoll)

`pco.iomux(kind)` returns an `IoMux` context manager backed by
`tapi_iomux`, and accepts any `Kind`: `Kind.SELECT`, `Kind.PSELECT`,
`Kind.POLL`, `Kind.PPOLL`, `Kind.EPOLL`, `Kind.EPOLL_PWAIT`,
`Kind.EPOLL_PWAIT2`.  The showcase test `ts/rpc/iomux.py` is
parametrized over all of them, picking one at runtime via
`Kind[mux_name.upper()]`:

```{literalinclude} /_snippets/rpc-iomux.py
:language: python
```

`mux.add()` also accepts a bare int fd in place of a socket.  The
`mux.wait(0.5) != []` check above is the timeout case shown live:
`wait()` returns an empty list on timeout (n==0 from
`tapi_iomux_call`) — not an error.  `IoMux` also has `mux.mod(sock,
Evt.OUT)` to change registered events and `mux.delete(sock)` to
unregister.  Event flags: `Evt.IN`, `Evt.OUT`, `Evt.PRI`, `Evt.EXC`,
`Evt.ERR`, `Evt.HUP`, `Evt.RDHUP`, `Evt.ET`, `Evt.ONESHOT`,
`Evt.NVAL`.

Note: `tapi_iomux` functions longjmp via `TEST_FAIL` on error; the
shim guards them with `PYTE_GUARD`.  The TAPI manages
`RPC_AWAIT_ERROR` internally — pyte must NOT re-arm it around these
calls (unlike direct `rpc_*` wrappers).

## sendmsg / recvmsg — scatter/gather and ancillary data

The showcase test `ts/rpc/msg_io.py` sends multiple buffers as one
datagram, then enables `IP_PKTINFO` to receive ancillary (control)
data alongside it:

```{literalinclude} /_snippets/rpc-msg-io.py
:language: python
```

`recvmsg()` returns an object with `.data: bytes`, `.addr: (ip,
port) | None`, `.flags: int`, and `.ancillary: [(level, type, data),
...]` (empty unless a `SockOpt` like `IP_PKTINFO` was enabled first).

Ancillary data note: cmsg level and type values are host-native
integers.  The TE RPC layer converts them via `msg_control_h2rpc` /
`msg_control_rpc2h` in `te_rpc_sys_socket.h`; only TE-known socket
levels (SOL_SOCKET, IPPROTO_IP, IPPROTO_IPV6, IPPROTO_TCP,
IPPROTO_UDP) and their known cmsg types survive.  Unknown level/type
values arrive mangled with SOL_MAX and a WARN in the TE log.  Engine
and agent must share the same OS ABI for ancillary payloads to be
meaningful.
