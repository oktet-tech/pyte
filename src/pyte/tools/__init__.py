# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools — wrappers around TE's tapi_job-based CLI tools.

Each module is pure Python over pyte.job (the thin-shim rule): an Opts
dataclass that builds argv, a run()/server() context-manager factory, and
frozen Report dataclasses parsed from the tool's output. Option and report
surfaces are pinned to the corresponding TE tapi_* C source.
"""
