# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the pure-Python parts of pyte.rcf."""

import pytest

from pyte.rcf import _conf_pairs, _grow_loop, _pick_port, _split_ta_list


def test_split_ta_list_basic():
    assert _split_ta_list(b"Agt_A\x00Agt_B\x00\x00") == ["Agt_A", "Agt_B"]


def test_split_ta_list_single():
    assert _split_ta_list(b"Agt_A\x00\x00") == ["Agt_A"]


def test_split_ta_list_empty():
    assert _split_ta_list(b"\x00") == []
    assert _split_ta_list(b"") == []


def test_split_ta_list_no_trailing_nul():
    # Defensive: used length may exclude the final terminator
    assert _split_ta_list(b"Agt_A\x00Agt_B") == ["Agt_A", "Agt_B"]


def test_pick_port_range():
    p = _pick_port()
    assert 20000 <= p <= 32000


def test_pick_port_varies():
    assert len({_pick_port() for _ in range(20)}) > 1


# -- _conf_pairs tests ------------------------------------------------------
#
# The keys are pinned to what the Configurator consumes when starting a
# managed agent (engine/configurator/conf_rcf.c, cfg_rcfunix_make_confstr):
# "port" is mandatory; an empty "host" value means an engine-host local
# agent (te/lib/rcfunix treats empty host as local, exactly like
# conf/rcf.conf with TE_IUT unset); "sudo" is a presence-only key whose
# value MUST be empty -- conf_rcf.c rejects a non-empty value with EINVAL.

def test_conf_pairs_basic():
    assert _conf_pairs(host=None, port=21000, sudo=False) == [
        ("host", ""), ("port", "21000")]


def test_conf_pairs_remote_sudo():
    assert _conf_pairs(host="test", port=21000, sudo=True) == [
        ("host", "test"), ("port", "21000"), ("sudo", "")]


def test_dynamic_agent_repr_shows_backend():
    """remove() routing depends on the backend; repr must expose it."""
    from pyte.rcf import DynamicAgent

    assert repr(DynamicAgent("Agt_X", managed=True)) == \
        "<DynamicAgent Agt_X managed>"
    assert repr(DynamicAgent("Agt_X")) == "<DynamicAgent Agt_X raw>"


def test_add_agent_sudo_requires_managed():
    """sudo rides in the managed conf kvpairs; the raw path is unchanged."""
    from pyte.rcf import add_agent

    with pytest.raises(ValueError, match="managed=True"):
        add_agent("Agt_X", sudo=True)


def test_conf_pairs_appends_extra_in_order():
    assert _conf_pairs("h", 5, extra=[("connect", "10.0.0.1"),
                                      ("shell", "ip netns exec ns1")]) == \
        [("host", "h"), ("port", "5"), ("connect", "10.0.0.1"),
         ("shell", "ip netns exec ns1")]


def test_conf_pairs_rejects_unknown_and_duplicate_keys():
    with pytest.raises(ValueError, match="unknown rcfunix key 'bogus'"):
        _conf_pairs("h", 5, extra=[("bogus", "1")])
    with pytest.raises(ValueError, match="duplicate"):
        _conf_pairs("h", 5, extra=[("port", "6")])


def test_add_agent_conf_requires_managed():
    from pyte.rcf import add_agent

    with pytest.raises(ValueError, match="conf requires managed=True"):
        add_agent("A", conf=[("shell", "x")])


def test_add_agent_managed_passes_extra_pairs(monkeypatch):
    from pyte import rcf

    seen = {}

    class FakeLib:
        PYTE_RCF_TA_REBOOTABLE = 1

        def pyte_cfg_rcf_add_ta(self, name, type_, lib, kv, n, flags):
            seen["kv"] = [kv[i] for i in range(2 * n)]
            seen["n"] = n
            return 0

    class FakeFfi:
        def new(self, decl, init=None):
            return list(init) if decl.startswith("const char *[]") \
                else init

    monkeypatch.setattr(rcf, "_shim", lambda: (FakeFfi(), FakeLib()))
    monkeypatch.setattr(rcf, "check", lambda rc, *a, **k: None)
    rcf.add_agent("A", port=7, managed=True, sudo=True,
                  conf=[("shell", "ip netns exec ns1")])
    assert seen["n"] == 4
    assert seen["kv"] == [b"host", b"", b"port", b"7", b"sudo", b"",
                          b"shell", b"ip netns exec ns1"]


# -- _grow_loop tests -------------------------------------------------------

def test_grow_loop_succeeds_first_try():
    """No retry needed: call succeeds immediately."""
    def call(size):
        return 0, b"result"

    assert _grow_loop(call) == b"result"


def test_grow_loop_retries_on_smallbuf():
    """Retries once on ESMALLBUF, then succeeds with doubled size."""
    sizes = []

    def call(size):
        sizes.append(size)
        if len(sizes) == 1:
            return "ESMALLBUF", None
        return 0, b"Agt_A\x00Agt_B\x00\x00"

    data = _grow_loop(call, initial=4096)
    assert _split_ta_list(data) == ["Agt_A", "Agt_B"]
    assert sizes == [4096, 8192]


def test_grow_loop_raises_on_overflow():
    """Raises RuntimeError when buffer would exceed 1 MiB."""
    def call(size):
        return "ESMALLBUF", None

    with pytest.raises(RuntimeError, match="1 MiB"):
        _grow_loop(call, initial=4096)


def test_grow_loop_propagates_other_errors():
    """Propagates non-ESMALLBUF errors unchanged."""
    sentinel = ValueError("RCF error")

    def call(size):
        return sentinel, None

    with pytest.raises(ValueError, match="RCF error"):
        _grow_loop(call)


# -- DynamicAgent.__exit__ ---------------------------------------------------
#
# Same cleanup_all policy as Job.__exit__/RpcServer.__exit__: a failing
# remove() during unwind must never replace the body's exception, and
# with no body exception the teardown failure is the only failure there
# is to report.

def _raiser(exc):
    def go():
        raise exc
    return go


def test_dynamic_agent_ctx_mgr_preserves_body_exc_when_remove_fails(
        monkeypatch):
    """__exit__ already receives the body's exception as its second
    argument, so a failing remove() must not replace it: the body's
    exception keeps its identity and the remove() failure is attached
    as a cleanup_errors entry instead."""
    from pyte.rcf import DynamicAgent

    agent = DynamicAgent("Agt_X")
    monkeypatch.setattr(agent, "remove",
                        _raiser(RuntimeError("remove failed")))
    boom = RuntimeError("BODY BOOM")

    with pytest.raises(RuntimeError) as info:
        with agent:
            raise boom

    assert info.value is boom
    assert len(boom.cleanup_errors) == 1


def test_dynamic_agent_ctx_mgr_raises_remove_failure_on_clean_exit(
        monkeypatch):
    """With no body exception to preserve, a teardown failure must
    still surface -- it is the only failure there is to report."""
    from pyte.rcf import DynamicAgent

    agent = DynamicAgent("Agt_X")
    monkeypatch.setattr(agent, "remove",
                        _raiser(RuntimeError("remove failed")))

    with pytest.raises(RuntimeError, match="remove failed"):
        with agent:
            pass
