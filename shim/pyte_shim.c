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
pyte_rpc_setsockopt_int(rcf_rpc_server *rpcs, int s, int optname,
                        int optval, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_setsockopt_int(rpcs, s, (rpc_sockopt)optname,
                                         optval));
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
pyte_rpc_getenv(rcf_rpc_server *rpcs, const char *name, char **out)
{
    RPC_AWAIT_ERROR(rpcs);
    /* NULL means both "variable unset" and "call failed":
     * Python tells them apart via pyte_rpc_errno() */
    PYTE_GUARD(*out = rpc_getenv(rpcs, name));
    return 0;
}

te_errno
pyte_rpc_setenv(rcf_rpc_server *rpcs, const char *name, const char *value,
                int overwrite, int *out)
{
    RPC_AWAIT_ERROR(rpcs);
    PYTE_GUARD(*out = rpc_setenv(rpcs, name, value, overwrite));
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
 * entry point is still wrapped in PYTE_GUARD so a surprise jump cannot
 * unwind past the C/Python boundary.  Helpers with internal control
 * flow use the _nojmp pattern (a helper function called inside the
 * guard); single-expression wrappers may guard the tapi call directly.
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

            if (v.sa == NULL || v.sa->sa_family == AF_UNSPEC)
            {
                /* NULL/unspecified address reads as an empty string */
                free(v.sa);
                *out = strdup("");
                break;
            }
            if (v.sa->sa_family == AF_LOCAL)
            {
                /*
                 * Configurator stores link-layer (MAC) addresses as
                 * AF_LOCAL with the bytes in sa_data (conf_types.c
                 * addr_to_str); render them the same way.
                 */
                const unsigned char *mac =
                    (const unsigned char *)v.sa->sa_data;

                snprintf(buf, sizeof(buf),
                         "%02x:%02x:%02x:%02x:%02x:%02x",
                         mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
                free(v.sa);
                *out = strdup(buf);
                break;
            }
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
 * Network configuration section (tapi_cfg / tapi_cfg_base /
 * tapi_cfg_sys).  All entry points follow the cfg house pattern:
 * a _nojmp helper does the work, the public function guards it.
 *
 * tapi_cfg_add_route()/tapi_cfg_del_route_tmp() take RAW network
 * addresses (struct in_addr et al., what te_sockaddr_get_netaddr()
 * yields), NOT sockaddrs — see their tapi_cfg.h prototypes
 * (const void *dst_addr).  Unexposed route attributes (src_addr,
 * flags, tos, mtu, win, irtt) are passed as NULL/0.
 */

static te_errno
pyte_cfg_route_op_nojmp(bool add, const char *ta, const char *dst,
                        int prefix, const char *gw, const char *dev,
                        int metric)
{
    struct in_addr dst_in;
    struct in_addr gw_in;
    bool           have_gw = (gw != NULL && gw[0] != '\0');
    cfg_handle     h = CFG_HANDLE_INVALID;

    if (dst == NULL || inet_pton(AF_INET, dst, &dst_in) != 1)
        return TE_RC(TE_TAPI, TE_EINVAL);
    if (have_gw && inet_pton(AF_INET, gw, &gw_in) != 1)
        return TE_RC(TE_TAPI, TE_EINVAL);
    if (dev != NULL && dev[0] == '\0')
        dev = NULL;

    if (add)
    {
        /* The handle is discarded: deletion goes by spec */
        return tapi_cfg_add_route(ta, AF_INET, &dst_in, prefix,
                                  have_gw ? &gw_in : NULL, dev, NULL,
                                  0, metric, 0, 0, 0, 0, &h);
    }
    return tapi_cfg_del_route_tmp(ta, AF_INET, &dst_in, prefix,
                                  have_gw ? &gw_in : NULL, dev, NULL,
                                  0, metric, 0, 0, 0, 0);
}

te_errno
pyte_cfg_route_add(const char *ta, const char *dst, int prefix,
                   const char *gw, const char *dev, int metric)
{
    PYTE_GUARD_RC(pyte_cfg_route_op_nojmp(true, ta, dst, prefix, gw,
                                          dev, metric));
    return 0;
}

te_errno
pyte_cfg_route_del(const char *ta, const char *dst, int prefix,
                   const char *gw, const char *dev, int metric)
{
    PYTE_GUARD_RC(pyte_cfg_route_op_nojmp(false, ta, dst, prefix, gw,
                                          dev, metric));
    return 0;
}

static te_errno
pyte_cfg_neigh_add_nojmp(const char *ta, const char *ifname,
                         const char *ip, const uint8_t *mac,
                         int is_static)
{
    struct sockaddr_storage ss;
    socklen_t               len;
    te_errno                rc;

    rc = pyte_sockaddr_in4(ip, 0, &ss, &len);
    if (rc != 0)
        return rc;
    return tapi_cfg_add_neigh_entry(ta, ifname, (struct sockaddr *)&ss,
                                    mac, is_static != 0);
}

te_errno
pyte_cfg_neigh_add(const char *ta, const char *ifname, const char *ip,
                   const uint8_t *mac, int is_static)
{
    PYTE_GUARD_RC(pyte_cfg_neigh_add_nojmp(ta, ifname, ip, mac,
                                           is_static));
    return 0;
}

static te_errno
pyte_cfg_neigh_del_nojmp(const char *ta, const char *ifname,
                         const char *ip)
{
    struct sockaddr_storage ss;
    socklen_t               len;
    te_errno                rc;

    rc = pyte_sockaddr_in4(ip, 0, &ss, &len);
    if (rc != 0)
        return rc;
    return tapi_cfg_del_neigh_entry(ta, ifname, (struct sockaddr *)&ss);
}

te_errno
pyte_cfg_neigh_del(const char *ta, const char *ifname, const char *ip)
{
    PYTE_GUARD_RC(pyte_cfg_neigh_del_nojmp(ta, ifname, ip));
    return 0;
}

static te_errno
pyte_cfg_if_addr_add_nojmp(const char *ta, const char *ifname,
                           const char *ip, int prefix, int set_bcast)
{
    struct sockaddr_storage ss;
    socklen_t               len;
    te_errno                rc;

    rc = pyte_sockaddr_in4(ip, 0, &ss, &len);
    if (rc != 0)
        return rc;
    return tapi_cfg_base_if_add_net_addr(ta, ifname,
                                         (struct sockaddr *)&ss, prefix,
                                         set_bcast != 0, NULL);
}

te_errno
pyte_cfg_if_addr_add(const char *ta, const char *ifname, const char *ip,
                     int prefix, int set_bcast)
{
    PYTE_GUARD_RC(pyte_cfg_if_addr_add_nojmp(ta, ifname, ip, prefix,
                                             set_bcast));
    return 0;
}

te_errno
pyte_cfg_sys_get_str(const char *ta, const char *path, char **out)
{
    PYTE_GUARD_RC(tapi_cfg_sys_get_str(ta, out, "%s", path));
    return 0;
}

te_errno
pyte_cfg_sys_set_str(const char *ta, const char *path, const char *val)
{
    /* old_val == NULL: Python reads the previous value itself */
    PYTE_GUARD_RC(tapi_cfg_sys_set_str(ta, val, NULL, "%s", path));
    return 0;
}

te_errno
pyte_cfg_sys_get_int(const char *ta, const char *path, int *out)
{
    PYTE_GUARD_RC(tapi_cfg_sys_get_int(ta, out, "%s", path));
    return 0;
}

te_errno
pyte_cfg_sys_set_int(const char *ta, const char *path, int val,
                     int *old_val)
{
    PYTE_GUARD_RC(tapi_cfg_sys_set_int(ta, val, old_val, "%s", path));
    return 0;
}

te_errno
pyte_cfg_sys_get_uint64(const char *ta, const char *path, uint64_t *out)
{
    PYTE_GUARD_RC(tapi_cfg_sys_get_uint64(ta, out, "%s", path));
    return 0;
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

/*
 * TAD section.  NDN values cross the boundary as ASN.1 text; parsing
 * happens here so Python never holds an asn_value it did not create.
 * Everything is guarded; tapi_tad calls return te_errno (no longjmp),
 * but the guard keeps a surprise jump from unwinding into Python.
 */

static const asn_type *
pyte_ndn_kind_type(int kind)
{
    switch (kind)
    {
        case 0: return ndn_csap_spec;
        case 1: return ndn_traffic_template;
        case 2: return ndn_traffic_pattern;
        default: return NULL;
    }
}

static te_errno
pyte_asn_parse_nojmp(const char *text, int kind, asn_value **out,
                     char **err)
{
    const asn_type *type = pyte_ndn_kind_type(kind);
    int             syms = -1;
    te_errno        rc;

    if (err != NULL)
        *err = NULL;
    if (type == NULL)
        return TE_RC(TE_TAPI, TE_EINVAL);
    rc = asn_parse_value_text(text, type, out, &syms);
    if (rc != 0 && err != NULL &&
        asprintf(err, "parse failed at symbol %d", syms) < 0)
        *err = NULL;
    return rc;
}

te_errno
pyte_asn_check(const char *text, int kind, char **err)
{
    asn_value *val = NULL;

    PYTE_GUARD_RC(pyte_asn_parse_nojmp(text, kind, &val, err));
    asn_free_value(val);
    return 0;
}

te_errno
pyte_ta_session(const char *ta, int *out)
{
    PYTE_GUARD_RC(rcf_ta_create_session(ta, out));
    return 0;
}

static te_errno
pyte_csap_create_nojmp(const char *ta, int session, const char *stack_id,
                       const char *spec_text, unsigned int *out_csap)
{
    asn_value     *spec = NULL;
    csap_handle_t  csap = CSAP_INVALID_HANDLE;
    te_errno       rc;

    rc = pyte_asn_parse_nojmp(spec_text, 0, &spec, NULL);
    if (rc != 0)
        return rc;
    rc = tapi_tad_csap_create(ta, session, stack_id, spec, &csap);
    asn_free_value(spec);
    if (rc == 0)
        *out_csap = csap;
    return rc;
}

te_errno
pyte_csap_create(const char *ta, int session, const char *stack_id,
                 const char *spec_text, unsigned int *out_csap)
{
    PYTE_GUARD_RC(pyte_csap_create_nojmp(ta, session, stack_id,
                                         spec_text, out_csap));
    return 0;
}

te_errno
pyte_csap_destroy(const char *ta, int session, unsigned int csap)
{
    PYTE_GUARD_RC(tapi_tad_csap_destroy(ta, session, csap));
    return 0;
}

static te_errno
pyte_csap_send_nojmp(const char *ta, int session, unsigned int csap,
                     const char *templ_text, int blocking)
{
    asn_value *templ = NULL;
    te_errno   rc;

    rc = pyte_asn_parse_nojmp(templ_text, 1, &templ, NULL);
    if (rc != 0)
        return rc;
    rc = tapi_tad_trsend_start(ta, session, csap, templ,
                               blocking ? RCF_MODE_BLOCKING
                                        : RCF_MODE_NONBLOCKING);
    asn_free_value(templ);
    return rc;
}

te_errno
pyte_csap_send(const char *ta, int session, unsigned int csap,
               const char *templ_text, int blocking)
{
    PYTE_GUARD_RC(pyte_csap_send_nojmp(ta, session, csap, templ_text,
                                       blocking));
    return 0;
}

static te_errno
pyte_csap_recv_start_nojmp(const char *ta, int session, unsigned int csap,
                           const char *pattern_text,
                           unsigned int timeout_ms, unsigned int num)
{
    asn_value *pattern = NULL;
    te_errno   rc;

    rc = pyte_asn_parse_nojmp(pattern_text, 2, &pattern, NULL);
    if (rc != 0)
        return rc;
    rc = tapi_tad_trrecv_start(ta, session, csap, pattern, timeout_ms,
                               num, RCF_TRRECV_PACKETS);
    asn_free_value(pattern);
    return rc;
}

te_errno
pyte_csap_recv_start(const char *ta, int session, unsigned int csap,
                     const char *pattern_text, unsigned int timeout_ms,
                     unsigned int num)
{
    PYTE_GUARD_RC(pyte_csap_recv_start_nojmp(ta, session, csap,
                                             pattern_text, timeout_ms,
                                             num));
    return 0;
}

/*
 * Collector callback: takes ownership of the packet (tapi_tad's
 * trrecv handler does not free it once a callback is set) and stores
 * the pointer in the growing pyte_pkts array.
 *
 * Per-packet realloc is fine at test volumes; don't optimize without need.
 */
static void
pyte_pkt_collect_cb(asn_value *packet, void *user_data)
{
    pyte_pkts  *p = user_data;
    void      **grown;

    grown = realloc(p->pkts, (p->n + 1) * sizeof(*grown));
    if (grown == NULL)
    {
        asn_free_value(packet);
        return;
    }
    p->pkts = grown;
    p->pkts[p->n++] = packet;
}

static te_errno
pyte_csap_recv_fin_nojmp(const char *ta, int session, unsigned int csap,
                         pyte_pkts *out, int wait)
{
    tapi_tad_trrecv_cb_data cb = { pyte_pkt_collect_cb, out };
    unsigned int            num = 0;

    out->pkts = NULL;
    out->n = 0;
    return wait ? tapi_tad_trrecv_wait(ta, session, csap, &cb, &num)
                : tapi_tad_trrecv_stop(ta, session, csap, &cb, &num);
}

te_errno
pyte_csap_recv_stop(const char *ta, int session, unsigned int csap,
                    pyte_pkts *out)
{
    PYTE_GUARD_RC(pyte_csap_recv_fin_nojmp(ta, session, csap, out, 0));
    return 0;
}

te_errno
pyte_csap_recv_wait(const char *ta, int session, unsigned int csap,
                    pyte_pkts *out)
{
    PYTE_GUARD_RC(pyte_csap_recv_fin_nojmp(ta, session, csap, out, 1));
    return 0;
}

static te_errno
pyte_pkt_read_int_nojmp(void *pkt, const char *labels, int64_t *out)
{
    int32_t  v = 0;
    te_errno rc;

    rc = asn_read_int32(pkt, &v, labels);
    if (rc == 0)
        *out = v;
    return rc;
}

te_errno
pyte_pkt_read_int(void *pkt, const char *labels, int64_t *out)
{
    PYTE_GUARD_RC(pyte_pkt_read_int_nojmp(pkt, labels, out));
    return 0;
}

static te_errno
pyte_pkt_payload_nojmp(void *pkt, uint8_t *buf, size_t *len)
{
    int      needed;
    size_t   d_len;
    te_errno rc;

    needed = asn_get_length(pkt, "payload.#bytes");
    if (needed <= 0)
    {
        /* Absent or empty payload reads as empty */
        *len = 0;
        return 0;
    }
    if (buf == NULL || *len < (size_t)needed)
    {
        *len = needed;
        return TE_RC(TE_TAPI, TE_ESMALLBUF);
    }
    d_len = *len;
    rc = asn_read_value_field(pkt, buf, &d_len, "payload.#bytes");
    if (rc == 0)
        *len = d_len;
    return rc;
}

te_errno
pyte_pkt_payload(void *pkt, uint8_t *buf, size_t *len)
{
    PYTE_GUARD_RC(pyte_pkt_payload_nojmp(pkt, buf, len));
    return 0;
}

void
pyte_pkt_free(void *pkt)
{
    asn_free_value(pkt);
}

void
pyte_pkts_free(pyte_pkts *p)
{
    free(p->pkts);
    p->pkts = NULL;
    p->n = 0;
}

/* See pyte_shim.h: RCF direct API wrappers */

te_errno
pyte_rcf_ta_list(char *buf, size_t *len)
{
    PYTE_GUARD_RC(rcf_get_ta_list(buf, len));
    return 0;
}

te_errno
pyte_rcf_ta_type(const char *ta, char *buf)
{
    PYTE_GUARD_RC(rcf_ta_name2type(ta, buf));
    return 0;
}

te_errno
pyte_rcf_ta_info(const char *ta, char **type, char **rcflib,
                 char **confstr, unsigned int *flags)
{
    PYTE_GUARD_RC(rcf_get_ta(ta, type, rcflib, confstr, flags));
    return 0;
}

te_errno
pyte_rcf_put_file(const char *ta, const char *lfile, const char *rfile)
{
    PYTE_GUARD_RC(rcf_ta_put_file(ta, 0, lfile, rfile));
    return 0;
}

te_errno
pyte_rcf_get_file(const char *ta, const char *rfile, const char *lfile)
{
    PYTE_GUARD_RC(rcf_ta_get_file(ta, 0, rfile, lfile));
    return 0;
}

te_errno
pyte_rcf_del_file(const char *ta, const char *rfile)
{
    PYTE_GUARD_RC(rcf_ta_del_file(ta, 0, rfile));
    return 0;
}

te_errno
pyte_rcf_ta_restart(const char *ta, const char *boot_params)
{
    PYTE_GUARD_RC(rcf_ta_reboot(ta, boot_params, NULL,
                                RCF_REBOOT_TYPE_AGENT));
    return 0;
}

te_errno
pyte_rcf_ta_flush_logs(const char *ta)
{
    PYTE_GUARD_RC(log_flush_ten(ta));
    return 0;
}

te_errno
pyte_rcf_add_ta_unix(const char *name, const char *type, const char *host,
                     uint16_t port, unsigned int flags)
{
    /* copy/kill timeouts 0 = RCF defaults */
    PYTE_GUARD_RC(rcf_add_ta_unix(name, type, host, port, 0, 0, flags));
    return 0;
}

te_errno
pyte_rcf_del_ta(const char *name)
{
    PYTE_GUARD_RC(rcf_del_ta(name));
    return 0;
}

static te_errno
pyte_cfg_rcf_add_ta_nojmp(const char *ta, const char *type,
                          const char *rcflib, const char **kv,
                          unsigned int n_kv, unsigned int flags)
{
    te_kvpair_h conf;
    te_errno rc = 0;
    unsigned int i;

    te_kvpair_init(&conf);
    for (i = 0; i < n_kv && rc == 0; i++)
        rc = te_kvpair_add(&conf, kv[2 * i], "%s", kv[2 * i + 1]);
    if (rc == 0)
        rc = tapi_cfg_rcf_add_ta(ta, type, rcflib, &conf, flags);
    te_kvpair_fini(&conf);
    return rc;
}

te_errno
pyte_cfg_rcf_add_ta(const char *ta, const char *type, const char *rcflib,
                    const char **kv, unsigned int n_kv, unsigned int flags)
{
    PYTE_GUARD_RC(pyte_cfg_rcf_add_ta_nojmp(ta, type, rcflib, kv, n_kv,
                                            flags));
    return 0;
}

te_errno
pyte_cfg_rcf_del_ta(const char *ta)
{
    PYTE_GUARD_RC(tapi_cfg_rcf_del_ta(ta));
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

/* -- tapi_env ---------------------------------------------------------- */

te_errno
pyte_env_new(tapi_env **out)
{
    tapi_env *env = TE_ALLOC(sizeof(*env));

    PYTE_GUARD_RC(tapi_env_init(env));
    *out = env;
    return 0;
}

te_errno
pyte_env_get(const char *cfg, tapi_env *env)
{
    PYTE_GUARD_RC(tapi_env_get(cfg, env));
    return 0;
}

te_errno
pyte_env_free(tapi_env *env)
{
    te_errno rc = 0;

    PYTE_GUARD(rc = tapi_env_free(env));
    free(env);
    return rc;
}

te_errno
pyte_env_get_pco(tapi_env *env, const char *name, rcf_rpc_server **out)
{
    rcf_rpc_server *rpcs = NULL;

    PYTE_GUARD(rpcs = tapi_env_get_pco(env, name));
    if (rpcs == NULL)
        return TE_RC(TE_TAPI, TE_ENOENT);
    *out = rpcs;
    return 0;
}

te_errno
pyte_rpc_server_ta_name(rcf_rpc_server *rpcs, char **ta)
{
    *ta = strdup(rpcs->ta);
    return (*ta == NULL) ? TE_RC(TE_TAPI, TE_ENOMEM) : 0;
}

te_errno
pyte_env_get_addr(tapi_env *env, const char *name, char **addr_str,
                  char **family, int *port)
{
    const struct sockaddr *sa = NULL;
    socklen_t salen = 0;
    char buf[128];
    uint16_t p = 0;
    te_errno rc;

    PYTE_GUARD(sa = tapi_env_get_addr(env, name, &salen));
    if (sa == NULL)
        return TE_RC(TE_TAPI, TE_ENOENT);

    if (sa->sa_family == AF_LOCAL)
    {
        /* ether address: bytes in sa_data (same convention as the cfg
         * CVT_ADDRESS rendering) */
        const uint8_t *m = (const uint8_t *)sa->sa_data;

        snprintf(buf, sizeof(buf), "%02x:%02x:%02x:%02x:%02x:%02x",
                 m[0], m[1], m[2], m[3], m[4], m[5]);
        *family = strdup("ether");
        *port = 0;
    }
    else
    {
        rc = pyte_sockaddr_parse(sa, buf, sizeof(buf), &p);
        if (rc != 0)
            return rc;
        *family = strdup(sa->sa_family == AF_INET6 ? "inet6" : "inet");
        *port = p;
    }
    *addr_str = strdup(buf);
    if (*family == NULL || *addr_str == NULL)
    {
        free(*family);
        free(*addr_str);
        *family = NULL;
        *addr_str = NULL;
        return TE_RC(TE_TAPI, TE_ENOMEM);
    }
    return 0;
}

te_errno
pyte_env_get_if(tapi_env *env, const char *name, char **ifname,
                unsigned int *ifindex)
{
    const struct if_nameindex *ifi = NULL;

    PYTE_GUARD(ifi = tapi_env_get_if(env, name));
    if (ifi == NULL)
        return TE_RC(TE_TAPI, TE_ENOENT);
    *ifname = strdup(ifi->if_name);
    if (*ifname == NULL)
        return TE_RC(TE_TAPI, TE_ENOMEM);
    *ifindex = ifi->if_index;
    return 0;
}

te_errno
pyte_env_get_if_ta(tapi_env *env, const char *name, char **ta)
{
    const tapi_env_if *eif = NULL;

    PYTE_GUARD(eif = tapi_env_get_env_if(env, name));
    if (eif == NULL || eif->host == NULL || eif->host->ta == NULL)
        return TE_RC(TE_TAPI, TE_ENOENT);
    *ta = strdup(eif->host->ta);
    return (*ta == NULL) ? TE_RC(TE_TAPI, TE_ENOMEM) : 0;
}

te_errno
pyte_env_get_host_ta(tapi_env *env, const char *name, char **ta)
{
    tapi_env_host *host = NULL;

    if (name != NULL && name[0] == '\0')
    {
        /* env_gram.y inserts with SLIST_INSERT_HEAD, so the tail is
         * the first-declared entity */
        tapi_env_host *iter;

        SLIST_FOREACH(iter, &env->hosts, links)
            host = iter;
    }
    else
    {
        PYTE_GUARD(host = tapi_env_get_host(env, name));
    }
    if (host == NULL || host->ta == NULL)
        return TE_RC(TE_TAPI, TE_ENOENT);
    *ta = strdup(host->ta);
    return (*ta == NULL) ? TE_RC(TE_TAPI, TE_ENOMEM) : 0;
}

te_errno
pyte_env_get_net_subnet(tapi_env *env, const char *name, int ipv6,
                        char **subnet, unsigned int *prefix)
{
    tapi_env_net *net = NULL;
    const struct sockaddr *sa;
    char buf[64];
    uint16_t port_unused = 0;
    te_errno rc;

    if (name != NULL && name[0] == '\0')
    {
        /* env_gram.y inserts with SLIST_INSERT_HEAD, so the tail is
         * the first-declared entity */
        tapi_env_net *iter;

        SLIST_FOREACH(iter, &env->nets, links)
            net = iter;
    }
    else
    {
        PYTE_GUARD(net = tapi_env_get_net(env, name));
    }
    if (net == NULL)
        return TE_RC(TE_TAPI, TE_ENOENT);

    sa = ipv6 ? net->ip6addr : net->ip4addr;
    if (sa == NULL)
        return TE_RC(TE_TAPI, TE_ENODATA);
    rc = pyte_sockaddr_parse(sa, buf, sizeof(buf), &port_unused);
    if (rc == 0)
    {
        *subnet = strdup(buf);
        if (*subnet == NULL)
            return TE_RC(TE_TAPI, TE_ENOMEM);
        *prefix = ipv6 ? net->ip6pfx : net->ip4pfx;
    }
    return rc;
}

te_errno
pyte_allocate_port(rcf_rpc_server *rpcs, unsigned int *port)
{
    uint16_t p = 0;

    PYTE_GUARD_RC(tapi_allocate_port(rpcs, &p));
    *port = p;
    return 0;
}

te_errno
pyte_cfg_net_all_assign_ip(int ipv6)
{
    PYTE_GUARD_RC(tapi_cfg_net_all_assign_ip(ipv6 ? AF_INET6 : AF_INET));
    return 0;
}

static te_errno
pyte_cfg_net_assign_subnet_nojmp(const char *net_name, int ipv6)
{
    te_errno rc;
    cfg_handle net_handle = CFG_HANDLE_INVALID;
    cfg_handle pool_hndl = CFG_HANDLE_INVALID;
    struct sockaddr *net_addr = NULL;

    /* The subnet-attach half of tapi_cfg_net_assign_ip(): allocate a
     * pool entry and add it as /net:<name>/ipN_subnet:<handle>.  Node
     * addresses are deliberately NOT assigned (that needs root). */
    rc = cfg_find_fmt(&net_handle, "/net:%s", net_name);
    if (rc != 0)
        return rc;
    rc = tapi_cfg_alloc_entry(ipv6 ? "/net_pool:ip6" : "/net_pool:ip4",
                              &pool_hndl);
    if (rc != 0)
        return rc;
    rc = cfg_get_inst_name_type(pool_hndl, CVT_ADDRESS,
                                CFG_IVP(&net_addr));
    if (rc != 0)
        return rc;
    rc = cfg_add_instance_child_fmt(NULL, CVT_ADDRESS, net_addr,
                                    net_handle, "/ip%u_subnet:0x%jx",
                                    ipv6 ? 6 : 4, (uintmax_t)pool_hndl);
    free(net_addr);
    return rc;
}

te_errno
pyte_cfg_net_assign_subnet(const char *net_name, int ipv6)
{
    PYTE_GUARD_RC(pyte_cfg_net_assign_subnet_nojmp(net_name, ipv6));
    return 0;
}

/*
 * Tester section: runtime requirement filtering and TRC tags.
 * Both calls are intended for the root prologue; TE itself enforces
 * the restriction via EPERM for tapi_tags_add_tag.
 */

te_errno
pyte_reqs_modify(const char *reqs)
{
    te_errno rc = 0;

    PYTE_GUARD(rc = tapi_reqs_modify(reqs));
    return rc;
}

te_errno
pyte_tags_add_tag(const char *tag, const char *value)
{
    te_errno rc = 0;

    PYTE_GUARD(rc = tapi_tags_add_tag(tag, value));
    return rc;
}

/*
 * TRC accessors are in pyte_trc.c — kept separate to avoid the
 * te_test_verdict name collision between te_test_result.h (struct typedef)
 * and tapi_test_log.h (function declaration).
 */

/*
 * iomux section (tapi_iomux wrappers).
 *
 * tapi_iomux functions longjmp via TEST_FAIL/TEST_VERDICT on errors, so
 * every body is wrapped in PYTE_GUARD.  The TAPI manages RPC_AWAIT_IUT_ERROR
 * internally (see tapi_iomux_epoll_create/add/mod/del in tapi_iomux.c); we
 * must NOT re-arm RPC_AWAIT_ERROR around these calls — doing so would
 * interfere with the TAPI's own error-handling logic.
 *
 * tapi_iomux_call returns the number of ready events (0 = timeout, -1 =
 * error).  The TAPI raises a verdict on -1 before returning, so inside
 * PYTE_GUARD a negative return from tapi_iomux_call means the test is
 * already failing.  We treat n < 0 after a clean guard as a programming
 * error and return TE_EFAIL; in practice this code path is unreachable.
 *
 * The revts array is owned by the iomux handle and is valid until the next
 * call or destroy.  We copy the two fields we need (fd and revents) into
 * separate malloc'ed int[] arrays so Python can read them after returning
 * from the C frame.  The arrays are freed with pyte_free_ints().
 */

te_errno
pyte_iomux_create(rcf_rpc_server *rpcs, int type,
                  tapi_iomux_handle **out)
{
    tapi_iomux_handle *h;

    PYTE_GUARD(h = tapi_iomux_create(rpcs, (tapi_iomux_type)type));
    if (h == NULL)
        return TE_RC(TE_TAPI, TE_EFAIL);
    *out = h;
    return 0;
}

te_errno
pyte_iomux_add(tapi_iomux_handle *h, int fd, int evt)
{
    PYTE_GUARD(tapi_iomux_add(h, fd, (tapi_iomux_evt)evt));
    return 0;
}

te_errno
pyte_iomux_mod(tapi_iomux_handle *h, int fd, int evt)
{
    PYTE_GUARD(tapi_iomux_mod(h, fd, (tapi_iomux_evt)evt));
    return 0;
}

te_errno
pyte_iomux_del(tapi_iomux_handle *h, int fd)
{
    PYTE_GUARD(tapi_iomux_del(h, fd));
    return 0;
}

static te_errno
pyte_iomux_call_nojmp(tapi_iomux_handle *h, int timeout_ms,
                      int *n_out, int **revts_out)
{
    tapi_iomux_evt_fd *revts = NULL;
    int                n;
    int               *buf = NULL;
    int                i;

    n = tapi_iomux_call(h, timeout_ms, &revts);
    if (n < 0)
        return TE_RC(TE_TAPI, TE_EFAIL);

    *n_out = n;
    *revts_out = NULL;

    if (n == 0)
        return 0;

    /*
     * Pack [fd0, evt0, fd1, evt1, ...] into a single int[2*n] array.
     * Python unpacks fds as buf[0::2] and evts as buf[1::2], then calls
     * pyte_free_ints() once to release it.
     */
    buf = malloc(2 * (size_t)n * sizeof(*buf));
    if (buf == NULL)
        return TE_RC(TE_TAPI, TE_ENOMEM);

    for (i = 0; i < n; i++)
    {
        buf[2 * i]     = revts[i].fd;
        buf[2 * i + 1] = (int)revts[i].revents;
    }

    *revts_out = buf;
    return 0;
}

te_errno
pyte_iomux_call(tapi_iomux_handle *h, int timeout_ms,
                int *n_out, int **revts_out)
{
    PYTE_GUARD_RC(pyte_iomux_call_nojmp(h, timeout_ms, n_out, revts_out));
    return 0;
}

te_errno
pyte_iomux_destroy(tapi_iomux_handle *h)
{
    PYTE_GUARD(tapi_iomux_destroy(h));
    return 0;
}

void
pyte_free_ints(int *p)
{
    free(p);
}

/*
 * sendmsg / recvmsg section.
 *
 * rpc_msghdr conventions (verified against tapi_rpc_socket.h and
 * tapi_rpc_internal.c):
 *
 * Scatter SEND (no cmsgs):
 *   Set msg_iov[i].{iov_base,iov_len,iov_rlen}, msg_iovlen, msg_riovlen.
 *   Leave msg_control=NULL, msg_controllen=0.  msg_name/msg_namelen only
 *   when sending to an unconnected address.
 *
 * Send WITH cmsgs:
 *   Additionally set msg_control = native cmsg buffer built with
 *   CMSG_SPACE/CMSG_FIRSTHDR/CMSG_NXTHDR/CMSG_DATA, msg_controllen =
 *   total buffer size, msg_cmsghdr_num = number of cmsgs.  Leave
 *   msg_control_mode at RPC_MSGHDR_FIELD_DEFAULT (0): for send calls the
 *   internal layer converts the buffer regardless.
 *   real_msg_controllen is NOT needed on send (it is only used to override
 *   msg_controllen on receive).
 *
 * RECV with control space:
 *   Allocate a buffer of ctrl_space bytes, set msg_control = buffer,
 *   msg_controllen = ctrl_space, real_msg_controllen = ctrl_space (this
 *   forces the internal layer to use real_msg_controllen as the true buffer
 *   size), msg_cmsghdr_num = 0 (zero is correct: the layer fills it after
 *   the call).  Leave msg_control_mode = RPC_MSGHDR_FIELD_DEFAULT (0);
 *   the returned buffer is rebuilt from TARPC records by
 *   msg_control_rpc2h (see the cmsg note below).  After the call:
 *     got_msg_controllen = actual bytes returned by the kernel;
 *     msg_cmsghdr_num    = number of complete cmsghdr records;
 *     msg_controllen     = bytes written into msg_control.
 *   Parse msg_control with CMSG_FIRSTHDR/CMSG_NXTHDR over msg_controllen
 *   (not got_msg_controllen).
 *
 * struct rpc_iovec fields:
 *   iov_base — pointer to data buffer
 *   iov_len  — advertised length (the value the remote sees)
 *   iov_rlen — real number of bytes to copy across the RPC boundary;
 *              for send: iov_rlen == iov_len; for recv: iov_rlen = buffer
 *              capacity so the RPC layer can fill it.
 *
 * Ancillary data / cmsg note:
 *   msg_control does NOT cross the RPC as a raw native cmsghdr buffer.
 *   The engine-side helpers (lib/rpc_types/sys_socket.c.rpch:
 *   msg_control_h2rpc / msg_control_rpc2h) decompose each cmsghdr into
 *   host-independent TARPC records — cmsg_level via socklevel_h2rpc,
 *   cmsg_type via cmsg_type_h2rpc, data via cmsg_data_h2rpc — and
 *   reconstruct a native buffer on each side from those records.  No
 *   shared ABI between engine and agent is required.
 *
 *   Caveat: only TE-known socket levels and cmsg types survive the
 *   round-trip.  Supported levels: SOL_SOCKET, IPPROTO_IP, IPPROTO_IPV6,
 *   IPPROTO_TCP, IPPROTO_UDP (and their known cmsg types, e.g.
 *   IP_PKTINFO, IPV6_PKTINFO, SO_TIMESTAMP).  Unknown values map to
 *   RPC_SOL_UNKNOWN / RPC_SOCKOPT_UNKNOWN and do not survive usefully:
 *   the remote side rebuilds them with SOL_MAX and logs a WARN
 *   (socklevel_rpc2h), so the record arrives mangled, not dropped.
 *
 *   On receive: the shim passes a zeroed ctrl buffer (msg_cmsghdr_num=0);
 *   the RPC layer fills it from the TARPC records returned by the agent,
 *   rebuilding a native cmsghdr chain.  The shim then parses that chain
 *   with CMSG_FIRSTHDR / CMSG_NXTHDR.  Only records with TE-known
 *   level/type are present; all others are absent from the rebuilt chain.
 *
 * RPC_AWAIT_ERROR:
 *   Re-armed before each rpc_* call (TE resets the await flag after every
 *   call; re-arming is mandatory for direct rpc_ wrappers — same pattern
 *   as pyte_rpc_sendto and all other pyte RPC wrappers).  This is
 *   intentionally different from the iomux section where PYTE_GUARD replaces
 *   the TAPI's internal await logic.
 */

#include <sys/socket.h>

static te_errno
pyte_rpc_sendmsg_nojmp(rcf_rpc_server *rpcs, int s,
                        const uint8_t **iov_bufs, const size_t *iov_lens,
                        unsigned int n_iov,
                        const char *addr, int port,
                        const int *cmsg_levels, const int *cmsg_types,
                        const uint8_t **cmsg_datas, const size_t *cmsg_lens,
                        unsigned int n_cmsg, int flags, ssize_t *sent)
{
    rpc_iovec  *iov = NULL;
    rpc_msghdr  msg;
    uint8_t    *ctrl = NULL;
    struct sockaddr_storage ss;
    socklen_t   sslen = 0;
    ssize_t     rc_send;
    unsigned int i;
    te_errno    rc = 0;

    memset(&msg, 0, sizeof(msg));

    /* --- scatter-gather buffers --- */
    if (n_iov > 0)
    {
        iov = calloc(n_iov, sizeof(*iov));
        if (iov == NULL)
            return TE_RC(TE_TAPI, TE_ENOMEM);
        for (i = 0; i < n_iov; i++)
        {
            iov[i].iov_base = (void *)(uintptr_t)iov_bufs[i];
            iov[i].iov_len  = iov_lens[i];
            iov[i].iov_rlen = iov_lens[i];
        }
    }
    msg.msg_iov    = iov;
    msg.msg_iovlen = n_iov;
    msg.msg_riovlen = n_iov;

    /* --- destination address --- */
    if (addr != NULL && addr[0] != '\0')
    {
        rc = pyte_sockaddr_in4(addr, (uint16_t)port, &ss, &sslen);
        if (rc != 0)
        {
            free(iov);
            return rc;
        }
        msg.msg_name    = &ss;
        msg.msg_namelen = sslen;
    }

    /* --- ancillary (control) data --- */
    if (n_cmsg > 0)
    {
        /* Calculate total buffer size */
        size_t ctrl_size = 0;

        for (i = 0; i < n_cmsg; i++)
            ctrl_size += CMSG_SPACE(cmsg_lens[i]);

        ctrl = calloc(1, ctrl_size);
        if (ctrl == NULL)
        {
            free(iov);
            return TE_RC(TE_TAPI, TE_ENOMEM);
        }

        /* Fill native cmsg buffer */
        struct msghdr tmp = { .msg_control = ctrl,
                              .msg_controllen = ctrl_size };
        struct cmsghdr *c = CMSG_FIRSTHDR(&tmp);

        for (i = 0; i < n_cmsg; i++)
        {
            if (c == NULL)
            {
                free(ctrl);
                free(iov);
                return TE_RC(TE_TAPI, TE_EINVAL);
            }
            c->cmsg_level = cmsg_levels[i];
            c->cmsg_type  = cmsg_types[i];
            c->cmsg_len   = CMSG_LEN(cmsg_lens[i]);
            memcpy(CMSG_DATA(c), cmsg_datas[i], cmsg_lens[i]);
            c = CMSG_NXTHDR(&tmp, c);
        }

        msg.msg_control    = ctrl;
        msg.msg_controllen = ctrl_size;
        msg.msg_cmsghdr_num = (int)n_cmsg;
        /* msg_control_mode stays RPC_MSGHDR_FIELD_DEFAULT (0):
         * the internal layer converts send control buffers by default */
    }

    RPC_AWAIT_ERROR(rpcs);
    rc_send = rpc_sendmsg(rpcs, s, &msg, (rpc_send_recv_flags)flags);

    free(ctrl);
    free(iov);

    /*
     * Store the raw retval (negative on failure) and return 0 so that
     * the Python _check_call(rc, sent[0], ok=lambda v: v >= 0) can
     * surface the remote errno or suppress it under expect_error().
     * Mirror pyte_rpc_sendto: do NOT convert a failed call to TE_EFAIL.
     */
    *sent = rc_send;
    return 0;
}

te_errno
pyte_rpc_sendmsg(rcf_rpc_server *rpcs, int s,
                 const uint8_t **iov_bufs, const size_t *iov_lens,
                 unsigned int n_iov,
                 const char *addr, int port,
                 const int *cmsg_levels, const int *cmsg_types,
                 const uint8_t **cmsg_datas, const size_t *cmsg_lens,
                 unsigned int n_cmsg, int flags, ssize_t *sent)
{
    PYTE_GUARD_RC(pyte_rpc_sendmsg_nojmp(rpcs, s, iov_bufs, iov_lens, n_iov,
                                          addr, port, cmsg_levels, cmsg_types,
                                          cmsg_datas, cmsg_lens, n_cmsg,
                                          flags, sent));
    return 0;
}

static te_errno
pyte_rpc_recvmsg_nojmp(rcf_rpc_server *rpcs, int s, size_t bufsize,
                        size_t ctrl_space, int flags,
                        uint8_t **data, size_t *data_len,
                        char **from_addr, int *from_port,
                        int **cmsg_levels, int **cmsg_types,
                        uint8_t ***cmsg_datas, size_t **cmsg_lens,
                        unsigned int *n_cmsg, int *msg_flags,
                        ssize_t *received)
{
    rpc_iovec  iov;
    rpc_msghdr msg;
    uint8_t   *databuf = NULL;
    uint8_t   *ctrl = NULL;
    struct sockaddr_storage ss;
    ssize_t    rc_recv;
    unsigned int nc;
    unsigned int i;
    char       addrbuf[64];
    uint16_t   port = 0;
    te_errno   rc = 0;

    memset(&msg, 0, sizeof(msg));
    memset(&iov, 0, sizeof(iov));
    memset(&ss, 0, sizeof(ss));

    /* --- single receive buffer --- */
    databuf = malloc(bufsize);
    if (databuf == NULL)
        return TE_RC(TE_TAPI, TE_ENOMEM);
    memset(databuf, 0, bufsize);

    iov.iov_base = databuf;
    iov.iov_len  = bufsize;
    iov.iov_rlen = bufsize;

    msg.msg_iov    = &iov;
    msg.msg_iovlen = 1;
    msg.msg_riovlen = 1;

    /* --- source address buffer --- */
    msg.msg_name    = &ss;
    msg.msg_namelen = sizeof(ss);
    msg.msg_rnamelen = sizeof(ss);

    /* --- control buffer --- */
    if (ctrl_space > 0)
    {
        ctrl = calloc(1, ctrl_space);
        if (ctrl == NULL)
        {
            free(databuf);
            return TE_RC(TE_TAPI, TE_ENOMEM);
        }
        msg.msg_control             = ctrl;
        msg.msg_controllen          = ctrl_space;
        msg.real_msg_controllen     = ctrl_space;
        /* msg_cmsghdr_num stays 0: the RPC layer fills it after the call */
        /* msg_control_mode stays RPC_MSGHDR_FIELD_DEFAULT (0): the RPC
         * layer rebuilds the returned cmsghdr chain from TARPC records */
    }

    msg.msg_flags_mode = RPC_MSG_FLAGS_NO_CHECK;

    RPC_AWAIT_ERROR(rpcs);
    rc_recv = rpc_recvmsg(rpcs, s, &msg, (rpc_send_recv_flags)flags);

    if (rc_recv < 0)
    {
        /*
         * Store the raw retval and NULL all out-pointers so the Python
         * facade can safely skip unpacking.  Return 0 so that
         * _check_call(rc, received[0], ok=lambda v: v >= 0) surfaces the
         * remote errno or suppresses it under expect_error().
         * Mirror pyte_rpc_sendto: do NOT convert to TE_EFAIL.
         */
        free(ctrl);
        free(databuf);
        *data       = NULL;
        *data_len   = 0;
        *from_addr  = NULL;
        *from_port  = 0;
        *cmsg_levels = NULL;
        *cmsg_types  = NULL;
        *cmsg_datas  = NULL;
        *cmsg_lens   = NULL;
        *n_cmsg      = 0;
        *msg_flags   = 0;
        *received    = rc_recv;
        return 0;
    }

    /* --- hand off data buffer to caller --- */
    *data     = databuf;
    *data_len = (size_t)rc_recv;
    *received = rc_recv;

    /* --- source address --- */
    if (msg.msg_namelen > 0 &&
        ((struct sockaddr *)&ss)->sa_family != AF_UNSPEC)
    {
        rc = pyte_sockaddr_parse((struct sockaddr *)&ss,
                                 addrbuf, sizeof(addrbuf), &port);
        if (rc != 0)
        {
            free(ctrl);
            free(databuf);
            return rc;
        }
        *from_addr = strdup(addrbuf);
        if (*from_addr == NULL)
        {
            free(ctrl);
            free(databuf);
            return TE_RC(TE_TAPI, TE_ENOMEM);
        }
        *from_port = port;
    }
    else
    {
        *from_addr = strdup("");
        if (*from_addr == NULL)
        {
            free(ctrl);
            free(databuf);
            return TE_RC(TE_TAPI, TE_ENOMEM);
        }
        *from_port = 0;
    }

    /* --- parse ancillary data --- */
    nc = 0;
    *cmsg_levels = NULL;
    *cmsg_types  = NULL;
    *cmsg_datas  = NULL;
    *cmsg_lens   = NULL;
    *n_cmsg      = 0;
    *msg_flags   = (int)msg.msg_flags;

    if (ctrl != NULL && msg.msg_controllen > 0)
    {
        struct msghdr tmp = { .msg_control = ctrl,
                              .msg_controllen = msg.msg_controllen };
        struct cmsghdr *c;
        int           *lvls = NULL;
        int           *typs = NULL;
        uint8_t      **datas_arr = NULL;
        size_t        *lens_arr = NULL;

        /* first pass: count */
        for (c = CMSG_FIRSTHDR(&tmp); c != NULL; c = CMSG_NXTHDR(&tmp, c))
            nc++;

        if (nc > 0)
        {
            lvls      = malloc(nc * sizeof(*lvls));
            typs      = malloc(nc * sizeof(*typs));
            datas_arr = malloc(nc * sizeof(*datas_arr));
            lens_arr  = malloc(nc * sizeof(*lens_arr));

            if (lvls == NULL || typs == NULL ||
                datas_arr == NULL || lens_arr == NULL)
            {
                free(lvls);
                free(typs);
                free(datas_arr);
                free(lens_arr);
                free(ctrl);
                free(databuf);
                free(*from_addr);
                *from_addr = NULL;
                return TE_RC(TE_TAPI, TE_ENOMEM);
            }

            /* second pass: fill */
            i = 0;
            for (c = CMSG_FIRSTHDR(&tmp); c != NULL;
                 c = CMSG_NXTHDR(&tmp, c), i++)
            {
                size_t dlen = c->cmsg_len -
                              ((uint8_t *)CMSG_DATA(c) - (uint8_t *)c);

                lvls[i]      = c->cmsg_level;
                typs[i]      = c->cmsg_type;
                lens_arr[i]  = dlen;
                datas_arr[i] = malloc(dlen);
                if (datas_arr[i] == NULL)
                {
                    /* free already-allocated data buffers */
                    unsigned int j;

                    for (j = 0; j < i; j++)
                        free(datas_arr[j]);
                    free(lvls);
                    free(typs);
                    free(datas_arr);
                    free(lens_arr);
                    free(ctrl);
                    free(databuf);
                    free(*from_addr);
                    *from_addr = NULL;
                    return TE_RC(TE_TAPI, TE_ENOMEM);
                }
                memcpy(datas_arr[i], CMSG_DATA(c), dlen);
            }

            *cmsg_levels = lvls;
            *cmsg_types  = typs;
            *cmsg_datas  = datas_arr;
            *cmsg_lens   = lens_arr;
        }
    }

    *n_cmsg = nc;
    free(ctrl);
    return 0;
}

te_errno
pyte_rpc_recvmsg(rcf_rpc_server *rpcs, int s, size_t bufsize,
                 size_t ctrl_space, int flags,
                 uint8_t **data, size_t *data_len,
                 char **from_addr, int *from_port,
                 int **cmsg_levels, int **cmsg_types,
                 uint8_t ***cmsg_datas, size_t **cmsg_lens,
                 unsigned int *n_cmsg, int *msg_flags,
                 ssize_t *received)
{
    PYTE_GUARD_RC(pyte_rpc_recvmsg_nojmp(rpcs, s, bufsize, ctrl_space, flags,
                                          data, data_len, from_addr, from_port,
                                          cmsg_levels, cmsg_types, cmsg_datas,
                                          cmsg_lens, n_cmsg, msg_flags,
                                          received));
    return 0;
}

void
pyte_free_cmsgs(int *levels, int *types, uint8_t **datas,
                size_t *lens, unsigned int n)
{
    unsigned int i;

    for (i = 0; i < n; i++)
        free(datas[i]);
    free(levels);
    free(types);
    free(datas);
    free(lens);
}

/* ---- te_mi thin wrappers ---- */

te_errno
pyte_mi_meas_create(const char *tool, te_mi_logger **out)
{
    return te_mi_logger_meas_create(tool, out);
}

te_errno
pyte_mi_add_meas(te_mi_logger *logger, int type, const char *name,
                 int aggr, double val, int multiplier)
{
    te_errno retval = 0;

    te_mi_logger_add_meas(logger, &retval,
                          (te_mi_meas_type)type, name,
                          (te_mi_meas_aggr)aggr, val,
                          (te_mi_meas_multiplier)multiplier);
    return retval;
}

te_errno
pyte_mi_destroy(te_mi_logger *logger)
{
    te_mi_logger_destroy(logger);
    return 0;
}
