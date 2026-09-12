# fprime-cpp-codegen

A Python package for generating C++ code for F Prime.

It builds C++ documents — one `.hpp` plus one or more `.cpp` files — through a
Builder-pattern API, where nesting in the generated C++ follows nesting in the
Python. It generates general-purpose C++: classes, structs, templates, namespaces,
enums, free functions, statements. Nothing in it knows about the FPP model, and it
has no runtime dependencies.

## Installation

```sh
pip install git+https://github.com/fprime-community/fprime-cpp-codegen.git
```

Requires Python 3.10 or newer.

## Quick start

```python
from fprime_cpp_codegen import CppDocBuilder, Output

doc = CppDocBuilder("Ring", description="a fixed-capacity ring buffer",
                    namespaces=["Demo"], tool_name="my-generator")
doc.include("Fw/FPrimeBasicTypes.hpp")
doc.include("Ring.hpp", output=Output.CPP)

with doc.namespace("Demo") as ns:
    with ns.class_("Ring", comment="A ring buffer of fixed capacity") as cls:
        with cls.public("Constructors and destructors"):
            ctor = cls.constructor(explicit=True, comment="Construct an empty ring")
            ctor.param("U32", "capacity", comment="The capacity")
            ctor.init("m_head(0)", "m_size(0)", "m_capacity(capacity)")

        with cls.public("Public member functions"):
            push = cls.function("push", ret="bool", comment="Append one item")
            push.param("U32", "item", comment="The item to append")
            with push.body as b:
                with b.if_("m_size == m_capacity"):
                    b.line("return false;")
                b.line("m_data[(m_head + m_size) % CAPACITY] = item;")
                b.line("m_size++;")
                b.line("return true;")

            cls.function("size", ret="U32", const=True, inline=True,
                         body="return m_size;", comment="How many items are stored")

        with cls.private("Member variables"):
            cls.var("U32", "CAPACITY", init="64", static=True, constexpr=True)
            cls.var("U32", "m_data", array="CAPACITY")
            cls.var("U32", "m_head")
            cls.var("U32", "m_size")
            cls.var("U32", "m_capacity", const=True)

doc.write("build-artifacts")
```

`write()` puts `Ring.hpp` and `Ring.cpp` in `build-artifacts/`, declarations in the
one and definitions in the other. `render_hpp()` / `render_cpp()` return the text
instead, and `files()` returns every file as a name-to-text mapping.

Generated files can optionally be passed through `clang-format`, which needs no
compilation database or include paths — it is purely lexical, so standalone text is
fine. Note that it discards the F Prime autocoder's own layout.

```python
from fprime_cpp_codegen import ClangFormat

doc.write("build-artifacts", formatter=ClangFormat())   # or style="LLVM"
```

Any `Callable[[str, str], str]` taking `(text, file_name)` works as a formatter.

`with` is optional throughout — a builder attaches to its parent as soon as you
create it, so you can keep filling it in afterwards. It is worth using on access
sections and preprocessor guards, which delete themselves when nothing lands
inside them.

## Text that comes from your model

Multi-line strings are margin-stripped: on each line, leading whitespace followed by
a `|` is dropped, so a block of C++ can be indented to match the Python around it.
That is convenient for literals written by hand and a hazard for text a generator
derives from its input — an FPP annotation used as a doc comment, a C++ expression
whose continuation line starts with `|`, would silently lose that character.

Three escapes, in order of preference:

```python
doc.lines(expression, margin=None)          # no stripping at all
body.line(expression)                       # one line, never stripped
cls.function("f", comment=lines(text, margin=None))   # comments take Lines, too
```

Every `comment=` argument accepts either a string, which is stripped, or a
`Sequence[Line]`, which is not. `Body.line()` and `Body.raw()` never strip;
`Body.lines()` and the scope-level `lines()` take `margin=None`. Doubling the marker
(`||x`) also works, since only the first one per line is removed.

Separately, a line whose text begins with a recognised preprocessor directive —
`#include`, `#if`, `#pragma` and the rest — is forced to column zero, wherever in the
document it sits. Content that merely starts with `#`, such as a Markdown heading
inside a C++ string literal, keeps its indentation. A real directive that has to keep
its column carries the spaces in the text (`line("  #include <x>")`) rather than in
the line's indent.

## Extension points

Declarations take attributes, which is what a shared object's exported symbols need.
On a class they land between the keyword and the name, leaving the name — and so the
constructor, the destructor and every `MyComp ::` qualifier — untouched:

```python
cls = ns.class_("MyComp", extends="public MyCompComponentBase",
                attributes='__attribute__((visibility("default")))')
cls.function("get", ret="U32", attributes="[[nodiscard]]", body="return m_v;")
```

A document does not have to be two files. `emit_hpp=False` gives a standalone
translation unit — a `PYBIND11_MODULE` block with no header to declare — and
`emit_cpp=False` a header-only one. Either way, anything the dropped file was the
only home for raises a `ValidationError` naming it, rather than disappearing:

```python
doc = CppDocBuilder("MyCompModule", emit_hpp=False, strict=True)
```

`strict=True` additionally rejects a definition that needs a body and has none, which
otherwise renders as an empty out-of-line definition — valid C++, and so easy for a
generator to emit by accident. Say `declaration_only=True` for a header-only
declaration, or `body=""` for a definition that is deliberately empty.
`fprime_cpp_codegen.validation` reports both classes of problem without raising.

To change how something renders, subclass `HppWriter` or `CppWriter` and pass the
instance in. Every output path takes one, so overriding a single method costs you
nothing else — `write()` keeps its directory creation, its unchanged-file mtime
handling and its formatter:

```python
class GuardlessHpp(HppWriter):
    def open_include_guard(self, guard: str) -> list[Line]:
        return lines("#pragma once")

    def close_include_guard(self) -> list[Line]:
        return []

doc = CppDocBuilder("MyComp", hpp_writer=GuardlessHpp())
doc.write("build-artifacts")     # or pass writer= / hpp_writer= per call
```

## Examples

Run any of these to print the C++ they generate, or pass a directory to write it:

```sh
python examples/ring_buffer.py           # print both files
python examples/ring_buffer.py build-dir # write them out
```

| Script                                          | What it covers                                                                                        |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| [`ring_buffer.py`](examples/ring_buffer.py)     | The class above, in full. Start here.                                                                 |
| [`fpp_constants.py`](examples/fpp_constants.py) | A document with no class in it: constants at namespace scope, split across the two files by `extern`. |
| [`fpp_enum.py`](examples/fpp_enum.py)           | A port of FPP's enum autocoder — the biggest one, and the closest to a real generator.                |

The two `fpp_*` scripts are ports of [`fpp-to-cpp`](https://github.com/nasa/fpp)'s
own autocoders, driven by a small Python data class in place of the FPP model. Both
are checked against unmodified reference output from `fpp`'s test suite, kept in
[`tests/goldens/fpp/`](tests/goldens/fpp), and reproduce it byte for byte — bar two
lines in the enum header where upstream's own indentation is inconsistent.

## Development

```sh
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python -m mypy    # strict
.venv/bin/python -m black src tests examples
```

Formatting is `black` with its default settings, as F Prime uses.

The compile-check tests need a C++ compiler on `PATH` (`g++`, `clang++` or `c++`)
and skip themselves if there is none.
