# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Parsing of the TRex server's console output.

The interactive TRex redraws a table on its stdout every second, each
time after a clear-screen sequence. Logged as it arrives, that floods
the test log; kept in a file (see ``start_server``), it can be read
back as whole screens and one of them logged now and then.
"""

from __future__ import annotations

import re

#: What TRex writes before each redraw: clear screen, cursor home.
CLEAR = "\x1b[2J\x1b[2H"

_CSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    """Remove CSI escape sequences (colors, cursor moves) from text."""
    return _CSI.sub("", text)


def screens(text: str) -> list[str]:
    """Complete screens in ``text``, ANSI stripped.

    A screen is the text between two :data:`CLEAR` markers. What comes
    before the first marker and after the last one is not a screen:
    the first is the tail of something older, the second is still
    being written.
    """
    parts = text.split(CLEAR)
    return [strip_ansi(part) for part in parts[1:-1]]


def last_screen(text: str) -> str | None:
    """The newest complete screen in ``text``, or None."""
    found = screens(text)
    return found[-1] if found else None
