"""Whole-document checks: does every member actually reach a file it was promised?

The writers validate one declaration at a time -- a variable that is both static and
mutable, a default argument that is not trailing.  The checks here are the ones that
need the whole document, or the set of files it is being rendered to:

* :func:`orphaned_members` -- members that would vanish because the file they
  belong in is not being emitted.  Only ever non-empty when ``emit_hpp`` or
  ``emit_cpp`` is off.
* :func:`unfilled_definitions` -- definitions that need a body and have none.  A
  generator that forgot to fill one in otherwise gets a valid but empty out-of-line
  definition rather than an error.

Both report rather than raise, so a caller can log them or make its own decision.
:func:`check_document` is the raising wrapper the output paths use.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace

from .doc import (
    Class,
    ClassMember,
    Constructor,
    CppDoc,
    Definition,
    Destructor,
    Function,
    Lines,
    Member,
    Namespace,
    Output,
    SVQualifier,
    Variable,
)
from .errors import ValidationError
from .writer import needs_definition, variable_defined_in_source

__all__ = [
    "check_document",
    "orphaned_members",
    "unfilled_definitions",
]


@dataclass(frozen=True)
class _Where:
    """Where in the document a member sits, in the terms these checks need."""

    path: tuple[str, ...] = ()
    """The enclosing namespaces and classes, outermost first."""

    in_class: bool = False
    in_template: bool = False
    """Set inside a templated class, all of whose members are defined in the header."""

    def in_namespace(self, name: str) -> _Where:
        return replace(self, path=(*self.path, name or "(anonymous)"))

    def in_class_body(self, c: Class) -> _Where:
        return replace(
            self,
            path=(*self.path, c.name),
            in_class=True,
            in_template=self.in_template or c.template is not None,
        )

    @property
    def scope(self) -> str:
        return f"in {'::'.join(self.path)}" if self.path else "at document scope"


def _is_pure_virtual(d: Definition) -> bool:
    """Whether ``d`` is a pure virtual function.  Only a function can be one."""
    return getattr(d, "sv", None) is SVQualifier.PURE_VIRTUAL


def _describe(m: object, where: _Where) -> str:
    """Name a member well enough for a person to find it in their generator."""
    if isinstance(m, Class):
        return f"{'struct' if m.struct else 'class'} {m.name!r} {where.scope}"
    if isinstance(m, Function):
        return f"function {m.name!r} {where.scope}"
    if isinstance(m, Constructor):
        return f"a constructor {where.scope}"
    if isinstance(m, Destructor):
        return f"a destructor {where.scope}"
    if isinstance(m, Variable):
        return f"variable {m.name!r} {where.scope}"
    if isinstance(m, Lines):
        first = next((l.string for l in m.content if l.string), "")
        return f"raw lines {where.scope}" + (f" starting {first!r}" if first else "")
    return f"{m!r} {where.scope}"


def _walk(
    doc: CppDoc, *, into_classes: bool = True
) -> Iterator[tuple[Member | ClassMember, _Where]]:
    """Yield every member of ``doc``, paired with where it sits.

    A class is yielded before the members inside it.  ``into_classes=False`` stops at
    the class itself, for a check that has already disqualified everything within.
    """

    def visit(
        members: Sequence[Member | ClassMember], where: _Where
    ) -> Iterator[tuple[Member | ClassMember, _Where]]:
        for m in members:
            yield m, where
            if isinstance(m, Namespace):
                yield from visit(m.members, where.in_namespace(m.name))
            elif isinstance(m, Class) and into_classes:
                yield from visit(m.members, where.in_class_body(m))

    yield from visit(doc.members, _Where())


def _needs_source_file(m: Member | ClassMember, where: _Where) -> bool:
    """Whether ``m`` puts anything in a source file."""
    if isinstance(m, Lines):
        return m.output is not Output.HPP and bool(m.content)
    if isinstance(m, (Function, Constructor, Destructor)):
        return (
            needs_definition(m, pure_virtual=_is_pure_virtual(m))
            and not m.defined_in_header
            and not where.in_template
        )
    if isinstance(m, Variable):
        return variable_defined_in_source(m, in_class=where.in_class)
    return False


def _lost_without_source_file(m: Member | ClassMember, where: _Where) -> bool:
    """Whether dropping the source files would lose part of ``m``.

    ``Output.BOTH`` lines are the exception: the same text goes into both files, so
    the header copy survives and nothing is lost.  Everything else that a source file
    holds, it holds alone -- a function's body is not in the header next to its
    declaration.
    """
    if isinstance(m, Lines):
        return m.output is Output.CPP and bool(m.content)
    return _needs_source_file(m, where)


def _lost_without_header(m: Member | ClassMember, where: _Where) -> bool:
    """Whether dropping the header would lose part of ``m``.

    What survives is what a standalone translation unit can hold: anything with an
    out-of-line definition to write, and lines that were going to the source file
    anyway.  A namespace is structure rather than content -- it is emitted wherever
    its members are -- so it is never itself the thing that gets stranded.
    """
    if isinstance(m, Namespace):
        return False
    if isinstance(m, Lines):
        return m.output is Output.HPP and bool(m.content)
    return not _needs_source_file(m, where)


def orphaned_members(
    doc: CppDoc, *, emit_hpp: bool = True, emit_cpp: bool = True
) -> list[str]:
    """Describe every member of ``doc`` that the chosen files would silently drop.

    With both files emitted there is nowhere for a member to fall, so the result is
    always empty.  Suppressing one of them strands whatever only that file was going
    to hold:

    * ``emit_cpp=False`` strands every out-of-line definition -- a function body, a
      static data member's initialiser, an ``extern`` variable, ``Output.CPP`` lines.
      Making them ``inline_body`` or ``constexpr`` moves them into the header.
    * ``emit_hpp=False`` strands every declaration, and so every class: a source file
      is given member definitions but never the class head that declares them.  What
      survives is what a standalone ``.cpp`` can hold on its own -- free functions
      with bodies, ``extern`` definitions, and ``Output.CPP`` lines.
    """
    out: list[str] = []
    if not emit_cpp:
        out.extend(
            _describe(m, where)
            for m, where in _walk(doc)
            if _lost_without_source_file(m, where)
        )
    if not emit_hpp:
        out.extend(
            _describe(m, where)
            for m, where in _walk(doc, into_classes=False)
            if _lost_without_header(m, where)
        )
    return out


def unfilled_definitions(doc: CppDoc) -> list[str]:
    """Describe every definition in ``doc`` that needs a body and has none.

    A deleted, defaulted or declaration-only member is excluded, as is a pure virtual
    without a body: each of those is meant to have no definition.  What is left is a
    definition a generator started and did not finish, which otherwise renders as an
    empty out-of-line body -- valid C++, and so silent.

    A definition that is deliberately empty says so with ``body=""``, which renders
    exactly as an empty body does.
    """
    return [
        _describe(m, where)
        for m, where in _walk(doc)
        if isinstance(m, (Function, Constructor, Destructor))
        and needs_definition(m, pure_virtual=_is_pure_virtual(m))
        and not m.body
    ]


def check_document(
    doc: CppDoc,
    *,
    emit_hpp: bool = True,
    emit_cpp: bool = True,
    strict: bool = False,
) -> None:
    """Raise :class:`~fprime_cpp_codegen.errors.ValidationError` if ``doc`` will not
    render cleanly to the chosen files.

    Runs :func:`orphaned_members` always -- it costs a walk only when a file is being
    suppressed -- and :func:`unfilled_definitions` when ``strict`` is set.
    """
    if not emit_hpp and not emit_cpp:
        raise ValidationError(
            "this document emits neither a header nor a source file, so it would "
            "produce nothing at all"
        )
    orphans = orphaned_members(doc, emit_hpp=emit_hpp, emit_cpp=emit_cpp)
    if orphans:
        suppressed = "header" if not emit_hpp else "source file"
        raise ValidationError(
            f"this document does not emit a {suppressed}, which is the only place "
            f"these would have gone: {_listing(orphans)}"
        )
    if strict:
        unfilled = unfilled_definitions(doc)
        if unfilled:
            raise ValidationError(
                "strict is set and these definitions need a body but have none: "
                f"{_listing(unfilled)}; use declaration_only=True to declare without "
                'defining, or body="" for a deliberately empty definition'
            )


def _listing(items: Sequence[str]) -> str:
    """Join descriptions for an error message, capping a runaway list."""
    shown = list(items[:10])
    if len(items) > len(shown):
        shown.append(f"and {len(items) - len(shown)} more")
    return "; ".join(shown)
