# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Generate docs from the python-ts showcase suite at Sphinx build time.

Two outputs, both derived from the same checkout:

- ``docs/showcase/`` — one MyST page per showcase package: each test's
  module docstring (its TE objective) followed by its source.
- ``docs/_snippets/`` — regions marked ``# docs:begin <name>`` /
  ``# docs:end`` in showcase tests, extracted for ``literalinclude``
  in the hand-written guides.

The python-ts checkout is REQUIRED: the build fails without it, so
documentation examples can never silently go stale.  Resolution order:
``$PYTE_SHOWCASE``, the enclosing python-ts (when building from
``python-ts/lib/pyte/docs``), then a ``python-ts`` sibling of the pyte
checkout.

Showcase test modules run code at import time — this module must only
ever parse them statically (ast), never import them.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT_ENV = "PYTE_SHOWCASE"
_BEGIN = re.compile(r"^\s*#\s*docs:begin\s+([\w-]+)\s*$")
_END = re.compile(r"^\s*#\s*docs:end\s*$")


class ShowcaseError(RuntimeError):
    """A showcase input the docs build cannot proceed without."""


def find_showcase_root(docs_dir: Path) -> Path:
    """Locate the python-ts checkout the docs are generated from."""
    env = os.environ.get(ROOT_ENV)
    if env:
        candidates = [Path(env)]
    else:
        candidates = [
            docs_dir.parents[2],                # python-ts/lib/pyte/docs
            docs_dir.parents[1] / "python-ts",  # sibling of pyte checkout
        ]
    for cand in candidates:
        if (cand / "ts" / "package.xml").is_file():
            return cand.resolve()
    raise ShowcaseError(
        "python-ts checkout not found (tried: "
        + ", ".join(str(c) for c in candidates)
        + f"); clone it next to pyte or point {ROOT_ENV} at its root")


def package_scripts(pkg_dir: Path) -> list[str]:
    """Test names of a package, in package.xml declaration order."""
    tree = ET.parse(pkg_dir / "package.xml")
    return [el.get("name") for el in tree.iter("script") if el.get("name")]


def test_parts(path: Path) -> tuple[str, str]:
    """Split a showcase test into (module docstring, code body).

    The body starts after the docstring, so the shebang/license header
    and the docstring (rendered separately as prose) are dropped, as
    are ``docs:begin``/``docs:end`` marker comments.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    doc = ast.get_docstring(tree, clean=True)
    if not doc:
        raise ShowcaseError(f"{path}: missing module docstring")
    lines = text.splitlines()[tree.body[0].end_lineno:]
    lines = [ln for ln in lines
             if not _BEGIN.match(ln) and not _END.match(ln)]
    return doc.strip(), "\n".join(lines).strip("\n")


def extract_snippets(text: str, origin: str) -> dict[str, str]:
    """Extract named, dedented docs:begin/docs:end regions."""
    snippets: dict[str, str] = {}
    name: str | None = None
    buf: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if m := _BEGIN.match(line):
            if name is not None:
                raise ShowcaseError(f"{origin}:{lineno}: nested docs:begin")
            name, buf = m.group(1), []
        elif _END.match(line):
            if name is None:
                raise ShowcaseError(
                    f"{origin}:{lineno}: docs:end without begin")
            if name in snippets:
                raise ShowcaseError(
                    f"{origin}: duplicate snippet {name!r}")
            snippets[name] = textwrap.dedent("\n".join(buf)).strip("\n")
            name = None
        elif name is not None:
            buf.append(line)
    if name is not None:
        raise ShowcaseError(f"{origin}: unterminated docs:begin {name!r}")
    return snippets


def _write_showcase(pkgs: list[Path], out: Path) -> None:
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for pkg in pkgs:
        parts = [f"# {pkg.name}", ""]
        for script in package_scripts(pkg):
            doc, code = test_parts(pkg / f"{script}.py")
            parts += [f"## {script}", "", doc, "",
                      "````python", code, "````", ""]
        (out / f"{pkg.name}.md").write_text("\n".join(parts),
                                            encoding="utf-8")
    index = [
        "# Showcase", "",
        "Real tests from the [python-ts](https://github.com/oktet-tech/"
        "python-ts) showcase suite.  Every page is generated at",
        "docs-build time from code the suite actually runs — these",
        "examples cannot go stale.", "",
        "```{toctree}", ":maxdepth: 1", "",
    ]
    index += [p.name for p in pkgs]
    index += ["```", ""]
    (out / "index.md").write_text("\n".join(index), encoding="utf-8")


def _write_snippets(ts_dir: Path, out: Path) -> None:
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    seen: dict[str, Path] = {}
    for path in sorted(ts_dir.rglob("*.py")):
        for name, code in extract_snippets(
                path.read_text(encoding="utf-8"), str(path)).items():
            if name in seen:
                raise ShowcaseError(
                    f"snippet {name!r} defined in both "
                    f"{seen[name]} and {path}")
            seen[name] = path
            (out / f"{name}.py").write_text(code + "\n", encoding="utf-8")


def generate(docs_dir: Path) -> None:
    """Regenerate docs/showcase/ and docs/_snippets/ from python-ts."""
    ts_dir = find_showcase_root(docs_dir) / "ts"
    pkgs = sorted(p for p in ts_dir.iterdir()
                  if p.is_dir() and (p / "package.xml").is_file())
    _write_showcase(pkgs, docs_dir / "showcase")
    _write_snippets(ts_dir, docs_dir / "_snippets")
