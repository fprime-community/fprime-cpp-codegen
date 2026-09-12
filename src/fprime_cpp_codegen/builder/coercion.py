"""Coercion and validation of the loose argument shapes the builders accept."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..body import Code, stmts
from ..doc import Param, SVQualifier, as_type
from ..errors import ValidationError
from ..lines import Line


def _as_body_lines(body: Code) -> list[Line]:
    """Coerce whatever the caller passed as a body into lines."""
    return stmts(body)


def _as_params(
    params: Iterable[Param | tuple[str, ...] | Sequence[str]],
) -> list[Param]:
    """Coerce a parameter spec list into :class:`Param` objects.

    A tuple is read as ``(type, name)`` optionally followed by ``comment`` and
    ``default``.  An empty string in either position means absent.
    """
    out: list[Param] = []
    for p in params:
        if isinstance(p, Param):
            out.append(p)
            continue
        parts = list(p)
        if not 2 <= len(parts) <= 4:
            raise ValidationError(
                f"parameter {p!r} should be a Param, or a tuple of "
                "(type, name[, comment[, default]])"
            )
        type_name, name, *rest = parts
        comment = rest[0] or None if len(rest) > 0 else None
        default = rest[1] or None if len(rest) > 1 else None
        out.append(Param(as_type(type_name), name, comment, default))
    return out


def _sv_qualifier(
    *,
    static: bool,
    virtual: bool,
    pure_virtual: bool,
    override: bool,
    final: bool,
) -> SVQualifier:
    """Collapse the mutually exclusive static/virtual flags into one qualifier."""
    if pure_virtual:
        # virtual is redundant alongside pure_virtual, so it is permitted.
        conflicts = [
            n
            for n, v in (("static", static), ("override", override), ("final", final))
            if v
        ]
        if conflicts:
            raise ValidationError(
                f"a pure virtual function cannot also be {' or '.join(conflicts)}"
            )
        return SVQualifier.PURE_VIRTUAL
    chosen = [
        n
        for n, v in (
            ("static", static),
            ("virtual", virtual),
            ("override", override),
            ("final", final),
        )
        if v
    ]
    if len(chosen) > 1:
        raise ValidationError(
            f"a function cannot be {' and '.join(chosen)} at once; pick one"
        )
    if static:
        return SVQualifier.STATIC
    if virtual:
        return SVQualifier.VIRTUAL
    if override:
        return SVQualifier.OVERRIDE
    if final:
        return SVQualifier.FINAL
    return SVQualifier.NONE


def _extends(extends: str | Sequence[str] | None) -> str | None:
    """Normalise a base-class specification into the text after the colon."""
    if extends is None:
        return None
    if isinstance(extends, str):
        return extends
    joined = ", ".join(extends)
    return joined or None


def _as_attributes(attributes: str | Sequence[str]) -> tuple[str, ...]:
    """Normalise a declaration-attribute specification into a tuple.

    A single string is one attribute, not a sequence of characters, since one is the
    common case: ``attributes='__attribute__((visibility("default")))'``.
    """
    if isinstance(attributes, str):
        return (attributes,)
    return tuple(attributes)
