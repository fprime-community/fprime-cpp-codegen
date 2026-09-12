"""Turning a document into files on disk.

A file whose contents already match is left alone, keeping its mtime stable so a
no-op regeneration does not cascade a rebuild downstream.  Pass
``skip_unchanged=False`` to always write.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .doc import Class, ClassMember, CppDoc, Member, Namespace
from .formatting import Formatter
from .validation import check_document
from .writer import CppWriter, HppWriter, render_cpp, render_hpp

__all__ = ["WriteResult", "collect_cpp_files", "doc_files", "write_doc"]


@dataclass(frozen=True)
class WriteResult:
    """What :func:`write_doc` did."""

    written: list[Path] = field(default_factory=list)
    """Files created or updated."""

    unchanged: list[Path] = field(default_factory=list)
    """Files that already had the right contents and were left alone."""

    @property
    def all(self) -> list[Path]:
        """Every file the document owns, written or not, in generation order."""
        return sorted([*self.written, *self.unchanged])


def collect_cpp_files(doc: CppDoc) -> list[str]:
    """Find every supplemental source file ``doc`` assigns definitions to.

    Returns base names without extensions, in the order they first appear, and never
    the document's own default file.  Rendering uses this to discover its own
    outputs; a file left unnamed would lose every definition assigned to it.
    """
    default_base = doc.cpp_file_name.rsplit(".", 1)[0]
    found: list[str] = []

    def visit(members: Sequence[Member | ClassMember]) -> None:
        for m in members:
            base = getattr(m, "cpp_file", None)
            if base is not None and base != default_base and base not in found:
                found.append(base)
            if isinstance(m, (Class, Namespace)):
                visit(m.members)

    visit(doc.members)
    return found


def doc_files(
    doc: CppDoc,
    cpp_files: Sequence[str] | None = None,
    *,
    formatter: Formatter | None = None,
    hpp_writer: HppWriter | None = None,
    cpp_writer: CppWriter | None = None,
    emit_hpp: bool = True,
    emit_cpp: bool = True,
) -> dict[str, str]:
    """Render a document to a mapping of file name to text.

    Produces the header and the document's default source file.  ``cpp_files`` names
    additional source files by base name, without extension; each gets only the
    definitions assigned to it.  Left as ``None``, the supplemental files are
    discovered from the document itself.

    ``formatter`` post-processes each file, receiving its text and its name; see
    :mod:`fprime_cpp_codegen.formatting`.  ``hpp_writer`` and ``cpp_writer``
    substitute :class:`~fprime_cpp_codegen.writer.DocWriter` subclasses for the
    default writers.

    ``emit_hpp=False`` or ``emit_cpp=False`` drops that half of the output, for a
    document that is only ever one file -- a translation unit holding nothing but a
    module-initialisation block, say.  Anything the dropped file was the only home
    for raises :class:`~fprime_cpp_codegen.errors.ValidationError` rather than
    disappearing; see :func:`fprime_cpp_codegen.validation.orphaned_members`.
    """
    check_document(doc, emit_hpp=emit_hpp, emit_cpp=emit_cpp)
    out: dict[str, str] = {}
    if emit_hpp:
        out[doc.hpp_file.name] = render_hpp(doc, writer=hpp_writer)
    if emit_cpp:
        if cpp_files is None:
            cpp_files = collect_cpp_files(doc)
        out[doc.cpp_file_name] = render_cpp(doc, writer=cpp_writer)
        for base in cpp_files:
            out[f"{base}.cpp"] = render_cpp(doc, base, writer=cpp_writer)
    if formatter is not None:
        out = {name: formatter(text, name) for name, text in out.items()}
    return out


def write_doc(
    doc: CppDoc,
    directory: str | Path = ".",
    cpp_files: Sequence[str] | None = None,
    *,
    formatter: Formatter | None = None,
    hpp_writer: HppWriter | None = None,
    cpp_writer: CppWriter | None = None,
    emit_hpp: bool = True,
    emit_cpp: bool = True,
    skip_unchanged: bool = True,
    encoding: str = "utf-8",
) -> WriteResult:
    """Write a document's header and source files into ``directory``.

    The directory is created if it does not exist.  See :func:`doc_files` for how
    ``cpp_files`` selects supplemental source files and what ``formatter``, the two
    writers and the two ``emit_`` flags do.

    Formatting happens before the unchanged check, so a file already holding the
    formatted text is still left alone.

    Everything is rendered before anything is written, so a document that fails
    validation leaves the directory as it found it.
    """
    rendered = doc_files(
        doc,
        cpp_files,
        formatter=formatter,
        hpp_writer=hpp_writer,
        cpp_writer=cpp_writer,
        emit_hpp=emit_hpp,
        emit_cpp=emit_cpp,
    )
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    unchanged: list[Path] = []
    for name, text in rendered.items():
        path = root / name
        if (
            skip_unchanged
            and path.is_file()
            and path.read_text(encoding=encoding) == text
        ):
            unchanged.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding)
        written.append(path)
    return WriteResult(written, unchanged)
