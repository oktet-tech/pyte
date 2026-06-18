/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright (C) 2026 Konstantin Ushakov */
/* cffi cdef — keep in sync with pyte_shim.h */
extern unsigned int te_test_id;
void pyte_log_init(const char *entity);
void pyte_log(unsigned int level, const char *user, const char *text);
void pyte_step(const char *text);
void pyte_substep(const char *text);
void pyte_step_push(const char *text);
void pyte_step_pop(const char *text);
void pyte_verdict(unsigned int level, const char *text);
void pyte_artifact(unsigned int level, const char *text);
unsigned int pyte_rc_module(unsigned int rc);
unsigned int pyte_rc_error(unsigned int rc);
const char *te_rc_mod2str(unsigned int rc);
const char *te_rc_err2str(unsigned int rc);
void pyte_free_string(char *p);
void pyte_trc_quiet_logging(void);

typedef int... te_errno;
typedef struct rcf_rpc_server rcf_rpc_server;
typedef int... socklen_t;
typedef long... ssize_t;
struct sockaddr { ...; };
struct sockaddr_storage { ...; };

te_errno pyte_rpc_server_create(const char *ta, const char *name,
                                rcf_rpc_server **out);
te_errno pyte_rpc_server_destroy(rcf_rpc_server *rpcs);
void pyte_rpc_set_silent(rcf_rpc_server *rpcs, int on);
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
te_errno pyte_rpc_setsockopt_int(rcf_rpc_server *rpcs, int s, int optname,
                                 int optval, int *out);
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
te_errno pyte_rpc_getenv(rcf_rpc_server *rpcs, const char *name,
                         char **out);
te_errno pyte_rpc_setenv(rcf_rpc_server *rpcs, const char *name,
                         const char *value, int overwrite, int *out);
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
te_errno pyte_cfg_wait_changes(void);
te_errno pyte_cfg_backup_create(char **out_name);
te_errno pyte_cfg_backup_restore(const char *name);
te_errno pyte_cfg_backup_release(const char *name);
void pyte_free_handles(cfg_handle *set);

te_errno pyte_cfg_route_add(const char *ta, const char *dst, int prefix,
                            const char *gw, const char *dev, int metric);
te_errno pyte_cfg_route_del(const char *ta, const char *dst, int prefix,
                            const char *gw, const char *dev, int metric);
te_errno pyte_cfg_neigh_add(const char *ta, const char *ifname,
                            const char *ip, const uint8_t *mac,
                            int is_static);
te_errno pyte_cfg_neigh_del(const char *ta, const char *ifname,
                            const char *ip);
te_errno pyte_cfg_if_addr_add(const char *ta, const char *ifname,
                              const char *ip, int prefix, int set_bcast);
te_errno pyte_cfg_sys_get_str(const char *ta, const char *path,
                              char **out);
te_errno pyte_cfg_sys_set_str(const char *ta, const char *path,
                              const char *val);
te_errno pyte_cfg_sys_get_int(const char *ta, const char *path, int *out);
te_errno pyte_cfg_sys_set_int(const char *ta, const char *path, int val,
                              int *old_val);
te_errno pyte_cfg_sys_get_uint64(const char *ta, const char *path,
                                 uint64_t *out);

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

te_errno pyte_rcf_ta_list(char *buf, size_t *len);
te_errno pyte_rcf_ta_type(const char *ta, char *buf);
te_errno pyte_rcf_ta_info(const char *ta, char **type, char **rcflib,
                          char **confstr, unsigned int *flags);
te_errno pyte_rcf_put_file(const char *ta, const char *lfile,
                           const char *rfile);
te_errno pyte_rcf_get_file(const char *ta, const char *rfile,
                           const char *lfile);
te_errno pyte_rcf_del_file(const char *ta, const char *rfile);
te_errno pyte_rcf_ta_restart(const char *ta, const char *boot_params);
te_errno pyte_rcf_ta_flush_logs(const char *ta);
te_errno pyte_rcf_add_ta_unix(const char *name, const char *type,
                              const char *host, uint16_t port,
                              unsigned int flags);
te_errno pyte_rcf_del_ta(const char *name);
te_errno pyte_cfg_rcf_add_ta(const char *ta, const char *type,
                             const char *rcflib, const char **kv,
                             unsigned int n_kv, unsigned int flags);
te_errno pyte_cfg_rcf_del_ta(const char *ta);

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
#define PYTE_SO_REUSEADDR ...
#define PYTE_IP_PKTINFO   ...
#define PYTE_ECONNREFUSED ...
#define PYTE_ENOENT ...
#define PYTE_ENODATA ...
#define PYTE_EPERM ...
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
#define PYTE_RCF_TA_REBOOTABLE ...
#define PYTE_RCF_MAX_NAME ...
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

/* ---- te_mi thin wrappers ---- */
typedef ... te_mi_logger;

te_errno pyte_mi_meas_create(const char *tool, te_mi_logger **out);
te_errno pyte_mi_add_meas(te_mi_logger *logger, int type, const char *name,
                          int aggr, double val, int multiplier);
te_errno pyte_mi_destroy(te_mi_logger *logger);

/* MI measurement type constants */
#define PYTE_MI_MEAS_LATENCY ...
#define PYTE_MI_MEAS_THROUGHPUT ...
#define PYTE_MI_MEAS_IOPS ...
#define PYTE_MI_MEAS_RTT ...
#define PYTE_MI_MEAS_RETRANS ...
#define PYTE_MI_MEAS_RPS ...
#define PYTE_MI_MEAS_PERCENTAGE ...

/* MI aggregation constants */
#define PYTE_MI_AGGR_SINGLE ...
#define PYTE_MI_AGGR_MIN ...
#define PYTE_MI_AGGR_MAX ...
#define PYTE_MI_AGGR_MEAN ...
#define PYTE_MI_AGGR_STDEV ...
#define PYTE_MI_AGGR_PERCENTILE ...
#define PYTE_MI_AGGR_MEDIAN ...

/* MI multiplier constants */
#define PYTE_MI_MULT_NANO ...
#define PYTE_MI_MULT_MICRO ...
#define PYTE_MI_MULT_MILLI ...
#define PYTE_MI_MULT_PLAIN ...
#define PYTE_MI_MULT_MEBI ...
#define PYTE_MI_MULT_MEGA ...

te_errno pyte_reqs_modify(const char *reqs);
te_errno pyte_tags_add_tag(const char *tag, const char *value);

/* ---- tapi_env ---- */
typedef ... tapi_env;

te_errno pyte_env_new(tapi_env **out);
te_errno pyte_env_get(const char *cfg, tapi_env *env);
te_errno pyte_env_free(tapi_env *env);
te_errno pyte_env_get_pco(tapi_env *env, const char *name,
                          rcf_rpc_server **out);
te_errno pyte_rpc_server_ta_name(rcf_rpc_server *rpcs, char **ta);
te_errno pyte_env_get_addr(tapi_env *env, const char *name,
                           char **addr_str, char **family, int *port);
te_errno pyte_env_get_if(tapi_env *env, const char *name, char **ifname,
                         unsigned int *ifindex);
te_errno pyte_env_get_if_ta(tapi_env *env, const char *name, char **ta);
te_errno pyte_env_get_host_ta(tapi_env *env, const char *name, char **ta);
te_errno pyte_env_get_net_subnet(tapi_env *env, const char *name,
                                 int ipv6, char **subnet,
                                 unsigned int *prefix);
te_errno pyte_allocate_port(rcf_rpc_server *rpcs, unsigned int *port);
te_errno pyte_cfg_net_all_assign_ip(int ipv6);
te_errno pyte_cfg_net_assign_subnet(const char *net_name, int ipv6);

/* ---- sendmsg / recvmsg ---- */
te_errno pyte_rpc_sendmsg(rcf_rpc_server *rpcs, int s,
                          const uint8_t **iov_bufs, const size_t *iov_lens,
                          unsigned int n_iov,
                          const char *addr, int port,
                          const int *cmsg_levels, const int *cmsg_types,
                          const uint8_t **cmsg_datas, const size_t *cmsg_lens,
                          unsigned int n_cmsg, int flags, ssize_t *sent);
te_errno pyte_rpc_recvmsg(rcf_rpc_server *rpcs, int s, size_t bufsize,
                          size_t ctrl_space, int flags,
                          uint8_t **data, size_t *data_len,
                          char **from_addr, int *from_port,
                          int **cmsg_levels, int **cmsg_types,
                          uint8_t ***cmsg_datas, size_t **cmsg_lens,
                          unsigned int *n_cmsg, int *msg_flags,
                          ssize_t *received);
void pyte_free_cmsgs(int *levels, int *types, uint8_t **datas,
                     size_t *lens, unsigned int n);

/* ---- iomux ---- */
typedef ... tapi_iomux_handle;

te_errno pyte_iomux_create(rcf_rpc_server *rpcs, int type,
                           tapi_iomux_handle **out);
te_errno pyte_iomux_add(tapi_iomux_handle *h, int fd, int evt);
te_errno pyte_iomux_mod(tapi_iomux_handle *h, int fd, int evt);
te_errno pyte_iomux_del(tapi_iomux_handle *h, int fd);
te_errno pyte_iomux_call(tapi_iomux_handle *h, int timeout_ms,
                         int *n_out, int **revts_out);
te_errno pyte_iomux_destroy(tapi_iomux_handle *h);
void pyte_free_ints(int *p);

#define PYTE_IOMUX_SELECT ...
#define PYTE_IOMUX_PSELECT ...
#define PYTE_IOMUX_POLL ...
#define PYTE_IOMUX_PPOLL ...
#define PYTE_IOMUX_EPOLL ...
#define PYTE_IOMUX_EPOLL_PWAIT ...
#define PYTE_IOMUX_EPOLL_PWAIT2 ...
#define PYTE_IOMUX_EVT_RD ...
#define PYTE_IOMUX_EVT_PRI ...
#define PYTE_IOMUX_EVT_WR ...
#define PYTE_IOMUX_EVT_EXC ...
#define PYTE_IOMUX_EVT_ERR ...
#define PYTE_IOMUX_EVT_HUP ...
#define PYTE_IOMUX_EVT_RDHUP ...
#define PYTE_IOMUX_EVT_ET ...
#define PYTE_IOMUX_EVT_ONESHOT ...
#define PYTE_IOMUX_EVT_NVAL ...

/* ---- TRC ---- */
typedef ... te_trc_db;
typedef ... te_trc_db_walker;
typedef ... trc_test;
typedef ... trc_test_iter;
typedef ... trc_test_iter_arg;
typedef ... trc_exp_result;
typedef ... trc_exp_result_entry;
typedef ... te_test_result;
typedef ... pyte_trc_verdict;
typedef ... logic_expr;
typedef ... tqh_strings;

/*
 * te_test_status enum values.  Exposed as PYTE_TE_TEST_* defines in
 * pyte_shim.h (numeric literals) to avoid including te_test_result.h in
 * the main shim — that header's te_test_verdict typedef conflicts with
 * the void te_test_verdict() function in tapi_test_log.h.
 * cffi resolves #define NAME ... at compile time from the included headers.
 */
#define PYTE_TE_TEST_INCOMPLETE ...
#define PYTE_TE_TEST_UNSPEC     ...
#define PYTE_TE_TEST_EMPTY      ...
#define PYTE_TE_TEST_SKIPPED    ...
#define PYTE_TE_TEST_FAKED      ...
#define PYTE_TE_TEST_PASSED     ...
#define PYTE_TE_TEST_FAILED     ...

void trc_db_close(te_trc_db *trc_db);

te_errno pyte_trc_db_open(const char *path, te_trc_db **db);
bool pyte_trc_db_last_match(const te_trc_db *db);
trc_test *pyte_trc_db_first_test(te_trc_db *db);
trc_test *pyte_trc_test_next(trc_test *test);
trc_test_iter *pyte_trc_test_first_iter(trc_test *test);
trc_test_iter *pyte_trc_iter_next(trc_test_iter *iter);
trc_test *pyte_trc_iter_first_test(trc_test_iter *iter);
const char *pyte_trc_test_name(const trc_test *test);
const char *pyte_trc_test_path(const trc_test *test);
int pyte_trc_test_type(const trc_test *test);
bool pyte_trc_test_aux(const trc_test *test);
const char *pyte_trc_test_objective(const trc_test *test);
const char *pyte_trc_test_notes(const trc_test *test);
const char *pyte_trc_test_filename(const trc_test *test);
int pyte_trc_test_file_pos(const trc_test *test);
const char *pyte_trc_iter_notes(const trc_test_iter *iter);
const char *pyte_trc_iter_filename(const trc_test_iter *iter);
int pyte_trc_iter_file_pos(const trc_test_iter *iter);
trc_test_iter_arg *pyte_trc_iter_first_arg(trc_test_iter *iter);
trc_test_iter_arg *pyte_trc_arg_next(trc_test_iter_arg *arg);
const char *pyte_trc_arg_name(const trc_test_iter_arg *arg);
const char *pyte_trc_arg_value(const trc_test_iter_arg *arg);
const trc_exp_result *pyte_trc_iter_default_result(const trc_test_iter *iter);
trc_exp_result *pyte_trc_iter_first_result(trc_test_iter *iter);
trc_exp_result *pyte_trc_result_next(trc_exp_result *result);
const char *pyte_trc_result_tags(const trc_exp_result *result);
const char *pyte_trc_result_key(const trc_exp_result *result);
const char *pyte_trc_result_notes(const trc_exp_result *result);
trc_exp_result_entry *pyte_trc_result_first_entry(trc_exp_result *result);
trc_exp_result_entry *pyte_trc_entry_next(trc_exp_result_entry *entry);
int pyte_trc_entry_status(const trc_exp_result_entry *entry);
const char *pyte_trc_entry_key(const trc_exp_result_entry *entry);
const char *pyte_trc_entry_notes(const trc_exp_result_entry *entry);
pyte_trc_verdict *pyte_trc_entry_first_verdict(trc_exp_result_entry *entry);
pyte_trc_verdict *pyte_trc_verdict_next(pyte_trc_verdict *verdict);
const char *pyte_trc_verdict_str(const pyte_trc_verdict *verdict);

typedef struct trc_report_argument {
    char *name;
    char *value;
    bool variable;
} trc_report_argument;

#define PYTE_STEP_ITER_NO_MATCH_OLD  ...
#define PYTE_STEP_ITER_NO_MATCH_WILD ...
#define PYTE_STEP_ITER_NO_MATCH_NEW  ...

te_trc_db_walker *trc_db_new_walker(te_trc_db *trc_db);
void trc_db_free_walker(te_trc_db_walker *walker);
void trc_db_walker_go_to_test(te_trc_db_walker *walker, trc_test *test);
const trc_exp_result *trc_db_iter_get_exp_result(const trc_test_iter *iter,
                                                 const tqh_strings *tags,
                                                 bool last_match);
const trc_exp_result_entry *trc_is_result_expected(
                                const trc_exp_result *expected,
                                const te_test_result *obtained);
te_errno logic_expr_parse(const char *str, logic_expr **expr);
int logic_expr_match(const logic_expr *re, const tqh_strings *set);
void logic_expr_free(logic_expr *expr);

bool pyte_trc_walker_step_iter(te_trc_db_walker *walker,
                               unsigned int n_args,
                               trc_report_argument *args,
                               uint32_t flags);
trc_test_iter *pyte_trc_walker_iter(const te_trc_db_walker *walker);
tqh_strings *pyte_tq_strings_new(void);
te_errno pyte_tq_strings_add(tqh_strings *strs, const char *value);
void pyte_tq_strings_free(tqh_strings *strs);
te_test_result *pyte_test_result_new(int status);
te_errno pyte_test_result_add_verdict(te_test_result *result,
                                      const char *text);
void pyte_test_result_free(te_test_result *result);
