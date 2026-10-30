"""Testes da tool descobrir_codigo_catalogo, com o cliente Compras.gov.br mockado."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.descobrir_codigo_catalogo import descobrir_codigo_catalogo

PDMS = [
    {
        "codigoPdm": 8435,
        "nomePdm": "NOTEBOOK",
        "codigoClasse": 7010,
        "nomeClasse": "COMPUTADORES",
        "codigoGrupo": 70,
        "nomeGrupo": "INFORMÁTICA",
    },
    {
        "codigoPdm": 19246,
        "nomePdm": "TABLET",
        "codigoClasse": 7010,
        "nomeClasse": "COMPUTADORES",
        "codigoGrupo": 70,
        "nomeGrupo": "INFORMÁTICA",
    },
]

ITENS_NOTEBOOK = {
    "resultado": [
        {"codigoItem": 8435001, "descricaoItem": "NOTEBOOK, NOME: NOTEBOOK PADRAO "},
    ],
    "totalRegistros": 1,
}

CLASSES_SERVICO = [
    {
        "codigoClasse": 1111,
        "nomeClasse": "SERVIÇOS DE DESENVOLVIMENTO DE SOFTWARE",
        "codigoGrupo": 111,
        "nomeGrupo": "SERVIÇOS DE DESENVOLVIMENTO E MANUTENÇÃO DE SOFTWARE",
    },
]

ITENS_SOFTWARE = {
    "resultado": [
        {"codigoServico": 25917, "nomeServico": "DESENVOLVIMENTO DE NOVO SOFTWARE"},
    ],
    "totalRegistros": 1,
}


@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_itens_material_por_pdm",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_pdms_material_ativos",
    new_callable=AsyncMock,
)
async def test_descobrir_material_encontra_pdm_e_amostra_de_itens(mock_pdms, mock_itens):
    mock_pdms.return_value = PDMS
    mock_itens.return_value = ITENS_NOTEBOOK

    resultado = await descobrir_codigo_catalogo("notebook", tipo_item="material")

    assert resultado["tipo_item"] == "material"
    assert resultado["total_correspondencias"] == 1
    assert "aviso" not in resultado
    primeiro = resultado["resultados"][0]
    assert primeiro["codigo_pdm"] == 8435
    assert primeiro["nome_pdm"] == "NOTEBOOK"
    assert primeiro["itens_exemplo"][0]["codigo_item"] == 8435001
    mock_itens.assert_awaited_once()


@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_itens_material_por_pdm",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_pdms_material_ativos",
    new_callable=AsyncMock,
)
async def test_descobrir_material_busca_acento_e_case_insensivel(mock_pdms, mock_itens):
    mock_pdms.return_value = PDMS
    mock_itens.return_value = ITENS_NOTEBOOK

    resultado = await descobrir_codigo_catalogo("NoteBook", tipo_item="material")

    assert resultado["total_correspondencias"] == 1
    assert resultado["resultados"][0]["nome_pdm"] == "NOTEBOOK"


@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_pdms_material_ativos",
    new_callable=AsyncMock,
)
async def test_descobrir_material_sem_correspondencia_gera_aviso(mock_pdms):
    mock_pdms.return_value = PDMS

    resultado = await descobrir_codigo_catalogo("xyzabc-termo-inexistente", tipo_item="material")

    assert resultado["total_correspondencias"] == 0
    assert resultado["resultados"] == []
    assert "aviso" in resultado


@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_itens_servico_por_classe",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_classes_servico",
    new_callable=AsyncMock,
)
async def test_descobrir_servico_encontra_classe_e_amostra_de_itens(mock_classes, mock_itens):
    mock_classes.return_value = CLASSES_SERVICO
    mock_itens.return_value = ITENS_SOFTWARE

    resultado = await descobrir_codigo_catalogo("software", tipo_item="servico")

    assert resultado["tipo_item"] == "servico"
    assert resultado["total_correspondencias"] == 1
    assert "aviso" not in resultado
    primeiro = resultado["resultados"][0]
    assert primeiro["codigo_classe"] == 1111
    assert primeiro["itens_exemplo"][0]["codigo_servico"] == 25917


@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_classes_servico",
    new_callable=AsyncMock,
)
async def test_descobrir_servico_sem_correspondencia_gera_aviso_especifico(mock_classes):
    mock_classes.return_value = CLASSES_SERVICO

    resultado = await descobrir_codigo_catalogo("dedetização de porão", tipo_item="servico")

    assert resultado["total_correspondencias"] == 0
    assert "aviso" in resultado
    assert "CATSER" in resultado["aviso"]


async def test_descobrir_codigo_catalogo_rejeita_tipo_invalido():
    with pytest.raises(ValueError):
        await descobrir_codigo_catalogo("notebook", tipo_item="invalido")


async def test_descobrir_codigo_catalogo_rejeita_termo_vazio():
    with pytest.raises(ValueError):
        await descobrir_codigo_catalogo("   ", tipo_item="material")


# --- ranking por qualidade ----------------------------------------


@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_itens_servico_por_classe",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_classes_servico",
    new_callable=AsyncMock,
)
async def test_tic_descarta_falsos_positivos_de_substring(mock_classes, mock_itens):
    mock_itens.return_value = {"resultado": []}
    mock_classes.return_value = [
        {"codigoClasse": 1, "nomeClasse": "GUIA TURISTICO", "codigoGrupo": 10, "nomeGrupo": "TURISMO"},
        {"codigoClasse": 2, "nomeClasse": "DADOS ESTATISTICOS", "codigoGrupo": 20, "nomeGrupo": "DADOS"},
        {"codigoClasse": 3, "nomeClasse": "PRODUTOS PLASTICOS", "codigoGrupo": 30, "nomeGrupo": "QUIMICOS"},
        {"codigoClasse": 4, "nomeClasse": "TECNOLOGIA DA INFORMACAO E COMUNICACAO (TIC)", "codigoGrupo": 40, "nomeGrupo": "TI"},
    ]
    r = await descobrir_codigo_catalogo("TIC", tipo_item="servico")
    # Só a correspondência de palavra inteira sobrevive; parciais descartadas com aviso.
    assert [x["codigo_classe"] for x in r["resultados"]] == [4]
    assert r["resultados"][0]["qualidade_correspondencia"] == "palavra_inteira"
    assert r["total_correspondencias"] == 1
    assert any("descartadas" in a for a in r["avisos"])


@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_itens_servico_por_classe",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.descobrir_codigo_catalogo.compras_client.listar_classes_servico",
    new_callable=AsyncMock,
)
async def test_parciais_sao_mantidas_quando_sao_a_unica_opcao(mock_classes, mock_itens):
    mock_itens.return_value = {"resultado": []}
    mock_classes.return_value = [
        {"codigoClasse": 3, "nomeClasse": "PRODUTOS PLASTICOS", "codigoGrupo": 30, "nomeGrupo": "QUIMICOS"},
    ]
    r = await descobrir_codigo_catalogo("TIC", tipo_item="servico")
    assert [x["codigo_classe"] for x in r["resultados"]] == [3]
    assert r["resultados"][0]["qualidade_correspondencia"] == "parcial"
    assert not any("descartadas" in a for a in r["avisos"])
