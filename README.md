<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (C) 2026 Konstantin Ushakov -->
# pyte — Python wrappers for the TE engine side

pyte lets you write TE tests in Python.  Tests are real Python
processes executed by Tester (argv `name=value` parameters, exit-code
contract — see `pyte.test.start()`), and they talk to the running Test
Engine through the same engine-side shared libraries C tests use:
RCF/RPC, Configurator, tapi_job and TAD.  The bridge is a small C shim
compiled as a cffi API-mode extension (`pyte._shim`) at `uv sync` time
against the TE installation pointed to by `TE_INSTALL`.  Zero TE
source changes.

Modules: `pyte.test` (lifecycle), `pyte.log`, `pyte.errors`,
`pyte.rpc` (RpcServer/RpcSocket/files/sh/expect_error), `pyte.cfg`
(CfgNode object model), `pyte.job` (Job/Channel/Filter), `pyte.tad`
(layer DSL + Csap).

## Architecture

- **Shim** (`shim/pyte_shim.{c,h}` + `shim/pyte_shim_cdef.h`): every
  exported function returns `te_errno` and writes results through
  out-parameters.  TAPI code reports some failures by `longjmp` to the
  enclosing `TEST_START` frame — which does not exist in Python — so
  each wrapper body runs inside `PYTE_GUARD`, a trampoline that pushes
  a `tapi_jmp` point, confines any longjmp to that C frame and turns
  it into a `te_errno` return.
- **RPC handles** are permanently re-armed with `RPC_AWAIT_ERROR`
  before each call, so a failed remote call never longjmps; the Python
  facade (`RpcServer._check_call`) inspects the return value and the
  remote errno and raises `pyte.errors.RpcError` instead.
- **Errors**: Python checks every `te_errno` with
  `pyte.errors.check()`, raising `TeError`/`CfgError`/`RpcError`
  (`TimeoutError` for `TE_ETIMEDOUT`).
- **Lazy `_shim` imports rule**: Python modules import the extension
  with `from pyte._shim import ffi, lib` *inside* functions, never at
  module top level.  This keeps pure-Python parts (`pyte.tad.dsl`,
  `pyte._params`) importable and unit-testable without a built shim
  or a TE installation.
- **Configurator values cross as text**: the shim converts to/from
  the real `CVT_*` instance type; `pyte.cfg.get()` turns integer
  types back into `int`.
- **TAD**: `pyte.tad.dsl` is a Scapy-style layer DSL that compiles to
  NDN ASN.1 *text*; the shim parses it against the proper `ndn_*`
  type.  The exact text shapes were calibrated against TE's
  `asn_parse_value_text()` and are pinned by unit tests
  (`tests/test_tad_dsl.py`); use `pyte.tad.validate()` to check
  hand-written NDN text.
- **Packet ownership**: TE's receive callback hands each parsed
  packet (asn_value) to the callback owner, so the shim stores the
  pointer without copying and Python's `Packet` frees it via
  `pyte_pkt_free()` (explicitly or in `__del__`).

## Extending pyte (the pattern)

Worked example — how `rpc_listen()` was added:

1. **C wrapper** in `shim/pyte_shim.c`, declaration in
   `shim/pyte_shim.h`.  Guarded, te_errno + out-param, awaiting-error
   re-armed:

   ```c
   te_errno
   pyte_rpc_listen(rcf_rpc_server *rpcs, int s, int backlog, int *out)
   {
       RPC_AWAIT_ERROR(rpcs);
       PYTE_GUARD(*out = rpc_listen(rpcs, s, backlog));
       return 0;
   }
   ```

   `PYTE_GUARD`'s statement must not return early (see the macro
   comment in `pyte_shim.h`); use `PYTE_GUARD_RC` for calls that
   already return `te_errno`.

2. **cdef line** in `shim/pyte_shim_cdef.h` (kept in sync with the
   header, minus `extern`):

   ```c
   te_errno pyte_rpc_listen(rcf_rpc_server *rpcs, int s, int backlog,
                            int *out);
   ```

3. **Facade method** (here in `src/pyte/rpc/socket.py`) routing the
   trampoline status and the call result through `_check_call`:

   ```python
   def listen(self, backlog: int = 5) -> None:
       from pyte._shim import ffi, lib
       out = ffi.new("int *")
       rc = lib.pyte_rpc_listen(self.server._h, self.fd, backlog, out)
       self.server._check_call(rc, out[0], lambda v: v == 0,
                               f"listen({backlog})")
   ```

   Non-RPC wrappers just call `pyte.errors.check(rc, where)`.

4. **Rebuild** the extension:

   ```sh
   TE_INSTALL=/path/to/te/inst uv sync --reinstall-package pyte
   ```

5. **Test**: a unit test if the logic is pure Python, plus a showcase
   test in `ts/` for end-to-end behaviour.

## Known caveats

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
  see the `SUPPRESSED` sentinel).
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

## How to run

```sh
# Unit tests (no TE engine needed; pure-Python parts only)
uv run pytest lib/pyte/tests

# The showcase suite (from the repo root; builds TE + shim first)
./scripts/run.sh --cfg=localhost

# A subset
./scripts/run.sh --cfg=localhost --tester-run=python-ts/rpc/socket_echo

# Lint
uv run ruff check lib ts
```

Logs: `log.txt` in the directory you ran from; add `--log-html=DIR`
for a browsable version.  The raw log is `tmp_raw_log`.
