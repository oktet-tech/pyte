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
