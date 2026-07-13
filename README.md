# pyte

Python API for writing OKTET Labs Test Environment (TE) tests. pyte wraps
TE's engine-side C libraries (RPC, Configurator, `tapi_job`, TAD/CSAP,
logging, `tapi_env`, `te_mi`) behind a cffi shim, so test suites are written
in plain Python instead of C.

pyte is consumed as a git submodule by test suites (for example
[python-ts](https://github.com/oktet-tech/python-ts) and `nvme-ts`); it is
not run on its own — a suite provides the tests, rigs, and run script.

## Quickstart

Clone a suite that uses pyte, with submodules, and run its showcase:

```sh
git clone --recurse-submodules https://github.com/oktet-tech/python-ts.git
cd python-ts
./scripts/run.sh --cfg=localhost      # builds TE + the pyte shim, then runs
```

Already cloned without submodules? `git submodule update --init lib/pyte`.

## Bootstrap your own suite

See **Bootstrap a test suite** in the documentation (built below) for the
full step-by-step. In short: create a suite repo, add pyte as the `lib/pyte`
submodule, declare the uv workspace, copy a run script and a rig, and add a
first test.

## Documentation

Architecture, per-module guides, the cdef/facade extension pattern, caveats,
and the auto-generated API reference are built with Sphinx and need no TE:

```sh
./scripts/build-docs.sh
# equivalently:
uv run --no-project --with-requirements docs/requirements.txt \
  sphinx-build -W --keep-going -b html docs docs/_build/html
```

Open `docs/_build/html/index.html`.

Building the docs requires a `python-ts` checkout (the showcase suite the
examples are generated from): either a sibling directory of this repo, or
point `PYTE_SHOWCASE` at its root. The build fails without it — by design:
every example in these docs is real, executed suite code.

## Unit tests

Most of pyte's unit tests are pure-Python and need no TE engine. A subset
needs the built cffi shim (`pyte._shim`) or is designed to run from a
consuming suite's environment.

The TE-free subset runs without TE installed (use `--with` to avoid building
the shim):

```sh
PYTHONPATH=src uv run --no-project --with pytest --with scapy --with pyyaml \
  pytest tests \
  --ignore=tests/test_tests_info.py \
  --ignore=tests/test_env.py \
  --ignore=tests/test_net.py \
  --ignore=tests/test_trex_stl.py
```

The full suite (467+ tests, including shim-backed tests) requires a TE
installation to build the cffi shim. Install dev deps once, then run:

```sh
# One-time setup (builds the shim against TE_INSTALL):
TE_INSTALL=/path/to/te/inst uv sync --group dev

# Run the full unit-test suite:
uv run --group dev pytest tests -q --ignore=tests/test_tests_info.py
```

The `--no-project --with pytest --with pyyaml` form still works for TE-free
tests and needs no TE_INSTALL.

The full suite is also easily run from a consuming suite that has already
built pyte, for example:

```sh
cd ../python-ts && uv run pytest lib/pyte/tests
```

## License

Apache-2.0.
