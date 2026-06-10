"""Import hygiene tests.

Two guarantees, both load-bearing for the extras model:

1. `import metalworks` (and every submodule) must succeed with NO env vars and
   NO network — keyless users must never see an import-time explosion. The
   source codebase this library is extracted from had three module-level
   singletons that raised at import without env vars; this test is the
   regression net that keeps that pattern out.
2. Bare import must not pull any LLM-provider SDK into sys.modules — core has
   zero provider deps; adapters load lazily behind extras.
"""

import importlib
import pkgutil
import sys

import metalworks

PROVIDER_MODULES = ("anthropic", "openai", "google", "litellm")


def _walk_submodules() -> list[str]:
    names = ["metalworks"]
    for info in pkgutil.walk_packages(metalworks.__path__, prefix="metalworks."):
        names.append(info.name)
    return names


def test_every_submodule_imports_clean() -> None:
    for name in _walk_submodules():
        importlib.import_module(name)


def test_no_provider_sdks_in_sys_modules() -> None:
    for name in _walk_submodules():
        importlib.import_module(name)
    loaded = {m.split(".")[0] for m in sys.modules}
    offenders = loaded.intersection(PROVIDER_MODULES)
    assert not offenders, f"bare import pulled provider SDKs: {sorted(offenders)}"


def test_version_exposed() -> None:
    assert metalworks.__version__ == "0.0.1"
