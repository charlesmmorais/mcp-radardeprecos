"""Testes do cliente SGS/Banco Central (série 433 — IPCA), com HTTP mockado."""
from __future__ import annotations

from datetime import date

import httpx
import respx

from mcp_radardeprecos.clients import bcb_client
from mcp_radardeprecos.config import settings

_URL = f"{settings.bcb_sgs_base_url}/dados/serie/bcdata.sgs.433/dados"


@respx.mock
async def test_obter_ipca_mensal_monta_parametros_e_normaliza():
    route = respx.get(_URL).mock(
        return_value=httpx.Response(200, json=[
            {"data": "01/02/2026", "valor": "0.80"},
            {"data": "01/01/2026", "valor": "0,50"},  # vírgula decimal tolerada
        ])
    )
    serie = await bcb_client.obter_ipca_mensal(date(2026, 1, 1), date(2026, 3, 1))

    params = route.calls.last.request.url.params
    assert params["formato"] == "json"
    assert params["dataInicial"] == "01/01/2026"
    assert params["dataFinal"] == "01/03/2026"
    # Normalizado, ordenado cronologicamente e com float de verdade:
    assert serie == [
        {"competencia": "2026-01", "variacao_percentual": 0.5},
        {"competencia": "2026-02", "variacao_percentual": 0.8},
    ]


@respx.mock
async def test_obter_ipca_mensal_ignora_registro_malformado():
    respx.get(_URL).mock(
        return_value=httpx.Response(200, json=[
            {"data": "01/01/2026", "valor": "0.50"},
            {"data": "sem-barra", "valor": "1.00"},
            {"data": "01/02/2026", "valor": "nao-numerico"},
        ])
    )
    serie = await bcb_client.obter_ipca_mensal(date(2026, 1, 1), date(2026, 3, 1))
    assert serie == [{"competencia": "2026-01", "variacao_percentual": 0.5}]


@respx.mock
async def test_obter_ipca_mensal_usa_cache_na_segunda_chamada():
    route = respx.get(_URL).mock(
        return_value=httpx.Response(200, json=[{"data": "01/01/2026", "valor": "0.50"}])
    )
    a = await bcb_client.obter_ipca_mensal(date(2026, 1, 1), date(2026, 2, 1))
    b = await bcb_client.obter_ipca_mensal(date(2026, 1, 1), date(2026, 2, 1))
    assert a == b
    assert route.call_count == 1  # segunda veio do cache


@respx.mock
async def test_obter_indice_mensal_monta_url_com_a_serie_pedida():
    # IGP-M = série 189 do SGS — obter_ipca_mensal
    # é hoje um wrapper fino sobre obter_indice_mensal(433, ...).
    url_igpm = f"{settings.bcb_sgs_base_url}/dados/serie/bcdata.sgs.189/dados"
    route = respx.get(url_igpm).mock(
        return_value=httpx.Response(200, json=[{"data": "01/02/2026", "valor": "-0.80"}])
    )
    serie = await bcb_client.obter_indice_mensal(189, date(2026, 1, 1), date(2026, 3, 1))
    assert route.called
    assert serie == [{"competencia": "2026-02", "variacao_percentual": -0.8}]


@respx.mock
async def test_obter_ipca_mensal_delega_para_obter_indice_mensal_com_serie_433():
    route = respx.get(_URL).mock(
        return_value=httpx.Response(200, json=[{"data": "01/01/2026", "valor": "0.50"}])
    )
    serie = await bcb_client.obter_ipca_mensal(date(2026, 1, 1), date(2026, 2, 1))
    assert route.called
    assert serie == [{"competencia": "2026-01", "variacao_percentual": 0.5}]
