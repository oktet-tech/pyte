# Architecture

A pyte test is plain Python. Each call descends through the pure-Python
facades into the cffi shim, which drives TE's engine-side libraries; those
talk to the Test Agents on the host(s) under test via RCF.

```{mermaid}
flowchart TD
    T["Python test<br/>(ts/*.py)"]
    F["pyte facades — pure Python<br/>cfg · rpc · net · tad.dsl · job · env"]
    S["pyte._shim — cffi C bridge<br/>PYTE_GUARD &rarr; te_errno · RPC_AWAIT_ERROR"]
    L["TE engine libraries<br/>tapi_* · rcfrpc · confapi · tad · logger"]
    R["RCF — Remote Control Facility"]
    A["Test Agent(s)<br/>on host(s) under test"]
    T --> F
    F -->|"lazy import inside functions"| S
    S --> L
    L --> R
    R --> A
```

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
