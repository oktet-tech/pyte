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
from pyte._params import Params, parse_argv
from pyte.errors import TestFail, TestSkip

EXIT_SIGINT = 0x2
EXIT_SKIP = 0x5

_current: "Test | None" = None


class Test:
    def __init__(self, params: Params):
        self.params = params
        self._cleanups: list[tuple[Callable, tuple, dict]] = []

    # -- structure ---------------------------------------------------
    def step(self, text: str) -> None:
        from pyte._shim import lib
        lib.pyte_step(text.encode())

    def substep(self, text: str) -> None:
        from pyte._shim import lib
        lib.pyte_substep(text.encode())

    def verdict(self, text: str, error: bool = False) -> None:
        from pyte._shim import lib
        lvl = lib.TE_LL_ERROR if error else lib.TE_LL_RING
        lib.pyte_verdict(lvl, text.encode())

    def artifact(self, text: str) -> None:
        from pyte._shim import lib
        lib.pyte_artifact(lib.TE_LL_RING, text.encode())

    # -- outcome -----------------------------------------------------
    def fail(self, text: str) -> None:
        raise TestFail(text)

    def skip(self, text: str = "") -> None:
        raise TestSkip(text)

    def cleanup(self, fn: Callable, *args, **kwargs) -> None:
        """Register fn to run at test end (LIFO), pass or fail."""
        self._cleanups.append((fn, args, kwargs))

    # -- environment -------------------------------------------------
    @property
    def agent(self) -> str:
        """Name of the suite's single test agent."""
        return os.environ.get("TE_IUT_TA_NAME", "Agt_A")

    def rpc_server(self, name: str):
        from pyte.rpc import RpcServer
        srv = RpcServer.create(self.agent, name)
        self.cleanup(srv.destroy)
        return srv

    def _run_cleanups(self) -> bool:
        ok = True
        for fn, args, kwargs in reversed(self._cleanups):
            try:
                fn(*args, **kwargs)
            except Exception:
                log.error("cleanup failed:\n" + traceback.format_exc())
                ok = False
        return ok


def current() -> Test:
    assert _current is not None, "test.start() not active"
    return _current


def _sig_handler(signum, frame):
    if signum == signal.SIGINT:
        os._exit(EXIT_SIGINT)
    raise TestFail(f"Test got signal {signal.Signals(signum).name}")


@contextmanager
def start(name: str | None = None):
    """TEST_START/TEST_END equivalent.

    with test.start() as t:
        t.step(...)
    """
    global _current
    from pyte._shim import lib

    entity = name or os.path.basename(sys.argv[0])
    params = Params(parse_argv(sys.argv[1:]))

    lib.pyte_log_init(entity.encode())
    test_id = int(params.get("te_test_id", "0"))
    if test_id == 0:
        print("te_test_id parameter not found", file=sys.stderr)
        sys.exit(1)
    lib.te_test_id = test_id

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGUSR1, _sig_handler)

    t = Test(params)
    _current = t
    t.step("Test start")

    if "te_rand_seed" in params:
        seed = params.int("te_rand_seed")
        random.seed(seed)
        log.ring(f"Pseudo-random seed is {seed}")

    # Route everything into the TE Logger: it does its own level
    # filtering, while the stdlib root logger defaults to WARNING.
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger().addHandler(log.TeLogHandler())

    result = 1
    try:
        yield t
        result = 0
    except TestSkip as e:
        if str(e):
            t.verdict(str(e))
        result = EXIT_SKIP
    except TestFail as e:
        log.error(f"Test failed: {e}")
        result = 1
    except Exception:
        log.error("Unhandled exception:\n" + traceback.format_exc())
        result = 1
    finally:
        if not t._run_cleanups() and result == 0:
            result = 1
        _current = None
    sys.exit(result)
