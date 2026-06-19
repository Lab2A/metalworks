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

> **Before you open a PR, run `/pr-ready`** — the Claude Code skill in
> `.claude/skills/`. It runs the gate above *plus* the contract-drift check CI
> doesn't (see below), and walks the surface-parity / docs / changelog checks
> that aren't automatable. See [docs/architecture.md](docs/architecture.md) for
> the *why* behind each rule.

## Surface parity — a primitive lives on all four surfaces

metalworks is contract-first: one capability is exposed on the **Python facade,
the CLI, the MCP server, and the Claude Code plugin** — never just one. If you
add or change a primitive, all four move together. Using `landscape` as the map:

1. **Facade** — a method on `Metalworks` in `src/metalworks/client.py`
   (`landscape(...)`), a thin wrapper over the `run_*` function in
   `src/metalworks/research/`.
2. **CLI** — a `@research_app.command(...)` in `src/metalworks/cli/__init__.py`
   (`research landscape`) with a `_print_*` renderer.
3. **MCP** — a tool *body* in `src/metalworks/mcp/tools.py`
   (`landscape_from_report`, returns an error envelope or a `model_dump`), an
   async wrapper in `src/metalworks/mcp/server.py`, **and** an entry in that
   file's `_TOOL_WRAPPERS` tuple (missing it = the tool isn't registered).
4. **Skill** — a `plugin/skills/<name>/SKILL.md` that drives the MCP tool
   (`plugin/skills/market-landscape/`).

A PR that adds a facade method but no CLI/MCP/skill is incomplete. (Removing a
surface is the same rule in reverse — drop all four, plus every doc reference.)

## The contract registry (lockstep)

The Pydantic models in `src/metalworks/contract/` are the stable spine. They
generate the TypeScript twin (`ts/contract.ts`) and the JSON-schema snapshots
(`src/metalworks/contract/schema/`). When you add or change a contract model:

1. Add the model to **`MODELS`** in `scripts/gen_ts_types.py` (dependency order,
   leaves first); add it to **`_SCHEMAS`** only if it's a snapshot-gated root.
2. Import it in `src/metalworks/contract/__init__.py` and add it to `__all__`.
3. Run `python scripts/gen_ts_types.py` and **commit** the regenerated
   `ts/contract.ts` and any changed `contract/schema/*.json`.

`python scripts/gen_ts_types.py --check` fails if the committed files have
drifted from the contract. **CI does not run this check** — `/pr-ready` does, so
run it (or the skill) before pushing, or your generated files silently rot.

Stay **additive** below 1.0: new fields are defaulted so an old payload still
validates (there's a round-trip parity test pattern for this — see
`tests/test_contract_forks.py`). Don't remove or rename a public contract field
without a deprecation note (see Rules below).

## Docs and the changelog

A new or changed surface updates the docs that describe it — the relevant page
under `docs/` (`cli.md`, `mcp-tools.md`, `python-sdk.md`, the capability page) —
and adds a `CHANGELOG.md` entry under `Added` / `Changed` / `Removed`. The docs
nav lives in `docs.json`.

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

See [docs/custom-chatmodel.md](docs/custom-chatmodel.md) for a worked example.

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

To cut a release, bump the version in the **three** sites that must agree —
`pyproject.toml`, `src/metalworks/__init__.py` (`__version__`), and
`plugin/.claude-plugin/plugin.json` — add a `CHANGELOG.md` entry, merge to
`main`, then push a tag `vX.Y.Z`. The `release.yml` workflow builds and publishes
to PyPI on any `v*` tag (OIDC, no token). Below 1.0, a removed surface is a patch
or minor at the owner's call, noted under `Removed` in the changelog.

Follow the deprecation policy: emit a `DeprecationWarning` at least one minor
version before removing anything, and call out breaking changes in
[CHANGELOG.md](CHANGELOG.md) with migration notes.
