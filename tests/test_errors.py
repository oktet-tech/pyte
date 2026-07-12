# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.errors unit tests: ToolError base + errno surface."""
import pytest

from pyte import errors
from pyte.errors import (EnvError, EthtoolError, FioError, IperfError,
                         MemaslapError, MemcachedError, MemtierError,
                         Mke2fsError, NetperfError, NptcpError, PingError,
                         SfntError, SshError, TeError, ToolError, TrcError,
                         TrexError, WrkError)

TOOL_ERRORS = [FioError, PingError, IperfError, TrexError, WrkError,
               NetperfError, SfntError, NptcpError, MemcachedError,
               MemaslapError, MemtierError, Mke2fsError, EthtoolError,
               SshError]


# -- ToolError: one dual-path constructor, 14 docstring-only subclasses --

def test_tool_error_message_path():
    e = ToolError("bad output")
    assert str(e) == "bad output"
    assert e.rc == 0 and e.module == 0 and e.code == 0


def test_tool_error_message_path_uses_where():
    """The string path must not silently drop the where context."""
    e = ToolError("bad output", "fio.wait()")
    assert str(e) == "fio.wait(): bad output"


def test_tool_error_rc_path_delegates_to_te_error():
    e = ToolError(12, "somewhere")
    assert e.rc == 12
    assert "somewhere" in str(e)


@pytest.mark.parametrize("cls", TOOL_ERRORS)
def test_every_tool_error_subclasses_tool_error(cls):
    assert issubclass(cls, ToolError)
    assert issubclass(cls, TeError)
    # the dual path works through the shared base
    e = cls("boom")
    assert str(e) == "boom" and e.rc == 0


def test_catching_any_tool_failure():
    with pytest.raises(ToolError):
        raise FioError("fio died")


def test_trc_and_env_are_not_tool_errors():
    """TRC/env share the constructor mechanism, not the semantics:
    'except ToolError' must not swallow TE-subsystem failures."""
    assert not issubclass(TrcError, ToolError)
    assert not issubclass(EnvError, ToolError)
    # but the dual path still works for them
    assert TrcError("msg").rc == 0
    assert EnvError("msg").rc == 0


# -- errno surface: every shim PYTE_E* constant, not a hand-picked set --

def test_known_errnos_still_exposed():
    assert isinstance(errors.ECONNREFUSED, int)
    assert isinstance(errors.ENOENT, int)


def test_shim_errnos_beyond_the_old_allowlist():
    """ETIMEDOUT exists in the shim but was not in the hardcoded set."""
    assert isinstance(errors.ETIMEDOUT, int)
    assert isinstance(errors.EINPROGRESS, int)


def test_unknown_errno_raises_attribute_error():
    with pytest.raises(AttributeError):
        errors.ENOSUCHERRNO_XYZ


def test_dir_lists_errnos():
    listing = dir(errors)
    assert "ETIMEDOUT" in listing
    assert "ToolError" in listing
