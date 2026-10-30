"""Testes de `gerar_estudo_mercado_tic` (tool pura, sem chamada de rede)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos.tools.gerar_estudo_mercado_tic import gerar_estudo_mercado_tic


async def test_rejeita_lista_vazia():
    with pytest.raises(ValueError, match="vazia"):
        await gerar_estudo_mercado_tic([])


async def test_rejeita_solucao_sem_nome():
    with pytest.raises(ValueError, match="nome"):
        await gerar_estudo_mercado_tic([{"criterios": {"x": 1}}])


async def test_rejeita_criterios_que_nao_e_dict():
    with pytest.raises(ValueError, match="criterios"):
        await gerar_estudo_mercado_tic([{"nome": "Solução A", "criterios": ["x"]}])


async def test_rejeita_nomes_duplicados():
    solucoes = [
        {"nome": "Solução A", "criterios": {"x": 1}},
        {"nome": "Solução A", "criterios": {"x": 2}},
    ]
    with pytest.raises(ValueError, match="duplicados"):
        await gerar_estudo_mercado_tic(solucoes)


async def test_rejeita_solucao_recomendada_fora_da_lista():
    solucoes = [{"nome": "Solução A", "criterios": {"x": 1}}]
    with pytest.raises(ValueError, match="solucao_recomendada"):
        await gerar_estudo_mercado_tic(solucoes, solucao_recomendada="Solução Inexistente")


async def test_monta_matriz_com_uniao_de_criterios_na_ordem_de_aparicao():
    solucoes = [
        {
            "nome": "SaaS Fornecedor X",
            "criterios": {"modelo_licenciamento": "SaaS anual", "tco_36_meses": 450000.0},
        },
        {
            "nome": "On-premise Fornecedor Y",
            "criterios": {"tco_36_meses": 620000.0, "requer_infra_propria": True},
        },
    ]
    resultado = await gerar_estudo_mercado_tic(solucoes)

    assert resultado["criterios_comparados"] == [
        "modelo_licenciamento", "tco_36_meses", "requer_infra_propria",
    ]
    assert resultado["matriz"] == [
        {
            "criterio": "modelo_licenciamento",
            "SaaS Fornecedor X": "SaaS anual",
            "On-premise Fornecedor Y": None,
        },
        {
            "criterio": "tco_36_meses",
            "SaaS Fornecedor X": 450000.0,
            "On-premise Fornecedor Y": 620000.0,
        },
        {
            "criterio": "requer_infra_propria",
            "SaaS Fornecedor X": None,
            "On-premise Fornecedor Y": True,
        },
    ]


async def test_preserva_solucoes_originais_no_retorno():
    solucoes = [
        {"nome": "Solução A", "fabricante": "Empresa X", "criterios": {"x": 1}},
    ]
    resultado = await gerar_estudo_mercado_tic(solucoes)
    assert resultado["solucoes"][0]["fabricante"] == "Empresa X"


async def test_aviso_uma_unica_solucao():
    resultado = await gerar_estudo_mercado_tic([{"nome": "Solução Única", "criterios": {"x": 1}}])
    assert any("Apenas 1 solução" in a for a in resultado["avisos"])


async def test_sem_aviso_de_solucao_unica_com_duas_solucoes():
    solucoes = [
        {"nome": "Solução A", "criterios": {"x": 1}},
        {"nome": "Solução B", "criterios": {"x": 2}},
    ]
    resultado = await gerar_estudo_mercado_tic(solucoes)
    assert not any("Apenas 1 solução" in a for a in resultado["avisos"])


async def test_aviso_matriz_vazia_sem_criterios():
    solucoes = [{"nome": "Solução A"}, {"nome": "Solução B"}]
    resultado = await gerar_estudo_mercado_tic(solucoes)
    assert resultado["criterios_comparados"] == []
    assert resultado["matriz"] == []
    assert any("matriz ficou vazia" in a for a in resultado["avisos"])


async def test_aviso_comparacao_incompleta_quando_criterios_nao_batem():
    solucoes = [
        {"nome": "Solução A", "criterios": {"x": 1, "y": 2}},
        {"nome": "Solução B", "criterios": {"x": 1}},
    ]
    resultado = await gerar_estudo_mercado_tic(solucoes)
    assert any("Comparação incompleta" in a and "Solução B" in a for a in resultado["avisos"])


async def test_sem_aviso_de_incompleta_quando_criterios_batem():
    solucoes = [
        {"nome": "Solução A", "criterios": {"x": 1, "y": 2}},
        {"nome": "Solução B", "criterios": {"x": 3, "y": 4}},
    ]
    resultado = await gerar_estudo_mercado_tic(solucoes)
    assert not any("Comparação incompleta" in a for a in resultado["avisos"])


async def test_aviso_recomendada_sem_justificativa():
    solucoes = [
        {"nome": "Solução A", "criterios": {"x": 1}},
        {"nome": "Solução B", "criterios": {"x": 2}},
    ]
    resultado = await gerar_estudo_mercado_tic(solucoes, solucao_recomendada="Solução A")
    assert any("sem justificativa_escolha" in a for a in resultado["avisos"])


async def test_sem_aviso_recomendada_com_justificativa():
    solucoes = [
        {"nome": "Solução A", "criterios": {"x": 1}},
        {"nome": "Solução B", "criterios": {"x": 2}},
    ]
    resultado = await gerar_estudo_mercado_tic(
        solucoes, solucao_recomendada="Solução A", justificativa_escolha="Melhor custo total."
    )
    assert not any("sem justificativa_escolha" in a for a in resultado["avisos"])
    assert resultado["solucao_recomendada"] == "Solução A"
    assert resultado["justificativa_escolha"] == "Melhor custo total."
