"""Testes da tool listar_itens_catalogo, com o cliente mockado."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.listar_itens_catalogo import listar_itens_catalogo

_MOD = "mcp_radardeprecos.tools.listar_itens_catalogo.compras_client"


@patch(f"{_MOD}.listar_itens_servico_por_classe", new_callable=AsyncMock)
async def test_servico_mapeia_campos_e_passa_paginacao(mock_cli):
    mock_cli.return_value = {
        "resultado": [
            {"codigoServico": 27332, "nomeServico": "CONSULTORIA EM TIC"},
            {"codigoServico": 111, "nomeServico": "GUIA TURISTICO"},
        ],
        "totalRegistros": 42,
    }
    r = await listar_itens_catalogo("servico", 830, pagina=2, tamanho_pagina=50)
    mock_cli.assert_awaited_once_with(830, pagina=2, tamanho_pagina=50)
    assert r["total_registros"] == 42
    assert r["itens"][0] == {"codigo_servico": 27332, "nome_servico": "CONSULTORIA EM TIC"}


@patch(f"{_MOD}.listar_itens_servico_por_classe", new_callable=AsyncMock)
async def test_filtro_local_usa_fronteira_de_palavra(mock_cli):
    mock_cli.return_value = {
        "resultado": [
            {"codigoServico": 1, "nomeServico": "CONSULTORIA EM TIC"},
            {"codigoServico": 2, "nomeServico": "PRODUTOS PLASTICOS"},
        ],
        "totalRegistros": 2,
    }
    r = await listar_itens_catalogo("servico", 830, termo_filtro="tic")
    # "TIC" dentro de "PLASTICOS" NÃO casa (fronteira de palavra) — só a consultoria.
    assert [i["codigo_servico"] for i in r["itens"]] == [1]


@patch(f"{_MOD}.listar_itens_material_por_pdm", new_callable=AsyncMock)
async def test_material_e_aviso_quando_filtro_zera_a_pagina(mock_cli):
    mock_cli.return_value = {
        "resultado": [{"codigoItem": 9, "descricaoItem": "CANETA AZUL"}],
        "totalRegistros": 500,
    }
    r = await listar_itens_catalogo("material", 123, termo_filtro="notebook")
    assert r["itens"] == []
    assert any("avance 'pagina'" in a for a in r["avisos"])


async def test_valida_tipo_item():
    with pytest.raises(ValueError, match="tipo_item"):
        await listar_itens_catalogo("obra", 1)
