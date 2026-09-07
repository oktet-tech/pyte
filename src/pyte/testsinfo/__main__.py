# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""``python3 -m pyte.testsinfo`` entry point."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
