"""Testes da tool consultar_contratacao_pncp, com o cliente PNCP mockado."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.consultar_contratacao_pncp import consultar_contratacao_pncp

DETALHE_BRUTO = {
    "numeroControlePNCP": "16854531000181-1-000066/2023",
    "numeroCompra": "PRE 63",
    "processo": "146/2023",
    "orgaoEntidade": {"cnpj": "16854531000181", "razaoSocial": "Município Teste"},
    "unidadeOrgao": {"ufSigla": "MG", "municipioNome": "Oliveira"},
    "modalidadeNome": "Pregão - Eletrônico",
    "modoDisputaNome": "Aberto",
    "srp": True,
    "objetoCompra": "Seguro veicular",
    "valorTotalEstimado": 66124.14,
    "valorTotalHomologado": 43196.85,
    "situacaoCompraNome": "Divulgada no PNCP",
    "amparoLegal": {"codigo": 1, "nome": "Lei 14.133/2021, Art. 28, I", "descricao": "pregão"},
    "dataPublicacaoPncp": "2023-09-14T14:27:49",
    "dataAberturaProposta": "2023-09-14T18:00:00",
    "dataEncerramentoProposta": "2023-10-03T16:00:00",
    "linkSistemaOrigem": (
        "https://comprasnet.exemplo.gov.br/comprasnet-web/public/"
        "landing?destino=acompanhamento-compra&compra=80308005913282025"
    ),
    "linkProcessoEletronico": None,
}


async def test_consultar_contratacao_pncp_exige_identificacao():
    with pytest.raises(ValueError):
        await consultar_contratacao_pncp()


@patch(
    "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_contratacao_detalhe",
    new_callable=AsyncMock,
)
async def test_consultar_contratacao_pncp_via_numero_controle(mock_detalhe):
    mock_detalhe.return_value = DETALHE_BRUTO

    resultado = await consultar_contratacao_pncp(
        numero_controle_pncp="16854531000181-1-000066/2023"
    )

    mock_detalhe.assert_awaited_once_with("16854531000181", 2023, 66)
    assert resultado["srp"] is True
    assert resultado["valor_total_homologado"] == 43196.85
    assert resultado["amparo_legal"]["nome"] == "Lei 14.133/2021, Art. 28, I"
    assert resultado["link_sistema_origem"] == (
        "https://comprasnet.exemplo.gov.br/comprasnet-web/public/"
        "landing?destino=acompanhamento-compra&compra=80308005913282025"
    )
    assert resultado["link_processo_eletronico"] is None
    assert resultado["link_pagina_pncp"] == (
        "https://pncp.gov.br/app/editais/16854531000181/2023/66"
    )
    assert "itens" not in resultado


@patch(
    "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_contratacao_detalhe",
    new_callable=AsyncMock,
)
async def test_consultar_contratacao_pncp_link_processo_eletronico_quando_presente(mock_detalhe):
    detalhe_com_sei = dict(DETALHE_BRUTO)
    detalhe_com_sei["linkProcessoEletronico"] = "https://sei.exemplo.gov.br/processo/123"
    mock_detalhe.return_value = detalhe_com_sei

    resultado = await consultar_contratacao_pncp(
        numero_controle_pncp="16854531000181-1-000066/2023"
    )

    assert resultado["link_processo_eletronico"] == "https://sei.exemplo.gov.br/processo/123"


@patch(
    "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_contratacao_detalhe",
    new_callable=AsyncMock,
)
async def test_consultar_contratacao_pncp_link_sistema_origem_ausente_vira_none(mock_detalhe):
    detalhe_sem_link = {k: v for k, v in DETALHE_BRUTO.items() if k != "linkSistemaOrigem"}
    mock_detalhe.return_value = detalhe_sem_link

    resultado = await consultar_contratacao_pncp(
        numero_controle_pncp="16854531000181-1-000066/2023"
    )

    assert resultado["link_sistema_origem"] is None


@patch(
    "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_contratacao_detalhe",
    new_callable=AsyncMock,
)
async def test_consultar_contratacao_pncp_incluir_itens(mock_detalhe, mock_itens):
    mock_detalhe.return_value = DETALHE_BRUTO
    mock_itens.return_value = [
        {
            "descricao": "Seguro veículo A",
            "quantidade": 3,
            "unidadeMedida": "SERVIÇO",
            "valorUnitarioEstimado": 5041.08,
            "valorTotal": 15123.24,
            "situacaoCompraItemNome": "Homologado",
        }
    ]

    resultado = await consultar_contratacao_pncp(
        cnpj="16854531000181", ano=2023, sequencial=66, incluir_itens=True
    )

    assert len(resultado["itens"]) == 1
    assert resultado["itens"][0]["descricao"] == "Seguro veículo A"
    mock_itens.assert_awaited_once_with("16854531000181", 2023, 66)


@patch(
    "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_contratacao_detalhe",
    new_callable=AsyncMock,
)
async def test_formato_invalido_retorna_erro_estruturado(mock_detalhe):
    r = await consultar_contratacao_pncp(numero_controle_pncp="formato-invalido")
    assert r["erro"] == "instrumento_incompativel"
    assert r["instrumento_detectado"] == "desconhecido"
    mock_detalhe.assert_not_awaited()


@patch(
    "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_contratacao_detalhe",
    new_callable=AsyncMock,
)
async def test_rejeita_numero_de_contrato_sem_substituicao_silenciosa(mock_detalhe):
    # Achado real 2026-07-28: passar um número de CONTRATO (-2-) devolvia,
    # sem avisar, a contratação (-1-) de mesmo sequencial (objeto diferente).
    # v0.3.16 (achado 2026-07-29): agora devolve ERRO ESTRUTURADO (não
    # exceção — que virava "Session terminated" no transporte HTTP) e NÃO
    # chama o endpoint.
    r = await consultar_contratacao_pncp(
        numero_controle_pncp="16854531000181-2-000066/2023"
    )
    assert r["erro"] == "instrumento_incompativel"
    assert r["instrumento_detectado"] == "contrato"
    assert "consultar_contratos_orgao_pncp" in r["recomendacao"]
    mock_detalhe.assert_not_awaited()


@patch(
    "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_contratacao_detalhe",
    new_callable=AsyncMock,
)
async def test_rejeita_numero_de_ata(mock_detalhe):
    r = await consultar_contratacao_pncp(
        numero_controle_pncp="18457226000181-1-000015/2023-000001"
    )
    assert r["erro"] == "instrumento_incompativel"
    assert r["instrumento_detectado"] == "ata"
    assert "consultar_ata_registro_preco" in r["recomendacao"]
    mock_detalhe.assert_not_awaited()


@patch(
    "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_contratacao_detalhe",
    new_callable=AsyncMock,
)
async def test_consultar_contratacao_pncp_link_pagina_pncp_nao_tem_segmento_compras_extra(
    mock_detalhe,
):
    # Regressão: um cliente MCP (ChatGPT) construiu esse link sozinho e errou,
    # inserindo um segmento "/compras/" a mais (.../app/editais/compras/...),
    # formato que não existe no site e dá erro. O link tem que vir pronto e
    # certo daqui, sem esse segmento.
    mock_detalhe.return_value = DETALHE_BRUTO

    resultado = await consultar_contratacao_pncp(
        cnpj="16854531000181", ano=2023, sequencial=66
    )

    assert "/app/editais/compras/" not in resultado["link_pagina_pncp"]
    assert resultado["link_pagina_pncp"] == (
        "https://pncp.gov.br/app/editais/16854531000181/2023/66"
    )
