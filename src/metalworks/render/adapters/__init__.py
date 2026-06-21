"""PageRenderer adapters.

* ``playwright`` — an owned headless Chromium behind ``metalworks[browser]``;
  renders and runs a fixed, vendored style-extraction script.
* ``firecrawl`` — a hosted REST screenshot behind ``metalworks[firecrawl]``
  (the same extra the search adapter uses); screenshot-only, no style audit.

Each adapter lazy-imports its dependency inside ``__init__`` to gate the extra
(:class:`~metalworks.errors.MissingExtraError`), matching the search adapters.
"""
