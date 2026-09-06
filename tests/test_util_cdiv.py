# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.util.cdiv: C/IEEE-754 division semantics.

Named test_util_cdiv.py because tests/test_util.py already covers the
internal pyte._util plumbing.
"""
import math

from pyte.util import cdiv


def test_normal_division():
    assert cdiv(6.0, 3.0) == 2.0


def test_negative_division():
    assert cdiv(-6.0, 3.0) == -2.0


def test_zero_over_zero_is_nan():
    assert math.isnan(cdiv(0.0, 0.0))


def test_zero_over_negative_zero_is_nan():
    assert math.isnan(cdiv(0.0, -0.0))


def test_positive_over_zero_is_plus_inf():
    assert cdiv(1.0, 0.0) == math.inf


def test_negative_over_zero_is_minus_inf():
    assert cdiv(-1.0, 0.0) == -math.inf


def test_positive_over_negative_zero_is_minus_inf():
    """The denominator's sign flips the result, as in C."""
    assert cdiv(1.0, -0.0) == -math.inf


def test_negative_over_negative_zero_is_plus_inf():
    assert cdiv(-1.0, -0.0) == math.inf


def test_finite_over_infinite_is_zero():
    assert cdiv(1.0, math.inf) == 0.0


def test_infinite_numerator_over_zero_is_infinite():
    assert cdiv(math.inf, 0.0) == math.inf


def test_infinite_over_infinite_is_nan():
    """Python's own float division already yields nan here."""
    assert math.isnan(cdiv(math.inf, math.inf))


def test_integers_are_accepted():
    assert cdiv(1, 0) == math.inf
