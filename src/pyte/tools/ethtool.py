# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.ethtool — run ethtool show/dump commands via pyte.job.

Pure Python over pyte.job; zero shim imports. The ethtool binary is
resolved from the agent's PATH (job program "ethtool").

READ-ONLY: the C TAPI header explicitly forbids using ethtool to *change*
configuration (use the configuration tree for that). This wrapper only
runs show/dump commands.

Pinned mappings (from te/lib/tapi_tool/tapi_ethtool.{h,c})
==========================================================

argv (BASIC_BINDS): [--include-statistics] [<cmd-flag>] <if_name>
  NONE emits no command flag (just `ethtool <if_name>`).
  EEPROM_DUMP appends:  [raw on|off] [offset N] [length N]
  DUMP_MODULE_EEPROM appends:
  [raw on|off] [hex on|off] [offset N] [length N] [page N] [bank N] [i2c N]

Output parsing (only these 4 commands yield structured data; the other
6 expose raw stdout only, mirroring the C "stdout parsing not supported"):

  NONE       -> IfProps(link, autoneg)        ("Link detected", "Auto-negotiation")
  STATS      -> dict[str, str] + get_stat()   ("name: value" lines, last colon splits)
  SHOW_PAUSE -> Pause(autoneg, rx, tx, rx/tx_pause_frames)
  SHOW_RING  -> Ring(rx_max, tx_max, rx, tx)  (Pre-set maximums then Current)

err_code: stderr containing "Operation not supported" -> EOPNOTSUPP, else OK
(pyte represents err_code as the local ErrCode enum rather than a raw
te_errno, to avoid adding shim constants).
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyte.tools import _tool

if TYPE_CHECKING:
    from pyte.job import JobStatus
    from pyte.rpc import RpcServer


class Cmd(enum.Enum):
    """ethtool command codes (mirror tapi_ethtool_cmd).

    A real Enum (A5): ``Opts(cmd="stat")`` (a typo for ``"stats"``) used
    to fall through ``_CMD_FLAG.get()`` silently and run bare ``ethtool
    eth0``. Construction now routes through ``_tool.coerce_enum``, so a
    typo raises ValueError up front instead of producing an unstructured
    report with no error.
    """
    NONE = "none"
    STATS = "stats"
    SHOW_PAUSE = "show_pause"
    SHOW_RING = "show_ring"
    REG_DUMP = "reg_dump"
    EEPROM_DUMP = "eeprom_dump"
    DUMP_MODULE_EEPROM = "dump_module_eeprom"
    SHOW_EEE = "show_eee"
    SHOW_FEC = "show_fec"
    SHOW_MODULE = "show_module"


#: command -> ethtool flag (NONE has no flag)
_CMD_FLAG: dict[Cmd, str] = {
    Cmd.STATS: "--statistics",
    Cmd.SHOW_PAUSE: "--show-pause",
    Cmd.SHOW_RING: "--show-ring",
    Cmd.REG_DUMP: "--register-dump",
    Cmd.EEPROM_DUMP: "--eeprom-dump",
    Cmd.DUMP_MODULE_EEPROM: "--dump-module-eeprom",
    Cmd.SHOW_EEE: "--show-eee",
    Cmd.SHOW_FEC: "--show-fec",
    Cmd.SHOW_MODULE: "--show-module",
}


def _bool3(name: str, val: bool | None) -> list[str]:
    """ethtool ``<name> on|off`` sub-arg; omitted when val is None."""
    if val is None:
        return []
    return [name, "on" if val else "off"]


def _uint(name: str, val: int | None) -> list[str]:
    """ethtool ``<name> N`` sub-arg; omitted when val is None."""
    if val is None:
        return []
    return [name, str(val)]


@dataclass(frozen=True)
class Opts:
    """ethtool options.

    Parameters
    ----------
    if_name:
        Interface name (mandatory; positional, after the command flag).
    cmd:
        A :class:`Cmd` member, or its (case-insensitive) name/value as a
        string, e.g. ``"stats"`` (default :data:`Cmd.NONE`). An unknown
        string raises ValueError at construction (A5).
    stats:
        ``--include-statistics`` flag.
    raw, hex, offset, length, page, bank, i2c:
        Sub-arguments used only by ``EEPROM_DUMP`` (raw/offset/length) and
        ``DUMP_MODULE_EEPROM`` (all of them); ignored for other commands.
        Each is omitted from argv when None.
    """
    if_name: str
    cmd: "Cmd | str" = Cmd.NONE
    stats: bool = False
    raw: bool | None = None
    hex: bool | None = None
    offset: int | None = None
    length: int | None = None
    page: int | None = None
    bank: int | None = None
    i2c: int | None = None

    def __post_init__(self) -> None:
        if not self.if_name:
            raise ValueError("Opts.if_name is required")
        object.__setattr__(
            self, "cmd", _tool.coerce_enum(Cmd, "cmd", self.cmd))

    def to_argv(self) -> list[str]:
        """Build the ethtool argument list (without argv[0])."""
        argv: list[str] = []
        if self.stats:
            argv.append("--include-statistics")
        flag = _CMD_FLAG.get(self.cmd)
        if flag is not None:
            argv.append(flag)
        argv.append(self.if_name)
        if self.cmd == Cmd.EEPROM_DUMP:
            argv += _bool3("raw", self.raw)
            argv += _uint("offset", self.offset)
            argv += _uint("length", self.length)
        elif self.cmd == Cmd.DUMP_MODULE_EEPROM:
            argv += _bool3("raw", self.raw)
            argv += _bool3("hex", self.hex)
            argv += _uint("offset", self.offset)
            argv += _uint("length", self.length)
            argv += _uint("page", self.page)
            argv += _uint("bank", self.bank)
            argv += _uint("i2c", self.i2c)
        return argv


# ---------------------------------------------------------------------------
# Report dataclasses
# ---------------------------------------------------------------------------

class ErrCode(enum.Enum):
    """pyte representation of the C report err_code.

    FAIL marks a non-zero ethtool exit whose stderr matched no known
    pattern — the run failed for an unexpected reason (bad interface
    name, permission, ...) and no section was parsed.
    """
    OK = "ok"
    EOPNOTSUPP = "eopnotsupp"
    FAIL = "fail"


@dataclass(frozen=True)
class IfProps:
    """Interface properties (Cmd.NONE)."""
    link: bool
    autoneg: bool


@dataclass(frozen=True)
class Pause:
    """Pause parameters (Cmd.SHOW_PAUSE)."""
    autoneg: bool
    rx: bool
    tx: bool
    rx_pause_frames: int | None
    tx_pause_frames: int | None


@dataclass(frozen=True)
class Ring:
    """Ring sizes (Cmd.SHOW_RING)."""
    rx_max: int
    tx_max: int
    rx: int
    tx: int


@dataclass(frozen=True)
class Report:
    """Parsed ethtool output (mirrors tapi_ethtool_report).

    Exactly one of if_props/stats/pause/ring is set, depending on cmd
    (and only when err_code is OK). The other commands expose raw `out`.
    """
    cmd: Cmd
    out: str
    err: str
    err_code: ErrCode
    if_props: "IfProps | None" = None
    stats: "dict[str, str] | None" = None
    pause: "Pause | None" = None
    ring: "Ring | None" = None
    #: Job completion status (None only for offline-built reports).
    status: "JobStatus | None" = None

    def get_stat(self, name: str) -> int:
        """Return a single statistic as an int (mirror tapi_ethtool_get_stat).

        Raises EthtoolError if there is no statistic with that name.
        """
        from pyte.errors import EthtoolError
        if self.stats is None or name not in self.stats:
            raise EthtoolError(f"no statistic named {name!r}")
        return int(self.stats[name])


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _value(text: str, prefix: str) -> str | None:
    """Return the value of the first ``<prefix>: <value>`` line, or None."""
    m = re.search(rf"^\s*{re.escape(prefix)}:\s*(.*?)\s*$", text, re.M)
    return m.group(1) if m else None


def _on(text: str, prefix: str) -> bool:
    """True iff ``<prefix>`` line value is 'on' (case-insensitive)."""
    v = _value(text, prefix)
    return v is not None and v.lower() == "on"


def _parse_if_props(out: str) -> IfProps:
    link = _value(out, "Link detected")
    autoneg = _value(out, "Auto-negotiation")
    return IfProps(
        link=(link is not None and link.lower() == "yes"),
        autoneg=(autoneg is not None and autoneg.lower() == "on"),
    )


def _parse_pause(out: str) -> Pause:
    rxf = _value(out, "RX pause frames")
    txf = _value(out, "TX pause frames")
    return Pause(
        autoneg=_on(out, "Autonegotiate"),
        rx=_on(out, "RX"),
        tx=_on(out, "TX"),
        rx_pause_frames=int(rxf) if rxf not in (None, "") else None,
        tx_pause_frames=int(txf) if txf not in (None, "") else None,
    )


def _parse_ring(out: str) -> Ring:
    from pyte.errors import EthtoolError
    rx = re.findall(r"^\s*RX:\s*(\d+)\s*$", out, re.M)
    tx = re.findall(r"^\s*TX:\s*(\d+)\s*$", out, re.M)
    if len(rx) < 2 or len(tx) < 2:
        raise EthtoolError(
            f"cannot parse ring sizes; rx={rx} tx={tx}")
    return Ring(rx_max=int(rx[0]), tx_max=int(tx[0]),
                rx=int(rx[1]), tx=int(tx[1]))


def _parse_stats(out: str) -> "dict[str, str]":
    from pyte.errors import EthtoolError
    stats: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            raise EthtoolError(f"wrong format of a stats line: {line!r}")
        key, _, value = line.rpartition(":")
        stats[key] = value
    return stats


def _err_code(err: str, status: "JobStatus | None") -> ErrCode:
    if "Operation not supported" in err:
        return ErrCode.EOPNOTSUPP
    if status is not None and not status.ok:
        # Unexpected failure (bad device, permission, ...): do NOT
        # parse the (usually empty) output into a confident report --
        # e.g. Cmd.NONE would yield IfProps(link=False) from empty
        # stdout, indistinguishable from a real link-down.
        return ErrCode.FAIL
    return ErrCode.OK


def _build_report(cmd: Cmd, out: str, err: str,
                  status: "JobStatus | None" = None) -> Report:
    """Assemble a Report from raw stdout/stderr (offline-testable)."""
    err_code = _err_code(err, status)
    kwargs: dict = dict(cmd=cmd, out=out, err=err, err_code=err_code,
                        status=status)
    if err_code is ErrCode.OK:
        if cmd == Cmd.NONE:
            kwargs["if_props"] = _parse_if_props(out)
        elif cmd == Cmd.STATS:
            kwargs["stats"] = _parse_stats(out)
        elif cmd == Cmd.SHOW_PAUSE:
            kwargs["pause"] = _parse_pause(out)
        elif cmd == Cmd.SHOW_RING:
            kwargs["ring"] = _parse_ring(out)
        # other commands: raw `out` only
    return Report(**kwargs)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(pco: "RpcServer", opts: Opts, timeout: float = 10.0) -> Report:
    """Run an ethtool command and return a parsed :class:`Report`.

    ethtool is a short-lived command, so this runs it to completion
    (create + start + wait), reads stdout/stderr, and destroys the job.
    A non-zero ethtool exit is NOT raised here — it is reflected in
    ``Report.err_code`` (``EOPNOTSUPP`` when stderr says so, ``FAIL``
    otherwise) and the completion status in ``Report.status``,
    mirroring the C TAPI's no-raise policy.  A parse failure (e.g.
    unexpected ring output) raises EthtoolError.

    Example::

        rep = ethtool.run(pco, ethtool.Opts(if_name="eth0",
                                             cmd=ethtool.Cmd.STATS))
        print(rep.get_stat("rx_packets"))
    """
    def _setup(job):
        out = job.stdout.attach_filter(name="ethtool_out", readable=True)
        err = job.stderr.attach_filter(name="ethtool_err", readable=True)
        return out, err

    job, (out_filter, err_filter) = _tool.launch(
        pco, "ethtool", opts.to_argv(), setup=_setup)
    try:
        status = job.wait(timeout=timeout)
        out = out_filter.read_all(timeout=timeout)
        err = err_filter.read_all(timeout=timeout)
    finally:
        job.destroy()
    return _build_report(opts.cmd, out, err, status=status)
