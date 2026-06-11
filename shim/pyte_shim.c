/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright (C) 2026 Konstantin Ushakov */
#include <stdlib.h>
#include <string.h>

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
    return TE_RC(TE_TAPI, TE_EAFNOSUPPORT);
}
