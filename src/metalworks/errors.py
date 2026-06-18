"""Typed exception hierarchy.

Every error a user (or a host model consuming MCP tool results) can hit maps
to one of these. Each carries an actionable `fix` — the exact command or env
var that unblocks — because the consumer is often an agent that will relay
the fix verbatim.
"""

from __future__ import annotations


class MetalworksError(Exception):
    """Base class. `fix` is the actionable remediation; `docs_url` optional."""

    error_code: str = "metalworks_error"

    def __init__(self, message: str, *, fix: str | None = None, docs_url: str | None = None):
        super().__init__(message)
        self.message = message
        self.fix = fix
        self.docs_url = docs_url

    def envelope(self) -> dict[str, str | None]:
        """Machine-readable shape returned through MCP tool results."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "fix": self.fix,
            "docs_url": self.docs_url,
        }


class MissingExtraError(MetalworksError):
    """A feature needs an optional dependency that isn't installed."""

    error_code = "missing_extra"

    def __init__(self, extra: str, *, package: str | None = None):
        self.extra = extra
        pkg = package or extra
        super().__init__(
            f"This feature requires the '{extra}' extra ({pkg} is not installed).",
            fix=f'pip install "metalworks[{extra}]"',
        )


class MissingKeyError(MetalworksError):
    """A provider/API credential is absent."""

    error_code = "missing_key"

    def __init__(self, env_var: str, *, provider: str | None = None, detail: str | None = None):
        self.env_var = env_var
        who = f" for {provider}" if provider else ""
        extra = f" {detail}" if detail else ""
        super().__init__(
            f"No API credential found{who}.{extra}",
            fix=f"Set the {env_var} environment variable.",
        )


class RateLimitedError(MetalworksError):
    """Upstream returned 429 / overloaded after retries were exhausted."""

    error_code = "rate_limited"

    def __init__(self, provider: str, *, retry_after_s: float | None = None):
        self.provider = provider
        self.retry_after_s = retry_after_s
        hint = f" Retry after ~{retry_after_s:.0f}s." if retry_after_s else ""
        super().__init__(
            f"{provider} rate limit exceeded after retries.{hint}",
            fix="Wait and retry; reduce request volume or add credentials with higher limits.",
        )


class StructuredOutputError(MetalworksError):
    """The model could not produce output matching the requested schema."""

    error_code = "structured_output"

    def __init__(self, model_id: str, detail: str):
        super().__init__(
            f"{model_id} failed to produce schema-valid output: {detail}",
            fix="Retry, simplify the output model, or switch to a more capable model.",
        )


class GroundingUnavailable(MetalworksError):
    """Model-native web grounding was requested but isn't available."""

    error_code = "grounding_unavailable"

    def __init__(self, model_id: str, detail: str = "no grounding metadata in response"):
        super().__init__(
            f"Grounded completion unavailable on {model_id}: {detail}",
            fix="Use a grounding-capable model (e.g. Gemini with google_search) or configure an "
            "external SearchProvider (metalworks[exa] / [tavily]).",
        )


class ReauthRequiredError(MetalworksError):
    """A stored OAuth token was revoked or expired beyond refresh."""

    error_code = "reauth_required"

    def __init__(self, account: str | None = None):
        who = f" for {account}" if account else ""
        super().__init__(
            f"Reddit authorization is no longer valid{who} (token revoked or expired).",
            fix="Run: metalworks reddit auth login",
        )


class StoreError(MetalworksError):
    """A storage backend failed (locked, unwritable, misconfigured)."""

    error_code = "store_error"


class RedditError(MetalworksError):
    """A Reddit API call failed in a way that isn't auth or rate limiting."""

    error_code = "reddit_error"

    def __init__(self, message: str, *, status: int | None = None):
        self.status = status
        super().__init__(
            message,
            fix="Check the Reddit app credentials, scopes, and that the target still exists.",
        )


class BillingError(MetalworksError):
    """A billing-provider call failed in a way that isn't a missing key/extra."""

    error_code = "billing_error"

    def __init__(self, message: str, *, status: int | None = None):
        self.status = status
        super().__init__(
            message,
            fix="Check the Stripe key's mode (test vs live), the price amount, and the dashboard.",
        )


class DeployError(MetalworksError):
    """A deploy-provider call failed in a way that isn't a missing token."""

    error_code = "deploy_error"

    def __init__(self, message: str, *, status: int | None = None):
        self.status = status
        super().__init__(
            message,
            fix="Check the VERCEL_TOKEN, the project/team id, and the artifact you are deploying.",
        )


class EmbeddingModelMismatch(MetalworksError):
    """A persisted vector index was built with a different embedding model."""

    error_code = "embedding_model_mismatch"

    def __init__(self, *, index_model: str, current_model: str):
        self.index_model = index_model
        self.current_model = current_model
        super().__init__(
            f"Index was built with '{index_model}' but the configured embedding model is "
            f"'{current_model}'. Vectors from different models are geometrically incompatible; "
            "retrieval would degrade silently.",
            fix="Re-embed the index with the current model, or configure the original model.",
        )
