# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.expand: the ${NAME}/${NAME:-default} substitution subset."""
import pytest

from pyte.expand import kvpairs
from pyte.errors import ExpandError


def test_no_references_passes_through():
    assert kvpairs("plain text {} $ ${", {}) == "plain text {} $ ${"


def test_basic_substitution():
    assert kvpairs("a=${A}, b=${B}", {"A": "1", "B": "2"}) == "a=1, b=2"


def test_repeated_reference_expands_every_time():
    assert kvpairs("${X}-${X}-${X}", {"X": "z"}) == "z-z-z"


def test_default_used_when_name_is_absent():
    assert kvpairs("${DUR:-65}", {}) == "65"


def test_default_ignored_when_name_is_present():
    assert kvpairs("${DUR:-65}", {"DUR": "10"}) == "10"


def test_empty_default_substitutes_nothing():
    assert kvpairs("[${X:-}]", {}) == "[]"


def test_strict_unresolved_reference_raises():
    with pytest.raises(ExpandError, match="undefined reference to 'X'"):
        kvpairs("v=${X}", {})


def test_non_strict_unresolved_reference_is_empty():
    assert kvpairs("v=${X}!", {}, strict=False) == "v=!"


def test_non_strict_still_honors_a_default():
    assert kvpairs("v=${X:-d}", {}, strict=False) == "v=d"


def test_filter_reference_is_rejected_in_strict_mode():
    with pytest.raises(ExpandError, match="filters are not supported"):
        kvpairs("${NAME|base64}", {"NAME": "x"})


def test_filter_reference_is_rejected_in_non_strict_mode():
    """A filter must never be silently copied through unexpanded."""
    with pytest.raises(ExpandError, match="filters are not supported"):
        kvpairs("${NAME|base64}", {}, strict=False)


def test_pipe_inside_a_default_is_not_a_filter():
    assert kvpairs("${X:-a|b}", {}) == "a|b"


def test_default_is_literal_no_nested_expansion():
    """Nested references inside a default are out of scope."""
    assert kvpairs("${A:-${B}}", {"B": "2"}) == "${B}"


def test_unknown_syntax_is_left_alone():
    """Neither ${} nor ${a-b} is a supported reference form."""
    assert kvpairs("${} ${a-b}", {}) == "${} ${a-b}"
