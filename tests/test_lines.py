"""Tests for the line model and line algebra."""

from __future__ import annotations

from fprime_cpp_codegen.lines import (
    IndentMode,
    Line,
    add_blank_prefix,
    add_postfix_line,
    add_prefix,
    add_prefix_indent,
    add_prefix_line,
    add_separators,
    add_suffix,
    blank,
    blank_separated,
    flatten,
    flatten_with_prefix_line,
    indent_lines,
    intersperse,
    intersperse_blank_lines,
    join,
    join_lists,
    line,
    lines,
    lines_opt,
    render,
    strip_margin,
)


def strings(ll: list[Line]) -> list[str]:
    return [str(l) for l in ll]


class TestLine:
    def test_blank_line_renders_empty_not_whitespace(self) -> None:
        assert str(Line("", 8)) == ""

    def test_indent_renders_as_spaces(self) -> None:
        assert str(Line("x", 4)) == "    x"

    def test_negative_indent_renders_flush_left(self) -> None:
        # Access tags rely on this: they are shifted out past column zero.
        assert str(Line("public:", -2)) == "public:"

    def test_size_counts_indent_and_text(self) -> None:
        assert Line("abc", 4).size == 7

    def test_size_keeps_negative_indent(self) -> None:
        assert Line("abc", -2).size == 1

    def test_indent_helpers_are_relative_and_absolute(self) -> None:
        l = Line("x", 4)
        assert l.indent_in(3).indent == 7
        assert l.indent_out(3).indent == 1
        assert l.indent_to(9).indent == 9
        assert l.indent_in().indent == 6  # default increment

    def test_lines_are_immutable_values(self) -> None:
        assert Line("x", 2) == Line("x", 2)
        assert Line("x", 2) != Line("x", 3)


class TestStripMargin:
    def test_strips_whitespace_then_marker(self) -> None:
        assert strip_margin("   |foo") == "foo"

    def test_strips_tab_then_marker(self) -> None:
        assert strip_margin("\t|foo") == "foo"

    def test_leaves_unmarked_line_untouched_including_indent(self) -> None:
        assert strip_margin("   foo") == "   foo"

    def test_leaves_interior_pipe_alone(self) -> None:
        # Splitting on the first pipe anywhere would corrupt a bitwise expression.
        assert strip_margin("if (a | b) {") == "if (a | b) {"
        assert strip_margin("x = a|b;") == "x = a|b;"

    def test_handles_each_line_independently(self) -> None:
        assert strip_margin("a | b\n  |c") == "a | b\nc"

    def test_empty_line_survives(self) -> None:
        assert strip_margin("a\n\nb") == "a\n\nb"

    def test_marker_only_line_becomes_empty(self) -> None:
        assert strip_margin("  |") == ""

    def test_only_the_first_marker_goes_so_doubling_it_escapes(self) -> None:
        assert strip_margin("||x") == "|x"

    def test_the_marker_is_configurable(self) -> None:
        assert strip_margin("  #x", margin="#") == "x"
        assert strip_margin("  |x", margin="#") == "  |x"


class TestLinesMargin:
    """Text a generator derives from its input must survive a leading marker."""

    def test_stripping_is_on_by_default(self) -> None:
        assert lines("|x") == [Line("x")]

    def test_margin_none_strips_nothing(self) -> None:
        assert lines("|x") == [Line("x")]
        assert lines("|x", margin=None) == [Line("|x")]

    def test_margin_none_keeps_leading_whitespace_too(self) -> None:
        assert lines("  |x", margin=None) == [Line("  |x")]

    def test_margin_none_still_splits_on_newlines(self) -> None:
        assert lines("|a\n|b", margin=None) == [Line("|a"), Line("|b")]

    def test_the_marker_is_configurable(self) -> None:
        assert lines("#x", margin="#") == [Line("x")]


class TestLines:
    def test_leading_newline_yields_leading_blank(self) -> None:
        assert strings(lines("\n|#ifndef X\n|#define X")) == [
            "",
            "#ifndef X",
            "#define X",
        ]

    def test_trailing_newline_does_not_yield_trailing_blank(self) -> None:
        # A trailing margin marker is an artifact of formatting the literal, not
        # a request for an extra blank line.
        assert strings(lines("a\n|b\n|")) == ["a", "b"]

    def test_interior_blank_is_preserved(self) -> None:
        assert strings(lines("a\n\nb")) == ["a", "", "b"]

    def test_empty_string_is_one_blank_line(self) -> None:
        assert lines("") == [Line("")]

    def test_produces_unindented_lines(self) -> None:
        assert all(l.indent == 0 for l in lines("  |a\n  |b"))

    def test_lines_opt(self) -> None:
        assert lines_opt(lines, None) == []
        assert lines_opt(lines, "a") == [Line("a")]


class TestJoin:
    def test_join_keeps_first_indent(self) -> None:
        assert join(" ", Line("a", 4), Line("b", 9)) == Line("a b", 4)

    def test_join_lists_short_circuits_on_empty(self) -> None:
        ll = [Line("a")]
        assert join_lists(IndentMode.INDENT, ll, ",", []) == ll
        assert join_lists(IndentMode.INDENT, [], ",", ll) == ll
        assert join_lists(IndentMode.INDENT, [], ",", []) == []

    def test_join_lists_no_indent_leaves_tail_where_it_is(self) -> None:
        result = join_lists(
            IndentMode.NO_INDENT, [Line("abc")], " ", [Line("x"), Line("y")]
        )
        assert strings(result) == ["abc x", "y"]

    def test_join_lists_indent_hangs_tail_under_the_seam(self) -> None:
        # "abc" is 3 wide, the separator adds 1, so the tail lands at column 4.
        result = join_lists(
            IndentMode.INDENT, [Line("abc")], " ", [Line("x"), Line("y")]
        )
        assert strings(result) == ["abc x", "    y"]

    def test_join_lists_indent_accumulates_onto_existing_indent(self) -> None:
        # The seam sits at column 4 ("ab" indented by 2), and the tail's own
        # indent of 1 is added on top rather than replaced.
        result = join_lists(
            IndentMode.INDENT, [Line("ab", 2)], "", [Line("x"), Line("y", 1)]
        )
        assert strings(result) == ["  abx", "     y"]

    def test_join_lists_only_merges_at_the_seam(self) -> None:
        result = join_lists(
            IndentMode.NO_INDENT, [Line("a"), Line("b")], "+", [Line("c"), Line("d")]
        )
        assert strings(result) == ["a", "b+c", "d"]


class TestAffixes:
    def test_add_prefix_merges_into_first_line(self) -> None:
        assert strings(add_prefix("void ", [Line("f()"), Line("{")])) == [
            "void f()",
            "{",
        ]

    def test_add_suffix_merges_into_last_line(self) -> None:
        assert strings(add_suffix([Line("f("), Line(")")], ";")) == ["f(", ");"]

    def test_add_prefix_indent_hangs_the_rest(self) -> None:
        assert strings(add_prefix_indent("f(", [Line("a"), Line("b")])) == [
            "f(a",
            "  b",
        ]

    def test_prefix_and_postfix_lines_skip_empty_bodies(self) -> None:
        assert add_prefix_line(blank(), []) == []
        assert add_postfix_line(blank(), []) == []
        assert add_blank_prefix([Line("a")]) == [Line(""), Line("a")]


class TestCombinators:
    def test_flatten_joins_all_text_keeping_first_indent(self) -> None:
        assert flatten(", ", [Line("a", 4), Line("b"), Line("c")]) == Line("a, b, c", 4)

    def test_flatten_of_nothing_is_blank(self) -> None:
        assert flatten(",", []) == Line("")

    def test_flatten_with_prefix_line_skips_empty_blocks(self) -> None:
        result = flatten_with_prefix_line(blank(), [[Line("a")], [], [Line("b")]])
        assert strings(result) == ["", "a", "", "b"]

    def test_blank_separated_keeps_separators_for_empty_results(self) -> None:
        assert strings(
            blank_separated(lambda s: [Line(s)] if s else [], ["a", "", "b"])
        ) == [
            "a",
            "",
            "",
            "b",
        ]

    def test_intersperse_blank_lines_drops_empty_blocks(self) -> None:
        result = intersperse_blank_lines([[Line("a")], [], [Line("b")]])
        assert strings(result) == ["a", "", "b"]

    def test_intersperse_blank_lines_of_nothing(self) -> None:
        assert intersperse_blank_lines([[], []]) == []

    def test_intersperse_puts_the_element_between_every_pair(self) -> None:
        assert intersperse([1, 2, 3], 0) == [1, 0, 2, 0, 3]
        assert intersperse([1], 0) == [1]
        assert intersperse([], 0) == []

    def test_add_separators_skips_the_last_line(self) -> None:
        assert strings(add_separators(",", [Line("a"), Line("b"), Line("c")])) == [
            "a,",
            "b,",
            "c",
        ]

    def test_add_separators_preserves_indent(self) -> None:
        assert add_separators(",", [Line("a", 4), Line("b", 4)])[0] == Line("a,", 4)

    def test_indent_lines(self) -> None:
        assert indent_lines([Line("a"), Line("b", 2)], 4) == [
            Line("a", 4),
            Line("b", 6),
        ]


class TestRender:
    def test_render_terminates_with_a_newline(self) -> None:
        assert render([line("a"), line("b")]) == "a\nb\n"

    def test_render_of_nothing_is_empty(self) -> None:
        assert render([]) == ""

    def test_render_emits_blank_lines_without_trailing_space(self) -> None:
        assert render([Line("a", 4), Line("", 4), Line("b", 4)]) == "    a\n\n    b\n"
