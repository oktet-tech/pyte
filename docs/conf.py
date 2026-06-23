# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Sphinx configuration for the pyte documentation.

Imports the pure-Python source under ../src directly and mocks the cffi
shim, so the docs build needs neither a built TE nor a compiled pyte.
"""
import os
import sys
import tomllib

sys.path.insert(0, os.path.abspath("../src"))

with open(os.path.join(os.path.dirname(__file__), "..", "pyproject.toml"),
          "rb") as _f:
    _version = tomllib.load(_f)["project"]["version"]

project = "pyte"
author = "OKTET Labs"
copyright = "2026, OKTET Labs"
release = _version

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]

autosummary_generate = True
autodoc_mock_imports = ["pyte._shim"]
autodoc_default_options = {"members": True, "undoc-members": True}

myst_enable_extensions = ["colon_fence", "deflist"]

exclude_patterns = ["_build", "superpowers/**", "Thumbs.db", ".DS_Store"]

html_theme = "furo"

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}
