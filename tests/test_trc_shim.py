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
        assert not lib.pyte_trc_db_last_match(db)
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


def _report_args(ffi, pairs):
    """Build a trc_report_argument[] plus keepalive list.

    The caller must keep the returned keepalive list alive until after the
    C call that reads the array (otherwise the char buffers are
    garbage-collected and the pointers dangle).
    """
    arr = ffi.new("trc_report_argument[]", len(pairs))
    keep = []
    for i, (k, v) in enumerate(pairs):
        kn = ffi.new("char[]", k.encode())
        kv = ffi.new("char[]", v.encode())
        keep += [kn, kv]
        arr[i].name = kn
        arr[i].value = kv
        arr[i].variable = False
    return arr, keep


def test_walker_matching_exact_and_wild():
    from pyte._shim import ffi, lib

    db = _open_db(ffi, lib)
    try:
        top = lib.pyte_trc_db_first_test(db)
        echo = lib.pyte_trc_iter_first_test(lib.pyte_trc_test_first_iter(top))

        w = lib.trc_db_new_walker(db)
        lib.trc_db_walker_go_to_test(w, echo)
        args, keep = _report_args(ffi, [("len", "1"), ("proto", "tcp")])
        assert lib.pyte_trc_walker_step_iter(w, 2, args, 0)
        it = lib.pyte_trc_walker_iter(w)
        assert ffi.string(lib.pyte_trc_arg_value(
            lib.pyte_trc_iter_first_arg(it))) == b"1"
        lib.trc_db_free_walker(w)

        # len=777/proto=udp only matches the wildcard record
        w = lib.trc_db_new_walker(db)
        lib.trc_db_walker_go_to_test(w, echo)
        args, keep = _report_args(ffi, [("len", "777"), ("proto", "udp")])
        assert lib.pyte_trc_walker_step_iter(w, 2, args, 0)
        it = lib.pyte_trc_walker_iter(w)
        assert ffi.string(lib.pyte_trc_arg_value(
            lib.pyte_trc_iter_first_arg(it))) == b""
        lib.trc_db_free_walker(w)

        # ... and is rejected when wildcards are excluded
        w = lib.trc_db_new_walker(db)
        lib.trc_db_walker_go_to_test(w, echo)
        args, keep = _report_args(ffi, [("len", "777"), ("proto", "udp")])
        assert not lib.pyte_trc_walker_step_iter(
            w, 2, args, lib.PYTE_STEP_ITER_NO_MATCH_WILD)
        lib.trc_db_free_walker(w)
    finally:
        lib.trc_db_close(db)


def test_exp_result_selection_and_compare():
    from pyte._shim import ffi, lib

    db = _open_db(ffi, lib)
    try:
        top = lib.pyte_trc_db_first_test(db)
        echo = lib.pyte_trc_iter_first_test(lib.pyte_trc_test_first_iter(top))
        eit = lib.pyte_trc_test_first_iter(echo)

        tags = lib.pyte_tq_strings_new()
        assert lib.pyte_tq_strings_add(tags, b"linux") == 0
        assert lib.pyte_tq_strings_add(tags, b"jumbo") == 0
        exp = lib.trc_db_iter_get_exp_result(eit, tags, False)
        assert exp != ffi.NULL
        ent = lib.pyte_trc_result_first_entry(exp)
        assert lib.pyte_trc_entry_status(ent) == lib.PYTE_TE_TEST_FAILED

        # observed FAILED + matching verdict is expected
        obtained = lib.pyte_test_result_new(lib.PYTE_TE_TEST_FAILED)
        assert lib.pyte_test_result_add_verdict(obtained, b"Too big") == 0
        assert lib.trc_is_result_expected(exp, obtained) != ffi.NULL
        lib.pyte_test_result_free(obtained)

        # observed PASSED is unexpected under linux&jumbo
        obtained = lib.pyte_test_result_new(lib.PYTE_TE_TEST_PASSED)
        assert lib.trc_is_result_expected(exp, obtained) == ffi.NULL
        lib.pyte_test_result_free(obtained)
        lib.pyte_tq_strings_free(tags)

        # without jumbo the default (PASSED) applies
        tags = lib.pyte_tq_strings_new()
        assert lib.pyte_tq_strings_add(tags, b"linux") == 0
        exp = lib.trc_db_iter_get_exp_result(eit, tags, False)
        assert exp != ffi.NULL
        ent = lib.pyte_trc_result_first_entry(exp)
        assert lib.pyte_trc_entry_status(ent) == lib.PYTE_TE_TEST_PASSED
        lib.pyte_tq_strings_free(tags)
    finally:
        lib.trc_db_close(db)


def test_logic_expr():
    from pyte._shim import ffi, lib

    out = ffi.new("logic_expr **")
    assert lib.logic_expr_parse(b"linux&jumbo", out) == 0
    tags = lib.pyte_tq_strings_new()
    lib.pyte_tq_strings_add(tags, b"linux")
    assert lib.logic_expr_match(out[0], tags) == -1
    lib.pyte_tq_strings_add(tags, b"jumbo")
    assert lib.logic_expr_match(out[0], tags) >= 0
    lib.pyte_tq_strings_free(tags)
    lib.logic_expr_free(out[0])

    assert lib.logic_expr_parse(b"linux &&& bad", out) != 0
