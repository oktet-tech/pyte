# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.ssh — run OpenSSH client (ssh) and server (sshd) via pyte.job.

Pure Python over pyte.job; zero shim imports. ssh/sshd binaries default to
/usr/bin/ssh and /usr/sbin/sshd (overridable via Opts.path).

Pinned mappings (from te/lib/tapi_tool/tapi_ssh.{h,c})
=======================================================

The C `-o X=Y` binds include "-o " in the option prefix and concatenate
the value, so TE emits a SINGLE argv token "-o StrictHostKeyChecking=no"
(one string with an embedded space), NOT two tokens. This wrapper mirrors
that byte-for-byte. The `-o` enum/enum-bool options and `-p` are always
emitted (with their C defaults); plain string options are two tokens and
omitted when None.

Client bind order:
    -i <identity_file>   -l <login_name>
    -o StrictHostKeyChecking=<value>   -o UserKnownHostsFile=<file>
    -g   -N   -L <local_pf>   -R <remote_pf>   -p <port>
    <destination>   <command>

Server bind order:
    -h <host_key_file>   -f <config_file>
    -o AuthorizedKeysFile=<file>   -o PermitRootLogin=<value>
    -o PidFile=<file>   -o PubkeyAuthentication=yes|no
    -o StrictModes=yes|no   -p <port>   -D

tapi_ssh_client_wrapper_add is intentionally NOT ported (pyte.job exposes
no tapi_job_wrapper binding). No MI (the C TAPI emits none).
"""
from __future__ import annotations

import enum
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

_DEFAULT_SSH_PATH = "/usr/bin/ssh"
_DEFAULT_SSHD_PATH = "/usr/sbin/sshd"
_DEFAULT_PORT = 22


class StrictHostKeyChecking(enum.Enum):
    """ssh -o StrictHostKeyChecking values."""
    YES = "yes"
    NO = "no"
    ACCEPT_NEW = "accept-new"


class PermitRootLogin(enum.Enum):
    """sshd -o PermitRootLogin values."""
    YES = "yes"
    NO = "no"
    FORCED_COMMANDS_ONLY = "forced-commands-only"
    PROHIBIT_PASSWORD = "prohibit-password"


def _yesno(val: bool) -> str:
    return "yes" if val else "no"


@dataclass(frozen=True)
class ClientOpts:
    """OpenSSH client (ssh) options (mirror tapi_ssh_client_opt)."""
    path: str = _DEFAULT_SSH_PATH
    identity_file: str | None = None
    login_name: str | None = None
    strict_host_key_checking: StrictHostKeyChecking = StrictHostKeyChecking.NO
    user_known_hosts_file: str | None = None
    gateway_ports: bool = False
    forbid_remote_commands_execution: bool = False
    local_port_forwarding: str | None = None
    remote_port_forwarding: str | None = None
    port: int = _DEFAULT_PORT
    destination: str | None = None
    command: str | None = None

    def client_argv(self) -> list[str]:
        """Build the ssh argument list (without argv[0])."""
        argv: list[str] = []
        if self.identity_file is not None:
            argv += ["-i", self.identity_file]
        if self.login_name is not None:
            argv += ["-l", self.login_name]
        argv.append(
            f"-o StrictHostKeyChecking={self.strict_host_key_checking.value}")
        if self.user_known_hosts_file is not None:
            argv.append(f"-o UserKnownHostsFile={self.user_known_hosts_file}")
        if self.gateway_ports:
            argv.append("-g")
        if self.forbid_remote_commands_execution:
            argv.append("-N")
        if self.local_port_forwarding is not None:
            argv += ["-L", self.local_port_forwarding]
        if self.remote_port_forwarding is not None:
            argv += ["-R", self.remote_port_forwarding]
        argv += ["-p", str(self.port)]
        if self.destination is not None:
            argv.append(self.destination)
        if self.command is not None:
            argv.append(self.command)
        return argv


@dataclass(frozen=True)
class ServerOpts:
    """OpenSSH server (sshd) options (mirror tapi_ssh_server_opt)."""
    path: str = _DEFAULT_SSHD_PATH
    host_key_file: str | None = None
    config_file: str | None = None
    authorized_keys_file: str | None = None
    permit_root_login: PermitRootLogin = PermitRootLogin.YES
    pid_file: str | None = None
    pub_key_authentication: bool = True
    strict_modes: bool = False
    port: int = _DEFAULT_PORT

    def server_argv(self) -> list[str]:
        """Build the sshd argument list (without argv[0]); -D always last."""
        argv: list[str] = []
        if self.host_key_file is not None:
            argv += ["-h", self.host_key_file]
        if self.config_file is not None:
            argv += ["-f", self.config_file]
        if self.authorized_keys_file is not None:
            argv.append(f"-o AuthorizedKeysFile={self.authorized_keys_file}")
        argv.append(f"-o PermitRootLogin={self.permit_root_login.value}")
        if self.pid_file is not None:
            argv.append(f"-o PidFile={self.pid_file}")
        argv.append(
            f"-o PubkeyAuthentication={_yesno(self.pub_key_authentication)}")
        argv.append(f"-o StrictModes={_yesno(self.strict_modes)}")
        argv += ["-p", str(self.port)]
        argv.append("-D")
        return argv


class Ssh:
    """Lifecycle manager for an ssh or sshd job (mirror tapi_ssh_t)."""

    def __init__(self, job):
        self._job = job
        self._closed = False

    def start(self) -> None:
        """Start the ssh/sshd process."""
        self._job.start()

    def wait(self, timeout: float = 3.0):
        """Wait for the process to finish (default 3 s, the C wait time)."""
        return self._job.wait(timeout=timeout)

    def kill(self, signal: int | str = "SIGTERM") -> None:
        """Send a signal to the process."""
        self._job.kill(signal)

    def destroy(self) -> None:
        """Destroy the job (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._job.destroy()


def client(pco: "RpcServer", opts: ClientOpts) -> Ssh:
    """Create (but do not start) an ssh client job."""
    job = pco.job(opts.path, opts.client_argv())
    job.stdout.log(level="RING")
    job.stderr.log(level="ERROR")
    return Ssh(job)


def server(pco: "RpcServer", opts: ServerOpts) -> Ssh:
    """Create (but do not start) an sshd server job."""
    job = pco.job(opts.path, opts.server_argv())
    job.stdout.log(level="RING")
    job.stderr.log(level="ERROR")
    return Ssh(job)


@contextmanager
def run(pco: "RpcServer", opts, *, as_server: bool = False):
    """Context manager: create + start an ssh (or sshd) job, then destroy.

    Pass a :class:`ClientOpts` (default) or a :class:`ServerOpts` with
    ``as_server=True``. Yields the :class:`Ssh` handle.

    Example::

        with ssh.run(pco, ssh.ServerOpts(port=2222), as_server=True) as srv:
            with ssh.run(pco, ssh.ClientOpts(
                    destination="127.0.0.1", port=2222,
                    command="true")) as cli:
                cli.wait(timeout=10.0)
    """
    app = server(pco, opts) if as_server else client(pco, opts)
    try:
        app.start()
        yield app
    finally:
        app.destroy()
