# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the pyte.testsinfo build-time generator."""
import textwrap
import xml.etree.ElementTree as ET

import pytest

from pyte import testsinfo
from pyte.testsinfo import check, docstring, steps


def _module(tmp_path, source, name="t"):
    """Write a test module and return its path."""
    path = tmp_path / (name + ".py")
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def _doc(body):
    """A module docstring, dedented, as the parser sees it."""
    return textwrap.dedent(body).strip("\n")


def _scenario(source):
    """The (depth, text) steps of a source snippet."""
    import ast
    return steps.scenario(ast.parse(textwrap.dedent(source)))


def _analyze(tmp_path, source, name="t"):
    return testsinfo.analyze(str(_module(tmp_path, source, name)))


# --------------------------------------------------------------- objective


def test_objective_is_the_first_paragraph_only():
    doc = _doc("""
        Measure forwarding throughput

        Runs one of the vendored profiles through the device.
    """)
    assert docstring.objective(doc) == "Measure forwarding throughput"


def test_objective_joins_a_multi_line_paragraph():
    doc = _doc("""
        Measure the concurrent connections
        a device sustains

        More prose.
    """)
    assert docstring.objective(doc) == (
        "Measure the concurrent connections a device sustains")


def test_objective_stops_at_a_heading_with_no_blank_line():
    doc = _doc("""
        Prepare the hosts for testing
        Parameter:
            env: Testing environment.
    """)
    assert docstring.objective(doc) == "Prepare the hosts for testing"


# -------------------------------------------------------------- parameters


@pytest.mark.parametrize("heading",
                         ["Parameters", "Parameter", "Args", "Arguments"])
def test_every_heading_spelling_opens_a_section(heading):
    doc = _doc(f"""
        Objective.

        {heading}:
            env: Testing environment.
    """)
    entries, findings = docstring.parameters(doc)
    assert entries == [("env", "Testing environment.")]
    assert findings == []


def test_a_one_line_entry_stays_one_line():
    doc = _doc("""
        Objective.

        Parameters:
            duration: How long to run, in seconds.
    """)
    entries, _ = docstring.parameters(doc)
    assert entries == [("duration", "How long to run, in seconds.")]


def test_a_multi_line_entry_keeps_its_lines():
    """Continuation lines keep their indent relative to the entry.

    Which is what makes a bullet list a bullet list; a wrapped
    sentence pays for it with a four-space hanging indent.
    """
    doc = _doc("""
        Objective.

        Parameters:
            duration: How long to run, in seconds. The `NAPTS_DURATION`
                environment variable overrides it.
    """)
    entries, _ = docstring.parameters(doc)
    assert entries == [(
        "duration",
        "How long to run, in seconds. The `NAPTS_DURATION`\n"
        "    environment variable overrides it.")]


def test_a_bullet_value_list_keeps_its_relative_indent():
    doc = _doc("""
        Objective.

        Parameters:
            fw_mode: Which device under test is in the path:
                - `bridge`: raw forwarding at L2, no DUT application
                - `route`: raw forwarding at L3, no DUT application
                - `blackbox`: preconfigured appliance
    """)
    entries, findings = docstring.parameters(doc)
    assert findings == []
    assert entries == [(
        "fw_mode",
        "Which device under test is in the path:\n"
        "    - `bridge`: raw forwarding at L2, no DUT application\n"
        "    - `route`: raw forwarding at L3, no DUT application\n"
        "    - `blackbox`: preconfigured appliance")]


def test_a_column_zero_line_ends_the_section():
    doc = _doc("""
        Objective.

        Parameters:
            duration: How long to run.

        Notes:
            Not a parameter entry at all.
    """)
    entries, findings = docstring.parameters(doc)
    assert entries == [("duration", "How long to run.")]
    assert findings == []


def test_a_malformed_line_in_a_section_is_a_finding():
    doc = _doc("""
        Objective.

        Parameters:
            duration: How long to run.
            this line is not an entry
    """)
    entries, findings = docstring.parameters(doc)
    assert entries == [("duration", "How long to run.")]
    assert findings == [
        "malformed line in Parameters section: this line is not an entry"]


def test_an_entry_with_no_description_is_empty_not_dropped():
    doc = _doc("""
        Objective.

        Parameters:
            duration:
    """)
    entries, findings = docstring.parameters(doc)
    assert entries == [("duration", "")]
    assert findings == []


# ------------------------------------------------------------------ steps


def test_a_flat_sequence_is_all_depth_one():
    found, findings = _scenario("""
        t.step("One")
        t.step("Two")
    """)
    assert found == [(1, "One"), (1, "Two")]
    assert findings == []


def test_with_contributes_no_heading_and_no_depth():
    found, _ = _scenario("""
        with test.start() as t:
            t.step("One")
    """)
    assert found == [(1, "One")]


def test_if_adds_a_heading_and_a_level():
    found, _ = _scenario("""
        if fw_layer is ts.FwLayer.ETH and dut_.kind is dut.DutKind.NONE:
            t.step("Create bridge")
    """)
    assert found == [
        (1, "If fw_layer is ts.FwLayer.ETH and "
            "dut_.kind is dut.DutKind.NONE:"),
        (2, "Create bridge"),
    ]


def test_else_is_phrased_as_if_not():
    found, _ = _scenario("""
        if rate_mult == "auto":
            t.step("Search")
        else:
            t.step("Run")
    """)
    assert found == [
        (1, "If rate_mult == 'auto':"),
        (2, "Search"),
        (1, "If not rate_mult == 'auto':"),
        (2, "Run"),
    ]


def test_an_elif_chain_stays_flat():
    found, _ = _scenario("""
        if a:
            t.step("A")
        elif b:
            t.step("B")
        elif c:
            t.step("C")
        else:
            t.step("D")
    """)
    assert found == [
        (1, "If a:"), (2, "A"),
        (1, "If b:"), (2, "B"),
        (1, "If c:"), (2, "C"),
        (1, "If not c:"), (2, "D"),
    ]


def test_an_else_holding_an_if_is_not_an_elif():
    found, _ = _scenario("""
        if a:
            t.step("A")
        else:
            if b:
                t.step("B")
    """)
    assert found == [
        (1, "If a:"), (2, "A"),
        (1, "If not a:"), (2, "If b:"), (3, "B"),
    ]


def test_for_names_the_target_and_the_iterable():
    found, _ = _scenario("""
        for name in sorted(captures):
            t.step("Replay one capture")
    """)
    assert found == [
        (1, "For each name in sorted(captures):"),
        (2, "Replay one capture"),
    ]


def test_while_names_its_condition():
    found, _ = _scenario("""
        while not done:
            t.step("Poll")
    """)
    assert found == [(1, "While not done:"), (2, "Poll")]


def test_a_construct_with_no_steps_contributes_nothing():
    found, _ = _scenario("""
        if a:
            x = 1
            for y in z:
                x += y
        t.step("One")
    """)
    assert found == [(1, "One")]


def test_try_and_except_and_finally_are_transparent():
    found, _ = _scenario("""
        try:
            t.step("One")
        except ValueError:
            t.step("Two")
        finally:
            t.step("Three")
    """)
    assert found == [(1, "One"), (1, "Two"), (1, "Three")]


def test_a_function_body_is_walked_where_it_is_defined():
    found, _ = _scenario("""
        def helper():
            t.step("Inner")
        t.step("Outer")
    """)
    assert found == [(1, "Inner"), (1, "Outer")]


def test_push_and_pop_group_the_steps_between_them():
    found, _ = _scenario("""
        log.step_push("Set the box up")
        t.step("One")
        t.step("Two")
        log.step_pop()
        t.step("After")
    """)
    assert found == [
        (1, "Set the box up"),
        (2, "One"),
        (2, "Two"),
        (1, "After"),
    ]


def test_an_fstring_step_keeps_its_expression():
    found, findings = _scenario("""
        t.step(f"Run {name} at {rate * 2} pps")
    """)
    assert found == [(1, "Run {name} at {rate * 2} pps")]
    assert findings == []


def test_a_non_literal_step_is_skipped_with_a_finding():
    found, findings = _scenario("""
        t.step("One")
        t.step(message)
    """)
    assert found == [(1, "One")]
    assert findings == ["line 3: step text is not a literal string"]


# --------------------------------------------------------------- findings


def _findings(source):
    """The parameter findings of a whole module source."""
    import ast
    tree = ast.parse(textwrap.dedent(source))
    doc = ast.get_docstring(tree, clean=True)
    entries, _ = docstring.parameters(doc)
    return check.check_params(tree, entries)


def test_a_read_with_no_entry_is_undocumented():
    assert _findings('''
        """Objective.

        Parameters:
            env: Testing environment.
        """
        with test.start() as t:
            p = t.params
            profile = p["profile"]
    ''') == ["parameter profile is undocumented"]


def test_an_entry_nothing_reads_is_stale():
    assert _findings('''
        """Objective.

        Parameters:
            profile: Which profile to run.
        """
        with test.start() as t:
            pass
    ''') == ["stale documentation for parameter profile (no such read)"]


def test_two_entries_for_one_name_are_a_duplicate():
    assert _findings('''
        """Objective.

        Parameters:
            profile: Which profile to run.
            profile: Which profile to run, again.
        """
        with test.start() as t:
            p = t.params
            profile = p["profile"]
    ''') == ["duplicate documentation for parameter profile"]


def test_an_entry_with_a_blank_description_is_empty():
    assert _findings('''
        """Objective.

        Parameters:
            profile:
        """
        with test.start() as t:
            p = t.params
            profile = p["profile"]
    ''') == ["empty documentation for parameter profile"]


def test_an_empty_entry_still_documents_and_still_duplicates():
    """cparam.py:99: an empty doc still occupies its name."""
    found = _findings('''
        """Objective.

        Parameters:
            profile:
            profile: Which profile to run.
        """
        with test.start() as t:
            p = t.params
            profile = p["profile"]
    ''')
    assert found == [
        "empty documentation for parameter profile",
        "duplicate documentation for parameter profile",
    ]
    assert "undocumented" not in " ".join(found)


def test_env_is_never_reported_stale():
    assert _findings('''
        """Objective.

        Parameters:
            env: Testing environment.
        """
        with test.start() as t:
            pass
    ''') == []


def test_an_indirect_reader_keeps_its_parameter_fresh():
    assert "default_duration" in check.INDIRECT_READERS
    assert _findings('''
        """Objective.

        Parameters:
            duration: How long to run.
        """
        with test.start() as t:
            duration = ts.default_duration(t, "trex_int/throughput")
    ''') == []


def test_every_params_accessor_counts_as_a_read():
    assert _findings('''
        """Objective.

        Parameters:
            a: one
            b: two
            c: three
            d: four
            e: five
            f: six
        """
        with test.start() as t:
            p = t.params
            a = p["a"]
            b = p.get("b")
            c = p.int("c")
            d = p.float("d")
            e = p.bool("e")
            f = p.enum("f", {})
    ''') == []


def test_a_params_read_through_the_attribute_counts():
    assert _findings('''
        """Objective.

        Parameters:
            test_mode: Which load generator the run uses.
        """
        with test.start() as t:
            mode = t.params["test_mode"]
    ''') == []


def test_a_lookup_on_something_else_is_not_a_parameter_read():
    """os.environ.get() and a plain dict are not the Params API.

    Matched receiver-blind, both would be read as parameter reads and
    every real test would report findings it has not earned.
    """
    assert _findings('''
        """Objective.

        Parameters:
            env: Testing environment.
        """
        import os

        with test.start() as t:
            result = {}
            ht = os.environ.get("NAPTS_TREX_HT_THREADS")
            series = result["series"]
    ''') == []


# ------------------------------------------------------------ exit codes


_CLEAN = '''
    """Measure forwarding throughput

    Parameters:
        env: Testing environment.
    """
    with test.start() as t:
        t.step("Run")
'''


def test_a_clean_input_exits_zero(tmp_path, capsys):
    _module(tmp_path, _CLEAN, "throughput")
    assert testsinfo.main([str(tmp_path), "throughput"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "<test name=\"throughput\">" in captured.out


_WITH_FINDING = '''
    """Measure forwarding throughput

    Parameters:
        env: Testing environment.
        profile: Which profile to run.
    """
    with test.start() as t:
        t.step("Run")
'''


def test_a_finding_warns_but_still_writes_the_document(tmp_path, capsys):
    _module(tmp_path, _WITH_FINDING, "throughput")
    assert testsinfo.main([str(tmp_path), "throughput"]) == 0
    captured = capsys.readouterr()
    assert "stale documentation for parameter profile" in captured.err
    assert captured.err.startswith("te_py_tests_info: ")
    assert "<objective>" in captured.out


def test_strict_turns_a_finding_into_a_failure(tmp_path, capsys):
    _module(tmp_path, _WITH_FINDING, "throughput")
    assert testsinfo.main(["--strict", str(tmp_path), "throughput"]) == 1
    captured = capsys.readouterr()
    assert "stale documentation for parameter profile" in captured.err
    assert "<objective>" in captured.out


def test_a_missing_docstring_writes_nothing_at_all(tmp_path, capsys):
    _module(tmp_path, "x = 1\n", "throughput")
    assert testsinfo.main([str(tmp_path), "throughput"]) != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "missing module docstring" in captured.err


def test_a_missing_docstring_is_hard_even_under_strict(tmp_path, capsys):
    _module(tmp_path, "x = 1\n", "throughput")
    assert testsinfo.main(["--strict", str(tmp_path), "throughput"]) != 0
    assert capsys.readouterr().out == ""


def test_a_syntax_error_writes_nothing_at_all(tmp_path, capsys):
    _module(tmp_path, '"""Objective."""\ndef (:\n', "throughput")
    assert testsinfo.main([str(tmp_path), "throughput"]) != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "syntax error" in captured.err


def test_an_unreadable_file_writes_nothing_at_all(tmp_path, capsys):
    assert testsinfo.main([str(tmp_path), "absent"]) != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "absent.py" in captured.err


# ------------------------------------------------------------------- xml


def test_xml_metacharacters_round_trip(tmp_path, capsys):
    _module(tmp_path, '''
        """Compare a & b

        Parameters:
            env: Values are `a & b`, "quoted" and <angled>.
        """
        with test.start() as t:
            t.step("Check a < b & \\"c\\"")
    ''', "escaping")
    assert testsinfo.main([str(tmp_path), "escaping"]) == 0
    root = ET.fromstring(capsys.readouterr().out)
    test_el = root.find("test")
    assert test_el.get("name") == "escaping"
    assert test_el.find("objective").text == "Compare a & b"
    assert test_el.find("param").get("name") == "env"
    assert test_el.find("param").text == (
        'Values are `a & b`, "quoted" and <angled>.')
    assert test_el.find("scenario/step").text == 'Check a < b & "c"'


_WHOLE_SOURCE = '''
    """Measure forwarding throughput

    Runs one of the vendored profiles through the device and reports
    what it carried.

    Parameters:
        env: Testing environment:
            - `env-peer2peer-two_links`
        rate_mult: TRex rate multiplier:
            - `auto`: search for the largest multiplier the path sustains
            - a number: run at that multiplier and measure
        duration: How long to run, in seconds.
    """
    from pyte import test

    with test.start() as t:
        p = t.params
        rate_mult = p["rate_mult"]
        duration = ts.default_duration(t, "trex_int/throughput")

        t.step("Bring the device under test into the requested mode.")
        if rate_mult == "auto":
            t.step("Search for the largest sustained rate multiplier.")
        else:
            t.step("Run at the requested rate multiplier.")
        for port in sorted(ports):
            t.step("Account for one port.")
        t.step("Log statistics in MI format.")
'''

_WHOLE_XML = '''<?xml version="1.0"?>
<tests-info>
  <test name="throughput">
    <objective>Measure forwarding throughput</objective>
    <param name="env">Testing environment:
    - `env-peer2peer-two_links`</param>
    <param name="rate_mult">TRex rate multiplier:
    - `auto`: search for the largest multiplier the path sustains
    - a number: run at that multiplier and measure</param>
    <param name="duration">How long to run, in seconds.</param>
    <scenario>
      <step depth="1">Bring the device under test into the requested \
mode.</step>
      <step depth="1">If rate_mult == 'auto':</step>
      <step depth="2">Search for the largest sustained rate \
multiplier.</step>
      <step depth="1">If not rate_mult == 'auto':</step>
      <step depth="2">Run at the requested rate multiplier.</step>
      <step depth="1">For each port in sorted(ports):</step>
      <step depth="2">Account for one port.</step>
      <step depth="1">Log statistics in MI format.</step>
    </scenario>
  </test>
</tests-info>
'''


def test_a_whole_document_is_rendered_exactly(tmp_path, capsys):
    _module(tmp_path, _WHOLE_SOURCE, "throughput")
    assert testsinfo.main([str(tmp_path), "throughput"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == _WHOLE_XML


def test_a_test_with_no_steps_has_no_scenario_element(tmp_path, capsys):
    _module(tmp_path, '''
        """Objective.

        Parameters:
            env: Testing environment.
        """
        x = 1
    ''', "quiet")
    assert testsinfo.main([str(tmp_path), "quiet"]) == 0
    assert "<scenario>" not in capsys.readouterr().out


def test_several_names_make_one_document(tmp_path, capsys):
    _module(tmp_path, _CLEAN, "one")
    _module(tmp_path, _CLEAN, "two")
    assert testsinfo.main([str(tmp_path), "one", "two"]) == 0
    root = ET.fromstring(capsys.readouterr().out)
    assert [el.get("name") for el in root.findall("test")] == ["one", "two"]


# ----------------------------------------------------------- no-dependency


def test_the_package_imports_only_the_standard_library():
    """It runs at suite build time under a bare python3.

    No virtualenv, no cffi, no compiled _shim: a stray import of the
    rest of pyte here would break every suite's build.
    """
    import ast
    import pathlib
    import sys

    root = pathlib.Path(testsinfo.__file__).parent
    stdlib = set(sys.stdlib_module_names)
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                assert name in stdlib, f"{path.name} imports {name}"
