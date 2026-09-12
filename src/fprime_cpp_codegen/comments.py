"""Comment, banner, and access-tag rendering.

Doxygen ``//!`` comments above declarations, ``//!<`` post comments hanging off
parameters, and ruled banners separating sections.

Every ``comment`` argument here takes a :data:`~fprime_cpp_codegen.doc.Comment`: a
string, which is margin-stripped, or ready-made lines, which are not.
"""

from __future__ import annotations

import re

from .doc import Comment, FileBanner
from .lines import (
    INDENT_INCREMENT,
    IndentMode,
    Line,
    blank,
    indent_lines,
    join,
    join_lists,
    line,
    lines,
)

__all__ = [
    "BANNER_RULE",
    "add_comment_prefix",
    "add_param_comment",
    "comment_lines",
    "is_directive",
    "left_align_directive",
    "write_access_tag",
    "write_banner",
    "write_banner_comment",
    "write_comment",
    "write_comment_body",
    "write_doxygen_comment",
    "write_doxygen_comment_opt",
    "write_doxygen_post_comment",
    "write_doxygen_post_comment_opt",
    "write_function_body",
]

#: The horizontal rule that delimits a banner comment.
BANNER_RULE = (
    "// ----------------------------------------------------------------------"
)


def comment_lines(comment: Comment) -> list[Line]:
    """Coerce comment text to lines.

    A string is margin-stripped and split; anything else is already lines and is
    taken exactly as it is, which is how a caller escapes margin stripping for text
    it derived from its own input.
    """
    return lines(comment) if isinstance(comment, str) else list(comment)


def add_comment_prefix(prefix: str, l: Line) -> Line:
    """Prefix a comment line.

    A blank line inside a multi-line comment becomes a bare ``//!``, with no trailing
    space.
    """
    if not l.string:
        return line(prefix)
    return join(" ", line(prefix), l)


def write_comment_body(comment: Comment) -> list[Line]:
    """Render ``comment`` as ``//`` lines, with no leading blank."""
    return [add_comment_prefix("//", l) for l in comment_lines(comment)]


def write_comment(comment: Comment) -> list[Line]:
    """Render ``comment`` as ``//`` lines, preceded by a blank line."""
    return [blank(), *write_comment_body(comment)]


def write_banner_comment(comment: Comment) -> list[Line]:
    """Render ``comment`` as a ruled banner, preceded by a blank line."""
    rule = line(BANNER_RULE)
    return [blank(), rule, *write_comment_body(comment), rule]


def write_doxygen_comment(comment: Comment) -> list[Line]:
    """Render ``comment`` as ``//!`` lines, preceded by a blank line."""
    return [blank(), *(add_comment_prefix("//!", l) for l in comment_lines(comment))]


def write_doxygen_comment_opt(comment: Comment | None) -> list[Line]:
    """Render an optional doxygen comment.

    ``None`` yields a single blank line, keeping declarations separated whether or not
    they are documented.
    """
    return write_doxygen_comment(comment) if comment is not None else [blank()]


def write_doxygen_post_comment(comment: Comment) -> list[Line]:
    """Render ``comment`` as ``//!<`` lines, with no leading blank."""
    return [add_comment_prefix("//!<", l) for l in comment_lines(comment)]


def write_doxygen_post_comment_opt(comment: Comment | None) -> list[Line]:
    """Render an optional doxygen post comment, or a single blank line."""
    return write_doxygen_post_comment(comment) if comment is not None else [blank()]


def add_param_comment(s: str, comment: Comment | None) -> list[Line]:
    """Hang a doxygen post-comment off the end of ``s``.

    Continuation lines are indented to the column the comment starts at, stacking
    under its first line.  Used for parameters and enumerated constants.
    """
    if comment is None:
        return lines(s)
    return join_lists(
        IndentMode.INDENT, lines(s), " ", write_doxygen_post_comment(comment)
    )


def write_access_tag(tag: str) -> list[Line]:
    """Render an access-specifier label such as ``public:``.

    Shifted out by two spaces to sit half a level left of the members it governs,
    which are indented two levels into the class body.
    """
    return [blank(), line(f"{tag}:").indent_out(2)]


#: The preprocessor directives :func:`is_directive` recognises.  ``import`` and
#: ``embed`` are not C++14, but a generator emitting them still wants them aligned.
DIRECTIVE_KEYWORDS = frozenset(
    {
        "define",
        "elif",
        "elifdef",
        "elifndef",
        "else",
        "embed",
        "endif",
        "error",
        "if",
        "ifdef",
        "ifndef",
        "import",
        "include",
        "include_next",
        "line",
        "pragma",
        "undef",
        "warning",
    }
)

_DIRECTIVE = re.compile(r"#[ \t]*([A-Za-z_]\w*)")


def is_directive(s: str) -> bool:
    """Whether ``s`` opens with a recognised preprocessor directive.

    Deliberately narrow: a line merely starting with ``#`` is not enough, because
    ``#`` also opens a heading in the Markdown or reStructuredText a generator may be
    embedding in a C++ string literal.  An unrecognised word after the ``#`` -- and so
    anything that would not compile as a directive anyway -- is treated as content.
    """
    m = _DIRECTIVE.match(s)
    return m is not None and m.group(1) in DIRECTIVE_KEYWORDS


def left_align_directive(l: Line) -> Line:
    """Force a preprocessor directive to column zero by discarding its indentation.

    Only lines :func:`is_directive` recognises are moved, so indented content that
    happens to begin with ``#`` is left alone.  A directive that must keep its indent
    -- one inside a string literal, say -- escapes by carrying the indentation in
    :attr:`Line.string` instead of in :attr:`Line.indent`.
    """
    return Line(l.string) if is_directive(l.string) else l


def write_banner(
    banner: FileBanner,
    file_name: str,
    generic_description: str,
) -> list[Line]:
    """Render the ``\\title``/``\\author``/``\\brief`` block atop a file."""
    return lines(
        f"""|// ======================================================================
            |// \\title  {banner.title(file_name)}
            |// \\author {banner.author(file_name)}
            |// \\brief  {banner.description(file_name, generic_description)}
            |// ======================================================================"""
    )


def write_function_body(body: list[Line]) -> list[Line]:
    """Wrap ``body`` in braces, indenting it one level.

    An empty body renders as braces around a single blank line.
    """
    inner = indent_lines(body, INDENT_INCREMENT) if body else [blank()]
    return [line("{"), *inner, line("}")]
