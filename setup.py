# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
from setuptools import setup

setup(
    package_dir={"": "src"},
    packages=["pyte", "pyte.rpc", "pyte.tad"],
    cffi_modules=["build_shim.py:ffibuilder"],
)
