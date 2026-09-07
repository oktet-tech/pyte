# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Agent-side op-functions shipped to the TRex host via pyte.remote.

Each function runs in the agent's python3 (started by pyte.remote). It
MUST be self-contained: all imports inside the body, no closures, no
module-level references, no calls to siblings here (helpers are nested
defs). Return values must be JSON-able; the live ASTFClient crosses
back as a RemoteObject (bootstrap) and is passed back in as ``cli``.
"""
from __future__ import annotations


def write_profile(text, suffix):
    """Write a profile source to a temp file on the agent; return path."""
    import os
    import tempfile
    fd, path = tempfile.mkstemp(prefix="pyte_astf_", suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


def remove_file(path):
    """Best-effort removal of a session temp file (teardown)."""
    import os
    try:
        os.remove(path)
    except OSError:
        return {"removed": False}
    return {"removed": True}


def bootstrap(trex_lib_dir, server, sync_port, async_port, timeout):
    """Install compatibility shims, import the bundled ASTF client,
    connect (with retry), return it.

    TRex's bundled client stack predates several Python stdlib
    removals; the target agent's python3 may be new enough to hit all
    of them. The shims are installed in a fixed order, and the order
    is the whole point -- see below.

    - ``imp`` was removed in Python 3.12; ``trex_astf_profile.py``
      only calls ``imp.reload()``, so a stub exposing that one
      attribute (as importlib.reload) is registered.
    - ``cgi`` was removed in Python 3.13; the real module is used
      when present, and only on ImportError is a minimal stub
      (escape, parse_header) registered instead. It has to be in
      place before anything imports scapy, whose ``themes`` module
      imports ``cgi`` at module scope.
    - ``import trex`` is then done on its own, BEFORE the scapy shim
      and before ``trex.astf.api``. ``trex/__init__.py`` puts its own
      bundled ``external_libs/*`` directories on sys.path, and while
      doing so it deletes from sys.modules every already-imported
      module whose name matches one of those libraries and whose
      ``__path__`` does not start with the path it just computed.
      That path comes from ``os.path.realpath(__file__)``, so on the
      usual install (``/usr/local/trex`` a symlink to
      ``/usr/local/trex-<version>``) it is spelled differently from
      the caller's ``trex_lib_dir`` -- and a scapy imported by us
      beforehand, under any other spelling, is purged along with the
      sys.modules entries the next shim installs. Letting TRex set
      scapy up itself sidesteps the whole question, which is why no
      scapy path is derived here.
    - ``scapy.modules.six`` registers ``six.moves`` and
      ``six.moves.queue`` via the old find_module/load_module
      meta-path protocol, removed in Python 3.12; they are
      pre-registered in sys.modules directly, after the ``import
      trex`` above so nothing removes them again.

    Each shim is independently guarded: one that turns out to be
    unnecessary (older Python, or a newer TRex that no longer needs
    it) must not break bring-up.
    """
    import sys
    import time

    try:
        import importlib
        import types
        if "imp" not in sys.modules:
            _imp_shim = types.ModuleType("imp")
            _imp_shim.reload = importlib.reload
            sys.modules["imp"] = _imp_shim
    except Exception:
        pass

    try:
        try:
            import cgi
            del cgi
        except ImportError:
            import html
            import types
            _cgi_shim = types.ModuleType("cgi")
            _cgi_shim.escape = html.escape

            def _parse_header(line):
                parts = line.split(";")
                key = parts[0].strip()
                params = {}
                for part in parts[1:]:
                    if "=" not in part:
                        continue
                    name, _, value = part.partition("=")
                    params[name.strip()] = value.strip().strip('"')
                return key, params

            _cgi_shim.parse_header = _parse_header
            sys.modules["cgi"] = _cgi_shim
    except Exception:
        pass

    if trex_lib_dir not in sys.path:
        sys.path.insert(0, trex_lib_dir)

    import trex        # noqa: F401  sets up its bundled external_libs

    try:
        import scapy.modules.six as _six
        sys.modules["scapy.modules.six.moves"] = _six.moves
        sys.modules["scapy.modules.six.moves.queue"] = _six.moves.queue
    except Exception:
        pass

    from trex.astf.api import ASTFClient
    c = ASTFClient(server=server, sync_port=sync_port,
                   async_port=async_port)
    c.set_verbose("none")
    deadline = time.time() + timeout
    last = None
    while True:
        try:
            c.connect()
            return c
        except Exception as exc:      # server not up yet / transient
            last = exc
            if time.time() >= deadline:
                raise RuntimeError(
                    "could not connect to the TRex ASTF server "
                    "within %ss: %r" % (timeout, last))
            time.sleep(0.5)


def reset(cli):
    """Release and re-acquire every port, clearing any loaded profile."""
    cli.reset()
    return {"ok": True}


def load_profile(cli, path, tunables):
    """Load a profile file, forwarding tunables as a dict.

    There is no per-template group naming here: assigning tg_name
    after profile load is a silent no-op (the tg_name to tg_id
    mapping happens once inside ASTFProfile.__init__, before any
    post-load attribute assignment can reach it), so a tg_prefix
    parameter would not do anything useful and is not offered.
    """
    cli.load_profile(path, tunables or {})
    return {"ok": True}


def start(cli, mult, duration, nc, latency_pps):
    """Start traffic; never blocks (the caller polls and waits)."""
    cli.start(mult=mult, duration=duration, nc=nc,
              latency_pps=latency_pps)
    return {"ok": True}


def stop(cli):
    """Stop traffic immediately."""
    cli.stop()
    return {"ok": True}


def wait_on_traffic(cli, timeout):
    """Block on the agent until traffic finishes or timeout elapses."""
    if timeout is None:
        cli.wait_on_traffic()
    else:
        cli.wait_on_traffic(timeout=timeout)
    return {"ok": True}


def clear_stats(cli):
    """Zero every counter before a measurement window."""
    cli.clear_stats()
    return {"ok": True}


def get_stats(cli):
    """Aggregate counters, including active_flows."""
    return cli.get_stats()


def get_traffic_stats(cli):
    """Client-side and server-side ASTF counter families.

    Passes skip_zero=False: the native default (True) omits every
    counter that is currently zero, including nearly all of the
    err_* family, which would make a caller wrongly conclude there
    were no flow-table errors because it never saw the keys.
    """
    return cli.get_traffic_stats(skip_zero=False)


def get_latency_stats(cli):
    """Latency counters; empty dict when no latency stream ran."""
    try:
        return cli.get_latency_stats()
    except Exception:
        return {}


def get_tg_names(cli):
    """Template-group names, or [] when the profile defines none."""
    try:
        return list(cli.get_tg_names())
    except Exception:
        return []


def get_tg_stats(cli, names):
    """Per-template-group counters for the given group names."""
    if not names:
        return {}
    return cli.get_traffic_tg_stats(list(names))


def disconnect(cli):
    """Best-effort disconnect (teardown)."""
    try:
        cli.disconnect()
    except Exception:
        return {"ok": False}
    return {"ok": True}
