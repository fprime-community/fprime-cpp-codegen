"""Building function bodies out of C++ statements.

A :class:`Body` accumulates lines.  Statements append to it; control-flow scopes
are context managers that indent everything written inside them::

    body = Body()
    body.line("U32 total = 0;")
    with body.for_("U32 i = 0", "i < n", "i++"):
        body.line("total += m_data[i];")
    body.line("return total;")

A ``Body`` is a value: build one anywhere, return it from a helper, and splice it
in with :meth:`Body.extend`.

This class covers structure -- scopes, nesting, control flow.  Individual
statements go through :meth:`Body.line`.  :meth:`Body.raw` takes lines from
elsewhere, such as :func:`fprime_cpp_codegen.fprime.write_assert`.

Scopes emit even when their body turns out empty, since a vanishing ``if`` would
re-point the ``else`` that follows it.  Pass ``omit_if_empty=True`` to let the scope
disappear.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from typing import TypeAlias

from .comments import (
    write_banner_comment,
    write_comment,
    write_comment_body,
    write_doxygen_comment,
)
from .doc import Comment
from .errors import ScopeError, ValidationError
from .lines import Line, blank, indent_lines
from .lines import line as _line
from .lines import lines as _lines
from .lines import render as _render

__all__ = ["Body", "Code", "Switch", "stmts"]

#: Anything usable as a run of C++ statements.  ``None`` contributes nothing, so
#: ``b.add(frag if condition else None)`` needs no branch.  A ``str`` is
#: margin-stripped and taken verbatim, with no punctuation added; pass a
#: :class:`~fprime_cpp_codegen.lines.Line` instead, or use :meth:`Body.line`, for text
#: that must survive a leading ``|``.
Code: TypeAlias = "None | str | Line | Body | Sequence[Code]"


def stmts(*code: Code) -> list[Line]:
    """Coerce statement-shaped values to lines, flattening nested sequences."""
    out: list[Line] = []
    for item in code:
        if item is None:
            continue
        if isinstance(item, Body):
            out.extend(item.build())
        elif isinstance(item, Line):
            out.append(item)
        elif isinstance(item, str):
            out.extend(_lines(item))
        elif isinstance(item, Sequence):
            out.extend(stmts(*item))
        else:
            raise ValidationError(f"not usable as C++ statements: {item!r}")
    return out


#: Statements after which control does not fall through.
_TERMINATING_KEYWORDS = ("return", "throw", "goto")


def _terminates(ll: Sequence[Line]) -> bool:
    """Whether ``ll`` ends in a statement that unconditionally transfers control.

    Conservative: a miss costs an unreachable ``break;``, while a false positive
    would drop a ``break`` and turn a switch arm into a fallthrough.  Only shapes
    that cannot be anything else match -- ``return`` and ``throw`` are keywords, so
    a following space or semicolon is unambiguous.
    """
    if not ll:
        return False
    last = ll[-1].string.strip()
    if last in ("break;", "continue;"):
        return True
    return any(
        last == f"{kw};" or last.startswith(f"{kw} ") for kw in _TERMINATING_KEYWORDS
    )


@dataclass
class _Frame:
    """One level of the body under construction."""

    lines: list[Line] = field(default_factory=list)
    kind: str = "body"
    open_chain: bool = False
    """Whether the last thing written was an ``if``/``else if``, so an ``else``
    may still attach to it."""


class Body:
    """A function body under construction."""

    def __init__(self, initial: Iterable[Line] | None = None) -> None:
        self._frames: list[_Frame] = [_Frame(list(initial or []))]

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    @property
    def terminated(self) -> bool:
        """Whether the last statement written unconditionally transfers control.

        A switch arm reads this to skip an unreachable ``break;``.  A ``return``
        nested inside an ``if`` does not count: the last line at this level is then
        the ``if``'s closing brace.
        """
        return _terminates(self._current.lines)

    @property
    def depth(self) -> int:
        """How many scopes are currently open.  Zero at the top level."""
        return len(self._frames) - 1

    def build(self) -> list[Line]:
        """Return the accumulated lines.

        Raises if a scope is still open, which means a ``with`` block was skipped
        or exited by something other than falling off the end.
        """
        if len(self._frames) > 1:
            raise ScopeError(
                f"{len(self._frames) - 1} body scope(s) are still open; finish every "
                "'with' block before building"
            )
        return list(self._frames[0].lines)

    def __bool__(self) -> bool:
        return any(f.lines for f in self._frames)

    def __iter__(self) -> Iterator[Line]:
        return iter(self.build())

    def __str__(self) -> str:
        return _render(self.build())

    def __enter__(self) -> Body:
        """Support ``with fn.body as b:`` as a way to shorten the name."""
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @property
    def _current(self) -> _Frame:
        return self._frames[-1]

    def _emit(self, ll: Sequence[Line], *, chain: bool = False) -> Body:
        """Append lines and record whether an ``else`` may follow."""
        frame = self._current
        frame.lines.extend(ll)
        frame.open_chain = chain
        return self

    @contextmanager
    def _scope(
        self,
        opening: str,
        closing: str,
        *,
        kind: str = "body",
        omit_if_empty: bool = False,
        chain: bool = False,
        indent: bool = True,
    ) -> Generator[Body]:
        """Open a nested scope, indenting whatever is written inside it.

        If the block raises, the scope is discarded and the body is left as it was
        before the ``with``.
        """
        frame = _Frame(kind=kind)
        self._frames.append(frame)
        try:
            yield self
        except BaseException:
            self._frames.pop()
            raise
        self._frames.pop()
        if not frame.lines and omit_if_empty:
            return
        body = indent_lines(frame.lines) if indent else list(frame.lines)
        self._emit(
            [*_lines(opening), *body, *_lines(closing)],
            chain=chain,
        )

    def _require_chain(self, keyword: str) -> None:
        if not self._current.open_chain:
            raise ScopeError(
                f"{keyword!r} has no 'if' to attach to; it must directly follow an "
                "if_() or elif_() scope in the same body"
            )

    # ------------------------------------------------------------------
    # Raw output
    # ------------------------------------------------------------------

    def line(self, text: str) -> Body:
        """Append one line verbatim."""
        return self._emit([_line(text)])

    def lines(self, text: str, *, margin: str | None = "|") -> Body:
        """Append a margin-stripped, possibly multi-line block of C++.

        ``margin=None`` turns the stripping off, for text taken from a generator's
        input that may legitimately begin with the margin character.  :meth:`line`
        never strips.
        """
        return self._emit(_lines(text, margin=margin))

    def raw(self, ll: Iterable[Line]) -> Body:
        """Append already-rendered lines."""
        return self._emit(list(ll))

    def add(self, *code: Code) -> Body:
        """Append anything statement-shaped: text, lines, another body, or nested
        sequences of those.  ``None`` contributes nothing."""
        return self._emit(stmts(*code))

    def extend(self, other: Code) -> Body:
        """Splice in another body or block of lines.  Alias of :meth:`add`."""
        return self.add(other)

    def blank(self) -> Body:
        """Append a blank line."""
        return self._emit([blank()])

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def comment(self, text: Comment) -> Body:
        """Append a ``//`` comment with no leading blank line."""
        return self._emit(write_comment_body(text))

    def spaced_comment(self, text: Comment) -> Body:
        """Append a ``//`` comment preceded by a blank line."""
        return self._emit(write_comment(text))

    def doc_comment(self, text: Comment) -> Body:
        """Append a ``//!`` doxygen comment."""
        return self._emit(write_doxygen_comment(text))

    def banner(self, text: Comment) -> Body:
        """Append a ruled banner comment."""
        return self._emit(write_banner_comment(text))

    # ------------------------------------------------------------------
    # Control flow
    # ------------------------------------------------------------------

    def block(self, *, omit_if_empty: bool = False) -> AbstractContextManager[Body]:
        """A bare braced block, for scoping a local."""
        return self._scope("{", "}", omit_if_empty=omit_if_empty)

    def if_(
        self, condition: str, *, omit_if_empty: bool = False
    ) -> AbstractContextManager[Body]:
        """``if (condition) { ... }``, which an :meth:`elif_` or :meth:`else_` may follow."""
        return self._scope(
            f"if ({condition}) {{", "}", omit_if_empty=omit_if_empty, chain=True
        )

    def elif_(self, condition: str) -> AbstractContextManager[Body]:
        """``else if (condition) { ... }``.  Must follow an ``if`` or another ``else if``."""
        self._require_chain("elif_")
        return self._scope(f"else if ({condition}) {{", "}", chain=True)

    def else_(self) -> AbstractContextManager[Body]:
        """``else { ... }``.  Must follow an ``if`` or an ``else if``."""
        self._require_chain("else_")
        return self._scope("else {", "}")

    def branch(self, condition: str) -> AbstractContextManager[Body]:
        """``if`` the first time, ``else if`` while a chain is still open.

        Lets a chain of arbitrary length come out of a plain loop::

            for condition, code in dispatch:
                with b.branch(condition):
                    b.add(code)
            with b.else_():
                b.raw(fprime.write_assert("0"))
        """
        return (
            self.elif_(condition) if self._current.open_chain else self.if_(condition)
        )

    def while_(
        self, condition: str, *, omit_if_empty: bool = False
    ) -> AbstractContextManager[Body]:
        """``while (condition) { ... }``"""
        return self._scope(f"while ({condition}) {{", "}", omit_if_empty=omit_if_empty)

    def do_while(self, condition: str) -> AbstractContextManager[Body]:
        """``do { ... } while (condition);``"""
        return self._scope("do {", f"}} while ({condition});")

    def for_(
        self,
        init: str,
        condition: str,
        step: str,
        *,
        omit_if_empty: bool = False,
        staggered: bool = False,
    ) -> AbstractContextManager[Body]:
        """``for (init; condition; step) { ... }``.

        ``staggered=True`` splits the three clauses across lines.
        """
        opening = (
            f"""|for (
                |  {init};
                |  {condition};
                |  {step}
                |) {{
                |"""
            if staggered
            else f"for ({init}; {condition}; {step}) {{"
        )
        return self._scope(opening, "}", omit_if_empty=omit_if_empty)

    def for_range(
        self, declaration: str, container: str, *, omit_if_empty: bool = False
    ) -> AbstractContextManager[Body]:
        """``for (declaration : container) { ... }``, e.g. ``for_range("auto& e", "m_list")``."""
        return self._scope(
            f"for ({declaration} : {container}) {{", "}", omit_if_empty=omit_if_empty
        )

    def scope(
        self, opening: str, closing: str, *, omit_if_empty: bool = False
    ) -> AbstractContextManager[Body]:
        """An arbitrary scope, for shapes this module does not cover."""
        return self._scope(opening, closing, omit_if_empty=omit_if_empty)

    def if_directive(
        self,
        directive: str,
        *,
        omit_if_empty: bool = True,
        spaced: bool = True,
    ) -> AbstractContextManager[Body]:
        """Bracket the block with a preprocessor ``directive`` and ``#endif``.

        ``directive`` is written verbatim and must include its ``#``.  The guarded
        code is not indented relative to the guard, since the directives sit at
        column zero.  ``spaced=False`` drops the blank lines around them.
        """
        gap = "\n" if spaced else ""
        return self._scope(
            f"{gap}{directive}",
            f"{gap}#endif",
            omit_if_empty=omit_if_empty,
            indent=False,
        )

    @contextmanager
    def switch(
        self, selector: str, *, omit_if_empty: bool = False
    ) -> Generator[Switch]:
        """``switch (selector) { ... }``.  Yields a :class:`Switch` for its cases."""
        frame = _Frame(kind="switch")
        self._frames.append(frame)
        switch = Switch(self, frame)
        try:
            yield switch
        except BaseException:
            self._frames.pop()
            raise
        self._frames.pop()
        if not frame.lines and omit_if_empty:
            return
        self._emit(
            [
                *_lines(f"switch ({selector}) {{"),
                *indent_lines(frame.lines),
                *_lines("}"),
            ]
        )


class Switch:
    """The cases of an open ``switch``.  Obtained from :meth:`Body.switch`."""

    def __init__(self, body: Body, frame: _Frame) -> None:
        self._body = body
        self._frame = frame

    def _check_open(self) -> None:
        if self._body._current is not self._frame:
            raise ScopeError(
                "this switch is not the innermost open scope; close any nested "
                "scope before adding another case"
            )

    def case(
        self, *labels: str, fallthrough: bool = False, braces: bool = True
    ) -> AbstractContextManager[Body]:
        """One or more ``case`` labels sharing a body.

        A ``break;`` is appended unless ``fallthrough=True`` or the body already
        ends in a statement that transfers control.  Braces let an arm declare a
        local, which a bare label cannot; ``braces=False`` emits the bare label.
        """
        self._check_open()
        if not labels:
            raise ScopeError("case() needs at least one label")
        last = f"case {labels[-1]}: {{" if braces else f"case {labels[-1]}:"
        opening = "\n".join([*(f"case {l}:" for l in labels[:-1]), last])
        return self._scoped(opening, fallthrough, braces)

    def default(
        self, *, fallthrough: bool = False, braces: bool = True
    ) -> AbstractContextManager[Body]:
        """The ``default`` label.  See :meth:`case` for the arguments."""
        self._check_open()
        return self._scoped("default: {" if braces else "default:", fallthrough, braces)

    @contextmanager
    def _scoped(self, opening: str, fallthrough: bool, braces: bool) -> Generator[Body]:
        body = self._body
        frame = _Frame(kind="case")
        body._frames.append(frame)
        try:
            yield body
        except BaseException:
            body._frames.pop()
            raise
        body._frames.pop()
        inner = list(frame.lines)
        if not fallthrough and not _terminates(frame.lines):
            inner.append(_line("break;"))
        closing = _lines("}") if braces else []
        body._emit([*_lines(opening), *indent_lines(inner), *closing])
