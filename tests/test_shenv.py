# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.shenv: PATH composition over a monkeypatched Configurator."""
import pytest

from pyte import shenv


class FakeCfg:
    """Holds one value per OID; records the get/set sequence."""

    def __init__(self, values=None, agents=()):
        self.values = dict(values or {})
        self.agents = list(agents)
        self.calls = []

    def get(self, oid, sync=False):
        self.calls.append(("get", oid))
        return self.values[oid]

    def set(self, oid, value, cvt=None):
        self.calls.append(("set", oid, value))
        self.values[oid] = value

    def find(self, pattern):
        self.calls.append(("find", pattern))

        class Node:
            def __init__(self, name):
                self.name = name

        return [Node(a) for a in self.agents]


@pytest.fixture()
def fake_cfg(monkeypatch):
    def install(cfg):
        monkeypatch.setattr(shenv, "cfg", cfg)
        return cfg
    return install


def test_default_sbin_dirs():
    assert shenv.DEFAULT_SBIN_DIRS == ("/usr/local/sbin", "/usr/sbin",
                                       "/sbin")


def test_ta_path_append_rereads_path_before_each_append(fake_cfg):
    """Each append builds on the value the Configurator reports, so a
    concurrent change is not overwritten."""
    cfg = fake_cfg(FakeCfg({"/agent:A/env:PATH": "/bin"}))

    shenv.ta_path_append("A", ("/x", "/y"))

    assert cfg.calls == [
        ("get", "/agent:A/env:PATH"),
        ("set", "/agent:A/env:PATH", "/bin:/x"),
        ("get", "/agent:A/env:PATH"),
        ("set", "/agent:A/env:PATH", "/bin:/x:/y"),
    ]


def test_ta_path_append_with_no_dirs_touches_nothing(fake_cfg):
    cfg = fake_cfg(FakeCfg({"/agent:A/env:PATH": "/bin"}))
    shenv.ta_path_append("A", ())
    assert cfg.calls == []


def test_ta_path_append_is_not_idempotent(fake_cfg):
    """A directory already present is appended again, by design."""
    cfg = fake_cfg(FakeCfg({"/agent:A/env:PATH": "/bin:/sbin"}))

    shenv.ta_path_append("A", ("/sbin",))

    assert cfg.values["/agent:A/env:PATH"] == "/bin:/sbin:/sbin"


def test_expand_path_all_ta_covers_every_agent(fake_cfg):
    cfg = fake_cfg(FakeCfg({"/agent:A/env:PATH": "/bin",
                            "/agent:B/env:PATH": "/usr/bin"},
                           agents=("A", "B")))

    shenv.expand_path_all_ta()

    assert cfg.calls[0] == ("find", "/agent:*")
    assert cfg.values["/agent:A/env:PATH"] == \
        "/bin:/usr/local/sbin:/usr/sbin:/sbin"
    assert cfg.values["/agent:B/env:PATH"] == \
        "/usr/bin:/usr/local/sbin:/usr/sbin:/sbin"


def test_expand_path_all_ta_honors_explicit_dirs(fake_cfg):
    cfg = fake_cfg(FakeCfg({"/agent:A/env:PATH": "/bin"}, agents=("A",)))

    shenv.expand_path_all_ta(("/opt/bin",))

    assert cfg.values["/agent:A/env:PATH"] == "/bin:/opt/bin"


def test_expand_path_all_ta_with_no_agents_is_a_noop(fake_cfg):
    cfg = fake_cfg(FakeCfg())
    shenv.expand_path_all_ta()
    assert cfg.calls == [("find", "/agent:*")]
