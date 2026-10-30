"""Testes da tool normalizar_precos_unidade (pura)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos.tools.normalizar_precos_unidade import (
    normalizar_precos_unidade,
)


async def test_rejeita_unidade_alvo_invalida():
    with pytest.raises(ValueError):
        await normalizar_precos_unidade([{"valor": 100}], "por_hora_maluca")


async def test_lote_usuarios_x_meses_para_usuario_mes():
    # Exemplo real do PLANO: R$120.376,40 por lote de 20 usuários × 36 meses.
    r = await normalizar_precos_unidade(
        [{"valor": 120376.40, "quantidade": 20, "meses": 36, "fornecedor": "X"}],
        "usuario_mes",
    )
    assert r["nao_normalizaveis"] == []
    item = r["normalizados"][0]
    assert item["valor_normalizado"] == pytest.approx(167.1894, abs=1e-3)
    assert item["quantidade"] == 20
    assert item["meses"] == 36
    assert item["fator_aplicado"] == pytest.approx(720)
    assert item["confianca"] == "alta"
    assert item["fornecedor"] == "X"  # campos originais preservados
    assert "120376.4" in item["formula"] and "20" in item["formula"]


async def test_usuario_ano_divide_por_meses_sobre_12():
    r = await normalizar_precos_unidade(
        [{"valor": 3417.72, "quantidade": 1, "meses": 36}], "usuario_ano"
    )
    item = r["normalizados"][0]
    # 3417.72 / (1 × 36/12) = 3417.72 / 3 = 1139.24
    assert item["valor_normalizado"] == pytest.approx(1139.24, abs=1e-2)
    assert "/12) anos" in item["formula"]


async def test_ja_na_unidade_alvo_mantem_valor():
    # quantidade=1, meses=1 → normalizado == valor original.
    r = await normalizar_precos_unidade(
        [{"valor": 178.94, "quantidade": 1, "meses": 1}], "usuario_mes"
    )
    assert r["normalizados"][0]["valor_normalizado"] == pytest.approx(178.94, abs=1e-2)


async def test_sem_meses_para_alvo_com_periodo_vai_para_nao_normalizaveis():
    r = await normalizar_precos_unidade(
        [{"valor": 1000, "quantidade": 10}], "usuario_mes"
    )
    assert r["normalizados"] == []
    assert len(r["nao_normalizaveis"]) == 1
    assert "meses" in r["nao_normalizaveis"][0]["motivo"]


async def test_sem_quantidade_para_alvo_com_base_vai_para_nao_normalizaveis():
    r = await normalizar_precos_unidade([{"valor": 1000, "meses": 12}], "usuario_mes")
    assert r["normalizados"] == []
    assert "quantidade" in r["nao_normalizaveis"][0]["motivo"]


async def test_valor_ausente_vai_para_nao_normalizaveis():
    r = await normalizar_precos_unidade([{"quantidade": 10, "meses": 12}], "usuario_mes")
    assert "valor" in r["nao_normalizaveis"][0]["motivo"]


async def test_premissa_global_marca_confianca_media():
    # meses vem de premissa global, não do registro → confiança 'media'.
    r = await normalizar_precos_unidade(
        [{"valor": 7200, "quantidade": 10}],
        "usuario_mes",
        premissas={"meses": 36},
    )
    item = r["normalizados"][0]
    assert item["confianca"] == "media"
    assert item["origem"]["meses"] == "premissa"
    assert item["valor_normalizado"] == pytest.approx(20.0, abs=1e-6)
    assert any("premissa global" in a for a in r["avisos"])


async def test_mapeamento_de_campos_via_premissas():
    r = await normalizar_precos_unidade(
        [{"vlr": "1.200,00", "qtd": 10, "num_meses": 12}],
        "usuario_mes",
        premissas={"valor_campo": "vlr", "quantidade_campo": "qtd", "meses_campo": "num_meses"},
    )
    item = r["normalizados"][0]
    # 1200 / (10 × 12) = 10.0 ; aceita string com vírgula
    assert item["valor_normalizado"] == pytest.approx(10.0, abs=1e-6)
    assert item["confianca"] == "alta"


async def test_alvo_sem_periodo_nao_exige_meses():
    r = await normalizar_precos_unidade([{"valor": 1000, "quantidade": 5}], "usuario")
    item = r["normalizados"][0]
    assert item["valor_normalizado"] == pytest.approx(200.0, abs=1e-6)
    assert item["meses"] is None


async def test_quantidade_zero_vai_para_nao_normalizaveis():
    r = await normalizar_precos_unidade(
        [{"valor": 1000, "quantidade": 0, "meses": 12}], "usuario_mes"
    )
    assert "não positiva" in r["nao_normalizaveis"][0]["motivo"]
