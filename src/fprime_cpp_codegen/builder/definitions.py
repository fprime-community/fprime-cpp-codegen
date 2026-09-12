"""Builders for the things a scope holds: functions, constructors, enums."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import Enum

from ..body import Body, Code
from ..comments import (
    add_param_comment,
    write_doxygen_comment,
    write_doxygen_comment_opt,
)
from ..doc import (
    Comment,
    Constructor,
    Destructor,
    Function,
    Lines,
    Output,
    Param,
    Type,
    as_type,
)
from ..errors import ValidationError
from ..lines import Line, wrap_in_scope
from ..lines import line as _line
from .base import _Builder
from .coercion import _as_attributes, _as_body_lines, _as_params, _sv_qualifier


class Radix(Enum):
    """How to spell an integer literal."""

    DECIMAL = "decimal"
    HEX = "hex"


def _wrap_in_enum(
    body: list[Line],
    *,
    name: str | None = None,
    scoped: bool = False,
    underlying: str | None = None,
) -> list[Line]:
    """Wrap enumerators in an ``enum``, ``enum <name>`` or ``enum class <name>``."""
    if scoped:
        suffix = f" : {underlying}" if underlying is not None else ""
        opening = f"enum class {name}{suffix} {{"
    elif name is not None:
        opening = f"enum {name} {{"
    else:
        opening = "enum {"
    return wrap_in_scope(opening, body, "};", keep_empty=True)


class FunctionBuilder(_Builder[Function]):
    """A function or member function under construction."""

    def __init__(
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
    ) -> None:
        if not name:
            raise ValidationError("a function needs a name")
        self.name = name
        self.ret = as_type(ret)
        self.comment = comment
        self.const = const
        self.constexpr = constexpr
        self.inline = inline
        self.noexcept = noexcept
        self.deleted = deleted
        self.defaulted = defaulted
        self.declaration_only = declaration_only
        self.attributes = _as_attributes(attributes)
        self.template = template
        self.inline_body = inline_body
        self.cpp_file = cpp_file
        self._sv = _sv_qualifier(
            static=static,
            virtual=virtual,
            pure_virtual=pure_virtual,
            override=override,
            final=final,
        )
        self._params = _as_params(params)
        self.body = Body(_as_body_lines(body))

    def param(
        self,
        type_name: Type | str,
        name: str,
        *,
        comment: Comment | None = None,
        default: str | None = None,
    ) -> FunctionBuilder:
        """Append one formal parameter.  Returns self, so calls can be chained."""
        self._params.append(Param(as_type(type_name), name, comment, default))
        return self

    def params(self, *params: Param | Sequence[str]) -> FunctionBuilder:
        """Append several formal parameters at once."""
        self._params.extend(_as_params(params))
        return self

    def build(self) -> Function:
        return Function(
            self.name,
            params=list(self._params),
            ret_type=self.ret,
            body=self.body.build(),
            comment=self.comment,
            sv=self._sv,
            const=self.const,
            constexpr=self.constexpr,
            inline=self.inline,
            noexcept=self.noexcept,
            deleted=self.deleted,
            defaulted=self.defaulted,
            declaration_only=self.declaration_only,
            attributes=self.attributes,
            template=self.template,
            inline_body=self.inline_body,
            cpp_file=self.cpp_file,
        )

    def __enter__(self) -> FunctionBuilder:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class ConstructorBuilder(_Builder[Constructor]):
    """A constructor under construction."""

    def __init__(
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
    ) -> None:
        self.comment = comment
        self.explicit = explicit
        self.constexpr = constexpr
        self.noexcept = noexcept
        self.deleted = deleted
        self.defaulted = defaulted
        self.declaration_only = declaration_only
        self.template = template
        self.inline_body = inline_body
        self.cpp_file = cpp_file
        self._params = _as_params(params)
        self._initializers = list(initializers)
        self.body = Body(_as_body_lines(body))

    def param(
        self,
        type_name: Type | str,
        name: str,
        *,
        comment: Comment | None = None,
        default: str | None = None,
    ) -> ConstructorBuilder:
        """Append one formal parameter."""
        self._params.append(Param(as_type(type_name), name, comment, default))
        return self

    def params(self, *params: Param | Sequence[str]) -> ConstructorBuilder:
        """Append several formal parameters at once."""
        self._params.extend(_as_params(params))
        return self

    def init(self, *entries: str) -> ConstructorBuilder:
        """Append member-initializer entries, e.g. ``init("m_size(size)")``."""
        self._initializers.extend(entries)
        return self

    def build(self) -> Constructor:
        return Constructor(
            params=list(self._params),
            initializers=list(self._initializers),
            body=self.body.build(),
            comment=self.comment,
            explicit=self.explicit,
            constexpr=self.constexpr,
            noexcept=self.noexcept,
            deleted=self.deleted,
            defaulted=self.defaulted,
            declaration_only=self.declaration_only,
            template=self.template,
            inline_body=self.inline_body,
            cpp_file=self.cpp_file,
        )

    def __enter__(self) -> ConstructorBuilder:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class DestructorBuilder(_Builder[Destructor]):
    """A destructor under construction."""

    def __init__(
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
    ) -> None:
        self.comment = comment
        self.virtual = virtual
        self.override = override
        self.noexcept = noexcept
        self.deleted = deleted
        self.defaulted = defaulted
        self.declaration_only = declaration_only
        self.inline_body = inline_body
        self.cpp_file = cpp_file
        self.body = Body(_as_body_lines(body))

    def build(self) -> Destructor:
        return Destructor(
            body=self.body.build(),
            comment=self.comment,
            virtual=self.virtual,
            override=self.override,
            noexcept=self.noexcept,
            deleted=self.deleted,
            defaulted=self.defaulted,
            declaration_only=self.declaration_only,
            inline_body=self.inline_body,
            cpp_file=self.cpp_file,
        )

    def __enter__(self) -> DestructorBuilder:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class EnumBuilder(_Builder[Lines]):
    """An enum or enum class under construction.  Renders as raw lines."""

    def __init__(
        self,
        name: str | None = None,
        *,
        underlying: str | None = None,
        scoped: bool = False,
        comment: Comment | None = None,
        output: Output = Output.HPP,
        cpp_file: str | None = None,
        radix: Radix = Radix.DECIMAL,
        trailing_comma: bool = True,
        comment_above: bool = False,
        qualifier: str = "",
    ) -> None:
        if underlying is not None and not scoped:
            raise ValidationError(
                "an underlying type needs a scoped enum; pass scoped=True (or use "
                "enum_class())"
            )
        if scoped and not name:
            raise ValidationError("a scoped enum needs a name")
        self.name = name
        self.underlying = underlying
        self.scoped = scoped
        self.comment = comment
        self.output = output
        self.cpp_file = cpp_file
        self.radix = radix
        self.trailing_comma = trailing_comma
        """Whether the last enumerator carries a comma.  Legal either way."""

        self.comment_above = comment_above
        """Put each enumerator's comment on a ``//!`` line above it, instead of a
        ``//!<`` post-comment after it."""

        self.qualifier = qualifier
        self._constants: list[list[Line]] = []

    @property
    def type(self) -> Type:
        """This enum as a :class:`Type`, qualified for use in a source file.

        A nested enum is spelled bare inside its class, but a source-file return type
        precedes ``Class::`` and so is not yet in the class's scope.  Pass this to
        ``ret=`` for both spellings::

            status = cls.enum_class("Status", underlying="U8")
            cls.function("check", ret=status.type)
        """
        if self.name is None:
            raise ValidationError("an anonymous enum has no type name")
        return Type(
            self.name, f"{self.qualifier}::{self.name}" if self.qualifier else None
        )

    def constant(
        self,
        name: str,
        value: int | str | None = None,
        *,
        comment: Comment | None = None,
        radix: Radix | None = None,
    ) -> EnumBuilder:
        """Append one enumerator.

        ``value`` may be an integer, an arbitrary C++ expression, or ``None`` to let
        the compiler assign the next value.
        """
        if value is None:
            text = f"{name},"
        elif isinstance(value, int):
            spelled = (
                f"0x{value:x}" if (radix or self.radix) is Radix.HEX else str(value)
            )
            text = f"{name} = {spelled},"
        else:
            text = f"{name} = {value},"
        if comment is not None and self.comment_above:
            entry = [*write_doxygen_comment(comment)[1:], _line(text)]
        else:
            entry = add_param_comment(text, comment)
        self._constants.append(entry)
        return self

    def constants(self, *names: str) -> EnumBuilder:
        """Append several auto-numbered enumerators at once."""
        for name in names:
            self.constant(name)
        return self

    def _body(self) -> list[Line]:
        """The enumerators, with the last one's comma removed if asked."""
        entries = [list(e) for e in self._constants]
        if entries and not self.trailing_comma:
            last = entries[-1]
            last[-1] = Line(last[-1].string.rstrip(","), last[-1].indent)
        return [l for entry in entries for l in entry]

    def build(self) -> Lines:
        inner = _wrap_in_enum(
            self._body(),
            name=self.name,
            scoped=self.scoped,
            underlying=self.underlying,
        )
        return Lines(
            [*write_doxygen_comment_opt(self.comment), *inner],
            self.output,
            self.cpp_file,
        )

    def __enter__(self) -> EnumBuilder:
        return self

    def __exit__(self, *exc: object) -> None:
        return None
