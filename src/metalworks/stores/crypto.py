"""TokenCipher — Fernet encryption for OAuth tokens at rest.

Key lifecycle (from plan review — never an ephemeral in-process key, which
makes stored tokens unrecoverable after restart):

  1. Explicit `key=` argument, else
  2. METALWORKS_FERNET_KEY env var, else
  3. Keyfile at ~/.metalworks/fernet.key — loaded if present, otherwise
     generated once and persisted with 0600 permissions.

Requires the `cryptography` package (ships with the [reddit] extra).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from metalworks.errors import MetalworksError, MissingExtraError

_ENV_VAR = "METALWORKS_FERNET_KEY"
_DEFAULT_KEYFILE = Path.home() / ".metalworks" / "fernet.key"


def _fernet_cls() -> Any:
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise MissingExtraError("reddit", package="cryptography") from exc
    return Fernet


class TokenCipher:
    def __init__(self, *, key: str | bytes | None = None, keyfile: Path | None = None):
        fernet = _fernet_cls()
        resolved = self._resolve_key(key, keyfile or _DEFAULT_KEYFILE, fernet)
        try:
            self._fernet = fernet(resolved)
        except (ValueError, TypeError) as exc:
            raise MetalworksError(
                "Invalid Fernet key.",
                fix=f"Provide a valid key via {_ENV_VAR} (generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())")',
            ) from exc

    @staticmethod
    def _resolve_key(key: str | bytes | None, keyfile: Path, fernet: Any) -> bytes:
        if key is not None:
            return key.encode() if isinstance(key, str) else key
        env = os.environ.get(_ENV_VAR)
        if env:
            return env.encode()
        if keyfile.exists():
            return keyfile.read_bytes().strip()
        generated: bytes = fernet.generate_key()
        keyfile.parent.mkdir(parents=True, exist_ok=True)
        keyfile.touch(mode=0o600)
        keyfile.write_bytes(generated)
        keyfile.chmod(0o600)
        return generated

    def encrypt(self, plaintext: str) -> str:
        token: bytes = self._fernet.encrypt(plaintext.encode())
        return token.decode()

    def decrypt(self, ciphertext: str) -> str:
        plain: bytes = self._fernet.decrypt(ciphertext.encode())
        return plain.decode()
