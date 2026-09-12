"""The document scope: one header plus one or more source files, and their output."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from ..doc import CppDoc, FileBanner, HppFile
from ..errors import ValidationError
from ..formatting import Formatter
from ..output import WriteResult, doc_files, write_doc
from ..validation import check_document
from ..writer import CppWriter, HppWriter, render_cpp, render_hpp
from .base import _DocContext
from .scopes import _MemberScope


class CppDocBuilder(_MemberScope[CppDoc]):
    """A whole C++ document: one header and one or more source files."""

    def __init__(
        self,
        file_base: str,
        *,
        description: str | None = None,
        include_guard: str | None = None,
        namespaces: Sequence[str] = (),
        tool_name: str | None = None,
        file_banner: FileBanner | None = None,
        formatter: Formatter | None = None,
        hpp_writer: HppWriter | None = None,
        cpp_writer: CppWriter | None = None,
        hpp_extension: str = "hpp",
        cpp_extension: str = "cpp",
        emit_hpp: bool = True,
        emit_cpp: bool = True,
        strict: bool = False,
    ) -> None:
        """Start a document whose files are named after ``file_base``.

        ``include_guard`` defaults to one derived from ``file_base`` and
        ``namespaces``; ``namespaces`` is used for nothing else, so pass it when you
        want ``Fw_Cfg_MyClass_HPP`` without spelling the macro out.

        ``formatter`` post-processes every file this document renders; see
        :mod:`fprime_cpp_codegen.formatting`.  Any render or write call can override
        it, but cannot switch it off.  ``hpp_writer`` and ``cpp_writer`` work the same
        way, substituting a :class:`~fprime_cpp_codegen.writer.DocWriter` subclass for
        the default rendering.

        ``emit_hpp=False`` or ``emit_cpp=False`` makes this a one-file document, which
        a translation unit holding only a module-initialisation block wants.  Members
        that would then have nowhere to go raise :class:`ValidationError` when the
        document is built, rather than disappearing.

        ``strict=True`` additionally rejects any definition that needs a body and has
        none, which would otherwise render as an empty out-of-line definition -- valid
        C++, and so easy for a generator to emit by accident.  Say
        ``declaration_only=True`` to declare without defining, or ``body=""`` for a
        definition that is deliberately empty.
        """
        super().__init__(_DocContext())
        if not file_base:
            raise ValidationError("a document needs a file name base")
        self.file_base = file_base
        self.description = description if description is not None else file_base
        self.hpp_extension = hpp_extension
        self.cpp_extension = cpp_extension
        self.tool_name = tool_name
        self.formatter = formatter
        """Applied to every file this document renders, unless a call overrides it."""

        self.hpp_writer = hpp_writer
        """Renders the header, unless a call overrides it.  ``None`` uses
        :class:`~fprime_cpp_codegen.writer.HppWriter`."""

        self.cpp_writer = cpp_writer
        """Renders the source files, unless a call overrides it.  ``None`` uses
        :class:`~fprime_cpp_codegen.writer.CppWriter`."""

        self.emit_hpp = emit_hpp
        """Whether this document produces a header at all."""

        self.emit_cpp = emit_cpp
        """Whether this document produces any source file at all."""

        self.strict = strict
        """Whether :meth:`build` rejects a definition that needs a body and has none."""

        self.file_banner = file_banner
        """Overrides the ``\\title``/``\\author``/``\\brief`` block atop each file.
        Distinct from :meth:`banner`, which emits a section comment."""

        self.include_guard = (
            include_guard
            if include_guard is not None
            else _default_guard(file_base, namespaces, hpp_extension)
        )

    @property
    def hpp_name(self) -> str:
        """The header file name, e.g. ``"MyClass.hpp"``."""
        return f"{self.file_base}.{self.hpp_extension}"

    @property
    def cpp_name(self) -> str:
        """The default source file name, e.g. ``"MyClass.cpp"``."""
        return f"{self.file_base}.{self.cpp_extension}"

    def build(self) -> CppDoc:
        """Produce the IR, checking it against ``emit_hpp``/``emit_cpp``/``strict``."""
        doc = CppDoc(
            description=self.description,
            hpp_file=HppFile(self.hpp_name, self.include_guard),
            cpp_file_name=self.cpp_name,
            members=self._built_members(),
            tool_name=self.tool_name,
            banner=self.file_banner,
        )
        check_document(
            doc,
            emit_hpp=self.emit_hpp,
            emit_cpp=self.emit_cpp,
            strict=self.strict,
        )
        return doc

    # -- output -------------------------------------------------------

    def _formatter(self, override: Formatter | None) -> Formatter | None:
        return override if override is not None else self.formatter

    def _hpp_writer(self, override: HppWriter | None) -> HppWriter | None:
        return override if override is not None else self.hpp_writer

    def _cpp_writer(self, override: CppWriter | None) -> CppWriter | None:
        return override if override is not None else self.cpp_writer

    def _require_emitted(self, which: str) -> None:
        """Reject rendering a file this document was told not to produce."""
        if not (self.emit_hpp if which == "hpp" else self.emit_cpp):
            raise ValidationError(
                f"this document was built with emit_{which}=False, so it has no "
                f"{which} file to render"
            )

    def render_hpp(
        self,
        *,
        formatter: Formatter | None = None,
        writer: HppWriter | None = None,
    ) -> str:
        """Render the header as text."""
        self._require_emitted("hpp")
        text = render_hpp(self.build(), writer=self._hpp_writer(writer))
        chosen = self._formatter(formatter)
        return chosen(text, self.hpp_name) if chosen else text

    def render_cpp(
        self,
        cpp_file: str | None = None,
        *,
        formatter: Formatter | None = None,
        writer: CppWriter | None = None,
    ) -> str:
        """Render one source file as text.  ``None`` selects the default one."""
        self._require_emitted("cpp")
        text = render_cpp(self.build(), cpp_file, writer=self._cpp_writer(writer))
        chosen = self._formatter(formatter)
        if not chosen:
            return text
        name = f"{cpp_file}.{self.cpp_extension}" if cpp_file else self.cpp_name
        return chosen(text, name)

    def files(
        self,
        cpp_files: Sequence[str] | None = None,
        *,
        formatter: Formatter | None = None,
        hpp_writer: HppWriter | None = None,
        cpp_writer: CppWriter | None = None,
    ) -> dict[str, str]:
        """Render every file this document owns, as a name-to-text mapping."""
        return doc_files(
            self.build(),
            cpp_files,
            formatter=self._formatter(formatter),
            hpp_writer=self._hpp_writer(hpp_writer),
            cpp_writer=self._cpp_writer(cpp_writer),
            emit_hpp=self.emit_hpp,
            emit_cpp=self.emit_cpp,
        )

    def write(
        self,
        directory: str | Path = ".",
        cpp_files: Sequence[str] | None = None,
        *,
        formatter: Formatter | None = None,
        hpp_writer: HppWriter | None = None,
        cpp_writer: CppWriter | None = None,
        skip_unchanged: bool = True,
        encoding: str = "utf-8",
    ) -> WriteResult:
        """Write every file this document owns into ``directory``.

        Supplemental source files are discovered automatically.
        """
        return write_doc(
            self.build(),
            directory,
            cpp_files,
            formatter=self._formatter(formatter),
            hpp_writer=self._hpp_writer(hpp_writer),
            cpp_writer=self._cpp_writer(cpp_writer),
            emit_hpp=self.emit_hpp,
            emit_cpp=self.emit_cpp,
            skip_unchanged=skip_unchanged,
            encoding=encoding,
        )

    def __enter__(self) -> CppDocBuilder:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _default_guard(
    file_base: str, namespaces: Sequence[str], hpp_extension: str
) -> str:
    """Derive an include-guard macro from the file base, namespaces and extension.

    ``_default_guard("MyClass", ["Fw", "Cfg"], "hpp")`` gives ``"Fw_Cfg_MyClass_HPP"``.
    Namespace arguments may themselves be qualified with ``::`` or ``.``.
    """
    parts = [part for ns in namespaces for part in re.split(r"::|\.", ns) if part]
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", "_".join([*parts, file_base])).strip("_")
    return f"{ident}_{hpp_extension.upper()}"
