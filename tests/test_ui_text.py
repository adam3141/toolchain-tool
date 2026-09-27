from toolchain_tool.app import safe_name
from toolchain_tool.ui import LineEditor, fit, truncate, wrap


def test_truncate_and_fit():
    assert truncate("Cool Python Container", 20) == "Cool Python Conta..."
    assert truncate("abcdef", 2) == "ab"
    assert fit("ab", 4) == "ab  "
    assert fit("24MB", 8, "right") == "    24MB"


def test_wrap_keeps_paragraphs():
    assert wrap("one two\nthree", 20) == ["one two", "three"]
    assert wrap("", 5) == [""]


def test_line_editor():
    ed = LineEditor("-O2")
    ed.insert(" -g")
    assert ed.text == "-O2 -g"
    ed.home()
    ed.delete()
    assert ed.text == "O2 -g"
    ed.end()
    ed.backspace()
    ed.move(-10)
    ed.insert("-")
    assert (ed.text, ed.pos) == ("-O2 -", 1)
    ed.kill_to_end()
    assert ed.text == "-"


def test_line_editor_window_follows_cursor():
    ed = LineEditor("abcdefghij")
    assert ed.window(4) == ("hij", 3)
    ed.home()
    assert ed.window(4) == ("abcd", 0)


def test_safe_name():
    assert safe_name("gcc 16 / fortran") == "gcc-16-fortran"
    assert safe_name("../..") == "profile"
