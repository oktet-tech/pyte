# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""One cleanup policy for every teardown path in pyte.

A bare ``finally: resource.close()`` has two bugs pyte hit in nine
places: a raising cleanup REPLACES the exception being unwound (so the
failure a user needs to see is lost and a teardown detail takes its
place), and the first failing cleanup skips every later one (so a
half-torn-down environment leaks the rest).

:func:`cleanup_all` attempts every action, keeps the primary exception
byte-for-byte, and attaches what went wrong during teardown to it.
"""
from __future__ import annotations

from typing import Callable


def _attach(exc: BaseException, failures: list[BaseException]) -> None:
    """Record *failures* on *exc* without altering its message."""
    exc.cleanup_errors = tuple(failures)
    for f in failures:
        exc.add_note(f"cleanup also failed: {f!r}")


def cleanup_all(*actions: Callable[[], object],
                primary: BaseException | None = None) -> None:
    """Run every action; never let a cleanup replace the real error.

    With *primary* given (the exception being unwound) this returns
    normally -- the caller re-raises *primary* itself -- and teardown
    failures are attached to it as a ``cleanup_errors`` tuple and
    exception notes.

    With no *primary*, the first failure is raised carrying the rest
    the same way.

    Catches BaseException: an interrupt arriving mid-teardown must not
    skip the cleanups that have not run yet.
    """
    failures: list[BaseException] = []
    for action in actions:
        try:
            action()
        except BaseException as exc:  # noqa: BLE001  see docstring
            failures.append(exc)
    if not failures:
        return
    if primary is not None:
        _attach(primary, failures)
        return
    first, rest = failures[0], failures[1:]
    if rest:
        _attach(first, rest)
    raise first
