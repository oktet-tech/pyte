# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Doxygen input filter for Python test modules.

    python3 -m pyte.testsinfo.dox --group ID --ingroup ID [--author TEXT] PATH

prints the doxygen header comment a C test would carry, built from the
Python test module at PATH, so a suite's doxygen run documents its
Python tests the way TE's ``scripts/scenario/doxfilter.py`` documents C
ones: ``@defgroup``/``@ingroup``, the objective, the description, one
``@param`` per documented parameter, the scenario as a nested list
after ``@par Scenario:``, then the ``@author`` block, and the
group-closing ``/** @} */``.  Doxygen is told to parse the output as C.

The pieces are the ones the tests-info generator logs: the objective
and the scenario come from ``cli.analyze``, the description and the
parameters from the docstring with the author's line breaks kept.  The
module is parsed, never imported -- importing a test runs it.

Doxygen ignores a filter's exit status and documents whatever it
printed, so a module that cannot be documented is a warning on stderr
and empty output, never a traceback.

The group ids are the caller's: the suite knows its package layout,
this module does not.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys

from . import cli as _cli
from . import docstring as _docstring

#: The name warnings are reported under: the suites run this through a
#: ``scripts/py2dox`` wrapper, and the build log names it so.
PROG = "py2dox"

#: A markdown code span: a run of backticks up to the next run of the
#: same length.  Doxygen shows its content literally.
_CODE = re.compile(r"(`+).*?\1", re.DOTALL)

#: Characters doxygen reads as markup in comment text: a command
#: (``@b`` in an e-mail address), an HTML tag or entity (``<i>`` in
#: ``<argument>.<i>`` turns the rest of the page italic), a link
#: request or a link suppressor.  A docstring is plain text, so each
#: gets doxygen's backslash escape.
_SPECIAL = re.compile(r"[\\@&<>#%]")

#: A run of two or three dashes, which doxygen prints as an en or an em
#: dash: ``--<option>`` would read as a one-dash option.  Each dash of
#: it gets the backslash escape.  Longer runs are left alone, as they
#: are markdown rules and table separators.
_DASHES = re.compile(r"(?<!-)-{2,3}(?!-)")

#: Where a ``/`` and a ``*`` touch.  The output is a C comment, so
#: ``*/`` in a docstring (a sysfs glob, say) would close it early and
#: ``/*`` opens a nested one doxygen warns about.  Neither has an
#: escape that doxygen renders back, in a code span or out of one.
_COMMENT_TOKEN = re.compile(r"(?<=/)(?=\*)|(?<=\*)(?=/)")


def _uncomment(text: str) -> str:
    """Text that cannot open or close the C comment it goes into.

    A space goes between the ``/`` and the ``*``: visible, but the
    only spelling that survives doxygen everywhere.
    """
    return _COMMENT_TOKEN.sub(" ", text)


def _literal(text: str) -> str:
    """Prose made literal for doxygen: markup characters, dash runs."""
    text = _SPECIAL.sub(r"\\\g<0>", text)
    return _DASHES.sub(lambda match: "\\-" * len(match.group(0)), text)


def _escape(text: str) -> str:
    """Docstring text made literal for doxygen, code spans left alone."""
    out: list[str] = []
    pos = 0
    for match in _CODE.finditer(text):
        out.append(_literal(text[pos:match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(_literal(text[pos:]))
    return _uncomment("".join(out))


def _comment(lines: list[str], prefix: str = " * ") -> list[str]:
    """Lines inside the comment; a blank one is a bare ``" *"``."""
    return [prefix + line if line else " *" for line in lines]


def render_params(params: list[tuple[str, str]]) -> list[str]:
    """``@param`` lines, continuation-indented as doxfilter does.

    Names are padded to the widest one, and every further line of a
    description sits under the text column.  A blank line would end
    the ``@param`` paragraph and spill the rest of the description into
    the page body, so a description holding one is wrapped in
    ``@parblock``/``@endparblock``.  An empty description is a bare
    ``@param name``: a parblock around nothing makes doxygen read the
    ``@endparblock`` as code and warn that it is missing.

    Args:
        params: The (name, description) entries, descriptions already
            escaped.

    Returns:
        The comment lines.
    """
    width = max(len(name) for name, _ in params)
    cont = " * " + " " * (len("@param ") + width + 1)
    out: list[str] = []
    for name, text in params:
        lines = text.split("\n")
        if len(lines) > 1 and "" in lines:
            lines = ["@parblock", *lines, "@endparblock"]
        first, *rest = lines
        out.append(f" * @param {name:<{width}} {first}".rstrip())
        out.extend(_comment(rest, cont))
    return out


def render_scenario(steps: list[tuple[int, str]]) -> list[str]:
    """The scenario as a doxygen list, nesting by indentation.

    Depth 1 is numbered (``-#``), deeper steps are bullets, three
    spaces per level, as doxfilter's ``render_dox`` does.

    Args:
        steps: The (depth, text) steps, depth starting at 1, texts
            already escaped.

    Returns:
        The comment lines.
    """
    return [" * " + "   " * depth + ("-# " if depth == 1 else "- ") + text
            for depth, text in steps]


def render(group: str, ingroup: str, title: str, objective: str,
           description: str, params: list[tuple[str, str]],
           steps: list[tuple[int, str]], author: str | None) -> str:
    """The doxygen comment for one test.

    Args:
        group: The ``@defgroup`` id of the test's page.
        ingroup: The id of the package group it belongs to.
        title: The page title.  Doxygen does not parse a group title
            for markup, so it goes out as given, but for a ``/*`` or
            ``*/`` in it.
        objective: The one-line objective.
        description: The description paragraphs, '' for none.
        params: The (name, description) parameter entries.
        steps: The (depth, text) scenario steps.
        author: The ``@author`` text, doxygen markup as a C header
            writes it (``Name <address>`` becomes a mailto link), or
            None for no author block.  Only ``/*`` and ``*/`` are
            broken up in it.

    Returns:
        The comment and the group-closing comment, newline-terminated.
        Everything else that came from the docstring or the steps is
        escaped for doxygen.
    """
    out = [
        f"/** @defgroup {group} {_uncomment(title)}",
        f" * @ingroup {ingroup}",
        " * @{",
        " *",
        f" * @objective {_escape(objective)}",
    ]
    if description:
        out.append(" *")
        out.extend(_comment(_escape(description).split("\n")))
    if params:
        out.append(" *")
        out.extend(render_params(
            [(name, _escape(text)) for name, text in params]))
    if steps:
        out.append(" *")
        out.append(" * @par Scenario:")
        out.extend(render_scenario(
            [(depth, _escape(text)) for depth, text in steps]))
    if author:
        out.append(" *")
        out.append(f" * @author {_uncomment(author)}")
    out.extend([" */", "", "/** @} */"])
    return "\n".join(out) + "\n"


def document(path: str, group: str, ingroup: str,
             author: str | None = None) -> str:
    """The doxygen comment for the test module at a path.

    Args:
        path: The test module.
        group: The ``@defgroup`` id of its page.
        ingroup: The id of the package group it belongs to.
        author: The ``@author`` text, or None.

    Returns:
        The rendered comment; the objective is the page title too.

    Raises:
        OSError: The file could not be read.
        SyntaxError: The file is not valid Python.
        ValueError: The module has no docstring, so no objective.
    """
    objective, _, steps, _ = _cli.analyze(path)
    # analyze() has read and parsed it once already, so this succeeds.
    with open(path, encoding="utf-8") as source:
        doc = ast.get_docstring(ast.parse(source.read(), filename=path),
                                clean=True) or ""
    return render(group, ingroup, objective, objective,
                  _docstring.description(doc),
                  _docstring.parameters_raw(doc), steps, author)


def _parser() -> argparse.ArgumentParser:
    """The command line the suites' doxygen wrapper calls."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Print the doxygen header comment of a Python "
                    "test module.")
    parser.add_argument("--group", required=True,
                        help="@defgroup id of the test's page")
    parser.add_argument("--ingroup", required=True,
                        help="id of the package group it belongs to")
    parser.add_argument("--author",
                        help="@author text, e.g. 'Name <address>'")
    parser.add_argument("path", help="the test module")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Print the comment for one test module.

    Args:
        argv: The arguments after the program name; sys.argv when None.

    Returns:
        0, also when the module cannot be documented: the reason goes
        to stderr as a warning and nothing is printed, so doxygen sees
        an empty file rather than a failed filter.
    """
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        text = document(args.path, args.group, args.ingroup, args.author)
    except OSError as exc:
        reason = exc.strerror or str(exc)
    except SyntaxError as exc:
        reason = f"syntax error: {exc}"
    except ValueError as exc:
        reason = str(exc)
    else:
        sys.stdout.write(text)
        return 0
    print(f"{PROG}: warning: {args.path}: {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
