# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex._astf_ops unit tests (stub client, no agent)."""
import builtins
import inspect
import re
import sys
import types

from pyte.tools.trex import _astf_ops as ops


class FakeCli:
    def __init__(self):
        self.calls = []
        self.stats = {"global": {"active_flows": 7}}

    def reset(self):
        self.calls.append(("reset",))

    def load_profile(self, profile, tunables=None):
        self.calls.append(("load_profile", profile, tunables))

    def start(self, mult=1, duration=-1, nc=False, latency_pps=0):
        self.calls.append(("start", mult, duration, nc, latency_pps))

    def stop(self):
        self.calls.append(("stop",))

    def wait_on_traffic(self, timeout=None):
        self.calls.append(("wait_on_traffic", timeout))

    def clear_stats(self):
        self.calls.append(("clear_stats",))

    def get_stats(self):
        return self.stats

    def get_traffic_stats(self, **kwargs):
        self.calls.append(("get_traffic_stats", kwargs))
        return {"client": {"tcps_connects": 3}, "server": {}}

    def get_latency_stats(self):
        return {"latency": {}}

    def get_tg_names(self):
        return ["a", "b"]

    def get_traffic_tg_stats(self, names):
        self.calls.append(("tg_stats", tuple(names)))
        return {n: {"tcps_connects": 1} for n in names}

    def disconnect(self):
        self.calls.append(("disconnect",))


def test_every_op_is_self_contained():
    """No op may reference module globals: they run on the agent."""
    for name, fn in vars(ops).items():
        if name.startswith("_") or not inspect.isfunction(fn):
            continue
        src = inspect.getsource(fn)
        body = src.split("\n", 1)[1]
        assert "ops." not in body, f"{name} calls a sibling"
        for other in vars(ops):
            if other != name and not other.startswith("_") \
                    and inspect.isfunction(getattr(ops, other, None)):
                assert f"{other}(" not in body, \
                    f"{name} calls sibling {other}"


def test_bootstrap_has_no_hardcoded_trex_version():
    """No install path may name a TRex or scapy version."""
    src = inspect.getsource(ops.bootstrap)
    assert "3.06" not in src
    assert "trex-v" not in src
    assert "scapy-2.4.3" not in src
    assert not re.search(r"scapy-\d", src)


def test_bootstrap_imports_trex_before_the_scapy_shim():
    """``import trex`` must come first, then the six.moves shim.

    ``trex/__init__.py`` puts its own bundled external_libs on
    sys.path and, while doing so, deletes from sys.modules every
    already-imported module of the same name whose path is not the
    one it just computed from ``os.path.realpath(__file__)``. A scapy
    imported before that -- and the ``scapy.modules.six.moves``
    sys.modules entries installed alongside it -- is thrown away, and
    the ASTF client import then fails on ``six.moves`` with no hint
    of why. The live bring-up on <tester-host> failed exactly this way,
    because ``/usr/local/trex`` is a symlink and so is spelled
    differently from the realpath TRex compares against.
    """
    src = inspect.getsource(ops.bootstrap)
    trex_at = re.search(r"^    import trex\b", src, re.M).start()
    shim_at = src.index("import scapy.modules.six")
    api_at = src.index("from trex.astf.api")
    assert trex_at < shim_at < api_at


def test_bootstrap_cgi_shim_survives_non_import_error(monkeypatch):
    """The cgi shim must be guarded by a bare except Exception, not
    except ImportError only, like the other three shims: a broken
    cgi import (anything other than a clean ModuleNotFoundError)
    must not escape bootstrap and kill bring-up."""
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "cgi":
            raise RuntimeError("simulated corrupted cgi import")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    # A fake trex.astf.api so bootstrap can run past the real import
    # and the connect-retry loop without a TRex install on this host.
    class _FakeASTFClient:
        def __init__(self, **kwargs):
            pass

        def set_verbose(self, level):
            pass

        def connect(self):
            pass

    api_mod = types.ModuleType("trex.astf.api")
    api_mod.ASTFClient = _FakeASTFClient
    monkeypatch.setitem(sys.modules, "trex", types.ModuleType("trex"))
    monkeypatch.setitem(sys.modules, "trex.astf",
                        types.ModuleType("trex.astf"))
    monkeypatch.setitem(sys.modules, "trex.astf.api", api_mod)

    cli = ops.bootstrap("/nonexistent/interactive", "127.0.0.1",
                        4501, 4500, 1)
    assert isinstance(cli, _FakeASTFClient)


def test_reset_calls_through():
    cli = FakeCli()
    ops.reset(cli)
    assert cli.calls == [("reset",)]


def test_load_profile_passes_tunables():
    cli = FakeCli()
    ops.load_profile(cli, "/tmp/p.py", {"flow_size": 10})
    assert cli.calls[0] == ("load_profile", "/tmp/p.py",
                            {"flow_size": 10})


def test_load_profile_with_no_tunables_passes_empty_dict():
    cli = FakeCli()
    ops.load_profile(cli, "/tmp/p.py", None)
    assert cli.calls[0] == ("load_profile", "/tmp/p.py", {})


def test_start_forwards_every_argument():
    cli = FakeCli()
    ops.start(cli, 2.5, 30.0, True, 100)
    assert cli.calls == [("start", 2.5, 30.0, True, 100)]


def test_get_stats_returns_a_plain_dict():
    out = ops.get_stats(FakeCli())
    assert out == {"global": {"active_flows": 7}}


def test_get_traffic_stats_passes_skip_zero_false():
    """The native default skip_zero=True hides most err_* counters."""
    cli = FakeCli()
    out = ops.get_traffic_stats(cli)
    assert cli.calls == [("get_traffic_stats", {"skip_zero": False})]
    assert out == {"client": {"tcps_connects": 3}, "server": {}}


def test_get_tg_stats_asks_for_the_named_groups():
    cli = FakeCli()
    out = ops.get_tg_stats(cli, ["a", "b"])
    assert cli.calls == [("tg_stats", ("a", "b"))]
    assert out == {"a": {"tcps_connects": 1},
                   "b": {"tcps_connects": 1}}


def test_get_tg_names_survives_a_profile_without_groups():
    class NoGroups(FakeCli):
        def get_tg_names(self):
            raise RuntimeError("not supported")

    assert ops.get_tg_names(NoGroups()) == []


def test_write_profile_then_remove_file_round_trip():
    path = ops.write_profile("print(1)\n", ".py")
    with open(path) as f:
        assert f.read() == "print(1)\n"
    assert ops.remove_file(path) == {"removed": True}
    assert ops.remove_file(path) == {"removed": False}
