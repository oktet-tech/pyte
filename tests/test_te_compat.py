# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
import types

import pytest

import te_compat


def _fake_run(returncode):
    def run(argv, **_kwargs):
        assert argv[0] == "git"
        return types.SimpleNamespace(returncode=returncode)
    return run


def _make_te(tmp_path, with_git=True):
    if with_git:
        (tmp_path / ".git").mkdir()
    return str(tmp_path)


def test_read_min_te_commit_present(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text('[tool.pyte]\nmin_te_commit = "abc123"\n')
    assert te_compat.read_min_te_commit(p) == "abc123"


def test_read_min_te_commit_absent(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "pyte"\n')
    assert te_compat.read_min_te_commit(p) is None


def test_skip_when_min_commit_none(tmp_path):
    # No exception, no run() call needed.
    te_compat.check_te_compat(_make_te(tmp_path), None, env={},
                              run=_fake_run(1))


def test_skip_when_env_override(tmp_path):
    te_compat.check_te_compat(_make_te(tmp_path), "abc123",
                              env={"PYTE_SKIP_TE_CHECK": "1"},
                              run=_fake_run(1))


def test_skip_when_te_base_falsy():
    te_compat.check_te_compat("", "abc123", env={}, run=_fake_run(1))
    te_compat.check_te_compat(None, "abc123", env={}, run=_fake_run(1))


def test_skip_when_not_a_git_checkout(tmp_path):
    te_compat.check_te_compat(_make_te(tmp_path, with_git=False), "abc123",
                              env={}, run=_fake_run(1))


def test_pass_when_ancestor(tmp_path):
    te_compat.check_te_compat(_make_te(tmp_path), "abc123", env={},
                              run=_fake_run(0))


def test_raise_when_not_ancestor(tmp_path):
    with pytest.raises(RuntimeError, match="does not include it"):
        te_compat.check_te_compat(_make_te(tmp_path), "abc123", env={},
                                  run=_fake_run(1))


def test_raise_when_commit_missing(tmp_path):
    with pytest.raises(RuntimeError, match="not present"):
        te_compat.check_te_compat(_make_te(tmp_path), "abc123", env={},
                                  run=_fake_run(128))


def test_skip_when_git_missing(tmp_path):
    def run(argv, **_kwargs):
        raise FileNotFoundError("git")
    te_compat.check_te_compat(_make_te(tmp_path), "abc123", env={}, run=run)
