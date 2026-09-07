# Wave 4: Packaging, Typing and Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an sdist rebuildable, make the type checker see the types pyte already computes, and make the three stale guide claims true.

**Architecture:** Three independent strands, deliberately ordered. Packaging finishes what wave 0 started (the wheel is fixed; the sdist still cannot rebuild the shim). Typing ships enforcement *before* generics — with no mypy config, no `py.typed` and no type tests today, generics added first would have nothing holding them in place, and a `py.typed` marker shipped before the descriptors are typed would make consumers' checkers trust `Any`. Documentation corrects claims the code already contradicts.

**Tech Stack:** Python 3.11+, setuptools + cffi, mypy, Sphinx with `-W`.

**Spec:** `/home/kostik/prj/te/pyte-api-fixes-plan-2026-09-07.md` (wave 4 section). Evidence: `/home/kostik/prj/te/pyte-api-fixes-review-2026-09-07.md`.

## Global Constraints

- Repo `/home/kostik/prj/te/pyte`, branch `trexb`. Test with `.venv/bin/python -m pytest tests/ -q`; never `uv run pytest`.
- Lint with `ruff check src tests setup.py`.
- Waves 0-3 landed first.
- Style: 4-space indent, wrap at 79 columns. `git commit -s`, summary at most 60 chars, no AI attribution trailers.
- **Docs build with `-W` (warnings fatal)** via `./scripts/build-docs.sh`, and it requires the python-ts checkout for the showcase snippets. Build docs from scratch after any docs change.
- Keep the existing minimum-TE check exactly as it is: `[tool.pyte] min_te_commit` in `pyproject.toml` plus `te_compat.check_te_compat()`, called from `build_shim.py:23`. It is a build-time floor and this wave does not change it.
- Do NOT add `build_info()`. te-dist already records `pyte.commit`, `pyte.version` and `te.commit` as image labels (`te-dist/containerfiles/Containerfile.base:92-95`); `__version__` covers the rest.

---

### Task 1: Make an sdist rebuildable

**Files:**
- Create: `MANIFEST.in`
- Modify: `src/pyte/__init__.py` (add `__version__`)
- Test: `tests/test_packaging.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `pyte.__version__: str`.

**Background:** wave 0 fixed the wheel. The sdist is still unbuildable: with no `MANIFEST.in`, setuptools ships `setup.py`, `pyproject.toml`, `README*` and the `.py` files implied by `packages` — and nothing else. Everything the build actually reads is missing:

| Missing file | Read by |
|---|---|
| `build_shim.py` | the `cffi_modules` hook, via `execfile` |
| `te_compat.py` | imported by `build_shim.py:20` |
| `shim/pyte_shim_cdef.h` | `ffibuilder.cdef()` at `build_shim.py:63` |
| `shim/pyte_shim.h`, `shim/pyte_trc.h` | `#include` via `include_dirs` |
| `shim/pyte_shim.c`, `shim/pyte_trc.c` | `set_source(sources=...)` |
| `tests/conftest.py`, `tests/data/` | the test suite, if it is to run from an sdist |

The `.c` files are only *sometimes* pulled in via `ext_modules`, and with absolute paths that an sdist cannot place; the headers never are. So `pip install pyte.tar.gz` cannot rebuild the shim.

There is also no `__version__` anywhere in `src/`; the only source of truth is `pyproject.toml`, read at docs-build time by `docs/conf.py:16-18`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py` (which reads files rather than importing setuptools, so it runs offline):

```python
MANIFEST = ROOT / "MANIFEST.in"

#: Everything setup.py / build_shim.py reads at build time that
#: setuptools would NOT put in an sdist by default.
_BUILD_INPUTS = (
    "build_shim.py",
    "te_compat.py",
    "shim/pyte_shim.c",
    "shim/pyte_shim.h",
    "shim/pyte_shim_cdef.h",
    "shim/pyte_trc.c",
    "shim/pyte_trc.h",
)


def test_manifest_exists():
    assert MANIFEST.exists(), (
        "no MANIFEST.in: an sdist ships only the .py files and cannot "
        "rebuild the shim")


def test_every_build_input_is_declared():
    text = MANIFEST.read_text()
    for path in _BUILD_INPUTS:
        stem = path.split("/")[-1]
        assert path in text or stem in text or "shim" in text, (
            f"{path} is read at build time but not in MANIFEST.in")


def test_every_build_input_actually_exists():
    """Guards the list above against drifting from the tree."""
    for path in _BUILD_INPUTS:
        assert (ROOT / path).exists(), f"{path} is gone; update the list"


def test_tests_and_their_data_are_shipped():
    text = MANIFEST.read_text()
    assert "tests" in text, "an sdist whose tests cannot run is not much"


def test_package_declares_a_version():
    import pyte
    assert pyte.__version__


def test_version_matches_pyproject():
    import tomllib

    import pyte
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyte.__version__ == data["project"]["version"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_packaging.py -v`
Expected: FAIL, no `MANIFEST.in`, no `pyte.__version__`.

- [ ] **Step 3: Write MANIFEST.in**

```
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
# Everything the build reads that setuptools would not ship by
# default.  Without these an sdist contains the Python sources but
# cannot rebuild the cffi shim: cffi execs build_shim.py, which reads
# te_compat.py, pyproject.toml and shim/pyte_shim_cdef.h, and compiles
# the .c files against headers found via include_dirs.  The headers
# are never in ext_modules' sources, so they are omitted
# unconditionally.
include build_shim.py
include te_compat.py
recursive-include shim *.c *.h
# So the suite can actually be run from an unpacked sdist.
recursive-include tests *.py
recursive-include tests/data *
```

- [ ] **Step 4: Add __version__**

In `src/pyte/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Python API wrappers for the OKTET Labs Test Environment."""
from importlib.metadata import PackageNotFoundError, version as _version

__all__ = ["test", "cfg", "job", "net", "rcf", "rpc", "tad", "errors",
           "log"]

try:
    #: Installed distribution version.
    __version__ = _version("pyte")
except PackageNotFoundError:      # running from a source tree
    import pathlib
    import tomllib
    _pp = pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml"
    __version__ = (tomllib.loads(_pp.read_text())["project"]["version"]
                   if _pp.exists() else "0.0.0+unknown")
```

Keep the fallback: the tests and the docs build both run from the source tree, where the distribution may not be installed.

- [ ] **Step 5: Verify an sdist really rebuilds**

This cannot run in the offline suite (it needs `TE_INSTALL` and a compiler). Do it by hand once, and record the commands in the commit body:

```bash
cd /tmp && rm -rf sdist-check && mkdir sdist-check && cd sdist-check
python -m build --sdist /home/kostik/prj/te/pyte -o .
tar tzf pyte-*.tar.gz | grep -E 'shim/|build_shim|te_compat'
```
Every file in `_BUILD_INPUTS` must appear. Then unpack it somewhere with no source tree on `sys.path`, set `TE_INSTALL`, and `pip install .`.

- [ ] **Step 6: Run tests, lint, commit**

```bash
.venv/bin/python -m pytest tests/ -q
ruff check src tests setup.py
git add -A
git commit -s -m "ship the files an sdist needs to rebuild" -m "With no MANIFEST.in an sdist contained the Python sources and
nothing else: cffi execs build_shim.py (absent), which imports
te_compat.py (absent) and reads shim/pyte_shim_cdef.h (absent), then
compiles two .c files against headers that are never in
ext_modules' sources and so were omitted unconditionally.  The .c
files themselves only appear when setup() ran with TE_INSTALL set,
and then with absolute paths an sdist cannot place.

Add MANIFEST.in covering every build input plus tests/ and
tests/data/, so an unpacked sdist can both rebuild and self-test.

Add pyte.__version__, read from the installed distribution with a
source-tree fallback.  Deliberately NOT adding build_info(): te-dist
already labels images with pyte.commit, pyte.version and te.commit."
```

---

### Task 2: Ship type enforcement before generics

**Files:**
- Modify: `pyproject.toml` (mypy config, dev dependency)
- Modify: `Taskfile.yml` (a `typecheck` task)
- Create: `tests/typing/test_cfg_types.py` (mypy fixtures)
- Test: `tests/test_typing.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a `task typecheck` that fails on a type regression; fixture files the generics work in Task 3 will make pass.

**Do NOT ship `py.typed` in this task.** A `py.typed` marker tells consumers' checkers to trust pyte's annotations, and today `iface.mtu` infers `Any`. Shipping the marker before Task 3 makes every consumer silently trust nothing. `py.typed` lands at the end of Task 3.

- [ ] **Step 1: Add the configuration**

In `pyproject.toml`:

```toml
[dependency-groups]
dev = ["pytest>=8", "PyYAML>=6", "mypy>=1.11"]

[tool.mypy]
python_version = "3.11"
files = ["src/pyte"]
# Start where the value is and the noise is not: the descriptor and
# collection layer, which throws away types cfg.get() already
# computes.  Widen module by module rather than turning on strict
# everywhere and drowning the signal.
warn_unused_ignores = true
warn_redundant_casts = true
no_implicit_optional = true

[[tool.mypy.overrides]]
module = ["pyte.cfg._engine", "pyte.cfg"]
disallow_untyped_defs = true
disallow_incomplete_defs = true

[[tool.mypy.overrides]]
# Generated from TE CM YAML; regenerate rather than annotate by hand.
module = "pyte.cfg.gen.*"
ignore_errors = true

[[tool.mypy.overrides]]
# cffi builds this at compile time; there is nothing to check.
module = "pyte._shim"
ignore_missing_imports = true
```

In `Taskfile.yml`, beside `test`:

```yaml
  typecheck:
    desc: Type-check the typed subset (no TE needed)
    cmds:
      - uv run mypy
```

- [ ] **Step 2: Record the current baseline**

Run: `uv run mypy 2>&1 | tail -5`
Write the error count into the commit body. If the count is large, tighten the `overrides` list until the run is clean, then widen it in Task 3 — a red gate nobody can turn green gets ignored.

- [ ] **Step 2b: Pin the ruff rule set**

The repo has no `[tool.ruff]` config, so "lint is clean" means
whatever the locally installed ruff happens to check. Concretely:
ruff 0.7.1 reports "All checks passed!" while ruff 0.16.6 reports
hundreds of findings across the same unmodified tree, because the
newer default rule set is far larger. A contributor with a different
ruff gets a different gate, and a `uv`-fetched ruff gets a third one.

Pin it in `pyproject.toml`, choosing the rules deliberately rather
than inheriting a moving default:

```toml
[tool.ruff]
line-length = 79
target-version = "py311"

[tool.ruff.lint]
# Deliberate, not inherited: ruff's default set changes between
# releases, so an unpinned config means the gate moves under the
# codebase.  E/W/F/I is what this tree is already clean under; add
# rules in their own commits so the fixes are reviewable.
select = ["E", "W", "F", "I"]

[tool.ruff.lint.isort]
known-first-party = ["pyte"]
```

Add `ruff` to `[dependency-groups] dev` with a floor, and a
`Taskfile.yml` `lint` task running `uv run ruff check src tests
setup.py`. Then confirm the tree is still clean:

```bash
uv run ruff check src tests setup.py
```

If `I` (import sorting) is not already satisfied — `cfg/__init__.py`
and `rcf.py` have un-sorted import blocks — either fix those two
files in this commit or drop `I` from `select` and note why. Do not
leave a red gate.

- [ ] **Step 3: Write the type fixtures the generics must satisfy**

Create `tests/typing/test_cfg_types.py`. These are inputs to mypy, not pytest tests; they must be excluded from pytest collection (add `testpaths` or a `collect_ignore` — check how `pyproject.toml`'s `[tool.pytest.ini_options]` is set and match it):

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Type fixtures: what a checker must infer from the cfg layer.

Not executed.  `reveal_type` lines are assertions mypy checks; each
one that currently says `Any` is a type pyte computes and throws away
at the descriptor boundary.
"""
from pyte.cfg import BoolKnob, CfgObject, Collection, IntKnob, StrKnob


class Addr(CfgObject):
    broadcast = StrKnob("broadcast")


class Iface(CfgObject):
    mtu = IntKnob("mtu")
    promisc = BoolKnob("promisc")
    name_ = StrKnob("name")
    index = IntKnob("index", access="read_only")
    addrs = Collection("net_addr", Addr)


def check_knob_reads(i: Iface) -> None:
    reveal_type(i.mtu)              # N: Revealed type is "builtins.int"
    reveal_type(i.promisc)          # N: Revealed type is "builtins.bool"
    reveal_type(i.name_)            # N: Revealed type is "builtins.str"


def check_class_access() -> None:
    # On the class, a descriptor is itself -- not its value type.
    reveal_type(Iface.mtu)          # N: ... "pyte.cfg._engine.IntKnob"


def check_collection_keeps_its_element_type(i: Iface) -> None:
    reveal_type(i.addrs["10.0.0.1"])        # N: ... "Addr"
    reveal_type(i.addrs["10.0.0.1"].broadcast)   # N: ... "builtins.str"
    for a in i.addrs:
        reveal_type(a)                       # N: ... "Addr"
    reveal_type(i.addrs.get("x"))            # N: ... "Addr | None"


def check_writes_are_checked(i: Iface) -> None:
    i.mtu = 9000
    i.mtu = "nine thousand"   # E: Incompatible types in assignment
    i.index = 3               # E: read-only knob
```

- [ ] **Step 4: Confirm the fixtures fail today**

Run: `uv run mypy tests/typing/test_cfg_types.py`
Expected: the `reveal_type` lines report `Any`, and the two deliberate errors are NOT reported. That is the gap Task 3 closes. Record the output in the commit body.

- [ ] **Step 5: Commit the enforcement**

```bash
.venv/bin/python -m pytest tests/ -q
ruff check src tests setup.py
git add -A
git commit -s -m "add a type-checking gate before typing the engine" -m "There is no mypy config, no type tests and no py.typed, so nothing
would hold generic descriptors in place once they were written.
Ship the enforcement first: a scoped mypy config over the cfg layer,
a `task typecheck`, and fixture files asserting what a checker
should infer.

The fixtures fail deliberately: iface.mtu reveals Any today because
cfg.get() is precisely annotated and _Knob.__get__ throws that away.
The next commit makes them pass.

py.typed is NOT shipped yet -- the marker tells consumers to trust
these annotations, and until the descriptors are typed it would just
make them trust Any."
```

---

### Task 3: Generic descriptors and collections

**Files:**
- Modify: `src/pyte/cfg/_engine.py` (`_Knob` and subclasses, `SubObject`, `Collection`, `BoundCollection`)
- Modify: `src/pyte/cfg/_gen.py` (emit explicit value types for `SelfKnob`)
- Create: `src/pyte/py.typed`
- Modify: `setup.py` (`package_data`)
- Test: `tests/typing/test_cfg_types.py`, `tests/test_packaging.py`

**Interfaces:**
- Consumes: the mypy gate from Task 2.
- Produces: `_Knob[T]`, `Collection[T]`, `BoundCollection[T]`, `SubObject[T]` generic in their value/element type; `py.typed` shipped.

**Background:** no `TypeVar` or `Generic[` exists anywhere in `src/`. `cfg.get()` is precisely annotated (`-> bool | float | int | str | None`) and `_Knob.__get__` throws it away by being unannotated. `BoundCollection.__getitem__` returns bare `CfgObject`, so `iface.irq["3"].smp_affinity` type-checks as `Any` on an `Any`.

**Runtime behavior must not change.** Coercion stays exactly as it is; stricter input validation is explicitly not part of this task.

- [ ] **Step 1: Make the descriptors generic**

In `src/pyte/cfg/_engine.py`:

```python
from typing import Generic, TypeVar, overload

T = TypeVar("T")
C = TypeVar("C", bound="CfgObject")


class _Knob(Generic[T]):
    """Descriptor base: an attribute backed by a leaf instance value.

    Generic in the value type, with overloaded __get__ so class-level
    access yields the descriptor and instance-level access yields the
    value.  cfg.get() already computes that type; without the
    overloads it was discarded here and every read inferred Any.
    """

    @overload
    def __get__(self, obj: None, owner: type | None = ...) -> "_Knob[T]":
        ...

    @overload
    def __get__(self, obj: CfgObject, owner: type | None = ...) -> T:
        ...

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        return self.from_cfg(cfg.get(self._oid(obj), sync=self.sync))

    def __set__(self, obj: CfgObject, value: T) -> None:
        ...   # body unchanged

    def from_cfg(self, value) -> T:
        return value

    def to_cfg(self, value: T):
        return value
```

Then parameterize the subclasses: `class IntKnob(_Knob[int])`, `BoolKnob(_Knob[bool])`, `DoubleKnob(_Knob[float])`, `StrKnob(_Knob[str])`, `AddrKnob(_Knob[str])`, `IpAddrKnob(_Knob["ipaddress.IPv4Address | ipaddress.IPv6Address | None"])`.

`SelfKnob` is the awkward one: it takes `cvt_name` at construction and its value type varies per generated use. Make it `SelfKnob(_Knob[T])` and have the generator emit an explicit parameter (Step 3).

- [ ] **Step 2: Make the containers generic**

```python
class SubObject(Generic[C]):
    def __init__(self, subid: str, cls: type[C]):
        ...

    @overload
    def __get__(self, obj: None, owner: type | None = ...
                ) -> "SubObject[C]": ...
    @overload
    def __get__(self, obj: CfgObject, owner: type | None = ...) -> C: ...
    def __get__(self, obj, owner=None):
        ...   # body unchanged


class Collection(Generic[C]):
    ...
    @overload
    def __get__(self, obj: None, owner: type | None = ...
                ) -> "Collection[C]": ...
    @overload
    def __get__(self, obj: CfgObject, owner: type | None = ...
                ) -> "BoundCollection[C]": ...
    def __get__(self, obj, owner=None):
        ...   # body unchanged


class BoundCollection(Generic[C]):
    def __getitem__(self, name: str) -> C: ...
    def get(self, name: str, default: C | None = None) -> C | None: ...
    def __iter__(self) -> Iterator[C]: ...
    def add(self, name: str, value=None) -> C: ...
```

Bodies are unchanged throughout; only signatures gain types.

- [ ] **Step 3: Give generated self-knobs an explicit value type**

`src/pyte/cfg/_gen.py:488-490` hand-builds the `SelfKnob` line, bypassing `_wrap_member`. Route it through `_wrap_member` and emit the parameter, e.g. `value = SelfKnob[int](cvt_name="INT32")`, mapping the CM type to the Python type with the same table `knob_class()` uses. Then regenerate:

```bash
.venv/bin/python -m pyte.cfg._gen
.venv/bin/python -m pytest tests/test_cfg_gen.py tests/test_cfg_gen_drift.py -q
```

The drift gate must be green; if the generated output changes, that IS the change, and the checked-in modules move with it.

- [ ] **Step 4: Verify the fixtures now pass**

Run: `uv run mypy tests/typing/test_cfg_types.py`
Expected: every `reveal_type` matches its comment, and the two deliberate errors ARE reported. If `i.mtu = "nine thousand"` still passes, `__set__` is not typed; fix it rather than relaxing the fixture.

Run: `uv run mypy`
Expected: no worse than the Task 2 baseline. Tighten the `overrides` to make `pyte.cfg._engine` clean.

- [ ] **Step 5: Ship py.typed**

Create the empty marker `src/pyte/py.typed`, and add to `setup.py`:

```python
    package_data={"pyte": ["py.typed"]},
```

Extend `tests/test_packaging.py`:

```python
def test_py_typed_is_shipped():
    assert (SRC / "pyte" / "py.typed").exists()
    kwargs = _setup_kwargs()
    assert "package_data" in kwargs, (
        "py.typed exists but setup.py does not ship it, so consumers "
        "still see an untyped package")
```

- [ ] **Step 6: Annotate the bare entry points**

Add return annotations to the facade factories and lookups the review named: `env.pco()` (`-> RpcServer`), `env.cfg_iface()` (`-> pyte.net.Iface`), `_tool.launch()`, `_tool.running()`, and the tool `run()` entry points in `ping.py`, `iperf3.py`, `netperf.py`, `wrk.py`, `stress.py`, `fio.py`. Use `TYPE_CHECKING` imports where a runtime import would cycle — `net.py:363,373` already shows the pattern.

- [ ] **Step 7: Run everything, lint, commit**

```bash
.venv/bin/python -m pytest tests/ -q
uv run mypy
ruff check src tests setup.py
git add -A
git commit -s -m "cfg: make the knob and collection types visible" -m "cfg.get() is precisely annotated and _Knob.__get__ threw that away
by being unannotated, so iface.mtu inferred Any -- the type existed
and was discarded at the descriptor boundary.  BoundCollection
erased its element class too, so iface.irq['3'].smp_affinity was Any
on an Any.

Make _Knob, SubObject, Collection and BoundCollection generic, with
overloaded __get__ so class access yields the descriptor and
instance access yields the value.  Emit an explicit value type for
generated SelfKnobs.  Bodies are unchanged: runtime coercion is
identical, and stricter input validation is deliberately not part of
this change.

Ship py.typed now that there is something worth trusting."
```

---

### Task 4: Correct the stale documentation

**Files:**
- Modify: `docs/guides/caveats.md`
- Modify: `docs/guides/rpc.md`
- Modify: `src/pyte/cfg/__init__.py` (`transaction` summary line, if wave 1 did not)
- Test: `tests/test_docs_claims.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: a small test that pins the doc claims which have already drifted once.

**The three drifts, all verified:**

1. `caveats.md:15-17`: "`CVT_BOOL` instances read back as int 0/1, not Python bool". False — `cfg/__init__.py:54-55` returns `int(value) != 0`, a real `bool`, and `cfg.get`'s own docstring says `BOOL -> bool`.
2. `caveats.md:26-30`: "deliberately exposes a minimal int-valued option surface (currently `SO_REUSEADDR`) ... add a row to `_SOCKOPTS` in `src/pyte/rpc/socket.py`". Doubly false — `SockOpt` has ten members and `_SOCKOPTS` does not exist, so the instructions cannot be followed.
3. `rpc.md:19-20`: "`getpeername()` — return `(ip, port)` ... or `None` when the call was suppressed". False — it is typed `-> tuple[str, int]` and always returns a value. It also contradicts `caveats.md:24-25`, which correctly says there is no suppressed-`None` path. `rpc.md`'s option list also omits `SO_INCOMING_NAPI_ID`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_docs_claims.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Pin the guide claims that have already drifted from the code.

Prose cannot be type-checked, and nothing else in the suite reads the
guides, so the three claims corrected here get a cheap regression
test rather than a promise to remember.
"""
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs" / "guides"
CAVEATS = (DOCS / "caveats.md").read_text()
RPC = (DOCS / "rpc.md").read_text()


def test_caveats_does_not_claim_bool_reads_back_as_int():
    assert "read back as int 0/1" not in CAVEATS


def test_caveats_does_not_point_at_a_table_that_was_deleted():
    assert "_SOCKOPTS" not in CAVEATS


def test_caveats_does_not_claim_one_socket_option():
    assert "currently `SO_REUSEADDR`" not in CAVEATS


def test_rpc_guide_does_not_claim_getpeername_returns_none():
    assert "or\n  `None` when the call was suppressed" not in RPC
    assert "None` when the call was suppressed" not in RPC


def test_socket_option_list_covers_every_enum_member():
    """The guide lists the options by hand; a new member must be added
    to it, not silently omitted (SO_INCOMING_NAPI_ID was)."""
    from pyte.rpc.socket import SockOpt
    for member in SockOpt:
        assert member.name in RPC, f"{member.name} is undocumented"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_docs_claims.py -v`
Expected: FAIL on all five.

- [ ] **Step 3: Correct caveats.md**

Replace the BOOL bullet:

```markdown
- `cfg`: `CVT_ADDRESS` values are plain strings, and the CVT is
  overloaded -- the value may be an IP (`"192.0.2.1"`) or a MAC, so
  `AddrKnob` returns text and only `IpAddrKnob` parses.  `CVT_BOOL`
  instances read back as real Python `bool`.
```

Replace the socket-option bullet:

```markdown
- `RpcSocket.setsockopt()` exposes an int-valued option surface named
  by the `SockOpt` enum in `src/pyte/rpc/socket.py`.  To add an
  option: passthrough the `RPC_SO_*` constant from
  `te_rpc_sys_socket.h` as `PYTE_SO_*` in `shim/pyte_shim.h` and the
  cdef, then add a member to `SockOpt` whose value is that constant's
  name.  (There is no `_SOCKOPTS` table any more; the enum member
  value IS the shim constant name.)
```

- [ ] **Step 4: Correct rpc.md**

Fix the `getpeername()` bullet to say it returns `(ip, port)` and raises on failure, and add `SO_INCOMING_NAPI_ID` to the option list. Consider generating that list from the enum instead of hand-maintaining it — the test in Step 1 will otherwise fail every time a member is added, which is the point, but a generated list is better than a gate.

- [ ] **Step 4b: Document the four resource lifecycles**

The spec asks for this explicitly, and it is the doc gap behind
several of the bugs the earlier waves fixed: a generic `Job`, a
`ToolHandle`, a batch `Trex` and an interactive `remote`/TRex session
all look alike and behave differently, and nothing says so.

Add a section to `docs/guides/architecture.md` with one short
paragraph each:

- **`pyte.job.Job`** — you own it. Create, start, wait, destroy;
  `with` destroys it. Channels and filters die with the job and raise
  `ClosedResourceError` afterwards.
- **`pyte.tools` `ToolHandle`** — the wrapper owns the job. `wait()`
  parses and caches a report; `close()` stops and destroys, and is
  retryable. Use `run()`'s context manager and do not touch the job.
- **`pyte.tools.trex.batch.Trex`** — created and started separately
  (mirroring the C `tapi_trex_create`/`tapi_trex_start`). `report()`
  is cached and stays valid after `close()`; the `create()` context
  manager tears everything down on every exit path.
- **Interactive sessions** (`pyte.remote.python`, `trex.stl.session`,
  `trex.astf.session`) — a live agent-side process driven per call.
  Every call is bounded; a timeout leaves the session unusable, so
  there is no "wait forever" and the session cannot be reused after
  one.

State plainly that these are deliberately not one interface: forcing
them into a universal handle would hide exactly the differences a
caller has to know. Cross-link the four from `caveats.md`.

- [ ] **Step 5: Check the rest of both guides against the code**

Two of these three drifts came from code moving under prose nobody re-read. Before closing this task, walk `caveats.md` and `rpc.md` bullet by bullet and confirm each against the source. Note anything else stale in the commit body even if you do not fix it.

- [ ] **Step 6: Build the docs from scratch**

```bash
rm -rf docs/_build
./scripts/build-docs.sh
```

The build is `-W` (warnings fatal) and needs the python-ts checkout for the showcase snippets. It must succeed.

- [ ] **Step 7: Run tests, lint, commit**

```bash
.venv/bin/python -m pytest tests/ -q
ruff check src tests setup.py
git add -A
git commit -s -m "docs: correct three claims the code contradicts" -m "caveats.md said CVT_BOOL reads back as int 0/1 -- cfg.get() has
returned a real bool for some time, and its own docstring says so.
It also told readers to add socket options to a _SOCKOPTS table that
no longer exists, and described the surface as 'currently
SO_REUSEADDR' when the SockOpt enum has ten members.

rpc.md said getpeername() may return None 'when the call was
suppressed'; it is typed -> tuple[str, int], always returns a value,
and caveats.md correctly says there is no suppressed-None path.  Its
option list also omitted SO_INCOMING_NAPI_ID.

Nothing in the suite read the guides, so all three drifted silently.
Add a small test pinning the claims, including one that fails when a
SockOpt member is left undocumented."
```

---

## Wave 4 exit criteria

- [ ] `.venv/bin/python -m pytest tests/ -q` green.
- [ ] `uv run mypy` clean over the configured subset; `task typecheck` exists.
- [ ] `[tool.ruff]` pins the rule set, and `uv run ruff check src
      tests setup.py` is clean with a pinned ruff version.
- [ ] The fixtures in `tests/typing/` reveal concrete types, and the two deliberate errors are reported.
- [ ] `src/pyte/py.typed` exists AND `setup.py` ships it.
- [ ] A hand-built sdist contains every file in `_BUILD_INPUTS` and rebuilds in a clean directory with no source tree on `sys.path`.
- [ ] `pyte.__version__` matches `pyproject.toml`.
- [ ] `./scripts/build-docs.sh` succeeds from scratch with `-W`.
- [ ] `docs/guides/architecture.md` documents the four resource
      lifecycles and says why they are not unified.
- [ ] The minimum-TE check is untouched and still runs at build
      time.
- [ ] No `build_info()` was added.
