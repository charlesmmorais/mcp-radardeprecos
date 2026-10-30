"""Testes de `consultar_contratos_compras` — contratos, nível cabeçalho (Compras.gov.br)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.consultar_contratos_compras import (
    consultar_contratos_compras,
)

_CLIENTE = "mcp_radardeprecos.clients.compras_client"


def _contrato_bruto(numero_contrato="01046/2025", **overrides):
    # Formato real confirmado ao vivo em 2026-07-10 (codigoOrgao=25201,
    # Banco Central do Brasil).
    base = {
        "codigoOrgao": "25201",
        "nomeOrgao": "BANCO CENTRAL DO BRASIL-ORC.FISCAL/SEG.SOCIAL",
        "codigoUnidadeGestora": "179087",
        "nomeUnidadeGestora": "BANCO CENTRAL DO BRASIL - BRASÍLIA",
        "codigoUnidadeGestoraOrigemContrato": "179087",
        "nomeUnidadeGestoraOrigemContrato": "BANCO CENTRAL DO BRASIL - BRASÍLIA",
        "receitaDespesa": "D",
        "numeroContrato": numero_contrato,
        "codigoUnidadeRealizadoraCompra": "179087",
        "nomeUnidadeRealizadoraCompra": "BANCO CENTRAL DO BRASIL - BRASÍLIA",
        "numeroCompra": "00347/2025",
        "codigoModalidadeCompra": "07",
        "nomeModalidadeCompra": "Inexigibilidade",
        "codigoTipo": "50",
        "nomeTipo": "Contrato",
        "codigoCategoria": "60",
        "nomeCategoria": "Serviços",
        "codigoSubcategoria": None,
        "nomeSubcategoria": None,
        "niFornecedor": "62070115000100",
        "nomeRazaoSocialFornecedor": "INSTITUTO DOS AUDITORES INTERNOS DO BRASIL",
        "processo": "282805",
        "objeto": (
            "CONTRATAÇÃO DE SERVIÇOS DE PRÉ-AVALIAÇÃO E AVALIAÇÃO DAS "
            "ATIVIDADES DA AUDITORIA INTERNA DO BANCO CENTRAL DO BRASIL"
        ),
        "informacoesComplementares": "",
        "dataVigenciaInicial": "2025-08-04T00:00:00",
        "dataVigenciaFinal": "2026-08-04T00:00:00",
        "valorGlobal": 303450,
        "numeroParcelas": 1,
        "valorParcela": 303450,
        "valorAcumulado": 303450,
        "totalDespesasAcessorias": None,
        "dataHoraInclusao": "2025-08-05T10:49:21",
        "numeroControlePncpContrato": "00038166000105-2-000155/2025",
        "numeroControlePncpCompra": "00038166000105-1-000254/2025",
        "idCompra": "17908707003472025",
        "dataHoraExclusao": None,
        "contratoExcluido": False,
        "unidadesRequisitantes": None,
    }
    base.update(overrides)
    return base


async def test_rejeita_so_uma_data_de_vigencia_informada():
    with pytest.raises(ValueError, match="juntos"):
        await consultar_contratos_compras(
            codigo_orgao=25201, data_vigencia_inicial_min="2025-01-01"
        )
    with pytest.raises(ValueError, match="juntos"):
        await consultar_contratos_compras(
            codigo_orgao=25201, data_vigencia_inicial_max="2025-01-01"
        )


async def test_usa_janela_padrao_quando_datas_nao_informadas():
    mock_contratos = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_contratos", new=mock_contratos):
        await consultar_contratos_compras(codigo_orgao=25201)
    _, kwargs = mock_contratos.call_args
    assert kwargs["data_vigencia_inicial_min"] is not None
    assert kwargs["data_vigencia_inicial_max"] is not None
    assert kwargs["data_vigencia_inicial_min"] <= kwargs["data_vigencia_inicial_max"]


async def test_repassa_codigo_orgao_obrigatorio():
    mock_contratos = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_contratos", new=mock_contratos):
        await consultar_contratos_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
        )
    _, kwargs = mock_contratos.call_args
    assert kwargs["codigo_orgao"] == 25201


async def test_retorna_contratos_formatados():
    mock_contratos = AsyncMock(
        return_value={"resultado": [_contrato_bruto()], "totalRegistros": 1}
    )
    with patch(f"{_CLIENTE}.consultar_contratos", new=mock_contratos):
        resultado = await consultar_contratos_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
        )
    assert resultado["total_no_periodo"] == 1
    contrato = resultado["contratos"][0]
    assert contrato["numero_contrato"] == "01046/2025"
    assert contrato["objeto"].startswith("CONTRATAÇÃO DE SERVIÇOS")
    assert contrato["tipo"] == "Contrato"
    assert contrato["categoria"] == "Serviços"
    assert contrato["receita_despesa"] == "D"
    assert contrato["valor_global"] == 303450
    assert contrato["numero_parcelas"] == 1
    assert contrato["numero_controle_pncp_contrato"] == "00038166000105-2-000155/2025"
    assert contrato["numero_controle_pncp_compra"] == "00038166000105-1-000254/2025"
    assert resultado["avisos"] == []


async def test_avisa_quando_ha_mais_contratos_que_o_limite():
    contratos_brutos = [
        _contrato_bruto(numero_contrato=f"{i:05d}/2025") for i in range(1, 4)
    ]
    mock_contratos = AsyncMock(
        return_value={"resultado": contratos_brutos, "totalRegistros": 10}
    )
    with patch(f"{_CLIENTE}.consultar_contratos", new=mock_contratos):
        resultado = await consultar_contratos_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
            limite=3,
        )
    assert len(resultado["contratos"]) == 3
    assert resultado["total_no_periodo"] == 10
    assert any("limite=3" in aviso for aviso in resultado["avisos"])


async def test_limite_e_limitado_ao_maximo():
    mock_contratos = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_contratos", new=mock_contratos):
        await consultar_contratos_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
            limite=9999,
        )
    _, kwargs = mock_contratos.call_args
    assert kwargs["tamanho_pagina"] == 100


async def test_repassa_filtros_opcionais():
    mock_contratos = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_contratos", new=mock_contratos):
        await consultar_contratos_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-08-01",
            data_vigencia_inicial_max="2026-07-01",
            ni_fornecedor="62070115000100",
            numero_contrato="01046/2025",
            codigo_modalidade_compra="07",
            codigo_tipo="50",
            codigo_categoria="60",
            codigo_unidade_gestora="179087",
        )
    _, kwargs = mock_contratos.call_args
    assert kwargs["ni_fornecedor"] == "62070115000100"
    assert kwargs["numero_contrato"] == "01046/2025"
    assert kwargs["codigo_modalidade_compra"] == "07"
    assert kwargs["codigo_tipo"] == "50"
    assert kwargs["codigo_categoria"] == "60"
    assert kwargs["codigo_unidade_gestora"] == "179087"
