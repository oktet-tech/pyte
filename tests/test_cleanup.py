# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte._cleanup: attempt every action, never eat the real error."""
import pytest

from pyte._cleanup import cleanup_all


def _raiser(exc):
    def go():
        raise exc
    return go


def test_runs_every_action_even_when_one_raises():
    done = []
    with pytest.raises(ValueError):
        cleanup_all(lambda: done.append(1),
                    _raiser(ValueError("boom")),
                    lambda: done.append(3))
    assert done == [1, 3]


def test_with_no_primary_raises_the_first_failure():
    first, second = ValueError("first"), ValueError("second")
    with pytest.raises(ValueError) as info:
        cleanup_all(_raiser(first), _raiser(second))
    assert info.value is first
    assert info.value.cleanup_errors == (second,)


def test_primary_exception_is_preserved_exactly():
    primary = RuntimeError("the real failure")
    failure = ValueError("teardown also broke")
    cleanup_all(_raiser(failure), primary=primary)
    assert primary.cleanup_errors == (failure,)
    assert str(primary) == "the real failure"


def test_primary_is_not_raised_by_the_helper():
    # Returns normally: the caller re-raises the primary itself.
    cleanup_all(_raiser(ValueError("x")), primary=RuntimeError("real"))


def test_cleanup_failures_are_noted_on_the_primary():
    primary = RuntimeError("real")
    cleanup_all(_raiser(ValueError("noted")), primary=primary)
    assert any("noted" in n for n in getattr(primary, "__notes__", []))


def test_base_exception_during_cleanup_does_not_skip_the_rest():
    done = []
    primary = RuntimeError("real")
    cleanup_all(_raiser(KeyboardInterrupt()),
                lambda: done.append("still ran"),
                primary=primary)
    assert done == ["still ran"]
    assert isinstance(primary.cleanup_errors[0], KeyboardInterrupt)


def test_no_failures_leaves_the_primary_untouched():
    primary = RuntimeError("real")
    cleanup_all(lambda: None, primary=primary)
    assert not hasattr(primary, "cleanup_errors")


def test_no_failures_and_no_primary_is_a_no_op():
    cleanup_all(lambda: None, lambda: None)


def test_repeated_calls_accumulate_onto_one_primary():
    """A teardown may run several cleanup_all passes against the same
    primary -- cfg.borrowed_rsrc does, one for the release and one for
    the restore.  Assigning rather than accumulating dropped the
    earlier failures from the tuple while leaving them in the notes."""
    primary = RuntimeError("the real failure")
    first, second = ValueError("release failed"), ValueError("restore failed")
    cleanup_all(_raiser(first), primary=primary)
    cleanup_all(_raiser(second), primary=primary)
    assert primary.cleanup_errors == (first, second)
    assert len(primary.__notes__) == 2
    assert str(primary) == "the real failure"
