# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.mi — thin Python wrapper over TE's te_mi measurement logger.

This module exposes a single context manager, ``Logger``, that wraps the
three te_mi C functions:

    te_mi_logger_meas_create(tool, **logger)   → pyte_mi_meas_create
    te_mi_logger_add_meas(logger, &retval, …)  → pyte_mi_add_meas
    te_mi_logger_destroy(logger)               → pyte_mi_destroy

The *tool* string passed to ``Logger("fio")`` becomes the ``"tool"`` key in
the MI JSON artifact that TE's Logger emits.  ``destroy`` (called on CM exit
or explicit ``close()``) flushes the artifact; no MI data is emitted if no
measurements were added.

Design: thin and generic — pyte.tools.fio (and future perf tools) consume it from
pure Python without any tapi_fio linkage.

Measurement types, aggregations, and multipliers are represented by the
:class:`Meas`, :class:`Aggr`, and :class:`Mult` enums.

Example::

    with mi.Logger("fio") as logger:
        logger.add(Meas.LATENCY, "clat-p99", Aggr.PERCENTILE, 42.0,
                   Mult.MICRO)
"""
from __future__ import annotations

import enum

from pyte.errors import check


class Meas(enum.Enum):
    """MI measurement type; value is the PYTE_MI_MEAS_* shim constant name."""

    LATENCY = "PYTE_MI_MEAS_LATENCY"
    THROUGHPUT = "PYTE_MI_MEAS_THROUGHPUT"
    IOPS = "PYTE_MI_MEAS_IOPS"
    RTT = "PYTE_MI_MEAS_RTT"
    RETRANS = "PYTE_MI_MEAS_RETRANS"
    RPS = "PYTE_MI_MEAS_RPS"
    PERCENTAGE = "PYTE_MI_MEAS_PERCENTAGE"
    TIME = "PYTE_MI_MEAS_TIME"
    LOADAVG = "PYTE_MI_MEAS_LOADAVG"


class Aggr(enum.Enum):
    """MI aggregation; value is the PYTE_MI_AGGR_* shim constant name."""

    SINGLE = "PYTE_MI_AGGR_SINGLE"
    MIN = "PYTE_MI_AGGR_MIN"
    MAX = "PYTE_MI_AGGR_MAX"
    MEAN = "PYTE_MI_AGGR_MEAN"
    STDEV = "PYTE_MI_AGGR_STDEV"
    MEDIAN = "PYTE_MI_AGGR_MEDIAN"
    PERCENTILE = "PYTE_MI_AGGR_PERCENTILE"


class Mult(enum.Enum):
    """MI multiplier/scale; value is the PYTE_MI_MULT_* shim constant name."""

    NANO = "PYTE_MI_MULT_NANO"
    MICRO = "PYTE_MI_MULT_MICRO"
    MILLI = "PYTE_MI_MULT_MILLI"
    PLAIN = "PYTE_MI_MULT_PLAIN"
    MEGA = "PYTE_MI_MULT_MEGA"
    MEBI = "PYTE_MI_MULT_MEBI"


#: Lazy cache: MI enum member -> integer value (populated from the shim on
#: first use so unit tests with a fake shim can supply the values).
_BITS: dict[enum.Enum, int] = {}


def _const(member: enum.Enum) -> int:
    """Resolve an MI enum member to its shim integer (cached)."""
    if member not in _BITS:
        from pyte._shim import lib
        _BITS[member] = int(getattr(lib, member.value))
    return _BITS[member]


# ---------------------------------------------------------------------------
# Logger context manager
# ---------------------------------------------------------------------------

class Logger:
    """MI measurement logger context manager.

    Creates a ``te_mi_logger`` on entry, flushes and destroys it on exit
    (idempotent ``close()``).  ``add()`` raises ``RuntimeError`` after
    close.

    Parameters
    ----------
    tool:
        Tool name that keys the MI artifact (e.g. ``"fio"``).

    Example::

        with mi.Logger("fio") as logger:
            logger.add(Meas.LATENCY, "clat-p99", Aggr.PERCENTILE, 42.0,
                       Mult.MICRO)
    """

    def __init__(self, tool: str) -> None:
        self._tool   = tool
        self._logger = None   # set by _open()
        self._closed = False
        self._open()

    def _open(self) -> None:
        from pyte._shim import ffi, lib
        out = ffi.new("te_mi_logger **")
        rc = lib.pyte_mi_meas_create(self._tool.encode(), out)
        check(rc, f"mi.Logger({self._tool!r})")
        self._logger = out[0]
        self._lib    = lib
        self._ffi    = ffi

    def add(self, type: Meas, name: str | None, aggr: Aggr, value: float,
            multiplier: Mult = Mult.PLAIN) -> None:
        """Add one measurement to the logger.

        :param type:       a :class:`Meas` member (e.g. ``Meas.LATENCY``).
        :param name:       free-form measurement name; ``None`` maps to
                           C ``NULL`` (an unnamed measurement — required
                           by graph views keyed on measurement type).
        :param aggr:       an :class:`Aggr` member (e.g. ``Aggr.MEAN``).
        :param value:      measurement value (units = *type* × *multiplier*).
        :param multiplier: a :class:`Mult` member (default ``Mult.PLAIN``).
        :raises RuntimeError: if the logger is already closed.
        :raises TypeError:    if type/aggr/multiplier are the wrong enum.
        :raises TeError:      if the underlying C call fails.
        """
        if self._closed:
            raise RuntimeError(
                f"mi.Logger({self._tool!r}) is already closed")
        if not isinstance(type, Meas):
            raise TypeError(
                f"type must be a Meas, not {type.__class__.__name__}")
        if not isinstance(aggr, Aggr):
            raise TypeError(
                f"aggr must be an Aggr, not {aggr.__class__.__name__}")
        if not isinstance(multiplier, Mult):
            raise TypeError(
                "multiplier must be a Mult, not "
                f"{multiplier.__class__.__name__}")
        cname = self._ffi.NULL if name is None else name.encode()
        rc = self._lib.pyte_mi_add_meas(
            self._logger, _const(type), cname, _const(aggr),
            float(value), _const(multiplier))
        check(rc, f"mi.Logger.add({name!r})")

    def line_graph(self, name: str, title: str, x_axis: Meas) -> None:
        """Add a line-graph view over the logged measurements.

        Wraps te_mi_logger_add_meas_view(TE_MI_MEAS_VIEW_LINE_GRAPH) +
        te_mi_logger_meas_graph_axis_add_type(TE_MI_GRAPH_AXIS_X): the
        X axis is keyed on the (single, unnamed) measurement of type
        *x_axis*; all other measurements become Y-axis lines.

        :param name:   view name (unique per view type).
        :param title:  view title shown when the graph is displayed.
        :param x_axis: a :class:`Meas` member whose (single, unnamed)
                       measurement supplies the X coordinates.
        :raises RuntimeError: if the logger is already closed.
        :raises TypeError:    if *x_axis* is not a :class:`Meas`.
        :raises TeError:      if the underlying C call fails.
        """
        if self._closed:
            raise RuntimeError(
                f"mi.Logger({self._tool!r}) is already closed")
        if not isinstance(x_axis, Meas):
            raise TypeError(
                f"x_axis must be a Meas, not {x_axis.__class__.__name__}")
        lib = self._lib
        rc = lib.pyte_mi_add_view(self._logger,
                                  int(lib.PYTE_MI_VIEW_LINE_GRAPH),
                                  name.encode(), title.encode())
        check(rc, f"mi.Logger.line_graph({name!r})")
        rc = lib.pyte_mi_graph_axis_add(self._logger,
                                        int(lib.PYTE_MI_VIEW_LINE_GRAPH),
                                        name.encode(),
                                        int(lib.PYTE_MI_GRAPH_AXIS_X),
                                        _const(x_axis))
        check(rc, f"mi.Logger.line_graph({name!r}) x-axis")

    def close(self) -> None:
        """Flush MI data and destroy the logger (idempotent)."""
        if self._closed:
            return
        self._closed = True
        rc = self._lib.pyte_mi_destroy(self._logger)
        check(rc, "mi.Logger.close()")

    # Context-manager protocol

    def __enter__(self) -> "Logger":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
