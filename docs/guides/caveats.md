# Known caveats

- uv caches editable builds: after any change under `shim/` rebuild
  with `uv sync --reinstall-package pyte`, plain `uv sync` will not
  recompile.
- Python signal handlers only run between bytecodes, so they do not
  fire while a C call blocks.  The SIGUSR1 "kill stuck test" handler
  installed by `test.start()` cannot preempt a blocked RPC call or
  CSAP/job receive — this is a design caveat of the shim approach.
- Received job data is text: TE's ta_job delivers messages as strings
  and truncates at interior NUL bytes, and `JobMessage.data` is
  UTF-8-decoded (errors replaced).  Send paths (`InputChannel.send`,
  `Csap.send`) are binary-safe, and received CSAP packet payloads come
  back as `bytes` (they cross RCF hex-encoded inside NDN text).
- `cfg`: `CVT_ADDRESS` values are portless IP strings
  (e.g. `"192.0.2.1"`); `CVT_BOOL` instances read back as int 0/1,
  not Python bool.
- The RCF session cache in `pyte.tad.csap._sessions` assumes agents
  live for the whole run; if an agent restarts, the cache must be
  cleared (or the test process restarted).
- Inside `RpcServer.expect_error()`, value-returning facade calls
  whose failure was swallowed return `None` (raw `_check_call` users
  see the `SUPPRESSED` sentinel).  This includes the open facades:
  `RpcServer.socket()`/`RpcSocket.open()` and
  `RpcServer.open()`/`open_file()` return `None`, not a wrapper
  around fd -1.
- `RpcSocket.setsockopt()` deliberately exposes a minimal int-valued
  option surface (currently `SO_REUSEADDR`).  To add an option:
  passthrough the `RPC_SO_*` constant from `te_rpc_sys_socket.h` as
  `PYTE_SO_*` in `shim/pyte_shim.h` + the cdef, then add a row to
  `_SOCKOPTS` in `src/pyte/rpc/socket.py`.
- `RpcServer.sleep()` is a remote shell `sleep` with RPC-timeout
  headroom: this TE has no `rpc_sleep()` RPC.
- `pyte.errors.check()` raises `pyte.errors.TimeoutError` for
  `TE_ETIMEDOUT` regardless of the exception class passed in.
- `pyte.tad.validate(text, kind)` wraps the shim's `pyte_asn_check()`
  dev/calibration helper; use it to sanity-check NDN text for the
  `from_asn`/`send_asn`/`listen(str)` escape hatches:

  ```python
  from pyte import tad
  tad.validate("{ layers { udp:{}, ip4:{} } }", "csap")
  tad.validate("{ pdus { udp:{ dst-port plain:9 } } }", "template")
  ```

  It raises `ValueError` with the failing symbol position on bad text
  (needs the built shim, but no agent).  Outside `test.start()` (e.g.
  in a REPL) expect harmless "Logging backend is unset" warnings from
  the jump-point bookkeeping.
