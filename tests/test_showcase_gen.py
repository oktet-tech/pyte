# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the showcase docs generator (no TE, no python-ts)."""
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "docs" / "_ext"))
import showcase_gen as sg  # noqa: E402


TEST_PY = '''\
#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""One-line objective.

Detail paragraph.
"""
from pyte import test

with test.start() as t:
    # docs:begin hello-body
    t.step("Say hello")
    # docs:end
'''


def make_suite(root: Path) -> Path:
    """Lay out a minimal fake python-ts checkout; return its root."""
    ts = root / "python-ts" / "ts"
    pkg = ts / "usecases"
    pkg.mkdir(parents=True)
    (ts / "package.xml").write_text("<package/>")
    pkg.joinpath("package.xml").write_text(
        '<package><session><run><script name="hello"/></run>'
        "</session></package>")
    pkg.joinpath("hello.py").write_text(TEST_PY)
    return root / "python-ts"


def test_find_root_via_env(tmp_path, monkeypatch):
    suite = make_suite(tmp_path)
    monkeypatch.setenv(sg.ROOT_ENV, str(suite))
    assert sg.find_showcase_root(tmp_path / "elsewhere") == suite.resolve()


def test_find_root_missing_raises(tmp_path, monkeypatch):
    monkeypatch.delenv(sg.ROOT_ENV, raising=False)
    docs = tmp_path / "a" / "b" / "c" / "docs"
    docs.mkdir(parents=True)
    with pytest.raises(sg.ShowcaseError, match="python-ts checkout not found"):
        sg.find_showcase_root(docs)


def test_package_scripts_order(tmp_path):
    suite = make_suite(tmp_path)
    assert sg.package_scripts(suite / "ts" / "usecases") == ["hello"]


def test_test_parts_strips_header_docstring_and_markers(tmp_path):
    suite = make_suite(tmp_path)
    doc, code = sg.test_parts(suite / "ts" / "usecases" / "hello.py")
    assert doc.startswith("One-line objective.")
    assert "Detail paragraph." in doc
    assert '"""' not in code
    assert "SPDX" not in code
    assert "docs:begin" not in code
    assert code.startswith("from pyte import test")
    assert 't.step("Say hello")' in code


def test_extract_snippets_dedents(tmp_path):
    text = textwrap.dedent('''\
        with test.start() as t:
            # docs:begin body
            t.step("x")
            if True:
                pass
            # docs:end
    ''')
    snips = sg.extract_snippets(text, "origin.py")
    assert snips == {"body": 't.step("x")\nif True:\n    pass'}


@pytest.mark.parametrize("text,err", [
    ("# docs:begin a\n# docs:begin b\n", "nested"),
    ("# docs:end\n", "without begin"),
    ("# docs:begin a\n", "unterminated"),
    ("# docs:begin a\n# docs:end\n# docs:begin a\n# docs:end\n",
     "duplicate"),
])
def test_extract_snippets_errors(text, err):
    with pytest.raises(sg.ShowcaseError, match=err):
        sg.extract_snippets(text, "origin.py")


def test_generate_end_to_end(tmp_path, monkeypatch):
    suite = make_suite(tmp_path)
    monkeypatch.setenv(sg.ROOT_ENV, str(suite))
    docs = tmp_path / "docs"
    docs.mkdir()
    sg.generate(docs)

    page = (docs / "showcase" / "usecases.md").read_text()
    assert "## hello" in page
    assert "One-line objective." in page
    assert 't.step("Say hello")' in page

    index = (docs / "showcase" / "index.md").read_text()
    assert "usecases" in index

    snippet = (docs / "_snippets" / "hello-body.py").read_text()
    assert snippet == 't.step("Say hello")\n'


def test_generate_rejects_cross_file_duplicate(tmp_path, monkeypatch):
    suite = make_suite(tmp_path)
    other = suite / "ts" / "usecases" / "other.py"
    other.write_text('"""Doc."""\n# docs:begin hello-body\nx = 1\n# docs:end\n')
    monkeypatch.setenv(sg.ROOT_ENV, str(suite))
    docs = tmp_path / "docs"
    docs.mkdir()
    with pytest.raises(sg.ShowcaseError, match="hello-body"):
        sg.generate(docs)
