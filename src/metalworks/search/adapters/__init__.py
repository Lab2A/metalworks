"""External SearchProvider adapters.

Each adapter lives behind an optional extra (``metalworks[exa]``, ``[tavily]``,
``[parallel]``, ``[firecrawl]``) and gates that extra lazily inside ``__init__``.
The Exa/Tavily adapters call their vendor SDK; the Parallel/Firecrawl adapters
call the documented REST endpoint over the core ``httpx`` dependency (their SDK
search surfaces are still in beta) but keep the same MissingExtraError gate.
"""
