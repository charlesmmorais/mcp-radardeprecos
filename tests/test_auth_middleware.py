"""Testes de ``auth/middleware.py`` — 100% offline.

Mesmo padrão de ``tests/test_rate_limit.py`` para testar um middleware ASGI
puro: um app interno de eco (``_app_ok``) por trás de
``httpx.ASGITransport``. A validação real do token é exercitada de ponta a
ponta (via ``auth.entra.validar_token``, com a JWKS mockada por ``respx``)
— não mockamos ``validar_token`` diretamente, para also cobrir a integração
entre os dois módulos.
"""
from __future__ import annotations

import httpx
import respx

from mcp_radardeprecos.auth.middleware import EntraAuthMiddleware
from tests.conftest import ENTRA_JWKS_URL_TESTE


async def _app_ok(scope, receive, send):
    claims = scope.get("entra_claims")
    corpo = b'{"ok": true, "sub": "%s"}' % (claims.get("sub").encode() if claims else b"null")
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": corpo})


async def _cliente(app, headers: dict | None = None, base_url: str = "http://servidor.exemplo") -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url=base_url, headers=headers or {})


def _mockar_jwks(mock: respx.MockRouter, jwk: dict) -> None:
    mock.get(ENTRA_JWKS_URL_TESTE).mock(return_value=httpx.Response(200, json={"keys": [jwk]}))


async def test_token_valido_passa_e_injeta_claims_no_scope(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar()
    app = EntraAuthMiddleware(_app_ok)
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        async with await _cliente(app, {"Authorization": f"Bearer {entra_fazer_token()}"}) as client:
            r = await client.get("/mcp")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "sub": "usuario-teste"}


async def test_sem_header_authorization_devolve_401_com_www_authenticate(entra_habilitar):
    entra_habilitar()
    app = EntraAuthMiddleware(_app_ok)
    async with await _cliente(app) as client:
        r = await client.get("/mcp")
    assert r.status_code == 401
    www_auth = r.headers.get("www-authenticate")
    assert www_auth is not None
    assert www_auth.startswith("Bearer")
    assert 'resource_metadata="http://servidor.exemplo/.well-known/oauth-protected-resource"' in www_auth


async def test_header_authorization_sem_bearer_devolve_401(entra_habilitar):
    entra_habilitar()
    app = EntraAuthMiddleware(_app_ok)
    async with await _cliente(app, {"Authorization": "Basic dXNlcjpwYXNz"}) as client:
        r = await client.get("/mcp")
    assert r.status_code == 401


async def test_bearer_vazio_devolve_401(entra_habilitar):
    entra_habilitar()
    app = EntraAuthMiddleware(_app_ok)
    async with await _cliente(app, {"Authorization": "Bearer "}) as client:
        r = await client.get("/mcp")
    assert r.status_code == 401


async def test_token_invalido_devolve_401_com_error_invalid_token(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar()
    token_expirado = entra_fazer_token(exp=0)
    app = EntraAuthMiddleware(_app_ok)
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        async with await _cliente(app, {"Authorization": f"Bearer {token_expirado}"}) as client:
            r = await client.get("/mcp")
    assert r.status_code == 401
    www_auth = r.headers.get("www-authenticate")
    assert 'error="invalid_token"' in www_auth
    assert "resource_metadata=" in www_auth


async def test_jwks_indisponivel_devolve_503(entra_habilitar, entra_fazer_token):
    entra_habilitar()
    token = entra_fazer_token()
    app = EntraAuthMiddleware(_app_ok)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ENTRA_JWKS_URL_TESTE).mock(side_effect=httpx.ConnectError("instabilidade"))
        async with await _cliente(app, {"Authorization": f"Bearer {token}"}) as client:
            r = await client.get("/mcp")
    assert r.status_code == 503


async def test_health_check_raiz_passa_sem_token(entra_habilitar):
    entra_habilitar()
    app = EntraAuthMiddleware(_app_ok)
    async with await _cliente(app) as client:
        r = await client.get("/")
    assert r.status_code == 200


async def test_well_known_passa_sem_token(entra_habilitar):
    entra_habilitar()
    app = EntraAuthMiddleware(_app_ok)
    async with await _cliente(app) as client:
        r = await client.get("/.well-known/oauth-protected-resource")
        r2 = await client.get("/.well-known/qualquer-outra-coisa")
    assert r.status_code == 200
    assert r2.status_code == 200


async def test_rota_protocolo_normal_exige_token_mesmo_com_entra_habilitado(entra_habilitar):
    # Regressão: só "/" e "/.well-known/*" são isentos — qualquer outra
    # rota (inclusive "/mcp"/"/sse", o próprio protocolo) exige token
    # quando a auth Entra está ligada.
    entra_habilitar()
    app = EntraAuthMiddleware(_app_ok)
    async with await _cliente(app) as client:
        r = await client.get("/sse")
    assert r.status_code == 401


async def test_ignora_scopes_nao_http(entra_habilitar):
    entra_habilitar()
    chamadas = []

    async def app_lifespan(scope, receive, send):
        chamadas.append(scope["type"])

    middleware = EntraAuthMiddleware(app_lifespan)

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        pass

    await middleware({"type": "lifespan"}, receive, send)
    assert chamadas == ["lifespan"]


async def test_scope_exigido_ausente_devolve_401_via_middleware(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar(entra_required_scope="Leitura.Tools")
    token = entra_fazer_token()  # sem scp/roles
    app = EntraAuthMiddleware(_app_ok)
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        async with await _cliente(app, {"Authorization": f"Bearer {token}"}) as client:
            r = await client.get("/mcp")
    assert r.status_code == 401
