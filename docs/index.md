# pyte documentation

Python API for writing OKTET Labs Test Environment (TE) tests. pyte wraps
TE's engine-side C libraries (RPC, Configurator, `tapi_job`, TAD/CSAP,
logging, `tapi_env`, `te_mi`) behind a cffi shim so test suites can be
written in plain Python.

This documentation is built with Sphinx and needs no TE.

````{toctree}
:maxdepth: 2
:caption: Tutorials

tutorials/bootstrap-a-suite
````

````{toctree}
:maxdepth: 2
:caption: Guides

guides/architecture
guides/rpc
guides/net
guides/rcf
guides/env
guides/tester
guides/tools-fio
guides/mi
guides/extending-pyte
guides/caveats
````

````{toctree}
:maxdepth: 1
:caption: Reference

api/index
````
