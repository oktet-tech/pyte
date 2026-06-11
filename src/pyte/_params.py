# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Test parameter parsing: argv entries of the form name=value."""
from __future__ import annotations


def parse_argv(argv: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for arg in argv:
        name, sep, value = arg.partition("=")
        if not sep:
            raise ValueError(f"malformed test parameter {arg!r}")
        params[name.strip()] = value
    return params


class Params:
    """Typed access to test parameters."""

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
