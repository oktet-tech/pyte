# pyte.mi — thin te_mi measurement logger

`pyte.mi` wraps TE's `te_mi` C library through three shim functions
(`pyte_mi_meas_create`, `pyte_mi_add_meas`, `pyte_mi_destroy`).
It is intentionally thin and generic — any perf tool can consume it
from pure Python without any C work.

```python
from pyte import mi

with mi.Logger("fio") as logger:
    logger.add("throughput", "Read throughput", "mean", 29.6, "mebi")
    logger.add("iops",       "Read iops",       "mean", 925550.0, "plain")
    logger.add("latency",    "Read clat 99.00 percentile",
               "percentile", 0.668, "micro")
```

The *tool* string (`"fio"`) keys the MI artifact that TE's Logger
emits.  `destroy` (called on CM exit or explicit `close()`) flushes
the artifact; no MI data is written if `add()` is never called.
`close()` is idempotent.

Recognised names:

| Kind        | Names |
|-------------|-------|
| **type**    | `latency`, `throughput`, `iops` |
| **aggr**    | `single`, `min`, `max`, `mean`, `stdev`, `percentile` |
| **multiplier** | `nano`, `micro`, `milli`, `plain`, `mebi` |

Unknown names raise `ValueError` with the valid set listed.  `add()`
on a closed logger raises `RuntimeError`.  The name→int maps are
resolved lazily from shim constants on first use (same pattern as
`pyte.rpc.iomux`'s `EVENT_BITS`).
