# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.mke2fs unit tests (offline: argv build + journal detect)."""
from pathlib import Path

import pytest

from pyte.tools import mke2fs  # noqa: F401  (import-smoke check)
from pyte.tools.mke2fs import Opts, _journal_created

DATA = Path(__file__).parent / "data"


# -- argv building ----------------------------------------------------------

def test_to_argv_minimal():
    assert Opts(device="/dev/loop0").to_argv() == ["/dev/loop0"]


def test_to_argv_full_order():
    argv = Opts(device="/dev/loop0", block_size=4096,
                use_journal=True, fs_type="ext4").to_argv()
    assert argv == ["-b", "4096", "-j", "-t", "ext4", "/dev/loop0"]


def test_to_argv_omits_unset():
    assert Opts(device="/dev/sda1", fs_type="ext2").to_argv() == \
        ["-t", "ext2", "/dev/sda1"]


def test_device_required():
    with pytest.raises(ValueError, match="device"):
        Opts(device="")


# -- journal detection ------------------------------------------------------

def test_journal_created_true():
    assert _journal_created((DATA / "mke2fs_journal.txt").read_text())


def test_journal_created_false():
    assert not _journal_created((DATA / "mke2fs_nojournal.txt").read_text())
