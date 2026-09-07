# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Build-time tests-info.xml generator for Python test suites.

TE's Tester reads a per-package ``tests-info.xml`` when it parses a
package and logs what it finds in the test_start message: the
objective, the parameter descriptions and the declared scenario.  C
suites get that file from ``te/scripts/scenario/tests_info.py``, which
globs ``*.c`` and so has nothing to say about a Python suite.  This is
the Python half, shared by every pyte-based suite (nap-ts, python-ts,
app-perf-ts-py) rather than copied into each of them.

Everything comes out of the test module's source, statically: the
objective and the parameter entries out of the module docstring, the
scenario out of the AST.  A test module is never imported -- its body
runs the test.

The whole package is standard library only, and imports nothing from
the rest of pyte.  It runs from a suite's meson.build under whatever
``python3`` the build host has, with no virtualenv and no compiled
cffi shim, so a single stray ``from pyte import log`` here would break
every suite build.

Command line::

    python3 -m pyte.testsinfo [--strict] <srcdir> <script-name>...
"""
from .check import INDIRECT_READERS, check_params, reads
from .cli import PROG, analyze, main
from .docstring import objective, parameters
from .emit import render_document, render_test
from .packagexml import declarations
from .steps import scenario

__all__ = [
    "INDIRECT_READERS",
    "PROG",
    "analyze",
    "check_params",
    "declarations",
    "main",
    "objective",
    "parameters",
    "reads",
    "render_document",
    "render_test",
    "scenario",
]
