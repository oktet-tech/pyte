# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
from setuptools import find_packages, setup

setup(
    package_dir={"": "src"},
    # Discovery, not a hand-kept list: the explicit list this replaced
    # silently dropped pyte.cfg, pyte.cfg.gen and pyte.tools.trex, so an
    # installed wheel could not `import pyte.test` (seven shipped modules
    # import pyte.cfg).  A new subpackage must never go missing again
    # just because nobody remembered to add it here.
    packages=find_packages(where="src"),
    cffi_modules=["build_shim.py:ffibuilder"],
)
