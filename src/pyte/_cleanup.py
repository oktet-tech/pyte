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
    """Record *failures* on *exc* without altering its message.

    Accumulates: a teardown can run more than one cleanup_all against
    the same primary exception (cfg.borrowed_rsrc does, once for the
    resource release and once for the owner restore), and assigning
    here would silently drop the earlier failures from the tuple while
    leaving them in the notes.
    """
    existing = getattr(exc, "cleanup_errors", ())
    exc.cleanup_errors = existing + tuple(failures)
    for f in failures:
        exc.add_note(f"cleanup also failed: {f!r}")


def cleanup_all(*actions: Callable[[], object],
                primary: BaseException | None = None) -> None:
    """Run every action; never let a cleanup replace the real error.

    With *primary* given (the exception being unwound) this returns
    normally -- the caller re-raises *primary* itself -- and teardown
    failures are attached to it as a ``cleanup_errors`` tuple and
    exception notes. Failures accumulate across multiple calls to
    cleanup_all on the same primary exception.

    With no *primary*, the first failure is raised carrying the rest
    the same way.

    A ``KeyboardInterrupt``/``SystemExit`` raised by an action is not
    special-cased: with *primary* given it is recorded in
    ``cleanup_errors`` like any other failure and NOT re-raised (the
    caller re-raises *primary* itself, as documented above) -- this is
    deliberate, not an oversight, so a Ctrl-C in one teardown action
    does not abort the rest of the actions or replace the real error.
    With no *primary* it is raised the same way a first failure always
    is.

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
