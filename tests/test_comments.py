"""Tests for comment, banner, and access-tag rendering."""

from __future__ import annotations

import pytest

from fprime_cpp_codegen.comments import (
    BANNER_RULE,
    add_comment_prefix,
    add_param_comment,
    comment_lines,
    is_directive,
    left_align_directive,
    write_access_tag,
    write_banner,
    write_banner_comment,
    write_comment,
    write_comment_body,
    write_doxygen_comment,
    write_doxygen_comment_opt,
    write_doxygen_post_comment,
    write_doxygen_post_comment_opt,
    write_function_body,
)
from fprime_cpp_codegen.doc import DefaultFileBanner
from fprime_cpp_codegen.lines import Line, line, lines


def strings(ll: list[Line]) -> list[str]:
    return [str(l) for l in ll]


class TestCommentPrefixes:
    def test_prefix_is_separated_by_a_space(self) -> None:
        assert add_comment_prefix("//!", line("hello")) == Line("//! hello")

    def test_blank_line_gets_a_bare_marker_with_no_trailing_space(self) -> None:
        assert add_comment_prefix("//!", Line("")) == Line("//!")

    def test_prefix_takes_the_prefix_indent_not_the_line_indent(self) -> None:
        assert add_comment_prefix("//", Line("x", 8)).indent == 0


class TestCommentBodies:
    def test_comment_body_has_no_leading_blank(self) -> None:
        assert strings(write_comment_body("a\nb")) == ["// a", "// b"]

    def test_comment_has_a_leading_blank(self) -> None:
        assert strings(write_comment("a")) == ["", "// a"]

    def test_banner_comment_is_ruled_above_and_below(self) -> None:
        assert strings(write_banner_comment("Section")) == [
            "",
            BANNER_RULE,
            "// Section",
            BANNER_RULE,
        ]

    def test_doxygen_comment_has_a_leading_blank(self) -> None:
        assert strings(write_doxygen_comment("a\nb")) == ["", "//! a", "//! b"]

    def test_blank_line_inside_a_doxygen_comment(self) -> None:
        assert strings(write_doxygen_comment("a\n\nc")) == ["", "//! a", "//!", "//! c"]

    def test_doxygen_post_comment_has_no_leading_blank(self) -> None:
        assert strings(write_doxygen_post_comment("a")) == ["//!< a"]

    def test_absent_comment_still_yields_a_separating_blank(self) -> None:
        # This is what keeps undocumented class members from running together.
        assert write_doxygen_comment_opt(None) == [Line("")]
        assert write_doxygen_post_comment_opt(None) == [Line("")]

    def test_present_comment_delegates(self) -> None:
        assert write_doxygen_comment_opt("a") == write_doxygen_comment("a")
        assert write_doxygen_post_comment_opt("a") == write_doxygen_post_comment("a")


class TestParamComment:
    def test_no_comment_leaves_the_text_alone(self) -> None:
        assert add_param_comment("U32 x,", None) == [Line("U32 x,")]

    def test_comment_is_appended_after_a_space(self) -> None:
        assert strings(add_param_comment("U32 x,", "the x")) == ["U32 x, //!< the x"]

    def test_continuation_lines_align_under_the_first_marker(self) -> None:
        result = add_param_comment("U32 x,", "one\ntwo")
        assert strings(result) == ["U32 x, //!< one", "       //!< two"]


class TestAccessTag:
    def test_access_tag_is_blank_then_label_shifted_out(self) -> None:
        result = write_access_tag("public")
        assert result == [Line(""), Line("public:", -2)]

    def test_access_tag_sits_left_of_the_members_it_governs(self) -> None:
        # Class members are indented 4; the tag lands at 4 - 2 = 2.
        tag = write_access_tag("private")[1].indent_in(4)
        assert str(tag) == "  private:"


class TestDirectives:
    def test_directive_loses_its_indentation(self) -> None:
        assert left_align_directive(Line("#endif", 8)) == Line("#endif")

    def test_ordinary_line_keeps_its_indentation(self) -> None:
        assert left_align_directive(Line("x();", 8)) == Line("x();", 8)

    @pytest.mark.parametrize(
        "text",
        [
            "#include <cstdio>",
            '#include "A.hpp"',
            "#ifndef A_HPP",
            "#define A_HPP",
            "#endif",
            "#pragma once",
            "# include <cstdio>",
            "#\tif 0",
        ],
    )
    def test_recognised_directives(self, text: str) -> None:
        assert is_directive(text)
        assert left_align_directive(Line(text, 8)).indent == 0

    @pytest.mark.parametrize(
        "text",
        [
            # A markdown heading in a docstring being bound to C++, which used to be
            # silently re-indented along with the real directives.
            "# Heading",
            "## Sub-heading",
            "#1 in the charts",
            "#",
            "# TODO",
            "x #include y",
            "",
        ],
    )
    def test_content_that_merely_starts_with_a_hash(self, text: str) -> None:
        assert not is_directive(text)
        assert left_align_directive(Line(text, 8)) == Line(text, 8)

    def test_indentation_carried_in_the_string_is_the_escape(self) -> None:
        # A real directive that must keep its column puts the column in the text.
        assert left_align_directive(Line("    #include <x>")) == Line(
            "    #include <x>"
        )


class TestCommentsFromLines:
    """Every ``comment=`` also takes ready-made lines, which are not margin-stripped."""

    def test_a_string_is_margin_stripped(self) -> None:
        assert strings(write_doxygen_comment("|a")) == ["", "//! a"]

    def test_lines_are_taken_exactly_as_they_are(self) -> None:
        assert strings(write_doxygen_comment([Line("|a")])) == ["", "//! |a"]

    def test_lines_bypass_stripping_in_a_post_comment(self) -> None:
        assert strings(write_doxygen_post_comment([Line("|x")])) == ["//!< |x"]

    def test_lines_bypass_stripping_in_a_plain_comment(self) -> None:
        assert strings(write_comment_body([Line("|x"), Line("|y")])) == [
            "// |x",
            "// |y",
        ]

    def test_lines_bypass_stripping_in_a_banner(self) -> None:
        assert strings(write_banner_comment([Line("|x")]))[2] == "// |x"

    def test_lines_bypass_stripping_in_a_param_comment(self) -> None:
        assert strings(add_param_comment("U32 x,", [Line("|c")])) == ["U32 x, //!< |c"]

    def test_comment_lines_coerces_both_shapes(self) -> None:
        assert comment_lines("a\nb") == [Line("a"), Line("b")]
        assert comment_lines((Line("a"),)) == [Line("a")]

    def test_multi_line_derived_text_keeps_every_marker(self) -> None:
        derived = lines("|a\n|b", margin=None)
        assert strings(write_doxygen_comment(derived)) == ["", "//! |a", "//! |b"]


class TestBanner:
    def test_banner_shape(self) -> None:
        result = strings(
            write_banner(DefaultFileBanner("mytool"), "A.hpp", "hpp file for a")
        )
        assert result[0].startswith("// ====")
        assert result[1] == "// \\title  A.hpp"
        assert result[2] == "// \\author Generated by mytool"
        assert result[3] == "// \\brief  hpp file for a"
        assert result[4].startswith("// ====")

    def test_default_tool_name(self) -> None:
        assert DefaultFileBanner().author("A.hpp") == "Generated by fpp tools"

    def test_custom_banner_is_honoured(self) -> None:
        class Mine:
            def title(self, file_name: str) -> str:
                return "T"

            def author(self, file_name: str) -> str:
                return "A"

            def description(self, file_name: str, generic_description: str) -> str:
                return "D"

        assert strings(write_banner(Mine(), "x", "y"))[1:4] == [
            "// \\title  T",
            "// \\author A",
            "// \\brief  D",
        ]


class TestFunctionBody:
    def test_body_is_indented_inside_braces(self) -> None:
        assert strings(write_function_body([line("a();"), line("b();")])) == [
            "{",
            "  a();",
            "  b();",
            "}",
        ]

    def test_empty_body_is_braces_around_a_blank_line(self) -> None:
        assert strings(write_function_body([])) == ["{", "", "}"]
