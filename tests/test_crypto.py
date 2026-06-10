"""TokenCipher key-lifecycle tests (review: never an ephemeral key)."""

from __future__ import annotations

from pathlib import Path

import pytest

from metalworks.errors import MetalworksError
from metalworks.stores import TokenCipher

cryptography = pytest.importorskip("cryptography")


def test_round_trip_with_explicit_key() -> None:
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    cipher = TokenCipher(key=key)
    assert cipher.decrypt(cipher.encrypt("secret-token")) == "secret-token"


def test_env_key_wins_over_keyfile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from cryptography.fernet import Fernet

    env_key = Fernet.generate_key().decode()
    monkeypatch.setenv("METALWORKS_FERNET_KEY", env_key)
    cipher = TokenCipher(keyfile=tmp_path / "never-created.key")
    assert not (tmp_path / "never-created.key").exists()
    assert cipher.decrypt(cipher.encrypt("t")) == "t"


def test_keyfile_generated_once_with_0600_and_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("METALWORKS_FERNET_KEY", raising=False)
    keyfile = tmp_path / "sub" / "fernet.key"

    first = TokenCipher(keyfile=keyfile)
    assert keyfile.exists()
    assert (keyfile.stat().st_mode & 0o777) == 0o600

    token = first.encrypt("persisted")
    # A NEW cipher instance (fresh process simulation) must decrypt it —
    # the ephemeral-key failure mode this design forbids.
    second = TokenCipher(keyfile=keyfile)
    assert second.decrypt(token) == "persisted"


def test_invalid_key_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METALWORKS_FERNET_KEY", "not-a-valid-fernet-key")
    with pytest.raises(MetalworksError) as exc_info:
        TokenCipher()
    assert exc_info.value.fix is not None
