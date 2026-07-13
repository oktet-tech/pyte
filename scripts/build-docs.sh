#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
# Build the pyte HTML documentation in a TE-free ephemeral environment.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "${root}"
uv run --no-project --with-requirements docs/requirements.txt \
    sphinx-build -W --keep-going -b html docs docs/_build/html "$@"
echo "Docs built: ${root}/docs/_build/html/index.html"
