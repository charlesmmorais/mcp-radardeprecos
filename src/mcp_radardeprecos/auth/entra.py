"""Validação de token OAuth 2.0/2.1 do Microsoft Entra ID.

Este módulo implementa o lado **resource server**: recebe um JWT (emitido
pelo Entra ID, nunca por este projeto) e confere se ele é legítimo para
acessar este servidor. Este projeto NUNCA emite token — quem emite é o
próprio Entra, via authorization code flow conduzido pelo cliente (ex.: o
Microsoft 365 Agents Toolkit) fora deste código.

Contexto e motivação completos: o estudo de integração com M365/Copilot — em
resumo, o M365 Copilot exige Entra ID para plugins MCP/API; Claude e
ChatGPT continuam funcionando sem nenhuma autenticação (ver
``rate_limit.py`` para a justificativa original de não ter OAuth). Este
módulo só é usado quando ``config.settings.entra_auth_habilitado`` é
``True`` — com ``ENTRA_TENANT_ID``/``ENTRA_CLIENT_ID`` ausentes, nada aqui
é chamado.

**Validações aplicadas em** :func:`validar_token`:

- Assinatura RS256, contra a chave pública (JWK) do Entra correspondente ao
  ``kid`` do header do token — buscada/cacheada por :class:`JWKSCache`.
- ``aud`` (audience) igual a ``ENTRA_CLIENT_ID``.
- ``iss`` (issuer) igual a uma das duas variantes que o Entra emite para o
  mesmo tenant: ``https://login.microsoftonline.com/{tenant}/v2.0`` (v2,
  a mais comum hoje) e ``https://sts.windows.net/{tenant}/`` (v1, ainda
  emitida por alguns fluxos/recursos legados do Entra).
- ``exp``/``nbf`` (expiração/"not before") — validados pelo próprio PyJWT.
- Scope/role (``ENTRA_REQUIRED_SCOPE``), se configurado: aceito tanto via
  ``scp`` (tokens delegados, de usuário) quanto ``roles`` (tokens de
  aplicação, client credentials) — são claims mutuamente exclusivas no
  Entra dependendo do tipo de token, então ambas são conferidas.

Qualquer falha de validação do TOKEN em si vira :class:`EntraAuthError`
(HTTP 401 — culpa do cliente/token). Uma falha ao BUSCAR a JWKS do Entra
(rede instável, Entra fora do ar) vira :class:`EntraJWKSIndisponivelError`
(HTTP 503 — não é culpa de quem chamou; decisão deliberada do plano para
não "trancar fora" por instabilidade do Entra).
"""
from __future__ import annotations

from typing import Any

import jwt

from ..clients.base import UpstreamError, get_json
from ..config import settings
from ..logging_utils import get_logger
from ..utils import cache

logger = get_logger(__name__)

SOURCE = "Entra ID"

_ALGORITMOS_ACEITOS = ["RS256"]


class EntraAuthError(Exception):
    """Token ausente, malformado ou reprovado em alguma validação — vira HTTP 401.

    Só carrega a mensagem — quem monta o header ``WWW-Authenticate`` (com o
    ``resource_metadata`` apontando ao ``/.well-known`` do próprio recurso,
    RFC 9728) é ``auth/middleware.py``, que tem acesso à URL da requisição
    (este módulo não tem, de propósito: é testável sem nenhum contexto ASGI).
    """

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem


class EntraJWKSIndisponivelError(Exception):
    """Falha de rede/upstream ao buscar as chaves públicas do Entra — vira HTTP 503.

    Deliberadamente uma exceção DIFERENTE de :class:`EntraAuthError`: um
    401 aqui responsabilizaria o cliente por um problema que é do Entra
    (instabilidade momentânea, rede).
    """


class JWKSCache:
    """Cache das chaves públicas (JWKS) de um tenant do Entra ID.

    Usa o cache em memória compartilhado do projeto (``utils/cache.py``,
    TTL simples) sob a chave ``entra:jwks:{tenant_id}`` — mesmo mecanismo
    já usado por ``clients/*.py`` para catálogos que mudam raramente.
    Além do TTL normal (``RADARDEPRECOS_JWKS_TTL``, padrão 1h), dispara um
    refresh imediato quando um token chega com um ``kid`` ausente do cache
    atual — cobre rotação de chave do Entra sem esperar o TTL expirar, sem
    precisar de um mecanismo de invalidação mais complexo.
    """

    def __init__(self, tenant_id: str, *, ttl_seconds: float | None = None) -> None:
        self._tenant_id = tenant_id
        self._ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else settings.entra_jwks_ttl_seconds
        )
        self._cache_key = f"entra:jwks:{tenant_id}"

    async def obter_chave(self, kid: str) -> dict[str, Any]:
        """Devolve o JWK (dict) do ``kid`` informado, buscando/atualizando a JWKS se preciso."""
        chaves_por_kid = cache.get(self._cache_key)
        if chaves_por_kid is None or kid not in chaves_por_kid:
            chaves_por_kid = await self._buscar_e_cachear()
        if kid not in chaves_por_kid:
            raise EntraAuthError(f"kid {kid!r} não encontrado na JWKS do tenant {self._tenant_id!r}")
        return chaves_por_kid[kid]

    async def _buscar_e_cachear(self) -> dict[str, dict[str, Any]]:
        url_base = f"https://login.microsoftonline.com/{self._tenant_id}"
        try:
            corpo = await get_json(url_base, "/discovery/v2.0/keys", {}, source=SOURCE)
        except UpstreamError as exc:
            logger.warning("falha ao buscar JWKS do Entra (tenant=%s): %s", self._tenant_id, exc)
            raise EntraJWKSIndisponivelError(str(exc)) from exc
        chaves_por_kid = {chave["kid"]: chave for chave in (corpo or {}).get("keys", []) if "kid" in chave}
        cache.set(self._cache_key, chaves_por_kid, self._ttl_seconds)
        return chaves_por_kid


# Uma JWKSCache por tenant, reaproveitada entre chamadas (evita recriar o
# objeto — sem estado próprio além da referência ao cache global de
# utils/cache.py, então uma instância por tenant já basta).
_jwks_caches: dict[str, JWKSCache] = {}


def _obter_jwks_cache(tenant_id: str) -> JWKSCache:
    jwks_cache = _jwks_caches.get(tenant_id)
    if jwks_cache is None:
        jwks_cache = JWKSCache(tenant_id)
        _jwks_caches[tenant_id] = jwks_cache
    return jwks_cache


def _issuers_aceitos(tenant_id: str) -> tuple[str, str]:
    return (
        f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        f"https://sts.windows.net/{tenant_id}/",
    )


async def validar_token(token: str) -> dict[str, Any]:
    """Decodifica e valida um JWT do Entra ID; devolve os claims se tudo passar.

    Levanta :class:`EntraAuthError` (401) para qualquer problema do próprio
    token (assinatura, header malformado, ``aud``/``iss`` incorretos,
    ``exp``/``nbf``, scope ausente). Levanta :class:`EntraJWKSIndisponivelError`
    (503) se não for possível buscar a JWKS do Entra por instabilidade de
    rede — nesse caso o problema não é do token/cliente.
    """
    tenant_id = settings.entra_tenant_id
    client_id = settings.entra_client_id
    if not tenant_id or not client_id:
        # Defesa: este módulo só deveria ser chamado quando
        # entra_auth_habilitado é True (ver config.py) — chamar sem os dois
        # configurados é erro de programação do chamador, não do token.
        raise RuntimeError(
            "auth.entra.validar_token chamado sem ENTRA_TENANT_ID/ENTRA_CLIENT_ID configurados"
        )

    try:
        cabecalho = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise EntraAuthError(f"token malformado: {exc}") from exc

    kid = cabecalho.get("kid")
    if not kid:
        raise EntraAuthError("token sem 'kid' no header")

    jwk_chave = await _obter_jwks_cache(tenant_id).obter_chave(kid)
    try:
        chave_publica = jwt.PyJWK.from_dict(jwk_chave).key
    except jwt.InvalidKeyError as exc:
        raise EntraAuthError(f"JWK inválida para kid={kid!r}: {exc}") from exc

    try:
        claims = jwt.decode(
            token,
            key=chave_publica,
            algorithms=_ALGORITMOS_ACEITOS,
            audience=client_id,
            # iss é validado manualmente logo abaixo, porque o Entra emite
            # duas variantes válidas (v1 e v2) para o mesmo tenant — o
            # verificador nativo do PyJWT só aceita um único valor fixo.
            options={"verify_iss": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise EntraAuthError("token expirado (exp)") from exc
    except jwt.ImmatureSignatureError as exc:
        raise EntraAuthError("token ainda não válido (nbf)") from exc
    except jwt.InvalidAudienceError as exc:
        raise EntraAuthError("audience (aud) do token não corresponde a ENTRA_CLIENT_ID") from exc
    except jwt.InvalidSignatureError as exc:
        raise EntraAuthError("assinatura do token inválida") from exc
    except jwt.InvalidTokenError as exc:
        raise EntraAuthError(f"token inválido: {exc}") from exc

    if claims.get("iss") not in _issuers_aceitos(tenant_id):
        raise EntraAuthError(f"issuer (iss) inesperado: {claims.get('iss')!r}")

    if settings.entra_required_scope:
        scopes_delegados = set((claims.get("scp") or "").split())
        roles_aplicacao = set(claims.get("roles") or [])
        if settings.entra_required_scope not in (scopes_delegados | roles_aplicacao):
            raise EntraAuthError(
                f"scope/role {settings.entra_required_scope!r} ausente no token "
                "(nem em 'scp' nem em 'roles')"
            )

    logger.info(
        "token Entra validado sub=%s oid=%s tenant=%s",
        claims.get("sub"), claims.get("oid"), tenant_id,
    )
    return claims


def _resetar_caches_para_teste() -> None:
    """Limpa o dict de ``JWKSCache`` por tenant. Usado só em testes."""
    _jwks_caches.clear()
