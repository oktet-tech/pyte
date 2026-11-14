# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Test parameter parsing: argv entries of the form name=value."""
from __future__ import annotations

import enum as _enum
import os
from collections.abc import Mapping

from pyte.errors import ParamError

_VAR_PREFIX = "VAR."
_ENV_PREFIX = "TE_TEST_VAR_"
COMP_PREFIX = "COMP."
_TE_NAMES = frozenset({"te_test_id", "te_test_name", "te_rand_seed"})


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


_UNSET = object()
_TRUE = frozenset({"true", "yes", "1", "on"})
_FALSE = frozenset({"false", "no", "0", "off"})


def _to_int(value: str) -> int:
    return int(value, 0)


def _to_bool(value: str) -> bool:
    v = value.lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ValueError(value)


def _to_flag(value: str) -> bool:
    if value == "TRUE":
        return True
    if value == "FALSE":
        return False
    raise ValueError(value)


class _Readers:
    """The typed readers Params and Compound share.

    Each takes the name to look up and, optionally, the value to
    return when it is absent; that default is returned as it is, not
    parsed.  A value that does not parse is a ParamError naming the
    parameter in full: ``iperf3_tcp_count='abc': want an integer``.

    A subclass says how a name is looked up (_lookup(), which returns
    the full parameter name and its value, or None) and what an
    absent one without a default raises (_absent()).
    """

    def _lookup(self, name: str) -> tuple[str, str] | None:
        raise NotImplementedError

    def _absent(self, name: str):
        raise NotImplementedError

    def _read(self, name: str, default, conv, want: str):
        found = self._lookup(name)
        if found is None:
            if default is _UNSET:
                self._absent(name)
            return default
        full, value = found
        try:
            return conv(value)
        except ValueError:
            raise ParamError(f"{full}={value!r}: want {want}") from None

    def int(self, name: str, default=_UNSET) -> int:
        """An integer; 0x, 0o and 0b prefixes are accepted."""
        return self._read(name, default, _to_int, "an integer")

    def float(self, name: str, default=_UNSET) -> float:
        return self._read(name, default, float, "a number")

    def bool(self, name: str, default=_UNSET) -> bool:
        """A boolean in any common spelling, whatever the case:
        true/false, yes/no, 1/0, on/off."""
        return self._read(name, default, _to_bool,
                          "a boolean (true/false, yes/no, 1/0, on/off)")

    def flag(self, name: str, default=_UNSET) -> bool:
        """A boolean in TE's own spelling only: TRUE or FALSE.

        What TEST_GET_BOOL_PARAM accepts in a C test.  One spelling
        per meaning keeps the iterations of a test the same ones in
        TRC and in the results history.
        """
        return self._read(name, default, _to_flag, "TRUE or FALSE")

    def enum(self, name: str, mapping: dict[str, object] | type[_enum.Enum],
             default=_UNSET) -> object:
        """The value *mapping* gives for the parameter's text.

        *mapping* is a dict from the text to the value, or an Enum
        class whose member values are the texts the parameter takes::

            fw_layer = p.enum("fw_layer", FwLayer)

        The dict form is for a parameter whose texts are not the
        values of an Enum, or a test that takes only some of them.
        """
        if isinstance(mapping, type) and issubclass(mapping, _enum.Enum):
            mapping = {str(member.value): member for member in mapping}

        def conv(value):
            if value not in mapping:
                raise ValueError(value)
            return mapping[value]
        return self._read(name, default, conv,
                          f"one of {sorted(mapping)}")


class Compound(_Readers, Mapping):
    """One compound argument: its name and its field -> value mapping.

    A read-only mapping of the fields, in Tester's order, plus the
    typed readers of Params.  The readers and error() report a field
    by the flattened name ``<argument>_<field>``, the one the log
    shows and a plain argument overrides the field by.
    """

    def __init__(self, name: str, fields: Mapping[str, str]):
        self.name = name
        self._fields = dict(fields)

    def __getitem__(self, field: str) -> str:
        return self._fields[field]

    def __iter__(self):
        return iter(self._fields)

    def __len__(self) -> int:
        return len(self._fields)

    def __repr__(self) -> str:
        return f"Compound({self.name!r}, {self._fields!r})"

    def param(self, field: str) -> str:
        """The flattened parameter name of *field*."""
        return f"{self.name}_{field}"

    def _lookup(self, name: str) -> tuple[str, str] | None:
        if name not in self._fields:
            return None
        return self.param(name), self._fields[name]

    def _absent(self, name: str):
        raise ParamError(f"{self.param(name)}: the field is required")

    def require(self, field: str) -> str:
        """The text of *field*; ParamError when the argument lacks it."""
        if field not in self._fields:
            self._absent(field)
        return self._fields[field]

    def error(self, field: str, msg: str) -> ParamError:
        """A ParamError about *field*, to raise: the flattened name,
        the value when the field is there, then *msg*."""
        if field in self._fields:
            return ParamError(
                f"{self.param(field)}={self._fields[field]!r}: {msg}")
        return ParamError(f"{self.param(field)}: {msg}")


class Params(_Readers):
    """Typed access to test parameters.

    Note: the methods int(), float(), and bool() intentionally shadow the
    built-in types of the same name — this is deliberate for a fluent API
    (``p.int("n")`` reads naturally).  Code inside this class that needs
    the real built-in must use ``builtins.int`` / ``builtins.float`` /
    ``builtins.bool``, or quote the type in annotations
    (e.g. ``"int"`` rather than ``int``).

    When Tester runs with ``<option name="script_compound_args"
    value="yes"/>`` it also passes one ``COMP.<arg>=<f1>,<f2>,...``
    marker per compound argument, next to the flattened
    ``<arg>_<field>`` entries.  Those are exposed by compounds(),
    compound() and plain(); the raw accessors still see everything.
    """

    def __init__(self, raw: dict[str, str]):
        self._raw = raw
        self._compounds: dict[str, dict[str, str]] = {}
        listed: set[str] = set()
        for key, value in raw.items():
            if not key.startswith(COMP_PREFIX):
                continue
            name = key[len(COMP_PREFIX):]
            if not name:
                raise ValueError(
                    f"empty compound argument name in {key!r}")
            fields: dict[str, str] = {}
            for field in filter(None, (x.strip() for x in value.split(","))):
                full = f"{name}_{field}"
                if full not in raw:
                    raise ValueError(
                        f"compound {name!r} lists field {field!r} but "
                        f"parameter {full!r} is missing")
                fields[field] = raw[full]
                listed.add(full)
            self._compounds[name] = fields
        self._plain = {k: v for k, v in raw.items()
                       if not k.startswith(COMP_PREFIX)
                       and k not in listed and k not in _TE_NAMES}

    def __getitem__(self, name: str) -> str:
        try:
            return self._raw[name]
        except KeyError:
            raise KeyError(f"test has no parameter {name!r}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._raw

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._raw.get(name, default)

    def as_dict(self) -> dict[str, str]:
        """Every parameter as a new name -> value dict.

        For code that must see all the names rather than look one
        up, e.g. to reject a parameter nothing reads.
        """
        return dict(self._raw)

    def compounds(self) -> dict[str, Compound]:
        """Compound arguments as a new name -> Compound dict."""
        return {n: Compound(n, f) for n, f in self._compounds.items()}

    def compound(self, name: str) -> Compound:
        """One compound argument."""
        try:
            return Compound(name, self._compounds[name])
        except KeyError:
            raise KeyError(
                f"test has no compound argument {name!r}") from None

    def plain(self) -> dict[str, str]:
        """Parameters that are neither compound markers nor fields.

        The te_test_id, te_test_name and te_rand_seed names are
        excluded too.
        """
        return dict(self._plain)

    def _lookup(self, name: str) -> tuple[str, str] | None:
        if name not in self._raw:
            return None
        return name, self._raw[name]

    def _absent(self, name: str):
        raise KeyError(f"test has no parameter {name!r}")
