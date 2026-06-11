/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright (C) 2026 Konstantin Ushakov */
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "pyte_shim.h"

void
pyte_log_init(const char *entity)
{
    const char *e = (entity == NULL) ? NULL : strdup(entity);

    te_log_init(e == NULL ? "pyte" : e, ten_log_message);
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

te_errno
pyte_rpc_server_create(const char *ta, const char *name,
                       rcf_rpc_server **out)
{
    te_errno rc = rcf_rpc_server_create(ta, name, out);

    if (rc == 0)
        RPC_AWAIT_ERROR(*out);
    return rc;
}

te_errno
pyte_rpc_server_destroy(rcf_rpc_server *rpcs)
{
    return rcf_rpc_server_destroy(rpcs);
}

int
pyte_rpc_errno(rcf_rpc_server *rpcs)
{
    return RPC_ERRNO(rpcs);
}

const char *
pyte_rpc_err_msg(rcf_rpc_server *rpcs)
{
    return rpcs->err_msg;
}

void
pyte_rpc_set_timeout(rcf_rpc_server *rpcs, uint32_t ms)
{
    rpcs->timeout = ms;
}

te_errno
pyte_rpc_socket(rcf_rpc_server *rpcs, int domain, int type, int proto,
                int *out_fd)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out_fd = rpc_socket(rpcs, domain, type, proto));
    return 0;
}

te_errno
pyte_rpc_bind(rcf_rpc_server *rpcs, int s, const struct sockaddr *addr,
              int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_bind(rpcs, s, addr));
    return 0;
}

te_errno
pyte_rpc_connect(rcf_rpc_server *rpcs, int s, const struct sockaddr *addr,
                 int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_connect(rpcs, s, addr));
    return 0;
}

te_errno
pyte_rpc_listen(rcf_rpc_server *rpcs, int s, int backlog, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_listen(rpcs, s, backlog));
    return 0;
}

te_errno
pyte_rpc_accept(rcf_rpc_server *rpcs, int s, struct sockaddr *addr,
                socklen_t *addrlen, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_accept(rpcs, s, addr, addrlen));
    return 0;
}

te_errno
pyte_rpc_send(rcf_rpc_server *rpcs, int s, const uint8_t *buf, size_t len,
              int flags, ssize_t *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_send(rpcs, s, buf, len, flags));
    return 0;
}

te_errno
pyte_rpc_recv(rcf_rpc_server *rpcs, int s, uint8_t *buf, size_t len,
              int flags, ssize_t *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_recv(rpcs, s, buf, len, flags));
    return 0;
}

te_errno
pyte_rpc_sendto(rcf_rpc_server *rpcs, int s, const uint8_t *buf, size_t len,
                int flags, const struct sockaddr *to, ssize_t *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_sendto(rpcs, s, buf, len, flags, to));
    return 0;
}

te_errno
pyte_rpc_recvfrom(rcf_rpc_server *rpcs, int s, uint8_t *buf, size_t len,
                  int flags, struct sockaddr *from, socklen_t *fromlen,
                  ssize_t *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_recvfrom_gen(rpcs, s, buf, len, flags, from,
                                       fromlen, len,
                                       fromlen != NULL ? *fromlen : 0));
    return 0;
}

te_errno
pyte_rpc_getsockname(rcf_rpc_server *rpcs, int s, struct sockaddr *name,
                     socklen_t *namelen, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_getsockname(rpcs, s, name, namelen));
    return 0;
}

te_errno
pyte_rpc_close(rcf_rpc_server *rpcs, int fd, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_close(rpcs, fd));
    return 0;
}

te_errno
pyte_rpc_open(rcf_rpc_server *rpcs, const char *path, int flags, int mode,
              int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_open(rpcs, path, flags, mode));
    return 0;
}

te_errno
pyte_rpc_read(rcf_rpc_server *rpcs, int fd, uint8_t *buf, size_t count,
              int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_read(rpcs, fd, buf, count));
    return 0;
}

te_errno
pyte_rpc_write(rcf_rpc_server *rpcs, int fd, const uint8_t *buf,
               size_t count, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_write(rpcs, fd, buf, count));
    return 0;
}

te_errno
pyte_rpc_unlink(rcf_rpc_server *rpcs, const char *path, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_unlink(rpcs, path));
    return 0;
}

te_errno
pyte_rpc_getpid(rcf_rpc_server *rpcs, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_getpid(rpcs));
    return 0;
}

te_errno
pyte_rpc_gethostname(rcf_rpc_server *rpcs, char *buf, size_t len, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_gethostname(rpcs, buf, len));
    return 0;
}

te_errno
pyte_rpc_shell_get_all(rcf_rpc_server *rpcs, char **out_buf,
                       const char *cmd, int *out_flag, int *out_value)
{
    rpc_wait_status st;

    RPC_AWAIT_ERROR(rpcs);
    /*
     * uid -1 means "run as the current user"; "%s" guards against
     * '%' in the user command, since cmd is a printf format here.
     */
    PYTE_GUARD(st = rpc_shell_get_all(rpcs, out_buf, "%s",
                                      (tarpc_uid_t)-1, cmd));
    *out_flag = st.flag;
    *out_value = st.value;
    return 0;
}

/*
 * Configurator section.  cfg_* calls do not longjmp today, but every
 * entry point is still wrapped in PYTE_GUARD via a _nojmp helper so a
 * surprise jump cannot unwind past the C/Python boundary.  The helpers
 * are ordinary functions: returning from them inside the guard is fine
 * (the guarded statement is just the rc assignment).
 */

static te_errno
pyte_cfg_get_type_nojmp(const char *oid, int *out_type)
{
    cfg_handle    h;
    cfg_obj_descr descr;
    te_errno      rc;

    rc = cfg_find_str(oid, &h);
    if (rc != 0)
        return rc;
    rc = cfg_get_object_descr(h, &descr);
    if (rc != 0)
        return rc;
    /* descr.def_val is a stale cross-process pointer: do not touch */
    *out_type = (int)descr.type;
    return 0;
}

te_errno
pyte_cfg_get_type(const char *oid, int *out_type)
{
    PYTE_GUARD_RC(pyte_cfg_get_type_nojmp(oid, out_type));
    return 0;
}

static te_errno
pyte_cfg_get_str_nojmp(const char *oid, char **out, int *out_type)
{
    cfg_val_type t = CVT_UNSPECIFIED;
    union {
        bool             b;
        int8_t           i8;
        uint8_t          u8;
        int16_t          i16;
        uint16_t         u16;
        int32_t          i32;
        uint32_t         u32;
        int64_t          i64;
        uint64_t         u64;
        double           d;
        char            *s;
        struct sockaddr *sa;
    } v;
    te_errno rc;
    int      n = -1;

    memset(&v, 0, sizeof(v));
    rc = cfg_get_instance_str(&t, &v, oid);
    if (rc != 0)
        return rc;
    if (out_type != NULL)
        *out_type = (int)t;

    switch (t)
    {
        case CVT_STRING:
            *out = (v.s != NULL) ? v.s : strdup("");
            return *out == NULL ? TE_RC(TE_TAPI, TE_ENOMEM) : 0;

        case CVT_NONE:
            *out = strdup("");
            break;

        case CVT_BOOL:
            n = asprintf(out, "%d", v.b ? 1 : 0);
            break;

        case CVT_INT8:
            n = asprintf(out, "%" PRId8, v.i8);
            break;

        case CVT_UINT8:
            n = asprintf(out, "%" PRIu8, v.u8);
            break;

        case CVT_INT16:
            n = asprintf(out, "%" PRId16, v.i16);
            break;

        case CVT_UINT16:
            n = asprintf(out, "%" PRIu16, v.u16);
            break;

        case CVT_INT32:
            n = asprintf(out, "%" PRId32, v.i32);
            break;

        case CVT_UINT32:
            n = asprintf(out, "%" PRIu32, v.u32);
            break;

        case CVT_INT64:
            n = asprintf(out, "%" PRId64, v.i64);
            break;

        case CVT_UINT64:
            n = asprintf(out, "%" PRIu64, v.u64);
            break;

        case CVT_DOUBLE:
            n = asprintf(out, "%.17g", v.d);
            break;

        case CVT_ADDRESS:
        {
            char     buf[INET6_ADDRSTRLEN];
            uint16_t port;

            rc = pyte_sockaddr_parse(v.sa, buf, sizeof(buf), &port);
            free(v.sa);
            if (rc != 0)
                return rc;
            *out = strdup(buf);
            break;
        }

        default:
            return TE_RC(TE_TAPI, TE_EINVAL);
    }

    if (t == CVT_NONE || t == CVT_ADDRESS)
        return *out == NULL ? TE_RC(TE_TAPI, TE_ENOMEM) : 0;
    return n < 0 ? TE_RC(TE_TAPI, TE_ENOMEM) : 0;
}

te_errno
pyte_cfg_get_str(const char *oid, char **out, int *out_type)
{
    PYTE_GUARD_RC(pyte_cfg_get_str_nojmp(oid, out, out_type));
    return 0;
}

/* Parse an integer (base auto-detected) with range check */
static te_errno
pyte_parse_int(const char *value, int64_t min, int64_t max, int64_t *out)
{
    char    *end = NULL;
    long long v;

    if (value == NULL)
        return TE_RC(TE_TAPI, TE_EINVAL);
    errno = 0;
    v = strtoll(value, &end, 0);
    if (errno != 0 || end == value || *end != '\0' || v < min || v > max)
        return TE_RC(TE_TAPI, TE_EINVAL);
    *out = v;
    return 0;
}

static te_errno
pyte_parse_uint(const char *value, uint64_t max, uint64_t *out)
{
    char              *end = NULL;
    unsigned long long v;
    const char        *p;

    if (value == NULL)
        return TE_RC(TE_TAPI, TE_EINVAL);
    /* Skip leading whitespace, then reject a '-' sign.  strtoull()
     * itself would silently accept " -1" as a large positive number. */
    for (p = value; isspace((unsigned char)*p); p++)
        ;
    if (*p == '-')
        return TE_RC(TE_TAPI, TE_EINVAL);
    errno = 0;
    v = strtoull(value, &end, 0);
    if (errno != 0 || end == value || *end != '\0' || v > max)
        return TE_RC(TE_TAPI, TE_EINVAL);
    *out = v;
    return 0;
}

static te_errno
pyte_parse_bool(const char *value, bool *out)
{
    if (value == NULL)
        return TE_RC(TE_TAPI, TE_EINVAL);
    if (strcmp(value, "1") == 0 || strcasecmp(value, "true") == 0)
        *out = true;
    else if (strcmp(value, "0") == 0 || strcasecmp(value, "false") == 0)
        *out = false;
    else
        return TE_RC(TE_TAPI, TE_EINVAL);
    return 0;
}

static te_errno
pyte_parse_sockaddr(const char *value, struct sockaddr_storage *ss)
{
    struct sockaddr_in  *sin = (struct sockaddr_in *)ss;
    struct sockaddr_in6 *sin6 = (struct sockaddr_in6 *)ss;

    memset(ss, 0, sizeof(*ss));
    if (value == NULL)
        return TE_RC(TE_TAPI, TE_EINVAL);
    if (inet_pton(AF_INET, value, &sin->sin_addr) == 1)
    {
        sin->sin_family = AF_INET;
        return 0;
    }
    if (inet_pton(AF_INET6, value, &sin6->sin6_addr) == 1)
    {
        sin6->sin6_family = AF_INET6;
        return 0;
    }
    return TE_RC(TE_TAPI, TE_EINVAL);
}

/*
 * Both set and add pass the value as a single properly typed vararg
 * (the convention of cfg_set_instance()/cfg_add_instance_str(); this
 * also makes CVT_DOUBLE work, unlike the (const void *)(intptr_t)
 * packing of CFG_VAL which cannot carry a double).  add_h == NULL
 * means "set existing instance", otherwise the instance is added.
 */
static te_errno
pyte_cfg_put_nojmp(const char *oid, int type, const char *value,
                   cfg_handle *add_h)
{
    cfg_val_type t = (cfg_val_type)type;
    cfg_handle   h = CFG_HANDLE_INVALID;
    te_errno     rc;
    int64_t      i = 0;
    uint64_t     u = 0;

    if (add_h == NULL)
    {
        rc = cfg_find_str(oid, &h);
        if (rc != 0)
            return rc;
    }

#define PYTE_CFG_PUT(...) \
    (add_h != NULL ? cfg_add_instance_str(oid, add_h, t, ##__VA_ARGS__) \
                   : cfg_set_instance(h, t, ##__VA_ARGS__))

    switch (t)
    {
        case CVT_NONE:
            return PYTE_CFG_PUT();

        case CVT_STRING:
            return PYTE_CFG_PUT(value);

        case CVT_BOOL:
        {
            bool b;

            rc = pyte_parse_bool(value, &b);
            return rc != 0 ? rc : PYTE_CFG_PUT((unsigned int)b);
        }

        case CVT_INT8:
            rc = pyte_parse_int(value, INT8_MIN, INT8_MAX, &i);
            return rc != 0 ? rc : PYTE_CFG_PUT((int)i);

        case CVT_INT16:
            rc = pyte_parse_int(value, INT16_MIN, INT16_MAX, &i);
            return rc != 0 ? rc : PYTE_CFG_PUT((int)i);

        case CVT_INT32:
            rc = pyte_parse_int(value, INT32_MIN, INT32_MAX, &i);
            return rc != 0 ? rc : PYTE_CFG_PUT((int)i);

        case CVT_INT64:
            rc = pyte_parse_int(value, INT64_MIN, INT64_MAX, &i);
            return rc != 0 ? rc : PYTE_CFG_PUT((int64_t)i);

        case CVT_UINT8:
            rc = pyte_parse_uint(value, UINT8_MAX, &u);
            return rc != 0 ? rc : PYTE_CFG_PUT((unsigned int)u);

        case CVT_UINT16:
            rc = pyte_parse_uint(value, UINT16_MAX, &u);
            return rc != 0 ? rc : PYTE_CFG_PUT((unsigned int)u);

        case CVT_UINT32:
            rc = pyte_parse_uint(value, UINT32_MAX, &u);
            return rc != 0 ? rc : PYTE_CFG_PUT((unsigned int)u);

        case CVT_UINT64:
            rc = pyte_parse_uint(value, UINT64_MAX, &u);
            return rc != 0 ? rc : PYTE_CFG_PUT((uint64_t)u);

        case CVT_DOUBLE:
        {
            char  *end = NULL;
            double d;

            if (value == NULL)
                return TE_RC(TE_TAPI, TE_EINVAL);
            errno = 0;
            d = strtod(value, &end);
            if (errno != 0 || end == value || *end != '\0')
                return TE_RC(TE_TAPI, TE_EINVAL);
            return PYTE_CFG_PUT(d);
        }

        case CVT_ADDRESS:
        {
            struct sockaddr_storage ss;

            rc = pyte_parse_sockaddr(value, &ss);
            return rc != 0 ? rc
                           : PYTE_CFG_PUT((struct sockaddr *)&ss);
        }

        default:
            return TE_RC(TE_TAPI, TE_EINVAL);
    }
#undef PYTE_CFG_PUT
}

te_errno
pyte_cfg_set_str(const char *oid, int type, const char *value)
{
    PYTE_GUARD_RC(pyte_cfg_put_nojmp(oid, type, value, NULL));
    return 0;
}

te_errno
pyte_cfg_add_str(const char *oid, int type, const char *value,
                 cfg_handle *out)
{
    PYTE_GUARD_RC(pyte_cfg_put_nojmp(oid, type, value, out));
    return 0;
}

static te_errno
pyte_cfg_del_nojmp(const char *oid, int with_children)
{
    cfg_handle h;
    te_errno   rc;

    rc = cfg_find_str(oid, &h);
    if (rc != 0)
        return rc;
    return cfg_del_instance(h, with_children != 0);
}

te_errno
pyte_cfg_del(const char *oid, int with_children)
{
    PYTE_GUARD_RC(pyte_cfg_del_nojmp(oid, with_children));
    return 0;
}

te_errno
pyte_cfg_find_pattern(const char *pattern, unsigned int *n,
                      cfg_handle **set)
{
    PYTE_GUARD_RC(cfg_find_pattern(pattern, n, set));
    return 0;
}

te_errno
pyte_cfg_oid_str(cfg_handle h, char **out)
{
    PYTE_GUARD_RC(cfg_get_oid_str(h, out));
    return 0;
}

te_errno
pyte_cfg_inst_name(cfg_handle h, char **out)
{
    PYTE_GUARD_RC(cfg_get_inst_name(h, out));
    return 0;
}

te_errno
pyte_cfg_synchronize(const char *oid, int with_subtree)
{
    PYTE_GUARD_RC(cfg_synchronize(oid, with_subtree != 0));
    return 0;
}

void
pyte_free_handles(cfg_handle *set)
{
    free(set);
}

/*
 * Job section.  tapi_job functions return te_errno and are not
 * supposed to longjmp, but every call is still guarded.  Channel sets
 * are repacked from (array, count) into NULL-terminated VLAs; the
 * _nojmp helpers own all te_string memory so it is freed on every
 * return path (a longjmp would leak it, but a jump out of a
 * te_errno-returning tapi_job call means the test is failing anyway).
 */

te_errno
pyte_job_factory_rpc(rcf_rpc_server *rpcs, tapi_job_factory_t **out)
{
    PYTE_GUARD_RC(tapi_job_factory_rpc_create(rpcs, out));
    return 0;
}

te_errno
pyte_job_factory_destroy(tapi_job_factory_t *f)
{
    PYTE_GUARD(tapi_job_factory_destroy(f));
    return 0;
}

te_errno
pyte_job_create(tapi_job_factory_t *f, const char *program,
                const char **argv, const char **env, tapi_job_t **out)
{
    PYTE_GUARD_RC(tapi_job_create(f, NULL, program, argv, env, out));
    return 0;
}

te_errno
pyte_job_start(tapi_job_t *job)
{
    PYTE_GUARD_RC(tapi_job_start(job));
    return 0;
}

te_errno
pyte_job_wait(tapi_job_t *job, int timeout_ms, int *out_type,
              int *out_value)
{
    tapi_job_status_t st = { .type = TAPI_JOB_STATUS_UNKNOWN, .value = 0 };

    PYTE_GUARD_RC(tapi_job_wait(job, timeout_ms, &st));
    *out_type = (int)st.type;
    *out_value = st.value;
    return 0;
}

te_errno
pyte_job_stop(tapi_job_t *job, int signo, int term_timeout_ms)
{
    PYTE_GUARD_RC(tapi_job_stop(job, signo, term_timeout_ms));
    return 0;
}

te_errno
pyte_job_kill(tapi_job_t *job, int signo)
{
    PYTE_GUARD_RC(tapi_job_kill(job, signo));
    return 0;
}

te_errno
pyte_job_destroy(tapi_job_t *job, int term_timeout_ms)
{
    PYTE_GUARD_RC(tapi_job_destroy(job, term_timeout_ms));
    return 0;
}

te_errno
pyte_job_out_channels(tapi_job_t *job, tapi_job_channel_t **out_stdout,
                      tapi_job_channel_t **out_stderr)
{
    tapi_job_channel_t *ch[2] = { NULL, NULL };

    PYTE_GUARD_RC(tapi_job_alloc_output_channels(job, 2, ch));
    *out_stdout = ch[0];
    *out_stderr = ch[1];
    return 0;
}

te_errno
pyte_job_in_channel(tapi_job_t *job, tapi_job_channel_t **out)
{
    tapi_job_channel_t *ch[1] = { NULL };

    PYTE_GUARD_RC(tapi_job_alloc_input_channels(job, 1, ch));
    *out = ch[0];
    return 0;
}

te_errno
pyte_job_attach_filter(tapi_job_channel_t **channels, unsigned int n,
                       const char *name, int readable,
                       unsigned int log_level, tapi_job_channel_t **out)
{
    tapi_job_channel_t *set[n + 1];
    unsigned int i;

    for (i = 0; i < n; i++)
        set[i] = channels[i];
    set[n] = NULL;
    PYTE_GUARD_RC(tapi_job_attach_filter(set, name, readable != 0,
                                         (te_log_level)log_level, out));
    return 0;
}

te_errno
pyte_job_filter_regexp(tapi_job_channel_t *filter, const char *re,
                       unsigned int extract)
{
    PYTE_GUARD_RC(tapi_job_filter_add_regexp(filter, re, extract));
    return 0;
}

te_errno
pyte_job_filter_add(tapi_job_channel_t *filter,
                    tapi_job_channel_t **channels, unsigned int n)
{
    tapi_job_channel_t *set[n + 1];
    unsigned int i;

    for (i = 0; i < n; i++)
        set[i] = channels[i];
    set[n] = NULL;
    PYTE_GUARD_RC(tapi_job_filter_add_channels(filter, set));
    return 0;
}

te_errno
pyte_job_filter_remove(tapi_job_channel_t *filter,
                       tapi_job_channel_t **channels, unsigned int n)
{
    tapi_job_channel_t *set[n + 1];
    unsigned int i;

    for (i = 0; i < n; i++)
        set[i] = channels[i];
    set[n] = NULL;
    PYTE_GUARD_RC(tapi_job_filter_remove_channels(filter, set));
    return 0;
}

static te_errno
pyte_job_receive_nojmp(tapi_job_channel_t **filters, unsigned int n,
                       int timeout_ms, int last, char **out_data,
                       size_t *out_len, int *out_eos,
                       unsigned int *out_dropped,
                       tapi_job_channel_t **out_filter)
{
    tapi_job_channel_t *set[n + 1];
    tapi_job_buffer_t buf = TAPI_JOB_BUFFER_INIT;
    te_errno rc;
    unsigned int i;

    for (i = 0; i < n; i++)
        set[i] = filters[i];
    set[n] = NULL;

    rc = last ? tapi_job_receive_last(set, timeout_ms, &buf)
              : tapi_job_receive(set, timeout_ms, &buf);
    if (rc != 0)
    {
        te_string_free(&buf.data);
        return rc;
    }

    *out_len = buf.data.len;
    *out_data = malloc(buf.data.len + 1);
    if (*out_data == NULL)
    {
        te_string_free(&buf.data);
        return TE_RC(TE_TAPI, TE_ENOMEM);
    }
    if (buf.data.ptr != NULL && buf.data.len > 0)
        memcpy(*out_data, buf.data.ptr, buf.data.len);
    (*out_data)[buf.data.len] = '\0';
    *out_eos = buf.eos ? 1 : 0;
    *out_dropped = buf.dropped;
    *out_filter = buf.filter;
    te_string_free(&buf.data);
    return 0;
}

te_errno
pyte_job_receive(tapi_job_channel_t **filters, unsigned int n,
                 int timeout_ms, int last, char **out_data,
                 size_t *out_len, int *out_eos, unsigned int *out_dropped,
                 tapi_job_channel_t **out_filter)
{
    PYTE_GUARD_RC(pyte_job_receive_nojmp(filters, n, timeout_ms, last,
                                         out_data, out_len, out_eos,
                                         out_dropped, out_filter));
    return 0;
}

static te_errno
pyte_job_send_nojmp(tapi_job_channel_t *channel, const char *data,
                    size_t len)
{
    te_string str = TE_STRING_INIT;
    te_errno rc;

    /* te_string_append_buf() is binary-safe (NULs allowed) */
    rc = te_string_append_buf(&str, data, len);
    if (rc == 0)
        rc = tapi_job_send(channel, &str);
    te_string_free(&str);
    return rc;
}

te_errno
pyte_job_send(tapi_job_channel_t *channel, const char *data, size_t len)
{
    PYTE_GUARD_RC(pyte_job_send_nojmp(channel, data, len));
    return 0;
}

te_errno
pyte_job_poll(tapi_job_channel_t **channels, unsigned int n,
              int timeout_ms)
{
    tapi_job_channel_t *set[n + 1];
    unsigned int i;

    for (i = 0; i < n; i++)
        set[i] = channels[i];
    set[n] = NULL;
    PYTE_GUARD_RC(tapi_job_poll(set, timeout_ms));
    return 0;
}

te_errno
pyte_sockaddr_in4(const char *ip, uint16_t port,
                  struct sockaddr_storage *ss, socklen_t *len)
{
    struct sockaddr_in *sin = (struct sockaddr_in *)ss;

    memset(ss, 0, sizeof(*ss));
    sin->sin_family = AF_INET;
    sin->sin_port = htons(port);
    if (inet_pton(AF_INET, ip, &sin->sin_addr) != 1)
        return TE_RC(TE_TAPI, TE_EINVAL);
    *len = sizeof(struct sockaddr_in);
    return 0;
}

te_errno
pyte_sockaddr_parse(const struct sockaddr *sa, char *ipbuf,
                    size_t ipbuflen, uint16_t *port)
{
    if (sa->sa_family == AF_INET)
    {
        const struct sockaddr_in *sin = (const struct sockaddr_in *)sa;

        if (inet_ntop(AF_INET, &sin->sin_addr, ipbuf, ipbuflen) == NULL)
            return TE_RC(TE_TAPI, TE_EINVAL);
        *port = ntohs(sin->sin_port);
        return 0;
    }
    if (sa->sa_family == AF_INET6)
    {
        const struct sockaddr_in6 *sin6 =
            (const struct sockaddr_in6 *)sa;

        if (inet_ntop(AF_INET6, &sin6->sin6_addr, ipbuf, ipbuflen) == NULL)
            return TE_RC(TE_TAPI, TE_EINVAL);
        *port = ntohs(sin6->sin6_port);
        return 0;
    }
    return TE_RC(TE_TAPI, TE_EAFNOSUPPORT);
}
