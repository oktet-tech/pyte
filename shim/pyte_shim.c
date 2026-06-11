/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright (C) 2026 Konstantin Ushakov */
#include <stdlib.h>
#include <string.h>

#include "pyte_shim.h"

void
pyte_log_init(const char *entity)
{
    te_log_init(strdup(entity), ten_log_message);
}

void
pyte_log(unsigned int level, const char *user, const char *text)
{
    TE_LOG(level, TE_LGR_ENTITY, user, "%s", text);
}

void
pyte_step(const char *text)
{
    LGR_MESSAGE(TE_LL_CONTROL | TE_LL_RING, TE_USER_STEP, "%s", text);
    te_test_fail_state_update("%s", text);
    te_test_fail_substate_update(NULL);
}

void
pyte_substep(const char *text)
{
    LGR_MESSAGE(TE_LL_CONTROL | TE_LL_RING, TE_USER_SUBSTEP, "%s", text);
    te_test_fail_substate_update("%s", text);
}

void
pyte_verdict(unsigned int level, const char *text)
{
    te_test_verdict("pyte", 0, level, "%s", text);
}

void
pyte_artifact(unsigned int level, const char *text)
{
    te_test_artifact("pyte", 0, level, "%s", text);
}

unsigned int
pyte_rc_module(unsigned int rc)
{
    return TE_RC_GET_MODULE(rc);
}

unsigned int
pyte_rc_error(unsigned int rc)
{
    return TE_RC_GET_ERROR(rc);
}

void
pyte_free_string(char *p)
{
    free(p);
}
