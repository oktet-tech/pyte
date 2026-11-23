# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.process unit tests (offline: a fake Configurator)."""
import sys
import types

import cffi
import pytest

from pyte import process
from pyte.rpc.server import RpcServer


class FakeCfg:
    """The slice of pyte.cfg that pyte.process uses."""

    def __init__(self):
        self.tree = {}
        self.calls = []

    def add(self, oid, value=None):
        self.calls.append(("add", oid, value))
        self.tree[oid] = value

    def set(self, oid, value, cvt=None):
        self.calls.append(("set", oid, value))
        self.tree[oid] = value

    def get(self, oid, sync=False):
        self.calls.append(("get", oid, sync))
        if oid not in self.tree:
            raise KeyError(oid)
        return self.tree[oid]

    def delete(self, oid, children=False):
        self.calls.append(("delete", oid, children))
        for key in [k for k in self.tree if k.startswith(oid)]:
            del self.tree[key]

    def exists(self, oid):
        return oid in self.tree


@pytest.fixture
def fake_cfg(monkeypatch):
    fake = FakeCfg()
    monkeypatch.setattr(process, "cfg", fake)
    return fake


def test_create_matches_the_models_access_modes(fake_cfg):
    """cm_process.yml makes exe and workdir read_write, so they exist
    with the parent and must be set -- adding one returns CS-EEXIST on
    a live Configurator. arg and env are read_create and must be
    added. A fake that accepted either would hide the difference, so
    the operation itself is asserted, not just the value."""
    process.Process.create(
        "TST1", "trex", "/usr/local/trex/t-rex-64",
        args=["-i"], env={"K": "v"}, workdir="/usr/local/trex")
    base = "/agent:TST1/process:trex"
    ops = {(op, oid) for op, oid, _ in fake_cfg.calls}
    assert ("add", base) in ops
    assert ("set", f"{base}/exe:") in ops
    assert ("set", f"{base}/workdir:") in ops
    assert ("add", f"{base}/arg:1") in ops
    assert ("add", f"{base}/env:K") in ops
    # ...and emphatically not the other way round.
    assert ("add", f"{base}/exe:") not in ops
    assert ("add", f"{base}/workdir:") not in ops


def test_create_installs_exe_args_env_and_workdir(fake_cfg):
    process.Process.create(
        "TST1", "trex", "/usr/local/trex/t-rex-64",
        args=["-i", "--astf"],
        env={"PYTHONWARNINGS": "ignore::SyntaxWarning"},
        workdir="/usr/local/trex")
    base = "/agent:TST1/process:trex"
    assert fake_cfg.tree[base] is None
    assert fake_cfg.tree[f"{base}/exe:"] == "/usr/local/trex/t-rex-64"
    assert fake_cfg.tree[f"{base}/arg:1"] == "-i"
    assert fake_cfg.tree[f"{base}/arg:2"] == "--astf"
    assert fake_cfg.tree[f"{base}/env:PYTHONWARNINGS"] == \
        "ignore::SyntaxWarning"
    assert fake_cfg.tree[f"{base}/workdir:"] == "/usr/local/trex"


def test_args_are_ordered_from_one(fake_cfg):
    """cm_process.yml names an arg instance by its order and the agent
    replays them sorted by it, so the names must not be sparse."""
    process.Process.create("TST1", "p", "/bin/true",
                           args=["a", "b", "c"])
    base = "/agent:TST1/process:p"
    assert [fake_cfg.tree[f"{base}/arg:{i}"] for i in (1, 2, 3)] == \
        ["a", "b", "c"]


def test_create_does_not_start(fake_cfg):
    """cm_process.yml forbids reconfiguring a running process, so every
    knob is written before status is ever set."""
    process.Process.create("TST1", "p", "/bin/true")
    assert "/agent:TST1/process:p/status:" not in fake_cfg.tree


def test_create_omits_workdir_when_not_given(fake_cfg):
    process.Process.create("TST1", "p", "/bin/true")
    assert "/agent:TST1/process:p/workdir:" not in fake_cfg.tree


def test_start_and_stop_write_status(fake_cfg):
    proc = process.Process.create("TST1", "p", "/bin/true")
    proc.start()
    assert fake_cfg.tree["/agent:TST1/process:p/status:"] == 1
    assert proc.running is True
    proc.stop()
    assert fake_cfg.tree["/agent:TST1/process:p/status:"] == 0
    assert proc.running is False


def test_running_reads_through_to_the_agent(fake_cfg):
    """A server can exit on its own; a cached status would report a
    dead process as alive."""
    proc = process.Process.create("TST1", "p", "/bin/true")
    proc.start()
    assert proc.running is True
    assert ("get", "/agent:TST1/process:p/status:", True) in \
        fake_cfg.calls


def test_destroy_deletes_the_parent_instance_only(fake_cfg):
    """The children go with the parent. Deleting them one by one would
    include the read_write leaves (exe, status, workdir), which the
    Configurator refuses with an ERROR line each and the C API then
    ignores, so the log of every teardown carried a page of errors
    that meant nothing."""
    proc = process.Process.create("TST1", "p", "/bin/true", args=["x"])
    proc.destroy()
    assert not fake_cfg.exists("/agent:TST1/process:p")
    assert ("delete", "/agent:TST1/process:p", False) in fake_cfg.calls


def test_exists_tracks_the_entry(fake_cfg):
    proc = process.Process("TST1", "p")
    assert proc.exists is False
    process.Process.create("TST1", "p", "/bin/true")
    assert proc.exists is True


def test_kill_writes_self_or_group(fake_cfg):
    proc = process.Process.create("TST1", "p", "/bin/true")
    proc.kill("SIGTERM")
    assert fake_cfg.tree["/agent:TST1/process:p/kill:/self:"] == \
        "SIGTERM"
    proc.kill("SIGKILL", group=True)
    assert fake_cfg.tree["/agent:TST1/process:p/kill:/group:"] == \
        "SIGKILL"


def test_exit_status_reads_type_and_value(fake_cfg):
    proc = process.Process.create("TST1", "p", "/bin/true")
    base = "/agent:TST1/process:p/status:/exit_status:"
    fake_cfg.tree[f"{base}/type:"] = 1
    fake_cfg.tree[f"{base}/value:"] = 9
    assert proc.exit_status == (1, 9)


def test_oid_is_the_instance_path(fake_cfg):
    assert process.Process("TST1", "trex").oid == \
        "/agent:TST1/process:trex"


# -- Process.create(): agent-side output settings -------------------------

def test_create_sets_output_nodes(fake_cfg):
    process.Process.create("TST1", "p", "/bin/true",
                           stdout_file="/tmp/o", stdout_log_level="none")
    sets = [(o, v) for k, o, v in fake_cfg.calls
            if k == "set" and "/output:" in o]
    assert sets == [
        ("/agent:TST1/process:p/output:stdout/file:", "/tmp/o"),
        ("/agent:TST1/process:p/output:stdout/log_level:", "none"),
    ]


def test_create_sets_stderr_nodes(fake_cfg):
    process.Process.create("TST1", "p", "/bin/true",
                           stderr_file="/tmp/e", stderr_log_level="RING")
    sets = [(o, v) for k, o, v in fake_cfg.calls
            if k == "set" and "/output:" in o]
    assert sets == [
        ("/agent:TST1/process:p/output:stderr/file:", "/tmp/e"),
        ("/agent:TST1/process:p/output:stderr/log_level:", "RING"),
    ]


def test_create_without_output_arguments_sets_no_output_nodes(fake_cfg):
    process.Process.create("TST1", "p", "/bin/true")
    assert not [o for _k, o, _v in fake_cfg.calls if "/output:" in o]


# -- Output: offset reads through a fake shim -------------------------------

class _FileLib:
    """In-memory agent filesystem behind the pyte_rpc_* file calls."""

    PYTE_O_RDONLY = 0
    PYTE_O_WRONLY = 1
    PYTE_O_CREAT = 2
    PYTE_O_TRUNC = 4
    PYTE_O_APPEND = 8
    PYTE_MODE_0644 = 0o644

    def __init__(self):
        self.files = {}
        self.fds = {}            # fd -> [path, position]
        self.next_fd = 3
        self.silent_pass = 0
        self._msg = cffi.FFI().new("char[]", b"No such file")
        #: silent_pass value seen by each file RPC
        self.seen = []
        self.reads = []          # sizes asked of read()

    def pyte_rpc_set_silent_pass(self, h, on):
        self.silent_pass = on

    def pyte_rpc_get_silent_pass(self, h):
        return self.silent_pass

    def pyte_rpc_errno(self, h):
        return 2

    # The error model decodes the rc it is given; a fixed one will do.
    def pyte_rc_module(self, rc):
        return 0

    def pyte_rc_error(self, rc):
        return rc

    def te_rc_mod2str(self, rc):
        return self._msg

    def te_rc_err2str(self, rc):
        return self._msg

    def pyte_rpc_err_msg(self, h):
        return self._msg

    def pyte_rpc_open(self, h, path, flags, mode, out):
        self.seen.append(self.silent_pass)
        path = path.decode()
        if path not in self.files:
            out[0] = -1
            return 0
        out[0] = self.next_fd
        self.fds[self.next_fd] = [path, 0]
        self.next_fd += 1
        return 0

    def pyte_rpc_close(self, h, fd, out):
        self.seen.append(self.silent_pass)
        del self.fds[fd]
        out[0] = 0
        return 0

    def pyte_rpc_lseek(self, h, fd, pos, whence, out):
        self.seen.append(self.silent_pass)
        path, cur = self.fds[fd]
        base = (0, cur, len(self.files[path]))[whence]
        self.fds[fd][1] = out[0] = base + pos
        return 0

    def pyte_rpc_read(self, h, fd, buf, size, out):
        self.seen.append(self.silent_pass)
        self.reads.append(size)
        path, cur = self.fds[fd]
        data = self.files[path][cur:cur + size]
        buf[0:len(data)] = data
        self.fds[fd][1] = cur + len(data)
        out[0] = len(data)
        return 0


@pytest.fixture
def agent(monkeypatch):
    lib = _FileLib()
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=cffi.FFI(), lib=lib))
    srv = RpcServer.__new__(RpcServer)
    srv._h = object()
    srv._silent_pass_depth = 0
    srv._silent_pass_was = 0
    lib.srv = srv
    return lib


def _output(agent, content=b"abc", cap=1 << 20):
    agent.files["/o"] = bytearray(content)
    return process.Output(agent.srv, "/o", cap=cap)


def test_output_new_returns_only_new_text(agent):
    out = _output(agent)
    out.mark()
    agent.files["/o"] += b"def"
    assert out.new() == "def"
    assert out.new() == ""


def test_output_since_mark_does_not_consume(agent):
    out = _output(agent)
    out.mark()
    agent.files["/o"] += b"def"
    assert out.new() == "def"
    assert out.since_mark() == "def"
    assert out.since_mark() == "def"


def test_output_cap_keeps_newest(agent):
    out = _output(agent, b"", cap=4)
    out.mark()
    agent.files["/o"] += b"0123456789"
    assert out.new() == "6789"


def test_output_file_shrank_restarts_from_zero(agent):
    out = _output(agent, b"a" * 100)
    out.mark()
    agent.files["/o"][:] = b"x"
    assert out.new() == "x"


def test_output_bad_utf8_never_raises(agent):
    out = _output(agent, b"\xff\xfeok")
    assert out.new() == "\ufffd\ufffdok"


def test_output_missing_file_reads_as_empty(agent):
    out = process.Output(agent.srv, "/absent")
    out.mark()
    assert out.new() == ""
    assert out.since_mark() == ""


def test_output_reads_in_chunks_of_at_most_64k(agent):
    out = _output(agent, b"x" * (200 * 1024))
    assert len(out.new()) == 200 * 1024
    assert agent.reads and max(agent.reads) <= 64 * 1024


def test_save_since_mark_is_uncapped(agent, tmp_path):
    out = _output(agent, b"", cap=4)
    out.mark()
    agent.files["/o"] += b"z" * (3 << 20)
    dest = tmp_path / "saved"
    assert out.save_since_mark(dest) == 3 << 20
    assert dest.stat().st_size == 3 << 20


def test_output_rpcs_run_under_silent_pass(agent, tmp_path):
    """A read must add no RPC trace rows to the test log."""
    out = _output(agent)
    out.mark()
    agent.files["/o"] += b"def"
    out.new()
    out.since_mark()
    out.save_since_mark(tmp_path / "s")
    assert agent.seen and all(v == 1 for v in agent.seen)
    assert agent.silent_pass == 0          # restored afterwards


def test_output_leaves_no_descriptor_open(agent):
    out = _output(agent)
    out.new()
    assert agent.fds == {}
