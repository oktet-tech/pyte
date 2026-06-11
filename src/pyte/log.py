# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TE logging: direct API + stdlib logging bridge."""
from __future__ import annotations

import logging


def _lvl(name: str) -> int:
    from pyte._shim import lib
    return getattr(lib, f"TE_LL_{name}")


def _emit(level_name: str, user: str, text: str) -> None:
    from pyte._shim import lib
    lib.pyte_log(_lvl(level_name), user.encode(), text.encode())


def error(text: str, user: str = "Self") -> None:
    _emit("ERROR", user, text)


def warn(text: str, user: str = "Self") -> None:
    _emit("WARN", user, text)


def ring(text: str, user: str = "Self") -> None:
    _emit("RING", user, text)


def info(text: str, user: str = "Self") -> None:
    _emit("INFO", user, text)


class TeLogHandler(logging.Handler):
    """Routes stdlib logging records into the TE Logger."""

    _MAP = [(logging.ERROR, "ERROR"), (logging.WARNING, "WARN"),
            (logging.INFO, "RING"), (logging.DEBUG, "INFO")]

    def emit(self, record: logging.LogRecord) -> None:
        for threshold, name in self._MAP:
            if record.levelno >= threshold:
                _emit(name, record.name, self.format(record))
                return
        _emit("VERB", record.name, self.format(record))
