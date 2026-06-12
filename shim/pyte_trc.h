/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright (C) 2026 Konstantin Ushakov */
#ifndef PYTE_TRC_H
#define PYTE_TRC_H

/*
 * TRC accessor declarations for pyte_trc.c.
 *
 * This header deliberately does NOT include tapi_test.h or tapi_test_log.h:
 * those headers declare void te_test_verdict() which conflicts with the
 * typedef struct te_test_verdict in te_test_result.h.  Keep TRC accessors
 * in a separate translation unit to avoid that collision.
 *
 * Accessors do not NULL-check their return values; callers walk the lists
 * and test each returned pointer, mirroring the TAILQ contract.
 */

#include "te_config.h"
#include "te_defs.h"
#include "te_errno.h"
#include "te_trc.h"
#include "trc_db.h"

/*
 * pyte_trc_verdict is an alias for te_test_verdict.
 * In pyte_shim.h (compiled with tapi_test.h / tapi_test_log.h) we cannot
 * use the name te_test_verdict as a typedef — it conflicts with the function
 * of the same name declared in tapi_test_log.h.  We alias it here so
 * pyte_trc.c and pyte_shim.h agree on the type without the collision.
 */
typedef te_test_verdict pyte_trc_verdict;

extern te_errno pyte_trc_db_open(const char *path, te_trc_db **db);
extern bool pyte_trc_db_last_match(const te_trc_db *db);

extern trc_test *pyte_trc_db_first_test(te_trc_db *db);
extern trc_test *pyte_trc_test_next(trc_test *test);
extern trc_test_iter *pyte_trc_test_first_iter(trc_test *test);
extern trc_test_iter *pyte_trc_iter_next(trc_test_iter *iter);
extern trc_test *pyte_trc_iter_first_test(trc_test_iter *iter);

extern const char *pyte_trc_test_name(const trc_test *test);
extern const char *pyte_trc_test_path(const trc_test *test);
extern int pyte_trc_test_type(const trc_test *test);
extern bool pyte_trc_test_aux(const trc_test *test);
extern const char *pyte_trc_test_objective(const trc_test *test);
extern const char *pyte_trc_test_notes(const trc_test *test);
extern const char *pyte_trc_test_filename(const trc_test *test);
extern int pyte_trc_test_file_pos(const trc_test *test);

extern const char *pyte_trc_iter_notes(const trc_test_iter *iter);
extern const char *pyte_trc_iter_filename(const trc_test_iter *iter);
extern int pyte_trc_iter_file_pos(const trc_test_iter *iter);

extern trc_test_iter_arg *pyte_trc_iter_first_arg(trc_test_iter *iter);
extern trc_test_iter_arg *pyte_trc_arg_next(trc_test_iter_arg *arg);
extern const char *pyte_trc_arg_name(const trc_test_iter_arg *arg);
extern const char *pyte_trc_arg_value(const trc_test_iter_arg *arg);

extern const trc_exp_result *pyte_trc_iter_default_result(
                                        const trc_test_iter *iter);
extern trc_exp_result *pyte_trc_iter_first_result(trc_test_iter *iter);
extern trc_exp_result *pyte_trc_result_next(trc_exp_result *result);
extern const char *pyte_trc_result_tags(const trc_exp_result *result);
extern const char *pyte_trc_result_key(const trc_exp_result *result);
extern const char *pyte_trc_result_notes(const trc_exp_result *result);

extern trc_exp_result_entry *pyte_trc_result_first_entry(
                                        trc_exp_result *result);
extern trc_exp_result_entry *pyte_trc_entry_next(
                                        trc_exp_result_entry *entry);
extern int pyte_trc_entry_status(const trc_exp_result_entry *entry);
extern const char *pyte_trc_entry_key(const trc_exp_result_entry *entry);
extern const char *pyte_trc_entry_notes(const trc_exp_result_entry *entry);
extern pyte_trc_verdict *pyte_trc_entry_first_verdict(
                                        trc_exp_result_entry *entry);
extern pyte_trc_verdict *pyte_trc_verdict_next(pyte_trc_verdict *verdict);
extern const char *pyte_trc_verdict_str(const pyte_trc_verdict *verdict);

extern bool pyte_trc_walker_step_iter(te_trc_db_walker *walker,
                                      unsigned int n_args,
                                      trc_report_argument *args,
                                      uint32_t flags);
extern trc_test_iter *pyte_trc_walker_iter(const te_trc_db_walker *walker);

extern tqh_strings *pyte_tq_strings_new(void);
extern te_errno pyte_tq_strings_add(tqh_strings *strs, const char *value);
extern void pyte_tq_strings_free(tqh_strings *strs);

extern te_test_result *pyte_test_result_new(int status);
extern te_errno pyte_test_result_add_verdict(te_test_result *result,
                                             const char *text);
extern void pyte_test_result_free(te_test_result *result);

extern void pyte_trc_quiet_logging(void);

#endif /* PYTE_TRC_H */
