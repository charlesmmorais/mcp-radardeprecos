"""Testes de `observability` (contadores em memória por tool, item 13, v0.2.6)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos import observability


@pytest.fixture(autouse=True)
def _resetar_metricas():
    observability.resetar()
    yield
    observability.resetar()


def test_sem_chamadas_devolve_dicionario_vazio():
    assert observability.obter_metricas() == {}


def test_registra_uma_chamada_bem_sucedida():
    observability.registrar_chamada("minha_tool", 0.1, True)
    metricas = observability.obter_metricas()
    assert metricas["minha_tool"]["chamadas"] == 1
    assert metricas["minha_tool"]["erros"] == 0
    assert metricas["minha_tool"]["duracao_media_ms"] == pytest.approx(100.0, rel=0.01)


def test_registra_chamada_com_erro():
    observability.registrar_chamada("minha_tool", 0.05, False)
    metricas = observability.obter_metricas()
    assert metricas["minha_tool"]["chamadas"] == 1
    assert metricas["minha_tool"]["erros"] == 1


def test_acumula_chamadas_da_mesma_tool():
    observability.registrar_chamada("minha_tool", 0.1, True)
    observability.registrar_chamada("minha_tool", 0.2, True)
    observability.registrar_chamada("minha_tool", 0.3, False)
    metricas = observability.obter_metricas()
    assert metricas["minha_tool"]["chamadas"] == 3
    assert metricas["minha_tool"]["erros"] == 1
    assert metricas["minha_tool"]["duracao_media_ms"] == pytest.approx(200.0, rel=0.01)


def test_tools_diferentes_tem_contadores_independentes():
    observability.registrar_chamada("tool_a", 0.1, True)
    observability.registrar_chamada("tool_b", 0.2, False)
    metricas = observability.obter_metricas()
    assert set(metricas.keys()) == {"tool_a", "tool_b"}
    assert metricas["tool_a"]["erros"] == 0
    assert metricas["tool_b"]["erros"] == 1


def test_p95_com_amostra_unica_igual_a_duracao():
    observability.registrar_chamada("minha_tool", 0.5, True)
    metricas = observability.obter_metricas()
    assert metricas["minha_tool"]["duracao_p95_ms"] == pytest.approx(500.0, rel=0.01)


def test_p95_maior_ou_igual_a_media_em_distribuicao_assimetrica():
    # Muitas chamadas rápidas, uma bem lenta — p95 deve refletir a cauda,
    # não ficar "escondido" atrás da média.
    for _ in range(19):
        observability.registrar_chamada("minha_tool", 0.01, True)
    observability.registrar_chamada("minha_tool", 2.0, True)
    metricas = observability.obter_metricas()
    assert metricas["minha_tool"]["duracao_p95_ms"] >= metricas["minha_tool"]["duracao_media_ms"]


def test_janela_limitada_de_amostras_nao_cresce_sem_limite():
    for _i in range(observability._MAX_AMOSTRAS_DURACAO + 50):
        observability.registrar_chamada("minha_tool", 0.01, True)
    with observability._lock:
        assert len(observability._duracoes["minha_tool"]) == observability._MAX_AMOSTRAS_DURACAO
    # O contador de chamadas totais não é afetado pelo limite de amostras
    # de duração — continua contando cada chamada.
    metricas = observability.obter_metricas()
    assert metricas["minha_tool"]["chamadas"] == observability._MAX_AMOSTRAS_DURACAO + 50


def test_resetar_zera_todos_os_contadores():
    observability.registrar_chamada("minha_tool", 0.1, True)
    observability.resetar()
    assert observability.obter_metricas() == {}
