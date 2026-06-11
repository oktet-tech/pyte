/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright (C) 2026 Konstantin Ushakov */
/* cffi cdef — keep in sync with pyte_shim.h */
extern unsigned int te_test_id;
void pyte_log_init(const char *entity);
void pyte_log(unsigned int level, const char *user, const char *text);
void pyte_step(const char *text);
void pyte_substep(const char *text);
void pyte_verdict(unsigned int level, const char *text);
void pyte_artifact(unsigned int level, const char *text);
unsigned int pyte_rc_module(unsigned int rc);
unsigned int pyte_rc_error(unsigned int rc);
const char *te_rc_mod2str(unsigned int rc);
const char *te_rc_err2str(unsigned int rc);
void pyte_free_string(char *p);
#define TE_LL_ERROR ...
#define TE_LL_WARN ...
#define TE_LL_RING ...
#define TE_LL_INFO ...
#define TE_LL_VERB ...
#define PYTE_ETIMEDOUT ...
