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
  sphinx-build -b html docs docs/_build/html
```

Open `docs/_build/html/index.html`.

## Unit tests

pyte's own unit tests are pure-Python and need no TE engine:

```sh
uv run --no-project --with pytest pytest tests
```

## License

Apache-2.0.
