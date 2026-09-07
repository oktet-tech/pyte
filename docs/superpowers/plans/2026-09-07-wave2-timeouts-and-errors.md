# Wave 2: Truthful Timeouts and Error Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every timeout pyte documents be the timeout pyte delivers, and make a timeout catchable as both a timeout and its subsystem's error.

**Architecture:** One shared deadline module replaces three inline copies of the seconds-to-milliseconds conversion and becomes the single place the `None` policy is enforced. `errors.check()` is already the central te_errno conversion with 100 call sites through it; a small registry inside it gives every one of them subsystem-specific timeout classes for free. Genuinely unbounded waits are then implemented as a loop of bounded backend calls, because TE, not pyte, imposes the real limits.

**Tech Stack:** Python 3.11+, cffi shim over TE C libraries, pytest.

**Spec:** `/home/kostik/prj/te/pyte-api-fixes-plan-2026-09-07.md` (wave 2 section). Evidence: `/home/kostik/prj/te/pyte-api-fixes-review-2026-09-07.md`.

## Global Constraints

- Repo `/home/kostik/prj/te/pyte`, branch `trexb`. Test with `.venv/bin/python -m pytest tests/ -q`; never `uv run pytest` (it rebuilds the shim, needs `TE_INSTALL`).
- Lint with `ruff check src tests setup.py`.
- Wave 1 must be landed first: this plan uses `ClosedResourceError` and `cleanup_all`.
- Style: 4-space indent, wrap at 79 columns. `git commit -s`, summary at most 60 chars, no AI attribution trailers.
- Breaking changes permitted; name each in the commit body.
- **No test may sleep.** Use the fake clock from Task 1.

## The `None` policy this wave implements

Decided, and load-bearing for Tasks 3 and 4:

> `timeout=None` means **block forever** only where the backend can actually deliver an unbounded wait. Where it cannot, `None` is **rejected** with an error naming the alternative.

| API | Today | After |
|---|---|---|
| `job.wait/receive/read_many/poll` | `None` to `-1` ms, TE caps at 600 s | genuinely unbounded, via slicing |
| `IoMux.wait` | `None` to `-1` ms, TE caps at **10 s** | genuinely unbounded, via slicing |
| `RemotePython.call` | `None` means the 30 s session default | `None` rejected (session is unusable after a timeout) |
| `Csap.listen` | no `None` accepted at all, no negative check | `None` rejected explicitly; negative rejected |
| `RpcServer.system` | `None` to `0` ms, meaning the RCF default | `None` documented as "the RCF default", not forever |

Where the caps come from: `TAPI_RPC_JOB_BIG_TIMEOUT_MS` is 600000 (`te/lib/tapi_job/tapi_rpc_job.h:22`); iomux falls back to `RCF_RPC_DEFAULT_TIMEOUT` = 10000 (`te/lib/rcfrpc/rcf_rpc.h:204`) because `te/lib/tapi_rpc/unistd.c:1771` skips the extension for a negative timeout. Expiry is not benign: `te/lib/rcfpch/rcf_pch_rpc.c:778-781` sets `rpcs->dead`.

---

### Task 1: Shared deadline module and a fake clock

**Files:**
- Create: `src/pyte/_time.py`
- Create: `tests/test_time.py`
- Modify: `src/pyte/testing.py` (add the `fake_clock` fixture)
- Modify: `tests/conftest.py` (re-export it)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `pyte._time.to_ms(timeout: float | None) -> int` — `None` to `-1`, rejects negative/NaN/inf.
  - `pyte._time.check_timeout(timeout, *, allow_none=True, who="") -> float | None` — validation only.
  - `pyte._time.Deadline(total: float | None)` with `.remaining() -> float | None`, `.expired -> bool`, `.slice(cap: float) -> float`.
  - `pyte.testing.fake_clock` fixture, yielding a controller with `.advance(seconds)` and `.patch(module)`.
- Tasks 2-6 all use these.

**Background:** `_ms` lives in `job.py:24-36`; `iomux.py:206` and `csap.py:277` each reimplement `int(timeout * 1000)`, and iomux duplicates the negative check word for word while csap has none. `remote.py:193` has no negative check and poisons the session instead of raising. `_tool._remaining` propagates NaN.

The existing fake-clock idiom is `itertools.chain([...], repeat(last))` monkeypatching the **module's** `time` attribute (`_tool.time.monotonic`), because `_tool.py` and `remote.py` both do a module-level `import time`. Generalize that; do not patch `time.monotonic` globally.

- [ ] **Step 1: Write the failing test**

Create `tests/test_time.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte._time: one conversion and one deadline for the whole package."""
import math

import pytest

from pyte import _time


def test_none_is_block_forever():
    assert _time.to_ms(None) == -1


def test_seconds_become_truncated_milliseconds():
    assert _time.to_ms(2.5) == 2500
    assert _time.to_ms(0) == 0
    assert _time.to_ms(0.0019) == 1      # truncation, not rounding


def test_negative_is_rejected():
    with pytest.raises(ValueError, match="negative"):
        _time.to_ms(-3)


def test_nan_is_rejected_at_the_boundary():
    """NaN used to survive into int() and blow up far from the caller."""
    with pytest.raises(ValueError, match="not a number|NaN"):
        _time.to_ms(math.nan)


def test_infinity_is_rejected_with_a_pointer_to_none():
    with pytest.raises(ValueError, match="None"):
        _time.to_ms(math.inf)


def test_check_timeout_can_forbid_none():
    with pytest.raises(ValueError, match="requires an explicit timeout"):
        _time.check_timeout(None, allow_none=False, who="rem.call()")


def test_check_timeout_names_the_caller():
    with pytest.raises(ValueError, match="rem.call"):
        _time.check_timeout(None, allow_none=False, who="rem.call()")


def test_deadline_none_never_expires():
    d = _time.Deadline(None)
    assert d.remaining() is None
    assert not d.expired
    assert d.slice(1.0) == 1.0


def test_deadline_counts_down_from_the_absolute_deadline(fake_clock):
    fake_clock.patch(_time)
    d = _time.Deadline(30.0)
    fake_clock.advance(20.0)
    assert d.remaining() == pytest.approx(10.0)
    fake_clock.advance(10.0)
    assert d.expired


def test_deadline_slice_never_exceeds_the_remaining_budget(fake_clock):
    fake_clock.patch(_time)
    d = _time.Deadline(2.5)
    assert d.slice(1.0) == 1.0
    fake_clock.advance(2.0)
    assert d.slice(1.0) == pytest.approx(0.5)


def test_deadline_slice_is_never_negative(fake_clock):
    fake_clock.patch(_time)
    d = _time.Deadline(1.0)
    fake_clock.advance(5.0)
    assert d.slice(1.0) == 0.0


def test_repeated_remaining_does_not_accumulate_rounding(fake_clock):
    """Recomputed from the absolute deadline, not by subtracting."""
    fake_clock.patch(_time)
    d = _time.Deadline(10.0)
    for _ in range(100):
        fake_clock.advance(0.01)
        d.remaining()
    assert d.remaining() == pytest.approx(9.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_time.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'pyte._time'` (and `fake_clock` unknown).

- [ ] **Step 3: Write the module**

Create `src/pyte/_time.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""One timeout conversion and one deadline for the whole package.

The seconds-to-milliseconds conversion used to exist three times
(pyte.job._ms, an inline copy in pyte.rpc.iomux, another in
pyte.tad.csap) with three different amounts of validation, which is
how the package ended up with five different meanings for
``timeout=None``.  Everything that takes a timeout converts here.

The package convention: ``None`` means block forever, and is accepted
ONLY where the backend can actually deliver an unbounded wait.  Where
it cannot -- a pyte.remote session is unusable after a timeout, so an
unbounded wait there could only hang forever -- pass
``allow_none=False`` to :func:`check_timeout` and say so in the error.
"""
from __future__ import annotations

import math
import time


def check_timeout(timeout: float | None, *, allow_none: bool = True,
                  who: str = "") -> float | None:
    """Validate a timeout argument; return it unchanged.

    Rejects negatives (a computed remaining time going negative must
    not silently mean "forever"), NaN and infinity (both used to
    survive into int() and fail far from the caller).
    """
    prefix = f"{who}: " if who else ""
    if timeout is None:
        if allow_none:
            return None
        raise ValueError(
            f"{prefix}requires an explicit timeout; this operation "
            "cannot wait forever")
    if isinstance(timeout, float) and math.isnan(timeout):
        raise ValueError(f"{prefix}timeout is not a number (NaN)")
    if math.isinf(timeout):
        raise ValueError(
            f"{prefix}timeout must be finite (use None to block "
            "forever where that is supported)")
    if timeout < 0:
        raise ValueError(
            f"{prefix}timeout must not be negative, got {timeout!r} "
            "(use None to block forever)")
    return timeout


def to_ms(timeout: float | None, *, allow_none: bool = True,
          who: str = "") -> int:
    """Convert float seconds to int milliseconds; None to -1.

    -1 is the tapi_job "block forever" convention.  Note that TE caps
    what -1 actually means (600 s for jobs, 10 s for iomux), which is
    why unbounded waits are implemented by slicing rather than by
    handing -1 to the backend once.
    """
    timeout = check_timeout(timeout, allow_none=allow_none, who=who)
    if timeout is None:
        return -1
    return int(timeout * 1000)


class Deadline:
    """An absolute deadline, so slices never accumulate rounding error.

    ``Deadline(None)`` never expires: ``remaining()`` stays None and
    ``slice(cap)`` always returns the full cap.
    """

    def __init__(self, total: float | None, *, who: str = ""):
        self.total = check_timeout(total, who=who)
        self._end = (None if self.total is None
                     else time.monotonic() + self.total)

    def remaining(self) -> float | None:
        """Seconds left, or None for an unbounded deadline."""
        if self._end is None:
            return None
        return self._end - time.monotonic()

    @property
    def expired(self) -> bool:
        rem = self.remaining()
        return rem is not None and rem <= 0

    def slice(self, cap: float) -> float:
        """The next bounded wait: at most *cap*, never past the end."""
        rem = self.remaining()
        if rem is None:
            return cap
        return max(0.0, min(cap, rem))
```

- [ ] **Step 4: Add the fake clock**

In `src/pyte/testing.py`, add after the existing fixtures:

```python
class FakeClock:
    """A monotonic clock tests drive by hand.

    Patches the ``time`` attribute of a MODULE, not the global
    ``time.monotonic``: pyte modules do a module-level ``import time``
    and call ``time.monotonic()``, so that is the seam.  Generalizes
    the ``itertools.chain([...], repeat(last))`` idiom the tool tests
    grew independently.
    """

    def __init__(self, monkeypatch, start: float = 0.0):
        self._monkeypatch = monkeypatch
        self._now = start

    def advance(self, seconds: float) -> None:
        """Move the clock forward."""
        self._now += seconds

    def monotonic(self) -> float:
        return self._now

    def patch(self, module) -> None:
        """Make *module*'s time.monotonic() read this clock."""
        self._monkeypatch.setattr(module.time, "monotonic",
                                  self.monotonic)


@pytest.fixture()
def fake_clock(monkeypatch):
    """A hand-driven monotonic clock; no test ever sleeps."""
    return FakeClock(monkeypatch)
```

In `tests/conftest.py`, extend the import:

```python
from pyte.testing import (fake_shim, current_test, mi_logger,  # noqa: F401
                          fake_clock)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_time.py -v`
Expected: 12 passed

- [ ] **Step 6: Route the three existing conversions through it**

`src/pyte/job.py`: replace `_ms`'s body with `return _time.to_ms(timeout)` and keep the name (it has direct tests: `test_ms_none_means_block_forever`, `test_ms_rejects_negative`). Add `from pyte import _time`.

`src/pyte/rpc/iomux.py:202-207`: replace the inline negative check and `-1 if timeout is None else int(timeout * 1000)` with `timeout_ms = _time.to_ms(timeout, who="IoMux.wait()")`.

`src/pyte/tad/csap.py:277`: replace `int(timeout * 1000)` with `_time.to_ms(timeout, allow_none=False, who="Csap.listen()")`. This adds the negative check csap never had and rejects `None` explicitly instead of raising `TypeError` from the multiplication.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. `test_wait_rejects_negative` (iomux) and the `_ms` tests still pass — the messages are unchanged apart from an optional `who:` prefix, and both tests match on substrings.

- [ ] **Step 8: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "add one timeout conversion and deadline helper" -m "The seconds-to-milliseconds conversion existed three times (job._ms
plus inline copies in rpc.iomux and tad.csap) with three different
amounts of validation: iomux duplicated the negative check word for
word, csap had none at all and rejected None with a TypeError from
the multiplication.  That divergence is how the package ended up
with five meanings for timeout=None.

pyte._time.to_ms/check_timeout/Deadline is now the single place, and
the place the None policy is enforced.  Deadline recomputes from an
absolute end time so sliced waits cannot accumulate rounding error.

Add a fake_clock fixture generalizing the itertools.chain tick idiom
the tool tests grew independently, so no test has to sleep."
```

---

### Task 2: Subsystem timeout classes

**Files:**
- Modify: `src/pyte/errors.py` (new classes; `check()`)
- Modify: `src/pyte/rpc/server.py:97-102` (`_check_call`'s remote-errno path)
- Modify: `src/pyte/job.py:640-647` (the EINPROGRESS mapping)
- Test: `tests/test_errors.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RpcTimeoutError(RpcError, TimeoutError)`, `CfgTimeoutError(CfgError, TimeoutError)`, `RcfTimeoutError(RcfError, TimeoutError)`, `EnvTimeoutError(EnvError, TimeoutError)`, `TrcTimeoutError(TrcError, TimeoutError)`, `JobError(TeError)`, `JobTimeoutError(JobError, TimeoutError)`.

**Background:** `errors.check()` (`errors.py:252-265`) is already the central conversion with 100 call sites through it, and already special-cases `ETIMEDOUT` and `CfgError`+`ENOENT`. The single defect is that it **discards `cls`** for timeouts, so no timeout is catchable as its subsystem error. Fixing that one line upgrades all 100 sites.

`RpcTimeoutError(RpcError, TimeoutError)` additionally resolves the `_check_call` asymmetry (the transport path raises `TimeoutError`, the remote-errno path raises `RpcError` four lines later) and makes `expect_error(errors.ETIMEDOUT)` matchable, with no special-casing.

`remote.py:197-199` relies on `builtins.TimeoutError` catching these. Every new class must keep that.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_errors.py`. It has no fake shim, and `TeError.__init__` reaches the real one, so use the real shim's `PYTE_ETIMEDOUT` the way the file already uses `errors.E*`:

```python
# -- subsystem timeout classes ----------------------------------------

def test_rpc_timeout_is_both_an_rpc_error_and_a_timeout():
    exc = errors.RpcTimeoutError(errors.ETIMEDOUT, "getpid()")
    assert isinstance(exc, errors.RpcError)
    assert isinstance(exc, errors.TimeoutError)
    import builtins
    assert isinstance(exc, builtins.TimeoutError)


def test_check_raises_the_subsystem_timeout_for_its_cls():
    with pytest.raises(errors.RpcTimeoutError):
        errors.check(errors.ETIMEDOUT, "getpid()", errors.RpcError)


def test_check_still_raises_a_plain_timeout_for_the_default_cls():
    with pytest.raises(errors.TimeoutError) as info:
        errors.check(errors.ETIMEDOUT, "somewhere")
    assert type(info.value) is errors.TimeoutError


def test_a_subsystem_timeout_is_catchable_as_its_subsystem():
    """The point of the change: 'except RpcError' must not miss a
    timeout on an RPC call."""
    with pytest.raises(errors.RpcError):
        errors.check(errors.ETIMEDOUT, "getpid()", errors.RpcError)


def test_check_preserves_the_native_rc():
    with pytest.raises(errors.RpcTimeoutError) as info:
        errors.check(errors.ETIMEDOUT, "getpid()", errors.RpcError)
    assert info.value.rc == errors.ETIMEDOUT


def test_cfg_enoent_still_beats_the_timeout_registry():
    with pytest.raises(errors.CfgNotFoundError):
        errors.check(errors.ENOENT, "oid", errors.CfgError)


def test_an_unregistered_cls_falls_back_to_plain_timeout():
    with pytest.raises(errors.TimeoutError) as info:
        errors.check(errors.ETIMEDOUT, "x", errors.ExpandError)
    assert type(info.value) is errors.TimeoutError


def test_job_timeout_is_both_a_job_error_and_a_timeout():
    exc = errors.JobTimeoutError(errors.ETIMEDOUT, "job.wait(ls)")
    assert isinstance(exc, errors.JobError)
    assert isinstance(exc, errors.TimeoutError)
```

Append to `tests/test_server.py`:

```python
def test_expect_error_matches_a_guard_level_timeout(monkeypatch):
    """expect_error catches RpcError; a timeout on the guard path used
    to raise a plain TimeoutError and escape the context manager, so
    expect_error(ETIMEDOUT) could never succeed."""
    from pyte import errors
    srv = _bare_server()
    with srv.expect_error(errors.ETIMEDOUT) as info:
        errors.check(errors.ETIMEDOUT, "getpid()", errors.RpcError)
    assert isinstance(info.error, errors.TimeoutError)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_errors.py tests/test_server.py -k "timeout or expect_error" -v`
Expected: FAIL, `AttributeError: ... 'RpcTimeoutError'`, and the `expect_error` test fails because the plain `TimeoutError` escapes.

- [ ] **Step 3: Add the classes and the registry**

In `src/pyte/errors.py`, after `TimeoutError`:

```python
class RpcTimeoutError(RpcError, TimeoutError):
    """An RPC call timed out.

    Both an RpcError and a TimeoutError, so ``except RpcError`` no
    longer misses a timeout and ``expect_error(errors.ETIMEDOUT)``
    can match one.  That dual identity is also why the two exits of
    RpcServer._check_call() -- the transport status and the remote
    errno -- no longer need to classify differently.
    """


class CfgTimeoutError(CfgError, TimeoutError):
    """A Configurator request timed out."""


class RcfTimeoutError(RcfError, TimeoutError):
    """An RCF request timed out."""


class EnvTimeoutError(EnvError, TimeoutError):
    """An environment operation timed out."""


class TrcTimeoutError(TrcError, TimeoutError):
    """A TRC operation timed out."""


class JobError(TeError):
    """A tapi_job operation failed."""


class JobTimeoutError(JobError, TimeoutError):
    """A job wait expired, or the job was still running."""


#: cls passed to check() -> the timeout subclass to raise instead.
#: A cls with no entry falls back to the plain TimeoutError, so a new
#: subsystem error class is never silently mis-typed.
_TIMEOUT_FOR: dict[type, type] = {
    RpcError: RpcTimeoutError,
    CfgError: CfgTimeoutError,
    RcfError: RcfTimeoutError,
    EnvError: EnvTimeoutError,
    TrcError: TrcTimeoutError,
    JobError: JobTimeoutError,
}


def _timeout_cls(cls: type) -> type:
    """The most specific registered timeout class for *cls*."""
    for base in cls.__mro__:
        found = _TIMEOUT_FOR.get(base)
        if found is not None:
            return found
    return TimeoutError
```

Replace `check()`:

```python
def check(rc: int, where: str = "", cls: type[TeError] = TeError) -> None:
    """Raise if a te_errno status is non-zero.

    A timeout raises the subsystem's timeout class -- which is both a
    TimeoutError and a *cls* -- so ``except TimeoutError`` and
    ``except RpcError`` both catch an RPC timeout.  It used to raise a
    bare TimeoutError regardless of *cls*, so a timeout was invisible
    to every subsystem-level except clause.
    """
    if rc != 0:
        lib = _shim_lib()
        if lib.pyte_rc_error(rc) == lib.pyte_rc_error(lib.PYTE_ETIMEDOUT):
            raise _timeout_cls(cls)(rc, where)
        if (issubclass(cls, CfgError)
                and lib.pyte_rc_error(rc) ==
                lib.pyte_rc_error(lib.PYTE_ENOENT)):
            raise CfgNotFoundError(rc, where)
        raise cls(rc, where)
```

`RpcError.__init__` takes `(rc, where, err_msg, output)` while the others take `(rc, where)`; `_timeout_cls(cls)(rc, where)` is compatible with both because the extra arguments default.

- [ ] **Step 4: Route _check_call's remote-errno path through check()**

In `src/pyte/rpc/server.py`, replace the tail of `_check_call`:

```python
        rpc_errno = lib.pyte_rpc_errno(self._handle())
        err_msg = ffi.string(lib.pyte_rpc_err_msg(self._handle())).decode(
            errors="replace")
        # Through check() so a remote ETIMEDOUT classifies exactly like
        # a transport-level one: both were RpcError vs TimeoutError
        # four lines apart, and expect_error() could only ever match
        # the remote half.
        try:
            check(rpc_errno, f"{where} -> {retval!r}", RpcError)
        except RpcError as exc:
            exc.err_msg = err_msg
            exc.output = output
            if err_msg:
                exc.args = (f"{exc.args[0]}: {err_msg}",)
            if output:
                excerpt = (output
                           if len(output) <= RpcError._OUTPUT_EXCERPT
                           else "..." + output[-RpcError._OUTPUT_EXCERPT:])
                exc.args = (f"{exc.args[0]} (output: {excerpt!r})",)
            raise
        raise RpcError(rpc_errno, f"{where} -> {retval!r}", err_msg,
                       output=output)
```

The trailing `raise` covers `rpc_errno == 0` (a failed predicate with no errno), which `check()` treats as success.

Alternatively, and more cleanly if the tests allow it: give `RpcError` a classmethod that builds the right class and reuse it in both exits. Pick one, and make `test_sh_failure_message_includes_output_excerpt` and `test_sh_failure_attaches_decoded_output` still pass — they assert on `.output` and on the excerpt in the message.

- [ ] **Step 5: Use JobTimeoutError for the EINPROGRESS mapping**

In `src/pyte/job.py:640-647`, replace `TeTimeoutError` with `JobTimeoutError` and update the docstring: `tapi_job_wait()` reports a still-running job as `TE_EINPROGRESS`; it now becomes a `JobTimeoutError`, still a `TimeoutError`, and now also a `JobError`. Preserve the original `rc` (the `EINPROGRESS` value), which the class stores via `TeError.__init__`.

Update the import at `job.py:15` accordingly, and check every `except TeTimeoutError` in the tree still catches (`batch.py:119,547` aliases `pyte.errors.TimeoutError`, which `JobTimeoutError` subclasses, so it does).

- [ ] **Step 5b: Preserve the native rc explicitly, and fix sleep()'s message**

Two field-contract items the spec calls for.

First, add `native_rc` so a caller can tell a real te_errno from a
message-only failure without comparing `rc` to 0 (which a genuine
`rc == 0` failure, like `RpcServer.sleep`'s, makes ambiguous). On
`TeError`:

```python
        #: The te_errno behind this error, or None when there is none.
        #: rc/module/code stay ints (0 for message-only failures) for
        #: compatibility; this is the unambiguous form.
        self.native_rc: int | None = rc
```

and in `_RcOrMsg`'s string path plus `RemotePythonError.__init__`,
`ClosedResourceError.__init__` and `JobExitError.__init__`, set
`self.native_rc = None` alongside the existing zeroed triple.

Test it:

```python
def test_native_rc_is_none_for_a_message_only_error():
    assert errors.ToolError("bad output").native_rc is None


def test_native_rc_carries_the_errno_for_a_real_failure():
    exc = errors.RpcTimeoutError(errors.ETIMEDOUT, "getpid()")
    assert exc.native_rc == errors.ETIMEDOUT
    assert exc.rc == errors.ETIMEDOUT      # legacy field unchanged
```

Second, `RpcServer.sleep()` (`server.py:270-273`) raises
`RpcError(0, f"sleep(...) exited with status {status}", "")`. `RpcError`
has no message path, so the text is smuggled through *where* and the
user sees a bogus `RPC-OK (0x0)` suffix on a real failure. Raise a
message-only error instead — `JobExitError` is wrong here (there is no
`CompletedJob`), so use `ToolError` or add the one-line message path to
`RpcError`; pick one and pin it:

```python
def test_sleep_failure_message_has_no_bogus_ok_suffix(_no_shim_calls):
    srv = _SleepServer()
    srv.system_status = 1
    with pytest.raises(errors.TeError) as info:
        srv.sleep(1)
    assert "OK (0x0)" not in str(info.value)
    assert "status 1" in str(info.value)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. `test_wait_timeout_logs_ring_and_reraises` in the TRex lifecycle tests catches `pyte.errors.TimeoutError` and still works by inheritance.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "errors: give each subsystem its own timeout class" -m "errors.check() special-cased ETIMEDOUT and then DISCARDED the cls
it was given, so no timeout was ever catchable as its subsystem's
error: 'except RpcError' missed an RPC timeout, 'except ToolError'
missed a tool one.  check() is already the central conversion with
100 call sites through it, so a small registry there upgrades all of
them at once.

Each new class inherits both its subsystem error and
pyte.errors.TimeoutError (which already subclasses
builtins.TimeoutError, and remote._recv depends on that).

RpcTimeoutError also removes the asymmetry inside _check_call, whose
two exits classified the same failure four lines apart -- the
transport status through check() as a TimeoutError, the remote errno
directly as an RpcError.  expect_error(errors.ETIMEDOUT) could
therefore never match the guard path; now it does.

Add JobError/JobTimeoutError for tapi_job failures, and use the
latter for the EINPROGRESS still-running mapping."
```

---

### Task 3: Reject `None` where an unbounded wait cannot be delivered

**Files:**
- Modify: `src/pyte/remote.py:267-291` (`_request`), `:293-316` (`call`, `import_module`)
- Modify: `src/pyte/rpc/server.py:228-255` (`system` docstring and guard)
- Modify: `src/pyte/tad/csap.py:254-282` (`listen`)
- Test: `tests/test_remote.py`, `tests/test_server.py`, `tests/test_csap.py`

**Interfaces:**
- Consumes: `check_timeout` from Task 1.
- Produces: `RemotePython.call/import_module` require an explicit timeout; `remote.DEFAULT` sentinel for "use the session default".

**Background:** `remote.py:279-280` makes `timeout=None` mean the 30 s session default, the exact trap the July review filed as A2 and `fe36c7d` already fixed for mke2fs/ssh/stress. It is also what caused the wave 0 TRex STL defect. The session genuinely cannot wait forever (`remote.py:147-152` marks it `_broken` on timeout and refuses reuse), so the answer is to reject `None`, not to document the inconsistency.

Keeping "use the session default" available matters — most control ops want it — so it gets an explicit sentinel rather than an overloaded `None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_remote.py`, using its `FakeSession`:

```python
def test_call_rejects_none_timeout():
    """None used to mean the 30 s session default, not forever -- the
    trap that killed every TRex STL run longer than 30 s."""
    s = FakeSession()
    s.replies.append({"id": 1, "ok": True, "value": None})
    with pytest.raises(ValueError, match="explicit timeout"):
        s.call(outer, 1, timeout=None)


def test_call_default_uses_the_session_timeout():
    s = FakeSession()
    s.replies.append({"id": 1, "ok": True, "value": None})
    s.call(outer, 1)                     # omitted: session default
    assert s.recv_timeouts == [5.0]      # FakeSession's timeout


def test_call_default_sentinel_is_explicit():
    s = FakeSession()
    s.replies.append({"id": 1, "ok": True, "value": None})
    s.call(outer, 1, timeout=remote.DEFAULT)
    assert s.recv_timeouts == [5.0]


def test_call_rejects_a_negative_timeout():
    s = FakeSession()
    with pytest.raises(ValueError, match="negative"):
        s.call(outer, 1, timeout=-1)
```

`FakeSession._recv` currently discards its argument; extend it to record into `self.recv_timeouts` so these can assert.

Append to `tests/test_csap.py`:

```python
def test_listen_rejects_none_timeout(monkeypatch):
    _fake_shim(monkeypatch)
    c = _bare_csap()
    with pytest.raises(ValueError, match="explicit timeout"):
        c.listen(timeout=None)


def test_listen_rejects_a_negative_timeout(monkeypatch):
    _fake_shim(monkeypatch)
    c = _bare_csap()
    with pytest.raises(ValueError, match="negative"):
        c.listen(timeout=-1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_remote.py tests/test_csap.py -k "none_timeout or negative or default" -v`
Expected: FAIL. `call(timeout=None)` silently uses 30 s; `listen(timeout=None)` raises `TypeError` from the multiplication; `listen(timeout=-1)` reaches the shim.

- [ ] **Step 3: Add the sentinel and reject None in remote**

In `src/pyte/remote.py`, next to `DEFAULT_TIMEOUT`:

```python
#: Sentinel for "use this session's default timeout".
#: An explicit object rather than None: package-wide None means "block
#: forever", which a remote session cannot do -- after a timeout its
#: request/reply pairing is broken and it refuses further use, so an
#: unbounded wait could only ever hang a session with no recovery.
DEFAULT = object()
```

Change `_request`, `call` and `import_module` to take `timeout=DEFAULT`:

```python
    def _request(self, req: dict, timeout=DEFAULT):
        if self._broken is not None:
            raise RemotePythonError(
                f"session unusable: {self._broken}; start a new "
                "remote.python() session")
        if timeout is DEFAULT:
            timeout = self._timeout
        else:
            timeout = _time.check_timeout(
                timeout, allow_none=False, who="remote call")
        self._last_id += 1
        req = {"id": self._last_id, **req}
        if self._dead:
            # Release garbage-collected proxies' remote objects, no
            # extra round trip.
            req["free"], self._dead = self._dead, []
        self._send(req)
        resp = self._recv(timeout)
        # ... the id check and the ok/error handling below are
        # unchanged; only the timeout resolution above moved.
```

Everything after `self._recv(timeout)` stays exactly as it is: the response-id check, the `resp["ok"]` branch and the `self._decode(...)` return.

Update `call`'s docstring: *timeout* bounds this one round trip; omit it (or pass `remote.DEFAULT`) for the session default; `None` is rejected because this session cannot wait forever.

- [ ] **Step 4: Reject None in csap.listen**

`src/pyte/tad/csap.py:254-282`: Task 1 already routed the conversion through `_time.to_ms(..., allow_none=False, who="Csap.listen()")`. Change the signature to `timeout: float = DEFAULT_TIMEOUT` (unchanged) and add to the docstring that the deadline is baked in at `listen()` — `Receiver.wait()` takes no timeout of its own — and that `None` is not accepted because the agent-side receive is bounded when it starts.

- [ ] **Step 4b: Decide what csap's swallowed timeout means**

`Receiver._finish` (`csap.py:157-160`) deliberately swallows
`ETIMEDOUT`: "a timeout only means fewer packets matched than
requested; report what arrived and let the test judge the count."
That is a real design decision and this wave must NOT convert it into a
raise — several showcase tests depend on `wait()` returning a short
list.

But it is the fourth independent error classifier in the tree, and it
is invisible: a caller cannot tell "the listen deadline expired with 2
of 5 packets" from "5 packets arrived". Add the distinction without
changing the return type:

```python
    #: True when the listen deadline expired before ``count`` packets
    #: arrived.  The packets that did arrive are still returned -- a
    #: timeout is not an error here -- but a test that cares can check
    #: this instead of inferring it from len().
    self.timed_out: bool = False
```

set in `_finish` on the ETIMEDOUT branch, and documented on `wait()`.
Pin it:

```python
def test_wait_reports_that_it_timed_out(monkeypatch):
    lib = _fake_shim(monkeypatch)
    c = _bare_csap()
    rx = Receiver(c)
    c._rx = rx
    lib.recv_rc = lib.PYTE_ETIMEDOUT
    lib.recv_pkts = ["p1"]
    pkts = rx.wait()
    assert len(pkts) == 1
    assert rx.timed_out


def test_wait_does_not_flag_a_complete_receive(monkeypatch):
    lib = _fake_shim(monkeypatch)
    c = _bare_csap()
    rx = Receiver(c)
    c._rx = rx
    lib.recv_rc = 0
    lib.recv_pkts = ["p1", "p2"]
    rx.wait()
    assert not rx.timed_out
```

- [ ] **Step 5: Document system()'s third meaning**

`src/pyte/rpc/server.py:228-255`: do not change behavior (`None` sends 0 ms, meaning "leave the RCF default alone"; 0 is rejected). Correct the docstring to say so explicitly, and route the guard through `_time.check_timeout(timeout, who="system()")` plus the existing `<= 0` rejection so NaN and infinity are caught at the boundary too.

- [ ] **Step 6: Fix the TRex callers**

`src/pyte/tools/trex/stl.py` and `astf.py` were fixed in wave 0 to require an explicit timeout and pass `timeout + WAIT_MARGIN` to the transport. Their `_call` still passes `timeout=None` for control ops, which now raises. Change both to pass `timeout=remote.DEFAULT` in that case, and update the `_call` docstring.

Run `.venv/bin/python -m pytest tests/test_trex_stl.py tests/test_trex_astf_client.py -q` and confirm.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 8: Check the consuming suites**

Run: `grep -rn 'timeout=None' /home/kostik/prj/te/{python-ts,nap-ts,nvme-ts,app-perf-ts-py} --include='*.py' | grep -v '/lib/pyte/' | grep -iE 'call|listen|remote'`
Any hit is a call site this task breaks. Record it in the commit body so the suite bump is not a surprise. nvme-ts's `agent.py` passes `timeout=timeout + _RPC_SLACK` explicitly, so it should be unaffected.

- [ ] **Step 9: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "remote: reject a None timeout instead of faking one" -m "RemotePython.call(timeout=None) meant 'the 30 s session default',
not the package-wide 'block forever'.  That is the same trap the
July review filed as A2 and fe36c7d already fixed for
mke2fs/ssh/stress, and it is what made every TRex STL run longer
than 30 s fail: the caller asked for 600 s, the transport gave up at
30 and marked the session broken.

A remote session genuinely cannot wait forever -- after a timeout
its request/reply pairing is broken and it refuses further use -- so
None is now rejected with an error saying so, and 'use the session
default' gets an explicit remote.DEFAULT sentinel instead of an
overloaded None.

Csap.listen() gains the same explicit rejection plus the negative
check it never had, and RpcServer.system()'s docstring now states
that its None means the RCF default rather than forever.

BREAKING: rem.call(timeout=None) raises ValueError; pass a number or
remote.DEFAULT."
```

---

### Task 4: Genuinely unbounded waits, by slicing

**Files:**
- Modify: `src/pyte/job.py` (`Job.wait`, `receive_any`, `Filter.read_many`, `poll`)
- Modify: `src/pyte/rpc/iomux.py` (`IoMux.wait`)
- Test: `tests/test_job.py`, `tests/test_iomux.py`

**Interfaces:**
- Consumes: `Deadline` from Task 1, `JobTimeoutError` from Task 2.
- Produces: no signature change; `timeout=None` now waits without a hidden cap.

**Background:** pyte passes `-1` and TE supplies the bound: 600 s for jobs, and **10 s** for iomux, because `unistd.c:1771` skips the extension for a negative timeout. Expiry is destructive — the agent watchdog sets `rpcs->dead` and the server is unusable until restarted — so "blocks indefinitely" is currently a server-killing operation.

Slice at 1 s. Retry **only** an ordinary "still running" or "no data yet". Never retry a transport failure, a dead server, or an arbitrary error.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_job.py`:

```python
def test_wait_none_slices_instead_of_asking_for_minus_one(
        monkeypatch, fake_clock):
    """timeout=None promised 'forever' but handed -1 to TE, which caps
    it at 600 s and then kills the RPC server."""
    lib = _fake_shim(monkeypatch)
    fake_clock.patch(pyte.job)
    job = _fake_job(handle="job-h")
    # still running for the first three slices, then exits
    lib.wait_sequence = [lib.PYTE_EINPROGRESS] * 3 + [0]
    job.wait(timeout=None)
    waits = [c[1] for c in lib.calls if c[0] == "job_wait"]
    assert -1 not in waits
    assert waits == [1000, 1000, 1000, 1000]


def test_wait_none_spans_more_than_ten_minutes(monkeypatch, fake_clock):
    lib = _fake_shim(monkeypatch)
    fake_clock.patch(pyte.job)
    job = _fake_job(handle="job-h")
    lib.wait_sequence = [lib.PYTE_EINPROGRESS] * 900 + [0]
    job.wait(timeout=None)               # 15 minutes of slices
    assert len([c for c in lib.calls if c[0] == "job_wait"]) == 901


def test_finite_wait_stops_at_its_deadline(monkeypatch, fake_clock):
    lib = _fake_shim(monkeypatch)
    fake_clock.patch(pyte.job)
    job = _fake_job(handle="job-h")
    lib.wait_sequence = [lib.PYTE_EINPROGRESS] * 100
    from pyte.errors import JobTimeoutError
    with pytest.raises(JobTimeoutError):
        job.wait(timeout=2.5)
    waits = [c[1] for c in lib.calls if c[0] == "job_wait"]
    assert sum(waits) <= 2500
    assert waits[-1] == 500              # the remaining budget


def test_wait_does_not_retry_an_arbitrary_failure(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    lib.wait_sequence = [12, 0]          # a real failure, then success
    from pyte.errors import TeError
    with pytest.raises(TeError):
        job.wait(timeout=None)
    assert len([c for c in lib.calls if c[0] == "job_wait"]) == 1


def test_zero_timeout_probes_once(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    lib.wait_sequence = [lib.PYTE_EINPROGRESS]
    from pyte.errors import JobTimeoutError
    with pytest.raises(JobTimeoutError):
        job.wait(timeout=0)
    assert [c[1] for c in lib.calls if c[0] == "job_wait"] == [0]
```

`FakeLib` needs a `wait_sequence` list that `pyte_job_wait` pops from; add it in the file's existing style, next to the current `wait_result`.

Append the equivalent to `tests/test_iomux.py`:

```python
def test_wait_none_slices_instead_of_minus_one(monkeypatch, fake_clock):
    """The iomux cap is 10 s, not 10 minutes: unistd.c skips the
    timeout extension for a negative value, so -1 fell back to
    RCF_RPC_DEFAULT_TIMEOUT."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    fake_clock.patch(_iomux_mod)
    mux = IoMux.create(FakeServer(), Kind.EPOLL)
    lib.call_sequence = [(0, [])] * 3 + [(1, [3, lib.PYTE_IOMUX_EVT_IN])]
    mux.wait(None)
    calls = [c[1] for c in lib.calls if c[0] == "call"]
    assert -1 not in calls
    assert calls == [1000, 1000, 1000, 1000]


def test_finite_wait_still_returns_empty_on_expiry(monkeypatch,
                                                   fake_clock):
    """Unlike a job receive, an iomux timeout is [] and not an error."""
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    fake_clock.patch(_iomux_mod)
    mux = IoMux.create(FakeServer(), Kind.EPOLL)
    lib.call_sequence = [(0, [])] * 100
    assert mux.wait(2.0) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_job.py tests/test_iomux.py -k "slices or ten_minutes or deadline or arbitrary or probes or empty" -v`
Expected: FAIL. Both still hand `-1` to the backend in one call.

- [ ] **Step 3: Implement slicing in job.wait**

In `src/pyte/job.py`, add a module constant and rewrite `wait`:

```python
#: Longest single backend wait, seconds.  TE bounds what "-1 ms" means
#: (TAPI_RPC_JOB_BIG_TIMEOUT_MS is 600 s for jobs), and an expiry is
#: not benign: the agent watchdog marks the RPC server dead, so it is
#: unusable until restarted.  An unbounded wait is therefore a loop of
#: short bounded ones, not one long one.
_WAIT_SLICE = 1.0


    def wait(self, timeout: float | None = DEFAULT_TIMEOUT) -> JobStatus:
        """Wait for completion; raises JobTimeoutError if still running.

        ``timeout=None`` blocks until the job completes, for real: the
        wait is a loop of one-second backend calls rather than a single
        "-1 ms", which TE caps at 600 s and then treats as a dead
        server.  ``timeout=0`` probes once.

        Only a still-running result (TE_EINPROGRESS) is retried; a
        transport failure or any other error propagates immediately.
        """
        h = self._handle()
        ffi, lib = _shim()
        deadline = _time.Deadline(timeout, who=f"job.wait({self.program})")
        while True:
            otype = ffi.new("int *")
            oval = ffi.new("int *")
            slice_s = deadline.slice(_WAIT_SLICE)
            rc = lib.pyte_job_wait(h, _time.to_ms(slice_s), otype, oval)
            still_running = (rc != 0 and lib.pyte_rc_error(rc) ==
                             lib.pyte_rc_error(lib.PYTE_EINPROGRESS))
            if not still_running:
                check(rc, f"job.wait({self.program})", JobError)
                kind = {lib.PYTE_JOB_EXITED: StatusKind.EXITED,
                        lib.PYTE_JOB_SIGNALED: StatusKind.SIGNALED}.get(
                            otype[0], StatusKind.UNKNOWN)
                return JobStatus(kind, oval[0])
            if deadline.total is not None and deadline.expired:
                raise JobTimeoutError(rc, f"job.wait({self.program}): "
                                          "still running")
            if deadline.total == 0:
                raise JobTimeoutError(rc, f"job.wait({self.program}): "
                                          "still running")
```

The `deadline.total == 0` branch preserves the single-probe semantics of `timeout=0`, which `Job.drain()` and the TRex tests depend on.

- [ ] **Step 4: Implement slicing for receive, read_many, poll and iomux**

Apply the same shape to `receive_any`, `Filter.read_many` and `poll` in `job.py`, and to `IoMux.wait` in `iomux.py`. The differences to respect:

- `receive_any`/`poll` raise on expiry (a `TimeoutError` today), so the retry condition is "the backend reported a timeout and the deadline has not expired".
- `Filter.read_many` treats a timeout as "return what arrived", so it must NOT loop once any message has been collected; only an empty result with an unexpired deadline retries.
- `IoMux.wait` returns `[]` on expiry and must keep doing so. Its retry condition is `n == 0` with an unexpired deadline.

Keep `timeout=0` a single probe in all four.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. `test_wait_accepts_none` asserts `("job_wait", -1) in lib.calls` and now needs updating to assert the slice instead — that assertion encodes the bug.

- [ ] **Step 6: Document the cost**

Update the `pyte.job` and `pyte.rpc.iomux` module docstrings: a deadline bounds the *requested* wait; native transport overhead and teardown can extend the wall-clock duration beyond it, and an unbounded wait costs one RPC per second.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "job: make an unbounded wait actually unbounded" -m "timeout=None was documented as 'block forever' and implemented as a
single '-1 ms' backend call.  TE bounds what that means -- 600 s for
jobs (TAPI_RPC_JOB_BIG_TIMEOUT_MS) and only 10 s for iomux, because
tapi_rpc/unistd.c skips the timeout extension for a negative value
and falls back to RCF_RPC_DEFAULT_TIMEOUT.  Worse, the expiry is not
benign: the agent watchdog sets rpcs->dead and the server is
unusable until restarted, so 'block forever' was a server-killing
operation.

Implement unbounded waits as a loop of one-second bounded calls
driven by an absolute deadline, retrying ONLY an ordinary
still-running / no-data-yet result.  A transport failure or any
other error propagates on the first attempt.  timeout=0 still probes
exactly once, which Job.drain() depends on."
```

---

### Task 5: One deadline per operation

**Files:**
- Modify: `src/pyte/job.py:426-444` (module `run()`)
- Modify: `src/pyte/rpc/server.py:329-340` (`run()`'s default)
- Modify: `src/pyte/tools/_tool.py:257-267` (`_remaining`)
- Modify: `src/pyte/tools/iperf3.py:239-240`, `src/pyte/tools/ethtool.py:349-351`
- Modify: `src/pyte/job.py:245-269,320-331` (`messages`, `read_all`)
- Test: `tests/test_job.py`, `tests/test_tool_helpers.py`, `tests/test_iperf3.py`, `tests/test_ethtool.py`

**Interfaces:**
- Consumes: `Deadline` from Task 1.
- Produces: keyword-only `total_timeout: float | None = None` on `Filter.messages` and `Filter.read_all`.

**Background:** module-level `run()` spends the full timeout **three** times (wait, stdout, stderr), and `RpcServer.run()` inherits it — a default of 10 s can take 30. `fe36c7d` fixed only the three tool `wait()` overrides; `iperf3._read_output` and `ethtool` still double-spend. `_tool._remaining` floors at 1.0 s, so a `wait(timeout=T)` can take `T + 1`. `RpcServer.run()`'s default is the literal `10.0` while its docstring claims `job.DEFAULT_TIMEOUT`.

`Filter.messages`/`read_all` are per-receive inactivity timeouts, which is correct and stays — but there is no way to bound total time, so a steadily chatty process holds `read_all(timeout=10)` for hours. `remote._recv` already implements the right pattern and is the model.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_job.py`:

```python
def test_run_shares_one_deadline_across_wait_and_both_reads(
        monkeypatch, fake_clock):
    """run() spent the full timeout three times: wait, stdout, stderr."""
    import pyte.job
    fake_clock.patch(pyte.job)
    reads = []

    class _F:
        def read_all(self, timeout=None, total_timeout=None):
            reads.append(total_timeout)
            fake_clock.advance(2.0)
            return "data"

    class _Chan:
        def attach_filter(self, name=None, log_level=None):
            return _F()

    class _Job:
        program = "prog"
        stdout = _Chan()
        stderr = _Chan()

        def start(self):
            pass

        def wait(self, timeout=None):
            fake_clock.advance(6.0)
            return pyte.job.JobStatus(pyte.job.StatusKind.EXITED, 0)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(pyte.job.Job, "create",
                        classmethod(lambda cls, *a, **k: _Job()))
    pyte.job.run(object(), "prog", timeout=10.0)
    assert reads == [4.0, 2.0]   # 10 - 6 consumed, then 4 - 2


def test_read_all_total_timeout_bounds_a_chatty_stream(
        monkeypatch, fake_clock):
    """A process that keeps talking must not hold read_all forever."""
    lib = _fake_shim(monkeypatch)
    fake_clock.patch(pyte.job)
    flt = _fake_filter(lib)
    lib.recv_forever = "chunk"          # never sends eos
    from pyte.errors import TimeoutError as TeTimeoutError
    with pytest.raises(TeTimeoutError):
        flt.read_all(timeout=1.0, total_timeout=5.0)


def test_read_all_without_total_timeout_is_unchanged(monkeypatch):
    lib = _fake_shim(monkeypatch)
    flt = _fake_filter(lib)
    lib.recv_bufs = [b"a", b"b"]        # then eos
    assert flt.read_all(timeout=1.0) == "ab"
```

Fill in the first test against the file's `FakeLib`, having `pyte_job_wait` call `fake_clock.advance(6.0)`.

Append to `tests/test_tool_helpers.py`:

```python
def test_remaining_has_no_one_second_floor(fake_clock):
    """The floor let wait(timeout=T) actually take T + 1."""
    fake_clock.patch(_tool)
    start = _tool.time.monotonic()
    fake_clock.advance(30.0)
    assert _tool.ToolHandle._remaining(30.0, start) == 0.0


def test_remaining_is_none_for_an_unbounded_timeout():
    assert _tool.ToolHandle._remaining(None, 0.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_job.py tests/test_tool_helpers.py -k "one_deadline or total_timeout or floor" -v`
Expected: FAIL. `run()` passes the full timeout three times; `read_all` has no `total_timeout`; `_remaining` returns 1.0.

- [ ] **Step 3: Add total_timeout to the stream helpers**

In `src/pyte/job.py`:

```python
    def messages(self, timeout: float | None = DEFAULT_TIMEOUT, *,
                 total_timeout: float | None = None,
                 ) -> Iterator[JobMessage]:
        """Yield messages until all attached channels have sent eos.

        ``timeout`` is a per-receive INACTIVITY timeout, forwarded to
        each :meth:`receive`: it bounds how long one message may take
        to arrive, not how long the whole stream may run.

        ``total_timeout`` bounds the whole operation.  Without it a
        steadily chatty process can hold this call open indefinitely,
        because every individual receive keeps succeeding.  Each
        receive waits the smaller of the remaining total budget and
        the inactivity timeout.
        """
        deadline = _time.Deadline(total_timeout, who="Filter.messages()")
        eos_seen = 0
        while eos_seen < self._n_channels:
            wait = (timeout if total_timeout is None
                    else deadline.slice(timeout if timeout is not None
                                        else _WAIT_SLICE))
            msg = self.receive(timeout=wait)
            if msg.eos:
                eos_seen += 1
            else:
                yield msg
```

Mirror the parameter on `read_all` and forward it. `__iter__` keeps calling `messages()` with defaults.

- [ ] **Step 4: Give run() one deadline**

```python
def run(server: "RpcServer", program: str, args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = DEFAULT_TIMEOUT) -> CompletedJob:
    """Run *program* to completion and capture its output.

    The ``subprocess.run()`` of tapi_job.  A non-zero exit is a
    result, not an exception -- check ``.status`` / ``.ok`` -- but a
    job still running when *timeout* expires raises JobTimeoutError.

    *timeout* is ONE deadline covering the wait and both output
    reads.  It used to be spent in full three times over, so a
    ten-second call could take thirty.
    """
    deadline = _time.Deadline(timeout, who=f"run({program})")
    with Job.create(server, program, args or [], env) as job:
        out = job.stdout.attach_filter(name="stdout", log_level="RING")
        err = job.stderr.attach_filter(name="stderr", log_level="RING")
        job.start()
        status = job.wait(timeout=deadline.remaining())
        return CompletedJob(
            status=status,
            stdout=out.read_all(total_timeout=deadline.remaining()),
            stderr=err.read_all(total_timeout=deadline.remaining()))
```

- [ ] **Step 5: Fix the remaining double-spends and the floor**

`src/pyte/rpc/server.py:332`: change the default from the literal `10.0` to `job.DEFAULT_TIMEOUT` (imported locally, as `run` already is) so the docstring stops lying.

`src/pyte/tools/_tool.py:257-267`: drop the `1.0` floor — `return max(timeout - (time.monotonic() - start), 0.0)` — and update the docstring, which currently documents the floor.

`src/pyte/tools/iperf3.py:239-240` and `src/pyte/tools/ethtool.py:349-351`: route both reads through `self._remaining(...)` the way `ToolHandle.wait` does, instead of passing the full timeout twice.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. `test_wait_shares_one_deadline_across_wait_and_read` (in both `test_tool_helpers.py` and `test_mke2fs.py`) asserts `reads == [10.0]` for a 30 s timeout with 20 s consumed; with the floor removed that stays 10.0, so both still pass.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "job: spend one deadline per run, not three" -m "Module-level run() passed the full timeout to job.wait() and then
again to each of the two read_all() calls, so RpcServer.run()'s
ten-second default could take thirty.  fe36c7d fixed only the three
tool wait() overrides; iperf3 and ethtool still spent theirs twice.

Give run() one Deadline covering all three steps, route the two
remaining tool hooks through _remaining(), and drop that helper's
one-second floor, which let wait(timeout=T) take T + 1.

Filter.messages()/read_all() keep their per-receive inactivity
timeout -- that is the right contract -- and gain a keyword-only
total_timeout for callers who need to bound the whole operation: a
steadily chatty process could otherwise hold read_all() open
indefinitely, since every individual receive kept succeeding.

Also make RpcServer.run()'s default actually be job.DEFAULT_TIMEOUT
rather than a literal 10.0 its docstring claimed it was."
```

---

### Task 6: Tell a dead transport from an expired wait

**Files:**
- Modify: `shim/pyte_shim.h` (new `PYTE_E*` constants), `shim/pyte_shim_cdef.h`, `shim/pyte_shim.c`
- Modify: `src/pyte/rpc/server.py` (add `is_dead`)
- Modify: `docs/guides/caveats.md`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: Task 2's error classes.
- Produces: `pyte.errors.ERPCTIMEOUT/ERPCDEAD/ERPCKILLED` constants; `RpcServer.is_dead -> bool`.

**Background:** TE distinguishes these (`te/include/te_errno.h:233-235`, sticky flag at `te/lib/rcfrpc/rcf_rpc.h:154`) and pyte throws it away. The shim exposes only 8 `PYTE_E*` constants with no `ERPCTIMEOUT`, never exposes `rpcs->timed_out`, and job/iomux paths lose the errno to `TAPI_JMP_DO(TE_EFAIL)` before Python sees it (`tapi_rpc_internal.h:135` plus `PYTE_GUARD`). A dead agent, a job RPC timeout and an unrelated TAPI verdict are all one `TAPI-EFAIL`.

This is **shim work, not Python work**. Scope it honestly: the full fix needs the guard to capture `rpcs->_errno` before the longjmp, which no current shim call does.

- [ ] **Step 1: Decide the scope and write it down**

Read `shim/pyte_shim.h`'s `PYTE_GUARD` (around line 1007) and `pyte_shim.c:2199-2201`, which deliberately does not re-arm `RPC_AWAIT_ERROR` around job calls. Write a short comment block in `pyte_shim.h` recording what is and is not being fixed here. If capturing the errno before the longjmp turns out to require touching every guarded call, split that into its own task rather than half-doing it.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_server.py`:

```python
def test_is_dead_reports_an_unusable_server(monkeypatch):
    """After an RPC timeout TE marks the server dead and it stays
    unusable until restarted; pyte had no way to see that."""
    lib = _fake_lifecycle_shim(monkeypatch)   # from wave 1 task 2
    lib.dead = 1
    srv = RpcServer(object(), "Agt", "pco")
    assert srv.is_dead


def test_is_dead_is_false_for_a_healthy_server(monkeypatch):
    lib = _fake_lifecycle_shim(monkeypatch)
    lib.dead = 0
    srv = RpcServer(object(), "Agt", "pco")
    assert not srv.is_dead
```

Add `pyte_rpc_is_dead` to `_LifecycleLib`, returning `self.dead`.

- [ ] **Step 3: Add the shim accessor and constants**

In `shim/pyte_shim.h`, add the missing errno passthroughs beside the existing eight:

```c
#define PYTE_ERPCTIMEOUT TE_ERPCTIMEOUT
#define PYTE_ERPCDEAD    TE_ERPCDEAD
#define PYTE_ERPCKILLED  TE_ERPCKILLED
```

In `shim/pyte_shim.c` and the cdef:

```c
int
pyte_rpc_is_dead(rcf_rpc_server *rpcs)
{
    /* rcf_rpc.h documents this as sticky: once an RPC times out the
     * agent watchdog marks the server dead and it is unusable until
     * someone restarts it.  Python had no way to see that, so a test
     * could only discover it by failing again. */
    return rpcs->dead ? 1 : 0;
}
```

- [ ] **Step 4: Expose it in Python**

In `src/pyte/rpc/server.py`:

```python
    @property
    def is_dead(self) -> bool:
        """Whether TE has marked this RPC server unusable.

        An RPC timeout is not benign: the agent watchdog sets
        rpcs->dead and the server stays unusable until it is
        restarted.  Check this after catching an RpcTimeoutError
        rather than retrying the call.
        """
        lib = _shim_lib()
        return bool(lib.pyte_rpc_is_dead(self._handle()))
```

- [ ] **Step 5: Document it**

Add to `docs/guides/caveats.md`: an RPC timeout marks the server dead; `pyte.errors.RpcTimeoutError` is both an `RpcError` and a `TimeoutError`; check `pco.is_dead` before reusing a server after one. Also note that job and iomux failures still surface as `TAPI-EFAIL` because TE longjmps before the errno reaches the shim — say so plainly rather than implying the distinction is available everywhere.

- [ ] **Step 6: Rebuild the shim, run tests, verify live**

Rebuild with `TE_INSTALL` set. Run `.venv/bin/python -m pytest tests/ -q`. Do not claim the C side works from fake-shim results alone.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "rpc: expose whether the server was marked dead" -m "TE distinguishes TE_ERPCTIMEOUT, TE_ERPCDEAD and TE_ERPCKILLED and
keeps a sticky rpcs->dead flag, but the shim exposed neither the
constants nor the flag, so a dead agent, an RPC timeout and an
unrelated TAPI verdict all reached Python as one TAPI-EFAIL.

Add the three errno passthroughs and pyte_rpc_is_dead(), surfaced as
RpcServer.is_dead, so a caller who catches a timeout can tell that
the server needs restarting rather than retrying into a corpse.

Job and iomux paths still flatten to TAPI-EFAIL: TE longjmps with
TE_EFAIL before the errno reaches the shim guard, and capturing it
there is a separate change.  caveats.md now says so."
```

---

## Wave 2 exit criteria

- [ ] `.venv/bin/python -m pytest tests/ -q` green; no test sleeps (`grep -rn 'time.sleep' tests/` returns nothing).
- [ ] `grep -rn 'int(timeout \* 1000)' src/pyte/` returns nothing outside `_time.py`.
- [ ] `grep -rn '\-1 if timeout is None' src/pyte/` returns nothing.
- [ ] A fake-clock test proves an unbounded job wait spans more than ten minutes without a real delay.
- [ ] Every timeout is catchable both as `pyte.errors.TimeoutError` and as its subsystem error; `expect_error(errors.ETIMEDOUT)` matches the guard path.
- [ ] The `None` policy table at the top of this plan matches the code, and each row is stated in the relevant docstring.
- [ ] Every exception carries `native_rc`: the errno, or None when
      there is none. The legacy `rc`/`module`/`code` ints are
      unchanged.
- [ ] `Receiver.timed_out` distinguishes a short receive from a
      complete one, without changing what `wait()` returns.
- [ ] Shim rebuilt; `is_dead` verified against a live agent.
