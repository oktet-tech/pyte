# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools shared machinery: the one home for wrapper plumbing.

The tool wrappers used to be fifteen hand-rolled copies of one design
whose lifecycle/error/cleanup layers drifted apart (five different
non-zero-exit policies, two cleanup idioms, three argv-builder styles).
This module owns the shared layers; per-tool modules keep what is
genuinely theirs: the Opts dataclass with its C-source-pinned argv
bind order, the output parser, and the MI vocabulary.

Everything here is override-friendly by design: tools with specifics
subclass and redefine individual hooks instead of forking the whole
lifecycle.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# argv builders: explicit order stays in the tool module (that order is
# pinned to the C TAPI); these only remove the `if x is not None` ladders.
# ---------------------------------------------------------------------------


def opt(flag: str, value) -> list[str]:
    """``["-p", "8080"]`` — a flag/value pair; [] when value is None."""
    return [] if value is None else [flag, str(value)]


def opt_eq(flag: str, value) -> list[str]:
    """``["--threads=4"]`` — joined form; *flag* includes the ``=``."""
    return [] if value is None else [f"{flag}{value}"]


def switch(name: str, on) -> list[str]:
    """``["-D"]`` when *on* is truthy, else []."""
    return [name] if on else []


def suffixed(flag: str, value, suffix: str) -> list[str]:
    """``["--time=30s"]`` — joined form with a unit suffix appended."""
    return [] if value is None else [f"{flag}{value}{suffix}"]


# ---------------------------------------------------------------------------
# option coercion / validation
# ---------------------------------------------------------------------------


def coerce_enum(cls, field: str, v):
    """Accept an enum member or a (case-insensitive) member-name string.

    Promoted from fio, the best-in-class enum strategy of the package:
    ``Opts(rwtype="randwrite")`` and ``Opts(rwtype=RwType.RANDWRITE)``
    both work, and a typo lists the valid names.
    """
    if isinstance(v, cls):
        return v
    if isinstance(v, str):
        try:
            return cls[v.upper()]
        except KeyError:
            valid = [m.name.lower() for m in cls]
            raise ValueError(
                f"unknown {field} {v!r}; valid: {valid}") from None
    raise TypeError(
        f"{field} must be {cls.__name__} or str, not "
        f"{v.__class__.__name__}")


#: ipversion values as the tools spell them on the command line
#: ("-4"/"-6"); shared by iperf3/netperf/sfnt_pingpong.
IPVERSIONS = frozenset({"4", "6"})


def check_ipversion(v, field: str = "ipversion") -> None:
    """Validate an optional "4"/"6" ipversion option value."""
    if v is not None and v not in IPVERSIONS:
        raise ValueError(
            f"unknown {field} {v!r}; valid: {sorted(IPVERSIONS)}")


# ---------------------------------------------------------------------------
# address arguments: tests hand wrappers a pyte.env.Addr, a (host, port)
# tuple, or a bare port; normalize in one place.
# ---------------------------------------------------------------------------

#: What address-taking wrapper options accept (env.Addr exposes .pair).
AddrLike = "int | tuple[str, int] | pyte.env.Addr"


def addr_host_port(v) -> tuple[str, int]:
    """Normalize an AddrLike carrying a host to ``(host, port)``."""
    if hasattr(v, "pair"):
        v = v.pair
    if isinstance(v, tuple):
        return str(v[0]), int(v[1])
    raise TypeError(
        f"expected (host, port) or an env.Addr (a bare port has no "
        f"host), got {v!r}")


def addr_port(v) -> int:
    """Normalize an AddrLike to just the port number."""
    if hasattr(v, "pair"):
        v = v.pair
    if isinstance(v, tuple):
        return int(v[1])
    return int(v)
