"""The immutable line model and the line algebra built on top of it.

A generated C++ file is a ``list[Line]``.  A :class:`Line` carries its indentation
separately from its text, so a continuation line can be aligned to an arbitrary
column of the line before it and a blank line renders empty rather than as trailing
whitespace.

Every function here is pure, and none of them know anything about C++.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

__all__ = [
    "INDENT_INCREMENT",
    "IndentMode",
    "Line",
    "add_blank_postfix",
    "add_blank_prefix",
    "add_postfix_line",
    "add_prefix",
    "add_prefix_and_suffix",
    "add_prefix_indent",
    "add_prefix_line",
    "add_separators",
    "add_suffix",
    "blank",
    "blank_separated",
    "flatten",
    "flatten_with_prefix_line",
    "indent_lines",
    "intersperse",
    "intersperse_blank_lines",
    "join",
    "join_lists",
    "line",
    "lines",
    "lines_opt",
    "render",
    "strip_margin",
    "wrap_in_scope",
]

_T = TypeVar("_T")

#: The number of spaces one level of indentation adds.
INDENT_INCREMENT = 2


class IndentMode(Enum):
    """How :func:`join_lists` treats the tail of the second list of lines.

    ``INDENT`` re-indents the tail to line up under the join column, aligning a
    doxygen post-comment beneath its parameter.  ``NO_INDENT`` leaves the tail where
    it is, for gluing a suffix such as ``;`` onto a multi-line signature.
    """

    INDENT = "indent"
    NO_INDENT = "no-indent"


@dataclass(frozen=True)
class Line:
    """A single line of output: some text plus the column it starts at.

    ``indent`` is a raw space count and may go negative, which renders as no indent.
    Access tags rely on that, being emitted at the class-body indent then shifted out
    by two.
    """

    string: str = ""
    indent: int = 0

    def __str__(self) -> str:
        """Render the line.  An empty line renders empty, never as whitespace."""
        if not self.string:
            return ""
        return " " * self.indent + self.string

    def indent_in(self, n: int = INDENT_INCREMENT) -> Line:
        """Return this line indented in by ``n`` spaces."""
        return Line(self.string, self.indent + n)

    def indent_out(self, n: int = INDENT_INCREMENT) -> Line:
        """Return this line indented out by ``n`` spaces."""
        return Line(self.string, self.indent - n)

    def indent_to(self, n: int) -> Line:
        """Return this line at the absolute indent ``n``."""
        return Line(self.string, n)

    @property
    def size(self) -> int:
        """The rendered width of the line, indentation included, newline excluded.

        The column :func:`join_lists` aligns against.  Computed from the raw indent,
        so a negative indent shrinks it.
        """
        return self.indent + len(self.string)


def line(s: str) -> Line:
    """Construct a single unindented line."""
    return Line(s)


def blank() -> Line:
    """Construct a blank line."""
    return Line()


def strip_margin(s: str, margin: str = "|") -> str:
    """Strip a leading margin from every line of ``s``.

    For each line, leading whitespace and control characters are skipped; if the next
    character is ``margin``, it and everything before it are dropped.  A line with no
    margin marker is left untouched, including its leading whitespace -- so
    ``"x = a | b;"`` survives intact.

    Only the first marker on a line is removed, so doubling it escapes it: a line of
    text that really does start with ``|`` is written ``"||x"``.  Text derived from a
    generator's input is better passed through :func:`lines` with ``margin=None``,
    which does not strip at all.
    """
    out: list[str] = []
    for part in s.split("\n"):
        i = 0
        n = len(part)
        while i < n and part[i] <= " ":
            i += 1
        if i < n and part[i] == margin:
            out.append(part[i + 1 :])
        else:
            out.append(part)
    return "\n".join(out)


def _split_lines(s: str) -> list[str]:
    """Split ``s`` on newlines, discarding trailing empty fields.

    A string ending in a newline yields no spurious blank line, but the empty string
    still yields one empty field.  Interior blank lines are preserved.
    """
    if s == "":
        return [""]
    parts = s.split("\n")
    while parts and parts[-1] == "":
        parts.pop()
    return parts


def lines(s: str, *, margin: str | None = "|") -> list[Line]:
    """Convert a (possibly margin-stripped, possibly multi-line) string to lines.

    ``lines("\\n|#ifndef X\\n|#define X")`` yields a leading blank line followed by the
    two directives.

    ``margin=None`` disables :func:`strip_margin` entirely, which is what text coming
    from a generator's input wants: an annotation or an expression beginning with the
    margin character survives intact rather than losing its first character.
    """
    stripped = s if margin is None else strip_margin(s, margin)
    return [Line(part) for part in _split_lines(stripped)]


def lines_opt(f: Callable[[_T], list[Line]], value: _T | None) -> list[Line]:
    """Apply ``f`` to ``value`` if it is not ``None``, else return no lines."""
    return [] if value is None else f(value)


def indent_lines(ll: Iterable[Line], n: int = INDENT_INCREMENT) -> list[Line]:
    """Indent every line in ``ll`` in by ``n`` spaces."""
    return [l.indent_in(n) for l in ll]


def join(sep: str, l1: Line, l2: Line) -> Line:
    """Concatenate two lines' text with ``sep``, keeping the first line's indent."""
    return Line(l1.string + sep + l2.string, l1.indent)


def join_lists(
    mode: IndentMode,
    lines1: Sequence[Line],
    sep: str,
    lines2: Sequence[Line],
) -> list[Line]:
    """Glue two blocks of lines together at their seam.

    The last line of ``lines1`` and the first of ``lines2`` merge into one line joined
    by ``sep``.  Under :attr:`IndentMode.INDENT` the remaining lines of ``lines2`` are
    indented by the width of that seam, so they hang under the join column.  Either
    block being empty short-circuits to the other.
    """
    if not lines2:
        return list(lines1)
    if not lines1:
        return list(lines2)
    head1, last1 = list(lines1[:-1]), lines1[-1]
    first2, rest2 = lines2[0], list(lines2[1:])
    joined = join(sep, last1, first2)
    if mode is IndentMode.INDENT:
        rest2 = indent_lines(rest2, last1.size + len(sep))
    return head1 + [joined] + rest2


def add_prefix(prefix: str, ll: Sequence[Line]) -> list[Line]:
    """Prepend ``prefix`` to the first line of ``ll``, without re-indenting."""
    return join_lists(IndentMode.NO_INDENT, [Line(prefix)], "", ll)


def add_prefix_indent(prefix: str, ll: Sequence[Line]) -> list[Line]:
    """Prepend ``prefix`` to the first line of ``ll``, hanging the rest under it."""
    return join_lists(IndentMode.INDENT, [Line(prefix)], "", ll)


def add_suffix(ll: Sequence[Line], suffix: str) -> list[Line]:
    """Append ``suffix`` to the last line of ``ll``."""
    return join_lists(IndentMode.NO_INDENT, ll, "", [Line(suffix)])


def add_prefix_and_suffix(prefix: str, ll: Sequence[Line], suffix: str) -> list[Line]:
    """Append ``suffix`` to the last line and prepend ``prefix`` to the first."""
    return add_prefix(prefix, add_suffix(ll, suffix))


def add_prefix_line(prefix: Line, ll: Sequence[Line]) -> list[Line]:
    """Prepend ``prefix`` as its own line, but only if ``ll`` is non-empty."""
    return [prefix, *ll] if ll else []


def add_postfix_line(postfix: Line, ll: Sequence[Line]) -> list[Line]:
    """Append ``postfix`` as its own line, but only if ``ll`` is non-empty."""
    return [*ll, postfix] if ll else []


def add_blank_prefix(ll: Sequence[Line]) -> list[Line]:
    """Prepend a blank line, but only if ``ll`` is non-empty."""
    return add_prefix_line(blank(), ll)


def add_blank_postfix(ll: Sequence[Line]) -> list[Line]:
    """Append a blank line, but only if ``ll`` is non-empty."""
    return add_postfix_line(blank(), ll)


def flatten(sep: str, ll: Sequence[Line]) -> Line:
    """Collapse ``ll`` into a single line, joining the text with ``sep``."""
    if not ll:
        return blank()
    result = ll[-1]
    for l in reversed(ll[:-1]):
        result = join(sep, l, result)
    return result


def flatten_with_prefix_line(prefix: Line, lll: Iterable[Sequence[Line]]) -> list[Line]:
    """Flatten a list of blocks, prefixing each non-empty block with ``prefix``."""
    out: list[Line] = []
    for ll in lll:
        out.extend(add_prefix_line(prefix, ll))
    return out


def blank_separated(f: Callable[[_T], list[Line]], items: Sequence[_T]) -> list[Line]:
    """Map ``f`` over ``items`` and separate the results with single blank lines.

    Empty results still contribute a separator; :func:`intersperse_blank_lines` drops
    them.
    """
    out: list[Line] = []
    for i, item in enumerate(items):
        if i:
            out.append(blank())
        out.extend(f(item))
    return out


def intersperse(items: Sequence[_T], element: _T) -> list[_T]:
    """Insert ``element`` between every pair of adjacent items."""
    if len(items) <= 1:
        return list(items)
    out: list[_T] = [items[0]]
    for item in items[1:]:
        out.append(element)
        out.append(item)
    return out


def intersperse_blank_lines(lll: Iterable[Sequence[Line]]) -> list[Line]:
    """Flatten a list of blocks with one blank line between them, dropping empty
    blocks so they do not produce doubled blanks."""
    blocks = [list(ll) for ll in lll if ll]
    out: list[Line] = []
    for i, block in enumerate(blocks):
        if i:
            out.append(blank())
        out.extend(block)
    return out


def add_separators(sep: str, ll: Sequence[Line]) -> list[Line]:
    """Append ``sep`` to every line except the last.  Useful for comma lists."""
    last = len(ll) - 1
    return [Line(l.string + sep, l.indent) if i < last else l for i, l in enumerate(ll)]


def wrap_in_scope(
    opening: str,
    body: Sequence[Line],
    closing: str,
    *,
    keep_empty: bool = False,
) -> list[Line]:
    """Indent ``body`` one level between an ``opening`` and ``closing`` line.

    An empty body yields nothing unless ``keep_empty`` is set, so a conditional block
    with no content disappears instead of leaving empty braces.
    """
    if not body and not keep_empty:
        return []
    return [*lines(opening), *indent_lines(body), *lines(closing)]


def render(ll: Iterable[Line]) -> str:
    """Render lines to file text, newline-separated and newline-terminated."""
    items = list(ll)
    if not items:
        return ""
    return "\n".join(str(l) for l in items) + "\n"
