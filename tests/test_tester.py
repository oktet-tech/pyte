# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tester unit tests with the shared fake shim (pyte.testing)."""
import pytest

from pyte import tester
from pyte.errors import TeError


def test_modify_reqs_passes_expression(fake_shim):
    tester.modify_reqs("!FIO")
    assert fake_shim.calls == [("reqs", "!FIO")]


def test_add_trc_tag_value_default(fake_shim):
    tester.add_trc_tag("no_fio")
    assert fake_shim.calls == [("tag", "no_fio", "")]


def test_add_trc_tag_with_value(fake_shim):
    tester.add_trc_tag("linux", "6.17")
    assert fake_shim.calls == [("tag", "linux", "6.17")]


def test_errors_surface_as_teerror(fake_shim):
    fake_shim.rc = 0xBEEF
    with pytest.raises(TeError, match="add_trc_tag"):
        tester.add_trc_tag("x")
    with pytest.raises(TeError, match="modify_reqs"):
        tester.modify_reqs("x")
