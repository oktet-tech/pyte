# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TRex server options: platform cfg-YAML and the launch command.

Pure (no shim/TE imports) so it is unit-testable offline. The YAML shape
mirrors the C tapi_trex generated config (port_limit/version/interfaces/
port_info). The launch command derives the working directory from
dirname(trex_exec) — TRex must run from its install dir — matching the C
TAPI's tapi_job_set_workdir(dirname) behaviour.

Two modes:
  * DPDK (default): ``interfaces`` are PCI addresses; optional ``port_info``
    carries per-port (ip, default_gw). MAC-form ``port_macs`` is also
    legal here -- TRex's config format accepts it in either mode.
  * Software/af_packet (``software=True``): ``interfaces`` are Linux
    interface names and the launch gets ``--software``; ``port_macs``
    supplies the per-port (src_mac, dest_mac) af_packet needs (for a
    veth loopback, each port's dest_mac is the peer port's src_mac).

``cfg_extra``, when set, is appended to the rendered YAML verbatim (for
example a ``platform:``/``memory:`` block a native DPDK run needs); this
class does not interpret it, only the caller does.
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field

#: PYTHONWARNINGS for the TRex process.  TRex 3.06 ships Python
#: scripts (dpdk_setup_ports.py and friends) that use "\d" in plain
#: string literals; under a modern interpreter each one raises a
#: SyntaxWarning on stderr, which the server job logs at WARN -- nine
#: per bring-up, so hundreds over a run.  The vendor tree cannot be
#: fixed here.
#:
#: The blanket category filter is deliberate, do not narrow it to the
#: message: warnings._setoption re.escape()s the message field, so it
#: is a literal prefix and not a regex, and CPython reworded this very
#: warning in 3.14 -- both "ignore:invalid escape sequence:
#: SyntaxWarning" and its regex-looking cousin were measured to miss
#: there.  The option is valid and inert on every Python 3, so it also
#: needs no interpreter version check.
PYTHONWARNINGS = "ignore::SyntaxWarning"


@dataclass(frozen=True)
class ServerOpts:
    """Options to launch ``t-rex-64 -i`` (interactive STL) on an agent."""

    #: Absolute path to the TRex binary (e.g. /usr/local/trex/t-rex-64).
    trex_exec: str
    #: PCI addresses (DPDK) or Linux interface names (software mode),
    #: in TRex port order.
    ports: list[str] = field(default_factory=list)
    #: Hardware threads per port pair (TRex -c).
    cores: int = 1
    #: ZMQ sync RPC port the client connects to (loopback).
    sync_port: int = 4501
    #: ZMQ async stats port the client subscribes to (loopback).
    async_port: int = 4500
    #: Optional per-port (ip, default_gw) pairs (DPDK mode); same order
    #: as ports.
    port_info: list[tuple[str, str]] | None = None
    #: Software/af_packet mode: interfaces are Linux names, launch adds
    #: ``--software``. Needs ``port_macs``.
    software: bool = False
    #: Per-port (src_mac, dest_mac) for software mode; same order as ports.
    port_macs: list[tuple[str, str]] | None = None
    #: Run TRex in ASTF service mode (adds ``--astf``).
    astf: bool = False
    #: Disable TCP segmentation offload (adds ``--tso-disable``).
    tso_disable: bool = False
    #: Disable large receive offload (adds ``--lro-disable``).
    lro_disable: bool = False
    #: Text appended verbatim to the platform YAML, for the
    #: ``platform:``/``memory:`` block a native DPDK run needs. The
    #: caller renders it; this class does not interpret it.
    cfg_extra: str | None = None
    #: Literal NIC shared-object argv flags, e.g. ``("--mlx5-so",)``.
    #: Passed as strings rather than as the batch driver's ``So`` enum
    #: so this module stays free of TE-touching imports.
    so: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.trex_exec:
            raise ValueError("trex_exec is required")
        if not self.ports:
            raise ValueError("at least one port is required")
        if self.port_info is not None and len(self.port_info) != len(self.ports):
            raise ValueError("port_info length must match ports length")
        if self.port_macs is not None and len(self.port_macs) != len(self.ports):
            raise ValueError("port_macs length must match ports length")
        if self.port_info is not None and self.port_macs is not None:
            raise ValueError(
                "port_info and port_macs are mutually exclusive")
        if self.software and self.port_macs is None:
            raise ValueError("software mode requires port_macs")

    @property
    def workdir(self) -> str:
        """TRex install directory (where the binary lives)."""
        return os.path.dirname(self.trex_exec)

    def cfg_yaml(self) -> str:
        """Render the TRex platform config YAML."""
        ifaces = ", ".join(f"'{p}'" for p in self.ports)
        out = [
            f"- port_limit: {len(self.ports)}",
            "  version: 2",
            f"  interfaces: [{ifaces}]",
        ]
        # MACs/IPs are quoted like the interfaces: an unquoted
        # colon-separated MAC is a sexagesimal INTEGER under YAML 1.1.
        if self.port_macs is not None:
            out.append("  port_info:")
            for src_mac, dest_mac in self.port_macs:
                out.append(f"    - src_mac: '{src_mac}'")
                out.append(f"      dest_mac: '{dest_mac}'")
        elif self.port_info is not None:
            out.append("  port_info:")
            for ip, gw in self.port_info:
                out.append(f"    - ip: '{ip}'")
                out.append(f"      default_gw: '{gw}'")
        text = "\n".join(out) + "\n"
        if self.cfg_extra:
            text += self.cfg_extra
        return text

    def env(self) -> dict[str, str]:
        """Environment the TRex process needs beyond the agent's own.

        A mapping rather than a baked-in shell export, because a
        Configurator-launched process sets it through
        ``/agent/process/env:`` instead -- see
        :func:`pyte.tools.trex.astf.start_server`.
        """
        return {"PYTHONWARNINGS": PYTHONWARNINGS}

    def argv(self, cfg_path: str) -> list[str]:
        """Arguments for the TRex binary, excluding argv[0].

        The single source of the option order. :meth:`shell_command`
        renders this list, and a Configurator-launched process
        installs it as ``/agent/process/arg:`` instances. A launch
        path that built its own list could drift from the other, and
        the drift would only show up as TRex behaving differently
        under one of them.
        """
        args = ["-i", "--cfg", cfg_path, "-c", str(self.cores)]
        if self.software:
            args.append("--software")
        if self.astf:
            args.append("--astf")
        if self.tso_disable:
            args.append("--tso-disable")
        if self.lro_disable:
            args.append("--lro-disable")
        args.extend(self.so)
        return args

    def shell_command(self, cfg_path: str) -> str:
        """Inner command for ``sh -c`` that runs TRex from its workdir.

        Every interpolated path is shell-quoted: this string is
        executed by ``sh -c``, so a space or metacharacter in the
        install path must not split the command.

        The :meth:`env` exports lead, before the ``cd``: an assignment
        prefix on ``exec`` (a special builtin) has surprising
        persistence semantics, and putting the ``export`` between the
        ``cd`` and the ``exec`` would break the ``&&`` guard --
        ``cd d && export V=x; exec p`` runs ``p`` even when the ``cd``
        failed.
        """
        exports = " ".join(f"export {key}={shlex.quote(value)};"
                           for key, value in self.env().items())
        args = " ".join(shlex.quote(arg) for arg in self.argv(cfg_path))
        return (f"{exports} "
                f"cd {shlex.quote(self.workdir)} && "
                f"exec {shlex.quote(self.trex_exec)} {args}")
