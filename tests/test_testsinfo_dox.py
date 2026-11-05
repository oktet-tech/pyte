# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for pyte.testsinfo.dox, the doxygen filter."""
import textwrap

from pyte.testsinfo import docstring
from pyte.testsinfo.dox import document, main, render

SRC = '''"""Say hello over the wire

Longer description, first paragraph.

Second paragraph.

Parameters:
    env: Testing environment.
    greeting: Lanes of profile hello.
        Fields:
        - `who`: whom to greet
        - `count`: how often, default 1
"""
from pyte import test

with test.start() as t:
    p = t.params
    t.step("Bind the environment")
    for i in range(3):
        t.step("Greet once")
        if p.get("loud"):
            t.step("Shout")
    t.step("Done")
'''

#: The text column of the greeting example: " * @param " plus the
#: widest name ("greeting") plus one space.
_CONT = " * " + " " * len("@param greeting ")


def _write(tmp_path, source=SRC, name="hello"):
    path = tmp_path / (name + ".py")
    path.write_text(source, encoding="utf-8")
    return str(path)


def _doc(body):
    """A module docstring, dedented, as the parser sees it."""
    return textwrap.dedent(body).strip("\n")


# ------------------------------------------------------------ docstring


def test_description_is_the_paragraphs_before_the_parameters():
    doc = _doc(SRC.split('"""')[1])
    assert docstring.description(doc) == (
        "Longer description, first paragraph.\n\nSecond paragraph.")


def test_description_without_a_parameter_section_runs_to_the_end():
    doc = _doc("""
        Objective line

        Only paragraph,
        on two lines.
    """)
    assert docstring.description(doc) == "Only paragraph,\non two lines."


def test_description_is_empty_when_the_heading_follows_the_objective():
    doc = _doc("""
        Prepare the hosts
        Parameter:
            env: Testing environment.
    """)
    assert docstring.description(doc) == ""


def test_parameters_raw_keeps_the_line_breaks_dedented():
    doc = _doc("""
        Objective

        Parameters:
            env: Testing environment naming every function
                of the layout.
            peer: Lanes. Fields:
                - `a`: first item,
                  wrapped
                - `b`: second
    """)
    assert docstring.parameters_raw(doc) == [
        ("env", ("Testing environment naming every function\n"
                 "of the layout.")),
        ("peer", ("Lanes. Fields:\n- `a`: first item,\n  wrapped\n"
                  "- `b`: second")),
    ]


def test_parameters_raw_keeps_inner_blank_lines_only():
    doc = _doc("""
        Objective

        Parameters:
            env:
                First paragraph.

                Second paragraph.

            other: Text.
    """)
    assert docstring.parameters_raw(doc) == [
        ("env", "First paragraph.\n\nSecond paragraph."),
        ("other", "Text."),
    ]


# --------------------------------------------------------------- render


def test_render_shape(tmp_path):
    out = document(_write(tmp_path), "demo-hello", "demo",
                   "A. Author <a@b.c>")
    lines = out.splitlines()
    assert out.endswith("\n")
    assert lines[0] == "/** @defgroup demo-hello Say hello over the wire"
    assert lines[1] == " * @ingroup demo"
    assert lines[2] == " * @{"
    assert lines[3] == " *"
    assert lines[4] == " * @objective Say hello over the wire"
    assert lines[5:9] == [
        " *",
        " * Longer description, first paragraph.",
        " *",
        " * Second paragraph.",
    ]
    assert lines[9] == " *"
    assert lines[10].startswith(" * @param ")
    assert lines[-3:] == [" */", "", "/** @} */"]


def test_render_params_keep_lists(tmp_path):
    out = document(_write(tmp_path), "demo-hello", "demo")
    lines = out.splitlines()
    assert " * @param env      Testing environment." in lines
    start = lines.index(" * @param greeting Lanes of profile hello.")
    assert lines[start + 1:start + 4] == [
        _CONT + "Fields:",
        _CONT + "- `who`: whom to greet",
        _CONT + "- `count`: how often, default 1",
    ]


def test_render_param_with_a_blank_line_is_a_parblock():
    # A blank line would otherwise end the @param paragraph and drop
    # the rest of the description into the page body.
    out = render("g", "p", "T", "T", "", [("env", "One.\n\nTwo.")], [],
                 None)
    cont = " * " + " " * len("@param env ")
    assert out.splitlines()[6:11] == [
        " * @param env @parblock",
        cont + "One.",
        " *",
        cont + "Two.",
        cont + "@endparblock",
    ]


def test_render_scenario_nests(tmp_path):
    lines = document(_write(tmp_path), "demo-hello", "demo").splitlines()
    idx = lines.index(" * @par Scenario:")
    assert lines[idx - 1] == " *"
    assert lines[idx + 1] == " *    -# Bind the environment"
    # The headings for the loop and the branch are whatever
    # steps.scenario() words them as; only their depth matters here.
    assert lines[idx + 2].startswith(" *    -# ")
    assert lines[idx + 3] == " *       - Greet once"
    assert lines[idx + 4].startswith(" *       - ")
    assert lines[idx + 5] == " *          - Shout"
    assert lines[idx + 6] == " *    -# Done"
    assert lines[idx + 7] == " */"


def test_author_last(tmp_path):
    lines = document(_write(tmp_path), "demo-hello", "demo",
                     "A. Author <a@b.c>").splitlines()
    assert lines[-5] == " *"
    assert lines[-4] == " * @author A. Author <a@b.c>"
    assert lines[-3] == " */"


def test_render_without_optional_sections():
    assert render("g", "p", "Title", "Objective", "", [], [], None) == (
        "/** @defgroup g Title\n"
        " * @ingroup p\n"
        " * @{\n"
        " *\n"
        " * @objective Objective\n"
        " */\n"
        "\n"
        "/** @} */\n")


def test_render_escapes_doxygen_markup_outside_code_spans():
    # <i> would turn the rest of the page italic, @b would be a
    # command; inside backticks doxygen shows them literally.
    out = render("g", "p", "T", "Engine<->agent",
                 "Named <argument>.<i> at `x_<i>`, mail a@b & 100%",
                 [("env", "at <peer>_addr, `#<k>`")],
                 [(1, "If x < 3:")], None)
    lines = out.splitlines()
    assert " * @objective Engine\\<-\\>agent" in lines
    assert (" * Named \\<argument\\>.\\<i\\> at `x_<i>`, "
            "mail a\\@b \\& 100\\%") in lines
    assert " * @param env at \\<peer\\>_addr, `#<k>`" in lines
    assert " *    -# If x \\< 3:" in lines


def test_render_never_opens_or_closes_the_comment():
    out = render("g", "p", "Glob /sys/*/x", "Read /sys/*/x",
                 "See `/sys/class/net/*/device` /* here */",
                 [("env", "a/*b*/c")], [(1, "Read /sys/*/speed")],
                 "A */ B")
    # Only the filter's own comment markers are left.
    assert out.count("/*") == 2 and out.count("*/") == 2
    assert out.splitlines()[0] == "/** @defgroup g Glob /sys/ * /x"
    assert " * See `/sys/class/net/ * /device` / * here * /" in out
    assert " *    -# Read /sys/ * /speed" in out


def test_render_title_is_left_raw():
    # A group title is not parsed for commands: an escape would show.
    out = render("g", "p", "Engine<->agent", "x", "", [], [], None)
    assert out.splitlines()[0] == "/** @defgroup g Engine<->agent"


def test_document_never_imports_the_module(tmp_path):
    source = SRC.replace("from pyte import test",
                         "raise RuntimeError('imported')\n"
                         "from pyte import test")
    out = document(_write(tmp_path, source), "g", "p")
    assert out.startswith("/** @defgroup g Say hello over the wire\n")


# ------------------------------------------------------------------ main


def test_main_warns_and_returns_zero(tmp_path, capsys):
    path = _write(tmp_path, "def x(:\n", "bad")
    assert main(["--group", "g", "--ingroup", "p", path]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"py2dox: warning: {path}: ")


def test_main_warns_on_a_missing_docstring(tmp_path, capsys):
    path = _write(tmp_path, "x = 1\n", "nodoc")
    assert main(["--group", "g", "--ingroup", "p", path]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (f"py2dox: warning: {path}: missing module "
                            f"docstring (test objective)\n")


def test_main_warns_on_a_missing_file(tmp_path, capsys):
    path = str(tmp_path / "absent.py")
    assert main(["--group", "g", "--ingroup", "p", path]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"py2dox: warning: {path}: ")


def test_main_prints(tmp_path, capsys):
    path = _write(tmp_path)
    assert main(["--group", "demo-hello", "--ingroup", "demo",
                 "--author", "A. Author <a@b.c>", path]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == document(path, "demo-hello", "demo",
                                    "A. Author <a@b.c>")
    assert captured.out.startswith("/** @defgroup demo-hello ")
