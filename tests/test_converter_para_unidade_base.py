"""Testes da conversão para unidade base, com a tabela do catálogo mockada."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.converter_para_unidade_base import (
    converter_para_unidade_base,
)

TABELA_PDM = [
    {
        "siglaUnidadeFornecimento": "UN",
        "nomeUnidadeFornecimento": "UNIDADE",
        "capacidadeUnidadeFornecimento": None,
        "siglaUnidadeMedida": "UN",
    },
    {
        "siglaUnidadeFornecimento": "PCT",
        "nomeUnidadeFornecimento": "PACOTE",
        "capacidadeUnidadeFornecimento": "50 UN",
        "siglaUnidadeMedida": "UN",
    },
    {
        "siglaUnidadeFornecimento": "CX",
        "nomeUnidadeFornecimento": "CAIXA",
        "capacidadeUnidadeFornecimento": "CAIXA 10 X 20",  # ambíguo de propósito
        "siglaUnidadeMedida": "UN",
    },
]


def _preco(valor: float, nome: str | None, capacidade: str | None = None) -> dict:
    return {
        "preco_unitario": valor,
        "unidade_fornecimento": {"sigla": None, "nome": nome, "capacidade": capacidade},
    }


def _mock_tabela():
    return patch(
        "mcp_radardeprecos.tools.converter_para_unidade_base."
        "compras_client.listar_unidades_fornecimento_material",
        new=AsyncMock(return_value=TABELA_PDM),
    )


async def test_converte_pacote_para_unidade():
    """R$ 21,01 o pacote com 50 = R$ 0,4202 a unidade — comparável com o avulso."""
    with _mock_tabela():
        r = await converter_para_unidade_base(
            [_preco(21.01, "PACOTE", "50 UN")], "material", codigo_pdm=4321
        )

    item = r["convertidos"][0]
    assert item["fator_conversao"] == 50.0
    assert item["preco_base"] == pytest.approx(0.4202)
    assert item["capacidade_usada"] == "50 UN"
    assert r["precos_base"] == [pytest.approx(0.4202)]


async def test_unidade_simples_tem_fator_um():
    with _mock_tabela():
        r = await converter_para_unidade_base(
            [_preco(0.60, "UNIDADE")], "material", codigo_pdm=4321
        )

    assert r["convertidos"][0]["fator_conversao"] == 1.0
    assert r["convertidos"][0]["preco_base"] == pytest.approx(0.60)


async def test_capacidade_ambigua_nao_e_convertida():
    """Preferir não converter a adivinhar: 10 X 20 pode ser 200 ou dimensões."""
    with _mock_tabela():
        r = await converter_para_unidade_base(
            [_preco(153.90, "CAIXA", "CAIXA 10 X 20")], "material", codigo_pdm=4321
        )

    assert r["convertidos"] == []
    assert "não pôde ser interpretada" in r["nao_convertidos"][0]["motivo"]


async def test_unidade_fora_da_tabela_oficial():
    with _mock_tabela():
        r = await converter_para_unidade_base(
            [_preco(10.0, "BARRIL")], "material", codigo_pdm=4321
        )

    assert "não consta na tabela oficial" in r["nao_convertidos"][0]["motivo"]


async def test_serie_mista_fica_na_mesma_base():
    """O caso do guardanapo: avulso e pacote convergem para a base unitária."""
    with _mock_tabela():
        r = await converter_para_unidade_base(
            [_preco(0.60, "UNIDADE"), _preco(21.01, "PACOTE", "50 UN")],
            "material",
            codigo_pdm=4321,
        )

    assert len(r["convertidos"]) == 2
    assert r["precos_base"] == [pytest.approx(0.60), pytest.approx(0.4202)]
    assert any("mesma base" in a for a in r["avisos"])


async def test_preco_invalido_vai_para_nao_convertidos():
    with _mock_tabela():
        r = await converter_para_unidade_base(
            [_preco(0, "UNIDADE")], "material", codigo_pdm=4321
        )

    assert "não positivo" in r["nao_convertidos"][0]["motivo"]


async def test_exige_codigo_pdm_para_material():
    with pytest.raises(ValueError, match="codigo_pdm é obrigatório"):
        await converter_para_unidade_base([], "material")


async def test_rejeita_tipo_item_invalido():
    with pytest.raises(ValueError, match="material.*servico"):
        await converter_para_unidade_base([], "outro")


async def test_servico_usa_a_tabela_de_catser():
    with patch(
        "mcp_radardeprecos.tools.converter_para_unidade_base."
        "compras_client.listar_unidades_medida_servico",
        new=AsyncMock(return_value=[]),
    ) as mock:
        r = await converter_para_unidade_base(
            [_preco(100.0, "HORA")], "servico", codigo_servico=999
        )

    mock.assert_awaited_once()
    assert r["nao_convertidos"]
