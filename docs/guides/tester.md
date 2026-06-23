# pyte.tester — runtime requirements and TRC tags

`pyte.tester` exposes two functions meant for the suite's root prologue:
`add_trc_tag(name, value=None)` records a runtime TRC tag (visible in
`/local:/trc_tags:` and attached to the run's TRC report); TE enforces
that tags can only be added before the TRC snapshot — calls from tests
raise `TeError(TE_EPERM)`.  `modify_reqs(expr)` ANDs a requirement
expression into the Tester's session filter (same syntax as
`--tester-req`); the Tester applies the new expression when the calling
prologue exits, so it cannot affect the prologue itself.

A typical use is fio gating: the prologue probes whether fio is
installed on the agent host, then either records `add_trc_tag("fio")` or
calls `add_trc_tag("no_fio")` followed by `modify_reqs("!FIO")` so that
tests carrying `<req id="FIO"/>` are excluded for the rest of the run.
See `ts/prologue.py` and `ts/tester/` in a consuming suite (e.g. python-ts)
for the full example.
