"""Cache em memória com TTL, para evitar chamadas de rede repetidas na mesma sessão.

Um dicionário simples com timestamp de expiração por chave, sem persistência entre execuções do
servidor.

Pensado para respostas de leitura que mudam raramente dentro do horizonte de
uma pesquisa (itens de uma contratação, resultado de um item, arquivos,
detalhe de ata) — não para a busca textual (``buscar_texto``), cujo
resultado pode mudar a qualquer momento com novos editais publicados e por
isso nunca é cacheado.

Não há invalidação manual além do TTL: como todas as chamadas cacheadas são
leituras de dados públicos e já somente-leitura, uma resposta levemente
desatualizada (até o TTL expirar) é um trade-off aceitável pela redução de
chamadas de rede repetidas.

O cache tem um limite de tamanho (``MAX_ENTRADAS``): num servidor HTTP
multiusuário de vida longa, as chaves distintas crescem sem teto. Ao atingir o limite, entradas
já expiradas são removidas primeiro; se ainda faltar espaço, descarta-se a
mais antiga por ordem de inserção (FIFO — mais simples que LRU e suficiente:
o objetivo é um teto de memória, não maximizar hit rate; re-inserir uma
chave não renova sua posição na fila).
"""
from __future__ import annotations

import time
from typing import Any

TTL_5_MIN = 300.0
TTL_30_MIN = 1800.0
# Catálogos de referência (grupos/classes/PDMs de CATMAT/CATSER) mudam raramente
# — usado por descobrir_codigo_catalogo para não repaginar ~15 mil PDMs a cada
# chamada na mesma sessão (ver clients/compras_client.py).
TTL_1_DIA = 86400.0

#: Teto de entradas do cache (proteção de memória para o processo HTTP
#: multi-usuário; irrelevante na prática no modo stdio de sessão única).
MAX_ENTRADAS = 5000

_cache: dict[str, tuple[float, Any]] = {}


def get(key: str) -> Any | None:
    """Devolve o valor cacheado para ``key``, ou ``None`` se ausente/expirado."""
    entrada = _cache.get(key)
    if entrada is None:
        return None
    expira_em, valor = entrada
    if time.monotonic() >= expira_em:
        del _cache[key]
        return None
    return valor


def set(key: str, valor: Any, ttl_seconds: float) -> None:
    """Armazena ``valor`` sob ``key`` por ``ttl_seconds`` segundos.

    Se o cache estiver no limite (``MAX_ENTRADAS``) e ``key`` for nova,
    remove primeiro as entradas já expiradas e, se ainda necessário, a
    entrada mais antiga por ordem de inserção (FIFO).
    """
    if key not in _cache and len(_cache) >= MAX_ENTRADAS:
        agora = time.monotonic()
        expiradas = [k for k, (expira_em, _) in _cache.items() if agora >= expira_em]
        for k in expiradas:
            del _cache[k]
        while len(_cache) >= MAX_ENTRADAS:
            # dicts preservam ordem de inserção — o primeiro é o mais antigo.
            del _cache[next(iter(_cache))]
    _cache[key] = (time.monotonic() + ttl_seconds, valor)


def clear() -> None:
    """Limpa todo o cache. Usado apenas para isolar testes entre si."""
    _cache.clear()
