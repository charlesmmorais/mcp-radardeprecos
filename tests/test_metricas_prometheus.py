"""Testes da exportação Prometheus e do registro de cliente MCP."""
from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest

from mcp_radardeprecos import metricas_prometheus, observability, server

obs = observability
prometheus_client = pytest.importorskip("prometheus_client")


@pytest.fixture(autouse=True)
def _zerar():
    obs.resetar()
    yield
    obs.resetar()


def _exposicao() -> str:
    return prometheus_client.generate_latest(metricas_prometheus.criar_registro()).decode()


def test_exporta_tools_fontes_clientes_e_sessoes():
    obs.registrar_chamada("buscar_pncp_texto", 0.2, True)
    obs.registrar_chamada("buscar_pncp_texto", 0.4, False)
    obs.registrar_upstream("PNCP", 0.3, True, tentativas=3)
    nova = obs.registrar_sessao("s1", "buscar_pncp_texto")
    obs.registrar_cliente("claude-ai", nova)
    obs.registrar_protocolo("2025-06-18")

    texto = _exposicao()

    assert 'radardeprecos_tool_chamadas_total{tool="buscar_pncp_texto"} 2.0' in texto
    assert 'radardeprecos_tool_erros_total{tool="buscar_pncp_texto"} 1.0' in texto
    assert 'radardeprecos_tool_duracao_segundos{tool="buscar_pncp_texto",quantil="p95"}' in texto
    assert 'radardeprecos_fonte_chamadas_total{fonte="PNCP"} 1.0' in texto
    assert 'radardeprecos_fonte_tentativas_total{fonte="PNCP"} 3.0' in texto
    assert 'radardeprecos_cliente_sessoes_total{cliente="claude-ai"} 1.0' in texto
    assert 'radardeprecos_cliente_chamadas_total{cliente="claude-ai"} 1.0' in texto
    assert "radardeprecos_sessoes_total 1.0" in texto
    assert 'radardeprecos_protocolo_chamadas_total{versao="2025-06-18"} 1.0' in texto
    assert 'radardeprecos_info{versao="' in texto


def test_sem_chamadas_exporta_sem_erro():
    texto = _exposicao()
    assert "radardeprecos_info" in texto
    assert "radardeprecos_sessoes_total 0.0" in texto


def test_sessao_nova_e_detectada_uma_vez():
    assert obs.registrar_sessao("s1", "t") is True
    assert obs.registrar_sessao("s1", "t") is False
    assert obs.registrar_sessao(None, "t") is False


def test_sessoes_vistas_nao_diminuem_quando_a_memoria_descarta(monkeypatch):
    """O contador do Prometheus é monotônico; a memória de sessões, não."""
    monkeypatch.setattr(
        obs, "settings", dataclasses.replace(obs.settings, observabilidade_max_sessoes=1)
    )
    for i in range(4):
        obs.registrar_sessao(f"s{i}", "t")
    dados = obs.instantaneo_prometheus()
    assert dados["sessoes_em_memoria"] == 1
    assert dados["sessoes_vistas"] == 4


@pytest.mark.parametrize(
    "bruto, esperado",
    [
        ("claude-ai", "claude-ai"),
        ("ChatGPT 5.1", "ChatGPT 5.1"),
        ('x"}\n{y', "xy"),
        ("", "(desconhecido)"),
        (None, "(desconhecido)"),
        ("a" * 80, "a" * 40),
    ],
)
def test_nome_do_cliente_e_normalizado(bruto, esperado):
    assert obs.normalizar_cliente(bruto) == esperado


def test_nomes_de_cliente_tem_teto():
    for i in range(obs._MAX_CLIENTES + 5):
        obs.registrar_cliente(f"cliente{i}", True)
    clientes = obs.instantaneo_prometheus()["clientes"]
    assert len(clientes) == obs._MAX_CLIENTES + 1
    assert clientes["(outros)"]["sessoes"] == 5


def test_visao_completa_traz_por_cliente():
    obs.registrar_cliente("gemini", True)
    assert obs.obter_metricas_completas()["por_cliente"] == {
        "gemini": {"chamadas": 1, "sessoes": 1}
    }


# --- Ligação pelo servidor ---------------------------------------------------


@pytest.mark.parametrize("valor", ["", "abc", "0", "70000"])
def test_porta_vazia_ou_invalida_nao_liga_metricas(valor):
    with patch.object(metricas_prometheus, "iniciar_servidor") as iniciar:
        assert server._iniciar_metricas(valor) is False
    iniciar.assert_not_called()


def test_porta_valida_liga_metricas():
    with patch.object(metricas_prometheus, "iniciar_servidor", return_value=True) as iniciar:
        assert server._iniciar_metricas("9091") is True
    iniciar.assert_called_once_with(9091)


def test_run_http_le_a_porta_do_ambiente(monkeypatch):
    monkeypatch.setenv(server.ENV_PORTA_METRICAS, "9091")
    with (
        patch.object(server, "_iniciar_metricas") as iniciar,
        patch("mcp_radardeprecos.server.uvicorn"),
        patch("mcp_radardeprecos.server.anyio"),
    ):
        server._run_http("streamable-http", 60)
    iniciar.assert_called_once_with("9091")


def test_cai_para_ipv4_se_ipv6_falhar():
    chamadas = []

    def falso(porta, addr, registry):
        chamadas.append(addr)
        if addr == "::":
            raise OSError("IPv6 indisponível")

    with patch("prometheus_client.start_http_server", side_effect=falso):
        assert metricas_prometheus.iniciar_servidor(9091) is True
    assert chamadas == ["::", "0.0.0.0"]
