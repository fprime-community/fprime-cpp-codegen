"""The C++ document IR: one ``.hpp`` file plus one or more ``.cpp`` files.

The layer the writers consume: a tree of frozen dataclasses.
:mod:`fprime_cpp_codegen.builder` assembles it for you.

A single :class:`CppDoc` describes a header and any number of source files.  Every
definition with a body, and every block of raw lines, can name the ``.cpp`` file it
belongs to via ``cpp_file``; those naming nothing land in the document's default
``.cpp``.  The header always gets everything, so one class can be split across
translation units without duplicating its declaration.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, TypeAlias, runtime_checkable

from .lines import Line

__all__ = [
    "VOID",
    "Class",
    "ClassMember",
    "Comment",
    "Constructor",
    "CppDoc",
    "DefaultFileBanner",
    "Definition",
    "Destructor",
    "FileBanner",
    "Function",
    "HppFile",
    "Lines",
    "Member",
    "Namespace",
    "Output",
    "Param",
    "SVQualifier",
    "Type",
    "Variable",
    "as_type",
]

#: Anything usable as comment text.  A ``str`` is margin-stripped and split on
#: newlines, so a line of it beginning with ``|`` loses that character; ready-made
#: lines are taken exactly as they are, which is how text derived from a generator's
#: input should be passed.  See :func:`fprime_cpp_codegen.lines.strip_margin`.
Comment: TypeAlias = "str | Sequence[Line]"


class Output(Enum):
    """Which of a document's files a block of raw lines is emitted into."""

    HPP = "hpp"
    """Header only."""

    CPP = "cpp"
    """Source only."""

    BOTH = "both"
    """Both the header and the source."""


class SVQualifier(Enum):
    """A function's static/virtual specifier, mutually exclusive by construction.

    ``OVERRIDE`` and ``FINAL`` render as trailing specifiers; ``STATIC``, ``VIRTUAL``
    and ``PURE_VIRTUAL`` as leading ones.  ``PURE_VIRTUAL`` also terminates the
    declaration with ``= 0``.
    """

    NONE = "none"
    STATIC = "static"
    VIRTUAL = "virtual"
    PURE_VIRTUAL = "pure-virtual"
    OVERRIDE = "override"
    FINAL = "final"


@dataclass(frozen=True)
class Type:
    """A C++ type.

    The source file may need a different spelling from the header, typically because
    the header sits inside the namespace qualifying the name.  ``cpp_type`` supplies
    it; when absent, both files use ``hpp_type``.
    """

    hpp_type: str
    cpp_type: str | None = None

    @property
    def cpp(self) -> str:
        """The spelling to use in a ``.cpp`` file."""
        return self.cpp_type if self.cpp_type is not None else self.hpp_type

    @property
    def hpp(self) -> str:
        """The spelling to use in the ``.hpp`` file."""
        return self.hpp_type


#: The ``void`` type, and the default return type of a :class:`Function`.
VOID = Type("void")


def as_type(t: Type | str | tuple[str, str]) -> Type:
    """Coerce a type specification to a :class:`Type`.

    A single string is used in both files.  A ``(header, source)`` pair supplies the
    two spellings a nested type needs: ``Status`` inside the class,
    ``MyClass::Status`` in the source file where the return type precedes
    ``MyClass::``.
    """
    if isinstance(t, Type):
        return t
    if isinstance(t, tuple):
        hpp, cpp = t
        return Type(hpp, cpp)
    return Type(t)


@dataclass(frozen=True)
class Param:
    """A formal parameter of a function, constructor, or destructor."""

    type: Type
    name: str
    comment: Comment | None = None
    """A doxygen post-comment, rendered after the parameter in the header."""

    default: str | None = None
    """A default argument, rendered in the header declaration only."""


@dataclass(frozen=True)
class Lines:
    """A block of raw, already-rendered C++ lines.

    Access tags, banner comments, ``#include`` directives, enums and structs are all
    lines.  ``output`` decides which files see them.
    """

    content: list[Line] = field(default_factory=list)
    output: Output = Output.HPP
    cpp_file: str | None = None
    """Restrict source-file output to this ``.cpp`` base name.  Header output is
    unaffected."""


@dataclass(frozen=True, kw_only=True)
class Definition:
    """Fields shared by everything that has a body.

    Keyword-only, so subclasses can take their own defining field as the first
    positional argument.

    ``deleted`` and ``defaulted`` replace the body with ``= delete`` or
    ``= default``; ``declaration_only`` leaves the declaration standing with no
    definition anywhere; ``inline_body`` and ``template`` move the definition into the
    header, since a template's definition must be visible at every use.  In all five
    cases the source file gets nothing.
    """

    body: list[Line] = field(default_factory=list)
    comment: Comment | None = None
    cpp_file: str | None = None
    """Which ``.cpp`` file the definition goes in.  ``None`` means the default."""

    noexcept: bool = False
    deleted: bool = False
    defaulted: bool = False
    inline_body: bool = False

    declaration_only: bool = False
    """Declare without defining: the header gets the declaration and no source file
    gets a definition.

    For a symbol something else provides -- another translation unit, a hand-written
    file, a linker script.  Without it, a definition left unfilled emits an empty
    out-of-line body instead, which is valid C++ with different linkage rather than an
    error; see also ``strict`` on
    :class:`~fprime_cpp_codegen.builder.CppDocBuilder`."""

    template: str | None = None
    """A template parameter list without the keyword, e.g. ``"typename T"``.
    Implies :attr:`inline_body`."""

    @property
    def defined_in_header(self) -> bool:
        return self.inline_body or self.template is not None

    @property
    def has_definition(self) -> bool:
        """Whether there is a body to write at all."""
        return not (self.deleted or self.defaulted or self.declaration_only)


@dataclass(frozen=True)
class Function(Definition):
    """A C++ function, either free-standing or a class member."""

    name: str
    params: list[Param] = field(default_factory=list)
    ret_type: Type = VOID
    """``Type("")`` emits no return type, as a conversion operator needs."""

    sv: SVQualifier = SVQualifier.NONE
    const: bool = False
    constexpr: bool = False
    inline: bool = False

    attributes: Sequence[str] = ()
    """Declaration attributes, e.g. ``['__attribute__((visibility("default")))']`` or
    ``["[[nodiscard]]"]``, written verbatim at the head of the declaration.

    The header declaration carries them; the out-of-line definition does not, which is
    where both GCC's ``__attribute__`` and standard ``[[...]]`` attributes want to
    be."""

    @property
    def defined_in_header(self) -> bool:
        """``constexpr`` and ``inline`` force the definition into the header: both
        require it visible in every translation unit that uses the function."""
        return super().defined_in_header or self.constexpr or self.inline


@dataclass(frozen=True)
class Constructor(Definition):
    """A C++ constructor.  Its name is taken from the enclosing class."""

    params: list[Param] = field(default_factory=list)
    initializers: list[str] = field(default_factory=list)
    """Member-initializer-list entries, e.g. ``"m_size(size)"``, rendered wherever the
    definition goes."""

    explicit: bool = False
    constexpr: bool = False

    @property
    def defined_in_header(self) -> bool:
        return super().defined_in_header or self.constexpr


@dataclass(frozen=True)
class Destructor(Definition):
    """A C++ destructor.  Its name is taken from the enclosing class."""

    virtual: bool = False
    override: bool = False


@dataclass(frozen=True)
class Class:
    """A C++ class, possibly nested inside another class."""

    name: str
    superclass_decls: str | None = None
    """Everything after the colon, verbatim, e.g. ``"public Fw::Serializable"``.
    Multiple bases go in one comma-separated string."""

    members: list[ClassMember] = field(default_factory=list)
    comment: Comment | None = None
    final: bool = False
    template: str | None = None
    """A template parameter list without the keyword, e.g. ``"typename T"``.  A
    templated class defines all its members in the header, so its source file output
    is empty."""

    struct: bool = False
    """Emit ``struct``, making members public by default."""

    attributes: Sequence[str] = ()
    """Declaration attributes, e.g. ``['__attribute__((visibility("default")))']``,
    written verbatim between the ``class``/``struct`` keyword and the name.

    That position is the one that leaves the name alone: an attribute folded into
    :attr:`name` would also corrupt the constructor and destructor names and the
    ``MyClass ::`` qualifier on every out-of-line definition."""


@dataclass(frozen=True)
class Variable:
    """A variable: a class data member, or a constant or global at namespace scope.

    Where the initialiser goes depends on the kind of variable:

    * A non-static data member takes its initialiser in the class body.
    * A static data member is only declared in the class; the definition, with the
      initialiser, goes in a source file.  A ``constexpr`` static is initialised in
      the class and needs no out-of-line definition unless something takes its
      address -- see ``out_of_line_definition``.
    * At namespace scope, ``extern`` splits declaration from definition the same way.
      Without it the variable is defined where it is declared, as a ``constexpr`` or
      ``const`` constant in a header should be.
    """

    name: str
    type: Type
    init: str | None = None
    array: str | None = None
    """An array extent, without brackets, e.g. ``"SIZE"`` for ``m_data[SIZE]``."""

    comment: Comment | None = None
    static: bool = False
    const: bool = False
    constexpr: bool = False
    mutable: bool = False
    extern: bool = False
    out_of_line_definition: bool = False
    """Also emit a source-file definition for a ``constexpr`` static member."""

    cpp_file: str | None = None

    @property
    def declarator(self) -> str:
        """The name plus any array extent, e.g. ``"m_data[SIZE]"``."""
        return f"{self.name}[{self.array}]" if self.array is not None else self.name


@dataclass(frozen=True)
class Namespace:
    """A C++ namespace.  Nest instances to nest namespaces."""

    name: str
    members: list[Member] = field(default_factory=list)


#: What may appear at document or namespace scope.
Member = Class | Lines | Function | Namespace | Variable

#: What may appear at class scope.  Namespaces may not; constructors and
#: destructors may.
ClassMember = Class | Lines | Function | Constructor | Destructor | Variable


@runtime_checkable
class FileBanner(Protocol):
    """Supplies the ``\\title``/``\\author``/``\\brief`` lines atop each file."""

    def title(self, file_name: str) -> str:
        """The ``\\title`` text for ``file_name``."""
        ...

    def author(self, file_name: str) -> str:
        """The ``\\author`` text for ``file_name``."""
        ...

    def description(self, file_name: str, generic_description: str) -> str:
        """The ``\\brief`` text.  ``generic_description`` is the writer's own phrasing,
        e.g. ``"hpp file for my component"``."""
        ...


@dataclass(frozen=True)
class DefaultFileBanner:
    """The banner used when a document does not supply one."""

    tool_name: str | None = None

    def title(self, file_name: str) -> str:
        return file_name

    def author(self, file_name: str) -> str:
        return f"Generated by {self.tool_name or 'fpp tools'}"

    def description(self, file_name: str, generic_description: str) -> str:
        return generic_description


@dataclass(frozen=True)
class HppFile:
    """The header file of a document."""

    name: str
    """The file name including extension, e.g. ``"MyClass.hpp"``."""

    include_guard: str
    """The include-guard macro, e.g. ``"Fw_MyClass_HPP"``."""


@dataclass(frozen=True)
class CppDoc:
    """A C++ document: one header, one default source file, and the members."""

    description: str
    """Used in the file banners, as ``"hpp file for <description>"``."""

    hpp_file: HppFile
    cpp_file_name: str
    """The default source file name including extension, e.g. ``"MyClass.cpp"``."""

    members: list[Member] = field(default_factory=list)
    tool_name: str | None = None
    banner: FileBanner | None = None

    @property
    def file_banner(self) -> FileBanner:
        """The document's banner, falling back to :class:`DefaultFileBanner`."""
        return (
            self.banner
            if self.banner is not None
            else DefaultFileBanner(self.tool_name)
        )
