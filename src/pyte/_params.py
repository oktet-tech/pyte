# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Test parameter parsing: argv entries of the form name=value."""
from __future__ import annotations

import os

_VAR_PREFIX = "VAR."
_ENV_PREFIX = "TE_TEST_VAR_"


def _resolve_var(value: str) -> str:
    """Resolve a tester global-variable reference.

    TE's Tester passes global-var references as ``VAR.<varname>``
    (see ``TEST_ARG_VAR_PREFIX`` in te_param.h).  The actual value
    is stored in the process environment under the name produced by
    ``te_var_name2env()``: strip the ``VAR.`` prefix, replace every
    ``.`` with ``__``, prepend ``TE_TEST_VAR_``.

    Example: ``VAR.env.iut_only`` → ``TE_TEST_VAR_env__iut_only``.

    Raises:
        ValueError: if the variable is not found in the environment.
    """
    if not value.startswith(_VAR_PREFIX):
        return value
    inner = value[len(_VAR_PREFIX):]
    env_name = _ENV_PREFIX + inner.replace(".", "__")
    resolved = os.environ.get(env_name)
    if resolved is None:
        raise ValueError(
            f"tester variable {value!r} not found in environment "
            f"(looked for {env_name!r})")
    return resolved


def parse_argv(argv: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for arg in argv:
        name, sep, value = arg.partition("=")
        if not sep:
            raise ValueError(f"malformed test parameter {arg!r}")
        # First occurrence wins, matching TE's C test_find_param behaviour.
        # Resolve global variable references (VAR.<name>) via the environment.
        name = name.strip()
        if name not in params:
            params[name] = _resolve_var(value)
    return params


class Params:
    """Typed access to test parameters.

    Note: the methods int(), float(), and bool() intentionally shadow the
    built-in types of the same name — this is deliberate for a fluent API
    (``p.int("n")`` reads naturally).  Code inside this class that needs
    the real built-in must use ``builtins.int`` / ``builtins.float`` /
    ``builtins.bool``, or quote the type in annotations
    (e.g. ``"int"`` rather than ``int``).
    """

    _TRUE = {"true", "yes", "1", "on"}
    _FALSE = {"false", "no", "0", "off"}

    def __init__(self, raw: dict[str, str]):
        self._raw = raw

    def __getitem__(self, name: str) -> str:
        try:
            return self._raw[name]
        except KeyError:
            raise KeyError(f"test has no parameter {name!r}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._raw

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._raw.get(name, default)

    def int(self, name: str) -> int:
        return int(self[name], 0)

    def float(self, name: str) -> float:
        return float(self[name])

    def bool(self, name: str) -> bool:
        v = self[name].lower()
        if v in self._TRUE:
            return True
        if v in self._FALSE:
            return False
        raise ValueError(f"parameter {name}={v!r} is not a boolean")

    def enum(self, name: str, mapping: dict[str, object]) -> object:
        v = self[name]
        if v not in mapping:
            raise ValueError(f"parameter {name}={v!r} not in "
                             f"{sorted(mapping)}")
        return mapping[v]
