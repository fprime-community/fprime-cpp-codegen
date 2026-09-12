"""Decoration wrapped around a run of members: banners, guards, access sections.

None of it emits code of its own, so where it lands depends on where the members it
decorates landed -- which is only known once the enclosing scope is built.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ..comments import write_access_tag, write_banner_comment
from ..doc import (
    Class,
    Comment,
    Constructor,
    Destructor,
    Function,
    Lines,
    Output,
    SVQualifier,
    Variable,
)
from ..lines import Line, blank
from ..lines import lines as _lines
from ..writer import needs_definition, variable_defined_in_source
from .base import _Builder

if TYPE_CHECKING:
    from .scopes import ClassBuilder


def _source_targets(members: Sequence[object], *, in_class: bool) -> list[str | None]:
    """Which source files ``members`` contribute definitions to.

    Entries are ``cpp_file`` base names, with ``None`` standing for the document's
    default source file, in order of first appearance.  An empty result means these
    members are header-only.

    Anything decorating a group of members -- a banner, a preprocessor guard -- needs
    this to land in the same files as the members themselves.
    """
    found: list[str | None] = []

    def note(target: str | None) -> None:
        if target not in found:
            found.append(target)

    def visit(items: Sequence[object]) -> None:
        for m in items:
            if isinstance(m, _Builder):
                visit(m.build_members())
            elif isinstance(m, Lines):
                if m.output is not Output.HPP and m.content:
                    note(m.cpp_file)
            elif isinstance(m, (Function, Constructor, Destructor)):
                pure = getattr(m, "sv", None) is SVQualifier.PURE_VIRTUAL
                if needs_definition(m, pure_virtual=pure) and not m.defined_in_header:
                    note(m.cpp_file)
            elif isinstance(m, Variable):
                if variable_defined_in_source(m, in_class=in_class):
                    note(m.cpp_file)
            elif isinstance(m, Class):
                # A templated class defines everything in the header.
                if m.template is None:
                    visit(m.members)

    visit(members)
    return found


def _per_file_lines(
    content: list[Line], output: Output, targets: Sequence[str | None]
) -> list[Lines]:
    """Repeat ``content`` once for the header and once per source file in ``targets``."""
    out: list[Lines] = []
    if output is not Output.CPP:
        out.append(Lines(content, Output.HPP))
    if output is not Output.HPP:
        out.extend(Lines(content, Output.CPP, target) for target in targets)
    return out


class _SectionBanner(_Builder[Lines]):
    """The banner comment heading an access section.

    Where it goes is decided at build time, once the section's contents are known.  A
    header-only section -- nested types, member variables -- keeps its banner out of
    the source files.  Otherwise the banner follows the members: into the default
    source file, or into the supplemental files when that is where the section's
    definitions went.
    """

    def __init__(self, comment: Comment) -> None:
        self.comment = comment
        self.members: list[object] = []

    def _targets(self) -> list[str | None]:
        targets = _source_targets(self.members, in_class=True)
        # One copy suffices for decoration, so relocate only when the default source
        # file holds none of the section.  A guard cannot do this; see _Guard.
        if None in targets:
            return [None]
        return targets

    def build(self) -> Lines:
        return self._members()[0]

    def _members(self) -> list[Lines]:
        content = write_banner_comment(self.comment)
        return _per_file_lines(content, Output.BOTH, self._targets())

    def build_members(self) -> list[Any]:
        return list(self._members())


class _Guard:
    """A preprocessor guard bracketing a run of members.

    Repeated into every source file receiving a guarded definition: code escaping the
    guard would be compiled unconditionally.
    """

    def __init__(self, directive: str, output: Output, *, in_class: bool) -> None:
        self.directive = directive
        self.output = output
        self.in_class = in_class
        self.members: list[object] = []

    def targets(self) -> list[str | None]:
        return _source_targets(self.members, in_class=self.in_class)

    def open_members(self) -> list[Lines]:
        if not self.members:
            return []
        return _per_file_lines(
            _lines(f"\n{self.directive}"), self.output, self.targets()
        )

    def close_members(self) -> list[Lines]:
        if not self.members:
            return []
        content = [blank(), *_lines("#endif")]
        return _per_file_lines(content, self.output, self.targets())


class _GuardOpen(_Builder[Lines]):
    """Placeholder for a guard's opening directive, resolved at build time."""

    def __init__(self, guard: _Guard) -> None:
        self._guard = guard

    def build(self) -> Lines:
        members = self._guard.open_members()
        return members[0] if members else Lines([], self._guard.output)

    def build_members(self) -> list[Any]:
        return list(self._guard.open_members())


class _GuardClose(_Builder[Lines]):
    """Placeholder for a guard's ``#endif``, resolved at build time."""

    def __init__(self, guard: _Guard) -> None:
        self._guard = guard

    def build(self) -> Lines:
        members = self._guard.close_members()
        return members[0] if members else Lines([], self._guard.output)

    def build_members(self) -> list[Any]:
        return list(self._guard.close_members())


class AccessSection:
    """An access-specifier section of a class.

    The ``public:`` label goes in immediately, so ``cls.public("Interface")`` works
    on its own.  As a ``with`` block, a section that ends up with no members takes
    its label and banner back out again.
    """

    def __init__(self, scope: ClassBuilder, tag: str, comment: Comment | None) -> None:
        self._scope = scope
        self._count = 1
        scope._add(Lines(write_access_tag(tag), Output.HPP))
        self._banner: _SectionBanner | None = None
        if comment is not None:
            self._banner = scope._add(_SectionBanner(comment))
            self._count += 1
        self._start = len(scope._pending)

    def __enter__(self) -> ClassBuilder:
        return self._scope

    def __exit__(self, *exc: object) -> None:
        pending = self._scope._pending
        if len(pending) == self._start:
            del pending[self._start - self._count : self._start]
        elif self._banner is not None:
            self._banner.members = pending[self._start :]
        return None
