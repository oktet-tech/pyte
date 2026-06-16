# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.ssh unit tests (offline: client/server argv build)."""
from pyte.tools import ssh  # noqa: F401  (import-smoke check)
from pyte.tools.ssh import (
    ClientOpts, PermitRootLogin, ServerOpts, StrictHostKeyChecking,
)


# -- client argv ------------------------------------------------------------

def test_client_argv_minimal():
    # enum StrictHostKeyChecking and -p are always emitted (C defaults).
    assert ClientOpts(destination="user@host").client_argv() == [
        "-o StrictHostKeyChecking=no", "-p", "22", "user@host",
    ]


def test_client_argv_no_destination():
    assert ClientOpts().client_argv() == [
        "-o StrictHostKeyChecking=no", "-p", "22",
    ]


def test_client_argv_full_order():
    argv = ClientOpts(
        identity_file="/k", login_name="u",
        strict_host_key_checking=StrictHostKeyChecking.ACCEPT_NEW,
        user_known_hosts_file="/kh", gateway_ports=True,
        forbid_remote_commands_execution=True,
        local_port_forwarding="8080:localhost:80",
        remote_port_forwarding="9090:localhost:90",
        port=2222, destination="h", command="uptime",
    ).client_argv()
    assert argv == [
        "-i", "/k", "-l", "u",
        "-o StrictHostKeyChecking=accept-new",
        "-o UserKnownHostsFile=/kh",
        "-g", "-N",
        "-L", "8080:localhost:80",
        "-R", "9090:localhost:90",
        "-p", "2222", "h", "uptime",
    ]


def test_client_strict_host_key_checking_values():
    def shkc(v):
        return ClientOpts(strict_host_key_checking=v,
                          destination="h").client_argv()[0]
    assert shkc(StrictHostKeyChecking.YES) == "-o StrictHostKeyChecking=yes"
    assert shkc(StrictHostKeyChecking.NO) == "-o StrictHostKeyChecking=no"
    assert shkc(StrictHostKeyChecking.ACCEPT_NEW) == \
        "-o StrictHostKeyChecking=accept-new"


# -- server argv ------------------------------------------------------------

def test_server_argv_default():
    assert ServerOpts().server_argv() == [
        "-o PermitRootLogin=yes",
        "-o PubkeyAuthentication=yes",
        "-o StrictModes=no",
        "-p", "22", "-D",
    ]


def test_server_argv_full_order():
    argv = ServerOpts(
        host_key_file="/hk", config_file="/cfg",
        authorized_keys_file="/ak",
        permit_root_login=PermitRootLogin.PROHIBIT_PASSWORD,
        pid_file="/pid", pub_key_authentication=False,
        strict_modes=True, port=2222,
    ).server_argv()
    assert argv == [
        "-h", "/hk", "-f", "/cfg",
        "-o AuthorizedKeysFile=/ak",
        "-o PermitRootLogin=prohibit-password",
        "-o PidFile=/pid",
        "-o PubkeyAuthentication=no",
        "-o StrictModes=yes",
        "-p", "2222", "-D",
    ]


def test_server_permit_root_login_values():
    def prl(v):
        return ServerOpts(permit_root_login=v).server_argv()[0]
    assert prl(PermitRootLogin.YES) == "-o PermitRootLogin=yes"
    assert prl(PermitRootLogin.NO) == "-o PermitRootLogin=no"
    assert prl(PermitRootLogin.FORCED_COMMANDS_ONLY) == \
        "-o PermitRootLogin=forced-commands-only"
    assert prl(PermitRootLogin.PROHIBIT_PASSWORD) == \
        "-o PermitRootLogin=prohibit-password"
