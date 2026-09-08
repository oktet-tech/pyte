# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.process unit tests (offline: a fake Configurator)."""
import pytest

from pyte import process


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


def test_destroy_removes_the_subtree(fake_cfg):
    proc = process.Process.create("TST1", "p", "/bin/true")
    proc.destroy()
    assert not fake_cfg.exists("/agent:TST1/process:p")
    assert ("delete", "/agent:TST1/process:p", True) in fake_cfg.calls


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
