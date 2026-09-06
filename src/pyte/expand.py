# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""``${NAME}`` template expansion over a key/value mapping.

The Python counterpart of TE's ``te_string_expand_kvpairs()``, used to
fill in the text templates a suite ships next to its tests (TRex ASTF
profiles, config fragments, command lines).

Supported subset -- exactly two constructs:

* ``${NAME}``, a bare reference;
* ``${NAME:-default}``, a reference with an inline default.

``NAME`` is ``[A-Za-z0-9_]+``.  The full TE expander's filters
(``${NAME|filter}``) and list/loop syntax are NOT implemented: a
filter reference is rejected loudly (see :func:`kvpairs`) rather than
copied through unexpanded.  References nested inside a default value
are out of scope too -- a default is taken literally, so
``${A:-${B}}`` expands to the seven characters ``${B}`` (or, when B is
also referenced elsewhere, whatever the single pass over the template
produced there).

Strictness contract: by default an unresolved bare reference is an
error, so a missing substitution surfaces at expansion time instead of
shipping a half-filled template to whatever consumes it.  Pass
``strict=False`` for TE's historical behavior of substituting the
empty string.
"""
from __future__ import annotations

import re
from typing import Mapping

from pyte.errors import ExpandError

#: ``${NAME}`` / ``${NAME:-default}``; group 2 is None without a default.
_REF_RE = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")

#: A filter reference, ``${NAME|...}``.  Matched separately over the
#: whole template because :data:`_REF_RE` simply does not match one,
#: which would otherwise leave it silently unexpanded in the output.
_FILTER_RE = re.compile(r"\$\{[A-Za-z0-9_]+\|")


def kvpairs(template: str, subs: Mapping[str, str], *,
            strict: bool = True) -> str:
    """Substitute ``${NAME}``/``${NAME:-default}`` references.

    :param template: the text to expand.
    :param subs: the substitutions, looked up by reference name.
    :param strict: whether an unresolved bare reference is an error.
    :raises ExpandError: on a filter reference (always), or on an
        unresolved bare ``${NAME}`` when *strict*.
    """
    m = _FILTER_RE.search(template)
    if m:
        raise ExpandError("filters are not supported")

    def repl(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in subs:
            return subs[name]
        if default is not None:
            return default
        if strict:
            raise ExpandError(f"undefined reference to '{name}'")
        return ""

    return _REF_RE.sub(repl, template)
