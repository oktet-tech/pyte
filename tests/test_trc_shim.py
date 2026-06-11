# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Raw shim smoke tests for the TRC bindings (no facade)."""
from pathlib import Path

import pytest

pytest.importorskip("pyte._shim")

DATA = str(Path(__file__).parent / "data" / "trc_basic.xml").encode()


def _open_db(ffi, lib):
    out = ffi.new("te_trc_db **")
    assert lib.pyte_trc_db_open(DATA, out) == 0
    return out[0]


def test_open_walk_close():
    from pyte._shim import ffi, lib

    db = _open_db(ffi, lib)
    try:
        assert lib.pyte_trc_db_last_match(db) == False
        top = lib.pyte_trc_db_first_test(db)
        assert top != ffi.NULL
        assert ffi.string(lib.pyte_trc_test_name(top)) == b"demo"
        it = lib.pyte_trc_test_first_iter(top)
        assert it != ffi.NULL
        echo = lib.pyte_trc_iter_first_test(it)
        assert ffi.string(lib.pyte_trc_test_name(echo)) == b"echo"
        eit = lib.pyte_trc_test_first_iter(echo)
        arg = lib.pyte_trc_iter_first_arg(eit)
        assert ffi.string(lib.pyte_trc_arg_name(arg)) == b"len"
        assert ffi.string(lib.pyte_trc_arg_value(arg)) == b"1"
        # second iteration: wildcard len (empty value, not NULL)
        eit2 = lib.pyte_trc_iter_next(eit)
        arg2 = lib.pyte_trc_iter_first_arg(eit2)
        assert ffi.string(lib.pyte_trc_arg_value(arg2)) == b""
        # results group on first iteration
        grp = lib.pyte_trc_iter_first_result(eit)
        assert grp != ffi.NULL
        assert ffi.string(lib.pyte_trc_result_key(grp)) == b"BUG-1"
        ent = lib.pyte_trc_result_first_entry(grp)
        assert lib.pyte_trc_entry_status(ent) == lib.PYTE_TE_TEST_FAILED
        v = lib.pyte_trc_entry_first_verdict(ent)
        assert ffi.string(lib.pyte_trc_verdict_str(v)) == b"Too big"
    finally:
        lib.trc_db_close(db)
