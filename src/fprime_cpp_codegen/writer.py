"""Rendering a :class:`~fprime_cpp_codegen.doc.CppDoc` to header and source lines.

Two visitors walk the same document tree.  :class:`HppWriter` emits declarations;
:class:`CppWriter` emits definitions.  The header sees every member exactly once.
A source file sees only the definitions assigned to it, so calling
:func:`cpp_lines` once per ``.cpp`` base name splits a document across as many
translation units as you like.

Deciding where a definition goes is the logic here.  Most go into a source file, but
templates, ``inline`` and ``constexpr`` functions must be visible in every
translation unit that uses them, as must every member of a templated class; those
are defined in the header and skipped by the source file.  ``= delete`` and
``= default`` members have no definition to place.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from .comments import (
    add_param_comment,
    left_align_directive,
    write_banner,
    write_doxygen_comment_opt,
    write_function_body,
)
from .doc import (
    Class,
    ClassMember,
    Constructor,
    CppDoc,
    Definition,
    Destructor,
    Function,
    HppFile,
    Lines,
    Member,
    Namespace,
    Output,
    Param,
    SVQualifier,
    Variable,
)
from .errors import CppCodegenError, ValidationError
from .lines import (
    INDENT_INCREMENT,
    IndentMode,
    Line,
    add_prefix,
    add_suffix,
    blank,
    indent_lines,
    join_lists,
    line,
    lines,
    render,
)

__all__ = [
    "Context",
    "CppWriter",
    "DocWriter",
    "HppWriter",
    "cpp_lines",
    "hpp_lines",
    "needs_definition",
    "render_cpp",
    "render_hpp",
    "variable_defined_in_source",
]


def _terminator(d: Definition, *, pure_virtual: bool = False) -> str:
    """The text ending a declaration: ``;``, ``= delete``, ``= default`` or ``= 0``."""
    what = type(d).__name__.lower()
    if d.deleted and d.defaulted:
        raise ValidationError(f"this {what} is both deleted and defaulted; pick one")
    if (d.deleted or d.defaulted) and d.body:
        raise ValidationError(
            f"this {what} is deleted or defaulted, so it cannot also have a body"
        )
    if pure_virtual and (d.deleted or d.defaulted):
        raise ValidationError(
            f"this {what} is pure virtual, so it cannot also be deleted or defaulted"
        )
    if d.declaration_only and d.body:
        raise ValidationError(
            f"this {what} is declaration-only, so it cannot also have a body; drop "
            "one of the two"
        )
    if d.declaration_only and (d.deleted or d.defaulted):
        raise ValidationError(
            f"this {what} is declaration-only and also deleted or defaulted; both "
            "leave it undefined, so pick one"
        )
    if d.deleted:
        return " = delete;"
    if d.defaulted:
        return " = default;"
    if pure_virtual:
        return " = 0;"
    return ";"


def _namespace_opening(name: str) -> str:
    """The line opening a namespace.  An empty name gives an unnamed namespace."""
    return f"namespace {name} {{" if name else "namespace {"


def _template_lines(params: str | None) -> list[Line]:
    """The ``template <...>`` line introducing a templated declaration."""
    return lines(f"template <{params}>") if params is not None else []


def _attribute_prefix(attributes: Sequence[str]) -> str:
    """The attributes of a declaration, as a space-terminated prefix.

    Empty when there are none, so it can be concatenated unconditionally.
    """
    return "".join(f"{a} " for a in attributes)


def variable_defined_in_source(v: Variable, *, in_class: bool) -> bool:
    """Whether ``v`` needs a definition in a source file, separate from its declaration."""
    if v.constexpr:
        return v.out_of_line_definition
    if in_class:
        return v.static
    return v.extern


def _check_variable(v: Variable, *, in_class: bool) -> None:
    """Reject variable declarations that could not compile."""
    if v.static and v.mutable:
        raise ValidationError(
            f"variable {v.name!r} is both static and mutable, which C++ does not allow"
        )
    if v.mutable and not in_class:
        raise ValidationError(
            f"variable {v.name!r} is mutable, which only means something for a class "
            "data member"
        )
    if v.constexpr and v.init is None:
        raise ValidationError(
            f"variable {v.name!r} is constexpr, so it needs an initialiser"
        )
    if v.extern and v.static:
        raise ValidationError(
            f"variable {v.name!r} is both extern and static, which contradict each "
            "other: one gives it external linkage and the other internal"
        )
    if v.extern and in_class:
        raise ValidationError(
            f"variable {v.name!r} is a class data member, so extern does not apply; "
            "use static instead"
        )


def _check_params(params: Sequence[Param]) -> None:
    """Reject a default argument followed by one without a default.

    C++ requires default arguments to be trailing.
    """
    defaulted: str | None = None
    for p in params:
        if p.default is not None:
            defaulted = p.name
        elif defaulted is not None:
            raise ValidationError(
                f"parameter {p.name!r} has no default argument but follows "
                f"{defaulted!r}, which does; C++ requires default arguments to be "
                "trailing"
            )


def needs_definition(d: Definition, *, pure_virtual: bool = False) -> bool:
    """Whether ``d`` has a definition that must be emitted somewhere.

    A deleted or defaulted member has none.  A pure virtual has none unless given a
    body, which C++ permits as a default implementation a derived class can call.
    """
    if not d.has_definition:
        return False
    return not (pure_virtual and not d.body)


@dataclass(frozen=True)
class Context:
    """Where the writer currently is in the document.

    ``class_names`` runs outermost-first and each entry may itself be qualified, so a
    nested class is spelled ``Outer::Inner`` in the source file while its constructor
    is spelled ``Inner``.
    """

    hpp_file: HppFile
    default_cpp_file_name: str
    output_cpp_file_name: str | None = None
    """The source file currently being written, if not the document default."""

    class_names: tuple[str, ...] = ()

    inline_definitions: bool = False
    """Set inside a templated class, whose members must all be defined in the header.
    Inherited by nested classes."""

    @property
    def cpp_file_name(self) -> str:
        """The source file being written."""
        return self.output_cpp_file_name or self.default_cpp_file_name

    @property
    def enclosing_class_qualified(self) -> str:
        """The enclosing class, fully qualified, e.g. ``"Outer::Inner"``."""
        return "::".join(self.class_names)

    @property
    def enclosing_class_unqualified(self) -> str:
        """The enclosing class with every qualifier stripped, e.g. ``"Inner"``."""
        if not self.class_names:
            raise ValidationError(
                "a constructor or destructor was placed outside a class, so it has "
                "no name to take"
            )
        return self.class_names[-1].split("::")[-1]

    def nested_in(self, class_name: str, *, inline: bool = False) -> Context:
        """Return this context, descended into ``class_name``."""
        return replace(
            self,
            class_names=(*self.class_names, class_name),
            inline_definitions=self.inline_definitions or inline,
        )


class DocWriter(ABC):
    """Dispatch for a document walk.

    Subclass :class:`HppWriter` or :class:`CppWriter` to change how something renders
    and pass the instance to any of the output paths -- ``writer=`` on
    :func:`render_hpp` and :func:`render_cpp`, ``hpp_writer=``/``cpp_writer=`` on
    :func:`~fprime_cpp_codegen.output.doc_files`,
    :func:`~fprime_cpp_codegen.output.write_doc` and
    :class:`~fprime_cpp_codegen.builder.CppDocBuilder`.  Subclass this directly only
    to render a document into something that is not C++ at all.
    """

    def visit_member(self, ctx: Context, member: Member) -> list[Line]:
        """Dispatch a document- or namespace-scope member."""
        if isinstance(member, Class):
            return self.visit_class(ctx, member)
        if isinstance(member, Lines):
            return self.visit_lines(ctx, member)
        if isinstance(member, Function):
            return self.visit_function(ctx, member)
        if isinstance(member, Namespace):
            return self.visit_namespace(ctx, member)
        if isinstance(member, Variable):
            return self.visit_variable(ctx, member)
        if isinstance(member, (Constructor, Destructor)):
            raise CppCodegenError(
                f"a {type(member).__name__} may only appear inside a class, not at "
                "document or namespace scope"
            )
        raise CppCodegenError(f"not a document member: {member!r}")

    def visit_class_member(self, ctx: Context, member: ClassMember) -> list[Line]:
        """Dispatch a class-scope member."""
        if isinstance(member, Class):
            return self.visit_class(ctx, member)
        if isinstance(member, Lines):
            return self.visit_lines(ctx, member)
        if isinstance(member, Constructor):
            return self.visit_constructor(ctx, member)
        if isinstance(member, Destructor):
            return self.visit_destructor(ctx, member)
        if isinstance(member, Function):
            return self.visit_function(ctx, member)
        if isinstance(member, Variable):
            return self.visit_variable(ctx, member)
        if isinstance(member, Namespace):
            raise CppCodegenError(
                "a namespace may not be declared inside a class; move it out to "
                "document scope"
            )
        raise CppCodegenError(f"not a class member: {member!r}")

    def visit_members(self, ctx: Context, members: list[Member]) -> list[Line]:
        """Dispatch every document- or namespace-scope member in order."""
        return [l for m in members for l in self.visit_member(ctx, m)]

    def visit_class_members(
        self, ctx: Context, members: list[ClassMember]
    ) -> list[Line]:
        """Dispatch every class-scope member in order."""
        return [l for m in members for l in self.visit_class_member(ctx, m)]

    def param_string(self, p: Param) -> str:
        """Render a parameter as ``"<type> <name>"``.

        Both writers use the header spelling.  An out-of-class definition's parameter
        list is looked up in the class's scope, so names resolving unqualified in the
        header resolve here too.  Only the return type, which precedes ``Class::``,
        needs the source spelling.
        """
        return f"{p.type.hpp} {p.name}"

    @abstractmethod
    def write_params(self, prefix: str, params: list[Param]) -> list[Line]:
        """Render ``prefix`` followed by a parenthesised parameter list."""

    @abstractmethod
    def visit_class(self, ctx: Context, c: Class) -> list[Line]: ...

    @abstractmethod
    def visit_constructor(self, ctx: Context, ctor: Constructor) -> list[Line]: ...

    @abstractmethod
    def visit_destructor(self, ctx: Context, dtor: Destructor) -> list[Line]: ...

    @abstractmethod
    def visit_function(self, ctx: Context, fn: Function) -> list[Line]: ...

    @abstractmethod
    def visit_lines(self, ctx: Context, ll: Lines) -> list[Line]: ...

    @abstractmethod
    def visit_namespace(self, ctx: Context, ns: Namespace) -> list[Line]: ...

    @abstractmethod
    def visit_variable(self, ctx: Context, v: Variable) -> list[Line]: ...


def initializer_lines(initializers: list[str]) -> list[Line]:
    """Render a member-initializer list, one entry per line, comma-separated."""
    last = len(initializers) - 1
    return [
        line(init + ("," if i < last else "")).indent_in(2 * INDENT_INCREMENT)
        for i, init in enumerate(initializers)
    ]


class HppWriter(DocWriter):
    """Renders a document's declarations into header lines."""

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def param_string(self, p: Param) -> str:
        """Render a parameter, including its default argument if it has one."""
        s = super().param_string(p)
        return f"{s} = {p.default}" if p.default is not None else s

    def param_lines(self, p: Param, *, comma: bool) -> list[Line]:
        """Render one parameter, with its post-comment hanging beneath it."""
        return add_param_comment(
            self.param_string(p) + ("," if comma else ""), p.comment
        )

    def write_params(self, prefix: str, params: list[Param]) -> list[Line]:
        """Render a parameter list, breaking one-per-line when there is more than one.

        A lone uncommented parameter stays on the same line as the name; anything else
        is exploded so the post-comments have somewhere to go.
        """
        _check_params(params)
        if not params:
            return lines(f"{prefix}()")
        if len(params) == 1 and params[0].comment is None:
            return lines(f"{prefix}({self.param_string(params[0])})")
        last = len(params) - 1
        body = [
            l for i, p in enumerate(params) for l in self.param_lines(p, comma=i < last)
        ]
        return [
            line(f"{prefix}("),
            *indent_lines(body, 2 * INDENT_INCREMENT),
            line(")"),
        ]

    # ------------------------------------------------------------------
    # Include guard
    # ------------------------------------------------------------------

    def open_include_guard(self, guard: str) -> list[Line]:
        """Render the opening half of an include guard."""
        return lines(f"""
            |#ifndef {guard}
            |#define {guard}""")

    def close_include_guard(self) -> list[Line]:
        """Render the closing half of an include guard."""
        return lines("""
            |#endif""")

    # ------------------------------------------------------------------
    # Declaration shaping
    # ------------------------------------------------------------------

    def add_trailing(
        self,
        decl: list[Line],
        *,
        const: bool = False,
        noexcept: bool = False,
        override: bool = False,
        final: bool = False,
    ) -> list[Line]:
        """Append trailing specifiers in the order C++ requires them."""
        if const:
            decl = add_suffix(decl, " const")
        if noexcept:
            decl = add_suffix(decl, " noexcept")
        if override:
            decl = add_suffix(decl, " override")
        if final:
            decl = add_suffix(decl, " final")
        return decl

    def defines_here(
        self, ctx: Context, d: Definition, *, pure_virtual: bool = False
    ) -> bool:
        """Whether ``d``'s definition belongs in the header, next to its declaration."""
        return needs_definition(d, pure_virtual=pure_virtual) and (
            ctx.inline_definitions or d.defined_in_header
        )

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------

    def visit_class(self, ctx: Context, c: Class) -> list[Line]:
        """Render a class declaration and everything in it.

        Attributes sit between the keyword and the name, which is where a
        ``visibility`` or ``dllexport`` attribute has to go and the only place that
        leaves the class's own name untouched.
        """
        kind = f"{'struct' if c.struct else 'class'} {_attribute_prefix(c.attributes)}"
        head = f"{kind}{c.name} final" if c.final else f"{kind}{c.name}"
        if c.superclass_decls is not None:
            open_lines = [
                line(f"{head} :"),
                line(c.superclass_decls).indent_in(),
                line("{"),
            ]
        else:
            open_lines = lines(f"{head} {{")
        inner = ctx.nested_in(c.name, inline=c.template is not None)
        body = self.visit_class_members(inner, c.members)
        return [
            *write_doxygen_comment_opt(c.comment),
            *_template_lines(c.template),
            *open_lines,
            *indent_lines(body, 2 * INDENT_INCREMENT),
            blank(),
            line("};"),
        ]

    def visit_constructor(self, ctx: Context, ctor: Constructor) -> list[Line]:
        """Render a constructor declaration, with its body if that belongs here."""
        decl = self.write_params(ctx.enclosing_class_unqualified, ctor.params)
        if ctor.constexpr:
            decl = add_prefix("constexpr ", decl)
        if ctor.explicit:
            decl = add_prefix("explicit ", decl)
        decl = self.add_trailing(decl, noexcept=ctor.noexcept)
        if self.defines_here(ctx, ctor):
            if ctor.initializers:
                decl = [*add_suffix(decl, " :"), *initializer_lines(ctor.initializers)]
            tail = [*decl, *write_function_body(ctor.body)]
        else:
            tail = join_lists(IndentMode.NO_INDENT, decl, "", lines(_terminator(ctor)))
        return [
            *write_doxygen_comment_opt(ctor.comment),
            *_template_lines(ctor.template),
            *tail,
        ]

    def visit_destructor(self, ctx: Context, dtor: Destructor) -> list[Line]:
        """Render a destructor declaration, with its body if that belongs here."""
        prefix = "virtual " if dtor.virtual else ""
        decl = self.add_trailing(
            lines(f"{prefix}~{ctx.enclosing_class_unqualified}()"),
            noexcept=dtor.noexcept,
            override=dtor.override,
        )
        if self.defines_here(ctx, dtor):
            tail = [*decl, *write_function_body(dtor.body)]
        else:
            tail = join_lists(IndentMode.NO_INDENT, decl, "", lines(_terminator(dtor)))
        return [*write_doxygen_comment_opt(dtor.comment), *tail]

    def visit_function(self, ctx: Context, fn: Function) -> list[Line]:
        """Render a function declaration, with its body if that belongs here.

        Attributes lead the whole declaration, ahead of ``static`` and the rest: that
        position is the one a standard ``[[...]]`` attribute requires, and one GCC's
        ``__attribute__`` accepts.
        """
        pure = fn.sv is SVQualifier.PURE_VIRTUAL
        lead = _attribute_prefix(fn.attributes)
        if fn.sv is SVQualifier.STATIC:
            lead += "static "
        elif fn.sv in (SVQualifier.VIRTUAL, SVQualifier.PURE_VIRTUAL):
            lead += "virtual "
        if fn.constexpr:
            lead += "constexpr "
        if fn.inline:
            lead += "inline "
        ret = f"{fn.ret_type.hpp} " if fn.ret_type.hpp else ""
        decl = self.add_trailing(
            self.write_params(f"{lead}{ret}{fn.name}", fn.params),
            const=fn.const,
            noexcept=fn.noexcept,
            override=fn.sv is SVQualifier.OVERRIDE,
            final=fn.sv is SVQualifier.FINAL,
        )
        if self.defines_here(ctx, fn, pure_virtual=pure):
            if pure:
                raise ValidationError(
                    f"function {fn.name!r} is pure virtual with a body, and its "
                    "definition has to live in the header, but C++ does not allow a "
                    "pure virtual to be defined inside its class; emit the "
                    "out-of-line definition yourself with Lines"
                )
            tail = [*decl, *write_function_body(fn.body)]
        else:
            tail = join_lists(
                IndentMode.NO_INDENT,
                decl,
                "",
                lines(_terminator(fn, pure_virtual=pure)),
            )
        return [
            *write_doxygen_comment_opt(fn.comment),
            *_template_lines(fn.template),
            *tail,
        ]

    def visit_variable(self, ctx: Context, v: Variable) -> list[Line]:
        """Render a variable declaration.

        The initialiser is included only when this declaration is also the definition;
        otherwise it goes to the source file with the definition.
        """
        in_class = bool(ctx.class_names)
        _check_variable(v, in_class=in_class)
        lead = ""
        if v.extern and not in_class:
            lead += "extern "
        if v.static:
            lead += "static "
        if v.constexpr:
            lead += "constexpr "
        if v.const:
            lead += "const "
        if v.mutable:
            lead += "mutable "
        decl = f"{lead}{v.type.hpp} {v.declarator}"
        if v.init is not None and not variable_defined_in_source(v, in_class=in_class):
            decl += f" = {v.init}"
        return [*write_doxygen_comment_opt(v.comment), *lines(f"{decl};")]

    def visit_lines(self, ctx: Context, ll: Lines) -> list[Line]:
        """Emit raw lines unless they are marked source-only."""
        return [] if ll.output is Output.CPP else list(ll.content)

    def visit_namespace(self, ctx: Context, ns: Namespace) -> list[Line]:
        """Render a namespace and everything in it.

        The header emits the namespace even when empty, since a declaration-free
        namespace may exist only to be reopened elsewhere.
        """
        return [
            blank(),
            line(_namespace_opening(ns.name)),
            *indent_lines(self.visit_members(ctx, ns.members)),
            blank(),
            line("}"),
        ]

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def visit_doc(self, doc: CppDoc) -> list[Line]:
        """Render the whole header file."""
        ctx = Context(doc.hpp_file, doc.cpp_file_name)
        ext = doc.hpp_file.name.rsplit(".", 1)[-1]
        out = [
            *write_banner(
                doc.file_banner, doc.hpp_file.name, f"{ext} file for {doc.description}"
            ),
            *self.open_include_guard(doc.hpp_file.include_guard),
            *self.visit_members(ctx, doc.members),
            *self.close_include_guard(),
        ]
        return [left_align_directive(l) for l in out]


class CppWriter(DocWriter):
    """Renders a document's definitions into source lines for one ``.cpp`` file."""

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def write_params(self, prefix: str, params: list[Param]) -> list[Line]:
        """Render a parameter list.  Comments and defaults belong in the header."""
        if not params:
            return lines(f"{prefix}()")
        if len(params) == 1:
            return lines(f"{prefix}({self.param_string(params[0])})")
        last = len(params) - 1
        body = [
            line(self.param_string(p) + ("," if i < last else ""))
            for i, p in enumerate(params)
        ]
        return [
            line(f"{prefix}("),
            *indent_lines(body, 2 * INDENT_INCREMENT),
            line(")"),
        ]

    # ------------------------------------------------------------------
    # File selection
    # ------------------------------------------------------------------

    def write_selected(
        self,
        ctx: Context,
        cpp_file: str | None,
        render_lines: Callable[[], list[Line]],
    ) -> list[Line]:
        """Render only if ``cpp_file`` names the source file being written.

        ``None`` means the document's default source file.  This is the mechanism
        behind splitting one document across several ``.cpp`` files.
        """
        selected = (
            f"{cpp_file}.cpp" if cpp_file is not None else ctx.default_cpp_file_name
        )
        return render_lines() if selected == ctx.cpp_file_name else []

    def defines_here(self, d: Definition, *, pure_virtual: bool = False) -> bool:
        """Whether ``d``'s definition belongs in a source file at all."""
        return (
            needs_definition(d, pure_virtual=pure_virtual) and not d.defined_in_header
        )

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------

    def visit_class(self, ctx: Context, c: Class) -> list[Line]:
        """Descend into a class.  The class itself contributes no source text.

        A templated class contributes nothing: all its members are defined in the
        header.
        """
        if c.template is not None:
            return []
        return self.visit_class_members(ctx.nested_in(c.name), c.members)

    def visit_constructor(self, ctx: Context, ctor: Constructor) -> list[Line]:
        """Render a constructor definition, member-initializer list included."""
        if not self.defines_here(ctor):
            return []

        def render_lines() -> list[Line]:
            params = self.write_params(ctx.enclosing_class_unqualified, ctor.params)
            if ctor.noexcept:
                params = add_suffix(params, " noexcept")
            if ctor.initializers:
                params = add_suffix(params, " :")
            return [
                blank(),
                *lines(f"{ctx.enclosing_class_qualified} ::"),
                *indent_lines(params),
                *initializer_lines(ctor.initializers),
                *write_function_body(ctor.body),
            ]

        return self.write_selected(ctx, ctor.cpp_file, render_lines)

    def visit_destructor(self, ctx: Context, dtor: Destructor) -> list[Line]:
        """Render a destructor definition."""
        if not self.defines_here(dtor):
            return []

        def render_lines() -> list[Line]:
            decl = lines(f"~{ctx.enclosing_class_unqualified}()")
            if dtor.noexcept:
                decl = add_suffix(decl, " noexcept")
            return [
                blank(),
                line(f"{ctx.enclosing_class_qualified} ::"),
                *indent_lines(decl),
                *write_function_body(dtor.body),
            ]

        return self.write_selected(ctx, dtor.cpp_file, render_lines)

    def visit_function(self, ctx: Context, fn: Function) -> list[Line]:
        """Render a function definition.

        A pure virtual with a body lands here as a default implementation; one without
        a body has nothing to define.
        """
        pure = fn.sv is SVQualifier.PURE_VIRTUAL
        if not self.defines_here(fn, pure_virtual=pure):
            return []

        def render_lines() -> list[Line]:
            prototype = self.write_params(fn.name, fn.params)
            if fn.const:
                prototype = add_suffix(prototype, " const")
            if fn.noexcept:
                prototype = add_suffix(prototype, " noexcept")
            ret = f"{fn.ret_type.cpp} " if fn.ret_type.cpp else ""
            body = write_function_body(fn.body)
            if ctx.class_names:
                start = [
                    line(f"{ret}{ctx.enclosing_class_qualified} ::"),
                    *indent_lines(prototype),
                ]
                content = [*start, *body]
            else:
                content = join_lists(
                    IndentMode.NO_INDENT, add_prefix(ret, prototype), " ", body
                )
            return [blank(), *content]

        return self.write_selected(ctx, fn.cpp_file, render_lines)

    def visit_variable(self, ctx: Context, v: Variable) -> list[Line]:
        """Render a variable definition, if this variable needs one out of line."""
        in_class = bool(ctx.class_names)
        _check_variable(v, in_class=in_class)
        if not variable_defined_in_source(v, in_class=in_class):
            return []

        def render_lines() -> list[Line]:
            qualifier = f"{ctx.enclosing_class_qualified}::" if in_class else ""
            if v.constexpr:
                # The initialiser stays with the in-class declaration; this definition
                # exists only to give the constant an address.
                decl = f"constexpr {v.type.cpp} {qualifier}{v.declarator}"
            else:
                lead = "const " if v.const else ""
                decl = f"{lead}{v.type.cpp} {qualifier}{v.declarator}"
                if v.init is not None:
                    decl += f" = {v.init}"
            return [blank(), *lines(f"{decl};")]

        return self.write_selected(ctx, v.cpp_file, render_lines)

    def visit_lines(self, ctx: Context, ll: Lines) -> list[Line]:
        """Emit raw lines unless they are marked header-only."""
        if ll.output is Output.HPP:
            return []
        return self.write_selected(ctx, ll.cpp_file, lambda: list(ll.content))

    def visit_namespace(self, ctx: Context, ns: Namespace) -> list[Line]:
        """Render a namespace, or nothing at all if it contributes no definitions.

        Namespaces routinely come out empty here, since a document split across
        several source files has members belonging to a different ``.cpp`` than the
        one being written.
        """
        body = self.visit_members(ctx, ns.members)
        if not body:
            return []
        return [
            blank(),
            line(_namespace_opening(ns.name)),
            *indent_lines(body),
            blank(),
            line("}"),
        ]

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def visit_doc(self, doc: CppDoc, cpp_file: str | None = None) -> list[Line]:
        """Render one source file.  ``cpp_file`` is a base name without extension."""
        output = f"{cpp_file}.cpp" if cpp_file is not None else None
        ctx = Context(doc.hpp_file, doc.cpp_file_name, output)
        out = [
            *write_banner(
                doc.file_banner, ctx.cpp_file_name, f"cpp file for {doc.description}"
            ),
            *self.visit_members(ctx, doc.members),
        ]
        return [left_align_directive(l) for l in out]


def hpp_lines(doc: CppDoc, *, writer: HppWriter | None = None) -> list[Line]:
    """Render ``doc``'s header as lines.

    ``writer`` substitutes an :class:`HppWriter` subclass for the default one, so a
    generator that overrides part of the rendering keeps every convenience path above
    this one.  Writers hold no per-document state, so one instance can render any
    number of documents.
    """
    return (writer if writer is not None else HppWriter()).visit_doc(doc)


def cpp_lines(
    doc: CppDoc, cpp_file: str | None = None, *, writer: CppWriter | None = None
) -> list[Line]:
    """Render one of ``doc``'s source files as lines.

    ``cpp_file`` is a base name without extension; ``None`` selects the document's
    default source file.  ``writer`` substitutes a :class:`CppWriter` subclass for the
    default one.
    """
    return (writer if writer is not None else CppWriter()).visit_doc(doc, cpp_file)


def render_hpp(doc: CppDoc, *, writer: HppWriter | None = None) -> str:
    """Render ``doc``'s header as file text."""
    return render(hpp_lines(doc, writer=writer))


def render_cpp(
    doc: CppDoc, cpp_file: str | None = None, *, writer: CppWriter | None = None
) -> str:
    """Render one of ``doc``'s source files as file text."""
    return render(cpp_lines(doc, cpp_file, writer=writer))
