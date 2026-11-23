# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Test.attach(): the attachments/node_id<N> layout Bublik reads."""
import json

import pytest

from pyte import test
from pyte._params import Params


@pytest.fixture()
def t(fake_shim, tmp_path, monkeypatch):
    monkeypatch.setenv("TE_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("TE_RUN_DIR", raising=False)
    return test.Test(Params({"te_test_id": "8"}))


def _dir(tmp_path):
    return tmp_path / "attachments" / "node_id8"


def _entries(tmp_path):
    data = json.loads((_dir(tmp_path) / "attachments.json").read_text())
    assert data["version"] == 1
    return data["attachments"]


def test_attach_bytes_writes_file_and_json(t, tmp_path, fake_shim):
    path = t.attach("trex-console.txt", b"hello\n", "TRex console")
    assert path == _dir(tmp_path) / "trex-console.txt"
    assert path.read_bytes() == b"hello\n"
    assert _entries(tmp_path) == [{
        "type": "text",
        "view_type": "inline",
        "name": "trex-console",
        "description": "TRex console",
        "download_enabled": True,
        "path": "./trex-console.txt",
    }]
    assert fake_shim.logs == [
        (fake_shim.TE_LL_RING, "Attachment: trex-console.txt (6 B)")]


def test_attach_copies_a_file(t, tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 2048)
    t.attach("c.txt", src)
    assert (_dir(tmp_path) / "c.txt").read_bytes() == b"x" * 2048
    t.attach("d.txt", str(src))
    assert (_dir(tmp_path) / "d.txt").stat().st_size == 2048


def test_attach_human_sizes(t, tmp_path, fake_shim):
    t.attach("a", b"x" * 1536)
    t.attach("b", b"x" * (3 * 1024 * 1024))
    texts = [txt for _, txt in fake_shim.logs]
    assert texts == ["Attachment: a (1.5 KiB)", "Attachment: b (3.0 MiB)"]


def test_attach_twice_same_name_replaces(t, tmp_path):
    t.attach("trex-console.txt", b"old")
    t.attach("trex-console.txt", b"new")
    assert len(_entries(tmp_path)) == 1
    assert (_dir(tmp_path) / "trex-console.txt").read_bytes() == b"new"


def test_attach_two_names_two_entries(t, tmp_path):
    t.attach("a.txt", b"1")
    t.attach("b.txt", b"2")
    assert [e["path"] for e in _entries(tmp_path)] == ["./a.txt", "./b.txt"]


def test_attach_falls_back_to_run_dir(fake_shim, tmp_path, monkeypatch):
    monkeypatch.delenv("TE_LOG_DIR", raising=False)
    monkeypatch.setenv("TE_RUN_DIR", str(tmp_path))
    tt = test.Test(Params({"te_test_id": "8"}))
    assert tt.attach("a.txt", b"1") == _dir(tmp_path) / "a.txt"


def test_attach_without_log_dir_warns_and_returns_none(
        fake_shim, monkeypatch):
    monkeypatch.delenv("TE_LOG_DIR", raising=False)
    monkeypatch.delenv("TE_RUN_DIR", raising=False)
    tt = test.Test(Params({"te_test_id": "8"}))
    assert tt.attach("a.txt", b"1") is None
    assert tt.attach("b.txt", b"1") is None
    warns = [x for x in fake_shim.logs if x[0] == fake_shim.TE_LL_WARN]
    assert len(warns) == 1


def test_attach_with_test_id_zero_returns_none(
        fake_shim, tmp_path, monkeypatch):
    monkeypatch.setenv("TE_LOG_DIR", str(tmp_path))
    tt = test.Test(Params({}))
    assert tt.attach("a.txt", b"1") is None
    assert not (tmp_path / "attachments").exists()


@pytest.mark.parametrize("name", [
    "../x", "a/b", ".", "..", "a b", "", "x" * 129, "\u00e9.txt",
    "a\n", "/etc/passwd"])
def test_attach_rejects_bad_name(t, tmp_path, name):
    with pytest.raises(ValueError):
        t.attach(name, b"1")
    assert not (tmp_path / "attachments").exists()


def test_attach_accepts_name_charset_edges(t):
    assert t.attach("a-b_c.d:E9", b"1") is not None
    assert t.attach("x" * 128, b"1") is not None
