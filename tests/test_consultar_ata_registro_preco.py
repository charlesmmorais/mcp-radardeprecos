"""Testes da tool consultar_ata_registro_preco, com o cliente PNCP mockado."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.consultar_ata_registro_preco import (
    consultar_ata_registro_preco,
)

ATA_BRUTA = {
    "numeroControlePNCPAta": "18457226000181-1-000015/2023-000001",
    "numeroAtaRegistroPreco": "NPERP 003/2023",
    "objetoContratacao": "Serviços de análise técnica",
    "orgaoEntidade": {"cnpj": "18457226000181", "razaoSocial": "Município Teste"},
    "unidadeOrgao": {"ufSigla": "MG", "municipioNome": "Santa Vitória"},
    "dataAssinatura": "2023-06-16",
    "vigenciaInicio": "2023-07-07",
    "vigenciaFim": "2099-10-07",
    "cancelado": False,
}

ITEM_ATA_BRUTO = {
    "descricao": "Notebook 16GB",
    "quantidade": 100,
    "quantidadeOriginal": 100,
    "saldoQuantidade": 40,
    "unidadeMedida": "UN",
    "valorUnitario": 3299.0,
    "valorTotal": 329900.0,
    "niFornecedor": "11222333000144",
    "nomeRazaoSocialFornecedor": "Fornecedor Vencedor Ltda",
    "marca": "MarcaX",
    "modelo": "ModeloY",
}


async def test_consultar_ata_registro_preco_exige_identificacao():
    with pytest.raises(ValueError):
        await consultar_ata_registro_preco()


@patch(
    "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client.consultar_itens_ata",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client.consultar_ata",
    new_callable=AsyncMock,
)
async def test_consultar_ata_registro_preco_via_numero_controle(mock_ata, mock_itens):
    mock_ata.return_value = ATA_BRUTA
    mock_itens.return_value = [ITEM_ATA_BRUTO]

    resultado = await consultar_ata_registro_preco(
        numero_controle_pncp_ata="18457226000181-1-000015/2023-000001"
    )

    mock_ata.assert_awaited_once_with("18457226000181", 2023, 15, 1)
    assert resultado["numero_ata"] == "NPERP 003/2023"
    assert resultado["vigente"] is True
    assert resultado["cancelada"] is False
    item = resultado["itens"][0]
    assert item["preco_unitario"] == 3299.0
    assert item["saldo_quantidade"] == 40
    assert item["fornecedor"] == {"cnpj": "11222333000144", "nome": "Fornecedor Vencedor Ltda"}
    assert resultado["avisos"] == []


@patch(
    "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client.consultar_itens_ata",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client.consultar_ata",
    new_callable=AsyncMock,
)
async def test_consultar_ata_registro_preco_via_parametros_discretos(mock_ata, mock_itens):
    mock_ata.return_value = ATA_BRUTA
    mock_itens.return_value = []

    resultado = await consultar_ata_registro_preco(
        cnpj="18457226000181", ano_compra=2023, sequencial_compra=15, sequencial_ata=1
    )

    mock_ata.assert_awaited_once_with("18457226000181", 2023, 15, 1)
    assert resultado["itens"] == []
    assert len(resultado["avisos"]) == 1
    assert "não retornou itens" in resultado["avisos"][0]


@patch(
    "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client.consultar_arquivos_ata",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client.consultar_itens_ata",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client.consultar_ata",
    new_callable=AsyncMock,
)
async def test_consultar_ata_registro_preco_incluir_arquivos(mock_ata, mock_itens, mock_arquivos):
    mock_ata.return_value = ATA_BRUTA
    mock_itens.return_value = []
    mock_arquivos.return_value = [
        {"titulo": "Ata.pdf", "url": "https://pncp.gov.br/x", "tipoDocumentoNome": "Ata"}
    ]

    resultado = await consultar_ata_registro_preco(
        cnpj="18457226000181",
        ano_compra=2023,
        sequencial_compra=15,
        sequencial_ata=1,
        incluir_arquivos=True,
    )

    mock_arquivos.assert_awaited_once_with("18457226000181", 2023, 15, 1)
    assert resultado["arquivos"][0]["titulo"] == "Ata.pdf"
    assert resultado["arquivos"][0]["url_download"] == "https://pncp.gov.br/x"


@patch(
    "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client.consultar_itens_ata",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client.consultar_ata",
    new_callable=AsyncMock,
)
async def test_consultar_ata_registro_preco_cancelada_nunca_e_vigente(mock_ata, mock_itens):
    mock_ata.return_value = {**ATA_BRUTA, "cancelado": True}
    mock_itens.return_value = []

    resultado = await consultar_ata_registro_preco(
        cnpj="18457226000181", ano_compra=2023, sequencial_compra=15, sequencial_ata=1
    )

    assert resultado["cancelada"] is True
    assert resultado["vigente"] is False


async def test_consultar_ata_registro_preco_rejeita_numero_controle_invalido():
    with pytest.raises(ValueError):
        await consultar_ata_registro_preco(numero_controle_pncp_ata="formato-invalido")
