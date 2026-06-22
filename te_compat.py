# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Verify the TE checkout is new enough for this pyte.

Kept separate from build_shim.py so it can be imported and unit-tested
without a built TE present. See [tool.pyte] in pyproject.toml.
"""
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def read_min_te_commit(pyproject_path):
    """Return tool.pyte.min_te_commit from pyproject.toml, or None."""
    data = tomllib.loads(Path(pyproject_path).read_text(encoding="utf-8"))
    return data.get("tool", {}).get("pyte", {}).get("min_te_commit")


def check_te_compat(te_base, min_te_commit, *, env=None, run=subprocess.run):
    """Verify te_base's git HEAD contains min_te_commit.

    Returns None when the check passes or is intentionally skipped; raises
    RuntimeError when the TE checkout is provably too old. `env` and `run`
    are injectable for testing.
    """
    env = os.environ if env is None else env
    if not min_te_commit:
        return
    if env.get("PYTE_SKIP_TE_CHECK"):
        return
    if not te_base:
        print("pyte: TE_BASE unset; skipping TE compatibility check",
              file=sys.stderr)
        return
    if not (Path(te_base) / ".git").exists():
        print(f"pyte: {te_base} is not a git checkout; skipping TE "
              "compatibility check", file=sys.stderr)
        return
    try:
        proc = run(["git", "-C", str(te_base), "merge-base",
                    "--is-ancestor", min_te_commit, "HEAD"],
                   capture_output=True)
    except FileNotFoundError:
        print("pyte: git not found; skipping TE compatibility check",
              file=sys.stderr)
        return
    if proc.returncode == 0:
        return
    short = min_te_commit[:12]
    if proc.returncode == 1:
        raise RuntimeError(
            f"pyte requires a TE that contains commit {short}, but the "
            f"checkout at {te_base} does not include it. Update TE, or set "
            "PYTE_SKIP_TE_CHECK=1 to override.")
    raise RuntimeError(
        f"pyte could not verify TE compatibility: commit {short} is not "
        f"present in {te_base} (TE too old, or a shallow clone). Set "
        "PYTE_SKIP_TE_CHECK=1 to override.")
