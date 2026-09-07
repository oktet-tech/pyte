# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.batch - drive a batch (ASTF) TRex run.

Port of te/lib/tapi_tool/tapi_trex.{h,c}, pinned at ngfw-ts 41f9731 era
(tapi_trex identical to tsf/main). Covers the option model, platform
YAML rendering, the stdout filter tables
(:mod:`pyte.tools.trex._batch_filters`), the report/series math
(:mod:`pyte.tools.trex._batch_report`) and the job lifecycle below --
:meth:`Opts.to_argv` deliberately does NOT append ``--cfg`` (that
happens at launch, in :func:`build_argv`).

:func:`create` (see its docstring for a runnable example) builds the
run but does NOT start it (mirrors
``tapi_trex_create``/``tapi_trex_start`` being separate C calls):
ships the ASTF json and rendered platform yaml to the agent over RCF
(``rcf.agent(pco.ta).put_bytes``, the same transport as the C tapi's
``rcf_ta_put_file`` -- not an RPC open/write/close loop), binds
each :class:`PciBdf` endpoint when ``opts.driver`` is set, creates the
TRex job, and attaches every stdout filter table from
:mod:`pyte.tools.trex._batch_filters` before returning -- port/global
stat filters only when ``opts.iom is Iom.NORMAL``.
``opts.stdout_log_level``/``stderr_log_level`` of ``None`` or ``0``
skip that stream's log filter entirely (pythonic spelling of "silence
this stream").

:func:`create` mirrors nap-trex.c's ``proc->rpcs->silent_pass = true;
tapi_trex_create(...); proc->rpcs->silent_pass = false;`` idiom via
:meth:`pyte.rpc.server.RpcServer.silent_pass`: the job and its filters
are created under that toggle, so the ``job_create`` /
``job_attach_filter`` / ``job_filter_add_regexp`` RPC calls are not
logged (tapi_job bakes the RPC server's ambient silent_pass into each
job/channel/filter object at creation time). That baked-in silence is
NOT limited to creation: ``rpc_job_start``/``wait``/``stop``/``kill``/
``destroy`` (``te/lib/tapi_job/rpc_job.c:118,171,212``) each reassert
``rpcs->silent_pass = tapi_job_get_silent_pass(job)`` around their own
call, and every :meth:`Filter.drain` on a filter created under it
inherits the same field -- so a job born silent under this window
stays silent for EVERY later RPC made on it, lifecycle calls included,
not just the ones that created it, until something calls
``tapi_job_set_tracing(TRUE)`` on it again. :meth:`Trex.report` does
exactly that once its own drain (already silent from creation, so it
needs no bracket of its own) is done, mirroring
``trex_result_extract()``'s closing ``tapi_job_set_tracing(TRUE)``
(nap-trex-stats.c:694) -- see its docstring -- so ``stop``/``kill``/
``destroy`` afterwards stay logged, same as the C. This is deliberate,
stated intent in the port, not a side effect of
:meth:`~pyte.job.Job.quiet`, which restores whatever tracing state it
finds rather than forcing it back on.

Interface resolution: this port only understands :class:`LinuxIface`
(used verbatim, never bound) and :class:`PciBdf` (used verbatim, bound
to ``opts.driver`` when set). C's PCI-by-kernel-iface and vendor/
device/instance OID resolution forms are not ported -- a suite that
needs those resolves the BDF itself (e.g. nap-ts's ``dpdk.py``) before
building an :class:`Endpoint`.

Pinned mappings (from tapi_trex.c:337-360, tapi_trex.h:290-324)
================================================================

- ``Verbose`` mirrors ``tapi_trex_verbose_mapping``: only MIN ("1") and
  MAX ("3") are meaningful values (no "2").
- ``Iom`` mirrors ``tapi_trex_iom_mapping``: DEFAULT ("0", C's
  TAPI_TREX_IOM_SILENT), NORMAL ("1", TAPI_TREX_IOM_NORMAL), BATCH
  ("2", TAPI_TREX_IOM_SHORT).
- ``So`` mirrors ``tapi_trex_so_mapping``, one member per single
  ``--*-so`` flag. DIVERGENCE: the C enum also has a
  ``TAPI_TREX_SO_MLX4_MLX5`` value that emits the two flags joined as
  one broken argv element (``"--mlx4-so --mlx5-so"``); pyte instead
  takes a tuple of ``So`` and emits each flag as its own argv element
  (put both ``So.MLX4`` and ``So.MLX5`` in the tuple for that case).
- DIVERGENCE: C's ``tapi_trex_opt`` does not validate ``astf_template``
  at all; :class:`Opts` requires ``astf_json`` non-empty in
  ``__post_init__`` (see the check there for the same note).

argv (bind order, tapi_trex.c:362-390 ``trex_args_binds``)::

    trex_exec  -f default.py --astf
    [--astf-server-only]  [-c N]  [--tso-disable]  [--lro-disable]
    [-d %.6f]  [--flip]  [--hdrh]  [--ipv6]  [-m %.6f]  [--nc]
    [--no-flow-control-change]  [--no-watchdog]  [--rt]  [-pubd]
    [--queue-drop]  [--sleeps]  [-v <1|3>]  [--iom <0|1|2>]
    [<so flag> ...]  [-w N]  [--prefix <name>]

``--cfg <path>`` is appended by the caller at launch, not by
:meth:`Opts.to_argv`.

Field-name divergences from the C struct (tapi_trex.h:406-487),
kept explicit rather than silently renamed:

- ``force_close_at_end`` binds ``--nc`` (same as C).
- ``no_flow_control_change`` binds ``--no-flow-control-change``; the
  C field backing it is named ``enable_flow_control`` (its meaning:
  when the flag is passed, TRex's own flow-control auto-disable is
  skipped).
- ``rt_prio`` binds ``--rt`` (C field: ``use_realtime_prio``).
- ``no_monitors`` binds ``-pubd`` (C field: ``no_monitors``).
- ``queue_drop`` binds ``--queue-drop`` (C field: ``dont_resend_pkts``).
- ``sleeps`` binds ``--sleeps`` (C field: ``use_sleep``).
"""
from __future__ import annotations

import contextlib
import dataclasses
import enum
import os
import random
import shlex
import string
from typing import TYPE_CHECKING, Iterator

from pyte import log, rcf
from pyte._cleanup import cleanup_all
from pyte.errors import RpcError, TeError
from pyte.errors import TimeoutError as TeTimeoutError
from pyte.tools import _tool
from pyte.tools.trex import _batch_filters as _flt
from pyte.tools.trex import _batch_report as _rpt

if TYPE_CHECKING:
    from pyte.job import Filter, Job, JobStatus
    from pyte.rpc.server import RpcServer


class Iom(enum.Enum):
    """IO mode for server output (tapi_trex_iom_mapping)."""
    DEFAULT = "0"
    NORMAL = "1"
    BATCH = "2"


class Verbose(enum.Enum):
    """Debug verbosity level (tapi_trex_verbose_mapping)."""
    MIN = "1"
    MAX = "3"


class So(enum.Enum):
    """NIC-specific shared-object flags (tapi_trex_so_mapping).

    Each member's value is the literal argv flag; put more than one
    member in :attr:`Opts.so` to get more than one flag emitted.
    """
    MLX4 = "--mlx4-so"
    MLX5 = "--mlx5-so"
    NTACC = "--ntacc-so"
    BNXT = "--bnxt-so"


@dataclasses.dataclass(frozen=True)
class LinuxIface:
    """A kernel/af-packet interface, identified by its name."""
    name: str


@dataclasses.dataclass(frozen=True)
class PciBdf:
    """A DPDK-bound port, identified by its PCI BDF (e.g. "0000:01:00.0")."""
    bdf: str


@dataclasses.dataclass(frozen=True)
class Endpoint:
    """One client or server port description.

    Not consumed by :meth:`Opts.to_argv` (there is no per-endpoint
    CLI flag); it feeds :func:`render_cfg_yaml`. ``iface`` is None for
    TRex's "dummy" port.
    """
    iface: LinuxIface | PciBdf | None = None
    ip: str | None = None
    gw: str | None = None
    src_mac: str | None = None
    dst_mac: str | None = None

    def __post_init__(self) -> None:
        if self.ip is not None and self.src_mac is not None:
            raise ValueError("Endpoint.ip and .src_mac are exclusive")
        if self.gw is not None and self.dst_mac is not None:
            raise ValueError("Endpoint.gw and .dst_mac are exclusive")


@dataclasses.dataclass(frozen=True)
class Opts:
    """TRex batch (ASTF) command-line options (mirrors tapi_trex_opt)."""
    trex_exec: str
    astf_json: str
    clients: tuple[Endpoint, ...] = ()
    servers: tuple[Endpoint, ...] = ()
    astf_server_only: bool = False
    n_threads: int | None = None
    tso_disable: bool = False
    lro_disable: bool = False
    duration: float | None = None
    flip: bool = False
    hdrh: bool = False
    ipv6: bool = False
    rate_multiplier: float | None = None
    force_close_at_end: bool = False       # --nc
    no_flow_control_change: bool = False   # C field enable_flow_control
    no_watchdog: bool = False
    rt_prio: bool = False
    no_monitors: bool = False              # -pubd
    queue_drop: bool = False
    sleeps: bool = False
    verbose: Verbose | None = None
    iom: Iom | None = None                 # NORMAL gates stat filters
    so: tuple[So, ...] = ()
    init_wait_sec: int | None = None
    instance_prefix: str | None = None
    cfg_extra: str | None = None   # YAML appended after port_info
    driver: str | None = None      # PCI bind driver, None = no bind
    # A level of None (or 0) disables the corresponding log filter
    # entirely -- pythonic spelling of "the suite silences this
    # stream" (C would still attach a filter at te_log_level 0).
    stdout_log_level: str | int | None = "RING"
    stderr_log_level: str | int | None = "WARN"

    def __post_init__(self) -> None:
        # DIVERGENCE: C tapi_trex does not validate astf_template; we
        # require it non-empty.
        if not self.astf_json:
            raise ValueError("Opts.astf_json is required")
        if not self.clients and not self.servers:
            raise ValueError(
                "Opts requires at least one of clients/servers")

    def to_argv(self) -> list[str]:
        """Build the TRex argument list, including argv[0] (trex_exec).

        Mirrors trex_args_binds bind order (tapi_trex.c:362-390).
        ``--cfg <path>`` is NOT appended here; the caller adds it at
        launch time.
        """
        argv: list[str] = [self.trex_exec, "-f", "default.py", "--astf"]
        argv += _tool.switch("--astf-server-only", self.astf_server_only)
        argv += _tool.opt("-c", self.n_threads)
        argv += _tool.switch("--tso-disable", self.tso_disable)
        argv += _tool.switch("--lro-disable", self.lro_disable)
        if self.duration is not None:
            argv += ["-d", f"{self.duration:.6f}"]
        argv += _tool.switch("--flip", self.flip)
        argv += _tool.switch("--hdrh", self.hdrh)
        argv += _tool.switch("--ipv6", self.ipv6)
        if self.rate_multiplier is not None:
            argv += ["-m", f"{self.rate_multiplier:.6f}"]
        argv += _tool.switch("--nc", self.force_close_at_end)
        argv += _tool.switch("--no-flow-control-change",
                             self.no_flow_control_change)
        argv += _tool.switch("--no-watchdog", self.no_watchdog)
        argv += _tool.switch("--rt", self.rt_prio)
        argv += _tool.switch("-pubd", self.no_monitors)
        argv += _tool.switch("--queue-drop", self.queue_drop)
        argv += _tool.switch("--sleeps", self.sleeps)
        if self.verbose is not None:
            argv += ["-v", self.verbose.value]
        if self.iom is not None:
            argv += ["--iom", self.iom.value]
        argv += [so.value for so in self.so]
        argv += _tool.opt("-w", self.init_wait_sec)
        argv += _tool.opt("--prefix", self.instance_prefix)
        return argv


def _iface_literal(iface: LinuxIface | PciBdf | None) -> str:
    """Render one interface as it appears in the ``interfaces:`` list.

    Mirrors ``tapi_trex_setup_port``'s ``IFACES`` push (tapi_trex.c:1066):
    the name is always single-quoted (TRex/Cisco scripts misparse some
    PCI BDFs without quotes); a missing interface renders as ``'dummy'``
    (``TAPI_TREX_DUMMY``).
    """
    if iface is None:
        name = "dummy"
    elif isinstance(iface, LinuxIface):
        name = iface.name
    else:
        name = iface.bdf
    return f"'{name}'"


def render_cfg_yaml(opts: Opts) -> str:
    """Render the TRex platform YAML config (default_trex_cfg template).

    Mirrors ``tapi_trex_gen_yaml_config``/``tapi_trex_setup_port``
    (tapi_trex.c:989-1168) expanding the default template
    (tapi_trex.c:326-334): ports are paired ``client[0], server[0],
    client[1], server[1], ...`` (a missing entry at an index becomes a
    default :class:`Endpoint` -- iface ``None``, ip/gw ``"0.0.0.0"``),
    ``port_limit`` counts every port including dummies, and
    ``port_info:`` lists all IP-form ports before all MAC-form ports.

    DIVERGENCE: in C, a port whose ``ip``/``gw`` sockaddr pair mixes an
    IP address with a MAC (e.g. an IP source address with a MAC
    gateway) silently splits across ``PORTINFO_IP``/``PORTINFO_DST_MAC``,
    misaligning the two ``port_info:`` groups so a later ``ip:`` entry
    ends up paired with the wrong ``default_gw:``/``dest_mac:`` line.
    This function instead requires exactly one address form per port
    (both ``ip``-shaped or both ``mac``-shaped) and raises
    :class:`ValueError` otherwise.
    """
    n = max(len(opts.clients), len(opts.servers))
    ports: list[Endpoint] = []
    for i in range(n):
        client = opts.clients[i] if i < len(opts.clients) else Endpoint()
        server = opts.servers[i] if i < len(opts.servers) else Endpoint()
        ports.append(client)
        ports.append(server)

    ip_ports: list[tuple[str, str]] = []
    mac_ports: list[tuple[str, str]] = []
    for ep in ports:
        addr_is_mac = ep.src_mac is not None
        gw_is_mac = ep.dst_mac is not None
        if addr_is_mac != gw_is_mac:
            raise ValueError(
                "Endpoint must use exactly one address form: either "
                "ip/gw or src_mac/dst_mac, not a mix (DIVERGENCE: C "
                "would silently misalign the port_info YAML lists "
                f"here); got ip={ep.ip!r} gw={ep.gw!r} "
                f"src_mac={ep.src_mac!r} dst_mac={ep.dst_mac!r}")
        if addr_is_mac:
            mac_ports.append((ep.dst_mac, ep.src_mac))
        else:
            ip_ports.append((ep.ip if ep.ip is not None else "0.0.0.0",
                             ep.gw if ep.gw is not None else "0.0.0.0"))

    lines = [
        f"- port_limit      : {len(ports)}",
        "  version         : 2",
        "  interfaces: [" +
        ", ".join(_iface_literal(ep.iface) for ep in ports) + "]",
        "  port_info:",
    ]
    for ip, gw in ip_ports:
        lines.append(f"    - ip: {ip}")
        lines.append(f"      default_gw: {gw}")
    for dst_mac, src_mac in mac_ports:
        lines.append(f"    - dest_mac: {dst_mac}")
        lines.append(f"      src_mac: {src_mac}")

    yaml_text = "\n".join(lines) + "\n"
    if opts.cfg_extra:
        yaml_text += opts.cfg_extra
    return yaml_text


# ---------------------------------------------------------------------
# Lifecycle / session (tapi_trex_create/start/wait/stop/kill/destroy,
# tapi_trex.c:628-676, 1179-1224, 1455-1795)
# ---------------------------------------------------------------------

#: First/rest character sets of a C identifier (te_make_spec_buf's
#: TE_FILL_SPEC_C_ID, as used by tapi_trex_setup_yaml_config_path_setup
#: -- RCF_RPC_NAME_LEN / 2 == 32 characters, tapi_trex.c:1230-1232).
_C_IDENT_FIRST = string.ascii_letters + "_"
_C_IDENT_REST = string.ascii_letters + string.digits + "_"
_C_IDENT_LEN = 32


def _random_c_ident(n: int = _C_IDENT_LEN) -> str:
    """A random n-char string shaped like a C identifier."""
    return (random.choice(_C_IDENT_FIRST)
            + "".join(random.choices(_C_IDENT_REST, k=n - 1)))


def yaml_cfg_path() -> str:
    """A fresh random platform-YAML path (TAPI_TREX_CFG_YAML_FMT).

    Mirrors ``tapi_trex_setup_yaml_config_path_setup`` (tapi_trex.c:
    1230-1247): ``/tmp/<32-char C identifier>.yaml``, first character
    ``[A-Za-z_]``, the rest ``[A-Za-z0-9_]``.
    """
    return f"/tmp/{_random_c_ident()}.yaml"


def astf_json_path(instance_prefix: str | None) -> str:
    """The ASTF json path (TAPI_TREX_ASTF_CONF_FMT, tapi_trex.c:541-559).

    ``/tmp/astf.json`` when *instance_prefix* is None or empty (C's
    ``te_str_is_null_or_empty``), else ``/tmp/astf-<instance_prefix>.json``.
    """
    if not instance_prefix:
        return "/tmp/astf.json"
    return f"/tmp/astf-{instance_prefix}.json"


def n_ports(opts: Opts) -> int:
    """The number of non-dummy ports (tapi_trex_ports_count, tapi_trex.c:
    1251-1268): clients and servers whose ``iface`` is not None.
    """
    return sum(1 for ep in (*opts.clients, *opts.servers)
              if ep.iface is not None)


def build_argv(opts: Opts, cfg_path: str) -> list[str]:
    """The full launch argv: :meth:`Opts.to_argv` plus ``--cfg <path>``.

    Mirrors ``tapi_trex_setup_yaml_config_path_setup`` (tapi_trex.c:
    1238-1246), which appends ``--cfg <path>`` after every other bound
    option.
    """
    return [*opts.to_argv(), "--cfg", cfg_path]


def _shell_cmd(trex_exec: str, argv: list[str]) -> str:
    """``cd <workdir> && exec <argv...>``, every token shell-quoted.

    TRex must run from its install directory (tapi_job_set_workdir in
    C, tapi_trex.c:1670-1678); pyte has no workdir binding in the
    shim, so the working directory is set the same way
    :func:`pyte.tools.trex.stl.session` does it -- via a ``/bin/sh -c``
    wrapper (see ``ServerOpts.shell_command``).
    """
    workdir = os.path.dirname(trex_exec)
    return (f"cd {shlex.quote(workdir)} && exec "
            + " ".join(shlex.quote(a) for a in argv))


def _bind_pci(pco: "RpcServer", opts: Opts) -> None:
    """Bind every :class:`PciBdf` endpoint's device to ``opts.driver``.

    Mirrors ``tapi_trex_bind_pci_addr`` (tapi_trex.c:628-676): find
    ``/agent:<ta>/hardware:/pci:/device:<bdf>`` and set its driver.
    :class:`LinuxIface` endpoints are never bound.
    """
    from pyte.cfg.gen.pci import Pci
    pci = Pci(pco.ta)
    for ep in (*opts.clients, *opts.servers):
        if isinstance(ep.iface, PciBdf):
            pci.device[ep.iface.bdf].driver = opts.driver


def _remove_tmp_files(pco: "RpcServer", *paths: str) -> None:
    """Best-effort ``pco.unlink()`` of each path; ENOENT is not an error.

    Deliberately still the RPC ``unlink()`` here, not
    :meth:`pyte.rcf.RcfAgent.del_file`: the ENOENT tolerance below
    needs :class:`pyte.errors.RpcError`'s ``.code``, and switching the
    delete side to RCF would trade a one-line noise saving (rmdir/close
    of a job's own tmp files is not on the hot log path the way the
    ship-side open/write/close loop was) for an error-handling rewrite
    with no log-shape benefit.
    """
    from pyte import errors
    for path in paths:
        try:
            pco.unlink(path)
        except RpcError as e:
            if e.code != errors.ENOENT:
                raise


class Trex:
    """A created TRex batch (ASTF) run (tapi_trex_app).

    Returned by :func:`create`, which builds and attaches everything
    but does not start the process -- call :meth:`start` explicitly
    (mirrors ``tapi_trex_create``/``tapi_trex_start`` being separate
    C calls). Not meant to be constructed directly.

    :ivar job: the underlying :class:`pyte.job.Job`.
    :ivar cmd: the full TRex argv (including ``--cfg``), for the
        suite's own logging (e.g. ``ring_app_cmd``); the job itself
        actually runs under a ``/bin/sh -c`` wrapper (see
        :func:`_shell_cmd`), so ``job.program`` is ``"/bin/sh"``.
    """

    def __init__(self, pco: "RpcServer", job: "Job", cmd: list[str],
                 yaml_path: str, astf_path: str):
        self.job = job
        self.cmd = cmd
        self._pco = pco
        self._yaml_path = yaml_path
        self._astf_path = astf_path
        self._closed = False
        self._stopped = False
        self._job_destroyed = False
        self._files_removed = False
        self._summary: dict[str, "Filter"] = {}
        self._m_traff_dur: tuple["Filter", "Filter"] | None = None
        self._opt: dict[str, tuple["Filter", "Filter"]] = {}
        self._port_stat: dict[str, list["Filter"]] = {}
        self._port_time: dict[str, "Filter"] = {}
        self._global: dict[str, "Filter"] = {}

    def _attach_filters(self, opts: Opts) -> None:
        """Attach every stdout filter table BEFORE start() (tapi_trex.c:
        1515-1600 summary+log filters at job-create time, 1272-1339
        optional counters, 1341-1474 port/global stats gated on
        ``iom == NORMAL``).
        """
        job = self.job
        self._summary = {
            name: job.filter(stdout=True, regex=regex, group=group,
                             name=name)
            for name, (regex, group) in _flt.SUMMARY.items()}
        self._m_traff_dur = (
            job.filter(stdout=True, regex=_flt.M_TRAFF_DUR, group=1,
                      name="m_traff_dur_cl"),
            job.filter(stdout=True, regex=_flt.M_TRAFF_DUR, group=2,
                      name="m_traff_dur_srv"))
        for name in _flt.OPT_COUNTERS:
            regex = _flt.OPT_COUNTER_RE(name, name in _flt.OPT_COUNTERS_ERR)
            self._opt[name] = (
                job.filter(stdout=True, regex=regex, group=1,
                          name=f"{name}_cl_flt"),
                job.filter(stdout=True, regex=regex, group=2,
                          name=f"{name}_srv_flt"))

        if opts.iom is Iom.NORMAL:
            ports = n_ports(opts)
            for row in _flt.PORT_STAT_ROWS:
                regex = _flt.port_stat_re(row, ports)
                self._port_stat[row] = [
                    job.filter(stdout=True, regex=regex, group=j + 1,
                              name=f"port {j} {row}")
                    for j in range(ports)]
            for row in _flt.PORT_TIME_ROWS:
                self._port_time[row] = job.filter(
                    stdout=True, regex=_flt.port_time_re(row), group=1,
                    name=row)
            for name, regex in _flt.GLOBAL_STATS.items():
                self._global[name] = job.filter(
                    stdout=True, regex=name + regex, group=1, name=name)

        if opts.stdout_log_level:
            job.stdout.log(level=opts.stdout_log_level)
        if opts.stderr_log_level:
            job.stderr.log(level=opts.stderr_log_level)

    def start(self) -> None:
        """Start the TRex process (tapi_trex_start)."""
        self.job.start()

    def wait(self, timeout: float | None = None) -> "JobStatus":
        """Wait for completion; None (the default) blocks forever.

        Mirrors ``tapi_trex_wait`` (tapi_trex.c:1685-1699): a still-
        running job (TE_EINPROGRESS, surfaced by pyte as
        :class:`pyte.errors.TimeoutError`) is logged at RING before
        the exception is re-raised.
        """
        try:
            return self.job.wait(timeout=timeout)
        except TeTimeoutError:
            log.ring(f"TRex batch ({self.cmd[0]}): job was still in "
                     "process at the end of the wait")
            raise

    def stop(self) -> None:
        """Terminate gracefully: SIGTERM, 10 s (tapi_trex_stop)."""
        self.job.stop()

    def kill(self, signum) -> None:
        """Send a signal to the job (tapi_trex_kill)."""
        self.job.kill(signum)

    def report(self) -> _rpt.Report:
        """Drain every attached filter and build the :class:`Report`.

        Mirrors reading each ``tapi_job`` filter and feeding
        ``tapi_trex_get_report`` (tapi_trex.c:2250-2309); the parsing
        itself is :func:`pyte.tools.trex._batch_report.build_report`.

        Every filter drained here was attached under :func:`create`'s
        ``pco.silent_pass()`` window and is already silent by the time
        this runs (nothing between creation and here flips
        ``silent_pass`` back), so the drain itself needs no
        ``tapi_job_set_tracing(FALSE)`` half of the bracket
        ``trex_result_extract()`` uses (nap-trex-stats.c:614-694).

        It DOES need that bracket's closing half:
        ``rpc_job_start``/``wait``/``stop``/``kill``/``destroy``
        (``te/lib/tapi_job/rpc_job.c:118,171,212``) all reassert the
        job's own baked-in ``silent_pass``, so a job born silent under
        :func:`create` stays silent for its ENTIRE remaining lifetime
        -- including :meth:`Trex.stop`/:meth:`kill`/:meth:`close`'s
        ``destroy()`` -- unless something re-enables tracing.
        :meth:`~pyte.job.Job.quiet` won't do that any more (it now
        restores whatever it found, by design -- see the module
        docstring), so this calls :meth:`~pyte.job.Job.tracing` (True)
        explicitly at the end, mirroring
        ``trex_result_extract()``'s closing
        ``tapi_job_set_tracing(TRUE)`` so later lifecycle calls stay
        logged, same as the C. Runs in a ``finally`` so it still
        happens if a drain raises.
        """
        filters = _rpt.BatchFilters()
        try:
            for name, f in self._summary.items():
                filters.summary[name] = [m.data for m in f.drain()]
            if self._m_traff_dur is not None:
                cl_f, srv_f = self._m_traff_dur
                cl_vals = [m.data for m in cl_f.drain()]
                srv_vals = [m.data for m in srv_f.drain()]
                filters.m_traff_dur = list(zip(cl_vals, srv_vals))
            for name, (cl_f, srv_f) in self._opt.items():
                cl_vals = [m.data for m in cl_f.drain()]
                srv_vals = [m.data for m in srv_f.drain()]
                filters.opt_counters[name] = list(zip(cl_vals, srv_vals))
            for name, port_filters in self._port_stat.items():
                per_port = [[m.data for m in pf.drain()]
                           for pf in port_filters]
                filters.port_stat[name] = list(zip(*per_port))
            for name, f in self._port_time.items():
                filters.port_time[name] = [m.data for m in f.drain()]
            for name, f in self._global.items():
                filters.global_stats[name] = [m.data for m in f.drain()]
        finally:
            self.job.tracing(True)
        return _rpt.build_report(filters)

    def close(self) -> None:
        """Idempotent, retryable teardown: stop-tolerant destroy, then
        remove the ``/tmp`` yaml and astf json files from the agent.

        DIVERGENCE: C's ``tapi_trex_destroy`` never removes either
        file -- a deliberate leak this port does not reproduce.

        Each step is tracked separately, so a close() whose job
        destroy failed retries only the unfinished work rather than
        marking itself done and leaving the process alive.
        """
        if self._closed:
            return
        if not self._stopped:
            try:
                self.job.stop()
            except TeError:
                pass
            self._stopped = True
        cleanup_all(self._destroy_job_once, self._remove_files_once)
        self._closed = True

    def _destroy_job_once(self) -> None:
        if not self._job_destroyed:
            self.job.destroy()
            self._job_destroyed = True

    def _remove_files_once(self) -> None:
        if not self._files_removed:
            _remove_tmp_files(self._pco, self._yaml_path, self._astf_path)
            self._files_removed = True


@contextlib.contextmanager
def create(pco: "RpcServer", opts: Opts) -> Iterator[Trex]:
    """Build a :class:`Trex` batch run; NOT started (call :meth:`Trex.start`).

    Order (mirrors ``tapi_trex_create``, tapi_trex.c:1477-1672, modulo
    the workdir divergence in :func:`_shell_cmd`): build the argv,
    generate the random yaml config path and append ``--cfg``; ship
    the ASTF json and the rendered platform yaml to the agent over
    RCF (:meth:`pyte.rcf.RcfAgent.put_bytes`, matching the C tapi's
    ``rcf_ta_put_file`` transport); bind
    each :class:`PciBdf` endpoint when ``opts.driver`` is set; create
    the job (via a ``/bin/sh -c 'cd <workdir> && exec ...'`` wrapper);
    attach every stdout filter table. :meth:`Trex.close` runs on every
    exit path, started or not.

    Example::

        opts = batch.Opts(
            trex_exec="/opt/trex/v3.05/_t-rex-64-o",
            astf_json=astf_profile_json,   # an already-rendered ASTF profile
            clients=(batch.Endpoint(iface=batch.PciBdf("0000:01:00.0"),
                                    ip="1.1.1.1", gw="1.1.1.2"),),
            servers=(batch.Endpoint(iface=batch.PciBdf("0000:01:00.1"),
                                    ip="2.2.2.1", gw="2.2.2.2"),),
            duration=30.0, iom=batch.Iom.NORMAL, driver="vfio-pci")

        with batch.create(pco, opts) as trex:
            trex.start()
            trex.wait()                    # None (default) blocks forever
            rep = trex.report()
            print(rep.avg_tx, rep.avg_rx, rep.opt_cl["tcps_connects"])
        # close() (stop-tolerant destroy + remove the /tmp yaml and astf
        # json) has already run here, on every exit path -- success,
        # exception, or a block that never called start() at all.
    """
    yaml_path = yaml_cfg_path()
    astf_path = astf_json_path(opts.instance_prefix)
    argv = build_argv(opts, yaml_path)

    try:
        # Shipped via RCF's own file transport (rcf_ta_put_file), the
        # same one the C tapi_trex uses -- NOT pco.file_put()'s RPC
        # open/write/close loop, which used to fill the log with a
        # dozen lines of RPC noise per file.
        agent = rcf.agent(pco.ta)
        agent.put_bytes(opts.astf_json.encode("utf-8"), astf_path)
        agent.put_bytes(render_cfg_yaml(opts).encode("utf-8"), yaml_path)
        if opts.driver is not None:
            _bind_pci(pco, opts)
        # Mirrors nap-trex.c:272-274's proc->rpcs->silent_pass = true/
        # false around tapi_trex_create(): the job created here bakes
        # silent_pass=true into itself and its primary stdout/stderr
        # channels (tapi_job.c:init_channel: a primary channel's flag
        # comes from job->silent_pass, not the ambient at the time the
        # channel happens to be allocated).
        with pco.silent_pass():
            job = pco.job("/bin/sh", ["-c", _shell_cmd(opts.trex_exec, argv)])
    except BaseException:
        _remove_tmp_files(pco, yaml_path, astf_path)
        raise

    trex = Trex(pco, job, argv, yaml_path, astf_path)
    primary = None
    try:
        # Every filter attached here inherits the JOB's baked-in
        # silent_pass (channels[0]->silent_pass in
        # tapi_job_attach_filter()) regardless of the ambient value at
        # attach time -- wrapping it too just keeps this block visibly
        # parallel to the C, which attaches filters inside the same
        # tapi_trex_create() call the silent_pass toggle wraps.  This
        # window itself only silences the job_attach_filter/job_
        # filter_add_regexp calls it makes (job_start/job_wait are
        # ALSO silenced later, but that comes from job->silent_pass
        # baked once in the FIRST window above, at job creation --
        # tapi_job_create_named(), tapi_job.c:430 -- not from this
        # one). It does NOT, on its own, silence Filter.drain() in
        # report() down the line: that comes from each filter's own
        # baked-in silent_pass field, inherited from job->silent_pass
        # at attach time and unchanged since -- see the module
        # docstring.
        with pco.silent_pass():
            trex._attach_filters(opts)
        yield trex
    except BaseException as exc:
        primary = exc
        raise
    finally:
        cleanup_all(trex.close, primary=primary)
