# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Parameters a package.xml declares for each of its scripts.

The Tester's package.xml is the authority on what parameters a test
actually receives; the test's own source only shows which of them it
has got round to reading.  A C test has no such file to consult -- its
parameters can only be recovered from its TEST_GET_*_PARAM calls, which
is why TE's cparam.py works from reads alone -- but a Python suite has
the declaration sitting in the same directory, so the checker reads it.

That distinction matters for what "stale" means.  A parameter declared
in package.xml and documented but not yet read is not stale
documentation: it is documentation ahead of the code, which is the
right direction.  nap-ts's ts/trex tests document thirteen suricata
knobs whose backend is not written yet, and every one of them is a real
<arg> the Tester passes.  Reads alone would call all thirteen stale.

Scoping rules, from the Tester's own inheritance:

- an <arg> inside a <run> belongs to the scripts of that run, and to
  the scripts of any run nested inside it;
- an <arg> inside a <session> belongs to everything that session runs.
  nap-ts uses this: ts/trex_int/package.xml hoists fw_layer and fw_mode
  to the session rather than repeating them in six run blocks;
- <enum> and <var> declare types and variables, not parameters, and are
  ignored.

Only ``<srcdir>/package.xml`` is read.  A parameter a *parent* package
declares for a whole sub-package is therefore invisible here; that
would need the reader to know where the parent lives, and the CLI takes
a bare directory. The cost is a possible false "undocumented", never a
false "stale", because an unseen declaration only shrinks the union.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

#: The file, in the directory the scripts come from.
NAME = "package.xml"

#: Elements that scope parameters: each may hold <arg> declarations,
#: <script> uses of them, and further scopes.
_SCOPES = ("session", "run", "prologue", "epilogue")


def _walk(node: ET.Element, inherited: frozenset[str],
          out: dict[str, set[str]]) -> None:
    """Attribute this scope's arguments to the scripts it runs."""
    args = {child.get("name") for child in node if child.tag == "arg"}
    args.discard(None)
    here = inherited | args
    for child in node:
        if child.tag == "script" and child.get("name"):
            name = child.get("name")
            out.setdefault(name, set()).update(here)
            # A prologue names its script by path ("../pre_test_prologue")
            # because it lives in the parent package.  Record the bare
            # name too, so a lookup by the name the CLI was given finds
            # it.
            base = os.path.basename(name)
            if base != name:
                out.setdefault(base, set()).update(here)
        elif child.tag in _SCOPES:
            _walk(child, here, out)


def declarations(srcdir: str) -> tuple[dict[str, frozenset[str]],
                                       str | None]:
    """The parameters declared per script name in a package.

    Args:
        srcdir: The directory holding the scripts and their package.xml.

    Returns:
        A mapping from script name (as package.xml spells it, and by
        bare name for a script named by path) to the parameters
        declared for it, and a note explaining an empty mapping when
        the file could not be used.  A missing or malformed package.xml
        is not an error: the caller falls back to checking reads alone,
        which is all a C suite ever had, so the CLI stays usable on a
        directory that is not a package.
    """
    path = os.path.join(srcdir, NAME)
    try:
        root = ET.parse(path).getroot()
    except OSError as exc:
        return {}, f"{path}: {exc.strerror or exc}"
    except ET.ParseError as exc:
        return {}, f"{path}: {exc}"
    out: dict[str, set[str]] = {}
    _walk(root, frozenset(), out)
    return {name: frozenset(args) for name, args in out.items()}, None
