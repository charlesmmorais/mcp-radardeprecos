"""Testes da tool buscar_homologados_14133, com o cliente mockado."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.buscar_homologados_14133 import buscar_homologados_14133

_MOD = "mcp_radardeprecos.tools.buscar_homologados_14133.compras_client"


async def test_valida_datas_e_exige_algum_filtro():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        await buscar_homologados_14133("2026/01/01", "2026-06-30", codigo_item_catalogo=1)
    with pytest.raises(ValueError, match="informe codigo_item_catalogo"):
        await buscar_homologados_14133("2026-01-01", "2026-06-30")


@patch(f"{_MOD}.consultar_itens_14133", new_callable=AsyncMock)
async def test_modo_por_catalogo_forca_tem_resultado(mock_cli):
    mock_cli.return_value = {"resultado": [{"campoOriginal": 1}], "totalRegistros": 1}
    r = await buscar_homologados_14133(
        "2026-01-01", "2026-06-30", codigo_item_catalogo=27332, cnpj_orgao="00394460000141"
    )
    kwargs = mock_cli.await_args.kwargs
    assert kwargs["tem_resultado"] is True
    assert kwargs["codigo_item_catalogo"] == 27332
    assert kwargs["orgao_entidade_cnpj"] == "00394460000141"
    assert r["modo"] == "por_catalogo"
    # Registros crus preservados (campos originais da API):
    assert r["registros"] == [{"campoOriginal": 1}]
    assert any("especificação OpenAPI" in a for a in r["avisos"])


@patch(f"{_MOD}.consultar_itens_14133", new_callable=AsyncMock)
async def test_modo_por_catalogo_avisa_fornecedor_ignorado(mock_cli):
    mock_cli.return_value = {"resultado": [], "totalRegistros": 0}
    r = await buscar_homologados_14133(
        "2026-01-01", "2026-06-30", codigo_item_catalogo=1, cnpj_fornecedor="123"
    )
    assert any("ignorado no modo por catálogo" in a for a in r["avisos"])


@patch(f"{_MOD}.consultar_resultados_itens_14133", new_callable=AsyncMock)
async def test_modo_por_fornecedor_usa_endpoint_de_resultados(mock_cli):
    mock_cli.return_value = {"resultado": [{"x": 1}], "totalRegistros": 10}
    r = await buscar_homologados_14133(
        "2026-01-01", "2026-06-30", cnpj_fornecedor="31621985000104"
    )
    kwargs = mock_cli.await_args.kwargs
    assert kwargs["ni_fornecedor"] == "31621985000104"
    assert kwargs["data_resultado_inicial"] == "2026-01-01"
    assert r["modo"] == "por_fornecedor_orgao"
    assert r["total_registros"] == 10
