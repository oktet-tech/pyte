# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""cffi API-mode builder for pyte._shim. Needs TE_INSTALL in env."""
import os
import shlex
import subprocess
import sys
from pathlib import Path

from cffi import FFI

TE_INSTALL = os.environ.get("TE_INSTALL")
if not TE_INSTALL:
    raise RuntimeError("TE_INSTALL must be set to build pyte (run via run.sh)")

# te_compat.py sits alongside this file. cffi execs build_shim.py without
# its directory on sys.path (especially under uv build isolation), so add
# it explicitly before importing the sibling module.
sys.path.insert(0, str(Path(__file__).parent))
from te_compat import check_te_compat, read_min_te_commit  # noqa: E402

_PYPROJECT = Path(__file__).parent / "pyproject.toml"
check_te_compat(os.environ.get("TE_BASE"),
                read_min_te_commit(_PYPROJECT))

PKGCONF = str(Path(TE_INSTALL) / "default/lib/pkgconfig")
LIBDIR = str(Path(TE_INSTALL) / "default/lib")
TE_LIBS = [
    "te-tapi", "te-tapi_env", "te-tapi_rpc", "te-tapi_job", "te-tapi_tad", "te-rcfrpc",
    "te-confapi", "te-conf_oid", "te-rcfapi", "te-logger_ten", "te-ipc",
    "te-tools", "te-logger_core", "te-asn", "te-ndn", "te-rpc_types",
    "te-rpcxdr",
    # tarpc.h includes <rpc/rpc.h>; te-rpcxdr.pc does not propagate it
    "libtirpc",
    "te-trc", "te-logic_expr",
    # te_trc.h pulls in libxml2 headers; resolve the include path via pkg-config
    "libxml-2.0",
]


def pkgconfig(*args: str) -> list[str]:
    env = dict(os.environ, PKG_CONFIG_PATH=PKGCONF)
    try:
        out = subprocess.check_output(["pkg-config", *args, *TE_LIBS],
                                      env=env, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"pkg-config failed for TE libs under {PKGCONF}"
            f" — is TE built? ({exc})"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"pkg-config failed for TE libs under {PKGCONF}"
            f" — is TE built? ({exc})"
        ) from exc
    return shlex.split(out)


cflags = pkgconfig("--cflags")
libs = pkgconfig("--libs")

here = Path(__file__).parent
cdef = (here / "shim" / "pyte_shim_cdef.h").read_text()

ffibuilder = FFI()
ffibuilder.cdef(cdef)
ffibuilder.set_source(
    "pyte._shim",
    '#include "pyte_shim.h"',
    sources=[str(here / "shim" / "pyte_shim.c"),
             str(here / "shim" / "pyte_trc.c")],
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
