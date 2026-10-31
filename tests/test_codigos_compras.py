"""Códigos de órgão e UASG chegam à fonte com zero à esquerda.

Sem o zero, o Compras.gov.br devolve lista vazia (``codigoOrgao=3000`` → 0
contratos; ``03000`` → 5), e a tool afirmava que o órgão não tinha contratos.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from mcp_radardeprecos.clients import compras_client
from mcp_radardeprecos.config import settings
from mcp_radardeprecos.tools.consultar_contratos_compras import consultar_contratos_compras
from mcp_radardeprecos.tools.consultar_itens_contrato_compras import (
    consultar_itens_contrato_compras,
)
from mcp_radardeprecos.utils.codigos import normalizar_codigo_orgao, normalizar_codigo_uasg

_BASE = settings.compras_dadosabertos_base_url
_VAZIO = {"resultado": [], "totalRegistros": 0, "totalPaginas": 0, "paginasRestantes": 0}


@pytest.mark.parametrize(
    "entrada, esperado",
    [(3000, "03000"), ("3000", "03000"), ("03000", "03000"), (" 03000 ", "03000"),
     (26000, "26000"), ("003000", "03000"), (None, None), ("", None)],
)
def test_normaliza_codigo_orgao(entrada, esperado):
    assert normalizar_codigo_orgao(entrada) == esperado


@pytest.mark.parametrize(
    "entrada, esperado",
    [(30001, "030001"), ("30001", "030001"), ("030001", "030001"), (925001, "925001"), (None, None)],
)
def test_normaliza_codigo_uasg(entrada, esperado):
    assert normalizar_codigo_uasg(entrada) == esperado


@pytest.mark.parametrize("invalido", ["03.000", "abc", "123456", True, -3000])
def test_codigo_orgao_invalido_e_recusado(invalido):
    with pytest.raises(ValueError, match="codigo_orgao"):
        normalizar_codigo_orgao(invalido)


@respx.mock
@pytest.mark.parametrize("codigo", [3000, "3000", "03000"])
async def test_contratos_enviam_codigo_orgao_com_zero(codigo):
    rota = respx.get(f"{_BASE}/modulo-contratos/1_consultarContratos").mock(
        return_value=httpx.Response(200, json=_VAZIO)
    )
    await compras_client.consultar_contratos(
        codigo_orgao=codigo, data_vigencia_inicial_min="2026-01-01",
        data_vigencia_inicial_max="2026-10-30", codigo_unidade_gestora=30001,
    )
    params = rota.calls.last.request.url.params
    assert params["codigoOrgao"] == "03000"
    assert params["codigoUnidadeGestora"] == "030001"


@respx.mock
async def test_itens_de_contrato_e_fim_de_vigencia_enviam_codigo_com_zero():
    itens = respx.get(f"{_BASE}/modulo-contratos/2_consultarContratosItem").mock(
        return_value=httpx.Response(200, json=_VAZIO)
    )
    fim = respx.get(f"{_BASE}/modulo-contratos/1.2_consultarContratos_FimVigencia").mock(
        return_value=httpx.Response(200, json=_VAZIO)
    )
    await compras_client.consultar_contratos_itens(
        codigo_orgao=3000, data_vigencia_inicial_min="2026-01-01",
        data_vigencia_inicial_max="2026-10-30",
    )
    await compras_client.consultar_contratos_fim_vigencia(
        codigo_orgao=3000, data_vigencia_final_min="2026-10-30",
        data_vigencia_final_max="2027-10-30",
    )
    assert itens.calls.last.request.url.params["codigoOrgao"] == "03000"
    assert fim.calls.last.request.url.params["codigoOrgao"] == "03000"


@respx.mock
async def test_atas_enviam_uasg_com_zero():
    arp = respx.get(f"{_BASE}/modulo-arp/1_consultarARP").mock(
        return_value=httpx.Response(200, json=_VAZIO)
    )
    arp_itens = respx.get(f"{_BASE}/modulo-arp/2_consultarARPItem").mock(
        return_value=httpx.Response(200, json=_VAZIO)
    )
    fim = respx.get(f"{_BASE}/modulo-arp/1.2_consultarARP_FimVigencia").mock(
        return_value=httpx.Response(200, json=_VAZIO)
    )
    await compras_client.consultar_arp(
        data_vigencia_inicial_min="2026-01-01", data_vigencia_inicial_max="2026-10-30",
        codigo_unidade_gerenciadora=30001,
    )
    await compras_client.consultar_arp_itens(
        data_vigencia_inicial_min="2026-01-01", data_vigencia_inicial_max="2026-10-30",
        codigo_unidade_gerenciadora=30001,
    )
    await compras_client.consultar_arp_fim_vigencia(
        codigo_unidade_gerenciadora="30001", data_vigencia_final_min="2026-10-30",
        data_vigencia_final_max="2027-10-30",
    )
    for rota in (arp, arp_itens, fim):
        assert rota.calls.last.request.url.params["codigoUnidadeGerenciadora"] == "030001"


@pytest.mark.parametrize(
    "tool, chave, metodo",
    [(consultar_contratos_compras, "contratos", "consultar_contratos"),
     (consultar_itens_contrato_compras, "itens", "consultar_contratos_itens")],
)
async def test_resultado_vazio_traz_aviso_com_o_codigo_usado(tool, chave, metodo):
    mock = AsyncMock(return_value=_VAZIO)
    with patch(f"mcp_radardeprecos.tools.{tool.__name__}.compras_client.{metodo}", new=mock):
        resultado = await tool(codigo_orgao=3000)
    assert mock.await_args.kwargs["codigo_orgao"] == "03000"
    assert resultado[chave] == []
    assert any("03000" in aviso and "zero à esquerda" in aviso for aviso in resultado["avisos"])


async def test_codigo_orgao_vazio_e_recusado_sem_chamar_a_fonte():
    mock = AsyncMock(return_value=_VAZIO)
    with patch(
        "mcp_radardeprecos.tools.consultar_contratos_compras.compras_client.consultar_contratos",
        new=mock,
    ), pytest.raises(ValueError, match="obrigatório"):
        await consultar_contratos_compras(codigo_orgao="")
    mock.assert_not_awaited()


@pytest.mark.parametrize("codigo", [3000, "3000", "03000"])
@pytest.mark.parametrize(
    "tool, metodo",
    [("consultar_contratos_compras", "consultar_contratos"),
     ("consultar_itens_contrato_compras", "consultar_contratos_itens")],
)
async def test_protocolo_mcp_aceita_codigo_como_numero_ou_texto(tool, metodo, codigo):
    """Pela validação do MCP: o parâmetro já foi ``int``; clientes ainda mandam número."""
    from mcp_radardeprecos import server

    mock = AsyncMock(return_value=_VAZIO)
    with patch(f"mcp_radardeprecos.tools.{tool}.compras_client.{metodo}", new=mock):
        await server.mcp.call_tool(tool, {"codigo_orgao": codigo})
    assert mock.await_args.kwargs["codigo_orgao"] == "03000"
