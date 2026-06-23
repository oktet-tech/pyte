# Bootstrap a test suite

This walks through creating a new TE Python test suite that consumes pyte,
following the layout of the reference suite
[python-ts](https://github.com/oktet-tech/python-ts). A suite owns the
tests, the rig configuration, and the run script; pyte is pulled in as a
git submodule and built against your local TE.

## Prerequisites

- A TE checkout next to your suite (the suite's `scripts/guess.sh`
  auto-detects a sibling `te/`), built at least once.
- [uv](https://docs.astral.sh/uv/) installed.

## 1. Create the suite repo and add pyte

```bash
mkdir my-ts && cd my-ts && git init
git submodule add https://github.com/oktet-tech/pyte.git lib/pyte
```

## 2. Declare the uv workspace

Create `pyproject.toml` so uv builds `lib/pyte` (the cffi shim) as a
workspace member:

```toml
[project]
name = "my-ts"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = ["pyte"]

[tool.uv]
package = false

[tool.uv.workspace]
members = ["lib/pyte"]

[tool.uv.sources]
pyte = { workspace = true }

[dependency-groups]
dev = ["pytest>=8", "ruff>=0.4"]
```

## 3. Add a run script

The run script must check out the submodule, build TE, build the pyte shim
against that TE, and invoke the dispatcher. The reference implementation is
intricate (TE detection, metadata, rig handling), so copy it from python-ts
and adjust the suite name:

```bash
cp ../python-ts/scripts/run.sh  scripts/run.sh
cp ../python-ts/scripts/guess.sh scripts/guess.sh
```

The two lines that make pyte work, already present in python-ts's
`run.sh`, are the submodule checkout and passing the TE location into the
build:

```bash
git -C "${TE_TS_TOPDIR}" submodule update --init lib/pyte || exit 1
# ...
( cd "${TE_TS_TOPDIR}" \
  && TE_INSTALL="${TE_INSTALL}" TE_BASE="${TE_BASE}" \
     uv sync --reinstall-package pyte ) || exit 1
```

`TE_BASE` lets the pyte shim build check your TE is new enough (see
`[tool.pyte] min_te_commit` in the pyte repo); `--reinstall-package pyte`
forces the shim to relink against the current TE.

## 4. Add a rig

A rig is an `env`/`run` pair under `conf/`. The simplest is a non-root
local agent. Copy python-ts's `localhost` rig as a starting point:

```bash
mkdir -p conf
cp -r ../python-ts/conf/* conf/
```

Adjust `conf/cs.conf` and the `env/localhost` / `run/localhost` pair to
your topology as needed.

## 5. Write the first test

A test is a plain Python script run by TE's Tester. Create
`ts/sanity/hello.py`:

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Your Name
"""First sanity test: start a test and pass."""
from pyte import test

with test.start() as t:
    # Test body goes here; `t` exposes logging and the TE APIs.
    # An empty body passes.
    pass
```

Register it in `ts/sanity/package.xml` (Tester needs a non-empty
`<author>` and an objective):

```xml
<?xml version="1.0"?>
<package version="1.0">
  <description>Sanity package</description>
  <author mailto="you@example.com"/>
  <session>
    <run>
      <script name="hello">
        <objective>First sanity test</objective>
      </script>
    </run>
  </session>
</package>
```

Install it from `ts/sanity/meson.build` and list the package in
`ts/meson.build` (copy the pattern from any python-ts package).

## 6. Run it

```bash
./scripts/run.sh --cfg=localhost
```

This checks out `lib/pyte`, builds TE and the pyte shim, then runs your
test. Results are in the dispatcher output and `log.txt`; add
`--log-html=html` for browsable logs.

## Next steps

- Per-module APIs (RPC, Configurator, TAD, env, fio, MI): see the
  [guides](../guides/architecture).
- Adding C-level wrappers: [Extending pyte](../guides/extending-pyte).
