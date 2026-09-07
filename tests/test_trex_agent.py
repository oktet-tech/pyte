# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex._agent: where a session's temp files land.

The Configurator is faked at pyte.cfg.get, so these run offline.
"""
from pyte.testing import FakeShimLib
from pyte.tools.trex import _agent


def _fake_get(monkeypatch, value):
    """Answer every cfg.get() with *value*, recording the OID asked."""
    seen = []

    def _get(oid, sync=False):
        seen.append((oid, sync))
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr("pyte.cfg.get", _get)
    return seen


def test_tmp_dir_reads_the_agents_published_directory(monkeypatch):
    seen = _fake_get(monkeypatch, "/tmp/te_agt")
    assert _agent.tmp_dir("Agt_A") == "/tmp/te_agt"
    # The knob is volatile, so the generated facade synchronizes it.
    assert seen == [("/agent:Agt_A/tmp_dir:", True)]


def test_tmp_dir_falls_back_and_warns_when_the_knob_is_empty(
        fake_shim, monkeypatch):
    """An agent that publishes nothing must not fail bring-up -- but
    the files then land in /tmp, which has to say so somewhere."""
    _fake_get(monkeypatch, "")
    assert _agent.tmp_dir("Agt_A") is None
    warns = "\n".join(fake_shim.texts(FakeShimLib.TE_LL_WARN))
    assert "/agent:Agt_A/tmp_dir:" in warns
    assert "default temp directory" in warns


def test_tmp_dir_falls_back_and_warns_when_the_lookup_fails(
        fake_shim, monkeypatch):
    """No Configurator entry at all (an older agent, a trimmed tree)
    is a warning too, not a bring-up failure."""
    _fake_get(monkeypatch, RuntimeError("no such instance"))
    assert _agent.tmp_dir("Agt_A") is None
    warns = "\n".join(fake_shim.texts(FakeShimLib.TE_LL_WARN))
    assert "no such instance" in warns
    assert "default temp directory" in warns
