"""Testes de `consultar_itens_contrato_compras` — itens de contrato (Compras.gov.br)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.consultar_itens_contrato_compras import (
    consultar_itens_contrato_compras,
)

_CLIENTE = "mcp_radardeprecos.clients.compras_client"


def _item_bruto(numero_item="00001", codigo_item=365121, **overrides):
    # Formato real confirmado ao vivo em 2026-07-10 (codigoOrgao=25201,
    # Banco Central do Brasil).
    base = {
        "codigoOrgao": "25201",
        "codigoUnidadeGestora": "925133",
        "codigoUnidadeGestoraOrigemContrato": "925133",
        "codigoUnidadeRealizadoraCompra": "925133",
        "codigoModalidadeCompra": "05",
        "numeroContrato": "05966/2025",
        "niFornecedor": "50079413000181",
        "nomeRazaoSocialFornecedor": "BRETAS MULTIMARCAS LTDA",
        "processo": "18600.048975/2025-81",
        "dataVigenciaInicial": "2025-08-07T00:00:00",
        "dataVigenciaFinal": "2025-09-06T00:00:00",
        "valorGlobal": 2700,
        "tipoItem": "Material",
        "codigoItem": codigo_item,
        "descricaoIitem": "ATUADOR ELETROMAGNÉTICO",
        "quantidadeItem": 1,
        "valorUnitarioItem": 2700,
        "valorTotalItem": 2700,
        "dataHoraInclusao": "2025-08-07T12:55:33",
        "numeroControlePncpContrato": "00038166000105-2-000158/2025",
        "idCompra": "92513305900362025",
        "dataHoraExclusaoContrato": None,
        "contratoExcluido": False,
        "nomeOrgao": "BANCO CENTRAL DO BRASIL-ORC.FISCAL/SEG.SOCIAL",
        "nomeUnidadeGestora": "GERENCIA ADMINISTRATIVA EM FORTALEZA",
        "nomeUnidadeGestoraOrigemContrato": "GERENCIA ADMINISTRATIVA EM FORTALEZA",
        "nomeUnidadeRealizadoraCompra": "GERENCIA ADMINISTRATIVA EM FORTALEZA",
        "nomeModalidadeCompra": "Pregão",
        "numeroCompra": "90036/2025",
        "dataHoraExclusaoItem": None,
        "contratoItemExcluido": False,
        "numeroItem": numero_item,
        "esfera": "Federal",
        "poder": "Executivo",
        "numeroControlePncpCompra": "00038166000105-1-000273/2025",
    }
    base.update(overrides)
    return base


async def test_rejeita_so_uma_data_de_vigencia_informada():
    with pytest.raises(ValueError, match="juntos"):
        await consultar_itens_contrato_compras(
            codigo_orgao=25201, data_vigencia_inicial_min="2025-01-01"
        )
    with pytest.raises(ValueError, match="juntos"):
        await consultar_itens_contrato_compras(
            codigo_orgao=25201, data_vigencia_inicial_max="2025-01-01"
        )


async def test_usa_janela_padrao_quando_datas_nao_informadas():
    mock_itens = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_contratos_itens", new=mock_itens):
        await consultar_itens_contrato_compras(codigo_orgao=25201)
    _, kwargs = mock_itens.call_args
    assert kwargs["data_vigencia_inicial_min"] is not None
    assert kwargs["data_vigencia_inicial_max"] is not None
    assert kwargs["data_vigencia_inicial_min"] <= kwargs["data_vigencia_inicial_max"]


async def test_repassa_codigo_orgao_obrigatorio():
    mock_itens = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_contratos_itens", new=mock_itens):
        await consultar_itens_contrato_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
        )
    _, kwargs = mock_itens.call_args
    assert kwargs["codigo_orgao"] == "25201"


async def test_retorna_itens_formatados():
    mock_itens = AsyncMock(
        return_value={"resultado": [_item_bruto()], "totalRegistros": 1}
    )
    with patch(f"{_CLIENTE}.consultar_contratos_itens", new=mock_itens):
        resultado = await consultar_itens_contrato_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
        )
    assert resultado["total_no_periodo"] == 1
    item = resultado["itens"][0]
    assert item["codigo_item"] == 365121
    assert item["descricao_item"] == "ATUADOR ELETROMAGNÉTICO"
    assert item["valor_unitario_item"] == 2700
    assert item["numero_controle_pncp_contrato"] == "00038166000105-2-000158/2025"
    assert item["numero_controle_pncp_compra"] == "00038166000105-1-000273/2025"
    assert resultado["avisos"] == []


async def test_avisa_quando_ha_mais_itens_que_o_limite():
    itens_brutos = [_item_bruto(numero_item=f"{i:05d}", codigo_item=i) for i in range(1, 4)]
    mock_itens = AsyncMock(
        return_value={"resultado": itens_brutos, "totalRegistros": 10}
    )
    with patch(f"{_CLIENTE}.consultar_contratos_itens", new=mock_itens):
        resultado = await consultar_itens_contrato_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
            limite=3,
        )
    assert len(resultado["itens"]) == 3
    assert resultado["total_no_periodo"] == 10
    assert any("limite=3" in aviso for aviso in resultado["avisos"])


async def test_limite_e_limitado_ao_maximo():
    mock_itens = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_contratos_itens", new=mock_itens):
        await consultar_itens_contrato_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
            limite=9999,
        )
    _, kwargs = mock_itens.call_args
    assert kwargs["tamanho_pagina"] == 100


async def test_repassa_filtros_opcionais():
    mock_itens = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_contratos_itens", new=mock_itens):
        await consultar_itens_contrato_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
            codigo_item=365121,
            tipo_item="Material",
            ni_fornecedor="50079413000181",
            numero_contrato="05966/2025",
            codigo_modalidade_compra="05",
            codigo_unidade_gestora="925133",
        )
    _, kwargs = mock_itens.call_args
    assert kwargs["codigo_item"] == 365121
    assert kwargs["tipo_item"] == "Material"
    assert kwargs["ni_fornecedor"] == "50079413000181"
    assert kwargs["numero_contrato"] == "05966/2025"
    assert kwargs["codigo_modalidade_compra"] == "05"
    assert kwargs["codigo_unidade_gestora"] == "925133"
