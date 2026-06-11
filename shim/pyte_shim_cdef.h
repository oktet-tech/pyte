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

typedef int... te_errno;
typedef struct rcf_rpc_server rcf_rpc_server;
typedef int... socklen_t;
typedef long... ssize_t;
struct sockaddr { ...; };
struct sockaddr_storage { ...; };

te_errno pyte_rpc_server_create(const char *ta, const char *name,
                                rcf_rpc_server **out);
te_errno pyte_rpc_server_destroy(rcf_rpc_server *rpcs);
int pyte_rpc_errno(rcf_rpc_server *rpcs);
const char *pyte_rpc_err_msg(rcf_rpc_server *rpcs);
void pyte_rpc_set_timeout(rcf_rpc_server *rpcs, uint32_t ms);

te_errno pyte_rpc_socket(rcf_rpc_server *rpcs, int domain, int type,
                         int proto, int *out_fd);
te_errno pyte_rpc_bind(rcf_rpc_server *rpcs, int s,
                       const struct sockaddr *addr, int *out);
te_errno pyte_rpc_connect(rcf_rpc_server *rpcs, int s,
                          const struct sockaddr *addr, int *out);
te_errno pyte_rpc_listen(rcf_rpc_server *rpcs, int s, int backlog,
                         int *out);
te_errno pyte_rpc_accept(rcf_rpc_server *rpcs, int s,
                         struct sockaddr *addr, socklen_t *addrlen,
                         int *out);
te_errno pyte_rpc_send(rcf_rpc_server *rpcs, int s, const uint8_t *buf,
                       size_t len, int flags, ssize_t *out);
te_errno pyte_rpc_recv(rcf_rpc_server *rpcs, int s, uint8_t *buf,
                       size_t len, int flags, ssize_t *out);
te_errno pyte_rpc_sendto(rcf_rpc_server *rpcs, int s, const uint8_t *buf,
                         size_t len, int flags, const struct sockaddr *to,
                         ssize_t *out);
te_errno pyte_rpc_recvfrom(rcf_rpc_server *rpcs, int s, uint8_t *buf,
                           size_t len, int flags, struct sockaddr *from,
                           socklen_t *fromlen, ssize_t *out);
te_errno pyte_rpc_getsockname(rcf_rpc_server *rpcs, int s,
                              struct sockaddr *name, socklen_t *namelen,
                              int *out);
te_errno pyte_rpc_close(rcf_rpc_server *rpcs, int fd, int *out);
te_errno pyte_rpc_open(rcf_rpc_server *rpcs, const char *path, int flags,
                       int mode, int *out);
te_errno pyte_rpc_read(rcf_rpc_server *rpcs, int fd, uint8_t *buf,
                       size_t count, int *out);
te_errno pyte_rpc_write(rcf_rpc_server *rpcs, int fd, const uint8_t *buf,
                        size_t count, int *out);
te_errno pyte_rpc_unlink(rcf_rpc_server *rpcs, const char *path, int *out);
te_errno pyte_rpc_getpid(rcf_rpc_server *rpcs, int *out);
te_errno pyte_rpc_gethostname(rcf_rpc_server *rpcs, char *buf, size_t len,
                              int *out);
te_errno pyte_rpc_system(rcf_rpc_server *rpcs, const char *cmd,
                         int *out_flag, int *out_value);
te_errno pyte_rpc_shell_get_all(rcf_rpc_server *rpcs, char **out_buf,
                                const char *cmd, int *out_flag,
                                int *out_value);

te_errno pyte_sockaddr_in4(const char *ip, uint16_t port,
                           struct sockaddr_storage *ss, socklen_t *len);
te_errno pyte_sockaddr_parse(const struct sockaddr *sa, char *ipbuf,
                             size_t ipbuflen, uint16_t *port);

#define PYTE_PF_INET ...
#define PYTE_PF_INET6 ...
#define PYTE_PF_LOCAL ...
#define PYTE_SOCK_STREAM ...
#define PYTE_SOCK_DGRAM ...
#define PYTE_PROTO_DEF ...
#define PYTE_O_RDONLY ...
#define PYTE_O_WRONLY ...
#define PYTE_O_RDWR ...
#define PYTE_O_CREAT ...
#define PYTE_O_TRUNC ...
#define PYTE_O_APPEND ...
#define PYTE_MODE_0644 ...
#define PYTE_ECONNREFUSED ...
#define PYTE_ENOENT ...
#define TE_LL_ERROR ...
#define TE_LL_WARN ...
#define TE_LL_RING ...
#define TE_LL_INFO ...
#define TE_LL_VERB ...
#define PYTE_ETIMEDOUT ...
