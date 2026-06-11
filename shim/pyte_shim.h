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

#include <arpa/inet.h>
#include <netinet/in.h>

#include "rcf_rpc.h"
#include "te_rpc_sys_socket.h"
#include "te_rpc_sys_stat.h"
#include "te_rpc_fcntl.h"
#include "tapi_rpc_socket.h"
#include "tapi_rpc_unistd.h"
#include "tapi_rpc_stdio.h"

#define PYTE_ETIMEDOUT TE_ETIMEDOUT
#define PYTE_ECONNREFUSED TE_ECONNREFUSED
#define PYTE_ENOENT TE_ENOENT

/* RPC constant passthrough: cffi-friendly ints with verified values */
#define PYTE_PF_INET RPC_PF_INET
#define PYTE_PF_INET6 RPC_PF_INET6
#define PYTE_PF_LOCAL RPC_PF_LOCAL
#define PYTE_SOCK_STREAM RPC_SOCK_STREAM
#define PYTE_SOCK_DGRAM RPC_SOCK_DGRAM
#define PYTE_PROTO_DEF RPC_PROTO_DEF
#define PYTE_O_RDONLY RPC_O_RDONLY
#define PYTE_O_WRONLY RPC_O_WRONLY
#define PYTE_O_RDWR RPC_O_RDWR
#define PYTE_O_CREAT RPC_O_CREAT
#define PYTE_O_TRUNC RPC_O_TRUNC
#define PYTE_O_APPEND RPC_O_APPEND
/* rpc_open() mode is an RPC bitmap (te_rpc_sys_stat.h), not raw octal */
#define PYTE_MODE_0644 \
    (RPC_S_IRUSR | RPC_S_IWUSR | RPC_S_IRGRP | RPC_S_IROTH)

extern void pyte_log_init(const char *entity);
extern void pyte_log(unsigned int level, const char *user, const char *text);
extern void pyte_step(const char *text);
extern void pyte_substep(const char *text);
extern void pyte_verdict(unsigned int level, const char *text);
extern void pyte_artifact(unsigned int level, const char *text);
extern unsigned int pyte_rc_module(unsigned int rc);
extern unsigned int pyte_rc_error(unsigned int rc);
extern void pyte_free_string(char *p);

/* RPC server lifecycle and error introspection */
extern te_errno pyte_rpc_server_create(const char *ta, const char *name,
                                       rcf_rpc_server **out);
extern te_errno pyte_rpc_server_destroy(rcf_rpc_server *rpcs);
extern int pyte_rpc_errno(rcf_rpc_server *rpcs);
extern const char *pyte_rpc_err_msg(rcf_rpc_server *rpcs);
extern void pyte_rpc_set_timeout(rcf_rpc_server *rpcs, uint32_t ms);

/* Guarded RPC wrappers: re-arm RPC_AWAIT_ERROR, confine longjmp */
extern te_errno pyte_rpc_socket(rcf_rpc_server *rpcs, int domain, int type,
                                int proto, int *out_fd);
extern te_errno pyte_rpc_bind(rcf_rpc_server *rpcs, int s,
                              const struct sockaddr *addr, int *out);
extern te_errno pyte_rpc_connect(rcf_rpc_server *rpcs, int s,
                                 const struct sockaddr *addr, int *out);
extern te_errno pyte_rpc_listen(rcf_rpc_server *rpcs, int s, int backlog,
                                int *out);
extern te_errno pyte_rpc_accept(rcf_rpc_server *rpcs, int s,
                                struct sockaddr *addr, socklen_t *addrlen,
                                int *out);
extern te_errno pyte_rpc_send(rcf_rpc_server *rpcs, int s,
                              const uint8_t *buf, size_t len, int flags,
                              ssize_t *out);
extern te_errno pyte_rpc_recv(rcf_rpc_server *rpcs, int s, uint8_t *buf,
                              size_t len, int flags, ssize_t *out);
extern te_errno pyte_rpc_sendto(rcf_rpc_server *rpcs, int s,
                                const uint8_t *buf, size_t len, int flags,
                                const struct sockaddr *to, ssize_t *out);
/* fromlen should be non-NULL; NULL means no room for the peer address */
extern te_errno pyte_rpc_recvfrom(rcf_rpc_server *rpcs, int s,
                                  uint8_t *buf, size_t len, int flags,
                                  struct sockaddr *from, socklen_t *fromlen,
                                  ssize_t *out);
extern te_errno pyte_rpc_getsockname(rcf_rpc_server *rpcs, int s,
                                     struct sockaddr *name,
                                     socklen_t *namelen, int *out);
extern te_errno pyte_rpc_close(rcf_rpc_server *rpcs, int fd, int *out);
extern te_errno pyte_rpc_open(rcf_rpc_server *rpcs, const char *path,
                              int flags, int mode, int *out);
extern te_errno pyte_rpc_read(rcf_rpc_server *rpcs, int fd, uint8_t *buf,
                              size_t count, int *out);
extern te_errno pyte_rpc_write(rcf_rpc_server *rpcs, int fd,
                               const uint8_t *buf, size_t count, int *out);
extern te_errno pyte_rpc_unlink(rcf_rpc_server *rpcs, const char *path,
                                int *out);
extern te_errno pyte_rpc_getpid(rcf_rpc_server *rpcs, int *out);
extern te_errno pyte_rpc_gethostname(rcf_rpc_server *rpcs, char *buf,
                                     size_t len, int *out);
extern te_errno pyte_rpc_shell_get_all(rcf_rpc_server *rpcs, char **out_buf,
                                       const char *cmd, int *out_flag,
                                       int *out_value);

/* Local sockaddr helpers (no RPC involved) */
extern te_errno pyte_sockaddr_in4(const char *ip, uint16_t port,
                                  struct sockaddr_storage *ss,
                                  socklen_t *len);
extern te_errno pyte_sockaddr_parse(const struct sockaddr *sa, char *ipbuf,
                                    size_t ipbuflen, uint16_t *port);

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
