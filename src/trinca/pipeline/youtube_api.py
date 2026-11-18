"""Cliente mínimo da YouTube Data API v3 (somente leitura).

Medidas de segurança:
- só HTTPS, com verificação de certificado, para um endereço fixo;
- a chave vai no cabeçalho X-goog-api-key, nunca na URL, para não parar em logs;
- redirecionamentos são recusados, para a chave não seguir para outro servidor;
- tempo limite e tamanho máximo de resposta.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import urlencode

from ..credentials import CredentialError
from .contracts import ServiceError

API_BASE = "https://www.googleapis.com/youtube/v3/"
RESOURCES = frozenset({"channels", "playlistItems", "videos", "search"})
MAX_RESPONSE_BYTES = 2_000_000
TIMEOUT_S = 20

Fetch = Callable[[str, dict[str, str]], tuple[int, bytes]]

_REASONS = {
    "quotaExceeded": "A cota diária da YouTube Data API acabou. Ela é renovada no dia seguinte.",
    "dailyLimitExceeded": "A cota diária da YouTube Data API acabou. Ela é renovada no dia seguinte.",
    "rateLimitExceeded": "Muitos pedidos ao YouTube em pouco tempo. Tente de novo em instantes.",
    "accessNotConfigured": "A YouTube Data API v3 não está ativada no projeto dessa chave.",
    "keyInvalid": "A chave da YouTube Data API não é válida.",
    "playlistNotFound": "A lista de envios do canal não foi encontrada.",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


def https_get(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    """GET por HTTPS sem seguir redirecionamentos. Devolve (status, corpo)."""
    opener = urllib.request.build_opener(
        _NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ServiceError(
            "Sem conexão com o YouTube. Verifique a internet e tente de novo."
        ) from exc


def _error_message(status: int, data: object) -> str:
    error = data.get("error") if isinstance(data, dict) else None
    details = error.get("errors") if isinstance(error, dict) else None
    reason = ""
    if isinstance(details, list) and details and isinstance(details[0], dict):
        reason = str(details[0].get("reason", ""))
    if reason in _REASONS:
        return _REASONS[reason]
    message = str(error.get("message", "")) if isinstance(error, dict) else ""
    if status == 400 and "API key not valid" in message:
        return _REASONS["keyInvalid"]
    if status in (401, 403):
        return "O YouTube recusou a chave. Confira a chave e as permissões dela."
    return f"O YouTube recusou o pedido (erro {status})."


class YouTubeApi:
    def __init__(self, get_key: Callable[[], str | None], fetch: Fetch = https_get) -> None:
        self._get_key = get_key
        self._fetch = fetch

    def get(self, resource: str, params: dict[str, str]) -> dict:
        """Chama um recurso de leitura. Custa 1 unidade de cota; a busca custa 100."""
        if resource not in RESOURCES:
            raise ValueError(f"Recurso não permitido: {resource}")
        key = self._get_key()
        if not key:
            raise CredentialError("Configure a chave da YouTube Data API em Configurações.")
        url = f"{API_BASE}{resource}?{urlencode(params)}"
        status, body = self._fetch(url, {"X-goog-api-key": key, "Accept": "application/json"})
        if len(body) > MAX_RESPONSE_BYTES:
            raise ServiceError("O YouTube devolveu uma resposta grande demais.")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise ServiceError("O YouTube devolveu uma resposta inválida.") from exc
        if status != 200:
            raise ServiceError(_error_message(status, data))
        if not isinstance(data, dict):
            raise ServiceError("O YouTube devolveu uma resposta inválida.")
        return data
