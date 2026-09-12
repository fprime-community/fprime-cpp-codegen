"""Generate C++ header and source files from Python.

The package is layered, and you can enter at whichever level suits the job:

* :mod:`~fprime_cpp_codegen.builder` -- the builder API.  Start with
  :class:`CppDocBuilder`.
* :mod:`~fprime_cpp_codegen.body` -- :class:`Body`, for function bodies.
* :mod:`~fprime_cpp_codegen.doc` -- the document IR, to build the tree directly.
* :mod:`~fprime_cpp_codegen.writer` -- the visitors rendering the IR to lines.
* :mod:`~fprime_cpp_codegen.comments` -- comment and banner formatting.
* :mod:`~fprime_cpp_codegen.lines` -- the line model everything is built on.
* :mod:`~fprime_cpp_codegen.output` -- rendering to text and to disk.
* :mod:`~fprime_cpp_codegen.validation` -- whole-document checks.
* :mod:`~fprime_cpp_codegen.formatting` -- optional post-processing through
  ``clang-format``.
* :mod:`~fprime_cpp_codegen.fprime` -- F Prime conventions.  Import it explicitly;
  nothing else in the package depends on it.

Nothing here knows about the FPP model.

A minimal example::

    from fprime_cpp_codegen import CppDocBuilder

    doc = CppDocBuilder("Greeter", description="a greeter", namespaces=["Demo"])
    doc.include("Fw/FPrimeBasicTypes.hpp")

    with doc.namespace("Demo") as ns:
        with ns.class_("Greeter") as cls:
            with cls.public():
                fn = cls.function("greet", params=[("const char*", "name")])
                fn.body.line('printf("hello %s\\n", name);')

    print(doc.render_hpp())
    print(doc.render_cpp())
"""

from __future__ import annotations

from .body import Body, Code, Switch, stmts
from .builder import (
    AccessSection,
    ClassBuilder,
    ConstructorBuilder,
    CppDocBuilder,
    DestructorBuilder,
    EnumBuilder,
    FunctionBuilder,
    NamespaceBuilder,
    Radix,
)
from .doc import (
    VOID,
    Class,
    ClassMember,
    Comment,
    Constructor,
    CppDoc,
    DefaultFileBanner,
    Definition,
    Destructor,
    FileBanner,
    Function,
    HppFile,
    Lines,
    Member,
    Namespace,
    Output,
    Param,
    SVQualifier,
    Type,
    Variable,
    as_type,
)
from .errors import CppCodegenError, ScopeError, ValidationError
from .formatting import ClangFormat, Formatter
from .lines import (
    INDENT_INCREMENT,
    IndentMode,
    Line,
    blank,
    line,
    lines,
    render,
    wrap_in_scope,
)
from .output import WriteResult, collect_cpp_files, doc_files, write_doc
from .validation import check_document, orphaned_members, unfilled_definitions
from .writer import (
    Context,
    CppWriter,
    DocWriter,
    HppWriter,
    cpp_lines,
    hpp_lines,
    render_cpp,
    render_hpp,
)

__all__ = [
    # Line model
    "INDENT_INCREMENT",
    "IndentMode",
    "Line",
    "blank",
    "line",
    "lines",
    "render",
    "wrap_in_scope",
    # Document IR
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
    "Radix",
    "SVQualifier",
    "Type",
    "Variable",
    "as_type",
    # Builders
    "AccessSection",
    "Body",
    "ClassBuilder",
    "Code",
    "ConstructorBuilder",
    "CppDocBuilder",
    "DestructorBuilder",
    "EnumBuilder",
    "FunctionBuilder",
    "NamespaceBuilder",
    "Switch",
    "stmts",
    # Writers
    "Context",
    "CppWriter",
    "DocWriter",
    "HppWriter",
    "cpp_lines",
    "hpp_lines",
    "render_cpp",
    "render_hpp",
    # Output
    "ClangFormat",
    "Formatter",
    "WriteResult",
    "collect_cpp_files",
    "doc_files",
    "write_doc",
    # Validation
    "check_document",
    "orphaned_members",
    "unfilled_definitions",
    # Errors
    "CppCodegenError",
    "ScopeError",
    "ValidationError",
]
