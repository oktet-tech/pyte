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

#include <stdarg.h>

#include "pyte_trc.h"
#include "te_alloc.h"
#include "tq_string.h"
#include "te_test_result.h"
#include "logger_defs.h"

/* No-op logging backend: CLI consumers surface their own errors and
 * must not depend on a running TE Logger. */
static void
pyte_trc_log_null(const char *file, unsigned int line,
                  te_log_ts_sec sec, te_log_ts_usec usec,
                  unsigned int level, const char *entity,
                  const char *user, const char *fmt, va_list ap)
{
    (void)file; (void)line; (void)sec; (void)usec;
    (void)level; (void)entity; (void)user; (void)fmt; (void)ap;
}

void
pyte_trc_quiet_logging(void)
{
    te_log_init("trc", pyte_trc_log_null);
}

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

bool
pyte_trc_walker_step_iter(te_trc_db_walker *walker, unsigned int n_args,
                          trc_report_argument *args, uint32_t flags)
{
    return trc_db_walker_step_iter(walker, n_args, args, flags, 0,
                                   (func_args_match_ptr)NULL);
}

trc_test_iter *
pyte_trc_walker_iter(const te_trc_db_walker *walker)
{
    return trc_db_walker_get_iter(walker);
}

/* Caller owns the allocation and must release it with pyte_tq_strings_free. */
tqh_strings *
pyte_tq_strings_new(void)
{
    tqh_strings *strs = TE_ALLOC(sizeof(*strs));

    TAILQ_INIT(strs);
    return strs;
}

te_errno
pyte_tq_strings_add(tqh_strings *strs, const char *value)
{
    return tq_strings_add_uniq_dup(strs, value);
}

void
pyte_tq_strings_free(tqh_strings *strs)
{
    tq_strings_free(strs, free);
    free(strs);
}

/* Caller owns the allocation and must release it with pyte_test_result_free. */
te_test_result *
pyte_test_result_new(int status)
{
    te_test_result *result = TE_ALLOC(sizeof(*result));

    te_test_result_init(result);
    result->status = status;
    return result;
}

te_errno
pyte_test_result_add_verdict(te_test_result *result, const char *text)
{
    te_test_verdict *verdict = TE_ALLOC(sizeof(*verdict));

    verdict->str = TE_STRDUP(text);
    TAILQ_INSERT_TAIL(&result->verdicts, verdict, links);
    return 0;
}

void
pyte_test_result_free(te_test_result *result)
{
    te_test_result_clean(result);
    free(result);
}
