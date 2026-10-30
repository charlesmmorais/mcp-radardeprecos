"""Testes da tool pesquisar_cesta_precos, com o cliente Compras.gov.br mockado."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.pesquisar_cesta_precos import pesquisar_cesta_precos

REGISTROS_NOTEBOOK = {
    "resultado": [
        {"precoUnitario": 3000.0, "descricaoDetalhadaItem": "Notebook 16GB"},
        {"precoUnitario": 3200.0, "descricaoDetalhadaItem": "Notebook 16GB"},
        {"precoUnitario": 3100.0, "descricaoDetalhadaItem": "Notebook 16GB"},
    ],
    "totalRegistros": 3,
}

REGISTROS_MANUTENCAO = {
    "resultado": [
        {"precoUnitario": 100.0, "descricaoItem": "Manutenção de ar condicionado"},
        {"precoUnitario": 120.0, "descricaoItem": "Manutenção de ar condicionado"},
        {"precoUnitario": 110.0, "descricaoItem": "Manutenção de ar condicionado"},
    ],
    "totalRegistros": 3,
}


async def test_pesquisar_cesta_precos_rejeita_lista_vazia():
    with pytest.raises(ValueError):
        await pesquisar_cesta_precos([])


async def test_pesquisar_cesta_precos_rejeita_mais_de_30_itens():
    itens = [{"codigo_item_catalogo": 1, "tipo_item": "material"}] * 31
    with pytest.raises(ValueError):
        await pesquisar_cesta_precos(itens)


async def test_pesquisar_cesta_precos_rejeita_item_sem_codigo():
    with pytest.raises(ValueError):
        await pesquisar_cesta_precos([{"tipo_item": "material"}])


async def test_pesquisar_cesta_precos_rejeita_tipo_item_invalido():
    with pytest.raises(ValueError):
        await pesquisar_cesta_precos(
            [{"codigo_item_catalogo": 1, "tipo_item": "invalido"}]
        )


async def test_pesquisar_cesta_precos_rejeita_metodo_invalido():
    with pytest.raises(ValueError):
        await pesquisar_cesta_precos(
            [{"codigo_item_catalogo": 1, "tipo_item": "material", "metodo": "invalido"}]
        )


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_servico",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_pesquisar_cesta_precos_calcula_total_de_dois_itens(mock_material, mock_servico):
    mock_material.return_value = REGISTROS_NOTEBOOK
    mock_servico.return_value = REGISTROS_MANUTENCAO

    resultado = await pesquisar_cesta_precos(
        [
            {
                "codigo_item_catalogo": 150912,
                "tipo_item": "material",
                "quantidade": 10,
                "descricao": "Notebook",
            },
            {
                "codigo_item_catalogo": 9999,
                "tipo_item": "servico",
                "quantidade": 5,
            },
        ]
    )

    assert resultado["quantidade_itens"] == 2
    assert resultado["avisos_gerais"] == []

    item_material = resultado["itens"][0]
    assert item_material["descricao"] == "Notebook"
    assert item_material["preco_referencia"] == 3100.0  # média dos 3 valores, sem exclusão
    assert item_material["valor_total_item"] == 31000.0
    assert item_material["quantidade_amostra"] == 3

    item_servico = resultado["itens"][1]
    assert item_servico["descricao"] == "Manutenção de ar condicionado"
    assert item_servico["preco_referencia"] == 110.0
    assert item_servico["valor_total_item"] == 550.0

    # total da cesta = soma dos dois itens
    assert resultado["valor_total_cesta"] == 31000.0 + 550.0


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_pesquisar_cesta_precos_item_sem_preco_gera_aviso_e_nao_entra_no_total(
    mock_material,
):
    mock_material.return_value = {"resultado": [], "totalRegistros": 0}

    resultado = await pesquisar_cesta_precos(
        [
            {
                "codigo_item_catalogo": 1,
                "tipo_item": "material",
                "descricao": "Item raro",
                "quantidade": 5,
            }
        ]
    )

    item = resultado["itens"][0]
    assert item["preco_referencia"] is None
    assert item["valor_total_item"] is None
    assert resultado["valor_total_cesta"] == 0
    assert len(resultado["avisos_gerais"]) == 1
    assert "Item raro" in resultado["avisos_gerais"][0]


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_pesquisar_cesta_precos_usa_metodo_mediana_quando_informado(mock_material):
    mock_material.return_value = REGISTROS_NOTEBOOK

    resultado = await pesquisar_cesta_precos(
        [{"codigo_item_catalogo": 150912, "tipo_item": "material", "quantidade": 1}],
        metodo="mediana",
    )

    assert resultado["itens"][0]["metodo_utilizado"] == "mediana"
    assert resultado["itens"][0]["preco_referencia"] == 3100.0


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_pesquisar_cesta_precos_repassa_uf_padrao_ao_item(mock_material):
    mock_material.return_value = REGISTROS_NOTEBOOK

    await pesquisar_cesta_precos(
        [{"codigo_item_catalogo": 150912, "tipo_item": "material"}],
        uf="SP",
    )

    _, kwargs = mock_material.call_args
    assert kwargs["estado"] == "SP"


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_pesquisar_cesta_precos_item_pode_sobrescrever_uf_padrao(mock_material):
    mock_material.return_value = REGISTROS_NOTEBOOK

    await pesquisar_cesta_precos(
        [{"codigo_item_catalogo": 150912, "tipo_item": "material", "uf": "DF"}],
        uf="SP",
    )

    _, kwargs = mock_material.call_args
    assert kwargs["estado"] == "DF"


# --- correção monetária integrada à cesta ---

REGISTROS_NOTEBOOK_COM_DATA = {
    "resultado": [
        {"precoUnitario": 3000.0, "descricaoDetalhadaItem": "Notebook 16GB", "dataResultado": "2025-12-15"},
        {"precoUnitario": 3200.0, "descricaoDetalhadaItem": "Notebook 16GB", "dataResultado": "2026-02-01"},
        {"precoUnitario": 3100.0, "descricaoDetalhadaItem": "Notebook 16GB", "dataResultado": "2026-03-20"},
    ],
    "totalRegistros": 3,
}

_SERIE_SGS = [
    {"competencia": "2026-01", "variacao_percentual": 1.0},
    {"competencia": "2026-02", "variacao_percentual": 2.0},
    {"competencia": "2026-03", "variacao_percentual": 0.5},
]

_PATCH_SGS = "mcp_radardeprecos.tools.atualizar_precos_indice.bcb_client.obter_indice_mensal"


async def test_pesquisar_cesta_precos_rejeita_indice_invalido_quando_corrigir_indice():
    with pytest.raises(ValueError, match="indice"):
        await pesquisar_cesta_precos(
            [{"codigo_item_catalogo": 1, "tipo_item": "material"}],
            corrigir_indice=True,
            indice="bogus",
        )


@patch(_PATCH_SGS, new_callable=AsyncMock)
@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_corrigir_indice_aplica_correcao_antes_do_calculo(mock_material, mock_sgs):
    mock_material.return_value = REGISTROS_NOTEBOOK_COM_DATA
    mock_sgs.return_value = _SERIE_SGS

    resultado = await pesquisar_cesta_precos(
        [{"codigo_item_catalogo": 150912, "tipo_item": "material", "quantidade": 1}],
        corrigir_indice=True,
        data_base="2026-03",
    )

    item = resultado["itens"][0]
    # Preço de referência não deve mais ser a média simples dos brutos (3100.0)
    # — os 3 valores foram corrigidos a valor presente antes do cálculo.
    assert item["preco_referencia"] != 3100.0
    assert item["correcao_monetaria"]["indice_chave"] == "ipca"
    assert item["correcao_monetaria"]["data_base"] == "2026-03"
    assert item["correcao_monetaria"]["quantidade_precos_corrigidos"] == 3


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_corrigir_indice_sem_data_resultado_cai_para_sem_correcao_com_aviso(mock_material):
    # REGISTROS_NOTEBOOK (sem dataResultado) já definido no topo do arquivo.
    mock_material.return_value = REGISTROS_NOTEBOOK

    resultado = await pesquisar_cesta_precos(
        [{"codigo_item_catalogo": 150912, "tipo_item": "material", "quantidade": 1}],
        corrigir_indice=True,
    )

    item = resultado["itens"][0]
    assert "correcao_monetaria" not in item
    assert item["preco_referencia"] == 3100.0  # calculado sem correção
    assert any("data_resultado" in a for a in item["avisos"])


@patch(_PATCH_SGS, new_callable=AsyncMock)
@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_corrigir_indice_falha_isolada_nao_derruba_a_cesta(mock_material, mock_sgs):
    mock_material.return_value = REGISTROS_NOTEBOOK_COM_DATA
    mock_sgs.side_effect = RuntimeError("SGS indisponível (simulado)")

    resultado = await pesquisar_cesta_precos(
        [{"codigo_item_catalogo": 150912, "tipo_item": "material", "quantidade": 1}],
        corrigir_indice=True,
    )

    item = resultado["itens"][0]
    assert "correcao_monetaria" not in item
    assert item["preco_referencia"] == 3100.0  # cálculo prossegue sem correção
    assert any("Falha ao aplicar correção monetária" in a for a in item["avisos"])
