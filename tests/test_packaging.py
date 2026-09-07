# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""setup.py must ship every package that exists in src/.

An explicit ``packages=[...]`` list silently dropped pyte.cfg,
pyte.cfg.gen and pyte.tools.trex for as long as it existed: the wheel
te-dist installs could not ``import pyte.test`` (seven shipped modules
import pyte.cfg), and the only smoke test on that wheel
(``import pyte._shim``) was the one import that still worked.

These tests read setup.py rather than importing setuptools, so they run
in the TE-free offline suite: the invariant worth pinning is that
setup.py *discovers* packages, not that setuptools can find them.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def _setup_kwargs() -> dict[str, ast.expr]:
    """The keyword arguments of setup.py's setup() call."""
    tree = ast.parse((ROOT / "setup.py").read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "setup"):
            return {kw.arg: kw.value for kw in node.keywords if kw.arg}
    raise AssertionError("setup.py has no setup() call")


def test_setup_py_discovers_instead_of_listing():
    packages = _setup_kwargs().get("packages")
    assert packages is not None, "setup.py declares no packages"
    assert not isinstance(packages, (ast.List, ast.Tuple, ast.Set)), (
        "setup.py hardcodes its package list again; use find_packages() "
        "so a new subpackage cannot be dropped from the wheel"
    )
    assert isinstance(packages, ast.Call)
    assert getattr(packages.func, "id", None) == "find_packages"
    where = {kw.arg: kw.value for kw in packages.keywords}.get("where")
    assert isinstance(where, ast.Constant) and where.value == "src"


def test_setup_py_roots_packages_at_src():
    package_dir = _setup_kwargs().get("package_dir")
    assert isinstance(package_dir, ast.Dict)
    mapping = {k.value: v.value for k, v in
               zip(package_dir.keys, package_dir.values)}
    assert mapping == {"": "src"}


def test_every_source_directory_is_an_importable_package():
    """A dir of .py files without __init__.py is invisible to discovery.

    find_packages() only walks packages, so a new subpackage that forgot
    its __init__.py would be dropped from the wheel exactly the way the
    hardcoded list used to drop pyte.cfg -- silently.
    """
    missing = sorted(
        str(d.relative_to(SRC))
        for d in SRC.rglob("*")
        if d.is_dir()
        and d.name != "__pycache__"
        and any(d.glob("*.py"))
        and not (d / "__init__.py").exists()
    )
    assert not missing, f"directories with .py but no __init__.py: {missing}"


def test_the_subpackages_the_old_list_dropped_still_exist():
    # Regression anchor: these three are what the explicit list omitted.
    for pkg in ("pyte/cfg", "pyte/cfg/gen", "pyte/tools/trex"):
        assert (SRC / pkg / "__init__.py").exists(), f"{pkg} vanished"
