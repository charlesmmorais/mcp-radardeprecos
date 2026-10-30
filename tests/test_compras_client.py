"""Testes do cliente Compras.gov.br (reservado para fases futuras) com HTTP mockado."""
from __future__ import annotations

import httpx
import respx

from mcp_radardeprecos.clients import compras_client
from mcp_radardeprecos.config import settings


@respx.mock
async def test_consultar_contratacoes_lei14133_monta_parametros():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-contratacoes/1_consultarContratacoes_PNCP_14133"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))
    resultado = await compras_client.consultar_contratacoes_lei14133(
        data_publicacao_pncp_inicial="2026-06-01",
        data_publicacao_pncp_final="2026-06-30",
        codigo_modalidade=6,
    )
    assert resultado == {"resultado": [], "totalRegistros": 0}
    params = route.calls.last.request.url.params
    assert params["codigoModalidade"] == "6"
    assert params["tamanhoPagina"] == "10"


@respx.mock
async def test_consultar_contratos_impoe_minimo_de_tamanho_pagina():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-contratos/1_consultarContratos"
    ).mock(return_value=httpx.Response(200, json={"resultado": []}))
    await compras_client.consultar_contratos(
        codigo_orgao="26290",
        data_vigencia_inicial_min="2026-01-01",
        data_vigencia_inicial_max="2026-06-30",
        tamanho_pagina=1,
    )
    assert route.calls.last.request.url.params["tamanhoPagina"] == "10"


@respx.mock
async def test_consultar_contratos_monta_todos_os_parametros():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-contratos/1_consultarContratos"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))
    resultado = await compras_client.consultar_contratos(
        codigo_orgao="25201",
        data_vigencia_inicial_min="2025-08-01",
        data_vigencia_inicial_max="2026-07-01",
        codigo_unidade_gestora="179087",
        codigo_unidade_gestora_origem_contrato="179087",
        codigo_unidade_realizadora_compra="179087",
        codigo_modalidade_compra="07",
        codigo_tipo="50",
        codigo_categoria="60",
        ni_fornecedor="62070115000100",
        numero_contrato="01046/2025",
    )
    assert resultado == {"resultado": [], "totalRegistros": 0}
    params = route.calls.last.request.url.params
    assert params["codigoOrgao"] == "25201"
    assert params["codigoUnidadeGestora"] == "179087"
    assert params["codigoUnidadeGestoraOrigemContrato"] == "179087"
    assert params["codigoUnidadeRealizadoraCompra"] == "179087"
    assert params["codigoModalidadeCompra"] == "07"
    assert params["codigoTipo"] == "50"
    assert params["codigoCategoria"] == "60"
    assert params["niFornecedor"] == "62070115000100"
    assert params["numeroContrato"] == "01046/2025"
    assert params["dataVigenciaInicialMin"] == "2025-08-01"
    assert params["dataVigenciaInicialMax"] == "2026-07-01"


@respx.mock
async def test_consultar_precos_servico_repassa_tamanho_pagina():
    # Achado real (2026-07-10): /modulo-pesquisa-preco/3_consultarServico
    # ACEITA tamanhoPagina — corrige suposição anterior deste projeto (a
    # função não repassava esse parâmetro). Confirmado ao vivo com
    # codigoItemCatalogo=27332/tamanhoPagina=100 devolvendo ~100 registros.
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-pesquisa-preco/3_consultarServico"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))
    resultado = await compras_client.consultar_precos_servico(
        27332, tamanho_pagina=100
    )
    assert resultado == {"resultado": [], "totalRegistros": 0}
    params = route.calls.last.request.url.params
    assert params["codigoItemCatalogo"] == "27332"
    assert params["tamanhoPagina"] == "100"


@respx.mock
async def test_consultar_precos_servico_impoe_minimo_de_tamanho_pagina():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-pesquisa-preco/3_consultarServico"
    ).mock(return_value=httpx.Response(200, json={"resultado": []}))
    await compras_client.consultar_precos_servico(27332, tamanho_pagina=1)
    assert route.calls.last.request.url.params["tamanhoPagina"] == "10"


@respx.mock
async def test_consultar_contratos_itens_monta_parametros():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-contratos/2_consultarContratosItem"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))
    resultado = await compras_client.consultar_contratos_itens(
        codigo_orgao=25201,
        data_vigencia_inicial_min="2025-08-01",
        data_vigencia_inicial_max="2026-07-01",
        codigo_item=365121,
    )
    assert resultado == {"resultado": [], "totalRegistros": 0}
    params = route.calls.last.request.url.params
    assert params["codigoOrgao"] == "25201"
    assert params["codigoItem"] == "365121"
    assert params["dataVigenciaInicialMin"] == "2025-08-01"
    assert params["dataVigenciaInicialMax"] == "2026-07-01"
    assert params["tamanhoPagina"] == "10"


@respx.mock
async def test_listar_grupos_material_devolve_lista_e_usa_cache():
    from mcp_radardeprecos.utils import cache

    cache.clear()
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-material/1_consultarGrupoMaterial"
    ).mock(
        return_value=httpx.Response(
            200, json={"resultado": [{"codigoGrupo": 70, "nomeGrupo": "INFORMÁTICA"}]}
        )
    )
    primeira = await compras_client.listar_grupos_material()
    segunda = await compras_client.listar_grupos_material()
    assert primeira == [{"codigoGrupo": 70, "nomeGrupo": "INFORMÁTICA"}]
    assert segunda == primeira
    assert route.call_count == 1


@respx.mock
async def test_listar_classes_material_devolve_lista():
    respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-material/2_consultarClasseMaterial"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"resultado": [{"codigoClasse": 7010, "nomeClasse": "COMPUTADORES"}]},
        )
    )
    resultado = await compras_client.listar_classes_material()
    assert resultado == [{"codigoClasse": 7010, "nomeClasse": "COMPUTADORES"}]


@respx.mock
async def test_listar_classes_servico_devolve_lista():
    respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-servico/4_consultarClasseServico"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "resultado": [
                    {
                        "codigoGrupo": 111,
                        "nomeGrupo": "SERVIÇOS DE DESENVOLVIMENTO DE SOFTWARE",
                        "codigoClasse": 1111,
                        "nomeClasse": "DESENVOLVIMENTO DE SOFTWARE",
                    }
                ]
            },
        )
    )
    resultado = await compras_client.listar_classes_servico()
    assert resultado[0]["nomeClasse"] == "DESENVOLVIMENTO DE SOFTWARE"


@respx.mock
async def test_listar_pdms_material_ativos_pagina_por_grupo_e_cacheia():
    # v0.3.12: para contornar o teto de offset (~10k) da API, a listagem de
    # PDMs pagina POR GRUPO (filtro codigoGrupo). Confirma que chama o
    # endpoint de grupos primeiro, depois PDMs por grupo, agrega e cacheia.
    from mcp_radardeprecos.utils import cache

    cache.clear()
    respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-material/1_consultarGrupoMaterial"
    ).mock(
        return_value=httpx.Response(
            200, json={"resultado": [{"codigoGrupo": 70}, {"codigoGrupo": 75}]}
        )
    )
    pdm_por_grupo = {
        "70": {"resultado": [{"codigoPdm": 8435, "nomePdm": "NOTEBOOK"}], "totalPaginas": 1},
        "75": {"resultado": [{"codigoPdm": 281, "nomePdm": "CARTUCHO CANETA TINTEIRO"}], "totalPaginas": 1},
    }

    def _responder(request):
        grupo = request.url.params.get("codigoGrupo")
        return httpx.Response(200, json=pdm_por_grupo[grupo])

    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-material/3_consultarPdmMaterial"
    ).mock(side_effect=_responder)

    resultado = await compras_client.listar_pdms_material_ativos()
    nomes = {p["nomePdm"] for p in resultado}
    assert nomes == {"NOTEBOOK", "CARTUCHO CANETA TINTEIRO"}
    assert route.call_count == 2  # uma varredura por grupo
    # o filtro por grupo deve estar presente (é o que evita o teto de offset)
    assert all(c.request.url.params.get("codigoGrupo") for c in route.calls)

    # segunda chamada vem do cache agregado, sem nova requisição
    resultado2 = await compras_client.listar_pdms_material_ativos()
    assert resultado2 == resultado
    assert route.call_count == 2


@respx.mock
async def test_consultar_precos_material_usa_tipo_e_codigo():
    # Regressão do drift confirmado ao vivo 2026-07-28: o endpoint
    # de preço de MATERIAL trocou codigoItemCatalogo (int) por tipo (enum) +
    # codigo. Com o parâmetro antigo, a API passou a devolver HTTP 404.
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-pesquisa-preco/1_consultarMaterial"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))

    await compras_client.consultar_precos_material(393604)
    params = route.calls.last.request.url.params
    assert params["tipo"] == "codigoItemCatalogo"
    assert params["codigo"] == "393604"
    assert "codigoItemCatalogo" not in params  # parâmetro antigo não é mais enviado

    # e permite buscar por PDM
    await compras_client.consultar_precos_material(8435, tipo_codigo="codigoPdm")
    params2 = route.calls.last.request.url.params
    assert params2["tipo"] == "codigoPdm"
    assert params2["codigo"] == "8435"


@respx.mock
async def test_listar_itens_material_por_pdm_monta_parametros():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-material/4_consultarItemMaterial"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"resultado": [{"codigoItem": 8435001, "descricaoItem": "NOTEBOOK, NOME: X"}]},
        )
    )
    # tamanho_pagina=5 é pedido, mas a v0.1.32 corrigiu o clamp para
    # max(10, min(tamanho_pagina, 500)) — o endpoint rejeita valores abaixo
    # de 10 com HTTP 400 (bug real, confirmado ao vivo).
    resultado = await compras_client.listar_itens_material_por_pdm(8435, tamanho_pagina=5)
    assert resultado["resultado"][0]["codigoItem"] == 8435001
    params = route.calls.last.request.url.params
    assert params["codigoPdm"] == "8435"
    assert params["tamanhoPagina"] == "10"
    assert params["statusItem"] == "true"


@respx.mock
async def test_listar_itens_material_por_pdm_nao_deixa_passar_tamanho_abaixo_de_10():
    respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-material/4_consultarItemMaterial"
    ).mock(return_value=httpx.Response(200, json={"resultado": []}))
    for tamanho in (1, 5, 9):
        await compras_client.listar_itens_material_por_pdm(8435, tamanho_pagina=tamanho)
        ultima_chamada = respx.calls.last
        assert ultima_chamada.request.url.params["tamanhoPagina"] == "10"


@respx.mock
async def test_listar_itens_servico_por_classe_monta_parametros():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-servico/6_consultarItemServico"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"resultado": [{"codigoServico": 25917, "nomeServico": "DESENVOLVIMENTO DE SOFTWARE"}]},
        )
    )
    # Mesma correção de clamp que listar_itens_material_por_pdm.
    resultado = await compras_client.listar_itens_servico_por_classe(1111, tamanho_pagina=5)
    assert resultado["resultado"][0]["codigoServico"] == 25917
    params = route.calls.last.request.url.params
    assert params["codigoClasse"] == "1111"
    assert params["tamanhoPagina"] == "10"
    assert params["statusServico"] == "true"


@respx.mock
async def test_consultar_fornecedor_monta_parametros_com_cnpj_e_ativo():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-fornecedor/1_consultarFornecedor"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"resultado": [{"cnpj": "05340845000140", "habilitadoLicitar": True}]},
        )
    )
    resultado = await compras_client.consultar_fornecedor(ativo=True, cnpj="05340845000140")
    assert resultado["resultado"][0]["habilitadoLicitar"] is True
    params = route.calls.last.request.url.params
    assert params["cnpj"] == "05340845000140"
    assert params["ativo"] == "true"
    assert "cpf" not in params


@respx.mock
async def test_consultar_fornecedor_aceita_ativo_false_e_cpf():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-fornecedor/1_consultarFornecedor"
    ).mock(return_value=httpx.Response(200, json={"resultado": []}))
    await compras_client.consultar_fornecedor(ativo=False, cpf="12345678901")
    params = route.calls.last.request.url.params
    assert params["ativo"] == "false"
    assert params["cpf"] == "12345678901"
    assert "cnpj" not in params


@respx.mock
async def test_consultar_fornecedor_impoe_minimo_de_tamanho_pagina():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-fornecedor/1_consultarFornecedor"
    ).mock(return_value=httpx.Response(200, json={"resultado": []}))
    await compras_client.consultar_fornecedor(ativo=True, cnpj="05340845000140", tamanho_pagina=1)
    assert route.calls.last.request.url.params["tamanhoPagina"] == "10"


@respx.mock
async def test_consultar_uasg_monta_parametros_e_nao_envia_tamanho_pagina():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-uasg/1_consultarUasg"
    ).mock(
        return_value=httpx.Response(
            200, json={"resultado": [{"codigoUasg": "030204", "nomeUasg": "TCU"}]}
        )
    )
    resultado = await compras_client.consultar_uasg(status_uasg=True, sigla_uf="DF")
    assert resultado["resultado"][0]["codigoUasg"] == "030204"
    params = route.calls.last.request.url.params
    assert params["statusUasg"] == "true"
    assert params["siglaUf"] == "DF"
    assert "tamanhoPagina" not in params


@respx.mock
async def test_consultar_orgao_monta_parametros_sem_uf():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-uasg/2_consultarOrgao"
    ).mock(
        return_value=httpx.Response(
            200, json={"resultado": [{"codigoOrgao": 3000, "nomeOrgao": "TCU"}]}
        )
    )
    resultado = await compras_client.consultar_orgao(status_orgao=True)
    assert resultado["resultado"][0]["codigoOrgao"] == 3000
    params = route.calls.last.request.url.params
    assert params["statusOrgao"] == "true"
    assert "siglaUf" not in params
    assert "tamanhoPagina" not in params


@respx.mock
async def test_listar_uasgs_ativas_pagina_ate_esgotar_e_cacheia():
    from mcp_radardeprecos.utils import cache

    cache.clear()
    pagina1 = {"resultado": [{"codigoUasg": "1", "nomeUasg": "A"}], "totalPaginas": 2}
    pagina2 = {"resultado": [{"codigoUasg": "2", "nomeUasg": "B"}], "totalPaginas": 2}
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-uasg/1_consultarUasg"
    ).mock(
        side_effect=[
            httpx.Response(200, json=pagina1),
            httpx.Response(200, json=pagina2),
        ]
    )

    resultado = await compras_client.listar_uasgs_ativas(sigla_uf="SP")
    assert len(resultado) == 2
    assert route.call_count == 2

    resultado2 = await compras_client.listar_uasgs_ativas(sigla_uf="SP")
    assert resultado2 == resultado
    assert route.call_count == 2


@respx.mock
async def test_listar_uasgs_ativas_cacheia_separado_por_uf():
    from mcp_radardeprecos.utils import cache

    cache.clear()
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-uasg/1_consultarUasg"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalPaginas": 1}))

    await compras_client.listar_uasgs_ativas(sigla_uf="SP")
    await compras_client.listar_uasgs_ativas(sigla_uf="RJ")
    assert route.call_count == 2

    params_chamadas = [c.request.url.params["siglaUf"] for c in route.calls]
    assert params_chamadas == ["SP", "RJ"]


@respx.mock
async def test_listar_orgaos_ativos_pagina_ate_esgotar_e_cacheia():
    from mcp_radardeprecos.utils import cache

    cache.clear()
    pagina1 = {"resultado": [{"codigoOrgao": 1, "nomeOrgao": "A"}], "totalPaginas": 2}
    pagina2 = {"resultado": [{"codigoOrgao": 2, "nomeOrgao": "B"}], "totalPaginas": 2}
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-uasg/2_consultarOrgao"
    ).mock(
        side_effect=[
            httpx.Response(200, json=pagina1),
            httpx.Response(200, json=pagina2),
        ]
    )

    resultado = await compras_client.listar_orgaos_ativos()
    assert len(resultado) == 2
    assert route.call_count == 2

    resultado2 = await compras_client.listar_orgaos_ativos()
    assert resultado2 == resultado
    assert route.call_count == 2


@respx.mock
async def test_consultar_contratos_fim_vigencia_monta_parametros():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-contratos/1.2_consultarContratos_FimVigencia"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))
    resultado = await compras_client.consultar_contratos_fim_vigencia(
        codigo_orgao="25201",
        data_vigencia_final_min="2026-07-01",
        data_vigencia_final_max="2026-09-30",
        codigo_unidade_gestora="179087",
    )
    assert resultado == {"resultado": [], "totalRegistros": 0}
    params = route.calls.last.request.url.params
    assert params["codigoOrgao"] == "25201"
    assert params["dataVigenciaFinalMin"] == "2026-07-01"
    assert params["dataVigenciaFinalMax"] == "2026-09-30"
    assert params["codigoUnidadeGestora"] == "179087"


@respx.mock
async def test_consultar_contratos_fim_vigencia_impoe_minimo_de_tamanho_pagina():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-contratos/1.2_consultarContratos_FimVigencia"
    ).mock(return_value=httpx.Response(200, json={"resultado": []}))
    await compras_client.consultar_contratos_fim_vigencia(
        codigo_orgao="25201",
        data_vigencia_final_min="2026-07-01",
        data_vigencia_final_max="2026-09-30",
        tamanho_pagina=1,
    )
    assert route.calls.last.request.url.params["tamanhoPagina"] == "10"


@respx.mock
async def test_consultar_arp_fim_vigencia_monta_parametros_com_unidade_gerenciadora_opcional():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-arp/1.2_consultarARP_FimVigencia"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))
    resultado = await compras_client.consultar_arp_fim_vigencia(
        data_vigencia_final_min="2026-07-01",
        data_vigencia_final_max="2026-09-30",
    )
    assert resultado == {"resultado": [], "totalRegistros": 0}
    params = route.calls.last.request.url.params
    assert params["dataVigenciaFinalMin"] == "2026-07-01"
    assert params["dataVigenciaFinalMax"] == "2026-09-30"
    # Diferente de consultar_contratos_fim_vigencia, codigo_unidade_gerenciadora
    # é opcional aqui — não deve ser enviado quando omitido.
    assert "codigoUnidadeGerenciadora" not in params


@respx.mock
async def test_consultar_arp_fim_vigencia_aceita_unidade_gerenciadora_e_numero_ata():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-arp/1.2_consultarARP_FimVigencia"
    ).mock(return_value=httpx.Response(200, json={"resultado": []}))
    await compras_client.consultar_arp_fim_vigencia(
        data_vigencia_final_min="2026-07-01",
        data_vigencia_final_max="2026-09-30",
        codigo_unidade_gerenciadora="179087",
        numero_ata_registro_preco="001/2026",
    )
    params = route.calls.last.request.url.params
    assert params["codigoUnidadeGerenciadora"] == "179087"
    assert params["numeroAtaRegistroPreco"] == "001/2026"


# navegação hierárquica completa do CATSER
# (seção/divisão/grupo/subclasse — classe já existia desde a v0.1.12).


@respx.mock
async def test_listar_secoes_servico_devolve_lista_e_usa_cache():
    from mcp_radardeprecos.utils import cache

    cache.clear()
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-servico/1_consultarSecaoServico"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"resultado": [{"codigoSecao": 1, "nomeSecao": "SERVIÇOS DE TIC"}]},
        )
    )
    primeira = await compras_client.listar_secoes_servico()
    segunda = await compras_client.listar_secoes_servico()
    assert primeira == [{"codigoSecao": 1, "nomeSecao": "SERVIÇOS DE TIC"}]
    assert segunda == primeira
    assert route.call_count == 1


@respx.mock
async def test_listar_divisoes_servico_sem_filtro_nao_envia_codigo_secao():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-servico/2_consultarDivisaoServico"
    ).mock(return_value=httpx.Response(200, json={"resultado": []}))
    await compras_client.listar_divisoes_servico()
    assert "codigoSecao" not in route.calls.last.request.url.params


@respx.mock
async def test_listar_divisoes_servico_filtra_por_codigo_secao():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-servico/2_consultarDivisaoServico"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"resultado": [{"codigoSecao": 1, "codigoDivisao": 11, "nomeDivisao": "SOFTWARE"}]},
        )
    )
    resultado = await compras_client.listar_divisoes_servico(1)
    assert resultado[0]["nomeDivisao"] == "SOFTWARE"
    assert route.calls.last.request.url.params["codigoSecao"] == "1"


@respx.mock
async def test_listar_grupos_servico_sem_filtro_cacheia():
    from mcp_radardeprecos.utils import cache

    cache.clear()
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-servico/3_consultarGrupoServico"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"resultado": [{"codigoDivisao": 11, "codigoGrupo": 111, "nomeGrupo": "SOFTWARE"}]},
        )
    )
    primeira = await compras_client.listar_grupos_servico()
    segunda = await compras_client.listar_grupos_servico()
    assert primeira == segunda
    assert route.call_count == 1


@respx.mock
async def test_listar_grupos_servico_com_filtro_nao_cacheia():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-servico/3_consultarGrupoServico"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"resultado": [{"codigoDivisao": 11, "codigoGrupo": 111, "nomeGrupo": "SOFTWARE"}]},
        )
    )
    await compras_client.listar_grupos_servico(11)
    await compras_client.listar_grupos_servico(11)
    assert route.call_count == 2
    assert route.calls.last.request.url.params["codigoDivisao"] == "11"


@respx.mock
async def test_listar_subclasses_servico_exige_codigo_classe_no_parametro():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-servico/5_consultarSubClasseServico"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "resultado": [
                    {"codigoClasse": 1111, "codigoSubclasse": 11111, "nomeSubclasse": "SOB DEMANDA"}
                ]
            },
        )
    )
    resultado = await compras_client.listar_subclasses_servico(1111)
    assert resultado[0]["nomeSubclasse"] == "SOB DEMANDA"
    assert route.calls.last.request.url.params["codigoClasse"] == "1111"


@respx.mock
async def test_listar_subclasses_servico_lista_vazia_e_normal():
    respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-servico/5_consultarSubClasseServico"
    ).mock(return_value=httpx.Response(200, json={"resultado": []}))
    resultado = await compras_client.listar_subclasses_servico(9999)
    assert resultado == []


@respx.mock
async def test_contratacoes_14133_exclui_desconsideradas_por_padrao():
    """Regressão do defeito medido em 05/09/2026.

    Sem ``contratacaoExcluida``, a API devolve as contratações
    desconsideradas junto das válidas: 980 sem o filtro, 978 com ``false``,
    2 com ``true``, na mesma janela. O padrão passou a ser ``false``.

    O teste é sobre um valor **falsy** numa query string — se algum dia a
    limpeza de parâmetros passar a descartar valores falsy, o filtro some em
    silêncio e o defeito volta sem quebrar nada mais.
    """
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-contratacoes/1_consultarContratacoes_PNCP_14133"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))
    await compras_client.consultar_contratacoes_lei14133(
        data_publicacao_pncp_inicial="2026-08-01",
        data_publicacao_pncp_final="2026-08-05",
        codigo_modalidade=6,
    )
    assert route.calls.last.request.url.params["contratacaoExcluida"] == "false"


@respx.mock
async def test_contratacoes_14133_permite_pedir_so_as_excluidas():
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-contratacoes/1_consultarContratacoes_PNCP_14133"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))
    await compras_client.consultar_contratacoes_lei14133(
        data_publicacao_pncp_inicial="2026-08-01",
        data_publicacao_pncp_final="2026-08-05",
        codigo_modalidade=6,
        contratacao_excluida=True,
    )
    assert route.calls.last.request.url.params["contratacaoExcluida"] == "true"


@respx.mock
async def test_contratacoes_14133_none_omite_o_filtro():
    """``None`` reproduz o comportamento anterior — as duas misturadas."""
    route = respx.get(
        f"{settings.compras_dadosabertos_base_url}/modulo-contratacoes/1_consultarContratacoes_PNCP_14133"
    ).mock(return_value=httpx.Response(200, json={"resultado": [], "totalRegistros": 0}))
    await compras_client.consultar_contratacoes_lei14133(
        data_publicacao_pncp_inicial="2026-08-01",
        data_publicacao_pncp_final="2026-08-05",
        codigo_modalidade=6,
        contratacao_excluida=None,
    )
    assert "contratacaoExcluida" not in route.calls.last.request.url.params
