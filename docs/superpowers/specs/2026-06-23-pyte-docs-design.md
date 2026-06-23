# pyte README rewrite + Sphinx documentation

**Date:** 2026-06-23
**Status:** Approved design, pending implementation plan
**Repo:** oktet-tech/pyte

## Problem

`pyte`'s current `README.md` (582 lines) is a thorough *developer* guide —
architecture, per-module guides (`rpc`, `net`, `rcf`, `env`, `tester`,
`tools.fio`, `mi`), the cdef/facade C-shim extension pattern, and caveats — but
it is not a friendly entry point, and there is no generated documentation. We
want:

1. A **user-friendly README** that: says what pyte is, gives a quickstart,
   shows clear steps to **bootstrap a new test suite**, and explains **how to
   build the documentation**.
2. **Sphinx documentation** that includes the deep development details
   (cdef/facade pattern, architecture, per-module guides, caveats) plus an
   auto-generated API reference.

## Key enabling fact

No `pyte` module imports `pyte._shim` at module level (verified: the CLAUDE.md
hard rule "`from pyte._shim import …` ONLY inside functions" holds across
`src/pyte/**`). Therefore Sphinx autodoc can import the pure-Python source and
extract docstrings **without a built TE and without compiling the cffi shim**.
The docs build is fully TE-free.

## Decisions

| # | Decision |
|---|----------|
| 1 | Doc source format: **MyST Markdown** (`myst-parser`). Content is already Markdown; one syntax to maintain. |
| 2 | API reference: **`autodoc` + `autosummary`** generated from docstrings (not hand-curated). |
| 3 | Narrative dev content (architecture, extending-pyte, caveats, per-module guides): **hand-written MyST guide pages**, migrated from today's README. |
| 4 | Bootstrap-a-suite: a **documented tutorial page** (no scaffolding tool). |
| 5 | Build/hosting: **local build only** now (TE-free ephemeral env); CI/Pages is an additive follow-up, out of scope. |
| 6 | Theme: **furo**. |

## Documentation toolchain

Sphinx with `myst-parser` and the `furo` theme. Extensions:
`myst_parser`, `sphinx.ext.autodoc`, `sphinx.ext.autosummary`,
`sphinx.ext.napoleon`, `sphinx.ext.viewcode`, `sphinx.ext.intersphinx`.

`docs/conf.py`:
- `sys.path.insert(0, os.path.abspath("../src"))` so autodoc imports the
  pure-Python source directly (no installed/built package needed).
- `autodoc_mock_imports = ["pyte._shim"]` so any import path that reaches the
  cffi shim is mocked — the build never needs `TE_INSTALL` or a compile.
- `autosummary_generate = True`.
- `exclude_patterns` includes `superpowers/**` so Sphinx does not try to parse
  these process/spec documents that live under `docs/`.

## Repo / docs layout

```
docs/
  conf.py
  index.md                      # landing / root toctree
  tutorials/
    bootstrap-a-suite.md        # NEW step-by-step new-suite guide
  guides/                       # migrated from today's README
    architecture.md
    rpc.md  net.md  rcf.md  env.md  tester.md  tools-fio.md  mi.md
    extending-pyte.md           # the cdef/facade C-shim pattern
    caveats.md
  api/
    index.md                    # autosummary :recursive: over pyte.*
  requirements.txt              # sphinx, myst-parser, furo, scapy
  superpowers/                  # specs/plans (excluded from Sphinx build)
README.md                       # rewritten friendly landing
scripts/build-docs.sh           # thin convenience wrapper
```

The existing README is **migrated, not discarded**: its architecture,
per-module, extension, and caveats sections become the `guides/` pages (near
copy-paste — already Markdown). Each per-module README section becomes one
`guides/<module>.md` page.

## The new README (user-friendly landing)

Short and task-oriented:
- What pyte is (2–3 sentences).
- **Quickstart**: clone a suite with `--recurse-submodules` (or
  `git submodule update --init lib/pyte`), run the showcase suite.
- **Bootstrap a suite**: brief inline steps + link to the full tutorial.
- **Build the docs**: the one command (below).
- Link to the generated docs for everything deep. Deep dev content lives in the
  docs, not the README.

## Bootstrap-a-suite tutorial

A documented walk-through using `python-ts` as the reference, with
copy-pasteable snippets:
- Create the suite repo; add pyte as the `lib/pyte` git submodule.
- The `pyproject.toml` uv-workspace stanza (`members = ["lib/pyte"]`,
  `[tool.uv.sources] pyte = {workspace = true}`).
- `scripts/run.sh` including the `git submodule update --init lib/pyte` step
  and passing `TE_BASE`/`TE_INSTALL` into the `uv sync` that builds the shim.
- A minimal `conf/` rig (env/run pair).
- A first `ts/<pkg>/<test>.py` + `package.xml` entry.

## API reference

`autosummary` with `:recursive:` over the `pyte` packages generates the
per-symbol reference from current docstrings. Undocumented public symbols
render bare, which usefully flags gaps.

**Scope boundary:** this work wires up generation and migrates narrative.
*Completing* every docstring (e.g. `rpc/__init__.py` has none) is a separate
incremental effort, not a blocker here.

## Build command & dependencies

TE-free, ephemeral env (mirrors the project's test-run pattern), documented in
both the README and the docs:

```bash
uv run --no-project --with-requirements docs/requirements.txt \
  sphinx-build -b html docs docs/_build/html
```

`scripts/build-docs.sh` wraps this exact command for convenience.
`docs/requirements.txt` pins `sphinx`, `myst-parser`, `furo`, and `scapy`
(needed because `pyte.tad` imports scapy at module level; everything else
pyte imports at module level is stdlib).

## Out of scope (YAGNI)

- CI / GitHub Pages / Read the Docs publishing (additive follow-up).
- A scaffolding/cookiecutter generator for new suites.
- Completing/auditing every docstring across the codebase.
