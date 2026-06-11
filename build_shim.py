# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""cffi API-mode builder for pyte._shim. Needs TE_INSTALL in env."""
import os
import subprocess
from pathlib import Path

from cffi import FFI

TE_INSTALL = os.environ.get("TE_INSTALL")
if not TE_INSTALL:
    raise RuntimeError("TE_INSTALL must be set to build pyte (run via run.sh)")

PKGCONF = str(Path(TE_INSTALL) / "default/lib/pkgconfig")
LIBDIR = str(Path(TE_INSTALL) / "default/lib")
TE_LIBS = [
    "te-tapi", "te-tapi_rpc", "te-tapi_job", "te-tapi_tad", "te-rcfrpc",
    "te-confapi", "te-conf_oid", "te-rcfapi", "te-logger_ten", "te-ipc",
    "te-tools", "te-logger_core", "te-asn", "te-ndn", "te-rpc_types",
    "te-rpcxdr",
]


def pkgconfig(*args: str) -> list[str]:
    env = dict(os.environ, PKG_CONFIG_PATH=PKGCONF)
    out = subprocess.check_output(["pkg-config", *args, *TE_LIBS],
                                  env=env, text=True)
    return out.split()


cflags = pkgconfig("--cflags")
libs = pkgconfig("--libs")

here = Path(__file__).parent
cdef = (here / "shim" / "pyte_shim_cdef.h").read_text()

ffibuilder = FFI()
ffibuilder.cdef(cdef)
ffibuilder.set_source(
    "pyte._shim",
    '#include "pyte_shim.h"',
    sources=[str(here / "shim" / "pyte_shim.c")],
    include_dirs=[str(here / "shim")],
    extra_compile_args=["-D_GNU_SOURCE", *cflags],
    # --disable-new-dtags: emit DT_RPATH (not DT_RUNPATH) so the path
    # also applies to transitive deps of the TE libs, which carry no
    # runpath of their own.
    extra_link_args=[*libs, f"-Wl,-rpath,{LIBDIR}",
                     "-Wl,--disable-new-dtags"],
)

if __name__ == "__main__":
    ffibuilder.compile(verbose=True)
