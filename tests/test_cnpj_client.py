"""Testes do cliente de enriquecimento de CNPJ (BrasilAPI + fallback MinhaReceita)."""
from __future__ import annotations

import httpx
import pytest
import respx

from mcp_radardeprecos.clients import cnpj_client
from mcp_radardeprecos.clients.base import UpstreamError
from mcp_radardeprecos.config import settings

CNPJ = "30051023000196"

DADOS_BRASILAPI = {
    "cnpj": CNPJ,
    "razao_social": "EMPRESA TESTE LTDA",
    "nome_fantasia": "TESTE",
    "descricao_situacao_cadastral": "ATIVA",
    "qsa": [],
}

DADOS_MINHARECEITA = {
    "cnpj": CNPJ,
    "razao_social": "EMPRESA TESTE LTDA (VIA MINHARECEITA)",
    "nome_fantasia": "TESTE",
    "descricao_situacao_cadastral": "ATIVA",
    "qsa": [],
}


def test_limpar_cnpj_remove_pontuacao():
    assert cnpj_client.limpar_cnpj("30.051.023/0001-96") == CNPJ
    assert cnpj_client.limpar_cnpj(CNPJ) == CNPJ
    assert cnpj_client.limpar_cnpj(" 30 051 023 0001 96 ") == CNPJ


@respx.mock
async def test_consultar_cnpj_usa_brasilapi_quando_disponivel():
    route_brasilapi = respx.get(f"{settings.brasilapi_base_url}/cnpj/v1/{CNPJ}").mock(
        return_value=httpx.Response(200, json=DADOS_BRASILAPI)
    )
    route_minhareceita = respx.get(f"{settings.minhareceita_base_url}/{CNPJ}")

    resultado = await cnpj_client.consultar_cnpj(CNPJ)

    assert resultado["_provider"] == "brasilapi"
    assert resultado["razao_social"] == "EMPRESA TESTE LTDA"
    assert route_brasilapi.called
    assert not route_minhareceita.called


@respx.mock
async def test_consultar_cnpj_cai_para_minhareceita_quando_brasilapi_falha():
    route_brasilapi = respx.get(f"{settings.brasilapi_base_url}/cnpj/v1/{CNPJ}").mock(
        return_value=httpx.Response(503, text="upstream indisponivel")
    )
    route_minhareceita = respx.get(f"{settings.minhareceita_base_url}/{CNPJ}").mock(
        return_value=httpx.Response(200, json=DADOS_MINHARECEITA)
    )

    resultado = await cnpj_client.consultar_cnpj(CNPJ)

    assert resultado["_provider"] == "minhareceita"
    assert resultado["razao_social"] == "EMPRESA TESTE LTDA (VIA MINHARECEITA)"
    assert route_brasilapi.called
    assert route_minhareceita.called


@respx.mock
async def test_consultar_cnpj_propaga_erro_quando_os_dois_falham():
    respx.get(f"{settings.brasilapi_base_url}/cnpj/v1/{CNPJ}").mock(
        return_value=httpx.Response(404, text="nao encontrado")
    )
    respx.get(f"{settings.minhareceita_base_url}/{CNPJ}").mock(
        return_value=httpx.Response(500, text="erro interno")
    )

    with pytest.raises(UpstreamError) as exc_info:
        await cnpj_client.consultar_cnpj(CNPJ)

    mensagem = str(exc_info.value)
    assert "BrasilAPI" in mensagem
    assert "MinhaReceita" in mensagem


@respx.mock
async def test_consultar_cnpj_usa_cache_na_segunda_chamada():
    route_brasilapi = respx.get(f"{settings.brasilapi_base_url}/cnpj/v1/{CNPJ}").mock(
        return_value=httpx.Response(200, json=DADOS_BRASILAPI)
    )

    primeiro = await cnpj_client.consultar_cnpj(CNPJ)
    segundo = await cnpj_client.consultar_cnpj(CNPJ)

    assert primeiro == segundo
    assert route_brasilapi.call_count == 1
