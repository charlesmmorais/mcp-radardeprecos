"""Tool MCP: busca contratos públicos pelo objeto (âmbito PNCP / Lei 14.133)."""
from __future__ import annotations

import asyncio
from typing import Any

from ..clients import pncp_client
from ..config import settings
from ..logging_utils import get_logger
from ..utils.datas import aviso_indice_parcial, dentro_da_janela
from ..utils.varredura import (
    MAX_PAGINAS_BUSCA_PNCP,
    TAMANHO_PAGINA_BUSCA_PNCP,
    aviso_motivo_da_parada,
    aviso_orcamento,
    aviso_paginas_com_falha,
    varrer_indice,
)

logger = get_logger(__name__)

_STATUS_VALIDOS = ("vigente", "nao_vigente", "todos")


def _formatar_contrato(c: dict[str, Any], link_pncp: str | None, incluir_bruto: bool = False) -> dict[str, Any]:
    formatado = {
        "numero_controle_pncp": c.get("numero_controle_pncp"),
        "titulo": c.get("title"),
        "objeto": c.get("description"),
        "orgao": c.get("orgao_nome"),
        "cnpj_orgao": c.get("orgao_cnpj"),
        "uf": c.get("uf"),
        "municipio": c.get("municipio_nome"),
        "modalidade_origem": c.get("modalidade_licitacao_nome"),
        "valor_global": c.get("valor_global"),
        "data_publicacao_pncp": c.get("data_publicacao_pncp"),
        "data_inicio_vigencia": c.get("data_inicio_vigencia"),
        "data_fim_vigencia": c.get("data_fim_vigencia"),
        "link_pncp": link_pncp,
    }
    if incluir_bruto:
        formatado["dados_originais"] = c
    return formatado


async def buscar_contratos_compras(
    termo_busca: str,
    uf: str | None = None,
    cnpj_orgao: str | None = None,
    status: str | None = None,
    janelas_meses: int = 12,
    limite: int = 20,
    incluir_arquivos: bool = False,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Busca contratos públicos pelo objeto, com valores efetivamente contratados.

    Fonte: contratos publicados no PNCP (Lei 14.133/2021), via o mesmo índice
    de busca textual usado pelo portal do PNCP. Não há filtro nativo por
    texto do objeto no lado do servidor para contratos legados (pré-14.133,
    no Comprasnet/Contratos.gov.br) — essa fonte fica como extensão futura.

    **Correção — filtro ``status="vigente"`` deixou de ser fixo.**
    Antes, esta tool sempre filtrava por ``status="vigente"`` sem
    expor isso como parâmetro, o que produzia uma contagem de "contratos
    assinados em 2026" **muito** abaixo do real (47 contra 176+ reais).
    Investigado ao vivo: ``status="vigente"`` no PNCP não significa "assinado
    neste ano", significa "a vigência ainda não terminou hoje" — descartando
    justamente a classe de instrumento mais comum (empenhos de baixo valor,
    vigência curta, ex.: inscrição em evento) sempre que sua vigência já
    tiver terminado. Teste isolado confirmado: mesma busca, mesmo período,
    caiu de 203 para 110 resultados só com esse filtro. Por isso o padrão
    agora é **sem filtro de status** (equivalente a ``"todos"`` — traz
    contratos independentemente de estarem vigentes hoje), que é o
    comportamento correto para perguntas como "quantos contratos foram
    assinados em X". Quem quiser só os que ainda estão em vigor pode passar
    ``status="vigente"`` explicitamente.

    **Atenção — esta busca não é garantidamente exaustiva.** Por ser busca
    textual (não uma listagem estruturada por órgão), depende do termo
    encontrar cada registro no índice, tem um teto de ``limite`` (máx. 50) e
    varre no máximo 100 páginas do índice (10.000 registros — o teto real da
    API do PNCP, ``pagina×tamanhoPagina<=10000``, confirmado ao vivo em
    2026-07-11 e documentado por Transparência Brasil/OCP, 06/2024). Para uma
    contagem **exaustiva e auditável** de todos os contratos/empenhos de um
    CNPJ num período, use
    ``consultar_contratos_orgao_pncp`` (endpoint oficial de Consulta,
    filtrado no servidor por CNPJ do órgão — não depende de o termo de busca
    aparecer no texto do objeto).

    **Atenção — ``link_pncp`` NÃO é um link de download**: é a página do
    contrato no site pncp.gov.br (para leitura humana), não um arquivo. Para
    baixar o PDF do contrato assinado (ou outros anexos), use
    ``incluir_arquivos=True`` (recomendado quando o pedido for "listar/baixar
    os contratos") ou chame a tool ``listar_arquivos_pncp`` separadamente com
    ``tipo_documento="contrato"`` — o link correto de download tem o formato
    ``https://pncp.gov.br/pncp-api/v1/orgaos/{cnpj}/contratos/{ano}/{sequencial}/arquivos/{n}``,
    bem diferente da URL de ``link_pncp``. Confundir os dois é um erro comum
    (já visto na prática): a página do site não serve o arquivo diretamente.

    ``link_pncp`` é construído localmente a partir de
    ``cnpj``/``ano``/``sequencial`` (extraídos de ``numero_controle_pncp``),
    e não mais a partir do campo ``item_url`` da API de busca — achado ao
    vivo (mesma classe de bug corrigida em ``buscar_contratacoes_pncp`` e
    ``consultar_contratacao_pncp``): ``item_url`` já vem no formato
    ``/contratos/{cnpj}/{ano}/{sequencial}`` (com o segmento ``/contratos/``
    embutido), então concatená-lo direto após
    ``https://pncp.gov.br/app/contratos`` gerava um link com ``/contratos/``
    duplicado (``.../app/contratos/contratos/...``), que não existe no site
    — confirmado ao vivo, o PNCP responde "Atenção: O contrato/empenho
    informado não está cadastrado." para esse formato.

    Args:
        termo_busca: Termos de busca sobre o objeto do contrato.
        uf: Sigla da UF para filtrar.
        cnpj_orgao: CNPJ do órgão contratante para filtrar (somente dígitos).
        status: ``"vigente"`` (só contratos cuja vigência não terminou),
            ``"nao_vigente"`` ou ``"todos"``/``None`` (padrão — sem filtro,
            recomendado para contagens do tipo "quantos foram assinados").
        janelas_meses: Janela de busca em meses a partir de hoje (padrão 12).
        limite: Número máximo de contratos a retornar (padrão 20, máx. 50).
        incluir_arquivos: Se True, busca também os arquivos anexados de cada
            contrato (uma chamada de rede extra por contrato, com
            concorrência limitada) — necessário para obter o link de
            download real. Padrão False (mais rápido quando só os dados do
            contrato interessam).
        incluir_bruto: Se True, cada contrato também traz ``dados_originais``
            com os campos exatos e completos do índice de busca do PNCP, sem
            tradução (padrão False — não incluído por padrão para não
            duplicar o payload à toa).

    Returns:
        Dicionário com ``total_encontrado_no_indice``, ``quantidade_retornada``,
        ``resultados`` — lista de contratos com objeto, órgão, valor global,
        vigência e ``link_pncp`` (página do site, **não** de download) — e
        ``avisos`` (ex.: alerta de possível truncamento quando o ``limite``
        é atingido, com o total do índice para referência). Quando
        ``incluir_arquivos=True``, cada contrato também traz ``arquivos``:
        lista com ``titulo``, ``tipo_documento`` e ``url_download`` (link
        direto, sem autenticação, pronto para baixar) — vazia se o PNCP
        ainda não tiver arquivos publicados para aquele contrato.
    """
    if status is not None and status not in _STATUS_VALIDOS:
        raise ValueError(f"status deve ser um de {_STATUS_VALIDOS} ou None")
    status_busca = None if status in (None, "todos") else status

    limite = max(1, min(limite, 50))
    logger.info(
        "buscar_contratos_compras termo=%r uf=%s cnpj_orgao=%s status=%s janelas_meses=%s "
        "limite=%s incluir_arquivos=%s",
        termo_busca, uf, cnpj_orgao, status, janelas_meses, limite, incluir_arquivos,
    )

    # Varredura via helper compartilhado (utils/varredura.py, v0.1.54):
    # páginas de 100 registros em lotes concorrentes após a página 1, até o
    # teto real do PNCP (100 páginas / 10.000 registros,
    # pagina*tamanhoPagina<=10000 — confirmado ao vivo em 2026-07-11) e com
    # orçamento de tempo (RADARDEPRECOS_TOOL_BUDGET_SECONDS).
    tamanho_pagina_busca = TAMANHO_PAGINA_BUSCA_PNCP

    def _aceitar(item: dict[str, Any]) -> bool:
        if cnpj_orgao and item.get("orgao_cnpj") != cnpj_orgao:
            return False
        return dentro_da_janela(item.get("data_publicacao_pncp"), janelas_meses)

    varredura = await varrer_indice(
        lambda p: pncp_client.buscar_texto(
            termo_busca, "contrato", uf=uf, status=status_busca, pagina=p,
            tamanho_pagina=tamanho_pagina_busca,
        ),
        _aceitar,
        limite=limite,
        tamanho_pagina=tamanho_pagina_busca,
        max_paginas=MAX_PAGINAS_BUSCA_PNCP,
        orcamento_segundos=settings.tool_budget_seconds,
        # SEM parada antecipada por janela — ver a nota em varredura.py
        # (``passou_da_janela``): o ``-data`` do /api/search ordena por data de
        # ATUALIZAÇÃO, não de publicação (medido em 2026-08-21).
    )
    coletados = varredura.coletados
    total_indice = varredura.total_indice

    def _link_pncp_contrato(c: dict[str, Any]) -> str | None:
        # Construído localmente a partir de cnpj/ano/sequencial (extraídos de
        # numero_controle_pncp) — não a partir de c["item_url"] (bug
        # corrigido na v0.1.31): item_url já vem no formato
        # "/contratos/{cnpj}/{ano}/{sequencial}" (com o segmento "/contratos/"
        # embutido), então concatená-lo direto após
        # "https://pncp.gov.br/app/contratos" gerava
        # ".../app/contratos/contratos/..." — segmento duplicado que não
        # existe no site (confirmado ao vivo: o PNCP responde "Atenção: O
        # contrato/empenho informado não está cadastrado."). Mesma classe de
        # bug já corrigida em buscar_contratacoes_pncp::link_pncp e
        # consultar_contratacao_pncp::link_pagina_pncp.
        parsed = pncp_client.parse_numero_controle_pncp(c.get("numero_controle_pncp") or "")
        if not parsed:
            return None
        cnpj, ano, sequencial = parsed
        return f"https://pncp.gov.br/app/contratos/{cnpj}/{ano}/{sequencial}"

    resultados = [
        _formatar_contrato(c, _link_pncp_contrato(c), incluir_bruto)
        for c in coletados[:limite]
    ]

    if incluir_arquivos:
        # Mesmo padrão de fan-out com concorrência limitada usado em
        # buscar_contratacoes_pncp (itens/resultados): uma chamada de rede
        # extra por contrato, falha isolada não derruba a busca inteira.
        semaforo_arquivos = asyncio.Semaphore(5)

        async def _com_arquivos(r: dict[str, Any]) -> dict[str, Any]:
            arquivos: list[dict[str, Any]] = []
            parsed = pncp_client.parse_numero_controle_pncp(r.get("numero_controle_pncp") or "")
            if parsed:
                cnpj, ano, sequencial = parsed
                try:
                    async with semaforo_arquivos:
                        brutos = await pncp_client.consultar_arquivos(
                            cnpj, ano, sequencial, "contratos"
                        )
                except Exception as exc:  # noqa: BLE001 - erro isolado não deve derrubar a busca inteira
                    logger.warning(
                        "falha ao buscar arquivos do contrato %s: %s",
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

    avisos: list[str] = []

    # Motivos que podem reduzir quantidade_retornada abaixo de total_indice
    # mesmo sem o limite ser atingido — sobretudo janelas_meses, que filtra
    # no cliente e não é refletido no total do índice (achado real: uma
    # busca com total_indice=10 devolvia só 4, sem nenhum aviso, porque nem
    # o limite nem cnpj_orgao tinham disparado os avisos abaixo).
    motivos_reducao = [f"janela de busca de {janelas_meses} mes(es) (parâmetro janelas_meses)"]
    if cnpj_orgao:
        motivos_reducao.append("filtro por CNPJ do órgão (cnpj_orgao)")

    if len(resultados) >= limite:
        avisos.append(
            f"Resultado truncado no limite de {limite} contrato(s) — pode haver mais "
            f"contratos do CNPJ/termo pedidos além dos retornados aqui (índice tem "
            f"{total_indice} registro(s) no total para esta página de busca, antes dos "
            f"filtros aplicados no cliente: {'; '.join(motivos_reducao)}). Para uma "
            "contagem exaustiva e auditável por órgão, use consultar_contratos_orgao_pncp."
        )
    else:
        aviso_reducao = aviso_indice_parcial(total_indice, len(resultados), motivos_reducao)
        if aviso_reducao:
            avisos.append(aviso_reducao)

    avisos.append(aviso_motivo_da_parada(varredura, limite))
    if varredura.paginas_com_falha:
        avisos.append(aviso_paginas_com_falha(varredura.paginas_com_falha))
    if varredura.orcamento_estourado:
        avisos.append(aviso_orcamento(settings.tool_budget_seconds))

    if cnpj_orgao:
        avisos.append(
            "Esta busca é por texto, não uma listagem exaustiva por CNPJ — depende do "
            "termo aparecer no índice do PNCP. Para uma contagem exaustiva e auditável "
            "de todos os contratos/empenhos deste CNPJ no período, use "
            "consultar_contratos_orgao_pncp."
        )

    return {
        "total_encontrado_no_indice": total_indice,
        "quantidade_retornada": len(resultados),
        "resultados": resultados,
        "avisos": avisos,
    }
