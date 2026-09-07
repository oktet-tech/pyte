# Wave 1 handoff — ownership and cleanup

Branch `wave1-ownership`, 26 commits off `trexb` at `c5b4c6c`.
State: 1025 passed, 1 skipped, `ruff check src tests setup.py` clean.

Spec: `../../../pyte-api-fixes-plan-2026-09-07.md` (wave 1 section).
Evidence for the original findings: `../../../pyte-api-fixes-review-2026-09-07.md`.

## THE MERGE GATE — read this first

**The shim was never rebuilt, and the branch cannot run until it is.**

`src/pyte/job.py` calls `pyte_rpc_get_silent_pass()` in **every**
`Job.create()`. That symbol does not exist in the currently built
`src/pyte/_shim.abi3.so`:

    nm -D src/pyte/_shim.abi3.so | grep silent
    # shows set_silent and set_silent_pass; get_silent_pass is ABSENT

So no suite can bump its pyte pin before the rebuild. It fails loudly
(`AttributeError` on the first job), not subtly. All 1025 tests pass
against fake shims and say nothing about the C.

The rebuild was skipped deliberately: this worktree's `.so` is a copy of
the one a live <tester-host> session was using.

## Post-rebuild checklist

1. **It compiled.** `pyte_rpc_get_silent_pass` is now declared in
   `shim/pyte_shim.h` (it was missing — the only one of 200 cdef'd
   functions without a declaration, a hard error on GCC >= 14). If a
   build error reappears here, add the `extern`; do not silence the
   diagnostic.
2. `nm -D src/pyte/_shim.abi3.so | grep silent` shows **three** symbols:
   `set_silent`, `set_silent_pass`, `get_silent_pass`.
3. `nm -D src/pyte/_shim.abi3.so | grep -c tapi_job_get_silent_pass` is
   `0` — no undefined reference to TE's non-installed internal symbol
   survives (that dependency was deliberately retired).
4. **Round-trip the getter against the setter.** No test exercises the
   real C: `set_silent_pass(h, 1)` then `get_silent_pass(h) == 1`, and
   likewise for 0.
5. **Seeding is right on a real server.** Create a job inside
   `pco.silent_pass()` and assert `job.tracing_enabled() is False`;
   create one outside and assert `True`. This is the load-bearing
   consequence of tracking the tracing flag in Python instead of asking
   C for it.
6. **The nap-ts observability fix, on a live run.** A TRex job created
   under `batch.create()`'s silent window must produce *no*
   `job_create`/`job_attach_filter` log lines, and *must* produce
   `job_stop`/`job_destroy` lines after `report()` — the pair the C's
   `tapi_job_set_tracing(TRUE)` guarantees at
   `ngfw-ts/nap-ts/lib/nap-trex-stats.c:975,977`.
7. Re-run the full suite against the rebuilt `.so`.

## Known gaps left open (none block merge)

- **`remote.py:146`** caches the raw `rcf_rpc_server*` with no link to
  the owning wrapper's liveness. Latent only — the session lives inside
  `with pco.job(...)` — and invisible to any `._h` sweep.
- **`trc.py:104`** has a bare `except BaseException` that was out of
  scope for every task.
- **`RpcFile` has no test file at all**, so its documented close-ordering
  rule is untested where `RpcSocket`'s is pinned.
- **`Csap` still leaks** if not used as a context manager. Its new
  `__del__` only *warns*; it deliberately does not free, because calling
  into the shim from a GC callback is forbidden in this codebase
  (`mi.py`, `remote.py` both say so). The leak is now visible, not fixed.

## Consumer impact when you bump the pin

- **nap-ts** — TRex teardown logging is preserved by an explicit
  `tracing(True)` in `Trex.report()`, mirroring `trex_result_extract()`.
  Behaviour matches the C.
- **app-perf-ts-py** — unaffected, but only because it never uses
  `silent_pass()`, so its jobs are born loud. Had any been born silent it
  would have hit the same regression TRex did.
- **python-ts / nvme-ts** — no touched API in suite code.
- **New observable behaviour everywhere:** teardown failures now arrive
  as `cleanup_errors` + `__notes__` on the original exception instead of
  replacing it, and `test.py` emits one extra `log.error` line carrying
  that detail. For `TestSkip` the detail goes to a log line, never into
  the verdict — verdicts are TRC-matchable and must stay clean.
- `Env.pco(name)` now returns the **same object** for aliases.
- An env-owned PCO's `destroy()` now poisons the wrapper.

## Sweeps worth re-running after any future change here

Every incomplete sweep in this wave failed the same way: it grepped an
allowlist of method names instead of matching the shape of a call.

    # raw foreign handle reaching C (boundary-anchored; `._h` alone
    # prefix-matches `._handle()` and is useless)
    grep -rnE '\._h([^A-Za-z0-9_]|$)' src/pyte/

    # cleanups inside finally:/__exit__/__del__ — parse, do not grep
    # (see the AST approach the final review used)

    # the construct three sweeps missed entirely:
    # a cleanup inside `except ...: <cleanup>; raise`
