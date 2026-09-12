"""Tests for rendering a document to files on disk."""

from __future__ import annotations

from pathlib import Path

from fprime_cpp_codegen.doc import (
    Class,
    CppDoc,
    Function,
    HppFile,
    Lines,
    Output,
    Type,
    Variable,
)
from fprime_cpp_codegen.lines import Line, line, lines
from fprime_cpp_codegen.output import collect_cpp_files, doc_files, write_doc
from fprime_cpp_codegen.writer import CppWriter, HppWriter


def build_doc() -> CppDoc:
    return CppDoc(
        description="output test",
        hpp_file=HppFile("A.hpp", "A_HPP"),
        cpp_file_name="A.cpp",
        members=[
            Lines(lines('#include "A.hpp"'), Output.CPP),
            Lines(lines('#include "A.hpp"'), Output.CPP, cpp_file="Extra"),
            Class(
                "A",
                members=[
                    Function("here", body=[line("a();")]),
                    Function("there", body=[line("b();")], cpp_file="Extra"),
                ],
            ),
        ],
    )


class TestCollectCppFiles:
    def test_supplemental_files_are_discovered(self) -> None:
        assert collect_cpp_files(build_doc()) == ["Extra"]

    def test_the_default_file_is_not_reported_as_supplemental(self) -> None:
        doc = CppDoc(
            description="d",
            hpp_file=HppFile("A.hpp", "A_HPP"),
            cpp_file_name="A.cpp",
            members=[
                Class("A", members=[Function("f", body=[line("x();")], cpp_file="A")])
            ],
        )
        assert collect_cpp_files(doc) == []

    def test_nothing_to_discover(self) -> None:
        doc = CppDoc(
            description="d",
            hpp_file=HppFile("A.hpp", "A_HPP"),
            cpp_file_name="A.cpp",
            members=[Class("A", members=[Function("f", body=[line("x();")])])],
        )
        assert collect_cpp_files(doc) == []


class TestDocFiles:
    def test_supplemental_source_files_are_discovered_by_default(self) -> None:
        # A file left unnamed would lose every definition assigned to it.
        assert set(doc_files(build_doc())) == {"A.hpp", "A.cpp", "Extra.cpp"}

    def test_discovery_can_be_suppressed_with_an_explicit_list(self) -> None:
        assert set(doc_files(build_doc(), [])) == {"A.hpp", "A.cpp"}

    def test_supplemental_source_files_are_named_by_base(self) -> None:
        files = doc_files(build_doc(), ["Extra"])
        assert set(files) == {"A.hpp", "A.cpp", "Extra.cpp"}
        assert "a();" in files["A.cpp"] and "b();" not in files["A.cpp"]
        assert "b();" in files["Extra.cpp"] and "a();" not in files["Extra.cpp"]

    def test_every_file_ends_with_a_newline(self) -> None:
        for text in doc_files(build_doc(), ["Extra"]).values():
            assert text.endswith("\n")


class TestWriters:
    """A ``DocWriter`` subclass has to reach the file-producing paths too.

    Otherwise needing one costs the caller ``write()`` -- its directory creation, its
    mtime handling and its formatter integration.
    """

    class MarkedHpp(HppWriter):
        def close_include_guard(self) -> list[Line]:
            return [line("// MARKED"), *super().close_include_guard()]

    class MarkedCpp(CppWriter):
        def visit_doc(self, doc: CppDoc, cpp_file: str | None = None) -> list[Line]:
            return [line("// MARKED"), *super().visit_doc(doc, cpp_file)]

    def test_doc_files_uses_the_given_writers(self) -> None:
        files = doc_files(
            build_doc(), hpp_writer=self.MarkedHpp(), cpp_writer=self.MarkedCpp()
        )
        assert all("// MARKED" in text for text in files.values())

    def test_supplemental_files_get_the_cpp_writer_too(self) -> None:
        files = doc_files(build_doc(), ["Extra"], cpp_writer=self.MarkedCpp())
        assert "// MARKED" in files["Extra.cpp"]
        assert "// MARKED" not in files["A.hpp"]

    def test_write_doc_uses_the_given_writers(self, tmp_path: Path) -> None:
        write_doc(build_doc(), tmp_path, hpp_writer=self.MarkedHpp())
        assert "// MARKED" in (tmp_path / "A.hpp").read_text()

    def test_the_formatter_still_runs_over_a_custom_writers_output(self) -> None:
        files = doc_files(
            build_doc(),
            hpp_writer=self.MarkedHpp(),
            formatter=lambda text, name: text.upper(),
        )
        assert "// MARKED" in files["A.hpp"]

    def test_writers_hold_no_state_between_files(self) -> None:
        # One instance renders every file, so a writer must not accumulate anything.
        writer = self.MarkedCpp()
        first = doc_files(build_doc(), ["Extra"], cpp_writer=writer)
        second = doc_files(build_doc(), ["Extra"], cpp_writer=writer)
        assert first == second


class TestEmitFlags:
    def test_suppressing_the_source_file_leaves_the_header(self) -> None:
        doc = CppDoc(
            description="d",
            hpp_file=HppFile("A.hpp", "A_HPP"),
            cpp_file_name="A.cpp",
            members=[Class("A", members=[Variable("N", Type("U32"), init="1")])],
        )
        assert set(doc_files(doc, emit_cpp=False)) == {"A.hpp"}

    def test_suppressing_the_header_leaves_the_source_file(self) -> None:
        doc = CppDoc(
            description="d",
            hpp_file=HppFile("A.hpp", "A_HPP"),
            cpp_file_name="A.cpp",
            members=[Lines(lines("int main() { return 0; }"), Output.CPP)],
        )
        assert set(doc_files(doc, emit_hpp=False)) == {"A.cpp"}

    def test_suppressing_the_source_file_suppresses_the_supplemental_ones(self) -> None:
        doc = CppDoc(
            description="d",
            hpp_file=HppFile("A.hpp", "A_HPP"),
            cpp_file_name="A.cpp",
            members=[Lines(lines("// note"), Output.BOTH, cpp_file="Extra")],
        )
        assert set(doc_files(doc, emit_cpp=False)) == {"A.hpp"}

    def test_write_doc_puts_down_only_what_it_renders(self, tmp_path: Path) -> None:
        doc = CppDoc(
            description="d",
            hpp_file=HppFile("A.hpp", "A_HPP"),
            cpp_file_name="A.cpp",
            members=[Lines(lines("int main() { return 0; }"), Output.CPP)],
        )
        result = write_doc(doc, tmp_path, emit_hpp=False)
        assert [p.name for p in result.written] == ["A.cpp"]
        assert not (tmp_path / "A.hpp").exists()


class TestWriteDoc:
    def test_writes_the_expected_files(self, tmp_path: Path) -> None:
        result = write_doc(build_doc(), tmp_path)
        assert sorted(p.name for p in result.written) == ["A.cpp", "A.hpp", "Extra.cpp"]
        assert result.unchanged == []
        assert (tmp_path / "A.hpp").read_text().startswith("// =====")

    def test_creates_the_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "gen"
        write_doc(build_doc(), target)
        assert (target / "A.hpp").is_file()

    def test_a_second_identical_run_touches_nothing(self, tmp_path: Path) -> None:
        # Build systems key off mtimes, so a no-op regeneration must not cascade
        # a rebuild through everything downstream.
        write_doc(build_doc(), tmp_path, ["Extra"])
        before = {p: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
        result = write_doc(build_doc(), tmp_path, ["Extra"])
        assert result.written == []
        assert len(result.unchanged) == 3
        assert {p: p.stat().st_mtime_ns for p in tmp_path.iterdir()} == before

    def test_changed_content_is_rewritten(self, tmp_path: Path) -> None:
        write_doc(build_doc(), tmp_path)
        (tmp_path / "A.cpp").write_text("stale\n")
        result = write_doc(build_doc(), tmp_path)
        assert [p.name for p in result.written] == ["A.cpp"]
        assert "stale" not in (tmp_path / "A.cpp").read_text()

    def test_skip_unchanged_can_be_turned_off(self, tmp_path: Path) -> None:
        write_doc(build_doc(), tmp_path)
        result = write_doc(build_doc(), tmp_path, skip_unchanged=False)
        assert len(result.written) == 3
        assert result.unchanged == []

    def test_all_lists_every_file(self, tmp_path: Path) -> None:
        write_doc(build_doc(), tmp_path)
        result = write_doc(build_doc(), tmp_path, ["Extra"])
        assert sorted(p.name for p in result.all) == ["A.cpp", "A.hpp", "Extra.cpp"]
