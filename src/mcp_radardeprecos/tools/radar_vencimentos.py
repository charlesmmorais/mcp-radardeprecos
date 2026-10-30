"""Tool MCP: radar de vencimento — contratos e atas de registro de preço a vencer.

O Compras.gov.br expõe variantes
``_FimVigencia`` dos módulos de contratos e ARP
(``clients.compras_client.consultar_contratos_fim_vigencia``/
``consultar_arp_fim_vigencia``), que filtram pela janela em que a vigência
TERMINA em vez de começa — a base de um radar de renovação: "o que vai
vencer nos próximos N dias".

Uso: planejar renovação/repactuação de contratos antes do fim da vigência, e
identificar atas em que ainda dá para aderir (carona) antes de expirarem.

Fonte primária por ``tipo``:

- ``"contratos"``: módulo "09 - CONTRATOS" do Compras.gov.br
  (``/modulo-contratos/1.2_consultarContratos_FimVigencia``) — mesma
  pegadinha real já documentada em ``consultar_contratos_compras``:
  ``codigo_orgao`` é OBRIGATÓRIO (a API devolve HTTP 404 sem ele, não uma
  lista vazia).
- ``"atas"``: módulo "ARP" do Compras.gov.br
  (``/modulo-arp/1.2_consultarARP_FimVigencia``) — ``codigo_unidade_gerenciadora``
  é opcional aqui. Aceita também ``codigo_orgao``:
  como o endpoint não filtra por órgão diretamente, a tool
  resolve as UASGs vinculadas ao órgão (``compras_client.consultar_orgao`` +
  ``consultar_uasg``) e faz fan-out limitado (semáforo 5) por UASG.

Complemento opcional (só para ``tipo="atas"``): a listagem oficial de atas
por vigência do PNCP (``clients.pncp_client.consultar_atas_periodo``, achado
3.3), que traz ``possibilidade_adesao`` — um sinal direto de se ainda dá
para aderir. Exige o CNPJ do órgão: sem
ele, o ``/v1/atas`` devolve uma janela NACIONAL (todas as atas do Brasil no
período, sem relação com o órgão pesquisado) — por isso o complemento é
SUPRIMIDO (com aviso) quando nenhum CNPJ pode ser resolvido a partir de
``cnpj_orgao``, ``codigo_orgao`` ou ``codigo_unidade_gerenciadora``. Busca
best-effort: uma falha aqui vira aviso, nunca derruba o resultado principal
(a fonte primária é o Compras.gov.br).
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal

from ..clients import compras_client, pncp_client
from ..logging_utils import get_logger
from ..utils.datas import hoje_iso, janela_dias_a_frente, janela_dias_a_frente_iso, somar_meses
from ..utils.documentos import mascarar_documento
from ..utils.paginacao import extrair_paginacao

logger = get_logger(__name__)

TipoRadar = Literal["contratos", "atas"]

_LIMITE_MAXIMO = 200
_TETO_ARP_MESES = 24  # teto legal de vigência de ARP, Lei 14.133/2021
_SEMAFORO_FANOUT = 5


def _formatar_contrato(bruto: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    formatado = {
        "numero_contrato": bruto.get("numeroContrato"),
        "objeto": bruto.get("objeto"),
        "tipo": bruto.get("nomeTipo"),
        "modalidade": bruto.get("nomeModalidadeCompra"),
        "ni_fornecedor": mascarar_documento(bruto.get("niFornecedor")),
        "nome_fornecedor": bruto.get("nomeRazaoSocialFornecedor"),
        "codigo_orgao": bruto.get("codigoOrgao"),
        "nome_orgao": bruto.get("nomeOrgao"),
        "codigo_unidade_gestora": bruto.get("codigoUnidadeGestora"),
        "nome_unidade_gestora": bruto.get("nomeUnidadeGestora"),
        "data_vigencia_inicial": bruto.get("dataVigenciaInicial"),
        "data_vigencia_final": bruto.get("dataVigenciaFinal"),
        "valor_global": bruto.get("valorGlobal"),
        "numero_controle_pncp_contrato": bruto.get("numeroControlePncpContrato"),
        "numero_controle_pncp_compra": bruto.get("numeroControlePncpCompra"),
        # v0.4.10: situação do registro. Um contrato EXCLUÍDO continua vindo na
        # consulta por fim de vigência, mas não é um vencimento a acompanhar —
        # tratá-lo como tal gera ação sobre um contrato que não existe mais.
        # As atas já expunham `status_ata`/`cancelado`; o contrato não expunha
        # nada equivalente, e a ausência do campo era lida como "vigente".
        "contrato_excluido": bruto.get("contratoExcluido"),
        "data_hora_exclusao": bruto.get("dataHoraExclusao"),
    }
    if incluir_bruto:
        formatado["dados_originais"] = bruto
    return formatado


def _formatar_ata(bruto: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    formatado = {
        "numero_ata_registro_preco": bruto.get("numeroAtaRegistroPreco"),
        "codigo_unidade_gerenciadora": bruto.get("codigoUnidadeGerenciadora"),
        "nome_unidade_gerenciadora": bruto.get("nomeUnidadeGerenciadora"),
        "codigo_orgao": bruto.get("codigoOrgao"),
        "nome_orgao": bruto.get("nomeOrgao"),
        "objeto": bruto.get("objeto"),
        "modalidade": bruto.get("nomeModalidadeCompra"),
        "data_vigencia_inicial": bruto.get("dataVigenciaInicial"),
        "data_vigencia_final": bruto.get("dataVigenciaFinal"),
        "valor_total": bruto.get("valorTotal"),
        "status_ata": bruto.get("statusAta"),
        "numero_controle_pncp_ata": bruto.get("numeroControlePncpAta"),
        "numero_controle_pncp_compra": bruto.get("numeroControlePncpCompra"),
        "link_ata_pncp": bruto.get("linkAtaPNCP"),
    }
    if incluir_bruto:
        formatado["dados_originais"] = bruto
    return formatado


def _formatar_ata_pncp(bruto: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    # nomes reais do AtaRegistroPrecoPeriodoDTO
    # (confirmados ao vivo) — o mapeamento anterior usava nomes adivinhados
    # (objetoCompra, dataVigenciaInicio/Fim) que não existem na resposta real
    # e sempre vinham null.
    formatado = {
        "numero_controle_pncp_ata": bruto.get("numeroControlePNCPAta"),
        "numero_controle_pncp_compra": bruto.get("numeroControlePNCPCompra"),
        "objeto": bruto.get("objetoContratacao"),
        "data_vigencia_inicio": bruto.get("vigenciaInicio"),
        "data_vigencia_fim": bruto.get("vigenciaFim"),
        "possibilidade_adesao": bruto.get("possibilidadeAdesao"),
        "cancelado": bruto.get("cancelado"),
        "data_cancelamento": bruto.get("dataCancelamento"),
        "cnpj_orgao": bruto.get("cnpjOrgao"),
        "nome_orgao": bruto.get("nomeOrgao"),
    }
    if incluir_bruto:
        formatado["dados_originais"] = bruto
    return formatado


async def _resolver_cnpj_do_orgao(codigo_orgao: str) -> str | None:
    """Resolve o CNPJ de um órgão a partir do código (``compras_client.consultar_orgao``)."""
    try:
        codigo_int = int(codigo_orgao)
    except (TypeError, ValueError):
        return None
    try:
        bruto = await compras_client.consultar_orgao(status_orgao=True, codigo_orgao=codigo_int)
    except Exception as exc:  # noqa: BLE001 - resolução best-effort
        logger.warning("falha ao resolver cnpj do orgao %s: %s", codigo_orgao, exc)
        return None
    registros = (bruto or {}).get("resultado", []) or []
    return registros[0].get("cnpjCpfOrgao") if registros else None


async def _resolver_cnpj_da_uasg(codigo_unidade_gerenciadora: str) -> str | None:
    """Resolve o CNPJ do órgão a partir do código de uma UASG (``compras_client.consultar_uasg``)."""
    try:
        bruto = await compras_client.consultar_uasg(
            status_uasg=True, codigo_uasg=codigo_unidade_gerenciadora,
        )
    except Exception as exc:  # noqa: BLE001 - resolução best-effort
        logger.warning(
            "falha ao resolver cnpj do orgao a partir da uasg %s: %s",
            codigo_unidade_gerenciadora, exc,
        )
        return None
    registros = (bruto or {}).get("resultado", []) or []
    return registros[0].get("cnpjCpfOrgao") if registros else None


async def _listar_uasgs_do_orgao(cnpj_orgao: str) -> list[str]:
    """Lista os códigos de UASG (unidades gerenciadoras) vinculadas a um CNPJ de órgão."""
    codigos: list[str] = []
    pagina = 1
    total_paginas = 1
    while pagina <= total_paginas:
        bruto = await compras_client.consultar_uasg(
            status_uasg=True, cnpj_cpf_orgao=cnpj_orgao, pagina=pagina,
        )
        registros = (bruto or {}).get("resultado", []) or []
        if not registros:
            break
        codigos.extend(str(u["codigoUasg"]) for u in registros if u.get("codigoUasg"))
        total_paginas = (bruto or {}).get("totalPaginas", 1) or 1
        pagina += 1
    return codigos


async def _buscar_arp_fim_vigencia_fanout(
    codigos_uasg: list[str], inicio: str, fim: str, limite: int,
) -> tuple[list[dict[str, Any]], int]:
    """Consulta ``consultar_arp_fim_vigencia`` por UASG, fan-out limitado (semáforo 5).

    O endpoint não tem filtro de
    órgão, só de unidade gerenciadora — "todas as atas do órgão X" exige uma
    chamada por UASG do órgão. Falha isolada numa UASG não derruba as demais.
    """
    semaforo = asyncio.Semaphore(_SEMAFORO_FANOUT)

    async def _uma(codigo_uasg: str) -> dict[str, Any]:
        async with semaforo:
            try:
                return await compras_client.consultar_arp_fim_vigencia(
                    codigo_unidade_gerenciadora=codigo_uasg,
                    data_vigencia_final_min=inicio,
                    data_vigencia_final_max=fim,
                    tamanho_pagina=max(10, limite),
                )
            except Exception as exc:  # noqa: BLE001 - falha isolada não derruba o fan-out
                logger.warning(
                    "falha ao consultar ARP fim de vigencia da uasg %s: %s", codigo_uasg, exc,
                )
                return {}

    respostas = await asyncio.gather(*(_uma(c) for c in codigos_uasg))
    registros: list[dict[str, Any]] = []
    total = 0
    for resposta in respostas:
        registros.extend((resposta or {}).get("resultado", []) or [])
        total += (resposta or {}).get("totalRegistros", 0) or 0
    return registros, total


async def radar_vencimentos(
    tipo: TipoRadar,
    data_fim_vigencia_inicio: str | None = None,
    data_fim_vigencia_fim: str | None = None,
    dias_a_frente: int = 30,
    codigo_orgao: str | None = None,
    codigo_unidade_gerenciadora: str | None = None,
    cnpj_orgao: str | None = None,
    vigentes_em: str | None = None,
    limite: int = 100,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Radar de vencimento: contratos ou atas de registro de preço com vigência acabando em breve.

    Args:
        tipo: ``"contratos"`` (módulo "09 - CONTRATOS" do Compras.gov.br) ou
            ``"atas"`` (módulo "ARP" do Compras.gov.br).
        data_fim_vigencia_inicio: Início da janela de FIM de vigência
            (``AAAA-MM-DD``). Se omitido junto com ``data_fim_vigencia_fim``,
            usa hoje até ``dias_a_frente`` dias à frente. Não pode ser
            combinado com ``vigentes_em``.
        data_fim_vigencia_fim: Fim da janela (``AAAA-MM-DD``). Deve ser
            igual ou posterior a ``data_fim_vigencia_inicio``.
        dias_a_frente: Horizonte (dias, a partir de hoje) usado quando as
            datas acima não são informadas (padrão 30). Ignorado quando
            ``vigentes_em`` é informado.
        codigo_orgao: Código do órgão no Compras.gov.br. **Obrigatório**
            quando ``tipo="contratos"`` (a API real devolve HTTP 404 sem
            ele, mesma pegadinha de ``consultar_contratos_compras``). Para
            ``tipo="atas"`` é opcional: quando informado, a tool resolve
            todas as UASGs do órgão e faz fan-out (o módulo ARP só filtra
            por unidade gerenciadora, não por órgão) — use
            ``descobrir_uasg`` com ``tipo="orgao"`` para descobrir o código
            a partir do nome.
        codigo_unidade_gerenciadora: Código da UASG gerenciadora — opcional,
            só usado quando ``tipo="atas"`` e ``codigo_orgao`` não foi
            informado (uma UASG específica em vez de todo o órgão).
        cnpj_orgao: CNPJ do órgão, usado para filtrar o complemento de atas
            do PNCP (``/v1/atas``) — só relevante para ``tipo="atas"``. Se
            omitido, a tool tenta resolvê-lo a partir de ``codigo_orgao`` ou
            ``codigo_unidade_gerenciadora``; se nenhum CNPJ puder ser
            resolvido, o complemento é SUPRIMIDO (com aviso) em vez de
            devolver uma janela nacional sem relação com o órgão pesquisado.
        vigentes_em: Atalho "todas as atas vigentes nesta data" (``AAAA-MM-DD``,
            ou ``"hoje"``) — só para ``tipo="atas"``. Define a janela de FIM
            de vigência como ``[vigentes_em, vigentes_em + 24 meses]`` (teto
            legal de ARP, Lei 14.133/2021) e filtra, no cliente, apenas atas
            cuja vigência já tenha começado (``data_vigencia_inicial <=
            vigentes_em``) — captura "vigentes" sem o usuário calcular a
            janela manualmente. Não pode ser combinado com
            ``data_fim_vigencia_inicio``/``data_fim_vigencia_fim``.
        limite: Número máximo de registros a devolver (padrão 100, máx. 200).
        incluir_bruto: Se True, cada registro (``contratos``/``atas``, e
            também ``atas_pncp_complemento`` quando presente) também traz
            ``dados_originais`` com os campos exatos e completos da fonte,
            sem tradução (padrão False — não incluído por padrão para não
            duplicar o payload à toa).

    Returns:
        Dicionário com ``tipo``, ``periodo`` (``data_fim_vigencia_inicio``/
        ``data_fim_vigencia_fim`` efetivamente usados), ``quantidade_retornada``,
        ``total_no_periodo``, ``contratos`` ou ``atas`` (conforme ``tipo``) e
        ``avisos``. Quando ``tipo="atas"``, também inclui
        ``atas_pncp_complemento`` — a mesma janela consultada na listagem
        oficial de atas do PNCP (``/v1/atas``), filtrada pelo CNPJ do órgão,
        com o campo ``possibilidade_adesao`` (sinal direto de se ainda dá
        para aderir); lista vazia se a consulta complementar falhar, não
        encontrar nada, ou for suprimida por falta de CNPJ (aviso explica em
        todos os casos).

    Raises:
        ValueError: ``tipo`` desconhecido; ``codigo_orgao`` ausente com
            ``tipo="contratos"``; ``vigentes_em`` usado com ``tipo="contratos"``
            ou combinado com as datas explícitas de fim de vigência; só uma
            das datas de fim de vigência informada; ou janela invertida
            (``data_fim_vigencia_inicio`` posterior a ``data_fim_vigencia_fim``).
    """
    if tipo not in ("contratos", "atas"):
        raise ValueError(f"tipo deve ser 'contratos' ou 'atas', recebido: {tipo!r}")
    if tipo == "contratos" and not codigo_orgao:
        raise ValueError(
            "codigo_orgao é obrigatório para tipo='contratos' — a API do Compras.gov.br "
            "devolve HTTP 404 sem ele (não é 'sem resultados', é parâmetro ausente). Use "
            "descobrir_uasg(tipo='orgao', ...) para descobrir o código a partir do nome."
        )
    if vigentes_em is not None and tipo == "contratos":
        raise ValueError(
            "vigentes_em só se aplica a tipo='atas' — é um atalho para o teto legal de "
            "vigência de ARP (24 meses, Lei 14.133/2021), que não existe para contratos."
        )
    if vigentes_em is not None and (data_fim_vigencia_inicio or data_fim_vigencia_fim):
        raise ValueError(
            "vigentes_em não pode ser combinado com data_fim_vigencia_inicio/"
            "data_fim_vigencia_fim — escolha um dos dois."
        )

    if vigentes_em is not None:
        vigentes_em_norm = hoje_iso() if vigentes_em.strip().lower() == "hoje" else vigentes_em
        inicio, fim = vigentes_em_norm, somar_meses(vigentes_em_norm, _TETO_ARP_MESES)
        datas_explicitas = True
    else:
        vigentes_em_norm = None
        if bool(data_fim_vigencia_inicio) != bool(data_fim_vigencia_fim):
            raise ValueError(
                "Informe data_fim_vigencia_inicio E data_fim_vigencia_fim juntos, ou nenhum "
                "dos dois (para usar dias_a_frente)."
            )
        datas_explicitas = bool(data_fim_vigencia_inicio and data_fim_vigencia_fim)
        if datas_explicitas:
            if data_fim_vigencia_inicio > data_fim_vigencia_fim:
                raise ValueError(
                    "data_fim_vigencia_inicio não pode ser posterior a data_fim_vigencia_fim "
                    f"(recebido {data_fim_vigencia_inicio!r} > {data_fim_vigencia_fim!r})."
                )
            inicio, fim = data_fim_vigencia_inicio, data_fim_vigencia_fim
        else:
            dias_a_frente = max(1, dias_a_frente)
            inicio, fim = janela_dias_a_frente_iso(dias_a_frente)

    limite = max(1, min(limite, _LIMITE_MAXIMO))

    logger.info(
        "radar_vencimentos tipo=%s periodo=%s..%s codigo_orgao=%s "
        "codigo_unidade_gerenciadora=%s vigentes_em=%s limite=%s",
        tipo, inicio, fim, codigo_orgao, codigo_unidade_gerenciadora, vigentes_em, limite,
    )

    avisos: list[str] = []
    resultado: dict[str, Any] = {
        "tipo": tipo,
        "periodo": {"data_fim_vigencia_inicio": inicio, "data_fim_vigencia_fim": fim},
    }

    if tipo == "contratos":
        bruto = await compras_client.consultar_contratos_fim_vigencia(
            codigo_orgao=codigo_orgao,
            data_vigencia_final_min=inicio,
            data_vigencia_final_max=fim,
            tamanho_pagina=max(10, limite),
        )
        registros_brutos = (bruto or {}).get("resultado", []) or []
        total_no_periodo = (bruto or {}).get("totalRegistros", 0) or 0
        registros = [_formatar_contrato(c, incluir_bruto) for c in registros_brutos[:limite]]
        resultado["contratos"] = registros
    else:
        # codigo_orgao aciona fan-out
        # por UASGs do órgão (o módulo ARP só filtra por unidade
        # gerenciadora, não por órgão diretamente).
        if codigo_orgao:
            cnpj_resolvido = await _resolver_cnpj_do_orgao(codigo_orgao)
            if not cnpj_orgao and cnpj_resolvido:
                cnpj_orgao = cnpj_resolvido
            if not cnpj_resolvido:
                avisos.append(
                    f"Não foi possível resolver o CNPJ do órgão codigo_orgao={codigo_orgao!r} "
                    "— nenhuma UASG pôde ser listada para o fan-out de atas por órgão."
                )
                registros_brutos, total_no_periodo, bruto = [], 0, None
            else:
                uasgs_orgao = await _listar_uasgs_do_orgao(cnpj_resolvido)
                if not uasgs_orgao:
                    avisos.append(
                        f"Nenhuma UASG ativa encontrada para o órgão codigo_orgao={codigo_orgao!r}."
                    )
                    registros_brutos, total_no_periodo, bruto = [], 0, None
                else:
                    registros_brutos, total_no_periodo = await _buscar_arp_fim_vigencia_fanout(
                        uasgs_orgao, inicio, fim, limite,
                    )
                    bruto = {"totalRegistros": total_no_periodo}
        else:
            bruto = await compras_client.consultar_arp_fim_vigencia(
                codigo_unidade_gerenciadora=codigo_unidade_gerenciadora,
                data_vigencia_final_min=inicio,
                data_vigencia_final_max=fim,
                tamanho_pagina=max(10, limite),
            )
            registros_brutos = (bruto or {}).get("resultado", []) or []
            total_no_periodo = (bruto or {}).get("totalRegistros", 0) or 0
            if not cnpj_orgao and codigo_unidade_gerenciadora:
                cnpj_orgao = await _resolver_cnpj_da_uasg(codigo_unidade_gerenciadora)

        # "vigentes_em" também filtra,
        # no cliente, atas cuja vigência ainda não tinha começado na data de
        # referência (a janela do servidor só controla o FIM da vigência).
        if vigentes_em_norm is not None:
            antes = len(registros_brutos)
            registros_brutos = [
                r for r in registros_brutos
                if (r.get("dataVigenciaInicial") or "") <= vigentes_em_norm
            ]
            if len(registros_brutos) < antes:
                avisos.append(
                    f"{antes - len(registros_brutos)} ata(s) removida(s) do resultado: "
                    f"vigência ainda não tinha começado em {vigentes_em_norm} (vigentes_em). "
                    "total_no_periodo abaixo reflete a contagem do servidor ANTES desse "
                    "filtro adicional do cliente."
                )

        registros = [_formatar_ata(a, incluir_bruto) for a in registros_brutos[:limite]]
        resultado["atas"] = registros

        # Complemento opcional:
        # listagem oficial de
        # atas do PNCP, best-effort — falha isolada vira aviso, nunca derruba
        # o resultado principal (fonte primária é o Compras.gov.br, acima).
        # Exige CNPJ do órgão: sem ele, o /v1/atas devolve janela NACIONAL
        # (todas as atas do Brasil no período), sem relação com o órgão
        # pesquisado — por isso é suprimido em vez de devolver ruído.
        if not cnpj_orgao:
            avisos.append(
                "Complemento de atas do PNCP (/v1/atas) suprimido: não foi possível "
                "determinar o CNPJ do órgão (informe cnpj_orgao, codigo_orgao ou "
                "codigo_unidade_gerenciadora). Sem o CNPJ, esse endpoint devolveria atas de "
                "TODOS os órgãos do Brasil no período, não só as deste órgão."
            )
            resultado["atas_pncp_complemento"] = []
        else:
            if datas_explicitas:
                inicio_pncp, fim_pncp = inicio.replace("-", ""), fim.replace("-", "")
            else:
                inicio_pncp, fim_pncp = janela_dias_a_frente(dias_a_frente)
            atas_pncp: list[dict[str, Any]] = []
            try:
                resposta_pncp = await pncp_client.consultar_atas_periodo(
                    data_inicial=inicio_pncp,
                    data_final=fim_pncp,
                    cnpj=cnpj_orgao,
                    tamanho_pagina=max(10, limite),
                )
                atas_pncp = [
                    _formatar_ata_pncp(a, incluir_bruto)
                    for a in (resposta_pncp or {}).get("data", [])[:limite]
                ]
                # paginação do complemento PNCP é
                # aninhada (não se mistura com a paginação da fonte primária,
                # Compras.gov.br, abaixo) — só existe quando o complemento
                # respondeu com sucesso.
                paginacao_pncp = extrair_paginacao(resposta_pncp)
                if paginacao_pncp:
                    resultado["atas_pncp_complemento_paginacao"] = paginacao_pncp
            except Exception as exc:  # noqa: BLE001 - complemento best-effort, nunca derruba o radar
                logger.warning("falha ao consultar complemento de atas no PNCP: %s", exc)
                avisos.append(
                    f"Complemento de atas do PNCP (/v1/atas) indisponível nesta chamada: {exc}. "
                    "O resultado principal (Compras.gov.br, acima) não foi afetado."
                )
            resultado["atas_pncp_complemento"] = atas_pncp

    if total_no_periodo > len(registros):
        avisos.append(
            f"O Compras.gov.br encontrou {total_no_periodo} registro(s) no período "
            f"informado, mas só {len(registros)} foram retornados (limite={limite}). "
            "Aumente limite ou estreite o período para uma nova chamada."
        )
    if not registros:
        rotulo = "ata(s) de registro de preço" if tipo == "atas" else "contrato(s)"
        avisos.append(f"Nenhum(a) {rotulo} com fim de vigência entre {inicio} e {fim}.")

    # v0.4.10: registros excluídos/cancelados continuam vindo da fonte. Não são
    # removidos aqui (descartar em silêncio esconderia dado), mas são contados
    # em voz alta — um radar de vencimentos que os trata como pendências gera
    # ação sobre contrato que não existe mais.
    excluidos = sum(
        1
        for r in registros
        if r.get("contrato_excluido") is True or r.get("cancelado") is True
    )
    if excluidos:
        avisos.append(
            f"{excluidos} de {len(registros)} registro(s) estão marcados como "
            "EXCLUÍDOS/CANCELADOS na fonte — continuam na lista (nada foi "
            "descartado), mas não são vencimentos a acompanhar. Filtre por "
            "'contrato_excluido'/'cancelado' antes de gerar pendências."
        )

    resultado["quantidade_retornada"] = len(registros)
    resultado["total_no_periodo"] = total_no_periodo
    # campos padronizados da fonte primária
    # (Compras.gov.br) — aditivos; total_no_periodo acima é mantido (nome
    # antigo), total_registros (nome padronizado) é acrescentado com o
    # mesmo valor. Para o fan-out por órgão, "bruto" é um envelope
    # sintético só com o total agregado (sem totalPaginas/numeroPagina, que
    # não existem de forma única quando várias UASGs são combinadas).
    resultado.update(extrair_paginacao(bruto))
    resultado["avisos"] = avisos
    return resultado
