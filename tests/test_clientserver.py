# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools._clientserver unit tests (offline, fake pco/job)."""
import signal

import pytest

from pyte.tools._clientserver import Endpoint, serve


class FakeChannel:
    def __init__(self):
        self.logged = None

    def log(self, level=None):
        self.logged = level


class FakeJob:
    def __init__(self):
        self.events = []
        self.stderr = FakeChannel()
        self.stop_signal = None

    def start(self):
        self.events.append("start")

    def stop(self, *a, **k):
        self.events.append("stop")
        self.stop_signal = k.get("signal")

    def destroy(self, *a, **k):
        self.events.append("destroy")


class FakePco:
    def __init__(self, job):
        self._job = job
        self.created = None
        self.slept = None

    def job(self, program, args=None):
        self.created = (program, args)
        return self._job

    def sleep(self, seconds):
        self.slept = seconds


def test_serve_lifecycle_and_endpoint():
    job = FakeJob()
    pco = FakePco(job)
    with serve(pco, "iperf3", ["-s", "-J"],
               host="127.0.0.1", port=5201, ready_delay=0.5) as ep:
        assert ep == Endpoint("127.0.0.1", 5201)
        assert pco.created == ("iperf3", ["-s", "-J"])
        assert job.events == ["start"]      # started, not yet stopped
        assert pco.slept == 0.5             # readiness wait happened
    # teardown on exit: stop then destroy
    assert job.events == ["start", "stop", "destroy"]


def test_serve_stops_with_documented_sigint_default():
    job = FakeJob()
    pco = FakePco(job)
    with serve(pco, "iperf3", ["-s"], host="h", port=1, ready_delay=0):
        pass
    assert job.stop_signal == signal.SIGINT


def test_serve_stops_with_explicit_term_signal():
    job = FakeJob()
    pco = FakePco(job)
    with serve(pco, "netserver", [], host="h", port=1, ready_delay=0,
               term=signal.SIGKILL):
        pass
    assert job.stop_signal == signal.SIGKILL


def test_serve_destroys_on_start_failure():
    job = FakeJob()

    def boom():
        raise RuntimeError("start failed")
    job.start = boom
    pco = FakePco(job)

    with pytest.raises(RuntimeError, match="start failed"):
        with serve(pco, "iperf3", ["-s"], host="h", port=1, ready_delay=0):
            pass
    assert "destroy" in job.events     # cleaned up despite start failure
