# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.mke2fs unit tests (offline: argv build + journal detect)."""
import itertools
from pathlib import Path

import pytest

from pyte.job import JobStatus, StatusKind
from pyte.tools import _tool, mke2fs  # noqa: F401  (import-smoke check)
from pyte.tools.mke2fs import Mke2fs, Opts, _journal_created

DATA = Path(__file__).parent / "data"

OK = JobStatus(StatusKind.EXITED, 0)


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


# -- wait() timeout convention (A2/A3) ---------------------------------------

class FakeJob:
    def __init__(self, status=OK):
        self.status = status
        self.wait_calls = []

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        return self.status


class FakeFilter:
    def __init__(self, text=""):
        self.text = text
        self.read_calls = []

    def read_all(self, timeout=None):
        self.read_calls.append(timeout)
        return self.text


def _mke2fs(job, flt):
    return Mke2fs(job, Opts(device="/dev/loop0"), flt)


def test_wait_omitted_uses_default_timeout():
    job, flt = FakeJob(), FakeFilter()
    _mke2fs(job, flt).wait()
    assert job.wait_calls == [Mke2fs.default_timeout]


def test_wait_none_blocks_forever_everywhere():
    """A2: timeout=None must mean 'forever' here too, not 'default'."""
    job, flt = FakeJob(), FakeFilter()
    _mke2fs(job, flt).wait(timeout=None)
    assert job.wait_calls == [None]
    assert flt.read_calls == [None]


def test_wait_shares_one_deadline_across_wait_and_read(monkeypatch):
    """A3: a single deadline covers job.wait() and the stdout read --
    the read must get the remaining budget, not the full timeout again."""
    ticks = itertools.chain([0.0, 20.0], itertools.repeat(20.0))
    monkeypatch.setattr(_tool.time, "monotonic", lambda: next(ticks))
    job, flt = FakeJob(), FakeFilter()
    _mke2fs(job, flt).wait(timeout=30.0)
    assert flt.read_calls == [10.0]     # 30 - 20 consumed by job.wait
