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
te_errno pyte_rpc_shell_get_all(rcf_rpc_server *rpcs, char **out_buf,
                                const char *cmd, int *out_flag,
                                int *out_value);

typedef uint64_t cfg_handle;

te_errno pyte_cfg_get_type(const char *oid, int *out_type);
te_errno pyte_cfg_get_str(const char *oid, char **out, int *out_type);
te_errno pyte_cfg_set_str(const char *oid, int type, const char *value);
te_errno pyte_cfg_add_str(const char *oid, int type, const char *value,
                          cfg_handle *out);
te_errno pyte_cfg_del(const char *oid, int with_children);
te_errno pyte_cfg_find_pattern(const char *pattern, unsigned int *n,
                               cfg_handle **set);
te_errno pyte_cfg_oid_str(cfg_handle h, char **out);
te_errno pyte_cfg_inst_name(cfg_handle h, char **out);
te_errno pyte_cfg_synchronize(const char *oid, int with_subtree);
void pyte_free_handles(cfg_handle *set);

typedef struct tapi_job_factory_t tapi_job_factory_t;
typedef struct tapi_job_t tapi_job_t;
typedef struct tapi_job_channel_t tapi_job_channel_t;

te_errno pyte_job_factory_rpc(rcf_rpc_server *rpcs,
                              tapi_job_factory_t **out);
te_errno pyte_job_factory_destroy(tapi_job_factory_t *f);
te_errno pyte_job_create(tapi_job_factory_t *f, const char *program,
                         const char **argv, const char **env,
                         tapi_job_t **out);
te_errno pyte_job_start(tapi_job_t *job);
te_errno pyte_job_wait(tapi_job_t *job, int timeout_ms, int *out_type,
                       int *out_value);
te_errno pyte_job_stop(tapi_job_t *job, int signo, int term_timeout_ms);
te_errno pyte_job_kill(tapi_job_t *job, int signo);
te_errno pyte_job_destroy(tapi_job_t *job, int term_timeout_ms);
te_errno pyte_job_out_channels(tapi_job_t *job,
                               tapi_job_channel_t **out_stdout,
                               tapi_job_channel_t **out_stderr);
te_errno pyte_job_in_channel(tapi_job_t *job, tapi_job_channel_t **out);
te_errno pyte_job_attach_filter(tapi_job_channel_t **channels,
                                unsigned int n, const char *name,
                                int readable, unsigned int log_level,
                                tapi_job_channel_t **out);
te_errno pyte_job_filter_regexp(tapi_job_channel_t *filter, const char *re,
                                unsigned int extract);
te_errno pyte_job_filter_add(tapi_job_channel_t *filter,
                             tapi_job_channel_t **channels, unsigned int n);
te_errno pyte_job_filter_remove(tapi_job_channel_t *filter,
                                tapi_job_channel_t **channels,
                                unsigned int n);
te_errno pyte_job_receive(tapi_job_channel_t **filters, unsigned int n,
                          int timeout_ms, int last, char **out_data,
                          size_t *out_len, int *out_eos,
                          unsigned int *out_dropped,
                          tapi_job_channel_t **out_filter);
te_errno pyte_job_send(tapi_job_channel_t *channel, const char *data,
                       size_t len);
te_errno pyte_job_poll(tapi_job_channel_t **channels, unsigned int n,
                       int timeout_ms);

typedef struct pyte_pkts {
    void        **pkts;
    unsigned int  n;
} pyte_pkts;

te_errno pyte_asn_check(const char *text, int kind, char **err);
te_errno pyte_ta_session(const char *ta, int *out);
te_errno pyte_csap_create(const char *ta, int session,
                          const char *stack_id, const char *spec_text,
                          unsigned int *out_csap);
te_errno pyte_csap_destroy(const char *ta, int session, unsigned int csap);
te_errno pyte_csap_send(const char *ta, int session, unsigned int csap,
                        const char *templ_text, int blocking);
te_errno pyte_csap_recv_start(const char *ta, int session,
                              unsigned int csap, const char *pattern_text,
                              unsigned int timeout_ms, unsigned int num);
te_errno pyte_csap_recv_stop(const char *ta, int session,
                             unsigned int csap, pyte_pkts *out);
te_errno pyte_csap_recv_wait(const char *ta, int session,
                             unsigned int csap, pyte_pkts *out);
te_errno pyte_pkt_read_int(void *pkt, const char *labels, int64_t *out);
te_errno pyte_pkt_payload(void *pkt, uint8_t *buf, size_t *len);
void pyte_pkt_free(void *pkt);
void pyte_pkts_free(pyte_pkts *p);

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
#define PYTE_CVT_NONE ...
#define PYTE_CVT_BOOL ...
#define PYTE_CVT_INT8 ...
#define PYTE_CVT_UINT8 ...
#define PYTE_CVT_INT16 ...
#define PYTE_CVT_UINT16 ...
#define PYTE_CVT_INT32 ...
#define PYTE_CVT_UINT32 ...
#define PYTE_CVT_INT64 ...
#define PYTE_CVT_UINT64 ...
#define PYTE_CVT_STRING ...
#define PYTE_CVT_ADDRESS ...
#define PYTE_CVT_DOUBLE ...
#define PYTE_CVT_UNSPECIFIED ...
#define TE_LL_ERROR ...
#define TE_LL_WARN ...
#define TE_LL_RING ...
#define TE_LL_INFO ...
#define TE_LL_VERB ...
#define PYTE_ETIMEDOUT ...
#define PYTE_ESMALLBUF ...
#define PYTE_EINPROGRESS ...
#define PYTE_JOB_EXITED ...
#define PYTE_JOB_SIGNALED ...
#define PYTE_JOB_UNKNOWN ...
#define PYTE_SIGHUP ...
#define PYTE_SIGINT ...
#define PYTE_SIGKILL ...
#define PYTE_SIGTERM ...
#define PYTE_SIGUSR1 ...
#define PYTE_SIGUSR2 ...
