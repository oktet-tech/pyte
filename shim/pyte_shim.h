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

#include <signal.h>

#include "asn_usr.h"
#include "ndn.h"
#include "tad_common.h"
#include "rcf_api.h"
#include "tapi_tad.h"

#include "conf_api.h"
#include "tapi_cfg.h"
#include "tapi_cfg_rcf.h"
#include "te_kvpair.h"
#include "tapi_cfg_base.h"
#include "tapi_cfg_sys.h"
#include "rcf_rpc.h"
#include "tapi_job.h"
#include "tapi_job_factory_rpc.h"
#include "te_string.h"
#include "te_rpc_sys_socket.h"
#include "te_rpc_sys_stat.h"
#include "te_rpc_fcntl.h"
#include "tapi_rpc_socket.h"
#include "tapi_rpc_unistd.h"
#include "tapi_rpc_stdio.h"
#include "tapi_env.h"
#include "tapi_cfg_net.h"
#include "tapi_sockaddr.h"

#define PYTE_ETIMEDOUT TE_ETIMEDOUT
#define PYTE_ECONNREFUSED TE_ECONNREFUSED
#define PYTE_ENOENT TE_ENOENT
#define PYTE_EINPROGRESS TE_EINPROGRESS
#define PYTE_ESMALLBUF TE_ESMALLBUF

/* RCF constant passthrough */
#define PYTE_RCF_TA_REBOOTABLE RCF_TA_REBOOTABLE
#define PYTE_RCF_MAX_NAME RCF_MAX_NAME

/* Job completion cause passthrough */
#define PYTE_JOB_EXITED TAPI_JOB_STATUS_EXITED
#define PYTE_JOB_SIGNALED TAPI_JOB_STATUS_SIGNALED
#define PYTE_JOB_UNKNOWN TAPI_JOB_STATUS_UNKNOWN

/*
 * Signal numbers for tapi_job_kill()/tapi_job_stop().  The job TAPI
 * takes HOST signal numbers and converts them itself (rpc_job.c uses
 * signum_h2rpc()), so plain <signal.h> values are correct here.
 */
#define PYTE_SIGHUP SIGHUP
#define PYTE_SIGINT SIGINT
#define PYTE_SIGKILL SIGKILL
#define PYTE_SIGTERM SIGTERM
#define PYTE_SIGUSR1 SIGUSR1
#define PYTE_SIGUSR2 SIGUSR2

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
/* Socket options for pyte_rpc_setsockopt_int() (rpc_sockopt values) */
#define PYTE_SO_REUSEADDR RPC_SO_REUSEADDR

/* Configurator value-type passthrough */
#define PYTE_CVT_NONE CVT_NONE
#define PYTE_CVT_BOOL CVT_BOOL
#define PYTE_CVT_INT8 CVT_INT8
#define PYTE_CVT_UINT8 CVT_UINT8
#define PYTE_CVT_INT16 CVT_INT16
#define PYTE_CVT_UINT16 CVT_UINT16
#define PYTE_CVT_INT32 CVT_INT32
#define PYTE_CVT_UINT32 CVT_UINT32
#define PYTE_CVT_INT64 CVT_INT64
#define PYTE_CVT_UINT64 CVT_UINT64
#define PYTE_CVT_STRING CVT_STRING
#define PYTE_CVT_ADDRESS CVT_ADDRESS
#define PYTE_CVT_DOUBLE CVT_DOUBLE
#define PYTE_CVT_UNSPECIFIED CVT_UNSPECIFIED

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
extern te_errno pyte_rpc_setsockopt_int(rcf_rpc_server *rpcs, int s,
                                        int optname, int optval, int *out);
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
/* *out is malloc'ed (pyte_free_string) or NULL: unset OR call failed */
extern te_errno pyte_rpc_getenv(rcf_rpc_server *rpcs, const char *name,
                                char **out);
extern te_errno pyte_rpc_setenv(rcf_rpc_server *rpcs, const char *name,
                                const char *value, int overwrite, int *out);
extern te_errno pyte_rpc_shell_get_all(rcf_rpc_server *rpcs, char **out_buf,
                                       const char *cmd, int *out_flag,
                                       int *out_value);

/*
 * Configurator wrappers: everything crosses the boundary as text,
 * conversion to/from the real instance type happens here.
 * with_children/with_subtree are int (0/1) for cffi friendliness.
 */
extern te_errno pyte_cfg_get_type(const char *oid, int *out_type);
extern te_errno pyte_cfg_get_str(const char *oid, char **out, int *out_type);
extern te_errno pyte_cfg_set_str(const char *oid, int type,
                                 const char *value);
extern te_errno pyte_cfg_add_str(const char *oid, int type,
                                 const char *value, cfg_handle *out);
extern te_errno pyte_cfg_del(const char *oid, int with_children);
extern te_errno pyte_cfg_find_pattern(const char *pattern, unsigned int *n,
                                      cfg_handle **set);
extern te_errno pyte_cfg_oid_str(cfg_handle h, char **out);
extern te_errno pyte_cfg_inst_name(cfg_handle h, char **out);
extern te_errno pyte_cfg_synchronize(const char *oid, int with_subtree);
extern void pyte_free_handles(cfg_handle *set);

/*
 * Network configuration wrappers (tapi_cfg / tapi_cfg_base /
 * tapi_cfg_sys).  IPv4 only; addresses cross the boundary as text.
 * gw/dev may be NULL or empty meaning "absent".  mac is the raw
 * 6-byte link-layer address.  sysctl paths are slash-separated
 * relative to /proc/sys (the shim feeds them to the printf-style
 * tapi_cfg_sys API via a literal "%s").
 */
extern te_errno pyte_cfg_route_add(const char *ta, const char *dst,
                                   int prefix, const char *gw,
                                   const char *dev, int metric);
extern te_errno pyte_cfg_route_del(const char *ta, const char *dst,
                                   int prefix, const char *gw,
                                   const char *dev, int metric);
extern te_errno pyte_cfg_neigh_add(const char *ta, const char *ifname,
                                   const char *ip, const uint8_t *mac,
                                   int is_static);
extern te_errno pyte_cfg_neigh_del(const char *ta, const char *ifname,
                                   const char *ip);
extern te_errno pyte_cfg_if_addr_add(const char *ta, const char *ifname,
                                     const char *ip, int prefix,
                                     int set_bcast);
extern te_errno pyte_cfg_sys_get_str(const char *ta, const char *path,
                                     char **out);
extern te_errno pyte_cfg_sys_set_str(const char *ta, const char *path,
                                     const char *val);
extern te_errno pyte_cfg_sys_get_int(const char *ta, const char *path,
                                     int *out);
extern te_errno pyte_cfg_sys_set_int(const char *ta, const char *path,
                                     int val, int *old_val);
extern te_errno pyte_cfg_sys_get_uint64(const char *ta, const char *path,
                                        uint64_t *out);

/*
 * Job wrappers (tapi_job over an RPC factory).  Channel sets cross the
 * boundary as (array, count) pairs and are repacked into the
 * NULL-terminated vectors tapi_job expects.  factory_destroy returns
 * te_errno (always 0) instead of void so it can be guarded.
 */
extern te_errno pyte_job_factory_rpc(rcf_rpc_server *rpcs,
                                     tapi_job_factory_t **out);
extern te_errno pyte_job_factory_destroy(tapi_job_factory_t *f);
extern te_errno pyte_job_create(tapi_job_factory_t *f, const char *program,
                                const char **argv, const char **env,
                                tapi_job_t **out);
extern te_errno pyte_job_start(tapi_job_t *job);
extern te_errno pyte_job_wait(tapi_job_t *job, int timeout_ms,
                              int *out_type, int *out_value);
extern te_errno pyte_job_stop(tapi_job_t *job, int signo,
                              int term_timeout_ms);
extern te_errno pyte_job_kill(tapi_job_t *job, int signo);
extern te_errno pyte_job_destroy(tapi_job_t *job, int term_timeout_ms);
extern te_errno pyte_job_out_channels(tapi_job_t *job,
                                      tapi_job_channel_t **out_stdout,
                                      tapi_job_channel_t **out_stderr);
extern te_errno pyte_job_in_channel(tapi_job_t *job,
                                    tapi_job_channel_t **out);
extern te_errno pyte_job_attach_filter(tapi_job_channel_t **channels,
                                       unsigned int n, const char *name,
                                       int readable, unsigned int log_level,
                                       tapi_job_channel_t **out);
extern te_errno pyte_job_filter_regexp(tapi_job_channel_t *filter,
                                       const char *re, unsigned int extract);
extern te_errno pyte_job_filter_add(tapi_job_channel_t *filter,
                                    tapi_job_channel_t **channels,
                                    unsigned int n);
extern te_errno pyte_job_filter_remove(tapi_job_channel_t *filter,
                                       tapi_job_channel_t **channels,
                                       unsigned int n);
extern te_errno pyte_job_receive(tapi_job_channel_t **filters,
                                 unsigned int n, int timeout_ms, int last,
                                 char **out_data, size_t *out_len,
                                 int *out_eos, unsigned int *out_dropped,
                                 tapi_job_channel_t **out_filter);
extern te_errno pyte_job_send(tapi_job_channel_t *channel, const char *data,
                              size_t len);
extern te_errno pyte_job_poll(tapi_job_channel_t **channels, unsigned int n,
                              int timeout_ms);

/*
 * TAD/CSAP wrappers.  All NDN values cross the boundary as ASN.1 text
 * and are parsed here against the proper ndn_* type.
 *
 * Packet ownership: tapi_tad_trrecv_pkt_handler() hands each parsed
 * packet to the user callback and does NOT free it afterwards
 * ("Packet is owned by callback", lib/tapi_tad/tapi_tad.c), so the
 * collector stores the pointer directly — no copy.  Python wraps each
 * pointer in a Packet object and frees it via pyte_pkt_free().
 */

/** Received-packets collector filled by recv_stop/recv_wait */
typedef struct pyte_pkts {
    void        **pkts; /**< malloc'ed array of asn_value pointers */
    unsigned int  n;    /**< number of packets in the array */
} pyte_pkts;

/*
 * Parse NDN ASN.1 text without doing anything else (DSL calibration).
 * kind: 0 = CSAP spec, 1 = traffic template, 2 = traffic pattern.
 * On parse failure *err (if not NULL) gets a malloc'ed message with
 * the failing symbol position; free it with pyte_free_string().
 */
extern te_errno pyte_asn_check(const char *text, int kind, char **err);

extern te_errno pyte_ta_session(const char *ta, int *out);
extern te_errno pyte_csap_create(const char *ta, int session,
                                 const char *stack_id,
                                 const char *spec_text,
                                 unsigned int *out_csap);
extern te_errno pyte_csap_destroy(const char *ta, int session,
                                  unsigned int csap);
extern te_errno pyte_csap_send(const char *ta, int session,
                               unsigned int csap, const char *templ_text,
                               int blocking);
extern te_errno pyte_csap_recv_start(const char *ta, int session,
                                     unsigned int csap,
                                     const char *pattern_text,
                                     unsigned int timeout_ms,
                                     unsigned int num);
extern te_errno pyte_csap_recv_stop(const char *ta, int session,
                                    unsigned int csap, pyte_pkts *out);
extern te_errno pyte_csap_recv_wait(const char *ta, int session,
                                    unsigned int csap, pyte_pkts *out);
extern te_errno pyte_pkt_read_int(void *pkt, const char *labels,
                                  int64_t *out);
/*
 * Read packet payload.  In: *len = capacity of buf.  Out: *len =
 * actual payload length.  Returns TE_ESMALLBUF (with *len = needed)
 * if buf is NULL or too small; absent payload reads as length 0.
 */
extern te_errno pyte_pkt_payload(void *pkt, uint8_t *buf, size_t *len);
extern void pyte_pkt_free(void *pkt);
/* Frees the pkts array only, NOT the packets (Python wraps each) */
extern void pyte_pkts_free(pyte_pkts *p);

/*
 * RCF direct API wrappers (rcf_api.h).  File operations use session 0
 * ("TA session or 0" per the header).  restart() maps to
 * rcf_ta_reboot(..., RCF_REBOOT_TYPE_AGENT): RCF refuses it for
 * engine-host TAs (TE_EINVAL) and non-rebootable TAs (TE_EPERM).
 * flush_logs asks the Logger to pump out the TA log via
 * log_flush_ten() — rcf_ta_get_log() is Logger-only and would divert
 * the log bulk away from the run log.
 */
extern te_errno pyte_rcf_ta_list(char *buf, size_t *len);
extern te_errno pyte_rcf_ta_type(const char *ta, char *buf);
extern te_errno pyte_rcf_ta_info(const char *ta, char **type,
                                 char **rcflib, char **confstr,
                                 unsigned int *flags);
extern te_errno pyte_rcf_put_file(const char *ta, const char *lfile,
                                  const char *rfile);
extern te_errno pyte_rcf_get_file(const char *ta, const char *rfile,
                                  const char *lfile);
extern te_errno pyte_rcf_del_file(const char *ta, const char *rfile);
extern te_errno pyte_rcf_ta_restart(const char *ta,
                                    const char *boot_params);
extern te_errno pyte_rcf_ta_flush_logs(const char *ta);
extern te_errno pyte_rcf_add_ta_unix(const char *name, const char *type,
                                     const char *host, uint16_t port,
                                     unsigned int flags);
extern te_errno pyte_rcf_del_ta(const char *name);

/*
 * Configurator-managed dynamic agents (tapi_cfg_rcf.h, /rcf subtree).
 * kv is a flat array [key0, val0, key1, val1, ...] of n_kv PAIRS
 * (2 * n_kv strings) repacked into the te_kvpair_h conf list.  The
 * keys/values become /rcf:/agent:<ta>/conf:<key> instances; the
 * Configurator turns them into the rcfunix confstr (see
 * engine/configurator/conf_rcf.c): "port" is mandatory, an empty
 * "host" value means the engine host, presence-only keys such as
 * "sudo" must have an empty value.  flags are the same RCF_TA_*
 * bits as the raw path (REBOOTABLE, NO_SYNC_TIME).
 */
extern te_errno pyte_cfg_rcf_add_ta(const char *ta, const char *type,
                                    const char *rcflib, const char **kv,
                                    unsigned int n_kv, unsigned int flags);
extern te_errno pyte_cfg_rcf_del_ta(const char *ta);

/* Local sockaddr helpers (no RPC involved) */
extern te_errno pyte_sockaddr_in4(const char *ip, uint16_t port,
                                  struct sockaddr_storage *ss,
                                  socklen_t *len);
extern te_errno pyte_sockaddr_parse(const struct sockaddr *sa, char *ipbuf,
                                    size_t ipbuflen, uint16_t *port);

/*
 * ---- TRC: read access to lib/trc + lib/logic_expr ----
 *
 * TRC headers (te_trc.h → te_test_result.h) define a typedef named
 * te_test_verdict for the verdict struct.  tapi_test_log.h (pulled in
 * above via tapi_test.h) declares a function with the same name.
 * Including both in one translation unit causes a C name-space conflict.
 *
 * Solution: TRC accessors live in pyte_trc.c which does NOT include
 * tapi_test.h.  Here we forward-declare the opaque TRC types and the
 * accessor functions so the cffi-generated file and pyte_shim.c can
 * reference them without pulling in the conflicting headers.
 *
 * te_test_status values are copied from te_test_result.h as PYTE_TE_TEST_*
 * macros so the cffi cdef can resolve them without including the header
 * (which would cause the te_test_verdict name conflict again).
 */

/* te_test_status passthrough — values copied from te_test_result.h enum */
#define PYTE_TE_TEST_INCOMPLETE 0
#define PYTE_TE_TEST_UNSPEC     1
#define PYTE_TE_TEST_EMPTY      2
#define PYTE_TE_TEST_SKIPPED    3
#define PYTE_TE_TEST_FAKED      4
#define PYTE_TE_TEST_PASSED     5
#define PYTE_TE_TEST_FAILED     6

/*
 * Opaque TRC types (defined in te_trc.h / trc_db.h).
 *
 * NOTE: te_test_verdict is NOT typedef'd here.  tapi_test_log.h (included
 * above via tapi_test.h) declares a function named te_test_verdict(); a
 * typedef for the struct with the same name would be a C name-space conflict.
 * The struct tag te_test_verdict does NOT conflict with the function name
 * (struct tags are in a separate tag namespace in C), so we use
 * "struct te_test_verdict *" for verdict-related function declarations.
 * cffi sees "typedef ... te_test_verdict;" in the cdef and maps these
 * through void * at the ABI boundary.
 */
struct te_trc_db;
typedef struct te_trc_db te_trc_db;
extern void trc_db_close(te_trc_db *trc_db);

struct trc_test;
typedef struct trc_test trc_test;
struct trc_test_iter;
typedef struct trc_test_iter trc_test_iter;
struct trc_test_iter_arg;
typedef struct trc_test_iter_arg trc_test_iter_arg;
struct trc_exp_result;
typedef struct trc_exp_result trc_exp_result;
struct trc_exp_result_entry;
typedef struct trc_exp_result_entry trc_exp_result_entry;

/*
 * te_test_verdict struct tag exists (defined in te_test_result.h / pyte_trc.c)
 * but cannot be typedef'd here under the name te_test_verdict: tapi_test_log.h
 * already declared a function with that same name (ordinary identifier space).
 * Alias it as pyte_trc_verdict using the struct tag, which lives in the tag
 * namespace and does not collide.
 */
struct te_test_verdict;
typedef struct te_test_verdict pyte_trc_verdict;

/*
 * tq_string.h and logic_expr.h do not pull in te_test_result.h, so they
 * can be included here without triggering the te_test_verdict name conflict.
 * They provide tqh_strings and logic_expr used in the SYNC block below.
 */
#include "tq_string.h"
#include "logic_expr.h"

/*
 * trc_report_argument is defined in te_trc.h (which conflicts via
 * te_test_result.h).  Replicate the struct here with the same layout so
 * cffi API mode can verify field offsets when it compiles pyte._shim.c
 * with pyte_shim.h as the real header.  Must stay in sync with te_trc.h.
 */
struct trc_report_argument {
    char *name;
    char *value;
    bool variable;
};
typedef struct trc_report_argument trc_report_argument;

/*
 * step_iter_flags enum values are in te_trc.h which cannot be included
 * here.  Expose them as PYTE_STEP_ITER_* macros mirroring the PYTE_TE_TEST_*
 * pattern.
 *
 * NOTE: these numeric values are NOT verified against te_trc.h by cffi
 * (that header is excluded from this compilation unit), so they must be
 * kept in sync with enum step_iter_flags in te_trc.h by hand.
 */
#define PYTE_STEP_ITER_NO_MATCH_OLD  0x1
#define PYTE_STEP_ITER_NO_MATCH_WILD 0x2
#define PYTE_STEP_ITER_NO_MATCH_NEW  0x4

/*
 * Forward-declared opaque types for the TRC walker and te_test_result.
 * Passed through as pointers only; full definitions live in te_trc.h /
 * te_test_result.h which cannot be included here (see the te_test_verdict
 * name-conflict note above).
 */
struct te_trc_db_walker;
typedef struct te_trc_db_walker te_trc_db_walker;

struct te_test_result;
typedef struct te_test_result te_test_result;

/*
 * Direct TE TRC library calls exposed to cffi.  These functions are defined
 * in libtrc/liblogic_expr.  Their signatures only reference types already
 * forward-declared or included above, so they can be declared here without
 * pulling in te_trc.h (which would trigger the te_test_verdict conflict).
 */
extern te_trc_db_walker *trc_db_new_walker(te_trc_db *trc_db);
extern void trc_db_free_walker(te_trc_db_walker *walker);
extern void trc_db_walker_go_to_test(te_trc_db_walker *walker,
                                     trc_test *test);
extern const trc_exp_result *trc_db_iter_get_exp_result(
                                 const trc_test_iter *iter,
                                 const tqh_strings *tags,
                                 bool last_match);
extern const trc_exp_result_entry *trc_is_result_expected(
                                 const trc_exp_result *expected,
                                 const te_test_result *obtained);

/* SYNC: declarations below MUST stay in sync with pyte_trc.h, which cannot
 * be included here due to the te_test_verdict name collision with tapi_test_log.h. */
extern te_errno pyte_trc_db_open(const char *path, te_trc_db **db);
extern bool pyte_trc_db_last_match(const te_trc_db *db);

extern trc_test *pyte_trc_db_first_test(te_trc_db *db);
extern trc_test *pyte_trc_test_next(trc_test *test);
extern trc_test_iter *pyte_trc_test_first_iter(trc_test *test);
extern trc_test_iter *pyte_trc_iter_next(trc_test_iter *iter);
extern trc_test *pyte_trc_iter_first_test(trc_test_iter *iter);

extern const char *pyte_trc_test_name(const trc_test *test);
extern const char *pyte_trc_test_path(const trc_test *test);
extern int pyte_trc_test_type(const trc_test *test);
extern bool pyte_trc_test_aux(const trc_test *test);
extern const char *pyte_trc_test_objective(const trc_test *test);
extern const char *pyte_trc_test_notes(const trc_test *test);
extern const char *pyte_trc_test_filename(const trc_test *test);
extern int pyte_trc_test_file_pos(const trc_test *test);

extern const char *pyte_trc_iter_notes(const trc_test_iter *iter);
extern const char *pyte_trc_iter_filename(const trc_test_iter *iter);
extern int pyte_trc_iter_file_pos(const trc_test_iter *iter);

extern trc_test_iter_arg *pyte_trc_iter_first_arg(trc_test_iter *iter);
extern trc_test_iter_arg *pyte_trc_arg_next(trc_test_iter_arg *arg);
extern const char *pyte_trc_arg_name(const trc_test_iter_arg *arg);
extern const char *pyte_trc_arg_value(const trc_test_iter_arg *arg);

extern const trc_exp_result *pyte_trc_iter_default_result(
                                        const trc_test_iter *iter);
extern trc_exp_result *pyte_trc_iter_first_result(trc_test_iter *iter);
extern trc_exp_result *pyte_trc_result_next(trc_exp_result *result);
extern const char *pyte_trc_result_tags(const trc_exp_result *result);
extern const char *pyte_trc_result_key(const trc_exp_result *result);
extern const char *pyte_trc_result_notes(const trc_exp_result *result);

extern trc_exp_result_entry *pyte_trc_result_first_entry(
                                        trc_exp_result *result);
extern trc_exp_result_entry *pyte_trc_entry_next(
                                        trc_exp_result_entry *entry);
extern int pyte_trc_entry_status(const trc_exp_result_entry *entry);
extern const char *pyte_trc_entry_key(const trc_exp_result_entry *entry);
extern const char *pyte_trc_entry_notes(const trc_exp_result_entry *entry);
extern pyte_trc_verdict *pyte_trc_entry_first_verdict(
                                        trc_exp_result_entry *entry);
extern pyte_trc_verdict *pyte_trc_verdict_next(pyte_trc_verdict *verdict);
extern const char *pyte_trc_verdict_str(const pyte_trc_verdict *verdict);

extern bool pyte_trc_walker_step_iter(te_trc_db_walker *walker,
                                      unsigned int n_args,
                                      trc_report_argument *args,
                                      uint32_t flags);
extern trc_test_iter *pyte_trc_walker_iter(const te_trc_db_walker *walker);

extern tqh_strings *pyte_tq_strings_new(void);
extern te_errno pyte_tq_strings_add(tqh_strings *strs, const char *value);
extern void pyte_tq_strings_free(tqh_strings *strs);

extern te_test_result *pyte_test_result_new(int status);
extern te_errno pyte_test_result_add_verdict(te_test_result *result,
                                             const char *text);
extern void pyte_test_result_free(te_test_result *result);

/* -- tapi_env ---------------------------------------------------------- */

/** Allocate and initialize an empty tapi_env. */
extern te_errno pyte_env_new(tapi_env **out);

/** Parse an environment configuration string and bind it. */
extern te_errno pyte_env_get(const char *cfg, tapi_env *env);

/** Free a bound environment (closes its RPC servers) and the struct. */
extern te_errno pyte_env_free(tapi_env *env);

/** Lookup an RPC server by PCO name; TE_ENOENT if missing. */
extern te_errno pyte_env_get_pco(tapi_env *env, const char *name,
                                 rcf_rpc_server **out);

/** Name of the TA an RPC server runs on (malloc'ed). */
extern te_errno pyte_rpc_server_ta_name(rcf_rpc_server *rpcs, char **ta);

/**
 * Lookup an address by name.
 *
 * @param addr_str  IP text, or MAC text for ether addresses (malloc'ed)
 * @param family    "inet", "inet6" or "ether" (malloc'ed)
 * @param port      port embedded in the sockaddr (host order; 0 if none)
 */
extern te_errno pyte_env_get_addr(tapi_env *env, const char *name,
                                  char **addr_str, char **family,
                                  int *port);

/** Lookup an interface by name: OS name + ifindex. */
extern te_errno pyte_env_get_if(tapi_env *env, const char *name,
                                char **ifname, unsigned int *ifindex);

/** TA name of the host the named interface belongs to (malloc'ed). */
extern te_errno pyte_env_get_if_ta(tapi_env *env, const char *name,
                                   char **ta);

/** TA name for a host label ("" = first host); malloc'ed. */
extern te_errno pyte_env_get_host_ta(tapi_env *env, const char *name,
                                     char **ta);

/**
 * Bound subnet of a net ("" = first net), as "10.38.10.0" + prefix.
 * TE_ENOENT if the net has no subnet of that family.
 */
extern te_errno pyte_env_get_net_subnet(tapi_env *env, const char *name,
                                        int ipv6, char **subnet,
                                        unsigned int *prefix);

/** Allocate a unique port (host order) via the Configurator. */
extern te_errno pyte_allocate_port(rcf_rpc_server *rpcs,
                                   unsigned int *port);

/** tapi_cfg_net_all_assign_ip: subnets + node addresses (needs root). */
extern te_errno pyte_cfg_net_all_assign_ip(int ipv6);

/**
 * Attach a subnet from /net_pool to /net:<name> WITHOUT assigning node
 * addresses (works without root; enough for fake/alien env addresses).
 */
extern te_errno pyte_cfg_net_assign_subnet(const char *net_name, int ipv6);

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
