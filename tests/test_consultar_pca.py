"""Testes da tool consultar_pca, com o cliente PNCP mockado."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.consultar_pca import consultar_pca

PCA_BRUTO = {
    "data": [
        {
            "orgaoEntidadeRazaoSocial": "Município Teste",
            "orgaoEntidadeCnpj": "11222333000181",
            "codigoUnidade": "UND1",
            "nomeUnidade": "Secretaria de TI",
            "anoPca": 2026,
            "dataPublicacaoPNCP": "2026-01-15T10:00:00",
            "itens": [
                {
                    "descricaoItem": "Notebook 16GB",
                    "quantidadeEstimada": 50,
                    "valorUnitario": 3500.0,
                    "valorTotal": 175000.0,
                    "unidadeFornecimento": "UN",
                    "dataDesejada": "2026-06-01",
                    "codigoItem": "123456",
                    "classificacaoSuperiorNome": "Equipamentos de Informática",
                    "classificacaoSuperiorCodigo": "7510",
                    "categoriaItemPcaNome": "Material",
                }
            ],
        }
    ],
    "totalRegistros": 1,
    "totalPaginas": 1,
    "numeroPagina": 1,
}


async def test_consultar_pca_exige_um_modo():
    with pytest.raises(ValueError):
        await consultar_pca()


async def test_consultar_pca_rejeita_os_dois_modos_simultaneos():
    with pytest.raises(ValueError):
        await consultar_pca(
            ano_pca=2026, codigo_classificacao_superior="7510",
            data_inicio="20260101", data_fim="20260701",
        )


async def test_consultar_pca_modo_classificacao_exige_os_dois_parametros():
    with pytest.raises(ValueError):
        await consultar_pca(ano_pca=2026)
    with pytest.raises(ValueError):
        await consultar_pca(codigo_classificacao_superior="7510")


async def test_consultar_pca_modo_periodo_exige_os_dois_parametros():
    with pytest.raises(ValueError):
        await consultar_pca(data_inicio="20260101")
    with pytest.raises(ValueError):
        await consultar_pca(data_fim="20260701")


async def test_consultar_pca_rejeita_cnpj_no_modo_classificacao():
    with pytest.raises(ValueError):
        await consultar_pca(
            ano_pca=2026, codigo_classificacao_superior="7510", cnpj_orgao="11222333000181"
        )


@patch(
    "mcp_radardeprecos.tools.consultar_pca.pncp_client.consultar_pca_por_classificacao",
    new_callable=AsyncMock,
)
async def test_consultar_pca_modo_classificacao_flatten_e_aviso(mock_pca):
    mock_pca.return_value = PCA_BRUTO

    resultado = await consultar_pca(ano_pca=2026, codigo_classificacao_superior="7510")

    mock_pca.assert_awaited_once_with(2026, "7510", pagina=1, tamanho_pagina=500)
    assert resultado["total_registros"] == 1
    item = resultado["itens_planejados"][0]
    assert item["descricao"] == "Notebook 16GB"
    assert item["quantidade_estimada"] == 50
    assert item["valor_unitario_estimado"] == 3500.0
    assert item["orgao"] == "Município Teste"
    assert item["cnpj_orgao"] == "11222333000181"
    assert item["classificacao_catalogo"] == "Equipamentos de Informática"
    assert any("estimativas orçamentárias" in a for a in resultado["avisos"])


@patch(
    "mcp_radardeprecos.tools.consultar_pca.pncp_client.consultar_pca_por_periodo",
    new_callable=AsyncMock,
)
async def test_consultar_pca_modo_periodo_repassa_cnpj_e_unidade(mock_pca):
    mock_pca.return_value = {"data": [], "totalRegistros": 0, "totalPaginas": 0, "numeroPagina": 1}

    resultado = await consultar_pca(
        data_inicio="20260101", data_fim="20260701",
        cnpj_orgao="11222333000181", codigo_unidade="UND1",
    )

    mock_pca.assert_awaited_once_with(
        "20260101", "20260701", cnpj="11222333000181", codigo_unidade="UND1",
        pagina=1, tamanho_pagina=500,
    )
    assert resultado["itens_planejados"] == []
    assert any("Nenhum item de PCA encontrado" in a for a in resultado["avisos"])


@patch(
    "mcp_radardeprecos.tools.consultar_pca.pncp_client.consultar_pca_por_classificacao",
    new_callable=AsyncMock,
)
async def test_consultar_pca_sempre_avisa_sobre_natureza_estimativa(mock_pca):
    mock_pca.return_value = PCA_BRUTO
    resultado = await consultar_pca(ano_pca=2026, codigo_classificacao_superior="7510")
    assert any("NÃO preços efetivamente pagos" in a or "não usar como entrada" in a for a in resultado["avisos"])
