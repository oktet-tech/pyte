# pyte.tools.fio — run fio from Python tests

`pyte.tools.fio` is **pure Python** over `pyte.job`: it builds fio's argv,
drives the job, parses the JSON report, and emits MI measurements —
with zero shim imports and no `tapi_fio` linkage.  fio is resolved
from the **agent's PATH** (the job program is the string `"fio"`).
Tests must carry `<req id="FIO"/>` so the prologue probe can exclude
them on rigs where fio is absent.

The fio JSON report arrives on the job's **stdout** via a readable
filter.  Diagnostic warnings that fio may print to stdout before the
JSON object (e.g. iodepth-capped notices) are stripped automatically.

From the showcase test `ts/fio/randrw.py` (`t.rpc_server(...)` gives
`pco`; `DATAFILE` is a `/dev/shm/...` tmpfs path so the workload needs
neither root nor real disk wear; `rwtype` comes from the test's
`rwtype` parameter, one of `fio.RwType`'s lowercase names):

```{literalinclude} /_snippets/fio-run.py
:language: python
```

`rwtype` accepts a `fio.RwType` enum member (e.g. `fio.RwType.RAND`) or
a lowercase name string (e.g. `"rand"`); the enum value is the fio
`--readwrite=` token (`"randrw"`).  Likewise, `ioengine` accepts a
`fio.IoEngine` member (e.g. `fio.IoEngine.LIBAIO`) or a lowercase name
string (e.g. `"libaio"`).  An unrecognised string raises `ValueError`;
a non-string non-enum value raises `TypeError`.

`Report` is a frozen dataclass: `rep.read` and `rep.write` are
`IoStats`, each with `bandwidth` (`Bw`), `iops` (`Iops`), `latency`
(`Lat`) and `clatency` (`Clat`) sub-objects.  `Clat` carries
`percentiles` (`Percentiles`) with `p99_00`, `p99_50`, `p99_90`,
`p99_95`.  All bandwidth fields are KiB/s; latency/clatency fields are
nanoseconds.

`Fio.mi_report(tool="fio")` mirrors `tapi_fio_mi_report`: it emits six
measurements via `pyte.mi.Logger` — read/write throughput (Mbit/s,
mean), read/write IOPS (plain, mean) and read/write clat 99th
percentile (µs, percentile aggr).

Argv mapping mirrors `tapi_fio`'s `fio_binds` order; the docstring in
`src/pyte/tools/fio.py` is the authoritative reference.
