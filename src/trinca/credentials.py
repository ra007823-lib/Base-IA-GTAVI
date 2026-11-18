"""Chaves de API guardadas no cofre do sistema operacional.

As chaves nunca são gravadas em arquivo, no banco ou em log. Se o sistema
não oferecer um cofre seguro, o app se recusa a guardá-las.
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from .config import KEYRING_SERVICE

SERVICES = {
    "gemini": "Gemini (analista)",
    "claude": "Claude (roteirista)",
    "speech": "Terceira IA (voz e legendas)",
    "youtube": "YouTube Data API (opcional, não usada)",
}

_INSECURE_BACKENDS = ("keyring.backends.fail", "keyring.backends.null", "keyrings.alt")


class CredentialError(Exception):
    """Falha ao acessar o cofre. A mensagem pode ser mostrada ao usuário."""


class CredentialStore:
    def __init__(self, backend: object | None = None) -> None:
        self._backend = backend if backend is not None else keyring.get_keyring()

    @property
    def secure(self) -> bool:
        """Falso quando o backend não existe ou guarda as chaves em texto puro."""
        return not type(self._backend).__module__.startswith(_INSECURE_BACKENDS)

    def _check(self, name: str) -> None:
        if name not in SERVICES:
            raise CredentialError("Serviço desconhecido.")
        if not self.secure:
            raise CredentialError(
                "Nenhum cofre seguro foi encontrado no sistema. "
                "Instale o GNOME Keyring ou o KWallet para guardar as chaves."
            )

    def set(self, name: str, value: str) -> None:
        self._check(name)
        secret = value.strip()
        if not 8 <= len(secret) <= 512 or not secret.isprintable() or " " in secret:
            raise CredentialError("A chave informada não tem um formato válido.")
        try:
            self._backend.set_password(KEYRING_SERVICE, name, secret)
        except KeyringError as exc:
            raise CredentialError("Não foi possível gravar a chave no cofre.") from exc

    def get(self, name: str) -> str | None:
        self._check(name)
        try:
            return self._backend.get_password(KEYRING_SERVICE, name)
        except KeyringError as exc:
            raise CredentialError("Não foi possível ler o cofre do sistema.") from exc

    def delete(self, name: str) -> None:
        self._check(name)
        try:
            self._backend.delete_password(KEYRING_SERVICE, name)
        except PasswordDeleteError:
            pass  # já não existia
        except KeyringError as exc:
            raise CredentialError("Não foi possível remover a chave do cofre.") from exc

    def masked(self, name: str) -> str:
        """Texto para a interface: mostra só os 4 últimos caracteres."""
        try:
            secret = self.get(name)
        except CredentialError:
            return "Cofre indisponível"
        if not secret:
            return "Não configurada"
        return f"Salva (••••{secret[-4:]})"
