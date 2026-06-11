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

#define PYTE_ETIMEDOUT TE_ETIMEDOUT
#define PYTE_ECONNREFUSED TE_ECONNREFUSED
#define PYTE_ENOENT TE_ENOENT
#define PYTE_EINPROGRESS TE_EINPROGRESS
#define PYTE_ESMALLBUF TE_ESMALLBUF

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
