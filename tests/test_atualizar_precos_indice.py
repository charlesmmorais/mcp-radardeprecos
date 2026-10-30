"""Testes da tool atualizar_precos_indice, com o cliente SGS/BCB mockado.

Cobre os três índices de domain.dominios.INDICES_CORRECAO_MONETARIA.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.atualizar_precos_indice import atualizar_precos_indice

# Série sintética: jan=1%, fev=2%, mar=0.5% (última publicada = 2026-03).
SERIE = [
    {"competencia": "2026-01", "variacao_percentual": 1.0},
    {"competencia": "2026-02", "variacao_percentual": 2.0},
    {"competencia": "2026-03", "variacao_percentual": 0.5},
]

# Série com deflação (típica de IGP-M): fev negativo.
SERIE_COM_DEFLACAO = [
    {"competencia": "2026-01", "variacao_percentual": 1.0},
    {"competencia": "2026-02", "variacao_percentual": -0.8},
    {"competencia": "2026-03", "variacao_percentual": 0.5},
]

_PATCH = "mcp_radardeprecos.tools.atualizar_precos_indice.bcb_client.obter_indice_mensal"


@patch(_PATCH, new_callable=AsyncMock)
async def test_fator_composto_e_convencao_de_competencia(mock_serie):
    mock_serie.return_value = SERIE
    resultado = await atualizar_precos_indice(
        [
            {"valor": 100.0, "data": "2025-12-15"},  # dez -> base mar: jan*fev*mar
            {"valor": 100.0, "data": "2026-02-01"},  # fev -> base mar: só mar
            {"valor": 100.0, "data": "2026-03-20"},  # mesma competência da base: 1,0
        ],
        data_base="2026-03",
    )
    assert resultado["data_base"] == "2026-03"
    p1, p2, p3 = resultado["precos_atualizados"]
    assert p1["valor_atualizado"] == pytest.approx(100 * 1.01 * 1.02 * 1.005, abs=1e-4)
    assert p2["valor_atualizado"] == pytest.approx(100 * 1.005, abs=1e-4)
    assert p3["fator_atualizacao"] == 1.0
    assert resultado["valores_atualizados"] == [
        p["valor_atualizado"] for p in resultado["precos_atualizados"]
    ]
    assert resultado["avisos"] == []  # ipca é o padrão — sem aviso metodológico


@patch(_PATCH, new_callable=AsyncMock)
async def test_indice_padrao_e_ipca_com_serie_433(mock_serie):
    mock_serie.return_value = SERIE
    await atualizar_precos_indice([{"valor": 50, "data": "2026-02"}])
    mock_serie.assert_awaited_once()
    assert mock_serie.call_args.args[0] == 433


@patch(_PATCH, new_callable=AsyncMock)
async def test_indice_igpm_usa_serie_189_e_gera_aviso_metodologico(mock_serie):
    mock_serie.return_value = SERIE
    resultado = await atualizar_precos_indice(
        [{"valor": 50, "data": "2026-02"}], indice="igpm"
    )
    assert mock_serie.call_args.args[0] == 189
    assert resultado["indice"] == "IGP-M (FGV, série 189 do SGS/Banco Central)"
    assert resultado["indice_chave"] == "igpm"
    assert any("IPCA é o índice padrão" in a for a in resultado["avisos"])


@patch(_PATCH, new_callable=AsyncMock)
async def test_indice_ipc_fipe_usa_serie_193(mock_serie):
    mock_serie.return_value = SERIE
    resultado = await atualizar_precos_indice(
        [{"valor": 50, "data": "2026-02"}], indice="ipc_fipe"
    )
    assert mock_serie.call_args.args[0] == 193
    assert resultado["indice"] == "IPC-Fipe (Fipe, série 193 do SGS/Banco Central)"


async def test_indice_desconhecido_e_erro_explicito():
    with pytest.raises(ValueError, match="indice deve ser um de"):
        await atualizar_precos_indice([{"valor": 50, "data": "2026-02"}], indice="selic")


@patch(_PATCH, new_callable=AsyncMock)
async def test_igpm_com_deflacao_gera_fator_menor_que_um(mock_serie):
    mock_serie.return_value = SERIE_COM_DEFLACAO
    resultado = await atualizar_precos_indice(
        [{"valor": 100.0, "data": "2026-01"}], data_base="2026-03", indice="igpm",
    )
    fator_esperado = 1.0 * (1 - 0.008) * 1.005  # fev negativo (deflação)
    p = resultado["precos_atualizados"][0]
    assert p["fator_atualizacao"] == pytest.approx(fator_esperado, abs=1e-6)
    assert p["fator_atualizacao"] < 1.0
    assert p["valor_atualizado"] < 100.0


@patch(_PATCH, new_callable=AsyncMock)
async def test_data_base_padrao_e_a_ultima_publicada(mock_serie):
    mock_serie.return_value = SERIE
    resultado = await atualizar_precos_indice([{"valor": 50, "data": "2026-02"}])
    assert resultado["data_base"] == "2026-03"
    assert resultado["precos_atualizados"][0]["valor_atualizado"] == pytest.approx(50 * 1.005)


@patch(_PATCH, new_callable=AsyncMock)
async def test_data_base_sem_indice_publicado_e_erro_explicito(mock_serie):
    mock_serie.return_value = SERIE
    with pytest.raises(ValueError, match="ainda não tem IPCA publicado.*2026-03"):
        await atualizar_precos_indice([{"valor": 10, "data": "2026-01"}], data_base="2026-06")


@patch(_PATCH, new_callable=AsyncMock)
async def test_preco_posterior_a_base_mantido_com_aviso(mock_serie):
    mock_serie.return_value = SERIE
    resultado = await atualizar_precos_indice(
        [{"valor": 10, "data": "2026-03"}], data_base="2026-01"
    )
    assert resultado["precos_atualizados"][0]["fator_atualizacao"] == 1.0
    assert any("POSTERIOR" in a for a in resultado["avisos"])


@patch(_PATCH, new_callable=AsyncMock)
async def test_competencia_faltante_na_serie_e_erro(mock_serie):
    mock_serie.return_value = [
        {"competencia": "2026-01", "variacao_percentual": 1.0},
        {"competencia": "2026-03", "variacao_percentual": 0.5},  # fev faltando
    ]
    with pytest.raises(ValueError, match="não tem a competência 2026-02"):
        await atualizar_precos_indice([{"valor": 10, "data": "2026-01"}], data_base="2026-03")


@patch(_PATCH, new_callable=AsyncMock)
async def test_chaves_extras_sao_preservadas(mock_serie):
    mock_serie.return_value = SERIE
    resultado = await atualizar_precos_indice(
        [{"valor": 10, "data": "2026-02", "fornecedor": "ACME", "uf": "SP"}]
    )
    p = resultado["precos_atualizados"][0]
    assert p["fornecedor"] == "ACME"
    assert p["uf"] == "SP"
    assert p["valor_original"] == 10.0


@patch(_PATCH, new_callable=AsyncMock)
async def test_validacao_de_entrada(mock_serie):
    mock_serie.return_value = SERIE
    with pytest.raises(ValueError, match="lista não vazia"):
        await atualizar_precos_indice([])
    with pytest.raises(ValueError, match="'valor' e 'data'"):
        await atualizar_precos_indice([{"valor": 10}])
    with pytest.raises(ValueError, match="não é numérico"):
        await atualizar_precos_indice([{"valor": "dez", "data": "2026-01"}])
    with pytest.raises(ValueError, match="deve ser positivo"):
        await atualizar_precos_indice([{"valor": 0, "data": "2026-01"}])
    with pytest.raises(ValueError, match="inválida"):
        await atualizar_precos_indice([{"valor": 10, "data": "jan/2026"}])
    mock_serie.assert_not_awaited()  # validação falha antes de qualquer rede


@patch(_PATCH, new_callable=AsyncMock)
async def test_serie_vazia_e_erro_explicito(mock_serie):
    mock_serie.return_value = []
    with pytest.raises(ValueError, match="não devolveu nenhuma variação"):
        await atualizar_precos_indice([{"valor": 10, "data": "2026-01"}])
