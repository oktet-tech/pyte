# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the scripts/te_py_tests_info objective generator."""
import importlib.machinery
import importlib.util
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_FALLBACK = Path(__file__).resolve().parents[1] / "scripts" / "te_py_tests_info"


def _resolve_gen_path():
    env = os.environ.get("TE_PY_TESTS_INFO")
    if env:
        return Path(env)
    if _FALLBACK.exists():
        return _FALLBACK
    return None


_GEN_PATH = _resolve_gen_path()


def _load_generator():
    if _GEN_PATH is None:
        pytest.skip("te_py_tests_info not available in this checkout",
                    allow_module_level=True)
    loader = importlib.machinery.SourceFileLoader("te_py_tests_info",
                                                  str(_GEN_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


gen = _load_generator()


def _write(d, name, body):
    (d / (name + ".py")).write_text(body, encoding="utf-8")


def test_oneline_docstring(tmp_path):
    _write(tmp_path, "t", '"""Check the thing."""\nx = 1\n')
    assert gen.read_objective(str(tmp_path / "t.py")) == "Check the thing."


def test_multiline_markdown_preserved(tmp_path):
    _write(tmp_path, "t",
           '"""Summary line.\n\nDetailed paragraph with context.\n"""\n')
    assert gen.read_objective(str(tmp_path / "t.py")) == \
        "Summary line.\n\nDetailed paragraph with context."


def test_no_docstring_returns_none(tmp_path):
    _write(tmp_path, "t", "x = 1\n")
    assert gen.read_objective(str(tmp_path / "t.py")) is None


def test_xml_escape_order():
    assert gen.xml_escape("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_render_document_shape():
    assert gen.render_document([("foo", "Bar & baz")]) == (
        '<?xml version="1.0"?>\n'
        "<tests-info>\n"
        '  <test name="foo">\n'
        "    <objective>Bar &amp; baz</objective>\n"
        "  </test>\n"
        "</tests-info>\n"
    )


def test_main_success(tmp_path, capsys):
    _write(tmp_path, "good", '"""Does good."""\n')
    rc = gen.main([str(tmp_path), "good"])
    assert rc == 0
    assert "<objective>Does good.</objective>" in capsys.readouterr().out


def test_main_missing_docstring_fails(tmp_path, capsys):
    _write(tmp_path, "good", '"""Does good."""\n')
    _write(tmp_path, "bad", "x = 1\n")
    rc = gen.main([str(tmp_path), "good", "bad"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "bad.py" in err and "missing module docstring" in err


def test_output_parses_as_single_text_node(tmp_path):
    _write(tmp_path, "t", '"""Has < and & chars."""\n')
    doc = gen.render_document([("t", gen.read_objective(str(tmp_path / "t.py")))])
    root = ET.fromstring(doc)
    assert root.find("test/objective").text == "Has < and & chars."
