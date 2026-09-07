# pyte docs navigation restructure

Status: proposal, 2026-08-18.

## Current sidebar

    Tutorials   1 item
    Guides      11 items, flat, 8 titled "pyte.<module> - ..."
    Showcase    1 item -> 20 alphabetical children
    Reference   1 item -> 15 modules -> 27 submodules (17 of them pyte.tools.*)

## Problems

1. Guide titles are module signatures. Eight of eleven start with "pyte.",
   so the sidebar's left edge carries no information and the
   distinguishing token sits at position 6 followed by 30+ chars that
   wrap. The section also reads as a second API listing next to the real
   Reference section.
2. "Guides" has no ordering principle. env.md defines PCOs and agent
   aliases but sits 6th, after four guides that use them; rcf sits after
   its consumers rpc and net.
3. Wrong altitude: tools-fio is a peer of architecture. One of 17 tool
   wrappers has a top-level slot; the tools family has no page.
4. Guides cover 8 of 15 modules. Nothing for cfg, tad, job, test,
   errors, log, trc, although showcase/cfg.md (175 lines) and
   showcase/job.md (235 lines) are the two largest showcase pages.
5. Showcase is a second taxonomy of the same topics, alphabetized, mixing
   core-API demos, tool demos and cross-cutting pages, so "fio, iperf3,
   job" sit adjacent.
6. Reference is flat, and pyte.tools.* is half the visible tree while
   pyte.cfg.gen.* expands first. Sidebar weight is inverse to importance.
7. No orientation layer: no install page, no TE-concepts glossary
   (agent, PCO, OID, CSAP, TRC tag, requirement, MI). The single
   tutorial assumes all of it, and a one-item caption reads as a stub.
8. Guides use :maxdepth: 2, expanding H2s into the left sidebar for 7 of
   11 pages, duplicating Furo's right-hand "On this page".

## Proposed structure

    Start here
      Overview                        index.md, rewritten
      Install and build               NEW, from README.md
      Your first test                 tutorials/bootstrap-a-suite.md
      TE concepts in pyte terms       NEW glossary

    Core concepts
      Architecture                    guides/architecture.md
      Test lifecycle and parameters   NEW (pyte.test, _params)
      Errors and failures             NEW (pyte.errors, longjmp guard)
      Logging                         NEW (pyte.log)
      Known caveats                   guides/caveats.md

    Working with the test bed
      Environment and PCOs            guides/env.md
      Configurator tree               NEW (pyte.cfg + cfg.gen)
      Network configuration           guides/net.md
      Agents and file transfer        guides/rcf.md

    Driving the hosts
      Socket RPC                      guides/rpc.md
      Running processes               NEW (pyte.job)
      Python on the agent             guides/remote.md
      Packets with TAD                NEW (tad.dsl + tad.csap)
      Tool wrappers                   NEW overview, table of all 17
        fio                           guides/tools-fio.md, demoted
        TRex stateless traffic        NEW

    Results and selection
      Requirements and TRC tags       guides/tester.md
      Measurements with MI            guides/mi.md
      TRC database access             NEW (pyte.trc)

    Examples
      Showcase overview
        Core API      cfg env job net rcf remote rpc tad tester dynamic
        Tools         fio iperf3 netperf nptcp ping sfnt_pingpong
                      stress trex wrk
        End-to-end    usecases

    Reference
      API by area                     5 pages, below
      Extending pyte                  guides/extending-pyte.md

Reference buckets:

    Writing tests     pyte.test  pyte.errors  pyte.log  pyte.tester
                      pyte.trc
    Test bed          pyte.env   pyte.cfg     pyte.net  pyte.rcf
    Driving hosts     pyte.rpc   pyte.job     pyte.remote
    Traffic and data  pyte.tad   pyte.mi
    Tool wrappers     pyte.tools

## Implementation tiers

Tier 1, no new prose:

- Override sidebar labels per toctree entry, e.g.
  "Socket RPC <guides/rpc>", leaving page H1s intact.
- Set :maxdepth: 1 on every toctree.
- Regroup captions as above using the existing 11 guides.
- Split api/index.md into five pages, one autosummary each.
- In showcase_gen._write_showcase, emit packages in group order from a
  GROUPS dict instead of sorted(); raise ShowcaseError for a package
  missing from the map, matching the generator's existing fail-loud
  handling of missing docstrings.

Fixes problems 1, 2, 3, 5, 6, 8.

Tier 2, the six gap-filling guides: cfg, tad, job, test lifecycle,
errors, tools overview. Each has a showcase package already, so each can
be built from docs:begin snippets the way guides/rpc.md is. Fixes 4,
which Tier 1 makes more visible rather than less.

Tier 3: install page, glossary, and real intermediate pages for the
showcase groups (needed for sidebar hierarchy rather than mere
ordering). Fixes 7.

## Migration cost

Only two cross-document links exist in the tree
(tutorials/bootstrap-a-suite.md:152-153). The 13 literalinclude paths
point at /_snippets/ and are unaffected by any renaming.

## Unrelated finding

conf.py sets autodoc_default_options undoc-members: True, so Reference
pages surface every undocumented member. Noise, independent of
navigation.
