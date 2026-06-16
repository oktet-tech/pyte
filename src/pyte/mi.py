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

Friendly-name maps
------------------
Names are resolved lazily from shim constants (same pattern as
``rpc/iomux.py``'s ``EVENT_BITS``).  Lookup tables are module-level dicts
populated on first use; unit tests that inject a fake shim just need to
define the matching ``PYTE_MI_*`` attributes.

Measurement types exposed:
    latency, throughput, iops, rtt, retrans, rps, percentage

Aggregation types:
    single, min, max, mean, stdev, median, percentile

Multipliers:
    nano, micro, milli, plain, mega, mebi
"""
from __future__ import annotations

from pyte.errors import check

# ---------------------------------------------------------------------------
# Lazy name → int maps (populated from shim on first use)
# ---------------------------------------------------------------------------

#: meas-type name → PYTE_MI_MEAS_* shim constant name
_TYPE_CONSTS: dict[str, str] = {
    "latency":    "PYTE_MI_MEAS_LATENCY",
    "throughput": "PYTE_MI_MEAS_THROUGHPUT",
    "iops":       "PYTE_MI_MEAS_IOPS",
    "rtt":        "PYTE_MI_MEAS_RTT",
    "retrans":    "PYTE_MI_MEAS_RETRANS",
    "rps":        "PYTE_MI_MEAS_RPS",
    "percentage": "PYTE_MI_MEAS_PERCENTAGE",
}

#: aggr name → PYTE_MI_AGGR_* shim constant name
_AGGR_CONSTS: dict[str, str] = {
    "single":     "PYTE_MI_AGGR_SINGLE",
    "min":        "PYTE_MI_AGGR_MIN",
    "max":        "PYTE_MI_AGGR_MAX",
    "mean":       "PYTE_MI_AGGR_MEAN",
    "stdev":      "PYTE_MI_AGGR_STDEV",
    "median":     "PYTE_MI_AGGR_MEDIAN",
    "percentile": "PYTE_MI_AGGR_PERCENTILE",
}

#: multiplier name → PYTE_MI_MULT_* shim constant name
_MULT_CONSTS: dict[str, str] = {
    "nano":  "PYTE_MI_MULT_NANO",
    "micro": "PYTE_MI_MULT_MICRO",
    "milli": "PYTE_MI_MULT_MILLI",
    "plain": "PYTE_MI_MULT_PLAIN",
    "mega":  "PYTE_MI_MULT_MEGA",
    "mebi":  "PYTE_MI_MULT_MEBI",
}

# Resolved int maps (populated lazily)
_TYPES: dict[str, int] = {}
_AGGRS: dict[str, int] = {}
_MULTS: dict[str, int] = {}


def _ensure_maps() -> None:
    """Populate the name→int maps lazily from the shim."""
    if _TYPES and _AGGRS and _MULTS:
        return
    from pyte._shim import lib
    if not _TYPES:
        for name, const in _TYPE_CONSTS.items():
            _TYPES[name] = int(getattr(lib, const))
    if not _AGGRS:
        for name, const in _AGGR_CONSTS.items():
            _AGGRS[name] = int(getattr(lib, const))
    if not _MULTS:
        for name, const in _MULT_CONSTS.items():
            _MULTS[name] = int(getattr(lib, const))


def _resolve(mapping: dict[str, int], kind: str, name: str) -> int:
    """Look up *name* in *mapping*, raising ``ValueError`` on miss."""
    if name not in mapping:
        raise ValueError(
            f"unknown {kind} {name!r}; "
            f"valid names: {sorted(mapping)}")
    return mapping[name]


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
            logger.add("latency", "clat-p99", "percentile", 42.0, "micro")
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

    def add(self, type: str, name: str, aggr: str, value: float,
            multiplier: str = "plain") -> None:
        """Add one measurement to the logger.

        Parameters
        ----------
        type:
            Measurement type name: ``"latency"``, ``"throughput"``,
            ``"iops"``.
        name:
            Free-form measurement name (e.g. ``"Read clat 99.00 percentile"``).
        aggr:
            Aggregation type: ``"single"``, ``"min"``, ``"max"``,
            ``"mean"``, ``"stdev"``, ``"percentile"``.
        value:
            Measurement value (in the units defined by *type* × *multiplier*).
        multiplier:
            Scale factor: ``"nano"``, ``"micro"``, ``"milli"``, ``"plain"``,
            ``"mebi"``  (default ``"plain"``).

        Raises
        ------
        RuntimeError
            If the logger has already been closed.
        ValueError
            If *type*, *aggr* or *multiplier* is not a recognised name.
        TeError
            If the underlying C call fails.
        """
        if self._closed:
            raise RuntimeError(
                f"mi.Logger({self._tool!r}) is already closed")
        _ensure_maps()
        typ_int  = _resolve(_TYPES, "type",       type)
        aggr_int = _resolve(_AGGRS, "aggr",       aggr)
        mult_int = _resolve(_MULTS, "multiplier", multiplier)
        rc = self._lib.pyte_mi_add_meas(
            self._logger, typ_int, name.encode(), aggr_int,
            float(value), mult_int)
        check(rc, f"mi.Logger.add({name!r})")

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
