# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tester unit tests with the shared fake shim (pyte.testing)."""
import types

import pytest

from pyte import tester
from pyte.errors import RpcError, TeError
from pyte.testing import FakeShimLib


def test_modify_reqs_passes_expression(fake_shim):
    tester.modify_reqs("!FIO")
    assert fake_shim.calls == [("reqs", "!FIO")]


def test_add_trc_tag_value_default(fake_shim):
    tester.add_trc_tag("no_fio")
    assert fake_shim.calls == [("tag", "no_fio", "")]


def test_add_trc_tag_with_value(fake_shim):
    tester.add_trc_tag("linux", "6.17")
    assert fake_shim.calls == [("tag", "linux", "6.17")]


def test_errors_surface_as_teerror(fake_shim):
    fake_shim.rc = 0xBEEF
    with pytest.raises(TeError, match="add_trc_tag"):
        tester.add_trc_tag("x")
    with pytest.raises(TeError, match="modify_reqs"):
        tester.modify_reqs("x")


# -- try_add_trc_tag() / tags_*() --------------------------------------
#
# The collectors are exercised over a recording add_trc_tag, a
# monkeypatched pyte.cfg/pyte.net and a stub RPC server.


class _Tags:
    """Records accepted tags; fails the ones named in ``refuse``."""

    def __init__(self, refuse=()):
        self.refuse = set(refuse)
        self.added = []

    def __call__(self, name, value=None):
        if name in self.refuse:
            raise TeError(0xBEEF, f"add_trc_tag({name!r})")
        self.added.append((name, value))


class _Rpcs:
    def __init__(self, ta="Agt_A", out="1.2.3"):
        self.ta = ta
        self.out = out

    def sh(self, cmd):
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


@pytest.fixture()
def tags(monkeypatch, fake_shim):
    """A recording add_trc_tag, with logging captured by fake_shim."""
    rec = _Tags()
    monkeypatch.setattr(tester, "add_trc_tag", rec)
    return rec


@pytest.fixture()
def hw(monkeypatch):
    """Machine type and thread count, as tags_cpus() reads them."""
    from pyte import cfg, net

    def install(machine="x86_64", threads=8):
        monkeypatch.setattr(cfg, "get", lambda oid, sync=False: machine)
        monkeypatch.setattr(
            net, "agent",
            lambda ta: types.SimpleNamespace(
                cpu_counts=lambda: (threads // 2, threads)))
    return install


def test_try_add_trc_tag_returns_true_on_success(tags):
    assert tester.try_add_trc_tag("iut-small-box") is True
    assert tags.added == [("iut-small-box", None)]


def test_try_add_trc_tag_swallows_the_failure(tags, fake_shim):
    """Tag collection must never fail a prologue."""
    tags.refuse.add("bad")
    assert tester.try_add_trc_tag("bad") is False
    assert any("add_trc_tag('bad') failed" in text
               for text in fake_shim.texts(FakeShimLib.TE_LL_ERROR))


def test_tags_cpus_declares_machine_and_thread_count(tags, hw):
    hw(machine="aarch64", threads=12)

    assert tester.tags_cpus("Agt_A", "iut") == ["iut-aarch64",
                                                "iut-cpus:12"]
    assert tags.added == [("iut-aarch64", None), ("iut-cpus", "12")]


def test_tags_cpus_skips_a_refused_tag(tags, hw):
    hw(machine="x86_64", threads=8)
    tags.refuse.add("tst-x86_64")

    assert tester.tags_cpus("Agt_A", "tst") == ["tst-cpus:8"]


def test_tags_tool_version_declares_the_version(tags):
    assert tester.tags_tool_version(_Rpcs(out="1.25.3"), "nginx",
                                   "nginx -v") == ["nginx-1.25.3"]
    assert tags.added == [("nginx-1.25.3", None)]


def test_tags_tool_version_warns_when_the_tool_is_missing(tags,
                                                          fake_shim):
    rpcs = _Rpcs(ta="Agt_B")
    rpcs.out = RpcError(0xBEEF, "sh")

    assert tester.tags_tool_version(rpcs, "nginx", "nginx -v") == []
    assert tags.added == []
    assert fake_shim.texts(FakeShimLib.TE_LL_WARN) == [
        "Cannot get 'nginx' version (is it installed on Agt_B?)"]


def test_tags_tool_version_returns_nothing_for_a_refused_tag(tags):
    tags.refuse.add("nginx-1.25.3")
    assert tester.tags_tool_version(_Rpcs(out="1.25.3"), "nginx",
                                   "nginx -v") == []
