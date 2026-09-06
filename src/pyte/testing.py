# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Test doubles for unit-testing suite code without a testbed.

Suite logic that only computes (window arithmetic, load projections,
message text) is worth unit-testing, but it calls into :mod:`pyte.log`
and :mod:`pyte.test`, which go through the compiled shim.  Every suite
therefore grows the same handful of doubles.  They live here instead:

* :class:`FakeShimLib` / :class:`FakeShimFfi` plus the
  :func:`fake_shim` fixture -- a recording stand-in for the native
  shim, installed as ``sys.modules["pyte._shim"]`` so the lazy shim
  lookups in :mod:`pyte.log` and :mod:`pyte.test` resolve to it;
* :func:`current_test` -- a real :class:`pyte.test.Test` installed as
  the current test, for code calling ``test.current()``;
* :class:`VerdictRecorder` -- for code taking its test handle as an
  explicit parameter, where no current test is needed;
* :class:`RecordingMiLogger` -- a stand-in for :class:`pyte.mi.Logger`;
* :class:`FakeTrexReport` -- a stand-in for a parsed TRex batch report.

The module imports :mod:`pytest` (it defines fixtures) and is meant to
be imported from test code only; nothing in pyte itself uses it.
Re-export the fixtures from a suite's ``conftest.py``::

    from pyte.testing import fake_shim, current_test  # noqa: F401
"""
from __future__ import annotations

import sys
import types
import warnings
from typing import ClassVar

import pytest


def _text(value) -> str:
    """Decode a shim argument (bytes or cdata) for recording."""
    if isinstance(value, str):
        return value
    return bytes(value).decode("utf-8", errors="replace")


class FakeShimFfi:
    """The sliver of cffi's ``ffi`` the recording doubles need.

    :meth:`string` is the identity on bytes, which is what the error
    model does with the ``const char *`` returned by te_rc_mod2str()
    and te_rc_err2str().
    """

    NULL = None

    @staticmethod
    def string(value):
        return value


class FakeShimLib:
    """Recording stand-in for the shim ``lib`` behind pyte.log/pyte.test.

    Records what was logged, rather than emitting it:

    * ``logs`` -- ``(level, text)`` per :func:`pyte.log` call, plus
      ``("STEP_PUSH"/"STEP_POP", text)`` for the nesting calls, in one
      chronological list;
    * ``records`` -- the same log calls as ``(level, user, text)``, for
      assertions that care about the log user;
    * ``steps``, ``substeps``, ``verdicts``, ``artifacts`` -- one list
      per structural call; the verdict/artifact entries are
      ``(level, text)`` pairs.

    Also covers the Tester calls (``pyte_reqs_modify``,
    ``pyte_tags_add_tag``), recorded in ``calls``, and the te_errno
    accessors :class:`pyte.errors.TeError` needs, so failure paths can
    be exercised: pass ``rc`` to make every recorded call fail with
    that status.  ``err_names`` maps an rc to the error name
    te_rc_err2str() reports for it (default ``"EUNKNOWN"``), which is
    how code branching on a specific te_errno is steered.
    """

    TE_LL_ERROR = 1
    TE_LL_WARN = 2
    TE_LL_RING = 3
    TE_LL_INFO = 4
    TE_LL_VERB = 5

    # Sentinel te_errno values.  Deliberately not small integers: a
    # test picking an arbitrary failing rc must not collide with them
    # and get a TimeoutError/CfgNotFoundError it did not ask for.
    PYTE_ETIMEDOUT = 0x7E01
    PYTE_ENOENT = 0x7E02

    def __init__(self, rc: int = 0):
        self.rc = rc
        self.te_test_id = 0
        self.entity: str | None = None
        self.logs: list[tuple] = []
        self.records: list[tuple[int, str, str]] = []
        self.steps: list[str] = []
        self.substeps: list[str] = []
        self.verdicts: list[tuple[int, str]] = []
        self.artifacts: list[tuple[int, str]] = []
        self.calls: list[tuple] = []
        self.err_names: dict[int, bytes] = {
            self.PYTE_ETIMEDOUT: b"ETIMEDOUT",
            self.PYTE_ENOENT: b"ENOENT",
        }

    # -- logging -------------------------------------------------------
    def pyte_log_init(self, entity):
        self.entity = _text(entity)

    def pyte_log(self, lvl, user, text):
        self.logs.append((lvl, _text(text)))
        self.records.append((lvl, _text(user), _text(text)))

    def pyte_step_push(self, text):
        self.logs.append(("STEP_PUSH", _text(text)))

    def pyte_step_pop(self, text):
        self.logs.append(("STEP_POP", _text(text)))

    # -- test structure ------------------------------------------------
    def pyte_step(self, text):
        self.steps.append(_text(text))

    def pyte_substep(self, text):
        self.substeps.append(_text(text))

    def pyte_verdict(self, lvl, text):
        self.verdicts.append((lvl, _text(text)))

    def pyte_artifact(self, lvl, text):
        self.artifacts.append((lvl, _text(text)))

    # -- tester --------------------------------------------------------
    def pyte_reqs_modify(self, reqs):
        self.calls.append(("reqs", _text(reqs)))
        return self.rc

    def pyte_tags_add_tag(self, tag, value):
        self.calls.append(("tag", _text(tag), _text(value)))
        return self.rc

    # -- te_errno ------------------------------------------------------
    def pyte_rc_module(self, rc):
        return 0

    def pyte_rc_error(self, rc):
        return rc

    def te_rc_mod2str(self, rc):
        return b"TAPI"

    def te_rc_err2str(self, rc):
        return self.err_names.get(rc, b"EUNKNOWN")

    # -- convenience ---------------------------------------------------
    def texts(self, level: int) -> list[str]:
        """The texts logged at one TE_LL_* level, in order."""
        return [text for lvl, text in self.logs if lvl == level]


@pytest.fixture()
def fake_shim(monkeypatch):
    """Install a :class:`FakeShimLib` as ``sys.modules["pyte._shim"]``.

    Lets pyte.log and pyte.test.Test run with no native TE build
    behind them.  Not autouse: a test that wants the real shim, or its
    own fake, must not be given this one.
    """
    lib = FakeShimLib()
    monkeypatch.setitem(
        sys.modules, "pyte._shim",
        types.SimpleNamespace(ffi=FakeShimFfi(), lib=lib))
    return lib


@pytest.fixture()
def current_test(fake_shim):
    """A real :class:`pyte.test.Test` installed as the current test.

    For code reaching for its test handle through
    :func:`pyte.test.current` instead of taking it as a parameter.
    The previous current test is restored afterwards, so the fixture
    nests and leaves no global state behind.
    """
    from pyte import test as pyte_test
    from pyte._params import Params

    t = pyte_test.Test(Params({}))
    saved = pyte_test._current
    pyte_test._current = t
    yield t
    pyte_test._current = saved


class VerdictRecorder:
    """A test handle that records instead of reaching the Logger.

    For the functions taking their pyte test handle as an explicit
    parameter: no current test needs installing, and nothing but the
    handle's own surface is faked.  ``fail()``/``skip()`` raise the
    real :class:`~pyte.errors.TestFail`/:class:`~pyte.errors.TestSkip`
    so a caller's error path behaves as it does in a real test.
    """

    def __init__(self):
        self.verdicts: list[tuple[str, bool]] = []
        self.artifacts: list[str] = []
        self.steps: list[str] = []
        self.substeps: list[str] = []

    def verdict(self, text: str, error: bool = False) -> None:
        self.verdicts.append((text, error))

    def artifact(self, text: str) -> None:
        self.artifacts.append(text)

    def step(self, text: str) -> None:
        self.steps.append(text)

    def substep(self, text: str) -> None:
        self.substeps.append(text)

    def fail(self, text: str) -> None:
        from pyte.errors import TestFail
        raise TestFail(text)

    def skip(self, text: str = "") -> None:
        from pyte.errors import TestSkip
        raise TestSkip(text)


class RecordingMiLogger:
    """Recording stand-in for :class:`pyte.mi.Logger`.

    Monkeypatch it over the ``mi.Logger`` the code under test uses and
    assert on ``adds``/``graphs``/``comments``.  :data:`registry`
    collects every instance created, in creation order, so a caller
    opening several ``with mi.Logger(tool):`` blocks can be checked
    block by block; reset it with :meth:`reset` before each test (a
    fixture doing that is one line).
    """

    registry: ClassVar[list["RecordingMiLogger"]] = []

    def __init__(self, tool):
        self.tool = tool
        self.adds: list[tuple] = []
        self.graphs: list[tuple] = []
        self.comments: list[tuple] = []
        self.closed = False
        RecordingMiLogger.registry.append(self)

    @classmethod
    def reset(cls) -> None:
        """Drop every recorded instance."""
        cls.registry = []

    def add(self, type_, name, aggr, value, multiplier=None):
        self.adds.append((type_, name, aggr, value, multiplier))

    def comment(self, name, value):
        self.comments.append((name, value))

    def line_graph(self, name, title, x_axis):
        self.graphs.append((name, title, x_axis))

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True
        return False


class FakeTrexReport:
    """Duck-typed stand-in for a parsed TRex batch report.

    Not a real :class:`pyte.tools.trex._batch_report.Report` instance:
    only the surface statistics code actually touches is implemented
    -- ``window()``, ``time_series()``, ``series_by_time()`` and the
    handful of read fields.  ``window()`` records its arguments in
    ``calls`` and returns the fixed ``value`` tuple; naming a parameter
    in ``clamp_params`` makes that call additionally raise the
    :class:`~pyte.tools.trex._batch_report.WindowClamped` warning the
    real report raises for an out-of-range time bound.
    """

    def __init__(self, value=(1.0, 2.0, 3.0, 4.0), clamp_params=(),
                 avg_cps=0.0, m_traff_dur_cl=0.0, port_series=(1,),
                 time_series_vals=(0.0, 1.0, 2.0), series_vals=None,
                 opt_cl=None, opt_srv=None):
        self.calls: list[tuple] = []
        self.value = value
        self.clamp_params = set(clamp_params)
        self.avg_cps = avg_cps
        self.m_traff_dur_cl = m_traff_dur_cl
        self.port_series = port_series
        self._time_series_vals = list(time_series_vals)
        self._series_vals = series_vals if series_vals is not None else {}
        self.opt_cl = opt_cl if opt_cl is not None else {}
        self.opt_srv = opt_srv if opt_srv is not None else {}

    def window(self, param, port, t0, t1):
        self.calls.append((param, port, t0, t1))
        if param in self.clamp_params:
            from pyte.tools.trex._batch_report import WindowClamped
            warnings.warn("fake clamp", WindowClamped)
        return self.value

    def time_series(self):
        return self._time_series_vals

    def series_by_time(self, param, port):
        return self._series_vals[(param, port)]
