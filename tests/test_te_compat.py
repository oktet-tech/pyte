# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
import subprocess
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


# Tag-ref coverage below. These use a real temporary git repo and the
# real `git` binary (default run=subprocess.run) instead of a fake run(),
# to prove that `git merge-base --is-ancestor` genuinely accepts a tag
# name and not only a commit hash -- the earlier tests only mock
# subprocess and would not catch a regression there.

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                    capture_output=True)


def _git_repo_with_tag_on_head(tmp_path):
    """A repo whose HEAD is tagged v1.0.0."""
    repo = tmp_path / "te"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "file.txt").write_text("one\n")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "first")
    _git(repo, "tag", "v1.0.0")
    return repo


def _git_repo_with_unmerged_tag(tmp_path):
    """A repo where HEAD does not contain the tagged commit v2.0.0.

    The tag sits on a side branch that was never merged back, so it is
    not an ancestor of HEAD even though the ref exists in the repo.
    """
    repo = tmp_path / "te"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "file.txt").write_text("one\n")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "first")
    base_branch = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--short", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "file.txt").write_text("two\n")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "second")
    _git(repo, "tag", "v2.0.0")
    _git(repo, "checkout", "-q", base_branch)
    return repo


def test_tag_ref_that_is_ancestor_passes(tmp_path):
    repo = _git_repo_with_tag_on_head(tmp_path)
    # No run= override: exercises the real git binary.
    te_compat.check_te_compat(str(repo), "v1.0.0", env={})


def test_tag_ref_that_is_not_ancestor_raises(tmp_path):
    repo = _git_repo_with_unmerged_tag(tmp_path)
    with pytest.raises(RuntimeError, match="does not include it"):
        te_compat.check_te_compat(str(repo), "v2.0.0", env={})
