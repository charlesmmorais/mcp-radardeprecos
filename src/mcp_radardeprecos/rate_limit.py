"""Rate limiting simples por IP para os transportes HTTP (sse/streamable-http).

Este servidor **não implementa OAuth nem autenticação por usuário**. Essa foi
uma decisão deliberada, não uma lacuna esquecida: todos os dados expostos
pelas tools (PNCP, Compras.gov.br) são públicos e as tools são somente
leitura — não existe dado privado por usuário para isolar, então autenticar
"quem" está chamando não traria isolamento de informação nenhum.

O que *precisa* existir, para rodar exposto publicamente via HTTP
(``--transport sse``/``streamable-http``) a múltiplos usuários simultâneos,
é uma proteção simples contra abuso: um único chamador (um bug num cliente,
um loop, um scraper) não deve conseguir sozinho esgotar a capacidade do
processo ou gerar carga excessiva contra as APIs upstream (PNCP/
Compras.gov.br) em nome de todos os outros usuários que compartilham o
mesmo servidor.

Implementação: janela deslizante (*sliding window*) por chave de origem
(IP), inteiramente em memória — sem dependência externa (Redis etc.).
Isso é suficiente para um único processo; se o servidor rodar com várias
réplicas atrás de um load balancer, cada réplica mantém seu próprio
contador (limite efetivo = limite configurado × número de réplicas). Para
esse caso mais avançado seria necessário um contador compartilhado (ex.:
Redis) — deliberadamente fora de escopo aqui, dado o volume esperado deste
servidor.

A chave de origem (ver :func:`ip_de_origem`) vem, nesta ordem, de
``Fly-Client-IP`` (definido pelo proxy do Fly.io, que descarta o valor
enviado pelo cliente), do **último** IP de ``X-Forwarded-For`` (o que o
proxy mais próximo acrescentou) e, por fim, do IP da conexão TCP. Até a
v0.6.4 usava-se o *primeiro* IP do ``X-Forwarded-For`` — valor escrito pelo
próprio cliente: bastava variar o cabeçalho a cada requisição para nunca
ser barrado, e cada valor inventado criava uma chave nova que nunca era
removida (memória crescendo sem teto). Agora as chaves sem registro na
janela são varridas periodicamente.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

_JANELA_PADRAO_SEGUNDOS = 60.0


class RateLimiter:
    """Limitador de taxa por chave, em janela deslizante, em memória."""

    def __init__(
        self,
        limite_por_minuto: int,
        *,
        agora: Callable[[], float] = time.monotonic,
    ) -> None:
        if limite_por_minuto <= 0:
            raise ValueError("limite_por_minuto deve ser positivo")
        self._limite = limite_por_minuto
        self._janela_segundos = _JANELA_PADRAO_SEGUNDOS
        self._agora = agora
        self._registros: dict[str, deque[float]] = defaultdict(deque)
        self._ultima_varredura = self._agora()

    def _varrer_chaves_expiradas(self, limite_inferior: float) -> None:
        """Remove chaves cujo registro mais recente já saiu da janela."""
        expiradas = [
            chave for chave, fila in self._registros.items()
            if not fila or fila[-1] <= limite_inferior
        ]
        for chave in expiradas:
            del self._registros[chave]

    def permitir(self, chave: str) -> bool:
        """Devolve True se a requisição pode prosseguir, False se deve ser barrada."""
        agora = self._agora()
        limite_inferior = agora - self._janela_segundos
        # Uma varredura por janela: custo O(chaves) amortizado, e a memória
        # fica limitada às origens vistas nos últimos ~2 minutos.
        if agora - self._ultima_varredura >= self._janela_segundos:
            self._varrer_chaves_expiradas(limite_inferior)
            self._ultima_varredura = agora
        fila = self._registros[chave]
        while fila and fila[0] <= limite_inferior:
            fila.popleft()
        if len(fila) >= self._limite:
            return False
        fila.append(agora)
        return True


def ip_de_origem(scope: dict[str, Any]) -> str | None:
    """IP de origem da requisição, preferindo fontes que o cliente não controla.

    1. ``Fly-Client-IP``: o proxy do Fly.io sobrescreve este cabeçalho.
    2. Último item de ``X-Forwarded-For``: acrescentado pelo proxy mais
       próximo. Os itens anteriores vêm do cliente e podem ser inventados.
    3. IP da conexão TCP (sem proxy na frente).
    """
    headers = dict(scope.get("headers") or [])
    fly_ip = headers.get(b"fly-client-ip")
    if fly_ip:
        valor = fly_ip.decode("latin-1").strip()
        if valor:
            return valor
    xff = headers.get(b"x-forwarded-for")
    if xff:
        ultimo = xff.decode("latin-1").split(",")[-1].strip()
        if ultimo:
            return ultimo
    client = scope.get("client")
    if client:
        return str(client[0])
    return None


def _chave_cliente(scope: dict[str, Any]) -> str:
    return ip_de_origem(scope) or "desconhecido"


async def _responder_429(send: Callable[[dict[str, Any]], Any]) -> None:
    corpo = b'{"erro": "limite de requisicoes excedido, tente novamente em instantes"}'
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", b"60"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": corpo})


class RateLimitMiddleware:
    """Middleware ASGI puro (compatível com Starlette) que aplica ``RateLimiter``.

    Só atua sobre requisições HTTP (``scope["type"] == "http"``); eventos de
    lifespan e websocket passam direto, sem contabilizar limite.
    """

    def __init__(self, app: Any, *, limiter: RateLimiter) -> None:
        self._app = app
        self._limiter = limiter

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        chave = _chave_cliente(scope)
        if not self._limiter.permitir(chave):
            await _responder_429(send)
            return

        await self._app(scope, receive, send)
