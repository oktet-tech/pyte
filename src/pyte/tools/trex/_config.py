# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TRex server options: platform cfg-YAML and the launch command.

Pure (no shim/TE imports) so it is unit-testable offline. The YAML shape
mirrors the C tapi_trex generated config (port_limit/version/interfaces/
port_info). The launch command derives the working directory from
dirname(trex_exec) — TRex must run from its install dir — matching the C
TAPI's tapi_job_set_workdir(dirname) behaviour.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServerOpts:
    """Options to launch ``t-rex-64 -i`` (interactive STL) on an agent."""

    #: Absolute path to the TRex binary (e.g. /usr/local/trex/t-rex-64).
    trex_exec: str
    #: DPDK PCI addresses or interface names, in TRex port order.
    ports: list[str] = field(default_factory=list)
    #: Hardware threads per port pair (TRex -c).
    cores: int = 1
    #: ZMQ sync RPC port the client connects to (loopback).
    sync_port: int = 4501
    #: ZMQ async stats port the client subscribes to (loopback).
    async_port: int = 4500
    #: Optional per-port (ip, default_gw) pairs; same order as ports.
    port_info: list[tuple[str, str]] | None = None

    def __post_init__(self) -> None:
        if not self.trex_exec:
            raise ValueError("trex_exec is required")
        if not self.ports:
            raise ValueError("at least one port is required")
        if self.port_info is not None and len(self.port_info) != len(self.ports):
            raise ValueError("port_info length must match ports length")

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
        if self.port_info is not None:
            out.append("  port_info:")
            for ip, gw in self.port_info:
                out.append(f"    - ip: {ip}")
                out.append(f"      default_gw: {gw}")
        return "\n".join(out) + "\n"

    def shell_command(self, cfg_path: str) -> str:
        """Inner command for ``sh -c`` that runs TRex from its workdir."""
        return (f"cd {self.workdir} && exec {self.trex_exec} "
                f"-i --cfg {cfg_path} -c {self.cores}")
