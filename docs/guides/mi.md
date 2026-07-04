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
emits.  `destroy` (called on CM exit or explicit `close()`) flushes
the artifact; no MI data is written if `add()` is never called.
`close()` is idempotent.

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
