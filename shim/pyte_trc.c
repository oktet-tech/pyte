/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright (C) 2026 Konstantin Ushakov */

/*
 * TRC read-only accessors.
 *
 * Kept in a separate translation unit so that te_test_result.h (pulled
 * in by te_trc.h) and tapi_test_log.h (pulled in by tapi_test.h in the
 * main shim) never appear in the same compilation unit: both declare an
 * identifier named te_test_verdict — one as a struct typedef, the other
 * as a function — causing a conflict the C compiler cannot resolve.
 */

#include "pyte_trc.h"

te_errno
pyte_trc_db_open(const char *path, te_trc_db **db)
{
    return trc_db_open_ext(path, db, TRC_OPEN_FIX_XINCLUDE);
}

bool
pyte_trc_db_last_match(const te_trc_db *db)
{
    return db->last_match;
}

trc_test *
pyte_trc_db_first_test(te_trc_db *db)
{
    return TAILQ_FIRST(&db->tests.head);
}

trc_test *
pyte_trc_test_next(trc_test *test)
{
    return TAILQ_NEXT(test, links);
}

trc_test_iter *
pyte_trc_test_first_iter(trc_test *test)
{
    return TAILQ_FIRST(&test->iters.head);
}

trc_test_iter *
pyte_trc_iter_next(trc_test_iter *iter)
{
    return TAILQ_NEXT(iter, links);
}

trc_test *
pyte_trc_iter_first_test(trc_test_iter *iter)
{
    return TAILQ_FIRST(&iter->tests.head);
}

const char *
pyte_trc_test_name(const trc_test *t)
{
    return t->name;
}

const char *
pyte_trc_test_path(const trc_test *t)
{
    return t->path;
}

int
pyte_trc_test_type(const trc_test *t)
{
    return t->type;
}

bool
pyte_trc_test_aux(const trc_test *t)
{
    return t->aux;
}

const char *
pyte_trc_test_objective(const trc_test *t)
{
    return t->objective;
}

const char *
pyte_trc_test_notes(const trc_test *t)
{
    return t->notes;
}

const char *
pyte_trc_test_filename(const trc_test *t)
{
    return t->filename;
}

int
pyte_trc_test_file_pos(const trc_test *t)
{
    return t->file_pos;
}

const char *
pyte_trc_iter_notes(const trc_test_iter *i)
{
    return i->notes;
}

const char *
pyte_trc_iter_filename(const trc_test_iter *i)
{
    return i->filename;
}

int
pyte_trc_iter_file_pos(const trc_test_iter *i)
{
    return i->file_pos;
}

trc_test_iter_arg *
pyte_trc_iter_first_arg(trc_test_iter *iter)
{
    return TAILQ_FIRST(&iter->args.head);
}

trc_test_iter_arg *
pyte_trc_arg_next(trc_test_iter_arg *arg)
{
    return TAILQ_NEXT(arg, links);
}

const char *
pyte_trc_arg_name(const trc_test_iter_arg *a)
{
    return a->name;
}

const char *
pyte_trc_arg_value(const trc_test_iter_arg *a)
{
    return a->value;
}

const trc_exp_result *
pyte_trc_iter_default_result(const trc_test_iter *iter)
{
    return iter->exp_default;
}

trc_exp_result *
pyte_trc_iter_first_result(trc_test_iter *iter)
{
    return STAILQ_FIRST(&iter->exp_results);
}

trc_exp_result *
pyte_trc_result_next(trc_exp_result *result)
{
    return STAILQ_NEXT(result, links);
}

const char *
pyte_trc_result_tags(const trc_exp_result *r)
{
    return r->tags_str;
}

const char *
pyte_trc_result_key(const trc_exp_result *r)
{
    return r->key;
}

const char *
pyte_trc_result_notes(const trc_exp_result *r)
{
    return r->notes;
}

trc_exp_result_entry *
pyte_trc_result_first_entry(trc_exp_result *result)
{
    return TAILQ_FIRST(&result->results);
}

trc_exp_result_entry *
pyte_trc_entry_next(trc_exp_result_entry *entry)
{
    return TAILQ_NEXT(entry, links);
}

int
pyte_trc_entry_status(const trc_exp_result_entry *entry)
{
    return entry->result.status;
}

const char *
pyte_trc_entry_key(const trc_exp_result_entry *e)
{
    return e->key;
}

const char *
pyte_trc_entry_notes(const trc_exp_result_entry *e)
{
    return e->notes;
}

pyte_trc_verdict *
pyte_trc_entry_first_verdict(trc_exp_result_entry *entry)
{
    return TAILQ_FIRST(&entry->result.verdicts);
}

pyte_trc_verdict *
pyte_trc_verdict_next(pyte_trc_verdict *verdict)
{
    return TAILQ_NEXT(verdict, links);
}

const char *
pyte_trc_verdict_str(const pyte_trc_verdict *v)
{
    return v->str;
}
