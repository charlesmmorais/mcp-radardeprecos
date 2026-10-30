"""Smoke tests AO VIVO contra as APIs reais (PNCP e Compras.gov.br) — marker ``live``.

**Excluídos da rodada padrão** (``addopts = -m "not live"`` no
``pyproject.toml``): todo o resto da suíte é mockado com ``respx`` e valida
que o código monta as chamadas como *pretendido* — o que, como o README
documenta, não pega drift silencioso da API real (o bug ``uf``/``ufs`` tinha
teste passando e só foi descoberto contra o site ao vivo). Estes testes
fecham essa lacuna: chamadas reais, poucas e leves, com **asserções fracas**
(status de sucesso, campos-chave presentes, invariantes grosseiras) — o
objetivo é detectar mudança de contrato/comportamento upstream, não validar
valores exatos, que mudam a cada edital publicado.

Como rodar:

    pytest -m live

No CI, rodam semanalmente (``.github/workflows/live-smoke.yml``, cron +
disparo manual) — uma falha aqui significa "a API upstream mudou/está fora",
não necessariamente um bug deste projeto; investigue antes de 'corrigir'.

Notas de estabilidade das escolhas:
- ``"notebook"`` como termo: 20k+ documentos no índice (confirmado ao vivo
  2026-07-08) — não vai zerar.
- CATMAT 27332 (guardanapo de papel): 100+ registros de preço praticado
  (confirmado ao vivo 2026-07-10 e 2026-07-11) — item de expediente comum,
  não deve sumir do catálogo.
- Grupos de material CATMAT: lista completa tem 79 grupos (estável há anos);
  asserção fraca em ">= 50".
"""
from __future__ import annotations

import pytest

from mcp_radardeprecos.clients import compras_client, pncp_client
from mcp_radardeprecos.tools.buscar_precos_praticados_compras import (
    buscar_precos_praticados_compras,
)
from mcp_radardeprecos.tools.listar_filtros_pncp import listar_filtros_pncp

pytestmark = pytest.mark.live


# --- asserção nos CAMPOS DE PREÇO ----------
#
# As asserções fracas de "campo presente" não pegam o pior drift possível: um
# campo de valor renomeado silenciosamente pelo upstream, que faz o preço
# sumir/virar None sem quebrar nada — a mesma classe do bug uf/ufs, só que
# devolvendo preço ERRADO em vez de resultado errado. Estes helpers exigem que
# o valor unitário exista, seja numérico e > 0 num registro real das tools que
# carregam preço.


def _valor_monetario_valido(v: object) -> bool:
    """True se ``v`` puder ser lido como número > 0 (tolerante a str/vírgula)."""
    if v is None:
        return False
    try:
        return float(str(v).replace(",", ".")) > 0
    except (TypeError, ValueError):
        return False


def _algum_valor_positivo(registro: dict) -> bool:
    """True se algum campo cujo nome contém 'valor'/'preco' for número > 0.

    Tolerante ao nome exato do campo — usado onde os registros vêm CRUS da API
    (ex.: buscar_homologados_14133), para o teste vigiar 'todo campo de preço
    sumiu' sem depender do nome exato, que pode variar entre versões da fonte.
    """
    for chave, valor in registro.items():
        nome = chave.lower()
        if ("valor" in nome or "preco" in nome or "preço" in nome) and _valor_monetario_valido(valor):
            return True
    return False


async def test_live_pncp_busca_textual_retorna_itens_com_campos_chave():
    resultado = await pncp_client.buscar_texto(
        "notebook", "edital", pagina=1, tamanho_pagina=10
    )
    assert resultado.get("total", 0) > 0
    items = resultado.get("items", [])
    assert items, "índice do PNCP não retornou nenhum item para 'notebook'"
    primeiro = items[0]
    # Campos dos quais as tools dependem estruturalmente (dedup, janela
    # temporal, links construídos localmente):
    assert primeiro.get("numero_controle_pncp")
    assert primeiro.get("data_publicacao_pncp")
    assert pncp_client.parse_numero_controle_pncp(primeiro["numero_controle_pncp"])


async def test_live_pncp_filtro_uf_realmente_filtra():
    # Regressão VIVA do bug uf/ufs (v0.1.x): o parâmetro errado era
    # silenciosamente ignorado e a busca vinha sem filtro nenhum. Se o
    # contrato do backend mudar de novo, o total filtrado deixa de ser
    # estritamente menor que o geral.
    geral = await pncp_client.buscar_texto("notebook", "edital", pagina=1, tamanho_pagina=1)
    sp = await pncp_client.buscar_texto(
        "notebook", "edital", uf="SP", pagina=1, tamanho_pagina=1
    )
    assert geral.get("total", 0) > 0
    assert 0 < sp.get("total", 0) < geral["total"]


async def test_live_pncp_paginacao_pagina_1_e_2_nao_repetem_os_mesmos_itens():
    # Relato de campo (2026-07-16): um agente que chamou pagina=1 e depois
    # pagina=2 recebeu exatamente o mesmo conjunto de IDs — suspeita de bug
    # de paginação em /api/search (não confirmado ao vivo no ambiente de
    # implementação, sem acesso de rede). Este teste vigia especificamente
    # essa regressão: se `pagina` deixar de ser respeitada pelo backend (ou
    # for silenciosamente ignorada/cacheada), as duas páginas voltam a
    # trazer o mesmo conjunto de itens — mesma classe do bug uf/ufs.
    pagina_1 = await pncp_client.buscar_texto("notebook", "edital", pagina=1, tamanho_pagina=50)
    pagina_2 = await pncp_client.buscar_texto("notebook", "edital", pagina=2, tamanho_pagina=50)

    ids_1 = {i.get("numero_controle_pncp") for i in pagina_1.get("items", [])}
    ids_2 = {i.get("numero_controle_pncp") for i in pagina_2.get("items", [])}
    assert ids_1, "página 1 não devolveu itens"
    assert ids_2, "página 2 não devolveu itens"
    assert ids_1 != ids_2, (
        "pagina=1 e pagina=2 devolveram exatamente o mesmo conjunto de "
        "numero_controle_pncp — parâmetro `pagina` possivelmente ignorado "
        "ou cacheado no backend do PNCP (relato de campo 2026-07-16)"
    )


async def test_live_pncp_facetas_de_filtro_disponiveis():
    resultado = await listar_filtros_pncp("edital", campo="modalidades")
    modalidades = resultado.get("modalidades") or []
    assert modalidades, "faceta 'modalidades' vazia no /api/search/filters"
    assert modalidades[0].get("id") is not None


async def test_live_pncp_itens_de_uma_contratacao_real():
    # Pega uma contratação com resultado no índice e busca os itens dela na
    # API de Consulta — o pivô central de buscar_contratacoes_pncp.
    busca = await pncp_client.buscar_texto("notebook", "edital", pagina=1, tamanho_pagina=10)
    com_resultado = [i for i in busca.get("items", []) if i.get("tem_resultado")]
    if not com_resultado:
        pytest.skip("nenhuma contratação com resultado na primeira página do índice")
    parsed = pncp_client.parse_numero_controle_pncp(
        com_resultado[0]["numero_controle_pncp"]
    )
    assert parsed
    cnpj, ano, sequencial = parsed
    itens = await pncp_client.consultar_itens_contratacao(cnpj, ano, sequencial)
    assert isinstance(itens, list)
    if itens:  # contratação real pode (raramente) não ter itens publicados
        assert "valorUnitarioEstimado" in itens[0]
        # valor unitário não pode virar None silenciosamente.
        assert _valor_monetario_valido(itens[0].get("valorUnitarioEstimado")), (
            "valorUnitarioEstimado presente mas não é número > 0 — possível "
            "drift do campo de preço na API de Consulta do PNCP"
        )


async def test_live_compras_grupos_material_catalogo_estavel():
    grupos = await compras_client.listar_grupos_material()
    assert len(grupos) >= 50  # lista completa tem 79; fraco de propósito


async def test_live_compras_precos_praticados_material_novo_contrato():
    # Regressão do drift confirmado ao vivo 2026-07-28: o endpoint
    # de preço de MATERIAL trocou o obrigatório codigoItemCatalogo (int) por
    # tipo (enum "codigoItemCatalogo"/"codigoPdm") + codigo. Com o parâmetro
    # antigo, a API passou a devolver HTTP 404 → a tool levantaria
    # UpstreamError. Este teste chama a tool com um código de item ATUAL
    # (393604, confirmado no catálogo vivo) e exige que o NOVO contrato seja
    # aceito (envelope válido, sem erro). O código 27332 usado antes virou
    # código morto (404) — não confundir "código migrado" com "drift".
    resultado = await buscar_precos_praticados_compras(
        codigo_item_catalogo=393604, tipo_item="material",
        apenas_com_resultado=False, limite=5,
    )
    assert isinstance(resultado["total_encontrado"], int)
    assert resultado["total_encontrado"] >= 0  # 0 é válido; o que importa é NÃO ter erro
    # Se houver preços, o campo de valor deve ser numérico > 0.
    if resultado["precos"]:
        assert _valor_monetario_valido(resultado["precos"][0].get("preco_unitario"))


async def test_live_descobrir_codigo_catalogo_material_completa_sem_erro():
    # Regressão do drift confirmado ao vivo 2026-07-28: a API passou
    # a limitar o offset de paginação a ~10k; como há 15.020 PDMs, a varredura
    # linear a 1000/página estourava HTTP 400 na 11ª página, quebrando
    # descobrir_codigo_catalogo para QUALQUER termo de material. A correção
    # pagina por grupo. Este teste exige que a busca material complete sem
    # erro e encontre o PDM NOTEBOOK.
    from mcp_radardeprecos.tools.descobrir_codigo_catalogo import (
        descobrir_codigo_catalogo,
    )

    resultado = await descobrir_codigo_catalogo("notebook", tipo_item="material")
    assert resultado["tipo_item"] == "material"
    nomes = " ".join(
        str(r.get("nome_pdm", "")) for r in resultado.get("resultados", [])
    ).lower()
    assert "notebook" in nomes, (
        "descobrir material não encontrou o PDM NOTEBOOK — paginação por grupo "
        "quebrada ou catálogo mudou"
    )


async def test_live_itens_contrato_compras_valor_unitario_valido():
    # vigia o campo de preço unitário dos
    # itens de contrato (valor_unitario_item ← valorUnitarioItem). Órgão 25201
    # (o mesmo dos testes mockados) com janela ampla; skip se não houver itens
    # na janela (evita falso-negativo por ausência de dado, não por drift).
    from mcp_radardeprecos.tools.consultar_itens_contrato_compras import (
        consultar_itens_contrato_compras,
    )

    r = await consultar_itens_contrato_compras(
        codigo_orgao=25201,
        data_vigencia_inicial_min="2024-01-01",
        data_vigencia_inicial_max="2026-12-31",
        limite=10,
    )
    itens = r.get("itens") or r.get("registros") or []
    if not itens:
        pytest.skip("órgão 25201 sem itens de contrato na janela — nada a vigiar")
    assert any(_valor_monetario_valido(i.get("valor_unitario_item")) for i in itens), (
        "nenhum item de contrato tem valor_unitario_item > 0 — possível drift "
        "do campo de preço (valorUnitarioItem) no Compras.gov.br"
    )


async def test_live_bcb_serie_433_ipca_disponivel():
    from datetime import date, timedelta

    from mcp_radardeprecos.clients import bcb_client

    serie = await bcb_client.obter_ipca_mensal(date.today() - timedelta(days=180), date.today())
    assert serie, "série 433 do SGS/BCB não devolveu nenhum mês nos últimos 180 dias"
    assert all("competencia" in r and "variacao_percentual" in r for r in serie)


async def test_live_precos_filtro_de_data_no_servidor():
    # v0.2.1: dataCompraInicio/Fim vieram da spec oficial — este teste vigia
    # se o filtro funciona DE FATO (a spec já nos enganou antes: uf, descricaoItem).
    resultado = await buscar_precos_praticados_compras(
        codigo_item_catalogo=27332, tipo_item="material", limite=10,
        data_compra_inicio="2024-01-01", data_compra_fim="2026-12-31",
    )
    sem_filtro = await buscar_precos_praticados_compras(
        codigo_item_catalogo=27332, tipo_item="material", limite=10,
    )
    assert resultado["total_encontrado"] <= sem_filtro["total_encontrado"], (
        "filtro de data no servidor devolveu MAIS que a consulta sem filtro — "
        "parâmetro possivelmente ignorado (mesma classe do bug uf/ufs)"
    )


async def test_live_homologados_14133_responde():
    from datetime import date, timedelta

    from mcp_radardeprecos.tools.buscar_homologados_14133 import buscar_homologados_14133

    fim = date.today()
    inicio = fim - timedelta(days=30)
    r = await buscar_homologados_14133(
        inicio.isoformat(), fim.isoformat(), cnpj_orgao="00394460000141", limite=5
    )
    assert r["modo"] == "por_fornecedor_orgao"
    assert isinstance(r["registros"], list)  # asserção fraca: contrato responde
    # se vierem registros, ao menos um deve ter algum campo de
    # valor > 0 (registros são crus — nome do campo tolerante de propósito).
    if r["registros"]:
        assert any(_algum_valor_positivo(reg) for reg in r["registros"]), (
            "nenhum registro homologado tem campo de valor > 0 — possível "
            "drift do campo de preço nas contratações 14.133 (Compras.gov.br)"
        )


async def test_live_buscar_propostas_abertas_responde():
    # Vigia especificamente o formato de data_final não confirmado ao vivo
    # nesta versão (ver docstring de
    # pncp_client.consultar_contratacoes_proposta_aberta)
    # — se a API real exigir AAAA-MM-DD em vez de
    # AAAAMMDD, este teste deve falhar (erro HTTP, não silêncio).
    from mcp_radardeprecos.tools.buscar_propostas_abertas import buscar_propostas_abertas

    resultado = await buscar_propostas_abertas(dias_a_frente=30, limite=5)
    assert isinstance(resultado["propostas"], list)  # asserção fraca: contrato responde
    assert resultado["periodo"]["data_final"]
    assert any("ESTIMADOS" in a for a in resultado["avisos"])


async def test_live_radar_vencimentos_atas_fim_de_vigencia_responde():
    # Vigia os endpoints _FimVigencia do Compras.gov.br
    # e o complemento opcional de
    # pncp_client.consultar_atas_periodo (achado 3.3) juntos.
    from mcp_radardeprecos.tools.radar_vencimentos import radar_vencimentos

    resultado = await radar_vencimentos("atas", dias_a_frente=90, limite=5)
    assert isinstance(resultado["atas"], list)  # asserção fraca: contrato responde
    assert isinstance(resultado["atas_pncp_complemento"], list)
    assert resultado["periodo"]["data_fim_vigencia_fim"]


async def test_live_bcb_series_igpm_e_ipc_fipe_disponiveis():
    # Vigia a generalização de bcb_client: as
    # séries 189 (IGP-M) e 193 (IPC-Fipe) do SGS usam o mesmo endpoint/schema
    # da 433 (IPCA, já coberta acima) — asserção fraca de propósito.
    from datetime import date, timedelta

    from mcp_radardeprecos.clients import bcb_client

    inicio = date.today() - timedelta(days=180)
    fim = date.today()
    for codigo_serie in (189, 193):
        serie = await bcb_client.obter_indice_mensal(codigo_serie, inicio, fim)
        assert serie, f"série {codigo_serie} do SGS/BCB não devolveu nenhum mês nos últimos 180 dias"
        assert all("competencia" in r and "variacao_percentual" in r for r in serie)


async def test_live_atualizar_precos_indice_aceita_igpm_e_ipc_fipe():
    from mcp_radardeprecos.tools.atualizar_precos_indice import atualizar_precos_indice

    for indice in ("igpm", "ipc_fipe"):
        resultado = await atualizar_precos_indice(
            [{"valor": 100.0, "data": "2026-01"}], indice=indice,
        )
        assert resultado["indice_chave"] == indice
        assert resultado["precos_atualizados"][0]["valor_atualizado"] > 0


async def test_live_consultar_notas_fiscais_por_periodo_responde():
    # Vigia o schema não confirmado ao vivo de consultar_instrumentos_cobranca_periodo
    # (achado 3.1 item 1) — asserção fraca de propósito: o
    # objetivo é detectar erro HTTP/mudança de contrato, não validar
    # exaustivamente o schema de NF-e (que pode não aparecer numa janela curta).
    from datetime import date, timedelta

    from mcp_radardeprecos.tools.consultar_notas_fiscais import consultar_notas_fiscais

    fim = date.today()
    inicio = fim - timedelta(days=7)
    resultado = await consultar_notas_fiscais(
        data_inicio=inicio.strftime("%Y%m%d"), data_fim=fim.strftime("%Y%m%d"), limite=5,
    )
    assert resultado["modo"] == "por_periodo"
    assert isinstance(resultado["instrumentos_cobranca"], list)
    assert any("FATURADO" in a for a in resultado["avisos"])


# --- vigia de drift das tabelas de domínio ---
#
# O portal do PNCP expõe REST público para 5 das 15 tabelas hardcoded em
# domain.dominios.TABELAS_DOMINIO_PNCP (achado 4.4,
# a análise das specs oficiais) — usado aqui só como VIGIA (nenhuma tool
# muda de comportamento): uma falha sinaliza que o hardcode ficou
# desatualizado frente à fonte viva, risco admitido desde a v0.1.24.
#
# Nomes de campo exatos do JSON destes 5 endpoints NÃO foram confirmados ao
# vivo nesta versão (rede bloqueada no ambiente de implementação) — por
# isso `_extrair_codigo`/`_extrair_nome` tentam várias variantes plausíveis
# em vez de assumir uma única. Se a primeira rodada real (CI semanal)
# mostrar que nenhuma variante bate, ajuste as listas de candidatos aqui
# (não é um bug de tool, é o próprio propósito do teste sendo exercido).
_TABELAS_DOMINIO_ENDPOINTS: dict[str, str] = {
    "tipo_contrato": "/v1/tipos-contratos",
    "tipo_documento": "/v1/tipos-documentos",
    "instrumento_convocatorio": "/v1/tipos-instrumentos-convocatorios",
    "modo_disputa": "/v1/tipo-instrumento-convocatorio-modo-disputa",
}
# /v1/tipos-instrumentos-cobranca não tem tabela hardcoded correspondente em
# TABELAS_DOMINIO_PNCP (nunca foi adicionada) — vigiado à parte, só
# confirmando que o endpoint responde (sem comparação possível).
_ENDPOINT_SEM_HARDCODE = "/v1/tipos-instrumentos-cobranca"


def _normalizar_texto(valor: object) -> str:
    return str(valor or "").strip().casefold()


def _extrair_codigo(item: dict) -> object:
    for chave in ("codigo", "id", "codigoTipo", "value", "codTipo"):
        if chave in item:
            return item[chave]
    return None


def _extrair_nome(item: dict) -> str:
    for chave in ("nome", "descricao", "name", "label", "descricaoTipo"):
        if chave in item:
            return item[chave]
    return ""


def _itens_da_resposta(bruto):
    if isinstance(bruto, list):
        return bruto
    if isinstance(bruto, dict):
        return bruto.get("data") or bruto.get("content") or bruto.get("resultado") or []
    return []


async def test_live_tabelas_dominio_pncp_sem_drift():
    from mcp_radardeprecos.clients.base import get_json
    from mcp_radardeprecos.config import settings
    from mcp_radardeprecos.domain.dominios import TABELAS_DOMINIO_PNCP

    divergencias: list[str] = []
    for chave_hardcode, path in _TABELAS_DOMINIO_ENDPOINTS.items():
        bruto = await get_json(
            settings.pncp_pncp_base_url, path, {}, source="PNCP tabelas de domínio",
        )
        itens_vivos = _itens_da_resposta(bruto)
        vivos_por_codigo = {
            _extrair_codigo(i): _normalizar_texto(_extrair_nome(i)) for i in itens_vivos
        }

        for entrada in TABELAS_DOMINIO_PNCP[chave_hardcode]:
            codigo = entrada["codigo"]
            nome_hardcode = _normalizar_texto(entrada["nome"])
            if codigo not in vivos_por_codigo:
                divergencias.append(
                    f"{chave_hardcode}: código {codigo} ({entrada['nome']!r}) não encontrado "
                    f"na fonte viva ({path})"
                )
            elif vivos_por_codigo[codigo] != nome_hardcode:
                divergencias.append(
                    f"{chave_hardcode}: código {codigo} tem nome {entrada['nome']!r} no "
                    f"hardcode, mas {vivos_por_codigo[codigo]!r} na fonte viva ({path})"
                )

    assert not divergencias, (
        "domain.dominios.TABELAS_DOMINIO_PNCP desatualizado frente à fonte viva:\n"
        + "\n".join(divergencias)
    )


async def test_live_tipos_instrumentos_cobranca_endpoint_responde():
    from mcp_radardeprecos.clients.base import get_json
    from mcp_radardeprecos.config import settings

    bruto = await get_json(
        settings.pncp_pncp_base_url, _ENDPOINT_SEM_HARDCODE, {}, source="PNCP tabelas de domínio",
    )
    itens = _itens_da_resposta(bruto)
    assert itens, f"{_ENDPOINT_SEM_HARDCODE} não devolveu nenhum item"
