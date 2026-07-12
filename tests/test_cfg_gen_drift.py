# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Drift gate: checked-in generated modules must match the live CM.

Skipped when the TE CM source is not reachable (e.g. CI without the te
checkout).
"""
from pathlib import Path

import pytest

from pyte.cfg import _gen

try:
    _CM = _gen.cm_dir()
except FileNotFoundError:
    _CM = None

pytestmark = pytest.mark.skipif(_CM is None, reason="TE CM source absent")

_GEN_DIR = Path(_gen.__file__).resolve().parent / "gen"


@pytest.mark.parametrize("target", _gen.TARGETS, ids=lambda t: t.module)
def test_generated_module_matches_cm(target):
    fresh = _gen.generate([target])[target.module]
    on_disk = (_GEN_DIR / f"{target.module}.py").read_text()
    assert fresh == on_disk, (
        f"{target.module}.py is stale; rerun "
        f"`uv run python -m pyte.cfg._gen`")


def test_generated_subtrees_have_no_hard_lint_errors():
    # The collection-probe ("looks like a collection") is advisory: some
    # CM singletons carry value/parent prose in their d: Name line and
    # are intentionally left as singletons.  Only the HARD signals
    # (invalid name token, integer typo) must be clean for the generated
    # subset.
    hard = []
    for target in _gen.TARGETS:
        text = (_CM / target.cm_file).read_text()
        entries = [e for e in _gen.parse_cm_raw(text)
                   if e.oid.startswith(target.root_oid)]
        hard += [w for w in _gen.lint(entries)
                 if "invalid name" in w or "typo" in w]
    assert hard == [], hard


@pytest.mark.parametrize("mod", ["agent", "interface", "module", "pci",
                                 "sys"])
def test_generated_modules_import(mod):
    """Import smoke for every checked-in generated module (module/pci
    had 0% coverage: nothing ever imported them)."""
    import importlib
    m = importlib.import_module(f"pyte.cfg.gen.{mod}")
    assert m.__name__.endswith(mod)
