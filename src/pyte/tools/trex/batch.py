# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.batch - option model for batch (ASTF) TRex runs.

Port of te/lib/tapi_tool/tapi_trex.{h,c} option model, pinned at
ngfw-ts 41f9731 era (tapi_trex identical to tsf/main).

This module owns the argv-building surface (:class:`Opts` and the
endpoint/enum types it is built from) plus platform YAML config-file
rendering (:func:`render_cfg_yaml`). Job launch and output parsing
belong to later tasks; :meth:`Opts.to_argv` deliberately does NOT
append ``--cfg`` (appended at launch time).

Pinned mappings (from tapi_trex.c:337-360, tapi_trex.h:290-324)
================================================================

- ``Verbose`` mirrors ``tapi_trex_verbose_mapping``: only MIN ("1") and
  MAX ("3") are meaningful values (no "2").
- ``Iom`` mirrors ``tapi_trex_iom_mapping``: DEFAULT ("0", C's
  TAPI_TREX_IOM_SILENT), NORMAL ("1", TAPI_TREX_IOM_NORMAL), BATCH
  ("2", TAPI_TREX_IOM_SHORT).
- ``So`` mirrors ``tapi_trex_so_mapping``, one member per single
  ``--*-so`` flag. DIVERGENCE: the C enum also has a
  ``TAPI_TREX_SO_MLX4_MLX5`` value that emits the two flags joined as
  one broken argv element (``"--mlx4-so --mlx5-so"``); pyte instead
  takes a tuple of ``So`` and emits each flag as its own argv element
  (put both ``So.MLX4`` and ``So.MLX5`` in the tuple for that case).
- DIVERGENCE: C's ``tapi_trex_opt`` does not validate ``astf_template``
  at all; :class:`Opts` requires ``astf_json`` non-empty in
  ``__post_init__`` (see the check there for the same note).

argv (bind order, tapi_trex.c:362-390 ``trex_args_binds``)::

    trex_exec  -f default.py --astf
    [--astf-server-only]  [-c N]  [--tso-disable]  [--lro-disable]
    [-d %.6f]  [--flip]  [--hdrh]  [--ipv6]  [-m %.6f]  [--nc]
    [--no-flow-control-change]  [--no-watchdog]  [--rt]  [-pubd]
    [--queue-drop]  [--sleeps]  [-v <1|3>]  [--iom <0|1|2>]
    [<so flag> ...]  [-w N]  [--prefix <name>]

``--cfg <path>`` is appended by the caller at launch, not by
:meth:`Opts.to_argv`.

Field-name divergences from the C struct (tapi_trex.h:406-487),
kept explicit rather than silently renamed:

- ``force_close_at_end`` binds ``--nc`` (same as C).
- ``no_flow_control_change`` binds ``--no-flow-control-change``; the
  C field backing it is named ``enable_flow_control`` (its meaning:
  when the flag is passed, TRex's own flow-control auto-disable is
  skipped).
- ``rt_prio`` binds ``--rt`` (C field: ``use_realtime_prio``).
- ``no_monitors`` binds ``-pubd`` (C field: ``no_monitors``).
- ``queue_drop`` binds ``--queue-drop`` (C field: ``dont_resend_pkts``).
- ``sleeps`` binds ``--sleeps`` (C field: ``use_sleep``).
"""
from __future__ import annotations

import dataclasses
import enum

from pyte.tools import _tool


class Iom(enum.Enum):
    """IO mode for server output (tapi_trex_iom_mapping)."""
    DEFAULT = "0"
    NORMAL = "1"
    BATCH = "2"


class Verbose(enum.Enum):
    """Debug verbosity level (tapi_trex_verbose_mapping)."""
    MIN = "1"
    MAX = "3"


class So(enum.Enum):
    """NIC-specific shared-object flags (tapi_trex_so_mapping).

    Each member's value is the literal argv flag; put more than one
    member in :attr:`Opts.so` to get more than one flag emitted.
    """
    MLX4 = "--mlx4-so"
    MLX5 = "--mlx5-so"
    NTACC = "--ntacc-so"
    BNXT = "--bnxt-so"


@dataclasses.dataclass(frozen=True)
class LinuxIface:
    """A kernel/af-packet interface, identified by its name."""
    name: str


@dataclasses.dataclass(frozen=True)
class PciBdf:
    """A DPDK-bound port, identified by its PCI BDF (e.g. "0000:01:00.0")."""
    bdf: str


@dataclasses.dataclass(frozen=True)
class Endpoint:
    """One client or server port description.

    Not consumed by :meth:`Opts.to_argv` (there is no per-endpoint
    CLI flag); it feeds :func:`render_cfg_yaml`. ``iface`` is None for
    TRex's "dummy" port.
    """
    iface: LinuxIface | PciBdf | None = None
    ip: str | None = None
    gw: str | None = None
    src_mac: str | None = None
    dst_mac: str | None = None

    def __post_init__(self) -> None:
        if self.ip is not None and self.src_mac is not None:
            raise ValueError("Endpoint.ip and .src_mac are exclusive")
        if self.gw is not None and self.dst_mac is not None:
            raise ValueError("Endpoint.gw and .dst_mac are exclusive")


@dataclasses.dataclass(frozen=True)
class Opts:
    """TRex batch (ASTF) command-line options (mirrors tapi_trex_opt)."""
    trex_exec: str
    astf_json: str
    clients: tuple[Endpoint, ...] = ()
    servers: tuple[Endpoint, ...] = ()
    astf_server_only: bool = False
    n_threads: int | None = None
    tso_disable: bool = False
    lro_disable: bool = False
    duration: float | None = None
    flip: bool = False
    hdrh: bool = False
    ipv6: bool = False
    rate_multiplier: float | None = None
    force_close_at_end: bool = False       # --nc
    no_flow_control_change: bool = False   # C field enable_flow_control
    no_watchdog: bool = False
    rt_prio: bool = False
    no_monitors: bool = False              # -pubd
    queue_drop: bool = False
    sleeps: bool = False
    verbose: Verbose | None = None
    iom: Iom | None = None                 # NORMAL gates stat filters
    so: tuple[So, ...] = ()
    init_wait_sec: int | None = None
    instance_prefix: str | None = None
    cfg_extra: str | None = None   # YAML appended after port_info
    driver: str | None = None      # PCI bind driver, None = no bind
    stdout_log_level: str = "RING"
    stderr_log_level: str = "WARN"

    def __post_init__(self) -> None:
        # DIVERGENCE: C tapi_trex does not validate astf_template; we
        # require it non-empty.
        if not self.astf_json:
            raise ValueError("Opts.astf_json is required")
        if not self.clients and not self.servers:
            raise ValueError(
                "Opts requires at least one of clients/servers")

    def to_argv(self) -> list[str]:
        """Build the TRex argument list, including argv[0] (trex_exec).

        Mirrors trex_args_binds bind order (tapi_trex.c:362-390).
        ``--cfg <path>`` is NOT appended here; the caller adds it at
        launch time.
        """
        argv: list[str] = [self.trex_exec, "-f", "default.py", "--astf"]
        argv += _tool.switch("--astf-server-only", self.astf_server_only)
        argv += _tool.opt("-c", self.n_threads)
        argv += _tool.switch("--tso-disable", self.tso_disable)
        argv += _tool.switch("--lro-disable", self.lro_disable)
        if self.duration is not None:
            argv += ["-d", f"{self.duration:.6f}"]
        argv += _tool.switch("--flip", self.flip)
        argv += _tool.switch("--hdrh", self.hdrh)
        argv += _tool.switch("--ipv6", self.ipv6)
        if self.rate_multiplier is not None:
            argv += ["-m", f"{self.rate_multiplier:.6f}"]
        argv += _tool.switch("--nc", self.force_close_at_end)
        argv += _tool.switch("--no-flow-control-change",
                             self.no_flow_control_change)
        argv += _tool.switch("--no-watchdog", self.no_watchdog)
        argv += _tool.switch("--rt", self.rt_prio)
        argv += _tool.switch("-pubd", self.no_monitors)
        argv += _tool.switch("--queue-drop", self.queue_drop)
        argv += _tool.switch("--sleeps", self.sleeps)
        if self.verbose is not None:
            argv += ["-v", self.verbose.value]
        if self.iom is not None:
            argv += ["--iom", self.iom.value]
        argv += [so.value for so in self.so]
        argv += _tool.opt("-w", self.init_wait_sec)
        argv += _tool.opt("--prefix", self.instance_prefix)
        return argv


def _iface_literal(iface: LinuxIface | PciBdf | None) -> str:
    """Render one interface as it appears in the ``interfaces:`` list.

    Mirrors ``tapi_trex_setup_port``'s ``IFACES`` push (tapi_trex.c:1066):
    the name is always single-quoted (TRex/Cisco scripts misparse some
    PCI BDFs without quotes); a missing interface renders as ``'dummy'``
    (``TAPI_TREX_DUMMY``).
    """
    if iface is None:
        name = "dummy"
    elif isinstance(iface, LinuxIface):
        name = iface.name
    else:
        name = iface.bdf
    return f"'{name}'"


def render_cfg_yaml(opts: Opts) -> str:
    """Render the TRex platform YAML config (default_trex_cfg template).

    Mirrors ``tapi_trex_gen_yaml_config``/``tapi_trex_setup_port``
    (tapi_trex.c:989-1168) expanding the default template
    (tapi_trex.c:326-334): ports are paired ``client[0], server[0],
    client[1], server[1], ...`` (a missing entry at an index becomes a
    default :class:`Endpoint` -- iface ``None``, ip/gw ``"0.0.0.0"``),
    ``port_limit`` counts every port including dummies, and
    ``port_info:`` lists all IP-form ports before all MAC-form ports.

    DIVERGENCE: in C, a port whose ``ip``/``gw`` sockaddr pair mixes an
    IP address with a MAC (e.g. an IP source address with a MAC
    gateway) silently splits across ``PORTINFO_IP``/``PORTINFO_DST_MAC``,
    misaligning the two ``port_info:`` groups so a later ``ip:`` entry
    ends up paired with the wrong ``default_gw:``/``dest_mac:`` line.
    This function instead requires exactly one address form per port
    (both ``ip``-shaped or both ``mac``-shaped) and raises
    :class:`ValueError` otherwise.
    """
    n = max(len(opts.clients), len(opts.servers))
    ports: list[Endpoint] = []
    for i in range(n):
        client = opts.clients[i] if i < len(opts.clients) else Endpoint()
        server = opts.servers[i] if i < len(opts.servers) else Endpoint()
        ports.append(client)
        ports.append(server)

    ip_ports: list[tuple[str, str]] = []
    mac_ports: list[tuple[str, str]] = []
    for ep in ports:
        addr_is_mac = ep.src_mac is not None
        gw_is_mac = ep.dst_mac is not None
        if addr_is_mac != gw_is_mac:
            raise ValueError(
                "Endpoint must use exactly one address form: either "
                "ip/gw or src_mac/dst_mac, not a mix (DIVERGENCE: C "
                "would silently misalign the port_info YAML lists "
                f"here); got ip={ep.ip!r} gw={ep.gw!r} "
                f"src_mac={ep.src_mac!r} dst_mac={ep.dst_mac!r}")
        if addr_is_mac:
            mac_ports.append((ep.dst_mac, ep.src_mac))
        else:
            ip_ports.append((ep.ip if ep.ip is not None else "0.0.0.0",
                             ep.gw if ep.gw is not None else "0.0.0.0"))

    lines = [
        f"- port_limit      : {len(ports)}",
        "  version         : 2",
        "  interfaces: [" +
        ", ".join(_iface_literal(ep.iface) for ep in ports) + "]",
        "  port_info:",
    ]
    for ip, gw in ip_ports:
        lines.append(f"    - ip: {ip}")
        lines.append(f"      default_gw: {gw}")
    for dst_mac, src_mac in mac_ports:
        lines.append(f"    - dest_mac: {dst_mac}")
        lines.append(f"      src_mac: {src_mac}")

    yaml_text = "\n".join(lines) + "\n"
    if opts.cfg_extra:
        yaml_text += opts.cfg_extra
    return yaml_text
