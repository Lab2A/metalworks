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
import subprocess
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
    """Importing every metalworks submodule must not pull a provider SDK.

    Run in a clean subprocess so the assertion is immune to test ordering — a
    sibling test that constructs a real adapter pollutes this process's
    sys.modules, but a fresh interpreter only loads what metalworks imports.
    """
    code = (
        "import importlib, pkgutil, sys, metalworks\n"
        "names = ['metalworks']\n"
        "names += [i.name for i in pkgutil.walk_packages("
        "metalworks.__path__, prefix='metalworks.')]\n"
        "[importlib.import_module(n) for n in names]\n"
        "providers = {'anthropic','openai','google','litellm'}\n"
        "offenders = {m.split('.')[0] for m in sys.modules} & providers\n"
        "assert not offenders, sorted(offenders)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"metalworks import pulled provider SDKs: {result.stderr}"


def test_version_exposed() -> None:
    assert metalworks.__version__ == "0.0.1"
