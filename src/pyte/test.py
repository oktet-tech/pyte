# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Test lifecycle: the Python counterpart of TEST_START/TEST_END."""
from __future__ import annotations

import json
import logging
import os
import pathlib
import random
import re
import shutil
import signal
import sys
from contextlib import contextmanager
from typing import Callable

from pyte import log
from pyte._util import shim_lib as _shim_lib
from pyte._params import Compound, Params, parse_argv  # noqa: F401
from pyte.errors import TestFail, TestSkip
from pyte._util import enc as _enc
from pyte._util import format_exc_chain as _format_exc_chain
from pyte._util import format_remote_tracebacks as _remote_detail

EXIT_SIGINT = 0x2
EXIT_SIGUSR2 = 0x4
EXIT_SKIP = 0x5

_current: "Test | None" = None

# The server-side unpack script rejects a whole run for a name outside
# this set, so refuse it here, where the test can still react.
_ATTACH_NAME = re.compile(r"[-_.:0-9a-zA-Z]{1,128}")
# The index the log viewer reads, next to the attached files.
_ATTACH_INDEX = "attachments.json"


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


class Test:
    def __init__(self, params: Params):
        self.params = params
        self._cleanups: list[tuple[Callable, tuple, dict]] = []
        self._finalizers: list[tuple[Callable, tuple, dict]] = []
        # MI writes held for the Measurements step; None once past it.
        self._pending_mi: list[Callable[[], None]] | None = []
        self._failed = False
        self._env = None
        self._attach_warned = False

    # -- structure ---------------------------------------------------
    def step(self, text: str) -> None:
        lib = _shim_lib()
        lib.pyte_step(_enc(text))

    def substep(self, text: str) -> None:
        lib = _shim_lib()
        lib.pyte_substep(_enc(text))

    def verdict(self, text: str, error: bool = False) -> None:
        lib = _shim_lib()
        lvl = lib.TE_LL_ERROR if error else lib.TE_LL_RING
        lib.pyte_verdict(lvl, _enc(text))

    def artifact(self, text: str) -> None:
        lib = _shim_lib()
        lib.pyte_artifact(lib.TE_LL_RING, _enc(text))

    def attach(self, name: str, source, description: str = ""
               ) -> pathlib.Path | None:
        """Attach a file to this test's result.

        *source* is the content when ``bytes``, otherwise a local file
        (``str`` or path-like) to copy.  The file lands in
        ``$TE_LOG_DIR/attachments/node_id<id>/<name>`` (``$TE_RUN_DIR``
        when no log dir is set), with an entry in the ``attachments.json``
        next to it, which is what the log viewer reads.  Attaching the
        same *name* again replaces the file and its entry.

        *name* must match ``[-_.:0-9a-zA-Z]{1,128}`` and not be ``.``,
        ``..`` or ``attachments.json`` (the index itself), else
        ValueError.  Returns the destination path, or None (with one
        warning per test) when there is nowhere to put it: no log
        directory, or no test id.
        """
        if (not _ATTACH_NAME.fullmatch(name)
                or name in (".", "..", _ATTACH_INDEX)):
            raise ValueError(f"Invalid attachment name {name!r}")
        test_id = int(self.params.get("te_test_id", "0") or "0")
        root = (os.environ.get("TE_LOG_DIR")
                or os.environ.get("TE_RUN_DIR"))
        if test_id == 0 or not root:
            if not self._attach_warned:
                self._attach_warned = True
                log.warn("Attachments are not available here (no test "
                         f"id or log directory), skipping {name}")
            return None

        node_dir = pathlib.Path(root) / "attachments" / f"node_id{test_id}"
        node_dir.mkdir(parents=True, exist_ok=True)
        dest = node_dir / name
        if isinstance(source, (bytes, bytearray)):
            dest.write_bytes(source)
        else:
            shutil.copyfile(source, dest)

        index = node_dir / _ATTACH_INDEX
        data = (json.loads(index.read_text()) if index.exists()
                else {"version": 1, "attachments": []})
        path = f"./{name}"
        entry = {
            "type": "text",
            "view_type": "inline",
            "name": os.path.splitext(name)[0],
            "description": description,
            "download_enabled": True,
            "path": path,
        }
        data["attachments"] = [a for a in data["attachments"]
                               if a.get("path") != path] + [entry]
        index.write_text(json.dumps(data, indent=2))

        log.ring(f"Attachment: {name} ({_human_size(dest.stat().st_size)})")
        return dest

    # -- outcome -----------------------------------------------------
    def fail(self, text: str, *, verdict: str | bool = False) -> None:
        """Fail the test with ``text``.

        A failure on its own is invisible to TRC, which matches
        verdicts only. ``verdict`` makes it visible:

        * ``verdict=True`` records ``text`` itself as an error verdict
          and fails. The harness then does not repeat the text as
          "Test failed:", so a constant message is logged once.
        * ``verdict="..."`` records that constant as the error verdict
          and fails with ``text``, which may carry the volatile detail
          (counts, names, values) a verdict must not.
        * ``verdict=False`` (the default) fails with no verdict at all.
        """
        if verdict is True:
            self.verdict(text, error=True)
            exc = TestFail(text)
            exc.verdict_recorded = True
            raise exc
        if verdict:
            self.verdict(verdict, error=True)
        raise TestFail(text)

    def skip(self, text: str = "") -> None:
        raise TestSkip(text)

    def expect(self, actual, expected, label: str | None = None) -> None:
        """Fail unless ``actual == expected``.

        The failure text is ``"{label}: expected {expected!r}, got
        {actual!r}"`` (``"value"`` when *label* is omitted). This format
        is stable; no verdict is recorded, see :meth:`fail`.
        """
        if actual != expected:
            self.fail(f"{label or 'value'}: expected {expected!r}, "
                      f"got {actual!r}")

    def check(self, cond: bool, msg: str) -> None:
        """Fail with *msg* unless *cond* holds."""
        if not cond:
            self.fail(msg)

    def need(self, value, text: str, *, verdict: str | bool = False):
        """Return ``value``, or fail with ``text`` when it is None.

        For a lookup that answers None on a miss, where the test
        cannot go on without the value::

            ifname = t.need(env.find_iface("iut_pf0"),
                            "the env binds no iut_pf0")

        Only None is a miss: 0, an empty string and an empty list are
        values and come back as they are. ``verdict`` is handed to
        :meth:`fail` unchanged.
        """
        if value is None:
            self.fail(text, verdict=verdict)
        return value

    def cleanup(self, fn: Callable, *args, **kwargs) -> None:
        """Register fn to run at test end (LIFO), pass or fail."""
        self._cleanups.append((fn, args, kwargs))

    def finalize(self, fn: Callable, *args, **kwargs) -> None:
        """Register fn to run when the body ends, before the MI step.

        Finalizers run last registered first, like cleanups, however
        the body ended (pass, fail, skip), after :attr:`failed` is set
        and before the "Measurements" step and the cleanups.  This is
        where a sampler stops and closes its mi.Logger, so its rows
        join the other measurements; registered after a session, it
        stops before the session's own finalizer runs.  They run under
        a "Collect results" step, opened only when at least one is
        registered, so what they log is not mistaken for the last body
        step's work.  Every logger must be closed by the time they
        return: a close() from another thread racing the Measurements
        step can miss it, so a sampling thread is stopped and joined in
        its finalizer.  A raising finalizer is logged and the rest
        still run.  An ordinary error leaves the exit code as the body
        left it; an interrupt, an exit or a TestFail (which the signal
        handler raises too) turns a pass into a failure, as it does in
        a cleanup.
        """
        self._finalizers.append((fn, args, kwargs))

    @property
    def failed(self) -> bool:
        """Whether the test failed, for finalizers and cleanups.

        False while the body runs.  Set when the body ends, before the
        finalizers: True unless the body passed (completed, or exited
        with code 0) or was skipped.
        """
        return self._failed

    # -- environment -------------------------------------------------
    @property
    def agent(self) -> str:
        """Name of the suite's single test agent."""
        return os.environ.get("TE_IUT_TA_NAME", "Agt_A")

    @property
    def agents(self) -> list[str]:
        """Names of all test agents in the configuration tree."""
        from pyte import cfg
        return [n.name for n in cfg.find("/agent:*")]

    # -- per-test defaults ---------------------------------------------
    def default_param(self, name: str, test_name: str) -> str:
        """A test parameter's default from the Configurator, as a string.

        Reads ``/local:/test:/testname:<node>/default:<name>``, where
        ``<node>`` is *test_name* with every "/" replaced by "_" (the
        node naming the Configurator uses).  Such nodes are registered
        by a suite's ``cs.conf``, typically with a value expanded from
        the environment at Configurator load time.

        Only that node is ever consulted: a test parameter of the same
        name is NOT a fallback, so whatever cs.conf resolved stays the
        single source of the value.  A missing node surfaces as
        :class:`~pyte.errors.CfgNotFoundError`, any other Configurator
        failure as :class:`~pyte.errors.CfgError`; both propagate.
        """
        from pyte import cfg
        node = test_name.replace("/", "_")
        value = cfg.get(f"/local:/test:/testname:{node}/default:{name}")
        return str(value)

    def default_uint(self, name: str, test_name: str) -> int:
        """:meth:`default_param` parsed as a non-negative integer.

        Base 0, so "0x10" and "0o20" are accepted alongside "16".

        :raises ValueError: the default does not parse, or is negative.
        """
        value = self.default_param(name, test_name)
        try:
            result = int(value, 0)
        except ValueError:
            raise ValueError(f"default value of parameter {name!r} is not "
                             f"an unsigned integer: {value!r}") from None
        if result < 0:
            raise ValueError(f"default value of parameter {name!r} is not "
                             f"an unsigned integer: {value!r}")
        return result

    def rpc_server(self, name: str):
        from pyte.rpc import RpcServer
        srv = RpcServer.create(self.agent, name)
        self.cleanup(srv.destroy)
        return srv

    def _run_cleanups(self) -> bool:
        ok = True
        if self._cleanups:
            self.step("Cleanup")
        for fn, args, kwargs in reversed(self._cleanups):
            try:
                fn(*args, **kwargs)
            except BaseException:  # noqa: BLE001
                # BaseException, not Exception: this runs inside
                # start()'s finally, so an interrupt (or a SystemExit
                # from a cleanup) escaping here would skip env.close()
                # and leave _current pointing at a dead test.
                log.error("cleanup failed:\n" + _format_exc_chain())
                ok = False
        return ok

    def _defer_mi(self, write: Callable[[], None]) -> bool:
        """Hold an mi.Logger write for the Measurements step.

        False once the test is past that step; the caller writes then.
        """
        pending = self._pending_mi
        if pending is None:
            return False
        pending.append(write)
        return True

    def _run_finalizers(self) -> bool:
        ok = True
        if self._finalizers:
            # Guarded on its own: without the step they still run.
            ok = _guarded("Opening the Collect results step", self.step,
                          "Collect results")
        for fn, args, kwargs in reversed(self._finalizers):
            ok = _guarded("Finalizer", fn, *args, **kwargs) and ok
        return ok

    def _write_measurements(self) -> bool:
        pending, self._pending_mi = self._pending_mi or [], None
        ok = True
        if pending:
            # Guarded on its own: without the step the rows still count.
            ok = _guarded("Opening the Measurements step", self.step,
                          "Measurements")
        for write in pending:
            ok = _guarded("MI write", write) and ok
        return ok

    def _finish(self, failed: bool) -> bool:
        """Run everything after the body; False if that fails the test.

        In order: set :attr:`failed`, run the finalizers (last
        registered first) under "Collect results", write the pending
        MI loggers under "Measurements", run the cleanups.
        Neither a finalizer nor an MI write can stop the rest.  False
        when a cleanup failed, or a finalizer or an MI write raised
        what fails the test (see :func:`_fails_the_test`).
        """
        self._failed = failed
        ok = True
        for what, phase in (("Running the finalizers", self._run_finalizers),
                            ("Writing the measurements",
                             self._write_measurements)):
            try:
                ok = phase() and ok
            except BaseException as exc:  # noqa: BLE001  never skip the rest
                # Only what escapes the per-item guards lands here,
                # e.g. a signal arriving between two items.
                log.error(f"{what} failed:\n" + _format_exc_chain())
                ok = ok and not _fails_the_test(exc)
        # Past the Measurements step on every path: a close from here
        # on writes at once, not into a list nobody will read.
        self._pending_mi = None
        return self._run_cleanups() and ok

    @property
    def env(self):
        """The bound tapi_env environment (lazy; needs an env param).

        Bound from the test's ``env`` parameter on first access and
        freed automatically at test end.
        """
        if self._env is None:
            from pyte.env import Env
            from pyte.errors import EnvError
            cfg = self.params.get("env")
            if cfg is None:
                raise EnvError("test has no 'env' parameter to bind")
            self._env = Env.bind(cfg)
        return self._env


def _fails_the_test(exc: BaseException) -> bool:
    """Whether *exc*, caught in a finalizer or an MI write, fails the test.

    An ordinary error is only logged.  An interrupt (KeyboardInterrupt,
    SystemExit) fails the test, as it does in a cleanup, and so does
    TestFail: t.fail() asks for exactly that, and the signal handler
    raises it.
    """
    return not isinstance(exc, Exception) or isinstance(exc, TestFail)


def _guarded(what: str, fn: Callable, /, *args, **kwargs) -> bool:
    """Run *fn*, logging what it raises as "<what> failed".

    Catches BaseException, as _run_cleanups() does, so nothing raised
    here skips the rest of the test end.  False when what was caught
    fails the test.
    """
    try:
        fn(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001  see the docstring
        log.error(f"{what} failed:\n" + _format_exc_chain())
        return not _fails_the_test(exc)
    return True


def _cleanup_detail(exc: BaseException) -> str:
    """Render cleanup failures attached to *exc* by pyte._cleanup.

    str(exc) does not include exception notes, so a teardown failure
    attached during unwind would otherwise reach no log at all on the
    TestFail path -- which is the common one (t.fail/check/expect).
    """
    errors = getattr(exc, "cleanup_errors", ())
    if not errors:
        return ""
    return "".join(f"\n  cleanup also failed: {e!r}" for e in errors)


def current() -> Test:
    if _current is None:
        raise RuntimeError("test.start() not active")
    return _current


def _sig_handler(signum, frame):
    if signum == signal.SIGINT:
        os._exit(EXIT_SIGINT)
    # TE's C handler exits on SIGUSR2 only when TE_TEST_SIGUSR2_STOP
    # is set; otherwise the signal fails the test like SIGUSR1.
    if (signum == signal.SIGUSR2
            and os.environ.get("TE_TEST_SIGUSR2_STOP") is not None):
        os._exit(EXIT_SIGUSR2)
    raise TestFail(f"Test got signal {signal.Signals(signum).name}")


@contextmanager
def start(name: str | None = None):
    """TEST_START/TEST_END equivalent.

    with test.start() as t:
        t.step(...)

    However the body ends, the same order follows: :attr:`Test.failed`
    is set, the finalizers run under a "Collect results" step, the
    mi.Logger objects closed in the test are written under a
    "Measurements" step, the cleanups run under "Cleanup", and the
    process exits with the test's result.  A step that would be empty
    is not opened.
    """
    global _current
    if _current is not None:
        raise RuntimeError("test.start() already active")
    lib = _shim_lib()

    entity = name or os.path.basename(sys.argv[0])
    params = Params(parse_argv(sys.argv[1:]))

    lib.pyte_log_init(_enc(entity))
    try:
        test_id = int(params.get("te_test_id", "0"))
    except ValueError:
        test_id = 0
    if test_id == 0:
        print("te_test_id parameter not found", file=sys.stderr)
        sys.exit(1)
    lib.te_test_id = test_id

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGUSR1, _sig_handler)
    signal.signal(signal.SIGUSR2, _sig_handler)

    t = Test(params)
    _current = t

    result = 1
    try:
        # The setup tail runs inside the try so a failure here (e.g. a
        # malformed te_rand_seed, or a TE error from the step message)
        # is logged and exits through the normal cleanup/sys.exit path
        # below instead of escaping the generator as a raw exception
        # that skips cleanups and leaves _current set.
        t.step("Test start")

        if "te_rand_seed" in params:
            seed = params.int("te_rand_seed")
            random.seed(seed)
            log.ring(f"Pseudo-random seed is {seed}")

        # Route everything into the TE Logger: it does its own level
        # filtering, while the stdlib root logger defaults to WARNING.
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        if not any(isinstance(h, log.TeLogHandler) for h in root.handlers):
            root.addHandler(log.TeLogHandler())

        yield t
        result = 0
    except TestSkip as e:
        if str(e):
            t.verdict(str(e))
        # A verdict is a formal result string, not a diagnostics log --
        # a cleanup failure attached to the skip goes to a separate
        # log.error instead of into the verdict text.
        detail = _cleanup_detail(e)
        if detail:
            log.error(f"Test skipped, but cleanup also failed:{detail}")
        result = EXIT_SKIP
    except TestFail as e:
        # _remote_detail: a test that catches a remote failure and
        # calls t.fail() with a one-line message is the common shape,
        # and this handler is then the only report of it -- without
        # the appended frames the agent-side traceback reaches no log
        # at all.  Empty whenever nothing in the chain came from
        # pyte.remote, which is the usual case.
        detail = f"{_cleanup_detail(e)}{_remote_detail(e)}"
        if getattr(e, "verdict_recorded", False):
            # The error verdict already carries the text; only what
            # the verdict cannot hold is logged.
            if detail:
                log.error(f"Test failed, see the verdict;{detail}")
        else:
            log.error(f"Test failed: {e}{detail}")
        result = 1
    except SystemExit as e:
        # sys.exit() can itself unwind through a `with` block whose
        # __exit__ attaches a teardown failure to it (cleanup_all),
        # same as TestFail/TestSkip -- so check here too.
        detail = _cleanup_detail(e)
        if e.code is None:
            result = 0
        elif isinstance(e.code, int):
            result = e.code
        else:
            log.error(f"SystemExit with non-integer code: {e.code!r}")
            result = 1
        if detail:
            log.error(f"SystemExit(code={e.code!r}), but cleanup also "
                      f"failed:{detail}")
    except Exception:
        log.error("Unhandled exception:\n" + _format_exc_chain())
        result = 1
    finally:
        # Pass and skip are the only results that are not failures; an
        # exception start() does not catch leaves result at 1.
        failed = result not in (0, EXIT_SKIP)
        if not t._finish(failed) and result == 0:
            result = 1
        if t._env is not None:
            try:
                t._env.close()
            except BaseException:  # noqa: BLE001  interrupt-safe teardown
                log.error("env close failed:\n" + _format_exc_chain())
                if result == 0:
                    result = 1
            t._env = None
        _current = None
    sys.exit(result)
