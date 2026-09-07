# Docs Up-to-date by Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pyte's documentation examples impossible to silently rot: every example is either generated from, included from, or executed as real code.

**Architecture:** A doc-build-time generator (`docs/_ext/showcase_gen.py` in the pyte repo) reads the python-ts showcase suite and produces (a) a generated "Showcase" doc section — one page per `ts/` package, each test's module docstring + source — and (b) snippet files extracted from `# docs:begin <name>` / `# docs:end` marker comments in real tests, which the hand-written guides pull in via `literalinclude`. The python-ts checkout is **required** to build docs; missing checkout, broken markers, or missing snippets fail the build (`sphinx-build -W`). Testbed-free docstring examples become doctests run by pytest.

**Tech Stack:** Sphinx 7 + MyST (existing), Python stdlib only for the generator (`ast`, `xml.etree`, `re`, `textwrap`), pytest for generator unit tests and doctests.

## Global Constraints

- Two separate git repos are touched: `pyte/` (standalone checkout at `/home/kostik/prj/te/pyte`) and `python-ts/` (`/home/kostik/prj/te/python-ts`). **Never mix changes to both repos in one commit.** Run git with `-C <repo>`.
- New files: `# SPDX-License-Identifier: Apache-2.0` on line 1 (line 2 after a shebang) + `# Copyright (C) 2026 Konstantin Ushakov`.
- Commit summary: `component: lowercase imperative`, ≤ 60 chars. pyte components seen in history: `docs`, `tests`, `tools`. python-ts components: `ts/<pkg>`, `docs`. Body wraps at 72, explains why. Commit with `git commit -s`.
- Python style: 4-space indent, no tabs, type annotations as in surrounding code (`from __future__ import annotations` at module top).
- The generator must never **import** showcase test modules (they run code at import time) — static `ast` parsing only, same rule as `python-ts/scripts/te_py_tests_info`.
- Docs build command is always `./scripts/build-docs.sh` (uv ephemeral env; no TE needed). Doc deps live in `docs/requirements.txt` — no new deps are needed.
- Suite verification runs use `./scripts/run.sh --cfg=localhost` from `python-ts/` (builds TE on first run — can take minutes).

---

### Task 1: Showcase generator module (pyte repo)

**Files:**
- Create: `pyte/docs/_ext/showcase_gen.py`
- Test: `pyte/tests/test_showcase_gen.py`

**Interfaces:**
- Produces: `showcase_gen.generate(docs_dir: Path) -> None` — the only entry point conf.py calls (Task 2). Also public for tests: `find_showcase_root(docs_dir) -> Path`, `package_scripts(pkg_dir) -> list[str]`, `test_parts(path) -> tuple[str, str]`, `extract_snippets(text, origin) -> dict[str, str]`, exception class `ShowcaseError(RuntimeError)`, env var name `ROOT_ENV = "PYTE_SHOWCASE"`.
- Output contract (consumed by Tasks 2–4): `docs/showcase/<pkg>.md` + `docs/showcase/index.md` (MyST), and `docs/_snippets/<name>.py` — one file per marker name, referenced from guides as `` {literalinclude} /_snippets/<name>.py ``.

- [ ] **Step 1: Write the failing tests**

Create `pyte/tests/test_showcase_gen.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/kostik/prj/te/pyte && uv run pytest tests/test_showcase_gen.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'showcase_gen'`

- [ ] **Step 3: Write the generator**

Create `pyte/docs/_ext/showcase_gen.py`:

```python
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
```

Path sanity check for `find_showcase_root`: with docs at
`python-ts/lib/pyte/docs`, `parents[2]` is the python-ts root; with the
standalone checkout at `prj/te/pyte/docs`, `parents[1]/python-ts` is the
sibling checkout. Both are covered by the unit tests.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/kostik/prj/te/pyte && uv run pytest tests/test_showcase_gen.py -v`
Expected: all 9 tests PASS. If `test_find_root_missing_raises` fails with `IndexError`, the parents indexing is wrong — fix per the note above.

- [ ] **Step 5: Commit (pyte repo)**

```bash
git -C /home/kostik/prj/te/pyte add docs/_ext/showcase_gen.py tests/test_showcase_gen.py
git -C /home/kostik/prj/te/pyte commit -s -m "docs: add showcase generator for python-ts examples"
```

Body: explain that examples will be generated from the executed suite so they cannot rot; markers contract; python-ts checkout becomes a docs-build prerequisite.

---

### Task 2: Wire the generator into the Sphinx build, make warnings fatal (pyte repo)

**Files:**
- Modify: `pyte/docs/conf.py` (top of file)
- Modify: `pyte/docs/index.md` (add Showcase toctree)
- Modify: `pyte/scripts/build-docs.sh` (add `-W --keep-going`)
- Modify: `pyte/.gitignore` (generated outputs)
- Modify: `pyte/README.md` (build prerequisite note)

**Interfaces:**
- Consumes: `showcase_gen.generate(docs_dir)` from Task 1.
- Produces: a docs build that hard-fails when python-ts is missing, markers are broken, or any Sphinx warning occurs (missing literalinclude targets included) — relied on by Tasks 3–4.

- [ ] **Step 1: Call the generator from conf.py**

At the top of `pyte/docs/conf.py`, after any existing imports and before the `extensions = [...]` block, add:

```python
import sys
from pathlib import Path

_DOCS = Path(__file__).resolve().parent
sys.path.insert(0, str(_DOCS / "_ext"))
import showcase_gen

showcase_gen.generate(_DOCS)
```

(Preserve whatever imports/`sys.path` manipulation conf.py already does for autodoc — add to it, don't replace it.)

- [ ] **Step 2: Add the Showcase section to the toctree**

In `pyte/docs/index.md`, insert between the Guides and Reference toctrees:

```markdown
````{toctree}
:maxdepth: 1
:caption: Showcase

showcase/index
````
```

- [ ] **Step 3: Make warnings fatal in build-docs.sh**

In `pyte/scripts/build-docs.sh` change the sphinx-build line to:

```bash
uv run --no-project --with-requirements docs/requirements.txt \
    sphinx-build -W --keep-going -b html docs docs/_build/html "$@"
```

- [ ] **Step 4: Ignore generated outputs**

Append to `pyte/.gitignore`:

```
docs/showcase/
docs/_snippets/
```

- [ ] **Step 5: Build and fix any pre-existing warnings**

Run: `cd /home/kostik/prj/te/pyte && ./scripts/build-docs.sh`
Expected: build succeeds and `docs/_build/html/showcase/index.html` exists with one page per `ts/` package (usecases, rpc, cfg, job, tad, remote, env, tester, net, rcf, dynamic, fio, iperf3, netperf, nptcp, ping, sfnt_pingpong, stress, trex, wrk).

`-W` may surface warnings the old build tolerated. Fix each at its source (typically a bad cross-reference or malformed docstring markup); do not blanket-suppress with `suppress_warnings`. If a warning comes from a generated showcase page (e.g. a docstring containing text MyST misparses), fix the rendering in `_write_showcase` (the docstring is already emitted as plain prose; wrapping it in a blank-line-delimited paragraph is usually enough).

- [ ] **Step 6: Verify the failure modes fail**

```bash
cd /home/kostik/prj/te/pyte
PYTE_SHOWCASE=/nonexistent ./scripts/build-docs.sh
```
Expected: build FAILS with `ShowcaseError: python-ts checkout not found`.

- [ ] **Step 7: Document the prerequisite**

In `pyte/README.md`, in/near the docs-build section, add:

```markdown
Building the docs requires a `python-ts` checkout (the showcase suite the
examples are generated from): either a sibling directory of this repo, or
point `PYTE_SHOWCASE` at its root. The build fails without it — by design:
every example in these docs is real, executed suite code.
```

- [ ] **Step 8: Commit (pyte repo)**

```bash
git -C /home/kostik/prj/te/pyte add docs/conf.py docs/index.md scripts/build-docs.sh .gitignore README.md
git -C /home/kostik/prj/te/pyte commit -s -m "docs: generate showcase section, make warnings fatal"
```

---

### Task 3: Convert guides/rpc.md to literalinclude from real tests (both repos)

**Files:**
- Modify: `python-ts/ts/rpc/socket_echo.py` (add markers)
- Modify: `python-ts/ts/rpc/iomux.py` (add markers)
- Modify: `python-ts/ts/rpc/msg_io.py` (add markers)
- Modify: `python-ts/CLAUDE.md` (marker discipline note)
- Modify: `pyte/docs/guides/rpc.md` (replace hand-written blocks)

**Interfaces:**
- Consumes: snippet extraction from Task 1; fatal-warning build from Task 2.
- Produces: snippet names `rpc-socket-echo`, `rpc-iomux`, `rpc-msg-io`; the marker + literalinclude pattern that Task 4 repeats for the other guides.

- [ ] **Step 1: Add markers to the three showcase tests**

Markers are plain comments at the enclosing block's indentation; they must not change test behaviour.

`python-ts/ts/rpc/socket_echo.py` — wrap the stream branch. Insert `# docs:begin rpc-socket-echo` on its own line immediately after `if sock_type == "stream":` (indented to match the branch body, i.e. 8 spaces), and `# docs:end` after the branch's last statement (the final echo check `t.fail(...)`), before the dgram branch:

```python
    if sock_type == "stream":
        # docs:begin rpc-socket-echo
        t.step("Open a listening TCP socket on an ephemeral port")
        with pco_srv.socket(Family.INET, SockType.STREAM) as lsock:
            ...
                    if echo != PAYLOAD:
                        t.fail(f"client got {echo!r}, not {PAYLOAD!r}")
        # docs:end
```

`python-ts/ts/rpc/iomux.py` — wrap lines 12–32 (the `with RpcSocket.open(...)` context through `a.recvfrom(16)`):

```python
    pco = t.rpc_server("pco")
    # docs:begin rpc-iomux
    with RpcSocket.open(pco, type=SockType.DGRAM) as a, \
            ...
        a.recvfrom(16)
    # docs:end
```

Note the file continues after line 32 inside the same `with` block ("Both readable" step) — place `# docs:end` after `a.recvfrom(16)` at the `with`-body indentation (4 spaces deeper than `with`); the remaining steps stay outside the snippet.

`python-ts/ts/rpc/msg_io.py` — wrap lines 24–44 (both `t.step` blocks: scatter send and ancillary data):

```python
        dst = rx.getsockname()

        # docs:begin rpc-msg-io
        t.step("Scatter send: three iovecs arrive as one datagram")
        ...
        if level != IPPROTO_IP or ctype != IP_PKTINFO:
            t.fail(f"unexpected cmsg {level}/{ctype}")
        # docs:end
```

- [ ] **Step 2: Verify snippets extract and the suite still passes**

```bash
cd /home/kostik/prj/te/pyte && ./scripts/build-docs.sh
head -5 docs/_snippets/rpc-iomux.py docs/_snippets/rpc-msg-io.py docs/_snippets/rpc-socket-echo.py
```
Expected: build passes; three snippet files exist with dedented code, no marker lines.

```bash
cd /home/kostik/prj/te/python-ts && ./scripts/run.sh --cfg=localhost --tester-run=python-ts/rpc
```
Expected: all rpc package iterations PASS (markers are comments; this run proves nothing broke and, more importantly, that everything the guide now shows was just executed).

- [ ] **Step 3: Rewrite guides/rpc.md around the snippets**

Replace the three hand-written ```` ```python ```` blocks in `pyte/docs/guides/rpc.md`:

1. The intro block (lines 6–13, `pco.socket`/bind/getsockname) becomes:

````markdown
`pyte.rpc.RpcServer` creates and owns remote socket file descriptors
through `RpcSocket`.  A complete TCP echo between two RPC servers
(from the showcase test `ts/rpc/socket_echo.py`):

```{literalinclude} /_snippets/rpc-socket-echo.py
:language: python
```
````

2. The IoMux block (lines 38–49) becomes:

````markdown
```{literalinclude} /_snippets/rpc-iomux.py
:language: python
```
````

Adjust the surrounding prose to match the real code: the snippet selects the
kind via `Kind[name.upper()]` from a test parameter and uses
`RpcSocket.open(pco, type=SockType.DGRAM)` — mention that `pco.iomux(kind)`
accepts any `Kind` and that `mux.wait(0.5) == []` is the timeout case shown
live in the snippet (keep the existing "timeout — not an error" sentence).

3. The sendmsg/recvmsg block (lines 63–77) becomes:

````markdown
```{literalinclude} /_snippets/rpc-msg-io.py
:language: python
```
````

Keep all prose notes (ancillary-data conversion, `RPC_AWAIT_ERROR`, longjmp
guard) — prose stays hand-written; only code is included. Delete any prose
that describes code no longer shown (e.g. the `print(rep.rtt.avg)`-style
fragments) rather than leaving it dangling.

- [ ] **Step 4: Build docs and inspect the rendered guide**

Run: `cd /home/kostik/prj/te/pyte && ./scripts/build-docs.sh`
Expected: PASS (a typo'd snippet path would fail the build — that's the point).
Open `docs/_build/html/guides/rpc.html` and check the three included blocks render with highlighting and sane indentation.

- [ ] **Step 5: Document the marker discipline in python-ts**

Add to `python-ts/CLAUDE.md`, in the "Hard rules" section:

```markdown
- **Docs markers**: `# docs:begin <name>` / `# docs:end` comments in
  `ts/` tests mark regions the pyte docs literalinclude as guide
  examples (extracted by `pyte/docs/_ext/showcase_gen.py` at docs-build
  time). Snippet names are global across the suite. Renaming/removing
  a marked region breaks the pyte docs build (`-W`) — grep pyte's
  `docs/guides/` for the snippet name before touching one. Every test's
  module docstring + source also appears verbatim in the docs Showcase
  section: keep both didactic.
```

- [ ] **Step 6: Commit (one commit per repo)**

```bash
git -C /home/kostik/prj/te/python-ts add ts/rpc/socket_echo.py ts/rpc/iomux.py ts/rpc/msg_io.py CLAUDE.md
git -C /home/kostik/prj/te/python-ts commit -s -m "ts/rpc: mark doc snippet regions for pyte guides"
git -C /home/kostik/prj/te/pyte add docs/guides/rpc.md
git -C /home/kostik/prj/te/pyte commit -s -m "docs: include rpc guide examples from showcase tests"
```

---

### Task 4: Sweep the remaining guides (both repos)

**Files:**
- Modify: `pyte/docs/guides/net.md`, `env.md`, `rcf.md`, `mi.md`, `tools-fio.md`
- Modify: the covering tests under `python-ts/ts/net/`, `ts/env/`, `ts/rcf/`, `ts/fio/` (markers)
- Leave as-is: `guides/architecture.md`, `guides/extending-pyte.md`, `guides/caveats.md`, `tutorials/bootstrap-a-suite.md` (prose / shim-dev / suite-scaffolding content with no showcase counterpart — hand-written is correct for these)

**Interfaces:**
- Consumes: the exact pattern established in Task 3 (marker naming `<guide>-<topic>`, `literalinclude /_snippets/<name>.py`, prose adjusted to real code).
- Produces: guides whose every runnable example is suite-executed code.

- [ ] **Step 1: Map each guide's code blocks to covering tests**

For each guide, list the package's tests (`ls python-ts/ts/<pkg>/*.py`, read them) and pick the test region that demonstrates what the hand-written block shows:

| Guide | Draw from | Snippet name(s) |
|---|---|---|
| `net.md` | `ts/net/net_info.py` (interface/address queries), `ts/net/net_setup.py` (topology; ROOT-only — fine, snippets need not run on every rig, only on the rig that runs the test) | `net-info`, `net-setup` |
| `env.md` | `ts/env/basic.py` (binding), `ts/env/addrs.py` (address kinds), `ts/env/peer2peer.py` (two-agent env) | `env-basic`, `env-addrs`, `env-peer2peer` |
| `rcf.md` | `ts/rcf/agent_restart.py`, `ts/rcf/dynamic_agent.py`, `ts/rcf/file_transfer.py` | `rcf-restart`, `rcf-dynamic-agent`, `rcf-file-transfer` |
| `mi.md` | `ts/fio/randrw.py` if it calls `pyte.mi`/`Fio.mi_report()` directly; otherwise apply the decision rule below | `mi-report` |
| `tools-fio.md` | `ts/fio/randrw.py` | `fio-run` |

Pick per guide only the snippets its existing code blocks actually need —
the table is the candidate pool, not a quota; a guide with one code block
gets one snippet.

Decision rule when no test covers a block: if the block shows a real, runnable pyte usage, prefer writing a small showcase test for it (follow python-ts CLAUDE.md's new-test checklist: docstring, `package.xml` entry, `meson.build`, TRC entry). If that is out of proportion (e.g. the block is 3 illustrative lines), keep it hand-written and record the gap in the pyte commit body as `showcase gap: <guide> <topic>`. Do not invent snippet markers pointing at code that does not demonstrate the documented behaviour.

- [ ] **Step 2: Apply markers + literalinclude, one guide at a time**

For each guide, repeat Task 3's steps 1–4 (markers → build → rewrite → build). Keep marker insertions comment-only; never reorder test code to make a prettier snippet — if the snippet reads badly, improve the test itself (it's showcase code; didactic quality is a feature) and re-run that package.

- [ ] **Step 3: Run every touched showcase package**

```bash
cd /home/kostik/prj/te/python-ts
./scripts/run.sh --cfg=localhost --tester-run=python-ts/net
./scripts/run.sh --cfg=localhost --tester-run=python-ts/env
./scripts/run.sh --cfg=localhost --tester-run=python-ts/rcf
./scripts/run.sh --cfg=localhost --tester-run=python-ts/fio
```
Expected: PASS (fio tests may be Not Run on rigs without fio — that is the documented `!FIO` behaviour, not a failure).

- [ ] **Step 4: Full docs build**

Run: `cd /home/kostik/prj/te/pyte && ./scripts/build-docs.sh`
Expected: PASS with all guides converted.

- [ ] **Step 5: Commit (one commit per repo)**

```bash
git -C /home/kostik/prj/te/python-ts add ts/net ts/env ts/rcf ts/fio
git -C /home/kostik/prj/te/python-ts commit -s -m "ts: mark doc snippet regions across showcase packages"
git -C /home/kostik/prj/te/pyte add docs/guides
git -C /home/kostik/prj/te/pyte commit -s -m "docs: include guide examples from showcase tests"
```

List any `showcase gap:` items in the pyte commit body.

---

### Task 5: Doctests for testbed-free docstring examples (pyte repo)

**Files:**
- Modify: `pyte/src/pyte/tools/_units.py:53-59` (Examples block)
- Modify: `pyte/Taskfile.yml` (add `test` task)

**Interfaces:**
- Consumes: nothing from earlier tasks (independent; ordered last only because it's the smallest).
- Produces: `task test` — the one command that runs unit tests + doctests; docstring examples in `_units.py` that pytest executes.

Scope note: `_units.parse_unit` is the only `Example` block in `src/pyte/` that runs without a testbed (the others — `tools/ping.py`, `mi.py`, etc. — need a live agent; their truth now comes from the Showcase section, not from duplicated runnable examples). Do not convert rig-dependent examples to doctests.

- [ ] **Step 1: Convert the Examples block to doctest form**

In `pyte/src/pyte/tools/_units.py`, replace:

```python
    Examples::

        parse_unit("456.78us", TIME_US)  -> 456.78
        parse_unit("2.50ms",   TIME_US)  -> 2500.0
        parse_unit("12.34k",   METRIC)   -> 12340.0
        parse_unit("3.50M",    BINARY)   -> 3670016.0
        parse_unit("89.00%",   TIME_US)  -> 89.0
```

with:

```python
    Examples:
        >>> parse_unit("456.78us", TIME_US)
        456.78
        >>> parse_unit("2.50ms", TIME_US)
        2500.0
        >>> parse_unit("12.34k", METRIC)
        12340.0
        >>> parse_unit("3.50M", BINARY)
        3670016.0
        >>> parse_unit("89.00%", TIME_US)
        89.0
```

- [ ] **Step 2: Run the doctests, verify they pass**

Run: `cd /home/kostik/prj/te/pyte && uv run pytest --doctest-modules src/pyte/tools/_units.py -v`
Expected: 1 doctest item, PASS. If an expected value mismatches, the old prose example was wrong — fix the expected output to the real value (that mismatch is exactly the rot this plan exists to catch) and note it in the commit body.

- [ ] **Step 3: Add the test task to Taskfile.yml**

Append to `pyte/Taskfile.yml` `tasks:`:

```yaml
  test:
    desc: Run unit tests and docstring doctests (no TE needed)
    cmds:
      - uv run pytest tests --doctest-modules src/pyte/tools/_units.py
```

- [ ] **Step 4: Run the combined task**

Run: `cd /home/kostik/prj/te/pyte && task test`
Expected: all unit tests (including Task 1's `test_showcase_gen.py`) + the doctest PASS.

- [ ] **Step 5: Rebuild docs, check rendering**

Run: `cd /home/kostik/prj/te/pyte && ./scripts/build-docs.sh`
Expected: PASS; `docs/_build/html/api/generated/pyte.tools.html` (or the `_units` page if separately generated) renders the examples as a doctest block.

- [ ] **Step 6: Commit (pyte repo)**

```bash
git -C /home/kostik/prj/te/pyte add src/pyte/tools/_units.py Taskfile.yml
git -C /home/kostik/prj/te/pyte commit -s -m "tools: make parse_unit examples executable doctests"
```

---

## Verification (end-to-end)

1. `cd pyte && task test` — generator unit tests + doctests pass.
2. `cd pyte && ./scripts/build-docs.sh` — full build under `-W`; Showcase section present, guides include real snippets.
3. Negative: `PYTE_SHOWCASE=/nonexistent ./scripts/build-docs.sh` fails; temporarily renaming a snippet marker in `ts/rpc/iomux.py` makes the build fail with a missing-include error (revert after checking).
4. `cd python-ts && ./scripts/run.sh --cfg=localhost` — full showcase suite passes, proving every included example executed.
5. Serve and eyeball: `cd pyte && task serve`, check `/showcase/` pages and `/guides/rpc.html`.
