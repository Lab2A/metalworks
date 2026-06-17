"""Startup shapes: the base-stack catalog + append-friendly registries.

Two layers, two registries. :data:`BASE_STACKS` holds the irreducible reusable
backends (the thing a Claude Code terminal builds from); :data:`SHAPES` holds the
named product shapes (base + modules + skin) that a :class:`ShapeMatcher` ranks
against a demand report. Both self-register on import of :mod:`metalworks.shapes.catalog`
via :func:`register_base_stack` / :func:`register_shape` — a new shape never edits a
shared inline list, so a fan-out of many shapes can land without colliding on this file.

``get_*`` lazily imports the built-in catalog so a bare ``import metalworks`` stays
free of the matcher's optional embedding dependency.
"""

from __future__ import annotations

from metalworks.contract.shape import (
    BaseStack,
    BaseStackId,
    MatchSignature,
    Module,
    ModuleId,
    ProductShape,
    ShapeMatch,
)

# ── Append-friendly registries ───────────────────────────────────────────────

BASE_STACKS: dict[BaseStackId, BaseStack] = {}
SHAPES: dict[str, ProductShape] = {}


def register_base_stack(stack: BaseStack) -> None:
    """Register ``stack`` under its id (idempotent on re-import)."""
    BASE_STACKS[stack.id] = stack


def register_shape(shape: ProductShape) -> None:
    """Register ``shape`` under its name (idempotent on re-import)."""
    SHAPES[shape.name] = shape


def _ensure_catalog() -> None:
    """Lazily import the built-in catalog so it self-registers (once)."""
    if not BASE_STACKS or not SHAPES:
        import importlib

        importlib.import_module("metalworks.shapes.catalog")


def get_base_stack(stack_id: BaseStackId) -> BaseStack:
    """Return the registered base stack for ``stack_id`` (triggers catalog load)."""
    _ensure_catalog()
    try:
        return BASE_STACKS[stack_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown base stack {stack_id!r}; registered: {sorted(BASE_STACKS)}"
        ) from exc


def get_shape(name: str) -> ProductShape:
    """Return the registered product shape ``name`` (triggers catalog load)."""
    _ensure_catalog()
    try:
        return SHAPES[name]
    except KeyError as exc:
        raise KeyError(f"unknown shape {name!r}; registered: {sorted(SHAPES)}") from exc


def all_shapes() -> list[ProductShape]:
    """Every registered product shape (triggers catalog load)."""
    _ensure_catalog()
    return list(SHAPES.values())


__all__ = [
    "BASE_STACKS",
    "SHAPES",
    "BaseStack",
    "BaseStackId",
    "MatchSignature",
    "Module",
    "ModuleId",
    "ProductShape",
    "ShapeMatch",
    "all_shapes",
    "get_base_stack",
    "get_shape",
    "register_base_stack",
    "register_shape",
]
