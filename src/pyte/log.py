# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TE logging: direct API + stdlib logging bridge."""
from __future__ import annotations

from pyte._util import shim_lib as _shim_lib

import logging

from pyte._util import enc


# The implementation lives in pyte._util (shared infra); the name stays
# importable here for existing callers.
_enc = enc


def _lvl(name: str) -> int:
    lib = _shim_lib()
    return getattr(lib, f"TE_LL_{name}")


def _emit(level_name: str, user: str, text: str) -> None:
    lib = _shim_lib()
    lib.pyte_log(_lvl(level_name), _enc(user), _enc(text))


def error(text: str, user: str = "Self") -> None:
    _emit("ERROR", user, text)


def warn(text: str, user: str = "Self") -> None:
    _emit("WARN", user, text)


def ring(text: str, user: str = "Self") -> None:
    _emit("RING", user, text)


def info(text: str, user: str = "Self") -> None:
    _emit("INFO", user, text)


def verb(text: str, user: str = "Self") -> None:
    _emit("VERB", user, text)


def step_push(text: str) -> None:
    """Log ``text`` then nest following messages one level deeper.

    The nested block is collapsed by default in the HTML log (INFO
    level); pair with step_pop().
    """
    lib = _shim_lib()
    lib.pyte_step_push(_enc(text))


def step_pop(text: str = "") -> None:
    """Decrement the nesting level (close a step_push); log ``text``."""
    lib = _shim_lib()
    lib.pyte_step_pop(_enc(text))


class TeLogHandler(logging.Handler):
    """Routes stdlib logging records into the TE Logger."""

    _MAP = [(logging.ERROR, "ERROR"), (logging.WARNING, "WARN"),
            (logging.INFO, "RING"), (logging.DEBUG, "INFO")]

    def emit(self, record: logging.LogRecord) -> None:
        try:
            for threshold, name in self._MAP:
                if record.levelno >= threshold:
                    _emit(name, record.name, self.format(record))
                    return
            _emit("VERB", record.name, self.format(record))
        except Exception:
            self.handleError(record)
