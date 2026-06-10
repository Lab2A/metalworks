"""Provider ChatModel adapters.

Each adapter lives behind an optional extra (``metalworks[anthropic]``,
``[openai]``, ``[google]``) and imports its SDK lazily inside ``__init__`` —
never at module import time — so bare ``import metalworks`` stays clean.
"""
