# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.mke2fs — create an ext2/3/4 filesystem via pyte.job.

Pure Python over pyte.job; zero shim imports. The mke2fs binary is
resolved from the agent's PATH (job program "mke2fs").

Pinned mappings (from te/lib/tapi_tool/tapi_mke2fs.{h,c})
=========================================================

argv (mke2fs_binds; each value flag omitted when unset):
    -b <block_size>   -j   -t <fs_type>   <device>

The device is the mandatory positional argument (last). check_journal()
mirrors tapi_mke2fs_check_journal: when use_journal was requested, the
stdout must contain a "Creating journal .*: done" line, else Mke2fsError
(TE_EPROTO). A non-zero exit from wait() raises Mke2fsError (TE_ESHCMD).
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyte.errors import Mke2fsError
from pyte.tools import _tool

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

#: stdout marker that mke2fs prints when it creates a journal
_JOURNAL_RE = re.compile(r"Creating journal .*: done")


def _journal_created(stdout: str) -> bool:
    """True iff mke2fs stdout reports a created journal."""
    return _JOURNAL_RE.search(stdout) is not None


@dataclass(frozen=True)
class Opts:
    """mke2fs options.

    Parameters
    ----------
    device:
        Block device to format (mandatory; positional, last).
    block_size:
        ``-b`` block size in bytes; None lets mke2fs choose.
    use_journal:
        ``-j`` create an ext3 journal.
    fs_type:
        ``-t`` filesystem type (e.g. ``"ext4"``); None omits the flag.
    """
    device: str
    block_size: int | None = None
    use_journal: bool = False
    fs_type: str | None = None

    def __post_init__(self) -> None:
        if not self.device:
            raise ValueError("Opts.device is required")

    def to_argv(self) -> list[str]:
        """Build the mke2fs argument list (without argv[0])."""
        argv: list[str] = []
        if self.block_size is not None:
            argv += ["-b", str(self.block_size)]
        if self.use_journal:
            argv.append("-j")
        if self.fs_type is not None:
            argv += ["-t", self.fs_type]
        argv.append(self.device)
        return argv


class Mke2fs(_tool.ToolHandle):
    """Lifecycle manager for an mke2fs job.

    There is no report object: wait() raises on a bad exit and stashes
    stdout for a later :meth:`check_journal` (so it overrides the
    base's report-producing wait wholesale).
    """

    tool = "mke2fs"
    error_cls = Mke2fsError
    default_timeout = 60.0

    def __init__(self, job, opts: Opts, stdout_filter):
        super().__init__(job, stdout_filter)
        self._opts = opts
        self._stdout: str | None = None

    def wait(self, timeout: float | None = None) -> None:
        """Wait for mke2fs to finish; raise Mke2fsError on non-zero exit.

        Drains stdout so a later check_journal() can inspect it.
        """
        if timeout is None:
            timeout = self.default_timeout
        status = self._job.wait(timeout=timeout)
        self._stdout = self._stdout_filter.read_all(timeout=timeout)
        if not status.ok:
            self._fail_status(status, self._stdout)

    def check_journal(self) -> None:
        """Mirror tapi_mke2fs_check_journal.

        No-op when use_journal was not requested. Otherwise raise
        Mke2fsError if the stdout has no "Creating journal ...: done"
        line.  Call after wait().
        """
        if not self._opts.use_journal:
            return
        if self._stdout is None:
            raise RuntimeError("call wait() before check_journal()")
        if not _journal_created(self._stdout):
            raise Mke2fsError(
                "filesystem was created without journal even though "
                "it was requested")


@contextmanager
def run(pco: "RpcServer", opts: Opts):
    """Context manager: create, start, and clean up an mke2fs job.

    Yields a :class:`Mke2fs`; call :meth:`Mke2fs.wait` inside the block.

    Example::

        with mke2fs.run(pco, mke2fs.Opts(device="/dev/loop0",
                                         use_journal=True)) as m:
            m.wait(timeout=120.0)
            m.check_journal()
    """
    def _setup(job):
        flt = job.stdout.attach_filter(name="mke2fs_stdout", readable=True)
        job.stderr.log(level="ERROR")
        return flt

    job, flt = _tool.launch(pco, "mke2fs", opts.to_argv(), setup=_setup)
    with _tool.running(Mke2fs(job, opts, flt)) as app:
        yield app


@contextmanager
def do(pco: "RpcServer", opts: Opts, timeout: float = 60.0):
    """Convenience CM mirroring tapi_mke2fs_do (create + start + wait).

    Yields a waited :class:`Mke2fs`; call :meth:`Mke2fs.check_journal`
    inside the block if needed.
    """
    with run(pco, opts) as app:
        app.wait(timeout=timeout)
        yield app
