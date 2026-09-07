# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""The te_py_tests_info command line.

    te_py_tests_info [--strict] <srcdir> <script-name>...

reads ``<srcdir>/<name>.py`` for each name and writes one
``<tests-info>`` document to stdout.  It runs from a suite's
meson.build at build time, under a bare ``python3``: no virtualenv, no
compiled shim, nothing installed.  That is why this package imports
only the standard library, and why nothing here reaches into the rest
of pyte.

``<srcdir>/package.xml`` is read once, for the parameters the Tester
declares; without it the parameter checks narrow to what the source
reads.  Either way the document itself is unaffected -- the
declarations inform the findings, never the output.

Two severities, deliberately far apart:

Hard errors -- a missing module docstring, a syntax error, a file that
will not open -- suppress the document entirely and exit non-zero.
There is nothing to say about a test whose source does not parse, and a
truncated tests-info is worse than none.

Findings -- undocumented or stale parameters, a step whose text is not
a literal -- go to stderr and the document is still written.  They exit
zero unless ``--strict`` is given.  This is the same transitional split
TE's own ``scenario check`` makes: python-ts has about fifty test
scripts with no parameter documentation at all, and the day this lands
must not be the day its build stops working.  A suite tightens by
passing ``--strict`` once it is clean.
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

from . import check as _check
from . import docstring as _docstring
from . import emit as _emit
from . import packagexml as _packagexml
from . import steps as _steps

#: The name findings and errors are reported under, so a build log
#: reads the same whichever suite the message came from.
PROG = "te_py_tests_info"


def analyze(path: str, declared: frozenset[str] = frozenset()
            ) -> tuple[str, list[tuple[str, str]],
                       list[tuple[int, str]], list[str]]:
    """Everything the document needs about one test module.

    The module is parsed, never imported: a test module runs its whole
    body at import time, against a rig that is not there at build time.

    Args:
        path: The test module's path.
        declared: The parameters the package declares for this script.
            Empty reduces the parameter checks to reads alone.

    Returns:
        The objective, the (name, description) parameter entries, the
        (depth, text) scenario steps, and the findings.

    Raises:
        OSError: The file could not be read.
        SyntaxError: The file is not valid Python.
        ValueError: The module has no docstring, so no objective.
    """
    with open(path, encoding="utf-8") as source:
        tree = ast.parse(source.read(), filename=path)
    doc = ast.get_docstring(tree, clean=True)
    if doc is None:
        raise ValueError("missing module docstring (test objective)")
    objective = _docstring.objective(doc)
    if not objective:
        raise ValueError("missing module docstring (test objective)")
    params, findings = _docstring.parameters(doc)
    scenario, step_findings = _steps.scenario(tree)
    findings += _check.check_params(tree, params, declared)
    findings += step_findings
    return objective, params, scenario, findings


def _parser() -> argparse.ArgumentParser:
    """The command line, kept as the suites' meson.build calls it."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Generate a TE tests-info.xml from Python test "
                    "modules.")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero when there are findings; "
                             "the document is written either way")
    parser.add_argument("srcdir",
                        help="directory holding the test modules")
    parser.add_argument("names", metavar="script-name", nargs="+",
                        help="test module name, without the .py suffix")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Write the tests-info document for one package.

    Args:
        argv: The arguments after the program name; sys.argv when None.

    Returns:
        The exit status: non-zero for a hard error, or for a finding
        under --strict.
    """
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)

    # Once per package, not once per script.  A note rather than a
    # finding: a directory that is not a Tester package is a legitimate
    # thing to run this on, and the checks simply narrow to the reads.
    declared, note = _packagexml.declarations(args.srcdir)
    if note is not None:
        print(f"{PROG}: {note}: checking documented parameters against "
              f"the source reads alone", file=sys.stderr)

    blocks: list[str] = []
    findings: list[str] = []
    errors: list[str] = []
    for name in args.names:
        path = os.path.join(args.srcdir, name + ".py")
        try:
            objective, params, scenario, found = analyze(
                path, declared.get(name, frozenset()))
        except OSError as exc:
            errors.append(f"{path}: {exc.strerror or exc}")
            continue
        except SyntaxError as exc:
            errors.append(f"{path}: syntax error: {exc}")
            continue
        except ValueError as exc:
            errors.append(f"{path}: {exc}")
            continue
        findings += [f"{path}: {message}" for message in found]
        blocks.append(_emit.render_test(name, objective, params, scenario))

    for message in findings + errors:
        print(f"{PROG}: {message}", file=sys.stderr)
    if errors:
        return 1
    sys.stdout.write(_emit.render_document(blocks))
    return 1 if findings and args.strict else 0
