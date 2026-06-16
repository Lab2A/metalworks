"""metalworks — marketing research and Reddit engagement, open-sourced.

The high-level entry point is :class:`~metalworks.client.Metalworks`::

    from metalworks import Metalworks

    mw = Metalworks()  # provider inferred from your env key
    research = mw.research("demand for a focus supplement?")
    print(research.demand.verdict, len(research.evidence))

Every layer underneath is composable and swappable: the LLM / search /
embedding / storage protocols, the ``run_research`` / ``run_discovery``
functions, and the typed repos. The ``Metalworks`` facade is the easy path on
top of them.

Stability: the ``Metalworks`` facade, ``metalworks.contract`` models, and the
MCP tool contracts are the stable public surface — breaking changes to them go
through a deprecation cycle. Everything else may change in any 0.x release.
"""

from metalworks.client import Metalworks

__version__ = "0.0.3"

__all__ = ["Metalworks", "__version__"]
