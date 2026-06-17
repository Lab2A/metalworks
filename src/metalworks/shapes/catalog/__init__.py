"""Built-in startup-shape catalog.

Each submodule (``store``, ``match``, ``synthesize``, ...) owns one base stack and
its product shapes, and self-registers them on import via ``register_base_stack`` /
``register_shape``. This package imports every submodule automatically, so a new
base-stack module is picked up just by dropping ``catalog/<base>.py`` — no edit to a
shared list here. That is the seam that lets the full base x module catalog be filled
out in parallel without collisions.
"""

from __future__ import annotations

import importlib
import pkgutil

for _module in pkgutil.iter_modules(__path__):
    if not _module.name.startswith("_"):
        importlib.import_module(f"{__name__}.{_module.name}")
