# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.trc facade tests against tests/data/trc_basic.xml."""
from pathlib import Path

import pytest

pytest.importorskip("pyte._shim")

from pyte import trc  # noqa: E402

DATA = Path(__file__).parent / "data" / "trc_basic.xml"


@pytest.fixture()
def db():
    with trc.Db.open(DATA) as handle:
        yield handle


def test_walk_and_find(db):
    paths = [t.path for t in db.walk_tests()]
    assert any(p.endswith("demo/echo") for p in paths)
    echo, = db.find_tests("demo/echo")
    assert echo.name == "echo"
    assert echo.test_type == "script"
    assert db.find_tests("nonexistent") == []


def test_iter_args_and_groups(db):
    echo, = db.find_tests("demo/echo")
    iters = list(echo.iters())
    assert len(iters) == 2
    assert iters[0].args == [("len", "1"), ("proto", "tcp")]
    assert iters[1].args == [("len", ""), ("proto", "udp")]
    assert iters[1].wildcard_args == ["len"]
    assert iters[0].notes in (None, "")
    groups = iters[0].groups()
    assert len(groups) == 1
    assert groups[0].tags_str == "linux&jumbo"
    assert groups[0].key == "BUG-1"
    assert groups[0].notes == "mtu issue"
    entry, = groups[0].entries()
    assert entry.status == "FAILED"
    assert entry.verdicts == ["Too big"]
    g1 = iters[0].groups()[0]
    g2 = iters[0].groups()[0]
    assert g1 == g2 and len({g1, g2}) == 1


def test_match_exact_beats_wildcard(db):
    # The fixture has no overlapping records: the exact iter (len=1,
    # proto=tcp) and the wildcard iter (len=*, proto=udp) cover
    # disjoint argument sets, so only one record ever matches any
    # given call.  The test name reflects the allow_wild=False /
    # allow_wild=True distinction rather than a within-match priority.
    echo, = db.find_tests("demo/echo")
    it = db.match(echo, {"len": "1", "proto": "tcp"})
    assert it is not None and it.args_dict()["len"] == "1"
    wild = db.match(echo, {"len": "777", "proto": "udp"})
    assert wild is not None and wild.wildcard_args == ["len"]
    assert db.match(echo, {"len": "777", "proto": "udp"},
                    allow_wild=False) is None
    assert db.match(echo, {"len": "1", "proto": "sctp"}) is None


def test_exp_result(db):
    echo, = db.find_tests("demo/echo")
    it = db.match(echo, {"len": "1", "proto": "tcp"})
    grp = it.exp_result(["linux", "jumbo"])
    assert grp is not None
    assert [e.status for e in grp.entries()] == ["FAILED"]
    assert grp.matches("FAILED", ["Too big"]) is not None
    assert grp.matches("PASSED") is None
    default = it.exp_result(["linux"])
    assert [e.status for e in default.entries()] == ["PASSED"]


def test_tag_expr_helpers():
    assert trc.tag_expr_matches("linux&jumbo", ["linux", "jumbo"])
    assert not trc.tag_expr_matches("linux&jumbo", ["linux"])
    assert trc.tag_expr_matches(None, [])
    with pytest.raises(trc.TrcError):
        trc.parse_tag_expr("linux &&& bad")


# XML with two overlapping records: one exact iter (a=1) and one
# wildcard iter (a=<wild>) that both match a=1.  lib/trc emits a
# "Duplicated iteration" warning on stderr when the walker encounters
# this; quiet_logging() installs a no-op backend so nothing appears.
_OVERLAP_XML = """\
<?xml version="1.0"?>
<trc_db version="1.0">
  <test name="pkg" type="package">
    <objective>Overlap test</objective>
    <iter result="PASSED">
      <notes/>
      <test name="target" type="script">
        <objective>Overlapping iters</objective>
        <iter result="PASSED">
          <arg name="a">1</arg>
          <notes/>
        </iter>
        <iter result="PASSED">
          <arg name="a"/>
          <notes/>
        </iter>
      </test>
    </iter>
  </test>
</trc_db>
"""


def test_quiet_logging_suppresses_stderr(tmp_path, capfd):
    """quiet_logging() must suppress lib/trc BUG/Duplicated stderr output."""
    db_file = tmp_path / "overlap.xml"
    db_file.write_text(_OVERLAP_XML)

    trc.quiet_logging()
    with trc.Db.open(db_file) as db:
        target, = db.find_tests("pkg/target")
        # Walk all iters to trigger the duplicate-record warning path.
        for it in target.iters():
            db.match(target, dict(it.args))

    captured = capfd.readouterr()
    assert "BUG" not in captured.err
    assert "Duplicated" not in captured.err
