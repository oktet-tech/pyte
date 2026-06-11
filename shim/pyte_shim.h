/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright (C) 2026 Konstantin Ushakov */
#ifndef PYTE_SHIM_H
#define PYTE_SHIM_H

#define TE_LGR_USER "pyte"
#include "te_config.h"
#include "te_defs.h"
#include "te_errno.h"
#include "logger_api.h"
#include "logger_ten.h"
#include "tapi_test.h"
#include "tapi_jmp.h"

#define PYTE_ETIMEDOUT TE_ETIMEDOUT

extern void pyte_log_init(const char *entity);
extern void pyte_log(unsigned int level, const char *user, const char *text);
extern void pyte_step(const char *text);
extern void pyte_substep(const char *text);
extern void pyte_verdict(unsigned int level, const char *text);
extern void pyte_artifact(unsigned int level, const char *text);
extern unsigned int pyte_rc_module(unsigned int rc);
extern unsigned int pyte_rc_error(unsigned int rc);
extern void pyte_free_string(char *p);

/*
 * Trampoline guard: confines any tapi longjmp to this C frame and
 * converts it to a te_errno return.
 *
 * WARNING: _stmt must not return early (via return/goto/break out of
 * the macro).  If _stmt returns early, tapi_jmp_pop() is never called,
 * leaving a stale jump point on the stack.  A later longjmp then lands
 * in the already-unwound frame — undefined behaviour that typically
 * manifests as a crash or silent data corruption.
 */
#define PYTE_GUARD(_stmt) \
    do {                                                              \
        tapi_jmp_point *pyte_jp_ = tapi_jmp_push(__FILE__, __LINE__); \
        int pyte_jrc_;                                                \
                                                                      \
        if (pyte_jp_ == NULL)                                         \
            return TE_RC(TE_TAPI, TE_ENOMEM);                         \
        if ((pyte_jrc_ = setjmp(pyte_jp_->env)) != 0)                 \
            return TE_RC(TE_TAPI, pyte_jrc_);                         \
        { _stmt; }                                                    \
        tapi_jmp_pop(__FILE__, __LINE__);                             \
    } while (0)

/*
 * Guard a te_errno-returning call: confines longjmp AND propagates the
 * call's own status. Returns from the enclosing function on error.
 */
#define PYTE_GUARD_RC(_call) \
    do {                                                              \
        te_errno pyte_call_rc_;                                       \
        PYTE_GUARD(pyte_call_rc_ = (_call));                          \
        if (pyte_call_rc_ != 0)                                       \
            return pyte_call_rc_;                                     \
    } while (0)

#endif /* PYTE_SHIM_H */
