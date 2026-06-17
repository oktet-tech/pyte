# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.stl unit tests (offline: orchestration with fakes)."""
from pyte.errors import TeError, TrexError


def test_trexerror_message_path():
    e = TrexError("connect failed: no server")
    assert "connect failed" in str(e)
    assert e.rc == 0
    assert isinstance(e, TeError)
