# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Shared unit-suffix parsing for tool output/options.

Promoted from per-wrapper copies (wrk's parse_unit + scale tables,
fio's size parser) so future wrappers stop hand-rolling suffix walks.
The scale tables mirror tapi_wrk.c's parse_unit tables.
"""
from __future__ import annotations

#: time -> microseconds
TIME_US: dict[str, float] = {
    "us": 1,
    "ms": 1e3,
    "s":  1e6,
    "m":  60e6,
    "h":  3600e6,
}

#: metric counts -> base (scale x1000)
METRIC: dict[str, float] = {
    "":  1,
    "k": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
    "P": 1e15,
}

#: percent: bare float (no suffix)
PERCENT: dict[str, float] = {"": 1.0}

#: binary sizes -> base (scale x1024)
BINARY: dict[str, float] = {
    "":  1,
    "K": 1024,
    "M": 1024 ** 2,
    "G": 1024 ** 3,
    "T": 1024 ** 4,
    "P": 1024 ** 5,
}


def parse_unit(token: str, scale_map: dict[str, float]) -> float:
    """Parse a numeric token with an optional unit suffix.

    Splits *token* into a numeric prefix and a unit suffix, then
    multiplies by the scale from *scale_map*.

    Percent tokens (e.g. ``"89.00%"``) strip the trailing ``%`` and
    return the plain float (scale_map is ignored for these).

    Examples::

        parse_unit("456.78us", TIME_US)  -> 456.78
        parse_unit("2.50ms",   TIME_US)  -> 2500.0
        parse_unit("12.34k",   METRIC)   -> 12340.0
        parse_unit("3.50M",    BINARY)   -> 3670016.0
        parse_unit("89.00%",   TIME_US)  -> 89.0
    """
    if token.endswith("%"):
        return float(token[:-1])
    # Split into leading numeric part and trailing unit suffix.
    # Walk backwards to find where digits/dots end and letters start.
    i = len(token)
    while i > 0 and token[i - 1].isalpha():
        i -= 1
    numeric = token[:i]
    suffix = token[i:]
    value = float(numeric)
    scale = scale_map.get(suffix)
    if scale is None:
        raise ValueError(
            f"unknown unit {suffix!r} in token {token!r}; "
            f"valid: {sorted(scale_map)}")
    return value * scale


def parse_size(size: str | int | None) -> int | None:
    """Parse a fio-style size string to bytes.

    Accepts integers (pass through) or strings with optional suffix:
    k/K -> x1024, m/M -> x1024**2, g/G -> x1024**3.  No suffix means
    bytes.  Raises ValueError on unrecognised suffix, on unparsable
    numeric parts (e.g. "1.5g"), or on non-positive values.

    Returns None when size is None (unset).
    """
    if size is None:
        return None
    if isinstance(size, int):
        if size <= 0:
            raise ValueError(
                f"size must be positive, got {size!r}")
        return size
    s = size.strip()
    suffix = s[-1].lower() if s else ""
    multiplier = 1
    body = s
    if suffix in ("k", "m", "g"):
        body = s[:-1]
        multiplier = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[suffix]
    elif not s:
        raise ValueError(
            f"unrecognised size {size!r}; "
            "use an integer or a string like '4k', '16m', '1g'")
    elif not s[-1].isdigit():
        raise ValueError(
            f"unrecognised size {size!r}; "
            "use an integer or a string like '4k', '16m', '1g'")
    if not body.lstrip("-").isdigit():
        raise ValueError(
            f"unparsable numeric in size {size!r}; "
            "only whole-number sizes are supported (e.g. '4k', '16m', "
            "'1g')")
    result = int(body) * multiplier
    if result <= 0:
        raise ValueError(
            f"size must be positive, got {size!r}")
    return result
