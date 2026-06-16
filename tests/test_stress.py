# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.stress unit tests (offline: argv build + validation)."""
import pytest

from pyte.tools import stress  # noqa: F401  (import-smoke check)
from pyte.tools.stress import Opts


def test_to_argv_full_order():
    argv = Opts(cpu=2, io=1, vm=3, timeout=5).to_argv()
    assert argv == ["--cpu", "2", "--io", "1", "--vm", "3", "--timeout", "5"]


def test_to_argv_omits_unset():
    assert Opts(cpu=1).to_argv() == ["--cpu", "1"]
    assert Opts(io=4, timeout=10).to_argv() == ["--io", "4", "--timeout", "10"]


def test_requires_at_least_one_target():
    with pytest.raises(ValueError, match="cpu/io/vm"):
        Opts(timeout=5)
    with pytest.raises(ValueError, match="cpu/io/vm"):
        Opts()
