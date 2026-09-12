"""Tests for the whole-document checks and the one-file documents they guard.

Two things are being pinned down here: that suppressing a file names whatever it was
the only home for instead of dropping it, and that ``strict`` catches a definition a
generator started and never filled in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fprime_cpp_codegen import CppDocBuilder, Output, ValidationError
from fprime_cpp_codegen.doc import (
    Class,
    Constructor,
    CppDoc,
    Destructor,
    Function,
    HppFile,
    Lines,
    Namespace,
    SVQualifier,
    Type,
    Variable,
)
from fprime_cpp_codegen.lines import line, lines
from fprime_cpp_codegen.output import doc_files, write_doc
from fprime_cpp_codegen.validation import (
    check_document,
    orphaned_members,
    unfilled_definitions,
)

from .conftest import FPRIME_STUB_HEADERS, assert_compiles


def doc_with(*members: object) -> CppDoc:
    return CppDoc(
        description="validation test",
        hpp_file=HppFile("T.hpp", "T_HPP"),
        cpp_file_name="T.cpp",
        members=list(members),  # type: ignore[arg-type]
    )


class TestNothingIsOrphanedByDefault:
    def test_a_document_emitting_both_files_strands_nothing(self) -> None:
        d = doc_with(
            Lines(lines('#include "T.hpp"'), Output.CPP),
            Class(
                "C",
                members=[
                    Function("f", body=[line("x();")]),
                    Variable("N", Type("U32"), init="1", static=True),
                ],
            ),
        )
        assert orphaned_members(d) == []
        check_document(d)


class TestHeaderOnlyDocuments:
    """``emit_cpp=False``: everything has to fit in the header."""

    def test_an_out_of_line_definition_is_reported(self) -> None:
        d = doc_with(Class("C", members=[Function("f", body=[line("x();")])]))
        assert orphaned_members(d, emit_cpp=False) == ["function 'f' in C"]

    def test_an_inline_definition_is_not(self) -> None:
        d = doc_with(
            Class("C", members=[Function("f", body=[line("x();")], inline_body=True)])
        )
        assert orphaned_members(d, emit_cpp=False) == []

    def test_a_member_of_a_templated_class_is_not(self) -> None:
        # Every member of a templated class is defined in the header already.
        d = doc_with(
            Class(
                "C",
                template="typename T",
                members=[Function("f", body=[line("x();")])],
            )
        )
        assert orphaned_members(d, emit_cpp=False) == []

    def test_a_static_data_member_is_reported(self) -> None:
        d = doc_with(
            Class(
                "C",
                members=[Variable("s_count", Type("U32"), init="0", static=True)],
            )
        )
        assert orphaned_members(d, emit_cpp=False) == ["variable 's_count' in C"]

    def test_source_only_lines_are_reported_with_their_first_line(self) -> None:
        d = doc_with(Lines(lines('#include "T.hpp"'), Output.CPP))
        (reported,) = orphaned_members(d, emit_cpp=False)
        assert reported == "raw lines at document scope starting '#include \"T.hpp\"'"

    def test_lines_going_into_both_files_are_not_reported(self) -> None:
        d = doc_with(Lines(lines("// both"), Output.BOTH))
        assert orphaned_members(d, emit_cpp=False) == []

    def test_the_nesting_path_is_reported(self) -> None:
        d = doc_with(
            Namespace(
                "Fw",
                members=[Class("Outer", members=[Class("Inner", members=[dtor()])])],
            )
        )
        assert orphaned_members(d, emit_cpp=False) == [
            "a destructor in Fw::Outer::Inner"
        ]

    def test_a_header_only_document_renders_one_file(self) -> None:
        d = doc_with(
            Class("C", members=[Function("f", body=[line("x();")], inline_body=True)])
        )
        assert set(doc_files(d, emit_cpp=False)) == {"T.hpp"}


class TestSourceOnlyDocuments:
    """``emit_hpp=False``: the pybind11 module-initialisation case."""

    def test_a_free_function_with_a_body_survives(self) -> None:
        d = doc_with(Function("init", body=[line("x();")]))
        assert orphaned_members(d, emit_hpp=False) == []

    def test_source_only_lines_survive(self) -> None:
        d = doc_with(Lines(lines("PYBIND11_MODULE(m, h) {}"), Output.CPP))
        assert orphaned_members(d, emit_hpp=False) == []

    def test_a_class_is_reported_because_its_head_is_header_only(self) -> None:
        # The source file would get MyClass::f() with nothing declaring MyClass.
        d = doc_with(Class("C", members=[Function("f", body=[line("x();")])]))
        assert orphaned_members(d, emit_hpp=False) == ["class 'C' at document scope"]

    def test_a_struct_is_reported_as_a_struct(self) -> None:
        d = doc_with(Class("S", struct=True))
        assert orphaned_members(d, emit_hpp=False) == ["struct 'S' at document scope"]

    def test_a_reported_class_does_not_also_report_its_members(self) -> None:
        d = doc_with(Class("C", members=[Function("f"), Function("g")]))
        assert orphaned_members(d, emit_hpp=False) == ["class 'C' at document scope"]

    def test_header_only_lines_are_reported(self) -> None:
        d = doc_with(Lines(lines("// header note"), Output.HPP))
        assert len(orphaned_members(d, emit_hpp=False)) == 1

    def test_empty_lines_are_not_reported(self) -> None:
        assert orphaned_members(doc_with(Lines([], Output.HPP)), emit_hpp=False) == []

    def test_a_namespace_is_never_itself_the_orphan(self) -> None:
        d = doc_with(Namespace("Fw", members=[Function("init", body=[line("x();")])]))
        assert orphaned_members(d, emit_hpp=False) == []

    def test_an_inline_function_is_reported(self) -> None:
        # inline puts the definition in the header, which is not being emitted.
        d = doc_with(Function("f", body=[line("x();")], inline_body=True))
        assert orphaned_members(d, emit_hpp=False) == ["function 'f' at document scope"]

    def test_a_declaration_only_function_is_reported(self) -> None:
        d = doc_with(Function("f", declaration_only=True))
        assert orphaned_members(d, emit_hpp=False) == ["function 'f' at document scope"]

    def test_a_namespace_scope_constant_is_reported(self) -> None:
        d = doc_with(Variable("N", Type("U32"), init="1", constexpr=True))
        assert orphaned_members(d, emit_hpp=False) == ["variable 'N' at document scope"]

    def test_an_extern_definition_survives(self) -> None:
        d = doc_with(Variable("N", Type("U32"), init="1", extern=True))
        assert orphaned_members(d, emit_hpp=False) == []

    def test_a_source_only_document_renders_one_file(self) -> None:
        d = doc_with(Lines(lines("PYBIND11_MODULE(m, h) {}"), Output.CPP))
        assert set(doc_files(d, emit_hpp=False)) == {"T.cpp"}


class TestCheckDocument:
    def test_orphans_raise_and_the_message_names_them(self) -> None:
        d = doc_with(Class("C", members=[Function("f", body=[line("x();")])]))
        with pytest.raises(ValidationError, match="class 'C' at document scope"):
            check_document(d, emit_hpp=False)

    def test_the_message_says_which_file_is_missing(self) -> None:
        d = doc_with(Class("C", members=[Function("f", body=[line("x();")])]))
        with pytest.raises(ValidationError, match="does not emit a source file"):
            check_document(d, emit_cpp=False)

    def test_emitting_neither_file_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="neither a header nor a source"):
            check_document(doc_with(), emit_hpp=False, emit_cpp=False)

    def test_a_long_list_is_capped(self) -> None:
        d = doc_with(*(Class(f"C{i}") for i in range(15)))
        with pytest.raises(ValidationError, match="and 5 more"):
            check_document(d, emit_hpp=False)

    def test_doc_files_runs_the_check(self) -> None:
        d = doc_with(Class("C", members=[Function("f", body=[line("x();")])]))
        with pytest.raises(ValidationError, match="class 'C'"):
            doc_files(d, emit_hpp=False)

    def test_write_doc_runs_the_check_before_touching_the_directory(
        self, tmp_path: Path
    ) -> None:
        d = doc_with(Class("C", members=[Function("f", body=[line("x();")])]))
        target = tmp_path / "gen"
        with pytest.raises(ValidationError):
            write_doc(d, target, emit_hpp=False)
        assert not target.exists()


class TestUnfilledDefinitions:
    def test_a_definition_with_no_body_is_reported(self) -> None:
        assert unfilled_definitions(doc_with(Function("f"))) == [
            "function 'f' at document scope"
        ]

    def test_a_filled_definition_is_not(self) -> None:
        assert unfilled_definitions(doc_with(Function("f", body=[line("x();")]))) == []

    def test_declaration_only_is_not(self) -> None:
        assert (
            unfilled_definitions(doc_with(Function("f", declaration_only=True))) == []
        )

    def test_deleted_and_defaulted_are_not(self) -> None:
        d = doc_with(Class("C", members=[ctor(deleted=True), dtor(defaulted=True)]))
        assert unfilled_definitions(d) == []

    def test_a_pure_virtual_without_a_body_is_not(self) -> None:
        d = doc_with(Class("C", members=[Function("f", sv=SVQualifier.PURE_VIRTUAL)]))
        assert unfilled_definitions(d) == []

    def test_a_pure_virtual_with_a_body_is_checked_like_any_other(self) -> None:
        d = doc_with(
            Class(
                "C",
                members=[
                    Function("f", sv=SVQualifier.PURE_VIRTUAL, body=[line("x();")])
                ],
            )
        )
        assert unfilled_definitions(d) == []

    def test_an_empty_body_string_counts_as_filled(self) -> None:
        # body="" is the escape for a deliberately empty definition, and renders
        # exactly as an unfilled one does.
        deliberate = CppDocBuilder("T", strict=True)
        with deliberate.class_("C") as cls:
            cls.destructor(body="")
        blank = CppDocBuilder("T")
        with blank.class_("C") as cls:
            cls.destructor()
        assert deliberate.render_cpp() == blank.render_cpp()

    def test_the_check_is_off_unless_asked_for(self) -> None:
        check_document(doc_with(Function("f")))


class TestStrictOnTheBuilder:
    def test_an_unfilled_definition_is_rejected(self) -> None:
        d = CppDocBuilder("T", strict=True)
        d.class_("C").function("f")
        with pytest.raises(ValidationError, match="need a body but have none"):
            d.render_hpp()

    def test_the_message_points_at_the_escapes(self) -> None:
        d = CppDocBuilder("T", strict=True)
        d.function("f")
        with pytest.raises(ValidationError, match="declaration_only=True"):
            d.build()

    def test_without_strict_it_is_the_hand_filled_stub_shape(self) -> None:
        d = CppDocBuilder("T")
        d.function("f")
        assert "void f() {" in d.render_cpp()


class TestDeclarationOnly:
    def test_the_header_declares_and_no_source_file_defines(self) -> None:
        d = CppDocBuilder("T")
        d.function("f", ret="U32", declaration_only=True)
        assert "U32 f();" in d.render_hpp()
        assert "f()" not in d.render_cpp()

    def test_a_member_function_works_the_same_way(self) -> None:
        d = CppDocBuilder("T")
        with d.class_("C") as cls:
            cls.function("f", declaration_only=True)
        assert "void f();" in d.render_hpp()
        assert "C ::" not in d.render_cpp()

    def test_a_body_alongside_it_is_rejected(self) -> None:
        d = CppDocBuilder("T")
        d.function("f", declaration_only=True, body="x();")
        with pytest.raises(ValidationError, match="declaration-only"):
            d.render_hpp()

    def test_deleted_alongside_it_is_rejected(self) -> None:
        d = CppDocBuilder("T")
        with d.class_("C") as cls:
            cls.constructor(declaration_only=True, deleted=True)
        with pytest.raises(ValidationError, match="both"):
            d.render_hpp()

    def test_a_declaration_only_destructor_compiles(self) -> None:
        # Nothing instantiates it, so the missing definition is not a link error.
        d = CppDocBuilder("T", description="declaration only")
        with d.class_("C") as cls:
            with cls.public():
                cls.constructor(declaration_only=True)
                cls.destructor(declaration_only=True)
        assert_compiles(d.files())


class TestOneFileDocumentsFromTheBuilder:
    def test_a_source_only_document_emits_one_file(self) -> None:
        d = CppDocBuilder("Module", emit_hpp=False, description="a python module")
        d.include("pybind11/pybind11.h", output=Output.CPP)
        d.lines("PYBIND11_MODULE(mod, m) {}", output=Output.CPP)
        assert set(d.files()) == {"Module.cpp"}

    def test_rendering_the_suppressed_file_is_an_error(self) -> None:
        d = CppDocBuilder("Module", emit_hpp=False)
        with pytest.raises(ValidationError, match="no hpp file to render"):
            d.render_hpp()

    def test_a_header_only_document_emits_one_file(self) -> None:
        d = CppDocBuilder("Consts", emit_cpp=False)
        d.var("U32", "N", init="1", constexpr=True)
        assert set(d.files()) == {"Consts.hpp"}

    def test_rendering_the_suppressed_source_file_is_an_error(self) -> None:
        d = CppDocBuilder("Consts", emit_cpp=False)
        with pytest.raises(ValidationError, match="no cpp file to render"):
            d.render_cpp()

    def test_a_stranded_member_is_named_rather_than_dropped(self) -> None:
        d = CppDocBuilder("Module", emit_hpp=False)
        with d.class_("Helper") as cls:
            cls.function("f", body="x();")
        with pytest.raises(ValidationError, match="class 'Helper'"):
            d.files()

    def test_write_puts_down_only_the_emitted_file(self, tmp_path: Path) -> None:
        d = CppDocBuilder("Module", emit_hpp=False)
        d.lines("PYBIND11_MODULE(mod, m) {}", output=Output.CPP)
        result = d.write(tmp_path)
        assert [p.name for p in result.written] == ["Module.cpp"]
        assert not (tmp_path / "Module.hpp").exists()


class TestRealisticOneFileDocuments:
    """The two shapes the flags exist for, end to end.

    Access sections and preprocessor guards repeat themselves into whichever files
    hold the members they decorate, so a document that is only one file is where that
    machinery is most likely to strand a copy.
    """

    def test_a_header_only_class_with_sections_and_a_guard(self) -> None:
        d = CppDocBuilder("Cfg", emit_cpp=False, description="header-only config")
        d.include("Fw/FPrimeBasicTypes.hpp")
        with d.namespace("Fw") as ns:
            with ns.class_("Cfg", comment="Config") as cls:
                with cls.public("Types"):
                    kind = cls.enum_class("Kind", underlying="U8")
                    kind.constant("A", 0, comment="first")
                with cls.public("Public member functions"):
                    cls.function(
                        "n", ret="U32", inline_body=True, body="return 1;", comment="n"
                    )
                    with cls.if_directive("#if FW_EXTRA"):
                        cls.function("extra", inline_body=True, body="(void) 0;")
                with cls.private("Member variables"):
                    cls.var("U32", "m_x")
        files = d.files()
        assert set(files) == {"Cfg.hpp"}
        assert "Types" in files["Cfg.hpp"] and "#if FW_EXTRA" in files["Cfg.hpp"]
        assert_compiles(
            {**files, "main.cpp": '#include "Cfg.hpp"\nint main() {}\n'},
            stubs=FPRIME_STUB_HEADERS,
        )

    def test_a_source_only_module_compiles(self) -> None:
        d = CppDocBuilder(
            "Module", emit_hpp=False, strict=True, description="a module initialiser"
        )
        d.system_include("cstdio", output=Output.CPP)
        init = d.function("init_Demo", params=[("int&", "registry")])
        init.body.line("(void) registry;")
        d.lines(
            """
            |int main() {
            |  int r = 0;
            |  init_Demo(r);
            |}""",
            output=Output.CPP,
        )
        files = d.files()
        assert set(files) == {"Module.cpp"}
        assert_compiles(files)


def ctor(**kwargs: object) -> Constructor:
    return Constructor(**kwargs)  # type: ignore[arg-type]


def dtor(**kwargs: object) -> Destructor:
    return Destructor(**kwargs)  # type: ignore[arg-type]
