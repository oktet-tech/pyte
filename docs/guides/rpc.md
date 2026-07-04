# pyte.rpc — RPC sockets, iomux and scatter/gather I/O

`pyte.rpc.RpcServer` creates and owns remote socket file descriptors
through `RpcSocket`.  Common usage pattern:

```python
from pyte.rpc import Family, SockOpt, SockType

pco = t.rpc_server("pco")
with pco.socket(Family.INET, SockType.DGRAM) as s:
    s.bind(("127.0.0.1", 0))
    addr = s.getsockname()
```

### IoMux — multiplexed waiting (select/poll/epoll)

`pco.iomux(kind)` returns an `IoMux` context manager backed by
`tapi_iomux`.  Supported kinds: `Kind.SELECT`, `Kind.PSELECT`,
`Kind.POLL`, `Kind.PPOLL`, `Kind.EPOLL`, `Kind.EPOLL_PWAIT`,
`Kind.EPOLL_PWAIT2`.

```python
from pyte.rpc.iomux import Evt, Kind

with pco.iomux(Kind.EPOLL) as mux:
    mux.add(sock_a, Evt.IN)            # also accepts int fd
    mux.add(sock_b, Evt.IN | Evt.OUT)
    events = mux.wait(2.0)             # [(fd, Evt.IN|...), ...]
    if events == []:
        ...  # timeout — not an error
    mux.mod(sock_a, Evt.OUT)
    mux.delete(sock_a)
```

`wait()` returns an empty list on timeout (n==0 from
`tapi_iomux_call`).  Event flags: `Evt.IN`, `Evt.OUT`, `Evt.PRI`,
`Evt.EXC`, `Evt.ERR`, `Evt.HUP`, `Evt.RDHUP`, `Evt.ET`,
`Evt.ONESHOT`, `Evt.NVAL`.

Note: `tapi_iomux` functions longjmp via `TEST_FAIL` on error; the
shim guards them with `PYTE_GUARD`.  The TAPI manages
`RPC_AWAIT_ERROR` internally — pyte must NOT re-arm it around these
calls (unlike direct `rpc_*` wrappers).

### sendmsg / recvmsg — scatter/gather and ancillary data

```python
# Scatter send: multiple buffers arrive as one datagram
n = tx.sendmsg([b"hello-", b"world"], addr=("127.0.0.1", port))

# Receive with ancillary data space
msg = rx.recvmsg(bufsize=4096, ctrl_space=256)
# msg.data: bytes  msg.addr: (ip, port)|None  msg.flags: int
# msg.ancillary: [(level, type, data), ...]

# Enable IP_PKTINFO to receive destination address
rx.setsockopt(SockOpt.IP_PKTINFO, 1)
msg = rx.recvmsg(64, ctrl_space=256)
for level, ctype, data in msg.ancillary:
    ...  # level=IPPROTO_IP(0), ctype=IP_PKTINFO(8) on Linux
```

Ancillary data note: cmsg level and type values are host-native
integers.  The TE RPC layer converts them via `msg_control_h2rpc` /
`msg_control_rpc2h` in `te_rpc_sys_socket.h`; only TE-known socket
levels (SOL_SOCKET, IPPROTO_IP, IPPROTO_IPV6, IPPROTO_TCP,
IPPROTO_UDP) and their known cmsg types survive.  Unknown level/type
values arrive mangled with SOL_MAX and a WARN in the TE log.  Engine
and agent must share the same OS ABI for ancillary payloads to be
meaningful.
