# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Small standalone helpers with no TE dependency.

Nothing here talks to the shim, the Configurator or an agent, so these
functions are usable from plain unit tests and from suite code alike.
(Not to be confused with :mod:`pyte._util`, which is the internal shim
plumbing.)
"""
from __future__ import annotations

import math


def cdiv(num: float, den: float) -> float:
    """Divide with C/IEEE-754 semantics instead of raising.

    A zero denominator yields an infinity of the appropriate sign, or
    NaN for ``0/0``, the way C floating-point division does, rather
    than Python's :exc:`ZeroDivisionError`.  Measurements legitimately
    come out as zero (a direction that carried no traffic at all, a
    run that failed completely), and a statistic computed from them
    should report inf/nan rather than abort the caller.

    The sign follows both operands: ``-0.0`` as the denominator flips
    it, matching C.
    """
    if den != 0:
        return num / den
    if num == 0:
        return math.nan
    return math.copysign(math.inf, num) * math.copysign(1.0, den)
