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
- The RCF session cache assumes agents live for the whole run; after
  an agent restart call `pyte.tad.reset_sessions()` so the next Csap
  creates a fresh session (Csaps created earlier must be recreated).
- `RpcServer.expect_error()` is a pytest.raises-style catching
  context manager: the failing RPC call raises `RpcError`, the block
  stops right there, and the caught error is available on the yielded
  object (`info.error`).  Facade calls always return real values —
  there is no suppressed-`None` path.
- `RpcSocket.setsockopt()` deliberately exposes a minimal int-valued
  option surface (currently `SO_REUSEADDR`).  To add an option:
  passthrough the `RPC_SO_*` constant from `te_rpc_sys_socket.h` as
  `PYTE_SO_*` in `shim/pyte_shim.h` + the cdef, then add a row to
  `_SOCKOPTS` in `src/pyte/rpc/socket.py`.
- `RpcServer.sleep()` is a remote shell `sleep` run as a single
  `rpc_system()` call whose timeout covers the whole command: this TE
  has no `rpc_sleep()` RPC.
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
