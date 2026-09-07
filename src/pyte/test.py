# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Test lifecycle: the Python counterpart of TEST_START/TEST_END."""
from __future__ import annotations

import logging
import os
import random
import signal
import sys
import traceback
from contextlib import contextmanager
from typing import Callable

from pyte import log
from pyte._util import shim_lib as _shim_lib
from pyte._params import Params, parse_argv
from pyte.errors import TestFail, TestSkip
from pyte._util import enc as _enc

EXIT_SIGINT = 0x2
EXIT_SIGUSR2 = 0x4
EXIT_SKIP = 0x5

_current: "Test | None" = None


class Test:
    def __init__(self, params: Params):
        self.params = params
        self._cleanups: list[tuple[Callable, tuple, dict]] = []
        self._env = None

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

    # -- outcome -----------------------------------------------------
    def fail(self, text: str) -> None:
        raise TestFail(text)

    def skip(self, text: str = "") -> None:
        raise TestSkip(text)

    def expect(self, actual, expected, label: str | None = None) -> None:
        """Fail unless ``actual == expected``.

        The failure verdict is ``"{label}: expected {expected!r}, got
        {actual!r}"`` (``"value"`` when *label* is omitted). This format
        is stable: TRC expectations may match against it.
        """
        if actual != expected:
            self.fail(f"{label or 'value'}: expected {expected!r}, "
                      f"got {actual!r}")

    def check(self, cond: bool, msg: str) -> None:
        """Fail with *msg* unless *cond* holds."""
        if not cond:
            self.fail(msg)

    def cleanup(self, fn: Callable, *args, **kwargs) -> None:
        """Register fn to run at test end (LIFO), pass or fail."""
        self._cleanups.append((fn, args, kwargs))

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
            except Exception:
                log.error("cleanup failed:\n" + traceback.format_exc())
                ok = False
        return ok

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
        log.error(f"Test failed: {e}{_cleanup_detail(e)}")
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
        log.error("Unhandled exception:\n" + traceback.format_exc())
        result = 1
    finally:
        if not t._run_cleanups() and result == 0:
            result = 1
        if t._env is not None:
            try:
                t._env.close()
            except Exception:
                log.error("env close failed:\n" + traceback.format_exc())
                if result == 0:
                    result = 1
            t._env = None
        _current = None
    sys.exit(result)
