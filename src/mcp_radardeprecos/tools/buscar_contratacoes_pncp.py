"""Tool MCP: busca licitações no PNCP pelo objeto e retorna preços unitários dos itens."""
from __future__ import annotations

import asyncio
from typing import Any

from ..clients import pncp_client
from ..config import settings
from ..logging_utils import get_logger
from ..utils.datas import aviso_indice_parcial, dentro_da_janela
from ..utils.documentos import mascarar_documento
from ..utils.varredura import (
    MAX_PAGINAS_BUSCA_PNCP,
    TAMANHO_PAGINA_BUSCA_PNCP,
    aviso_motivo_da_parada,
    aviso_orcamento,
    aviso_paginas_com_falha,
    varrer_indice,
)

logger = get_logger(__name__)


async def buscar_contratacoes_pncp(
    termo_busca: str,
    uf: str | None = None,
    codigo_modalidade: int | None = None,
    apenas_homologadas: bool = True,
    incluir_valor_homologado: bool = True,
    janelas_meses: int = 12,
    limite: int = 20,
    incluir_arquivos: bool = False,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Busca licitações no PNCP pelo objeto e retorna seus itens com preços unitários.

    Combina a busca textual indexada do PNCP (``/api/search`` — a mesma API
    que alimenta a busca do site pncp.gov.br/app/editais) com a consulta
    oficial de itens de cada contratação encontrada, servindo como base de
    pesquisa de preços praticados (fonte primária, conforme IN SEGES/ME
    65/2021, art. 5º, I).

    **Importante sobre qual valor usar como referência:** cada item traz
    ``valor_unitario_estimado`` (o valor ANTES da disputa, sempre disponível,
    mas **não é referência válida de pesquisa de preços** — Acórdãos TCU
    6.405/2017-1C e 2.062/2016-1C) e, quando ``incluir_valor_homologado=True``
    (padrão), também ``valor_unitario_homologado`` (o valor efetivamente
    vencedor/pago, obtido do endpoint de resultado do item) — **este é o
    valor correto para pesquisa de preços**. Os dois podem divergir de forma
    relevante (confirmado ao vivo: ~6% de diferença em um caso real; pode ser
    maior). Ver ``docs/BOAS_PRATICAS_PESQUISA_PRECOS.md``.

    **Atenção — ``link_pncp`` NÃO é um link de download**: é a página do
    edital no site pncp.gov.br (para leitura humana), não um arquivo. Para
    baixar o PDF do edital (e eventuais retificações/errata, que aparecem
    como arquivos separados anexados à mesma contratação), use
    ``incluir_arquivos=True`` (recomendado quando o pedido for "baixar o
    edital" ou "ver se tem retificação") ou chame a tool
    ``listar_arquivos_pncp`` separadamente com ``tipo_documento="edital"`` —
    o link correto de download tem o formato
    ``https://pncp.gov.br/pncp-api/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos/{n}``,
    bem diferente da URL de ``link_pncp`` (mesmo erro de confusão já visto em
    ``buscar_contratos_compras``, corrigido na v0.1.13 — ver CHANGELOG).

    ``link_pncp`` é construído localmente a partir de
    ``cnpj``/``ano``/``sequencial`` (extraídos de ``numero_controle_pncp``),
    e não mais a partir do campo ``item_url`` da API de busca — achado ao
    vivo: ``item_url`` já vem no formato ``/compras/{cnpj}/{ano}/{sequencial}``
    (com o segmento ``/compras/`` embutido), então concatená-lo direto após
    ``https://pncp.gov.br/app/editais`` gerava um link com ``/compras/``
    duplicado/indevido (``.../app/editais/compras/...``), que não existe no
    site e resulta em erro ao abrir — mesma classe de bug já corrigida em
    ``consultar_contratacao_pncp::link_pagina_pncp``.

    **Limitação conhecida (apontada pelo usuário em 2026-07-10, teto ajustado
    em 2026-07-11):** internamente esta tool varre o índice de busca do PNCP
    (``/api/search``) em páginas de 100 registros brutos, até **no máximo
    100 páginas** (10.000 registros brutos) por chamada. Esse número não é
    arbitrário: é o teto **real e documentado** do próprio backend do PNCP
    (confirmado ao vivo em 2026-07-11 e também relatado por Transparência
    Brasil/Open Contracting Partnership em seu relatório técnico de
    junho/2024 — "Portal Nacional de Contratações Públicas: recomendações e
    desafios técnicos") — o endpoint rejeita com HTTP 400 ("Janela de
    resultados muito grande...") qualquer combinação onde
    ``pagina × tamanhoPagina > 10000`` (limite do índice Elasticsearch
    subjacente, ``index.max_result_window``). Antes da v0.1.51 esta tool
    usava um teto interno bem mais conservador (5 páginas / 500 registros);
    ele foi elevado ao teto real da própria API, então esta varredura agora
    é exaustiva até onde o PNCP permite. Em buscas muito amplas com filtros
    restritivos (``apenas_homologadas=True``, ``janelas_meses`` curto), ainda
    é possível a varredura parar antes de coletar ``limite`` resultados sem
    esgotar o índice — quando isso acontece, o aviso em ``avisos`` menciona
    explicitamente que a varredura parou por esse teto, para não ser
    confundido com os outros motivos de redução (janela, homologação,
    limite). Se isso ocorrer, não há como aumentar mais a cobertura nesta
    tool — é o teto real da API; refine ``termo_busca``/``uf``/
    ``codigo_modalidade`` para reduzir o universo da busca a menos de 10.000
    registros brutos.

    Args:
        termo_busca: Termos de busca sobre o objeto da licitação.
        uf: Sigla da UF para filtrar (ex: SP, DF). Apenas uma UF por chamada
            — o índice do PNCP não combina múltiplas UFs como OR.
        codigo_modalidade: Código de modalidade PNCP para filtrar (ex.: 6 =
            Pregão Eletrônico, 8 = Dispensa). Ver a tool
            ``listar_filtros_pncp`` para a lista completa de códigos válidos.
        apenas_homologadas: Se True (padrão), retorna somente contratações com
            resultado (``tem_resultado``), que possuem preços efetivamente
            praticados/homologados.
        incluir_valor_homologado: Se True (padrão), busca também o valor
            efetivamente homologado de cada item (uma chamada de rede extra
            por item, com concorrência limitada). Desative para acelerar
            buscas muito amplas quando só o valor estimado for suficiente —
            nesse caso ``valor_unitario_homologado`` vem sempre ``None``.
        janelas_meses: Janela de busca em meses a partir de hoje (padrão 12).
        limite: Número máximo de contratações a detalhar (padrão 20). Cada
            contratação gera uma chamada adicional para buscar seus itens —
            valores altos aumentam a latência.
        incluir_arquivos: Se True, busca também os arquivos anexados a cada
            contratação — edital, termo de referência e eventuais
            retificações/errata (uma chamada de rede extra por contratação,
            com concorrência limitada). Necessário para obter o link de
            download real; sem isso, só ``link_pncp`` (página do site) fica
            disponível. Padrão False (mais rápido quando só os dados/itens
            interessam).
        incluir_bruto: Se True, cada contratação também traz
            ``dados_originais`` (o registro bruto do índice de busca) e cada
            item traz ``dados_originais`` (o item bruto da API de itens),
            sem tradução (padrão False — não incluído por padrão para não
            duplicar o payload à toa).

    Returns:
        Dicionário com ``total_encontrado_no_indice`` (total no índice do
        PNCP, **antes** dos filtros de ``janelas_meses``/``apenas_homologadas``
        aplicados no cliente), ``quantidade_retornada``, ``resultados``, uma
        lista de contratações com seus itens, cada um com
        ``valor_unitario_estimado``, e, se ``incluir_valor_homologado``,
        também ``valor_unitario_homologado``, ``quantidade_homologada``,
        ``fornecedor_vencedor`` (CNPJ/nome) e ``data_resultado``, e
        ``avisos`` (ex.: alerta quando ``total_encontrado_no_indice`` supera
        ``quantidade_retornada`` — geralmente por causa da janela temporal
        padrão de 12 meses, não um bug de paginação). Quando
        ``incluir_arquivos=True``, cada contratação também traz
        ``arquivos``: lista com ``titulo``, ``tipo_documento`` (ex.:
        "Edital", "Aviso de Retificação" — cada retificação aparece como uma
        entrada própria nesta lista) e ``url_download`` (link direto, sem
        autenticação, pronto para baixar) — vazia se o PNCP ainda não tiver
        arquivos publicados para aquela contratação.
    """
    limite = max(1, min(limite, 50))
    logger.info(
        "buscar_contratacoes_pncp termo=%r uf=%s modalidade=%s janelas_meses=%s limite=%s "
        "incluir_valor_homologado=%s incluir_arquivos=%s",
        termo_busca, uf, codigo_modalidade, janelas_meses, limite, incluir_valor_homologado,
        incluir_arquivos,
    )

    # Varredura via helper compartilhado (utils/varredura.py, v0.1.54):
    # páginas de 100 registros (o índice aceita bem mais que os 10-20 da UI
    # do site), em lotes concorrentes após a página 1, até o teto real do
    # PNCP (100 páginas / 10.000 registros, pagina*tamanhoPagina<=10000 —
    # confirmado ao vivo em 2026-07-11 e documentado por Transparência
    # Brasil/OCP, 06/2024) e com orçamento de tempo
    # (RADARDEPRECOS_TOOL_BUDGET_SECONDS) — ao estourar, devolve o parcial
    # com aviso em vez de arriscar o timeout do cliente MCP.
    tamanho_pagina_busca = TAMANHO_PAGINA_BUSCA_PNCP
    max_paginas = MAX_PAGINAS_BUSCA_PNCP

    def _aceitar(item: dict[str, Any]) -> bool:
        if apenas_homologadas and not item.get("tem_resultado"):
            return False
        return dentro_da_janela(item.get("data_publicacao_pncp"), janelas_meses)

    varredura = await varrer_indice(
        lambda p: pncp_client.buscar_texto(
            termo_busca,
            "edital",
            uf=uf,
            modalidade=codigo_modalidade,
            pagina=p,
            tamanho_pagina=tamanho_pagina_busca,
        ),
        _aceitar,
        limite=limite,
        tamanho_pagina=tamanho_pagina_busca,
        max_paginas=max_paginas,
        orcamento_segundos=settings.tool_budget_seconds,
        # SEM parada antecipada por janela. Ver a nota em varredura.py
        # (``passou_da_janela``): medido em 2026-08-21, o ``ordenacao=-data``
        # do /api/search ordena por ``data_atualizacao_pncp``, e não pela data
        # de publicação que este filtro usa. Parar aqui descartaria o resto do
        # índice por causa de um edital antigo reeditado hoje.
    )
    coletados = varredura.coletados
    total_indice = varredura.total_indice
    # Achado real (2026-07-10, apontado pelo usuário; teto elevado ao máximo
    # real da API em 2026-07-11): mesmo com max_paginas=100, buscas muito
    # amplas com filtros restritivos ainda podem parar de varrer antes de
    # esgotar o índice E antes de atingir `limite`, sem que isso fique claro
    # para quem chamou. Sinalizado nos avisos, separado dos outros motivos
    # de redução (janela/homologação/limite), para não ser confundido com eles.
    atingiu_max_paginas = varredura.atingiu_max_paginas

    # Limita a concorrência do fan-out de itens: disparar dezenas de chamadas
    # simultâneas ao endpoint de itens do PNCP aumenta a chance de timeout
    # (o próprio endpoint responde mais devagar sob carga). 5 em paralelo é
    # um equilíbrio razoável entre latência total e estabilidade.
    semaforo_itens = asyncio.Semaphore(5)
    # Semáforo independente para o fan-out de RESULTADOS por item — é um
    # nível a mais de chamadas (uma por item, não por contratação), então
    # merece seu próprio limite de concorrência.
    semaforo_resultados = asyncio.Semaphore(5)

    async def _resultado_do_item(
        cnpj: str, ano: int, sequencial: int, it: dict[str, Any]
    ) -> dict[str, Any]:
        """Busca o valor homologado de um item — None em todos os campos se
        o item não tiver resultado ainda ou a chamada falhar isoladamente."""
        vazio = {
            "valor_unitario_homologado": None,
            "quantidade_homologada": None,
            "fornecedor_vencedor": None,
            "data_resultado": None,
        }
        if not incluir_valor_homologado or not it.get("temResultado"):
            return vazio
        numero_item = it.get("numeroItem")
        if numero_item is None:
            return vazio
        try:
            async with semaforo_resultados:
                resultados_item = await pncp_client.consultar_resultado_item(
                    cnpj, ano, sequencial, numero_item
                )
        except Exception as exc:  # noqa: BLE001 - erro isolado não deve derrubar a busca inteira
            logger.warning(
                "falha ao buscar resultado do item %s (cnpj=%s ano=%s seq=%s): %s",
                numero_item, cnpj, ano, sequencial, exc,
            )
            return vazio
        if not resultados_item:
            return vazio
        primeiro = resultados_item[0]
        return {
            "valor_unitario_homologado": primeiro.get("valorUnitarioHomologado"),
            "quantidade_homologada": primeiro.get("quantidadeHomologada"),
            "fornecedor_vencedor": {
                "cnpj": mascarar_documento(primeiro.get("niFornecedor")),
                "nome": primeiro.get("nomeRazaoSocialFornecedor"),
                # Promovidos na v0.4.18 — vinham no retorno e eram descartados.
                # `porte` sustenta análise de participação de ME/EPP (cota
                # reservada, Lei 14.133 art. 48). `tipo_pessoa` distingue PJ de
                # PF: quando é "PF", o "fornecedor" é uma pessoa natural, e o
                # nome é nome civil — informação que muda como o dado deve ser
                # tratado, e que antes ficava invisível.
                "porte": primeiro.get("porteFornecedorNome"),
                "tipo_pessoa": primeiro.get("tipoPessoa"),
            },
            "data_resultado": primeiro.get("dataResultado"),
        }

    async def _com_itens(edital: dict[str, Any]) -> dict[str, Any]:
        numero_controle = edital.get("numero_controle_pncp", "")
        parsed = pncp_client.parse_numero_controle_pncp(numero_controle)
        itens: list[dict[str, Any]] = []
        itens_formatados: list[dict[str, Any]] = []
        link_pncp: str | None = None
        if parsed:
            cnpj, ano, sequencial = parsed
            # Construído localmente a partir de cnpj/ano/sequencial — não a
            # partir de edital["item_url"] (bug corrigido na v0.1.31):
            # item_url vem da API de busca como "/compras/{cnpj}/{ano}/{seq}"
            # (já com o prefixo "/compras/"), então concatenar
            # "https://pncp.gov.br/app/editais" + item_url gerava
            # ".../app/editais/compras/..." — segmento extra que não existe
            # no site e dá erro (mesmo bug já corrigido em
            # consultar_contratacao_pncp::link_pagina_pncp, v0.1.30).
            link_pncp = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"
            try:
                async with semaforo_itens:
                    itens = await pncp_client.consultar_itens_contratacao(cnpj, ano, sequencial)
            except Exception as exc:  # noqa: BLE001 - erro isolado não deve derrubar a busca inteira
                logger.warning("falha ao buscar itens de %s: %s", numero_controle, exc)

            resultados_por_item = await asyncio.gather(
                *(_resultado_do_item(cnpj, ano, sequencial, it) for it in itens)
            )
            itens_formatados = [
                {
                    "descricao": it.get("descricao"),
                    "quantidade": it.get("quantidade"),
                    "unidade_medida": it.get("unidadeMedida"),
                    "valor_unitario_estimado": it.get("valorUnitarioEstimado"),
                    "valor_total": it.get("valorTotal"),
                    "situacao": it.get("situacaoCompraItemNome"),
                    **resultado_homologado,
                    **({"dados_originais": it} if incluir_bruto else {}),
                }
                for it, resultado_homologado in zip(itens, resultados_por_item, strict=False)
            ]

        registro = {
            "numero_controle_pncp": numero_controle,
            "titulo": edital.get("title"),
            "objeto": edital.get("description"),
            "orgao": edital.get("orgao_nome"),
            "cnpj_orgao": edital.get("orgao_cnpj"),
            "uf": edital.get("uf"),
            "municipio": edital.get("municipio_nome"),
            "modalidade": edital.get("modalidade_licitacao_nome"),
            "data_publicacao_pncp": edital.get("data_publicacao_pncp"),
            "link_pncp": link_pncp,
            "itens": itens_formatados,
        }
        if incluir_bruto:
            registro["dados_originais"] = edital
        return registro

    resultados = await asyncio.gather(*(_com_itens(e) for e in coletados[:limite]))

    if incluir_arquivos:
        # Mesmo padrão de fan-out com concorrência limitada usado em
        # buscar_contratos_compras: uma chamada de rede extra por
        # contratação, falha isolada não derruba a busca inteira. Usa
        # recurso="compras" (não "contratos") — o edital e suas
        # retificações/errata ficam anexados à COMPRA (contratação), não ao
        # contrato assinado.
        semaforo_arquivos = asyncio.Semaphore(5)

        async def _com_arquivos(r: dict[str, Any]) -> dict[str, Any]:
            arquivos: list[dict[str, Any]] = []
            parsed = pncp_client.parse_numero_controle_pncp(r.get("numero_controle_pncp") or "")
            if parsed:
                cnpj, ano, sequencial = parsed
                try:
                    async with semaforo_arquivos:
                        brutos = await pncp_client.consultar_arquivos(
                            cnpj, ano, sequencial, "compras"
                        )
                except Exception as exc:  # noqa: BLE001 - erro isolado não deve derrubar a busca inteira
                    logger.warning(
                        "falha ao buscar arquivos da contratação %s: %s",
                        r.get("numero_controle_pncp"), exc,
                    )
                    brutos = []
                arquivos = [
                    {
                        "titulo": a.get("titulo"),
                        "tipo_documento": a.get("tipoDocumentoNome"),
                        "url_download": a.get("uri") or a.get("url"),
                    }
                    for a in brutos
                ]
            return {**r, "arquivos": arquivos}

        resultados = await asyncio.gather(*(_com_arquivos(r) for r in resultados))

    # Aviso quando o total do índice supera o retornado — sobretudo por
    # causa da janela temporal (filtrada no cliente, não refletida no total
    # do índice) ou do filtro apenas_homologadas, nenhum dos dois com aviso
    # próprio até agora (achado real: buscas com total_encontrado_no_indice
    # bem maior que quantidade_retornada, sem nenhuma explicação, levando a
    # suspeitar de bug de paginação em vez do comportamento esperado).
    avisos: list[str] = []
    motivos_reducao = [f"janela de busca de {janelas_meses} mes(es) (parâmetro janelas_meses)"]
    if apenas_homologadas:
        motivos_reducao.append(
            "apenas_homologadas=True (descarta contratações sem resultado)"
        )
    if len(resultados) >= limite:
        motivos_reducao.append(f"limite de {limite} resultado(s) (parâmetro limite)")
    if atingiu_max_paginas:
        motivos_reducao.append(
            f"a varredura interna do índice parou nas primeiras {max_paginas} páginas "
            f"({max_paginas * tamanho_pagina_busca} registros brutos) sem esgotar o "
            "índice nem atingir o limite pedido — pode haver mais contratações que "
            "atendem aos filtros além do que foi varrido; refine termo_busca/uf/"
            "codigo_modalidade para reduzir o universo de busca"
        )
    aviso_reducao = aviso_indice_parcial(total_indice, len(resultados), motivos_reducao)
    if aviso_reducao:
        avisos.append(aviso_reducao)
    avisos.append(aviso_motivo_da_parada(varredura, limite))
    if varredura.paginas_com_falha:
        avisos.append(aviso_paginas_com_falha(varredura.paginas_com_falha))
    if varredura.orcamento_estourado:
        avisos.append(aviso_orcamento(settings.tool_budget_seconds))

    return {
        "total_encontrado_no_indice": total_indice,
        "quantidade_retornada": len(resultados),
        "resultados": resultados,
        "avisos": avisos,
    }
