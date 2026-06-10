"""EmbeddingProvider adapters.

Each adapter lives behind an optional extra (``metalworks[google]``,
``[openai]``) and imports its SDK lazily inside ``__init__``.
"""
