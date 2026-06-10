# Contributing to metalworks

Thanks for helping. metalworks is pre-release, so the most useful contributions
right now are provider adapters, storage backends, bug reports against the
shipped pieces, and docs fixes. Please read [USAGE_POLICY.md](USAGE_POLICY.md)
and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) first.

## Dev setup

We use [uv](https://docs.astral.sh/uv/).

```bash
uv venv
uv pip install -e ".[all,dev]"
```

`[all,dev]` gives you every provider adapter plus the test and lint toolchain.

## The gate

Everything must pass before a PR lands:

```bash
ruff check .
ruff format --check .
pyright
pytest -q
```

`pyright` runs in strict mode over `src`. The test suite runs offline:
`pytest-socket` disables network, recorded fixtures (respx cassettes, committed
Parquet shards, recorded grounding responses) stand in for live services.

## The extras model

Core depends only on pydantic, httpx, typing-extensions, typer, and rich.
Everything that pulls a provider SDK or a heavy dependency (duckdb, supabase,
the LLM SDKs) lives behind an extra.

Provider SDKs are **lazy-imported behind their extra**. The import happens
inside the method that needs it, not at module top level, so:

- `import metalworks` never requires a provider SDK. CI asserts a bare import
  pulls in zero provider modules.
- A missing extra raises `MissingExtraError` carrying the exact
  `pip install "metalworks[...]"` command, instead of a raw `ModuleNotFoundError`.

When you add an import of an optional dependency, wrap it:

```python
try:
    import duckdb
except ImportError as exc:
    raise MissingExtraError("arctic", package="duckdb") from exc
```

## Adding a provider adapter

1. Implement the protocol. For a chat adapter, implement `ChatModel`
   (`complete_text`, `complete_structured`, the `model_id` /
   `capabilities` / `protocol_version` attributes). Add `complete_grounded` and
   set `capabilities.native_grounding` only if the provider does native web
   grounding, and carry the full `GroundedResult` provenance (chunks plus
   character-offset supports, converting from the provider's offsets).
2. Lazy-import the SDK behind your extra and raise `MissingExtraError` when it
   is absent.
3. Read credentials from the environment, raise `MissingKeyError` (naming the
   env var) when absent. Never read keys from config or at import time.
4. Run the conformance suite against your adapter:

   ```python
   from metalworks.testing import FakeChatModel  # reference behavior
   # repo backends:
   from metalworks.testing import check_all_repos
   check_all_repos(MyBackend())
   ```

   `check_all_repos` includes the >1000-row pagination case that catches
   silently-truncating backends. Match the semantics the fakes and built-in
   backends demonstrate.

See [docs/how-to-custom-chatmodel.md](docs/how-to-custom-chatmodel.md) for a
worked example.

## Rules that are not negotiable

- **No module-level singletons.** No constructing clients, repos, or models at
  import time.
- **No env reads at import.** Read environment variables inside functions, never
  at module scope. A clean-env import test walks every submodule and asserts zero
  exceptions and zero network with no environment variables set.
- **Protocols are versioned as a unit.** Additive keyword-only parameters with
  defaults are a minor bump; anything breaking is a major bump.

## CI matrix

CI runs on Python 3.11, 3.12, and 3.13, each against a bare install and an
`[all]` install. The bare leg proves core imports clean with no provider
dependencies; the `[all]` leg runs the full suite.

## Releases and version pinning

The Claude Code plugin launches the MCP server with a version-pinned `uvx`
command. The plugin and the PyPI package bump in lockstep: when you cut a PyPI
release, the plugin's pinned version moves with it, in the same release. Do not
ship one without the other.

Follow the deprecation policy: emit a `DeprecationWarning` at least one minor
version before removing anything, and call out breaking changes in
[CHANGELOG.md](CHANGELOG.md) with migration notes.
