"""Testes da tool listar_filtros_pncp, com o cliente PNCP mockado."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.listar_filtros_pncp import listar_filtros_pncp

FILTROS_FAKE = {
    "filters": {
        "modalidades": [{"id": "6", "nome": "Pregão - Eletrônico", "total": 100}],
        "ufs": [{"id": "SP", "total": 50}],
        "orgaos": [{"id": str(i), "nome": f"Órgão {i}", "total": 100 - i} for i in range(50)],
        "municipios": [{"id": str(i), "total": 1} for i in range(50)],
    }
}


async def test_listar_filtros_pncp_rejeita_tipo_invalido():
    with pytest.raises(ValueError):
        await listar_filtros_pncp("invalido")


@patch("mcp_radardeprecos.tools.listar_filtros_pncp.pncp_client.listar_filtros", new_callable=AsyncMock)
async def test_listar_filtros_pncp_retorna_facetas_pequenas_por_completo(mock_listar):
    mock_listar.return_value = FILTROS_FAKE
    resultado = await listar_filtros_pncp("edital")
    assert resultado["modalidades"] == FILTROS_FAKE["filters"]["modalidades"]
    assert resultado["ufs"] == FILTROS_FAKE["filters"]["ufs"]


@patch("mcp_radardeprecos.tools.listar_filtros_pncp.pncp_client.listar_filtros", new_callable=AsyncMock)
async def test_listar_filtros_pncp_trunca_facetas_grandes(mock_listar):
    mock_listar.return_value = FILTROS_FAKE
    resultado = await listar_filtros_pncp("edital", limite_por_campo=10)
    assert len(resultado["orgaos"]) == 10
    assert resultado["orgaos_total_disponivel"] == 50


@patch("mcp_radardeprecos.tools.listar_filtros_pncp.pncp_client.listar_filtros", new_callable=AsyncMock)
async def test_listar_filtros_pncp_campo_especifico_retorna_completo(mock_listar):
    mock_listar.return_value = FILTROS_FAKE
    resultado = await listar_filtros_pncp("edital", campo="orgaos")
    assert len(resultado["orgaos"]) == 50
    assert "ufs" not in resultado


@patch("mcp_radardeprecos.tools.listar_filtros_pncp.pncp_client.listar_filtros", new_callable=AsyncMock)
async def test_listar_filtros_pncp_campo_invalido_leva_a_erro(mock_listar):
    mock_listar.return_value = FILTROS_FAKE
    with pytest.raises(ValueError):
        await listar_filtros_pncp("edital", campo="campo_que_nao_existe")
