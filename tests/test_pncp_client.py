"""Testes do cliente PNCP com HTTP mockado (nenhuma chamada de rede real)."""
from __future__ import annotations

import httpx
import pytest
import respx

from mcp_radardeprecos.clients import pncp_client
from mcp_radardeprecos.clients.base import UpstreamError
from mcp_radardeprecos.config import settings


@respx.mock
async def test_buscar_texto_monta_parametros_corretos():
    route = respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    resultado = await pncp_client.buscar_texto("notebook", "edital", uf="SP", pagina=1, tamanho_pagina=10)
    assert resultado == {"items": [], "total": 0}
    request = route.calls.last.request
    assert request.url.params["q"] == "notebook"
    assert request.url.params["tipos_documento"] == "edital"
    # Regressão: o parâmetro correto é "ufs" (plural). "uf" (singular) é
    # silenciosamente ignorado pelo servidor real — confirmado em teste
    # manual contra a API ao vivo (ver notas em clients/pncp_client.py).
    assert request.url.params["ufs"] == "SP"
    assert "uf" not in request.url.params
    assert request.url.params["ordenacao"] == "-data"


@respx.mock
async def test_buscar_texto_aceita_modalidade_municipio_e_ano():
    route = respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    await pncp_client.buscar_texto(
        "notebook", "edital", modalidade=6, municipio="3830", ano=2026
    )
    params = route.calls.last.request.url.params
    assert params["modalidades"] == "6"
    assert params["municipios"] == "3830"
    assert params["anos"] == "2026"


@respx.mock
async def test_buscar_texto_aceita_filtros_de_orgao_unidade_esfera_e_poder():
    route = respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    await pncp_client.buscar_texto(
        "notebook",
        "edital",
        tipo_instrumento=1,
        orgao="44611",
        unidade="912",
        esfera="F",
        poder="E",
        fonte_orcamentaria="1",
        tipo_margem_preferencia="1",
    )
    params = route.calls.last.request.url.params
    assert params["tipos"] == "1"
    assert params["orgaos"] == "44611"
    assert params["unidades"] == "912"
    assert params["esferas"] == "F"
    assert params["poderes"] == "E"
    assert params["fontes_orcamentarias"] == "1"
    assert params["tipos_margens_preferencia"] == "1"


@respx.mock
async def test_buscar_texto_aceita_filtros_booleanos():
    route = respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    await pncp_client.buscar_texto(
        "notebook",
        "edital",
        exigencia_conteudo_nacional=True,
        possui_emenda_parlamentar=False,
    )
    params = route.calls.last.request.url.params
    # Regressão: o nome correto do parâmetro é "possui_emenda_parlamentar",
    # não "emenda_parlamentar" (que é silenciosamente ignorado pelo servidor).
    assert params["exigencia_conteudo_nacional"] == "true"
    assert params["possui_emenda_parlamentar"] == "false"
    assert "emenda_parlamentar" not in params


@respx.mock
async def test_buscar_texto_omite_filtros_booleanos_quando_nao_informados():
    route = respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    await pncp_client.buscar_texto("notebook", "edital")
    params = route.calls.last.request.url.params
    assert "exigencia_conteudo_nacional" not in params
    assert "possui_emenda_parlamentar" not in params
    assert "permite_adesao" not in params


@respx.mock
async def test_buscar_texto_aceita_permite_adesao_para_atas():
    route = respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    await pncp_client.buscar_texto("notebook", "ata", permite_adesao=True)
    assert route.calls.last.request.url.params["permite_adesao"] == "true"


@respx.mock
async def test_buscar_texto_aceita_tipo_contrato_para_contratos():
    route = respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    await pncp_client.buscar_texto("notebook", "contrato", tipo_contrato=7)
    assert route.calls.last.request.url.params["tipos_contrato"] == "7"


@respx.mock
async def test_buscar_texto_limita_tamanho_pagina_a_100():
    route = respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    await pncp_client.buscar_texto("notebook", "edital", tamanho_pagina=999)
    assert route.calls.last.request.url.params["tam_pagina"] == "100"


@respx.mock
async def test_listar_filtros_monta_parametros_corretos():
    route = respx.get(f"{settings.pncp_search_base_url}/filters").mock(
        return_value=httpx.Response(200, json={"filters": {"ufs": [{"id": "SP", "total": 10}]}})
    )
    resultado = await pncp_client.listar_filtros("edital")
    assert resultado["filters"]["ufs"][0]["id"] == "SP"
    assert route.calls.last.request.url.params["tipos_documento"] == "edital"


def test_parse_numero_controle_pncp_valido():
    assert pncp_client.parse_numero_controle_pncp("33683111000107-1-000084/2025") == (
        "33683111000107",
        2025,
        84,
    )


def test_parse_numero_controle_pncp_invalido_retorna_none():
    assert pncp_client.parse_numero_controle_pncp("formato-invalido") is None


def test_classificar_numero_controle_pncp():
    c = pncp_client.classificar_numero_controle_pncp
    assert c("33683111000107-1-000084/2025") == "contratacao"
    assert c("16854531000181-2-000066/2023") == "contrato"
    assert c("18457226000181-1-000015/2023-000001") == "ata"
    assert c("formato-invalido") == "desconhecido"
    assert c("") == "desconhecido"


@respx.mock
async def test_consultar_itens_contratacao():
    respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/compras/2025/10/itens"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"descricao": "Notebook", "valorUnitarioEstimado": 3000.0}]
        )
    )
    itens = await pncp_client.consultar_itens_contratacao("12345678000199", 2025, 10)
    assert itens[0]["descricao"] == "Notebook"


@respx.mock
async def test_consultar_arquivos_compras_monta_path_e_parametros_corretos():
    route = respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/compras/2026/10/arquivos"
    ).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "titulo": "Edital.pdf",
                    "tipoDocumentoNome": "Edital",
                    "dataPublicacaoPncp": "2026-07-03T10:00:00",
                    "sequencialDocumento": 1,
                    "uri": "https://pncp.gov.br/pncp-api/v1/orgaos/12345678000199/compras/2026/10/arquivos/1",
                }
            ],
        )
    )
    resultado = await pncp_client.consultar_arquivos("12345678000199", 2026, 10, "compras")
    assert resultado[0]["titulo"] == "Edital.pdf"
    params = route.calls.last.request.url.params
    assert params["pagina"] == "1"
    assert params["tamanhoPagina"] == "50"


@respx.mock
async def test_consultar_arquivos_contratos_usa_path_de_contratos():
    route = respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/00509968000148/contratos/2026/1835/arquivos"
    ).mock(return_value=httpx.Response(200, json=[]))
    await pncp_client.consultar_arquivos("00509968000148", 2026, 1835, "contratos")
    assert route.called


@respx.mock
async def test_get_json_propaga_erro_upstream_em_4xx():
    respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(422, text="parametro invalido")
    )
    with pytest.raises(UpstreamError):
        await pncp_client.buscar_texto("x", "edital")


def test_parse_numero_controle_pncp_ata_valido():
    assert pncp_client.parse_numero_controle_pncp_ata(
        "18457226000181-1-000015/2023-000001"
    ) == ("18457226000181", 2023, 15, 1)


def test_parse_numero_controle_pncp_ata_invalido_retorna_none():
    assert pncp_client.parse_numero_controle_pncp_ata("formato-invalido") is None


@respx.mock
async def test_consultar_itens_contratacao_usa_cache_na_segunda_chamada():
    route = respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/11111111000191/compras/2026/1/itens"
    ).mock(return_value=httpx.Response(200, json=[{"descricao": "Item 1"}]))
    primeira = await pncp_client.consultar_itens_contratacao("11111111000191", 2026, 1)
    segunda = await pncp_client.consultar_itens_contratacao("11111111000191", 2026, 1)
    assert primeira == segunda == [{"descricao": "Item 1"}]
    assert route.call_count == 1  # segunda chamada veio do cache, não da rede


@respx.mock
async def test_consultar_resultado_item():
    respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/22222222000100/compras/2026/2/itens/1/resultados"
    ).mock(return_value=httpx.Response(200, json=[{"valorUnitarioHomologado": 99.9}]))
    resultado = await pncp_client.consultar_resultado_item("22222222000100", 2026, 2, 1)
    assert resultado[0]["valorUnitarioHomologado"] == 99.9


@respx.mock
async def test_consultar_contratacao_detalhe():
    route = respx.get(
        f"{settings.pncp_consulta_base_url}/v1/orgaos/33333333000122/compras/2026/3"
    ).mock(return_value=httpx.Response(200, json={"srp": True, "valorTotalHomologado": 5000.0}))
    detalhe = await pncp_client.consultar_contratacao_detalhe("33333333000122", 2026, 3)
    assert detalhe["srp"] is True
    assert detalhe["valorTotalHomologado"] == 5000.0
    assert route.called


@respx.mock
async def test_consultar_contratos_monta_parametros_com_cnpj_orgao():
    # Corrigido na v0.1.13: não existe filtro por cnpjFornecedor nesta API
    # (confirmado contra a especificação OpenAPI oficial) — o único filtro
    # de CNPJ real deste endpoint é cnpjOrgao.
    route = respx.get(f"{settings.pncp_consulta_base_url}/v1/contratos").mock(
        return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0})
    )
    await pncp_client.consultar_contratos(
        data_inicial="20260101",
        data_final="20260701",
        cnpj_orgao="44444444000133",
    )
    params = route.calls.last.request.url.params
    assert params["cnpjOrgao"] == "44444444000133"
    assert "cnpjFornecedor" not in params


@respx.mock
async def test_consultar_ata():
    route = respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/55555555000144/compras/2023/4/atas/1"
    ).mock(return_value=httpx.Response(200, json={"numeroAtaRegistroPreco": "001/2023"}))
    ata = await pncp_client.consultar_ata("55555555000144", 2023, 4, 1)
    assert ata["numeroAtaRegistroPreco"] == "001/2023"
    assert route.called


@respx.mock
async def test_consultar_itens_ata_lista_vazia_nao_e_erro():
    respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/66666666000155/compras/2023/5/atas/1/itens"
    ).mock(return_value=httpx.Response(200, json=[]))
    itens = await pncp_client.consultar_itens_ata("66666666000155", 2023, 5, 1)
    assert itens == []


@respx.mock
async def test_consultar_arquivos_ata():
    respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/77777777000166/compras/2023/6/atas/1/arquivos"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"titulo": "Ata assinada.pdf", "url": "https://pncp.gov.br/x"}]
        )
    )
    arquivos = await pncp_client.consultar_arquivos_ata("77777777000166", 2023, 6, 1)
    assert arquivos[0]["titulo"] == "Ata assinada.pdf"


@respx.mock
async def test_consultar_pca_por_classificacao_monta_parametros():
    route = respx.get(f"{settings.pncp_consulta_base_url}/v1/pca/").mock(
        return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0})
    )
    await pncp_client.consultar_pca_por_classificacao(2026, "7510", pagina=2, tamanho_pagina=1000)
    params = route.calls.last.request.url.params
    assert params["anoPca"] == "2026"
    assert params["codigoClassificacaoSuperior"] == "7510"
    assert params["pagina"] == "2"
    # tamanho_pagina é limitado a 500 (máximo da própria API).
    assert params["tamanhoPagina"] == "500"


@respx.mock
async def test_consultar_pca_por_periodo_monta_parametros_com_cnpj_opcional():
    route = respx.get(f"{settings.pncp_consulta_base_url}/v1/pca/atualizacao").mock(
        return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0})
    )
    await pncp_client.consultar_pca_por_periodo(
        "20260101", "20260701", cnpj="11222333000181", codigo_unidade="UND1"
    )
    params = route.calls.last.request.url.params
    assert params["dataInicio"] == "20260101"
    assert params["dataFim"] == "20260701"
    assert params["cnpj"] == "11222333000181"
    assert params["codigoUnidade"] == "UND1"


@respx.mock
async def test_consultar_pca_por_periodo_sem_cnpj_nao_envia_parametro():
    route = respx.get(f"{settings.pncp_consulta_base_url}/v1/pca/atualizacao").mock(
        return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0})
    )
    await pncp_client.consultar_pca_por_periodo("20260101", "20260701")
    params = route.calls.last.request.url.params
    assert "cnpj" not in params
    assert "codigoUnidade" not in params


@respx.mock
async def test_consultar_atas_periodo_monta_parametros_em_aaaammdd():
    route = respx.get(f"{settings.pncp_consulta_base_url}/v1/atas").mock(
        return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0})
    )
    await pncp_client.consultar_atas_periodo(
        data_inicial="20260101", data_final="20260201", cnpj="11222333000181"
    )
    params = route.calls.last.request.url.params
    assert params["dataInicial"] == "20260101"
    assert params["dataFinal"] == "20260201"
    assert params["cnpj"] == "11222333000181"
    assert params["pagina"] == "1"


@respx.mock
async def test_consultar_atas_periodo_limita_tamanho_pagina_a_500():
    route = respx.get(f"{settings.pncp_consulta_base_url}/v1/atas").mock(
        return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0})
    )
    await pncp_client.consultar_atas_periodo(
        data_inicial="20260101", data_final="20260201", tamanho_pagina=9999
    )
    assert route.calls.last.request.url.params["tamanhoPagina"] == "500"


@respx.mock
async def test_consultar_contratacoes_proposta_aberta_monta_parametros():
    route = respx.get(f"{settings.pncp_consulta_base_url}/v1/contratacoes/proposta").mock(
        return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0})
    )
    await pncp_client.consultar_contratacoes_proposta_aberta(
        data_final="20260801", uf="SP", codigo_modalidade_contratacao=6,
    )
    params = route.calls.last.request.url.params
    assert params["dataFinal"] == "20260801"
    assert params["uf"] == "SP"
    assert params["codigoModalidadeContratacao"] == "6"
    assert "dataInicial" not in params


@respx.mock
async def test_consultar_contratacoes_proposta_aberta_limita_tamanho_pagina_a_50():
    # Diferente da maioria dos endpoints da API de Consulta (teto 500/100),
    # este endpoint tem teto de 50 — confirmado na spec oficial (ver
    # docstring da função e a análise das specs oficiais).
    route = respx.get(f"{settings.pncp_consulta_base_url}/v1/contratacoes/proposta").mock(
        return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0})
    )
    await pncp_client.consultar_contratacoes_proposta_aberta(
        data_final="20260801", tamanho_pagina=9999,
    )
    assert route.calls.last.request.url.params["tamanhoPagina"] == "50"


@respx.mock
async def test_consultar_termos_contrato_monta_path_e_parametros():
    route = respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/contratos/2026/10/termos"
    ).mock(return_value=httpx.Response(200, json={"data": [{"numeroTermo": 1}]}))
    resultado = await pncp_client.consultar_termos_contrato("12345678000199", 2026, 10)
    assert resultado == [{"numeroTermo": 1}]
    assert route.calls.last.request.url.params["pagina"] == "1"


@respx.mock
async def test_consultar_termos_contrato_aceita_retorno_em_lista_simples():
    respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/contratos/2026/10/termos"
    ).mock(return_value=httpx.Response(200, json=[{"numeroTermo": 1}]))
    resultado = await pncp_client.consultar_termos_contrato("12345678000199", 2026, 10)
    assert resultado == [{"numeroTermo": 1}]


@respx.mock
async def test_consultar_termos_contrato_aceita_retorno_envelopado_em_content():
    respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/contratos/2026/10/termos"
    ).mock(return_value=httpx.Response(200, json={"content": [{"numeroTermo": 2}]}))
    resultado = await pncp_client.consultar_termos_contrato("12345678000199", 2026, 10)
    assert resultado == [{"numeroTermo": 2}]


@respx.mock
async def test_consultar_termos_contrato_retorno_dict_sem_data_nem_content_e_lista_vazia():
    respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/contratos/2026/10/termos"
    ).mock(return_value=httpx.Response(200, json={"outraCoisa": True}))
    resultado = await pncp_client.consultar_termos_contrato("12345678000199", 2026, 10)
    assert resultado == []


@respx.mock
async def test_consultar_empenhos_contrato_monta_path_e_parametros():
    route = respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/contratos/2026/10/empenhos"
    ).mock(return_value=httpx.Response(200, json={"data": [{"numeroEmpenho": "2026NE1"}]}))
    resultado = await pncp_client.consultar_empenhos_contrato("12345678000199", 2026, 10)
    assert resultado == [{"numeroEmpenho": "2026NE1"}]
    assert route.called


@respx.mock
async def test_consultar_empenhos_contrato_aceita_retorno_em_lista_simples():
    respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/contratos/2026/10/empenhos"
    ).mock(return_value=httpx.Response(200, json=[{"numeroEmpenho": "2026NE2"}]))
    resultado = await pncp_client.consultar_empenhos_contrato("12345678000199", 2026, 10)
    assert resultado == [{"numeroEmpenho": "2026NE2"}]


@respx.mock
async def test_consultar_instrumentos_cobranca_periodo_monta_parametros():
    route = respx.get(
        f"{settings.pncp_consulta_base_url}/v1/instrumentoscobranca/inclusao"
    ).mock(return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0}))
    await pncp_client.consultar_instrumentos_cobranca_periodo(
        data_inicial="20260101", data_final="20260107", cnpj_orgao="12345678000199",
        tipo_instrumento_cobranca=1,
    )
    params = route.calls.last.request.url.params
    assert params["dataInicial"] == "20260101"
    assert params["dataFinal"] == "20260107"
    assert params["cnpjOrgao"] == "12345678000199"
    assert params["tipoInstrumentoCobranca"] == "1"
    assert params["pagina"] == "1"


@respx.mock
async def test_consultar_instrumentos_cobranca_periodo_limita_tamanho_pagina_a_100():
    route = respx.get(
        f"{settings.pncp_consulta_base_url}/v1/instrumentoscobranca/inclusao"
    ).mock(return_value=httpx.Response(200, json={"data": [], "totalRegistros": 0}))
    await pncp_client.consultar_instrumentos_cobranca_periodo(
        data_inicial="20260101", data_final="20260107", tamanho_pagina=9999,
    )
    assert route.calls.last.request.url.params["tamanhoPagina"] == "100"


@respx.mock
async def test_consultar_instrumentos_cobranca_contrato_monta_path_e_parametros():
    route = respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/contratos/2026/10/instrumentocobranca"
    ).mock(return_value=httpx.Response(200, json={"data": [{"numero": "1"}]}))
    resultado = await pncp_client.consultar_instrumentos_cobranca_contrato(
        "12345678000199", 2026, 10
    )
    assert resultado == [{"numero": "1"}]
    assert route.calls.last.request.url.params["pagina"] == "1"


@respx.mock
async def test_consultar_instrumentos_cobranca_contrato_aceita_retorno_em_lista_simples():
    respx.get(
        f"{settings.pncp_pncp_base_url}/v1/orgaos/12345678000199/contratos/2026/10/instrumentocobranca"
    ).mock(return_value=httpx.Response(200, json=[{"numero": "2"}]))
    resultado = await pncp_client.consultar_instrumentos_cobranca_contrato(
        "12345678000199", 2026, 10
    )
    assert resultado == [{"numero": "2"}]
