# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
from pyte.tools.trex.console import CLEAR, last_screen, screens, strip_ansi


def test_screens_splits_on_clear():
    text = "junk" + CLEAR + "A\n" + CLEAR + "B\n" + CLEAR + "part"
    assert screens(text) == ["A\n", "B\n"]


def test_last_screen_none_without_two_markers():
    assert last_screen("x" + CLEAR + "half") is None
    assert last_screen("") is None


def test_last_screen_is_the_newest_complete_one():
    text = CLEAR + "A" + CLEAR + "B" + CLEAR + "part"
    assert last_screen(text) == "B"


def test_strip_ansi_removes_csi():
    assert strip_ansi("\x1b[1mBold\x1b[0m") == "Bold"


def test_screens_are_stripped_of_ansi():
    assert screens(CLEAR + "\x1b[31mred\x1b[0m\n" + CLEAR) == ["red\n"]
