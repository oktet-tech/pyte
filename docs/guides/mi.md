# pyte.mi — thin te_mi measurement logger

`pyte.mi` wraps TE's `te_mi` C library through three shim functions
(`pyte_mi_meas_create`, `pyte_mi_add_meas`, `pyte_mi_destroy`).
It is intentionally thin and generic — any perf tool can consume it
from pure Python without any C work.

```python
from pyte import mi
from pyte.mi import Aggr, Meas, Mult

with mi.Logger("fio") as logger:
    logger.add(Meas.THROUGHPUT, "Read throughput", Aggr.MEAN, 29.6, Mult.MEBI)
    logger.add(Meas.IOPS,       "Read iops",       Aggr.MEAN, 925550.0, Mult.PLAIN)
    logger.add(Meas.LATENCY,    "Read clat 99.00 percentile",
               Aggr.PERCENTILE, 0.668, Mult.MICRO)
```

The *tool* string (`"fio"`) keys the MI artifact that TE's Logger
emits.  `destroy` flushes the artifact; no MI data is written if
`add()` is never called.  `close()` is idempotent.

## When the data is written

Inside a running test `close()`, and leaving the `with` block (also
by an exception), does not write: the logger is handed to the test.
When the body ends, however it ends, the test:

1. sets `t.failed`: True unless the body passed or was skipped;
2. runs the finalizers registered with `t.finalize(fn, *args)`, in
   registration order;
3. if any logger is pending, opens a step named "Measurements" and
   writes the loggers in the order they were closed;
4. runs the cleanups under "Cleanup", as before.

So all MI rows of a test sit under one "Measurements" step before
Cleanup, on failed tests too, with whatever was collected.  A
finalizer is where something sampling through the whole test stops
and closes its logger:

```python
sampler.start()
t.finalize(sampler.stop)    # stop() closes its mi.Logger
```

Finalizers get no step of their own: what they log lands at the end
of the last body step.  A failing finalizer or logger write is logged
as an error with its traceback; the others still run and the exit
code does not change.  Prologues and epilogues are tests and get the
same step.

`close(immediate=True)` writes at once, and so does `close()` outside
a test (unit tests, tools) or in a cleanup, once the test is past the
Measurements step.  In unit tests `pyte.testing.RecordingMiLogger`
defers the same way inside a `current_test`, and
`pyte.testing.end_test(t)` runs that end-of-test order on it.

Measurement types, aggregations, and multipliers are represented by
the `Meas`, `Aggr`, and `Mult` enums:

| Enum   | Members |
|--------|---------|
| `Meas` | `LATENCY`, `THROUGHPUT`, `IOPS`, `RTT`, `RETRANS`, `RPS`, `PERCENTAGE` |
| `Aggr` | `SINGLE`, `MIN`, `MAX`, `MEAN`, `STDEV`, `MEDIAN`, `PERCENTILE` |
| `Mult` | `NANO`, `MICRO`, `MILLI`, `PLAIN`, `MEGA`, `MEBI` |

Passing a value of the wrong enum (or a plain string) raises `TypeError`.
`add()` on a closed logger raises `RuntimeError`.  The enum→int
resolution is lazy (cached from shim constants on first use, same
pattern as `pyte.rpc.iomux`'s `EVENT_BITS`).
