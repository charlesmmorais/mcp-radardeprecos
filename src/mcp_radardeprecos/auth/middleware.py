"""Middleware ASGI de autenticação Entra ID.

Espelha ``rate_limit.RateLimitMiddleware`` deliberadamente: mesma
convenção de assinatura (``__init__(self, app, ...)`` +
``async def __call__(self, scope, receive, send)``) e mesma regra de só
atuar sobre requisições HTTP (``scope["type"] == "http"``) — lifespan e
websocket passam direto. Só é montado por ``server._run_http`` quando
``config.settings.entra_auth_habilitado`` é ``True``; ver a docstring de
``auth/entra.py`` para o "porquê" completo desta camada (M365 Copilot
exige Entra ID; Claude/ChatGPT continuam sem nenhuma autenticação).

**Rotas que passam SEM exigir token:**

- ``GET /`` — o health check, testado por provedores de hospedagem antes
  de qualquer coisa (ver ``server.health_check``); exigir token aqui
  quebraria o smoke test de deploy de infraestrutura que não sabe nada
  sobre OAuth.
- Qualquer caminho sob ``/.well-known/`` — os metadados do protocolo (ver
  ``server.py``, item 5) precisam ser lidos pelo cliente ANTES de ele
  saber como se autenticar; exigir token aqui criaria uma dependência
  circular (o cliente precisaria de um token para descobrir como obter um
  token).

Token ausente/malformado ou reprovado em alguma validação de
``auth.entra.validar_token`` vira HTTP 401 com o header
``WWW-Authenticate: Bearer ...`` (RFC 6750), incluindo o parâmetro
``resource_metadata`` apontando para
``/.well-known/oauth-protected-resource`` (RFC 9728 / MCP Authorization
spec — CONFERIR o formato exato contra a versão vigente da spec no
momento de um teste real com o Agents Toolkit, está evoluindo). Falha ao
buscar a JWKS do Entra (instabilidade de rede, não culpa do cliente) vira
HTTP 503 — ver ``auth.entra.EntraJWKSIndisponivelError``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .entra import EntraAuthError, EntraJWKSIndisponivelError, validar_token

#: Caminhos exatos que dispensam token, além de qualquer coisa sob
#: ``_PREFIXO_SEM_TOKEN``.
_ROTAS_SEM_TOKEN_EXATAS = frozenset({"/"})
_PREFIXO_SEM_TOKEN = "/.well-known/"


def _rota_dispensa_token(path: str) -> bool:
    return path in _ROTAS_SEM_TOKEN_EXATAS or path.startswith(_PREFIXO_SEM_TOKEN)


def _cabecalho(scope: dict[str, Any], nome: bytes) -> bytes | None:
    for chave, valor in scope.get("headers") or []:
        if chave == nome:
            return valor
    return None


def _url_metadados_recurso(scope: dict[str, Any]) -> str:
    """Monta a URL absoluta de ``/.well-known/oauth-protected-resource`` a partir do scope ASGI.

    Usa o ``Host`` header da própria requisição (em vez de uma URL fixa em
    config) porque o mesmo servidor pode ser acessado por hostnames
    diferentes (ex.: domínio próprio e o do provedor) — o valor sempre
    reflete o host que o cliente efetivamente usou.
    """
    esquema = scope.get("scheme") or "https"
    host_bruto = _cabecalho(scope, b"host")
    host = host_bruto.decode("latin-1") if host_bruto else "localhost"
    return f"{esquema}://{host}/.well-known/oauth-protected-resource"


async def _responder_401(send: Callable[[dict[str, Any]], Any], www_authenticate: str) -> None:
    corpo = b'{"erro": "token de acesso Entra ID ausente ou invalido"}'
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", www_authenticate.encode("latin-1")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": corpo})


async def _responder_503(send: Callable[[dict[str, Any]], Any]) -> None:
    corpo = b'{"erro": "servico de autenticacao (Entra ID) temporariamente indisponivel"}'
    await send(
        {
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", b"30"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": corpo})


class EntraAuthMiddleware:
    """Middleware ASGI puro (compatível com Starlette) que exige um Bearer token válido do Entra ID.

    Quando o token é válido, injeta os claims decodificados em
    ``scope["entra_claims"]`` antes de repassar ao app interno — permite
    que ``logging_utils``/tools futuras correlacionem QUEM chamou (o
    ``sub``/``oid`` do usuário Entra), sem que isso seja usado hoje para
    gating de conteúdo (todas as tools continuam sendo dados públicos de
    leitura).
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        if _rota_dispensa_token(scope.get("path", "")):
            await self._app(scope, receive, send)
            return

        url_metadados = _url_metadados_recurso(scope)
        www_authenticate_sem_credencial = f'Bearer resource_metadata="{url_metadados}"'

        auth_header = _cabecalho(scope, b"authorization")
        token = _extrair_bearer_token(auth_header)
        if token is None:
            await _responder_401(send, www_authenticate_sem_credencial)
            return

        try:
            claims = await validar_token(token)
        except EntraJWKSIndisponivelError:
            await _responder_503(send)
            return
        except EntraAuthError as exc:
            www_authenticate = (
                'Bearer error="invalid_token", error_description="'
                f'{exc.mensagem}", resource_metadata="{url_metadados}"'
            )
            await _responder_401(send, www_authenticate)
            return

        scope_com_claims = dict(scope)
        scope_com_claims["entra_claims"] = claims
        await self._app(scope_com_claims, receive, send)


def _extrair_bearer_token(auth_header: bytes | None) -> str | None:
    """Devolve o token de um header ``Authorization: Bearer <token>``, ou ``None`` se ausente/mal formado."""
    if not auth_header:
        return None
    valor = auth_header.decode("latin-1")
    prefixo = "bearer "
    if not valor.lower().startswith(prefixo):
        return None
    token = valor[len(prefixo):].strip()
    return token or None
