# Wave 3: Process Execution and Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `sh()` usable for the 28 call sites that actually exist, and make a TRex report something you can read twice.

**Architecture:** Two unrelated fixes that share a theme: pyte's result objects throw away information the caller needs. `sh()` returns stdout only and discards stderr, which is why nvme-ts declined pyte and built its own `CmdResult`; adopt that proven shape. `Trex.report()` drains its filters, so the report exists exactly once and only inside the `with` block; cache it the way `ToolHandle.wait()` already does. Publishing the report types is part of the same fix, because nap-ts currently annotates against a private module.

**Tech Stack:** Python 3.11+, cffi shim over TE C libraries, pytest.

**Spec:** `/home/kostik/prj/te/pyte-api-fixes-plan-2026-09-07.md` (wave 3 section). Evidence: `/home/kostik/prj/te/pyte-api-fixes-review-2026-09-07.md`.

## Global Constraints

- Repo `/home/kostik/prj/te/pyte`, branch `trexb`. Test with `.venv/bin/python -m pytest tests/ -q`; never `uv run pytest`.
- Lint with `ruff check src tests setup.py`.
- Waves 1 and 2 landed first: this plan uses `cleanup_all`, `Deadline` and `JobError`.
- Style: 4-space indent, wrap at 79 columns. `git commit -s`, summary at most 60 chars, no AI attribution trailers.
- Breaking changes permitted; name each in the commit body.

## What the usage numbers say

Call sites across the four consuming suites, excluding vendored `lib/pyte/`:

| API | python-ts | nap-ts | nvme-ts | app-perf-ts-py | total |
|---|---|---|---|---|---|
| `RpcServer.sh()` | 15 | 3 | 0 | 10 | **28** |
| `RpcServer.system()` | 0 | 2 | 0 | 7 | **9** |
| `RpcServer.run()` | 3 | 0 | 0 | 0 | **3** |

All three `run()` sites are python-ts showcase demos of the API itself. nvme-ts uses none of them: it built `CmdResult(rc, out, err)` with an `ok: bool = True` opt-in check (`nvme-ts/lib/nvmets/src/nvmets/agent.py:27-80`) and roughly 40 call sites. That is the shape to adopt — the first draft of the spec proposed elevating `run()` instead, which serves 3 call sites and ignores 28.

---

### Task 1: Give CompletedJob the fields an error message needs

**Files:**
- Modify: `src/pyte/job.py:413-423` (`CompletedJob`), `:426-444` (`run`)
- Test: `tests/test_job.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CompletedJob.program: str`, `.argv: list[str]`, `.returncode: int`. Task 2 needs all three.

**Background:** `CompletedJob` is `(status, stdout, stderr)` plus an `ok` property. It has no `argv`, no `program` and no plain `returncode`, so a `check_returncode()` built on it could not name the failing command — strictly worse than `subprocess.CalledProcessError`. Add the fields first.

`returncode` must not lie about a signalled job: `JobStatus` is `(kind, value)` where kind is `EXITED`, `SIGNALED` or `UNKNOWN`. Follow the `subprocess` convention — a signal is a negative return code.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_job.py`:

```python
def test_completed_job_carries_the_command():
    from pyte.job import CompletedJob, JobStatus, StatusKind
    res = CompletedJob(status=JobStatus(StatusKind.EXITED, 0),
                       stdout="", stderr="",
                       program="ls", argv=["ls", "-l"])
    assert res.program == "ls"
    assert res.argv == ["ls", "-l"]


def test_returncode_is_the_exit_status():
    from pyte.job import CompletedJob, JobStatus, StatusKind
    res = CompletedJob(status=JobStatus(StatusKind.EXITED, 3),
                       stdout="", stderr="", program="p", argv=["p"])
    assert res.returncode == 3
    assert not res.ok


def test_returncode_is_negative_for_a_signalled_job():
    """subprocess convention: a signal reads as -N, so a caller cannot
    mistake 'killed by SIGTERM' for 'exited 15'."""
    from pyte.job import CompletedJob, JobStatus, StatusKind
    res = CompletedJob(status=JobStatus(StatusKind.SIGNALED, 15),
                       stdout="", stderr="", program="p", argv=["p"])
    assert res.returncode == -15
    assert not res.ok


def _run_against_fake(monkeypatch, exit_code=0, **kw):
    """Drive module-level run() with a job that exits `exit_code`."""
    import pyte.job

    class _F:
        def read_all(self, timeout=None, total_timeout=None):
            return ""

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
            return pyte.job.JobStatus(pyte.job.StatusKind.EXITED,
                                      exit_code)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(pyte.job.Job, "create",
                        classmethod(lambda cls, *a, **k: _Job()))
    return pyte.job.run(object(), "ls", ["-l"], **kw)


def test_run_records_the_command_it_ran(monkeypatch):
    res = _run_against_fake(monkeypatch)
    assert res.program == "ls"
    assert res.argv == ["ls", "-l"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_job.py -k "completed_job or returncode or records_the_command" -v`
Expected: FAIL, `TypeError: CompletedJob.__init__() got an unexpected keyword argument 'program'`.

- [ ] **Step 3: Extend the dataclass**

In `src/pyte/job.py`:

```python
@dataclass(frozen=True)
class CompletedJob:
    """Result of :func:`run`: the command, its status and its output.

    Carries the command it ran because a failure message that cannot
    name the command is not much of a failure message (cf.
    ``subprocess.CalledProcessError``, which carries ``cmd``).
    """
    status: JobStatus
    stdout: str
    stderr: str
    program: str = ""
    argv: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True iff the job exited normally with code 0."""
        return self.status.ok

    @property
    def returncode(self) -> int:
        """Exit status, or -N when a signal N killed the job.

        Follows the subprocess convention so 'killed by SIGTERM' can
        never be read as 'exited 15'.  An UNKNOWN completion reads as
        -1; check ``.status`` when the distinction matters.
        """
        if self.status.kind is StatusKind.EXITED:
            return self.status.value
        if self.status.kind is StatusKind.SIGNALED:
            return -self.status.value
        return -1
```

Add `field` to the `dataclasses` import. The two new fields default, so every existing positional/keyword construction keeps working.

In `run()`, pass them:

```python
        return CompletedJob(
            status=status,
            stdout=out.read_all(total_timeout=deadline.remaining()),
            stderr=err.read_all(total_timeout=deadline.remaining()),
            program=program, argv=[program, *(args or [])])
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "job: let CompletedJob name the command it ran" -m "CompletedJob was (status, stdout, stderr) with no argv, no program
and no plain returncode, so anything built on it -- a
check_returncode(), a tool wrapper's error text -- could not say
which command failed.  That is strictly worse than
subprocess.CalledProcessError and it is why nvme-ts built its own
result type instead of using this one.

Add program/argv (defaulted, so existing constructions still work)
and a returncode property following the subprocess convention: a
signal reads as -N, so it can never be mistaken for an exit status."
```

---

### Task 2: Opt-in checked execution

**Files:**
- Modify: `src/pyte/errors.py` (add `JobExitError`)
- Modify: `src/pyte/job.py` (`CompletedJob.check_returncode`, `run(check=)`, `Job.run(check=)`)
- Modify: `src/pyte/rpc/server.py:329-340` (`run(check=)`)
- Test: `tests/test_job.py`, `tests/test_errors.py`

**Interfaces:**
- Consumes: `CompletedJob.returncode/program/argv` from Task 1, `JobError` from wave 2.
- Produces: `pyte.errors.JobExitError(JobError)` with `.result: CompletedJob`; keyword-only `check: bool = False` on `job.run()` and `RpcServer.run()`; `CompletedJob.check_returncode()`.

**Default stays `False`.** "A non-zero exit is a result, not an exception" is the documented contract of `run()` and `system()`, and changing it would break every existing caller silently. This is opt-in only. (Folds in D14 from the July review, `JobStatus.raise_if_not_ok()`.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_job.py`:

```python
def test_check_returncode_is_a_no_op_on_success():
    from pyte.job import CompletedJob, JobStatus, StatusKind
    CompletedJob(JobStatus(StatusKind.EXITED, 0), "", "",
                 program="p", argv=["p"]).check_returncode()


def test_check_returncode_raises_with_the_full_result():
    from pyte.errors import JobExitError
    from pyte.job import CompletedJob, JobStatus, StatusKind
    res = CompletedJob(JobStatus(StatusKind.EXITED, 3),
                       stdout="out", stderr="the actual reason",
                       program="mkfs", argv=["mkfs", "/dev/x"])
    with pytest.raises(JobExitError) as info:
        res.check_returncode()
    assert info.value.result is res
    assert "mkfs /dev/x" in str(info.value)
    assert "the actual reason" in str(info.value)


def test_check_returncode_falls_back_to_stdout_when_stderr_is_empty():
    from pyte.errors import JobExitError
    from pyte.job import CompletedJob, JobStatus, StatusKind
    res = CompletedJob(JobStatus(StatusKind.EXITED, 1),
                       stdout="only stdout said anything", stderr="",
                       program="p", argv=["p"])
    with pytest.raises(JobExitError, match="only stdout"):
        res.check_returncode()


def test_run_does_not_raise_by_default(monkeypatch):
    """The documented contract: a non-zero exit is a result."""
    res = _run_against_fake(monkeypatch, exit_code=3)
    assert res.returncode == 3          # no exception
    assert not res.ok


def test_run_check_true_raises(monkeypatch):
    from pyte.errors import JobExitError
    with pytest.raises(JobExitError, match="rc=3"):
        _run_against_fake(monkeypatch, exit_code=3, check=True)


def test_run_check_true_is_silent_on_success(monkeypatch):
    assert _run_against_fake(monkeypatch, exit_code=0, check=True).ok


def test_job_exit_error_is_a_job_error():
    from pyte import errors
    from pyte.job import CompletedJob, JobStatus, StatusKind
    res = CompletedJob(JobStatus(StatusKind.EXITED, 1), "", "",
                       program="p", argv=["p"])
    exc = errors.JobExitError(res)
    assert isinstance(exc, errors.JobError)
    assert isinstance(exc, errors.TeError)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_job.py -k "check_returncode or check_true or exit_error" -v`
Expected: FAIL, no `check_returncode`, no `JobExitError`.

- [ ] **Step 3: Add JobExitError**

In `src/pyte/errors.py`, after `JobTimeoutError`:

```python
class JobExitError(JobError):
    """A checked job exited non-zero (see CompletedJob.check_returncode).

    Message-only: there is no te_errno behind a non-zero exit status.
    ``result`` carries the whole CompletedJob -- status, stdout,
    stderr and the command -- so a caller catching this still has
    everything the run produced.
    """

    def __init__(self, result):
        argv = " ".join(result.argv) or result.program
        detail = (result.stderr.strip() or result.stdout.strip())[:200]
        msg = f"{argv} -> rc={result.returncode}"
        Exception.__init__(self, f"{msg}: {detail}" if detail else msg)
        self.result = result
        self.rc = 0
        self.module = 0
        self.code = 0
```

The 200-character tail and the `argv -> rc=N: detail` shape match nvme-ts's `CmdError`, which the suites already read.

- [ ] **Step 4: Add check_returncode and the check= flags**

In `src/pyte/job.py`, on `CompletedJob`:

```python
    def check_returncode(self) -> None:
        """Raise :exc:`pyte.errors.JobExitError` if the job failed.

        The subprocess.CompletedProcess method of the same name.
        Opt-in: run() still treats a non-zero exit as a result.
        """
        if not self.ok:
            from pyte.errors import JobExitError
            raise JobExitError(self)
```

On module-level `run()` add a keyword-only parameter:

```python
def run(server, program, args=None, env=None,
        timeout: float | None = DEFAULT_TIMEOUT, *,
        check: bool = False) -> CompletedJob:
```

and before returning:

```python
        result = CompletedJob(...)
        if check:
            result.check_returncode()
        return result
```

Document it: `check=True` raises `JobExitError` on a non-zero exit instead of returning it; the default stays `False` because "a non-zero exit is a result, not an exception" is this API's contract.

Add the same keyword-only `check: bool = False` to `RpcServer.run()` and forward it. Leave `Job.run()` alone — it returns a bare `JobStatus`, not a `CompletedJob`.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass; no existing behavior changed.

- [ ] **Step 6: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "job: add opt-in checked execution" -m "There was no way to say 'and fail the test if this command fails'
short of hand-writing the check at every call site.  nvme-ts wrote
its own runner with exactly this flag rather than use pyte's.

Add CompletedJob.check_returncode() (the subprocess method of the
same name) and a keyword-only check=False to run().  The default is
unchanged and deliberately so: 'a non-zero exit is a result, not an
exception' is this API's documented contract.

JobExitError carries the whole CompletedJob, and formats as
'argv -> rc=N: <stderr or stdout tail>' -- the same shape nvme-ts's
CmdError already uses, so the message reads the same either way."
```

---

### Task 3: Make sh() return stderr

**Files:**
- Modify: `src/pyte/rpc/server.py:200-226` (`sh`)
- Modify: `docs/guides/rpc.md` (document sh/system/run together)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `JobExitError` shape from Task 2 (for message consistency).
- Produces: `RpcServer.sh(cmd, *, check=True) -> ShResult` where `ShResult` has `.rc`, `.out`, `.err`, `.ok` and `__str__` returning `out`.

**Background:** this is the real gap the first draft missed. `sh()` returns stdout only; stderr is unreachable except as `.output` on a raised `RpcError`. 28 call sites use it. nvme-ts declined it and built `CmdResult(rc, out, err)`.

**BREAKING and needs care.** All 28 call sites do `text = pco.sh(...)`. Two options:

1. Return a `ShResult` whose `__str__`/`__eq__` behave like the old `str`. Keeps most call sites working; `.strip()` and slicing do not.
2. Keep `sh()` returning `str` and add `sh_result()` returning the full object.

**Choose option 2** unless the audit in Step 1 shows the call sites are all `str()`-compatible. A silently-different return type across 28 sites is exactly the class of breakage the pinned-submodule policy is meant to make deliberate, not accidental.

- [ ] **Step 1: Audit the call sites, then decide**

Run:
```bash
grep -rn '\.sh(' /home/kostik/prj/te/{python-ts,nap-ts,nvme-ts,app-perf-ts-py} --include='*.py' | grep -v '/lib/pyte/'
```
Classify each: assigned to a variable, `.strip()`ed, compared, iterated, or discarded. Write the counts into the commit body. If every site would survive a `str`-like object, option 1 is available; otherwise take option 2. **Do not guess — this step decides the task's design.**

- [ ] **Step 2: Write the failing test**

Append to `tests/test_server.py`, using its `_fake_sh_shim` helper (extend `_ShLib` so it can also produce stderr — check whether `pyte_rpc_shell_get_all` can return it; if the shim call cannot, say so and scope this task to `rc` + `out` only, with a note in the commit body):

```python
def test_sh_result_carries_rc_out_and_err(monkeypatch):
    _fake_sh_shim(monkeypatch, b"the output\n", flag=0, value=0)
    srv = _bare_server()
    res = srv.sh_result("echo hi")
    assert res.rc == 0
    assert res.out == "the output\n"
    assert res.ok


def test_sh_result_does_not_raise_on_failure(monkeypatch):
    _fake_sh_shim(monkeypatch, b"boom\n", flag=0, value=3)
    srv = _bare_server()
    res = srv.sh_result("false")
    assert res.rc == 3
    assert not res.ok


def test_sh_still_raises_and_still_returns_stdout(monkeypatch):
    """The 28 existing call sites must be untouched."""
    from pyte.errors import RpcError
    _fake_sh_shim(monkeypatch, b"boom\n", flag=0, value=1)
    srv = _bare_server()
    with pytest.raises(RpcError):
        srv.sh("false")
```

- [ ] **Step 3: Implement**

Add the result type in `src/pyte/rpc/server.py`:

```python
@dataclass(frozen=True)
class ShResult:
    """Result of :meth:`RpcServer.sh_result`: status and both streams.

    The shape nvme-ts built for itself rather than use sh(), which
    returns stdout only and reaches stderr solely as an attribute on
    a raised error.
    """
    rc: int
    out: str
    err: str
    cmd: str

    @property
    def ok(self) -> bool:
        return self.rc == 0
```

and `sh_result()` beside `sh()`, sharing one private helper so the two cannot drift. `sh()` keeps its exact current contract (returns stdout, raises on non-zero with `.output` attached) and gains a docstring line pointing at `sh_result()`.

- [ ] **Step 4: Document the three APIs together**

`docs/guides/rpc.md` covers only sockets and iomux; no guide documents `sh`/`system`/`run` side by side, which is the real reason the choice is confusing. Add a short section with a table: what each returns, what it does on a non-zero exit, and when to reach for which. State plainly that `sh()` is the common one (28 call sites), `system()` returns the status, and `run()` is for capturing both streams with a job.

- [ ] **Step 5: Run tests, lint, commit**

```bash
.venv/bin/python -m pytest tests/ -q
ruff check src tests setup.py
git add -A
git commit -s -m "rpc/server: add sh_result() carrying rc, out and err" -m "sh() returns stdout only; stderr is reachable solely as an
attribute on a raised RpcError.  That, more than the raise-vs-return
policy, is why nvme-ts declined pyte's runners and wrote
CmdResult(rc, out, err) with ~40 call sites of its own.

sh_result() returns all three and does not raise, alongside an
unchanged sh() -- 28 call sites across the four suites use sh() and
none of them should have to change.

Also document sh/system/run side by side: no guide covered them
together, which is why the choice between them reads as arbitrary."
```

---

### Task 4: Cache the TRex report and stop losing samples

**Files:**
- Modify: `src/pyte/tools/trex/batch.py` (`__init__`, `report`, `wait_report`, `close`)
- Test: `tests/test_trex_batch_lifecycle.py`

**Interfaces:**
- Consumes: `Deadline` from wave 2.
- Produces: `Trex.report()` cached and valid after `close()`; `Trex.wait_report(timeout)`.

**Background:** `report()` drains every filter (`batch.py:579-600`), so a second call sees only what arrived since the first, and drained counters come back as `0` rather than as an error (`_single_uint`/`_avg` return `0`/`0.0` for an empty list). After `close()` the job is destroyed and the filters raise `ClosedResourceError`, so the report must be extracted inside the `with` block and stored by the caller — nothing enforces that but prose.

`ToolHandle.wait()` already caches (`_tool.py:281-282,300`); copy that pattern rather than inventing one.

**The bigger hazard the first draft missed:** `report()` drains with the default `timeout=0`, so anything the agent has not yet delivered is silently absent and the averages are quietly wrong. nap-ts works around this with its own `_drain_stdout()` before `report()` (`nap-ts/lib/nap/trexlib/run.py:388-393`). A `wait_report()` that merely reorders `wait` and `report` does **not** close this.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trex_batch_lifecycle.py`:

```python
def test_report_is_cached_and_readable_twice():
    pco = _FakePco()
    with batch.create(pco, _batch_opts()) as trex:
        trex._summary["total_tx"].feed("12.34 M")
        first = trex.report()
        second = trex.report()
    assert second is first
    assert second.avg_tx == pytest.approx(12.34e6)


def test_report_survives_close():
    """The report had to be extracted inside the with block and stored
    by the caller; after close() the filters raise."""
    pco = _FakePco()
    with batch.create(pco, _batch_opts()) as trex:
        trex._summary["total_tx"].feed("12.34 M")
        rep = trex.report()
    assert trex.report() is rep          # after close()


def test_report_before_start_raises_instead_of_returning_zeros():
    """It used to return an all-zero Report with port_series=None and
    no error at all."""
    pco = _FakePco()
    with batch.create(pco, _batch_opts()) as trex:
        with pytest.raises(batch.TrexBatchError, match="not started"):
            trex.report()


def test_wait_report_waits_then_reports():
    pco = _FakePco()
    with batch.create(pco, _batch_opts()) as trex:
        trex.start()
        trex._summary["total_tx"].feed("12.34 M")
        rep = trex.wait_report(timeout=5.0)
    assert rep.avg_tx == pytest.approx(12.34e6)
    assert pco._job.wait_calls           # it really waited


def test_report_accumulates_across_drains():
    """A caller who drains stdout between wait() and report() -- as
    nap-ts does -- must not lose the samples that drain consumed."""
    pco = _FakePco()
    with batch.create(pco, _batch_opts()) as trex:
        trex.start()
        trex._summary["total_tx"].feed("10.0 M")
        trex._accumulate()               # simulates an interim drain
        trex._summary["total_tx"].feed("20.0 M")
        rep = trex.report()
    assert rep.avg_tx == pytest.approx(15.0e6)   # both samples
```

`_FakeJob` needs a `wait_calls` list; add it beside the existing `_wait_result`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_trex_batch_lifecycle.py -k "cached or survives or before_start or wait_report or accumulates" -v`
Expected: FAIL. The second `report()` returns a fresh all-zero report; `report()` after close raises; there is no `wait_report`; the pre-start call returns zeros silently.

- [ ] **Step 3: Implement accumulation and caching**

In `src/pyte/tools/trex/batch.py`, add to `__init__`:

```python
        self._report: "_rpt.Report | None" = None
        self._drained = _rpt.BatchFilters()
        self._started = False
```

Split the draining out of `report()` into `_accumulate()`, which drains into `self._drained` and can be called any number of times, then:

```python
    def report(self) -> _rpt.Report:
        """The parsed :class:`Report`, built once and cached.

        Draining is destructive -- each filter's data is consumed --
        so the report is accumulated into a running BatchFilters and
        built once.  It used to be rebuilt on every call from whatever
        happened to have arrived since the last one, which meant a
        second call quietly returned zeros (an empty filter parses as
        0, not as an error), and no call at all was possible after
        close() destroyed the job.

        Valid after close(): the samples are already in Python.
        """
        if self._report is not None:
            return self._report
        if not self._started:
            raise TrexBatchError(
                "TRex batch was never started; there is nothing to "
                "report (call start() first)")
        self._accumulate()
        self._report = _rpt.build_report(self._drained)
        return self._report
```

Set `self._started = True` in `start()`. Have `close()` call `self._accumulate()` before destroying the job, wrapped so a failure there cannot mask a teardown error — reuse wave 1's `cleanup_all`.

- [ ] **Step 4: Add wait_report**

```python
    def wait_report(self, timeout: float | None = None) -> _rpt.Report:
        """Wait for completion, then return the parsed report.

        The pairing callers actually want.  Note that draining is a
        snapshot of what the agent has delivered so far: this waits
        for the process to finish first, so nothing is still in
        flight when the filters are read.
        """
        self.wait(timeout=timeout)
        return self.report()
```

- [ ] **Step 5: Address the timeout=0 drain hazard**

`_accumulate()` inherits `Filter.drain()`'s default `timeout=0`, so a message the agent has not delivered yet is silently missing. Decide and implement one of:

- give `_accumulate()` a short drain timeout after the job has completed (the process is gone, so anything still coming is already queued), or
- document precisely that `report()` reflects what has been delivered and that `wait_report()` is the correct entry point because it waits first.

Whichever you choose, say so in `report()`'s docstring, and check whether nap-ts's `_drain_stdout()` workaround (`run.py:311-323`) is still needed. Do not silently leave the hazard.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. `test_report_drains_summary_filters` and `test_report_resilences_filters_via_job_quiet_not_rpcserver` both encode the old draining behavior — update them to the new contract rather than working around it. The latter asserts `quiet_calls == ["enter", "exit"]` exactly once, so a cached second `report()` must add no pair.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "tools/trex: cache the batch report, keep it after close" -m "report() drained every filter and rebuilt the Report from whatever
had arrived since the last call, so it worked exactly once: a second
call returned zeros rather than an error (an empty filter parses as
0), and after close() destroyed the job it raised.  The report had
to be read inside the with block and stashed by the caller, enforced
only by prose in nap-ts's module docstring.

Accumulate drains into a running BatchFilters, build the Report
once, and cache it -- the pattern ToolHandle.wait() already uses.
close() accumulates before destroying the job, so the report stays
valid afterwards.

Add wait_report(), and make a report before start() raise instead of
returning an all-zero Report with no indication anything was wrong."
```

---

### Task 5: Publish the report and stats types

**Files:**
- Modify: `src/pyte/tools/trex/batch.py` (re-exports, `__all__`)
- Modify: `src/pyte/tools/trex/astf.py` (re-exports, `__all__`)
- Modify: `src/pyte/tools/trex/__init__.py` (`__all__`)
- Test: `tests/test_trex_batch_lifecycle.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `batch.Report`, `batch.PortParam`, `batch.NoPortStats`, `batch.WindowClamped`, `batch.BatchFilters`; `astf.AstfGlobal`, `astf.AstfTraffic`, `astf.AstfLatency`, `astf.Series`, `astf.Snapshot`, `astf.TemplateStats`.

**Background:** nap-ts *production* code imports the private module: `from pyte.tools.trex import _batch_report as batch` (`stats.py:35`), then annotates against `batch.Report`, `batch.PortParam`, and uses `batch.WindowClamped` at runtime in `warnings.simplefilter`. `nap-ts/lib/nap/trexlib/run.py:345` writes `batch.Report` and only gets away with it because `from __future__ import annotations` leaves the annotation an unevaluated string. The ASTF stats types are exported from nowhere at all and `measure.py` annotates against them too.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trex_batch_lifecycle.py`:

```python
def test_public_report_types_are_reachable_without_a_private_import():
    """nap-ts production code imports _batch_report directly today."""
    assert batch.Report is not None
    assert batch.PortParam is not None
    assert batch.NoPortStats is not None
    assert batch.WindowClamped is not None


def test_report_types_are_the_same_objects_as_the_private_ones():
    from pyte.tools.trex import _batch_report as _rpt
    assert batch.Report is _rpt.Report
    assert batch.WindowClamped is _rpt.WindowClamped


def test_astf_stats_types_are_public():
    from pyte.tools.trex import astf
    for name in ("AstfGlobal", "AstfTraffic", "AstfLatency", "Series",
                 "Snapshot", "TemplateStats"):
        assert hasattr(astf, name), name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_trex_batch_lifecycle.py -k "public or same_objects or astf_stats" -v`
Expected: FAIL, `AttributeError: module 'pyte.tools.trex.batch' has no attribute 'Report'`.

- [ ] **Step 3: Re-export**

In `batch.py`, alongside the existing private import, add public names and an `__all__` listing the lifecycle API plus the report types. In `astf.py`, re-export the six stats types from `_astf_stats` and add an `__all__`. Extend `pyte/tools/trex/__init__.py`'s `__all__` with `Report` and `PortParam` if they belong at package level — decide deliberately and keep `Series` out of the top level, since `Report.window()` and `Series.window()` mean different things and colliding them in one namespace would be worse than the private import.

Keep every existing import path working: these are additions.

- [ ] **Step 4: Migrate nap-ts off the private import**

In `/home/kostik/prj/te/nap-ts`, change `lib/nap/trexlib/stats.py:35` to `from pyte.tools.trex import batch`, drop the gratuitous private import at `interactive.py:18` (`ServerOpts` is already public), and point `measure.py:5` at `pyte.tools.trex.astf`. Run nap-ts's own checks. This is a separate commit in a separate repo; note the pyte commit it depends on.

- [ ] **Step 5: Run tests, lint, commit**

```bash
.venv/bin/python -m pytest tests/ -q
ruff check src tests setup.py
git add -A
git commit -s -m "tools/trex: publish the report and stats types" -m "nap-ts production code imports pyte.tools.trex._batch_report
directly and annotates against batch.Report -- which only works
because 'from __future__ import annotations' leaves the annotation
an unevaluated string -- and uses WindowClamped at runtime in a
warnings filter.  The ASTF stats types are exported from nowhere at
all, and measure.py annotates against those too.

Re-export Report, PortParam, NoPortStats, WindowClamped and
BatchFilters from batch, and the six ASTF stats types from astf,
with explicit __all__ lists.  Series stays out of the package-level
namespace: Report.window() and Series.window() return different
things and colliding them would be worse than the private import.

Additive; every existing import path still works."
```

---

## Wave 3 exit criteria

- [ ] `.venv/bin/python -m pytest tests/ -q` green.
- [ ] `grep -rn '_batch_report\|_astf_stats' /home/kostik/prj/te/nap-ts/lib` returns nothing outside the vendored `lib/pyte/`.
- [ ] `Trex.report()` returns the same object twice and works after `close()`.
- [ ] A report before `start()` raises rather than returning zeros.
- [ ] `sh()`'s 28 call sites are untouched; the audit from Task 3 Step 1 is recorded in the commit body.
- [ ] `run()`'s default remains "a non-zero exit is a result".
- [ ] `docs/guides/rpc.md` documents `sh`/`system`/`run` side by side.
