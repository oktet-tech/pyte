# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools — wrappers around TE's tapi_job-based CLI tools.

Each module is pure Python over pyte.job (the thin-shim rule): an Opts
dataclass that builds argv, a run()/server() context-manager factory, and
frozen Report dataclasses parsed from the tool's output. Option and report
surfaces are pinned to the corresponding TE tapi_* C source.

Shared machinery lives in ``pyte.tools._tool`` (ToolHandle lifecycle,
launch()/running(), argv builders, option coercion) and
``pyte.tools._units`` (suffix parsing); per-tool modules keep only what
is genuinely theirs — the Opts dataclass with its pinned argv bind
order, the output parser, and the MI vocabulary — and override
individual ToolHandle hooks for their specifics.

Naming doctrine: per-tool OPTION names mirror the tool's own flags,
not a synthetic common vocabulary — fio has ``runtime``, memtier
``test_time``, memaslap ``time`` because that is what you grep for in
the tool's man page and the pinned C TAPI.  The inconsistency across
wrappers is policy, not drift; do not "clean it up".  Units, however,
must be explicit: a field whose value is silently scaled ("k"
suffixes) carries the unit in its name (``win_size_kb``,
``expected_ktps``).
"""
