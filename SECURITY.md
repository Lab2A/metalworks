# Security policy

## Reporting a vulnerability

Email **security@lab2a.dev** with a description, reproduction steps, and the
affected version. Please do not open a public issue for a security report.

> Maintainer note: update this contact before the first public release if the
> address changes.

We will acknowledge the report, work with you on a fix, and credit you in the
release notes if you would like. Please give us a reasonable window to ship a
fix before public disclosure.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.x (pre-release) | Latest 0.x only |

metalworks is pre-release. Below 1.0 only the most recent 0.x release receives
security fixes. Pin a version if you depend on it.

## Secrets posture

- **API keys come from the environment, never from config files.** Provider
  credentials (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`,
  `HF_TOKEN`, search-provider keys) are read from environment variables only.
  The config file holds non-secret settings. metalworks does not write secrets
  to disk.
- **OAuth tokens are encrypted at rest.** Reddit access and refresh tokens are
  encrypted with Fernet via `TokenCipher` before they reach any store. Plaintext
  tokens are never persisted, and the `StoredRedditAccount` model holds
  ciphertext only.
- **The encryption key persists or hard-fails.** `TokenCipher` resolves its key
  from an explicit argument, then `METALWORKS_FERNET_KEY`, then a keyfile at
  `~/.metalworks/fernet.key` (generated once at `0600` if absent). It never
  silently falls back to an ephemeral in-process key, which would make stored
  tokens unrecoverable after a restart.
- **No env reads at import time.** Modules do not read environment variables or
  construct provider clients at import. Nothing leaks a secret just because you
  imported the package.

## Reporting scope

In scope: token handling, the encryption key lifecycle, the compliance gate as a
posting safeguard, SQL construction in the storage and reader layers,
credential handling in adapters, and the MCP posting-tool authorization model
(confirm tokens, the `METALWORKS_ALLOW_POSTING` opt-in).

Out of scope: vulnerabilities in upstream provider SDKs (report those upstream),
and misuse of the library against Reddit's terms (see
[USAGE_POLICY.md](USAGE_POLICY.md)).
