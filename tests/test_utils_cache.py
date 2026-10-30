"""Testes do cache em memória com TTL (utils/cache.py)."""
from __future__ import annotations

import time

from mcp_radardeprecos.utils import cache


def setup_function():
    cache.clear()


def test_get_retorna_none_para_chave_ausente():
    assert cache.get("inexistente") is None


def test_set_e_get_devolvem_o_mesmo_valor():
    cache.set("chave", {"a": 1}, ttl_seconds=60)
    assert cache.get("chave") == {"a": 1}


def test_get_expira_apos_ttl():
    cache.set("chave", "valor", ttl_seconds=0.05)
    assert cache.get("chave") == "valor"
    time.sleep(0.1)
    assert cache.get("chave") is None


def test_clear_remove_todas_as_chaves():
    cache.set("a", 1, ttl_seconds=60)
    cache.set("b", 2, ttl_seconds=60)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_limite_de_entradas_descarta_a_mais_antiga(monkeypatch):
    # v0.1.53: teto de memória para o processo HTTP multi-usuário (FIFO).
    monkeypatch.setattr(cache, "MAX_ENTRADAS", 3)
    cache.set("a", 1, ttl_seconds=60)
    cache.set("b", 2, ttl_seconds=60)
    cache.set("c", 3, ttl_seconds=60)
    cache.set("d", 4, ttl_seconds=60)  # estoura o teto -> "a" (mais antiga) sai
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert cache.get("d") == 4


def test_limite_remove_expiradas_antes_de_descartar_validas(monkeypatch):
    monkeypatch.setattr(cache, "MAX_ENTRADAS", 3)
    cache.set("expirada", 0, ttl_seconds=0.0)  # já nasce expirada
    cache.set("b", 2, ttl_seconds=60)
    cache.set("c", 3, ttl_seconds=60)
    cache.set("d", 4, ttl_seconds=60)  # deve sacrificar "expirada", não "b"
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert cache.get("d") == 4


def test_atualizar_chave_existente_no_teto_nao_descarta_nada(monkeypatch):
    monkeypatch.setattr(cache, "MAX_ENTRADAS", 2)
    cache.set("a", 1, ttl_seconds=60)
    cache.set("b", 2, ttl_seconds=60)
    cache.set("a", 10, ttl_seconds=60)  # update, não inserção — nada sai
    assert cache.get("a") == 10
    assert cache.get("b") == 2
