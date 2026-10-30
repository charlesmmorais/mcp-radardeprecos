"""Testes de src/mcp_radardeprecos/rate_limit.py."""
from __future__ import annotations

import httpx
import pytest

from mcp_radardeprecos.rate_limit import RateLimiter, RateLimitMiddleware


def test_rate_limiter_rejeita_apos_limite() -> None:
    relogio = _Relogio()
    limiter = RateLimiter(limite_por_minuto=3, agora=relogio.agora)

    assert limiter.permitir("1.2.3.4") is True
    assert limiter.permitir("1.2.3.4") is True
    assert limiter.permitir("1.2.3.4") is True
    assert limiter.permitir("1.2.3.4") is False


def test_rate_limiter_janela_desliza_e_libera_espaco() -> None:
    relogio = _Relogio()
    limiter = RateLimiter(limite_por_minuto=2, agora=relogio.agora)

    assert limiter.permitir("1.2.3.4") is True
    assert limiter.permitir("1.2.3.4") is True
    assert limiter.permitir("1.2.3.4") is False

    relogio.avancar(61)
    assert limiter.permitir("1.2.3.4") is True


def test_rate_limiter_chaves_diferentes_sao_independentes() -> None:
    relogio = _Relogio()
    limiter = RateLimiter(limite_por_minuto=1, agora=relogio.agora)

    assert limiter.permitir("1.2.3.4") is True
    assert limiter.permitir("1.2.3.4") is False
    assert limiter.permitir("5.6.7.8") is True


def test_rate_limiter_rejeita_limite_nao_positivo() -> None:
    with pytest.raises(ValueError):
        RateLimiter(limite_por_minuto=0)


class _Relogio:
    def __init__(self) -> None:
        self._t = 0.0

    def agora(self) -> float:
        return self._t

    def avancar(self, segundos: float) -> None:
        self._t += segundos


async def _app_ok(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _cliente(app: RateLimitMiddleware, x_forwarded_for: str | None = None) -> httpx.AsyncClient:
    headers = {"X-Forwarded-For": x_forwarded_for} if x_forwarded_for else {}
    transport = httpx.ASGITransport(app=app, client=("9.9.9.9", 12345))
    return httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers)


async def test_middleware_permite_ate_o_limite_depois_bloqueia() -> None:
    limiter = RateLimiter(limite_por_minuto=2)
    app = RateLimitMiddleware(_app_ok, limiter=limiter)

    async with await _cliente(app) as client:
        r1 = await client.get("/mcp")
        r2 = await client.get("/mcp")
        r3 = await client.get("/mcp")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert "erro" in r3.json()


async def test_middleware_usa_ultimo_ip_do_x_forwarded_for() -> None:
    limiter = RateLimiter(limite_por_minuto=1)
    app = RateLimitMiddleware(_app_ok, limiter=limiter)

    async with await _cliente(app, x_forwarded_for="10.0.0.1, 172.16.0.1") as client:
        r1 = await client.get("/mcp")

    # A chave é o ÚLTIMO IP (acrescentado pelo proxy), não o primeiro (do cliente).
    assert r1.status_code == 200
    assert limiter.permitir("172.16.0.1") is False
    assert limiter.permitir("10.0.0.1") is True


async def test_middleware_nao_e_burlado_variando_o_inicio_do_xff() -> None:
    # Regressão: com o primeiro IP do XFF como chave, inventar um valor novo
    # a cada requisição zerava o limite.
    limiter = RateLimiter(limite_por_minuto=2)
    app = RateLimitMiddleware(_app_ok, limiter=limiter)

    status = []
    for i in range(4):
        async with await _cliente(app, x_forwarded_for=f"1.1.1.{i}, 200.0.0.1") as c:
            status.append((await c.get("/mcp")).status_code)

    assert status == [200, 200, 429, 429]


async def test_middleware_prefere_fly_client_ip() -> None:
    limiter = RateLimiter(limite_por_minuto=1)
    app = RateLimitMiddleware(_app_ok, limiter=limiter)
    transport = httpx.ASGITransport(app=app, client=("9.9.9.9", 12345))
    headers = {"Fly-Client-IP": "200.1.2.3", "X-Forwarded-For": "6.6.6.6, 7.7.7.7"}

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
        assert (await c.get("/mcp")).status_code == 200

    assert limiter.permitir("200.1.2.3") is False
    assert limiter.permitir("7.7.7.7") is True


def test_rate_limiter_remove_chaves_expiradas() -> None:
    relogio = _Relogio()
    limiter = RateLimiter(limite_por_minuto=5, agora=relogio.agora)

    for i in range(100):
        limiter.permitir(f"10.0.0.{i}")
    assert len(limiter._registros) == 100

    relogio.avancar(61)
    limiter.permitir("1.2.3.4")

    assert set(limiter._registros) == {"1.2.3.4"}


async def test_middleware_ips_diferentes_nao_se_afetam() -> None:
    limiter = RateLimiter(limite_por_minuto=1)
    app = RateLimitMiddleware(_app_ok, limiter=limiter)

    async with await _cliente(app, x_forwarded_for="10.0.0.1") as c1:
        r1 = await c1.get("/mcp")
    async with await _cliente(app, x_forwarded_for="10.0.0.2") as c2:
        r2 = await c2.get("/mcp")

    assert r1.status_code == 200
    assert r2.status_code == 200


async def test_middleware_ignora_scopes_nao_http() -> None:
    limiter = RateLimiter(limite_por_minuto=1)

    chamadas = []

    async def app_lifespan(scope, receive, send):
        chamadas.append(scope["type"])

    middleware = RateLimitMiddleware(app_lifespan, limiter=limiter)

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        pass

    await middleware({"type": "lifespan"}, receive, send)
    assert chamadas == ["lifespan"]
