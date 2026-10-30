"""Testes do cliente do Banco de Preços em Saúde."""
from __future__ import annotations

import httpx
import respx

from mcp_radardeprecos.clients import bps_client

_BASE = "https://apidadosabertos.saude.gov.br"
_ROTA = f"{_BASE}/economia-da-saude/bps"


@respx.mock
async def test_url_nao_tem_v1():
    """O `/v1` é onde o Swagger UI está montado, não prefixo da API.

    A especificação (`/static/swagger.json`) não declara `basePath`, então os
    caminhos são relativos à raiz. Montar a URL a partir do endereço da página
    de documentação devolve 404 — foi o primeiro erro cometido aqui.
    """
    rota = respx.get(_ROTA).mock(return_value=httpx.Response(200, json={"bps": []}))
    await bps_client.consultar_bps(codigo_catmat="268252")

    assert rota.called
    assert "/v1/" not in str(rota.calls[0].request.url)


@respx.mock
async def test_nunca_envia_ordenacao():
    """Ver `_ORDENACAO_NAO_USAR`: o parâmetro destrói a ordem padrão.

    Este teste existe para que uma futura "melhoria" que reintroduza
    `ordenacao` — achando que passa a ordenar por preço — falhe aqui, e não
    numa pesquisa de preço em que alguém tome um valor arbitrário por mínimo.
    """
    rota = respx.get(_ROTA).mock(return_value=httpx.Response(200, json={"bps": []}))
    await bps_client.consultar_bps(codigo_catmat="268252")

    assert "ordenacao" not in str(rota.calls[0].request.url)


@respx.mock
async def test_extrai_da_chave_bps():
    respx.get(_ROTA).mock(
        return_value=httpx.Response(200, json={"bps": [{"precoUnitario": 1.0}]})
    )
    assert await bps_client.consultar_bps(codigo_catmat="268252") == [
        {"precoUnitario": 1.0}
    ]


@respx.mock
async def test_envelope_inesperado_nao_derruba_mas_e_registrado(caplog):
    """Se a origem mudar de forma, o silêncio seria pior que o erro."""
    respx.get(_ROTA).mock(return_value=httpx.Response(200, json=[{"a": 1}]))
    assert await bps_client.consultar_bps(codigo_catmat="268252") == []
    assert any("envelope inesperado" in r.message for r in caplog.records)


@respx.mock
async def test_cnpj_com_mascara_e_normalizado():
    rota = respx.get(_ROTA).mock(return_value=httpx.Response(200, json={"bps": []}))
    await bps_client.consultar_bps(cnpj_instituicao="28.715.986/0001-03")
    assert "28715986000103" in str(rota.calls[0].request.url)


@respx.mock
async def test_tamanho_pagina_limitado_ao_teto_da_origem():
    rota = respx.get(_ROTA).mock(return_value=httpx.Response(200, json={"bps": []}))
    await bps_client.consultar_bps(codigo_catmat="268252", tamanho_pagina=9999)
    assert "tamanhoPagina=500" in str(rota.calls[0].request.url)
