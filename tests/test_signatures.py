"""The scope methods must keep the signatures of the builders they construct.

:meth:`ClassBuilder.function` and friends spell out every parameter of the builder
they forward to, instead of taking ``**kwargs``, so that an editor and a type checker
can see them.  The cost of that is duplication, and the risk is drift: a parameter
added to :class:`FunctionBuilder` and not to :meth:`ClassBuilder.function` is
invisible from the API everyone actually uses.

These tests compare the two signatures parameter by parameter -- name, annotation and
default -- and fail on any difference the deliberate exclusions do not explain.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest

from fprime_cpp_codegen.builder import (
    ClassBuilder,
    ConstructorBuilder,
    DestructorBuilder,
    FunctionBuilder,
)
from fprime_cpp_codegen.builder.scopes import _MemberScope

#: Parameters that exist to wire a builder to its parent and are supplied by the
#: scope, so a caller never passes them.
INTERNAL = frozenset({"self", "ctx", "type_qualifier"})

#: Qualifiers that only mean something for a member function, and so are absent from
#: the namespace-scope variant.
CLASS_ONLY = frozenset({"const", "virtual", "pure_virtual", "override", "final"})


def parameters(f: Callable[..., Any]) -> dict[str, tuple[Any, Any]]:
    """Map each of ``f``'s parameters to its annotation and default."""
    return {
        name: (p.annotation, p.default)
        for name, p in inspect.signature(f).parameters.items()
        if name not in INTERNAL
    }


def assert_forwards(
    method: Callable[..., Any],
    builder: type,
    *,
    without: frozenset[str] = frozenset(),
    overridden: frozenset[str] = frozenset(),
) -> None:
    """Assert ``method`` exposes exactly ``builder``'s parameters.

    ``without`` names parameters the method deliberately drops; ``overridden`` names
    ones it keeps but fixes to a different default, as ``struct_`` does with
    ``struct``.
    """
    expected = parameters(builder.__init__)
    actual = parameters(method)
    assert set(actual) == set(expected) - without, (
        f"{method.__qualname__} and {builder.__name__} disagree on which parameters "
        "exist"
    )
    for name, (annotation, default) in actual.items():
        if name in overridden:
            continue
        assert (annotation, default) == expected[name], (
            f"{method.__qualname__} declares {name} as {annotation!r} = {default!r}, "
            f"but {builder.__name__} declares it as {expected[name][0]!r} = "
            f"{expected[name][1]!r}"
        )


class TestClassMembers:
    def test_function_forwards_every_function_parameter(self) -> None:
        assert_forwards(ClassBuilder.function, FunctionBuilder)

    def test_constructor_forwards_every_constructor_parameter(self) -> None:
        assert_forwards(ClassBuilder.constructor, ConstructorBuilder)

    def test_destructor_forwards_every_destructor_parameter(self) -> None:
        assert_forwards(ClassBuilder.destructor, DestructorBuilder)

    def test_nested_class_forwards_every_class_parameter(self) -> None:
        assert_forwards(ClassBuilder.class_, ClassBuilder)

    def test_nested_struct_forwards_every_class_parameter_but_struct(self) -> None:
        assert_forwards(
            ClassBuilder.struct_, ClassBuilder, without=frozenset({"struct"})
        )


class TestNamespaceMembers:
    def test_function_forwards_all_but_the_class_only_qualifiers(self) -> None:
        assert_forwards(_MemberScope.function, FunctionBuilder, without=CLASS_ONLY)

    def test_class_forwards_every_class_parameter(self) -> None:
        assert_forwards(_MemberScope.class_, ClassBuilder)

    def test_struct_forwards_every_class_parameter_but_struct(self) -> None:
        assert_forwards(
            _MemberScope.struct_, ClassBuilder, without=frozenset({"struct"})
        )


class TestNoPassthroughKwargs:
    """No public builder method may take ``**kwargs`` again.

    That is what made the parameters invisible in the first place, so it is worth a
    test rather than a comment.
    """

    @pytest.mark.parametrize(
        "owner",
        [ClassBuilder, _MemberScope, FunctionBuilder, ConstructorBuilder],
        ids=lambda c: c.__name__,
    )
    def test_no_method_takes_var_keyword(self, owner: type) -> None:
        offenders = []
        for name, member in vars(owner).items():
            if name.startswith("_") and name != "__init__":
                continue
            if not callable(member):
                continue
            kinds = inspect.signature(member).parameters.values()
            if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in kinds):
                offenders.append(f"{owner.__name__}.{name}")
        assert not offenders, f"these take **kwargs: {offenders}"
