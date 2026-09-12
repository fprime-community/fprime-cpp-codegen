"""Scopes: the things that hold an ordered list of members.

A class body, a namespace, and the document itself all share the member-adding
vocabulary in :class:`_Scope`, and differ in what a member may be.

The methods that add a definition -- :meth:`ClassBuilder.function`,
:meth:`ClassBuilder.constructor` and the rest -- spell out the parameters of the
builder they construct instead of forwarding ``**kwargs``, so an editor and a type
checker can both see them.  ``tests/test_signatures.py`` holds the two in step.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Sequence
from contextlib import contextmanager
from typing import Any, Generic

from ..body import Code
from ..comments import (
    write_banner_comment,
    write_doxygen_comment,
    write_doxygen_comment_opt,
)
from ..doc import (
    Class,
    Comment,
    Lines,
    Namespace,
    Output,
    Param,
    Type,
    Variable,
    as_type,
)
from ..errors import ValidationError
from ..lines import Line, blank
from ..lines import line as _line
from ..lines import lines as _lines
from .base import _Builder, _DocContext, _resolve, _T, _T2
from .coercion import _as_attributes, _extends
from .decoration import AccessSection, _Guard, _GuardClose, _GuardOpen
from .definitions import (
    Radix,
    ConstructorBuilder,
    DestructorBuilder,
    EnumBuilder,
    FunctionBuilder,
)


class _Scope(_Builder[_T], Generic[_T]):
    """Shared behaviour for anything that holds an ordered list of members."""

    _in_class = False
    """Whether this scope is a class body.  Decides how a variable's declaration
    and definition are split."""

    def __init__(
        self, ctx: _DocContext | None = None, *, type_qualifier: str = ""
    ) -> None:
        self._ctx = ctx if ctx is not None else _DocContext()
        self._pending: list[object] = []
        self._type_qualifier = type_qualifier
        """How a type declared in this scope is spelled from a source file: the
        enclosing class chain, or empty at namespace scope."""

    # -- internals ----------------------------------------------------

    def _add(self, item: _T2) -> _T2:
        self._pending.append(item)
        return item

    def _resolved_cpp_file(self, cpp_file: str | None) -> str | None:
        """Fall back to the enclosing ``cpp_file`` block when none was given."""
        return cpp_file if cpp_file is not None else self._ctx.cpp_file

    def _built_members(self) -> list[Any]:
        return _resolve(self._pending)

    # -- raw content --------------------------------------------------

    def member(self, *members: object) -> None:
        """Splice in ready-made IR members or builders, in order.

        Takes output from :mod:`fprime_cpp_codegen.fprime`::

            cls.member(*fprime.write_ostream_operator("MyType", body))
        """
        for m in members:
            self._add(m)

    def raw(
        self,
        ll: Iterable[Line],
        *,
        output: Output = Output.HPP,
        cpp_file: str | None = None,
    ) -> None:
        """Append already-rendered lines as a member."""
        self._add(Lines(list(ll), output, self._resolved_cpp_file(cpp_file)))

    def lines(
        self,
        text: str,
        *,
        margin: str | None = "|",
        output: Output = Output.HPP,
        cpp_file: str | None = None,
    ) -> None:
        """Append a margin-stripped, possibly multi-line block of C++ as a member.

        ``margin=None`` turns the stripping off, for text taken from a generator's
        input that may legitimately begin with the margin character.
        """
        self.raw(_lines(text, margin=margin), output=output, cpp_file=cpp_file)

    def banner(
        self,
        text: Comment,
        *,
        output: Output = Output.BOTH,
        cpp_file: str | None = None,
    ) -> None:
        """Append a ruled banner comment, heading the members that follow.

        Unconditional: it goes into both files unless ``output`` says otherwise.  An
        access section's banner instead follows its members.
        """
        self.raw(write_banner_comment(text), output=output, cpp_file=cpp_file)

    def doc_comment(self, text: Comment, *, output: Output = Output.HPP) -> None:
        """Append a standalone ``//!`` doxygen comment."""
        self.raw(write_doxygen_comment(text), output=output)

    def using(
        self,
        name: str,
        target: str,
        *,
        comment: Comment | None = None,
        output: Output = Output.HPP,
    ) -> None:
        """Append a type alias: ``using <name> = <target>;``."""
        self.raw(
            [*write_doxygen_comment_opt(comment), *_lines(f"using {name} = {target};")],
            output=output,
        )

    # -- nested constructs -------------------------------------------

    def enum(
        self,
        name: str | None = None,
        *,
        comment: Comment | None = None,
        output: Output = Output.HPP,
        radix: Radix = Radix.DECIMAL,
        trailing_comma: bool = True,
        comment_above: bool = False,
    ) -> EnumBuilder:
        """Add an unscoped ``enum``, named or anonymous.

        An anonymous enum carries an integer constant in the header without needing a
        definition in a source file.
        """
        return self._add(
            EnumBuilder(
                name,
                comment=comment,
                output=output,
                radix=radix,
                trailing_comma=trailing_comma,
                comment_above=comment_above,
                qualifier=self._type_qualifier,
            )
        )

    def enum_class(
        self,
        name: str,
        *,
        underlying: str | None = None,
        comment: Comment | None = None,
        output: Output = Output.HPP,
        radix: Radix = Radix.DECIMAL,
        trailing_comma: bool = True,
        comment_above: bool = False,
    ) -> EnumBuilder:
        """Add a scoped ``enum class``, optionally with an underlying type."""
        return self._add(
            EnumBuilder(
                name,
                underlying=underlying,
                scoped=True,
                comment=comment,
                output=output,
                radix=radix,
                trailing_comma=trailing_comma,
                comment_above=comment_above,
                qualifier=self._type_qualifier,
            )
        )

    def var(
        self,
        type_name: Type | str,
        name: str,
        *,
        init: str | None = None,
        array: str | None = None,
        comment: Comment | None = None,
        static: bool = False,
        const: bool = False,
        constexpr: bool = False,
        mutable: bool = False,
        extern: bool = False,
        out_of_line_definition: bool = False,
        cpp_file: str | None = None,
    ) -> None:
        """Add a variable: a class data member, or a constant at namespace scope."""
        self._add(
            Variable(
                name,
                as_type(type_name),
                init=init,
                array=array,
                comment=comment,
                static=static,
                const=const,
                constexpr=constexpr,
                mutable=mutable,
                extern=extern,
                out_of_line_definition=out_of_line_definition,
                cpp_file=self._resolved_cpp_file(cpp_file),
            )
        )

    @contextmanager
    def if_directive(
        self, directive: str, *, output: Output = Output.BOTH
    ) -> Generator[Any]:
        """Bracket the members added inside with a preprocessor guard.

        ``directive`` is written verbatim and must include its ``#``.  A guard with no
        members inside it is not emitted, and a block that raises discards whatever
        it added.

        The guard is repeated into every source file receiving one of the guarded
        definitions, so a definition sent to a supplemental ``.cpp`` stays guarded
        there.
        """
        start = len(self._pending)
        try:
            yield self
        except BaseException:
            del self._pending[start:]
            raise
        if len(self._pending) == start:
            return
        guard = _Guard(directive, output, in_class=self._in_class)
        guard.members = self._pending[start:]
        self._pending.insert(start, _GuardOpen(guard))
        self._pending.append(_GuardClose(guard))

    @contextmanager
    def cpp_file(self, base: str | None) -> Generator[Any]:
        """Send definitions created inside this block to ``<base>.cpp``.

        ``base`` is a file name without extension; ``None`` restores the document
        default.  Only definitions created while the block is open are affected.
        """
        self._ctx.cpp_files.append(base)
        try:
            yield self
        finally:
            self._ctx.cpp_files.pop()


class ClassBuilder(_Scope[Class]):
    """A class or struct under construction."""

    _in_class = True

    def __init__(
        self,
        name: str,
        *,
        extends: str | Sequence[str] | None = None,
        final: bool = False,
        comment: Comment | None = None,
        template: str | None = None,
        struct: bool = False,
        attributes: str | Sequence[str] = (),
        ctx: _DocContext | None = None,
        type_qualifier: str = "",
    ) -> None:
        if not name:
            raise ValidationError("a class needs a name")
        qualified = f"{type_qualifier}::{name}" if type_qualifier else name
        super().__init__(ctx, type_qualifier=qualified)
        self.name = name
        self.qualified_name = qualified
        """How this class is spelled from a source file: the enclosing class chain
        plus its own name.  Namespaces are excluded, since a source file is written
        inside its namespace."""

        self.extends = _extends(extends)
        self.final = final
        self.comment = comment
        self.template = template
        self.struct = struct
        self.attributes = _as_attributes(attributes)
        """Declaration attributes, between the keyword and the name.  See
        :attr:`fprime_cpp_codegen.doc.Class.attributes`."""

    @property
    def type(self) -> Type:
        """This class as a :class:`Type`, qualified for use in a source file."""
        return Type(
            self.name, self.qualified_name if self.qualified_name != self.name else None
        )

    def nested(self, name: str) -> Type:
        """A type declared inside this class, qualified for use in a source file.

        For anything this class declares that the builder does not know about, such as
        an alias from :meth:`using`::

            cls.using("Id", "U32")
            cls.function("id", ret=cls.nested("Id"), const=True)
        """
        return Type(name, f"{self.qualified_name}::{name}")

    # -- access sections ---------------------------------------------

    def public(self, comment: Comment | None = None) -> AccessSection:
        """Start a ``public:`` section."""
        return AccessSection(self, "public", comment)

    def protected(self, comment: Comment | None = None) -> AccessSection:
        """Start a ``protected:`` section."""
        return AccessSection(self, "protected", comment)

    def private(self, comment: Comment | None = None) -> AccessSection:
        """Start a ``private:`` section."""
        return AccessSection(self, "private", comment)

    # -- members ------------------------------------------------------

    def constructor(
        self,
        *,
        params: Iterable[Param | Sequence[str]] = (),
        initializers: Iterable[str] = (),
        comment: Comment | None = None,
        body: Code = None,
        explicit: bool = False,
        constexpr: bool = False,
        noexcept: bool = False,
        deleted: bool = False,
        defaulted: bool = False,
        declaration_only: bool = False,
        template: str | None = None,
        inline_body: bool = False,
        cpp_file: str | None = None,
    ) -> ConstructorBuilder:
        """Add a constructor.  See :class:`ConstructorBuilder`.

        ``cpp_file`` defaults to the enclosing :meth:`cpp_file` block's target, as it
        does for every definition added to a scope.
        """
        return self._add(
            ConstructorBuilder(
                params=params,
                initializers=initializers,
                comment=comment,
                body=body,
                explicit=explicit,
                constexpr=constexpr,
                noexcept=noexcept,
                deleted=deleted,
                defaulted=defaulted,
                declaration_only=declaration_only,
                template=template,
                inline_body=inline_body,
                cpp_file=self._resolved_cpp_file(cpp_file),
            )
        )

    def destructor(
        self,
        *,
        comment: Comment | None = None,
        body: Code = None,
        virtual: bool = False,
        override: bool = False,
        noexcept: bool = False,
        deleted: bool = False,
        defaulted: bool = False,
        declaration_only: bool = False,
        inline_body: bool = False,
        cpp_file: str | None = None,
    ) -> DestructorBuilder:
        """Add a destructor.  See :class:`DestructorBuilder`."""
        return self._add(
            DestructorBuilder(
                comment=comment,
                body=body,
                virtual=virtual,
                override=override,
                noexcept=noexcept,
                deleted=deleted,
                defaulted=defaulted,
                declaration_only=declaration_only,
                inline_body=inline_body,
                cpp_file=self._resolved_cpp_file(cpp_file),
            )
        )

    def function(
        self,
        name: str,
        *,
        ret: Type | str = "void",
        params: Iterable[Param | Sequence[str]] = (),
        comment: Comment | None = None,
        body: Code = None,
        const: bool = False,
        static: bool = False,
        virtual: bool = False,
        pure_virtual: bool = False,
        override: bool = False,
        final: bool = False,
        constexpr: bool = False,
        inline: bool = False,
        noexcept: bool = False,
        deleted: bool = False,
        defaulted: bool = False,
        declaration_only: bool = False,
        attributes: str | Sequence[str] = (),
        template: str | None = None,
        inline_body: bool = False,
        cpp_file: str | None = None,
    ) -> FunctionBuilder:
        """Add a member function.  See :class:`FunctionBuilder`."""
        return self._add(
            FunctionBuilder(
                name,
                ret=ret,
                params=params,
                comment=comment,
                body=body,
                const=const,
                static=static,
                virtual=virtual,
                pure_virtual=pure_virtual,
                override=override,
                final=final,
                constexpr=constexpr,
                inline=inline,
                noexcept=noexcept,
                deleted=deleted,
                defaulted=defaulted,
                declaration_only=declaration_only,
                attributes=attributes,
                template=template,
                inline_body=inline_body,
                cpp_file=self._resolved_cpp_file(cpp_file),
            )
        )

    def class_(
        self,
        name: str,
        *,
        extends: str | Sequence[str] | None = None,
        final: bool = False,
        comment: Comment | None = None,
        template: str | None = None,
        struct: bool = False,
        attributes: str | Sequence[str] = (),
    ) -> ClassBuilder:
        """Add a nested class.  See :class:`ClassBuilder`.

        The nested class inherits this one's type qualifier, so a type it declares is
        spelled ``Outer::Inner::T`` from a source file.
        """
        return self._add(
            ClassBuilder(
                name,
                extends=extends,
                final=final,
                comment=comment,
                template=template,
                struct=struct,
                attributes=attributes,
                ctx=self._ctx,
                type_qualifier=self._type_qualifier,
            )
        )

    def struct_(
        self,
        name: str,
        *,
        extends: str | Sequence[str] | None = None,
        final: bool = False,
        comment: Comment | None = None,
        template: str | None = None,
        attributes: str | Sequence[str] = (),
    ) -> ClassBuilder:
        """Add a nested struct: :meth:`class_` with ``struct=True``."""
        return self.class_(
            name,
            extends=extends,
            final=final,
            comment=comment,
            template=template,
            struct=True,
            attributes=attributes,
        )

    def friend(self, declaration: str, *, comment: Comment | None = None) -> None:
        """Add a ``friend`` declaration, written verbatim after the keyword."""
        self.raw(
            [
                *write_doxygen_comment_opt(comment),
                *_lines(f"friend {declaration};"),
            ]
        )

    def build(self) -> Class:
        return Class(
            self.name,
            superclass_decls=self.extends,
            members=self._built_members(),
            comment=self.comment,
            final=self.final,
            template=self.template,
            struct=self.struct,
            attributes=self.attributes,
        )

    def __enter__(self) -> ClassBuilder:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _MemberScope(_Scope[_T], Generic[_T]):
    """Document and namespace scope: classes, free functions, nested namespaces."""

    def include(
        self,
        *paths: str,
        output: Output = Output.HPP,
        cpp_file: str | None = None,
    ) -> None:
        """Append quoted ``#include`` directives for project headers."""
        if not paths:
            return
        self.raw(
            [blank(), *(_line(f'#include "{p}"') for p in paths)],
            output=output,
            cpp_file=cpp_file,
        )

    def system_include(
        self,
        *paths: str,
        output: Output = Output.HPP,
        cpp_file: str | None = None,
    ) -> None:
        """Append angle-bracket ``#include`` directives for system headers."""
        if not paths:
            return
        self.raw(
            [blank(), *(_line(f"#include <{p}>") for p in paths)],
            output=output,
            cpp_file=cpp_file,
        )

    def class_(
        self,
        name: str,
        *,
        extends: str | Sequence[str] | None = None,
        final: bool = False,
        comment: Comment | None = None,
        template: str | None = None,
        struct: bool = False,
        attributes: str | Sequence[str] = (),
    ) -> ClassBuilder:
        """Add a class.  See :class:`ClassBuilder`."""
        return self._add(
            ClassBuilder(
                name,
                extends=extends,
                final=final,
                comment=comment,
                template=template,
                struct=struct,
                attributes=attributes,
                ctx=self._ctx,
            )
        )

    def struct_(
        self,
        name: str,
        *,
        extends: str | Sequence[str] | None = None,
        final: bool = False,
        comment: Comment | None = None,
        template: str | None = None,
        attributes: str | Sequence[str] = (),
    ) -> ClassBuilder:
        """Add a struct: :meth:`class_` with ``struct=True``."""
        return self.class_(
            name,
            extends=extends,
            final=final,
            comment=comment,
            template=template,
            struct=True,
            attributes=attributes,
        )

    def function(
        self,
        name: str,
        *,
        ret: Type | str = "void",
        params: Iterable[Param | Sequence[str]] = (),
        comment: Comment | None = None,
        body: Code = None,
        static: bool = False,
        constexpr: bool = False,
        inline: bool = False,
        noexcept: bool = False,
        deleted: bool = False,
        defaulted: bool = False,
        declaration_only: bool = False,
        attributes: str | Sequence[str] = (),
        template: str | None = None,
        inline_body: bool = False,
        cpp_file: str | None = None,
    ) -> FunctionBuilder:
        """Add a free function.  See :class:`FunctionBuilder`.

        ``const``, ``virtual``, ``pure_virtual``, ``override`` and ``final`` are
        absent by design: none of them means anything at namespace scope, so passing
        one is a :class:`TypeError` here rather than C++ that will not compile.  Use
        ``static`` for internal linkage.
        """
        return self._add(
            FunctionBuilder(
                name,
                ret=ret,
                params=params,
                comment=comment,
                body=body,
                static=static,
                constexpr=constexpr,
                inline=inline,
                noexcept=noexcept,
                deleted=deleted,
                defaulted=defaulted,
                declaration_only=declaration_only,
                attributes=attributes,
                template=template,
                inline_body=inline_body,
                cpp_file=self._resolved_cpp_file(cpp_file),
            )
        )

    def namespace(self, *names: str) -> NamespaceBuilder:
        """Add a namespace, or a chain of nested ones.

        ``namespace("Fw", "Cfg")`` opens both and returns the innermost, so members
        added to the result land in ``Fw::Cfg``.
        """
        if not names:
            raise ValidationError("namespace() needs at least one name")
        outer = NamespaceBuilder(names[0], ctx=self._ctx)
        self._add(outer)
        inner = outer
        for name in names[1:]:
            inner = inner._add(NamespaceBuilder(name, ctx=self._ctx))
        return inner

    def anonymous_namespace(self) -> NamespaceBuilder:
        """Add an unnamed namespace, giving everything in it internal linkage."""
        return self._add(NamespaceBuilder("", ctx=self._ctx))


class NamespaceBuilder(_MemberScope[Namespace]):
    """A namespace under construction."""

    def __init__(self, name: str, *, ctx: _DocContext | None = None) -> None:
        super().__init__(ctx)
        self.name = name

    def build(self) -> Namespace:
        return Namespace(self.name, self._built_members())

    def __enter__(self) -> NamespaceBuilder:
        return self

    def __exit__(self, *exc: object) -> None:
        return None
