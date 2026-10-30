"""Tool MCP: consolida a "família" de uma contratação — edital, ata (se houver) e contratos derivados.

O vínculo contrato→compra de origem (campo ``compra_origem``,
via ``numeroControlePncpCompra``) foi confirmado ao vivo e é exposto por
``consultar_contratos_orgao_pncp``. Esta tool reutiliza esse
campo — dado um edital/compra, encontra os contratos que citam essa mesma
compra como origem, fechando o ciclo inverso (compra → contratos).

Não consolida/agregar múltiplos
Empenhos numa única linha resumida — cada contrato/empenho encontrado é
devolvido como um item separado, exatamente como já vem de
``consultar_contratos_orgao_pncp`` (mesmos campos, incluindo
``compra_origem``), sem nenhuma lógica adicional de soma/consolidação.

**Limitação conhecida sobre atas — não há endpoint do PNCP para "listar as
atas desta compra".** Diferente de contratos (que agora podem ser
encontrados a partir da compra via ``compra_origem``), uma Ata de Registro
de Preço só pode ser consultada se você já souber o número de controle dela
(``numero_controle_pncp_ata`` — obtido, por exemplo, via
``buscar_pncp_texto(tipo_documento="ata", ...)``). Por isso, esta tool só
inclui a ata quando ``numero_controle_pncp_ata`` é informado explicitamente;
quando a compra é SRP (``srp=True``) e nenhuma ata foi informada, um aviso
alerta que pode haver ata(s) associada(s) não incluída(s) aqui.

**Contratos são buscados por período, não por filtro direto do servidor —
outra limitação conhecida da API de Consulta oficial do PNCP** (ver
docstring de ``clients.pncp_client.consultar_contratos``): o endpoint
``/v1/contratos`` só filtra por ``cnpjOrgao`` + período, não por compra de
origem. Esta tool contorna isso reutilizando ``consultar_contratos_orgao_pncp``
(que já pagina o período internamente) e filtrando no cliente pelos
registros cujo ``compra_origem`` bate com a compra pedida. O período de
busca começa em ``data_publicacao_pncp`` da compra e se estende por
``meses_busca_contratos`` (padrão 24) — contratos assinados bem depois
desse prazo não seriam encontrados; aumente o parâmetro se necessário.

**Termos aditivos e empenhos.** Por padrão
(``incluir_termos_e_empenhos=True``), para cada contrato derivado já
encontrado acima, esta tool também busca os termos aditivos/apostilamentos
(``pncp_client.consultar_termos_contrato``) e os empenhos vinculados
(``pncp_client.consultar_empenhos_contrato``) — fan-out com concorrência
limitada (semáforo 5, mesmo padrão de ``buscar_contratacoes_pncp``/
``buscar_arp_compras``), onde a falha de um contrato isolado não derruba a
família inteira (vira lista vazia + aviso). O schema desses dois endpoints
não é documentado em detalhe pela spec pública do PNCP — os campos
originais são preservados sem tradução (mesma cautela de
``consultar_contratos_orgao_pncp`` antes da tradução oficial da v0.2.2).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from ..clients import pncp_client
from ..logging_utils import get_logger
from .consultar_ata_registro_preco import consultar_ata_registro_preco
from .consultar_contratacao_pncp import consultar_contratacao_pncp
from .consultar_contratos_orgao_pncp import consultar_contratos_orgao_pncp
from .listar_arquivos_pncp import listar_arquivos_pncp

logger = get_logger(__name__)

_MESES_BUSCA_CONTRATOS_PADRAO = 24
_SEMAFORO_TERMOS_EMPENHOS = 5


def _periodo_busca_contratos(
    data_publicacao_pncp: str | None, meses: int
) -> tuple[str, str] | None:
    """``(data_inicial, data_final)`` em ``AAAAMMDD`` para buscar contratos
    desta compra: começa na publicação da compra, se estende por ``meses``
    meses, e nunca passa de hoje. ``None`` se ``data_publicacao_pncp`` estiver
    ausente ou em formato inesperado — sinal para o chamador não tentar a
    busca de contratos."""
    if not data_publicacao_pncp:
        return None
    try:
        inicio = datetime.fromisoformat(data_publicacao_pncp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=timezone.utc)
    hoje = datetime.now(timezone.utc)
    fim = min(inicio + timedelta(days=30 * meses), hoje)
    if fim < inicio:
        fim = inicio
    return inicio.strftime("%Y%m%d"), fim.strftime("%Y%m%d")


async def consultar_familia_contratacao_pncp(
    numero_controle_pncp: str | None = None,
    cnpj: str | None = None,
    ano: int | None = None,
    sequencial: int | None = None,
    numero_controle_pncp_ata: str | None = None,
    meses_busca_contratos: int = _MESES_BUSCA_CONTRATOS_PADRAO,
    incluir_itens_contratacao: bool = False,
    incluir_termos_e_empenhos: bool = True,
) -> dict[str, Any]:
    """Consolida a "família" de uma contratação: o edital/compra, a ata (se informada) e os contratos derivados.

    Dado um edital/compra já conhecido, reúne numa única chamada: (1) o
    detalhe da contratação (mesmo resultado de ``consultar_contratacao_pncp``),
    (2) os arquivos do edital (mesmo resultado de
    ``listar_arquivos_pncp(tipo_documento="edital", ...)``), (3) a Ata de
    Registro de Preço, se ``numero_controle_pncp_ata`` for informado (mesmo
    resultado de ``consultar_ata_registro_preco``, com arquivos), e (4) os
    contratos/empenhos que citam esta compra como origem (via o campo
    ``compra_origem`` de ``consultar_contratos_orgao_pncp``, v0.1.36) —
    cada um devolvido como um item separado, **sem** consolidar/somar
    múltiplos Empenhos numa única linha.

    Ver docstring do módulo para as duas limitações conhecidas da API do
    PNCP que moldam esta tool: (a) não há endpoint para listar as atas de
    uma compra — só é possível incluir uma ata se você já souber o número
    dela; (b) não há filtro de "contratos desta compra" no servidor — a
    busca é feita por período (a partir da publicação da compra) e filtrada
    no cliente.

    Esta tool é uma composição de outras tools já existentes deste servidor
    (``consultar_contratacao_pncp``, ``listar_arquivos_pncp``,
    ``consultar_ata_registro_preco``, ``consultar_contratos_orgao_pncp``) —
    não faz nenhuma chamada de API nova.

    Identifique a compra de uma das duas formas:

    1. ``numero_controle_pncp``: a string completa no formato
       ``CNPJ-1-SEQUENCIAL/ANO``; **ou**
    2. os três parâmetros discretos ``cnpj``/``ano``/``sequencial``.

    Args:
        numero_controle_pncp: Número de controle completo da compra (ver
            acima). Se informado, os 3 parâmetros discretos são ignorados.
        cnpj: CNPJ do órgão, se não usar ``numero_controle_pncp``.
        ano: Ano da contratação.
        sequencial: Sequencial da contratação.
        numero_controle_pncp_ata: Número de controle completo de uma Ata de
            Registro de Preço já conhecida (formato
            ``CNPJ-1-SEQUENCIAL_COMPRA/ANO-SEQUENCIAL_ATA``, ex.: obtido via
            ``buscar_pncp_texto(tipo_documento="ata", ...)``). Deve
            pertencer à MESMA compra identificada acima — caso contrário, um
            ``ValueError`` é levantado. Se omitido e a compra for SRP
            (``srp=True``), um aviso alerta que pode haver ata(s) não
            incluída(s) aqui.
        meses_busca_contratos: Quantos meses, a partir da publicação da
            compra, buscar por contratos derivados (padrão 24). Contratos
            assinados bem depois desse prazo não seriam encontrados;
            aumente se necessário.
        incluir_itens_contratacao: Repassado a ``consultar_contratacao_pncp``
            — se True, inclui a lista de itens da contratação no resultado.
        incluir_termos_e_empenhos: Se True (padrão), busca também os termos
            aditivos/apostilamentos e os empenhos vinculados de CADA
            contrato derivado encontrado (fan-out com concorrência limitada
            — ver docstring do módulo); falha isolada num contrato não
            derruba a família inteira (esse contrato fica com ``termos``/
            ``empenhos`` vazios). Desligue para respostas mais rápidas
            quando esses dados não forem necessários.

    Returns:
        Dicionário com ``compra`` (resultado de ``consultar_contratacao_pncp``),
        ``arquivos_compra`` (lista de arquivos do edital), ``ata`` (resultado
        de ``consultar_ata_registro_preco``, ou ``None`` se
        ``numero_controle_pncp_ata`` não foi informado), ``contratos`` (lista
        de contratos/empenhos cujo ``compra_origem`` bate com esta compra —
        cada um como devolvido por ``consultar_contratos_orgao_pncp``, sem
        consolidação, e — quando ``incluir_termos_e_empenhos=True`` — com os
        campos adicionais ``termos``/``empenhos``, campos originais da API
        preservados sem tradução) e ``avisos`` (SRP sem ata informada,
        ausência de ``data_publicacao_pncp`` impedindo a busca de contratos,
        nenhum contrato encontrado no período, e quaisquer avisos
        propagados de ``consultar_contratos_orgao_pncp``).
    """
    if numero_controle_pncp:
        parsed = pncp_client.parse_numero_controle_pncp(numero_controle_pncp)
        if not parsed:
            raise ValueError(
                "numero_controle_pncp em formato inválido — esperado CNPJ-1-SEQUENCIAL/ANO"
            )
        cnpj, ano, sequencial = parsed
    elif not all(v is not None for v in (cnpj, ano, sequencial)):
        raise ValueError(
            "Informe numero_controle_pncp OU os 3 parâmetros discretos "
            "(cnpj, ano, sequencial)."
        )

    if numero_controle_pncp_ata:
        parsed_ata = pncp_client.parse_numero_controle_pncp_ata(numero_controle_pncp_ata)
        if not parsed_ata:
            raise ValueError(
                "numero_controle_pncp_ata em formato inválido — esperado "
                "CNPJ-1-SEQUENCIAL_COMPRA/ANO-SEQUENCIAL_ATA"
            )
        cnpj_ata, ano_ata, sequencial_ata_compra, _sequencial_ata = parsed_ata
        if (cnpj_ata, ano_ata, sequencial_ata_compra) != (cnpj, ano, sequencial):
            raise ValueError(
                f"numero_controle_pncp_ata ({numero_controle_pncp_ata!r}) pertence a uma "
                f"compra diferente ({cnpj_ata}/{ano_ata}/{sequencial_ata_compra}) da "
                f"informada ({cnpj}/{ano}/{sequencial})."
            )

    logger.info(
        "consultar_familia_contratacao_pncp cnpj=%s ano=%s sequencial=%s "
        "numero_controle_pncp_ata=%s meses_busca_contratos=%s",
        cnpj, ano, sequencial, numero_controle_pncp_ata, meses_busca_contratos,
    )

    compra = await consultar_contratacao_pncp(
        cnpj=cnpj, ano=ano, sequencial=sequencial, incluir_itens=incluir_itens_contratacao,
    )
    arquivos_compra = await listar_arquivos_pncp(
        tipo_documento="edital", cnpj=cnpj, ano=ano, sequencial=sequencial,
    )

    avisos: list[str] = []

    ata: dict[str, Any] | None = None
    if numero_controle_pncp_ata:
        ata = await consultar_ata_registro_preco(
            numero_controle_pncp_ata=numero_controle_pncp_ata, incluir_arquivos=True,
        )
    elif compra.get("srp"):
        avisos.append(
            "Esta contratação é por Sistema de Registro de Preços (srp=True) e pode ter "
            "uma ou mais atas associadas, mas o PNCP não tem um endpoint para listar as "
            "atas de uma compra — é preciso já saber o número de controle da ata (ex.: via "
            'buscar_pncp_texto(tipo_documento="ata", ...)) e informá-lo em '
            "numero_controle_pncp_ata para incluí-la aqui."
        )

    periodo = _periodo_busca_contratos(compra.get("data_publicacao_pncp"), meses_busca_contratos)
    contratos: list[dict[str, Any]] = []
    if periodo is None:
        avisos.append(
            "Não foi possível determinar o período de busca de contratos porque a "
            "contratação não trouxe data_publicacao_pncp válida — contratos NÃO foram "
            "buscados. Use consultar_contratos_orgao_pncp diretamente, informando um "
            "período manualmente."
        )
    else:
        data_inicial, data_final = periodo
        resultado_contratos = await consultar_contratos_orgao_pncp(
            cnpj_orgao=cnpj, data_inicial=data_inicial, data_final=data_final,
        )
        contratos = [
            c
            for c in resultado_contratos.get("contratos", [])
            if (c.get("compra_origem") or {}).get("cnpj") == cnpj
            and (c.get("compra_origem") or {}).get("ano") == ano
            and (c.get("compra_origem") or {}).get("sequencial") == sequencial
        ]
        avisos.extend(resultado_contratos.get("avisos") or [])
        if not contratos:
            avisos.append(
                f"Nenhum contrato/empenho encontrado para esta compra no período "
                f"pesquisado ({data_inicial} a {data_final}, {meses_busca_contratos} "
                "mes(es) a partir da publicação). Se o contrato foi assinado depois desse "
                "prazo, refaça a chamada com meses_busca_contratos maior."
            )

    if incluir_termos_e_empenhos and contratos:
        semaforo = asyncio.Semaphore(_SEMAFORO_TERMOS_EMPENHOS)

        async def _com_termos_e_empenhos(contrato: dict[str, Any]) -> dict[str, Any]:
            numero_controle_contrato = contrato.get("numero_controle_pncp")
            parsed = pncp_client.parse_numero_controle_pncp(numero_controle_contrato or "")
            if not parsed:
                return {**contrato, "termos": [], "empenhos": []}
            cnpj_c, ano_c, sequencial_c = parsed
            try:
                async with semaforo:
                    termos, empenhos = await asyncio.gather(
                        pncp_client.consultar_termos_contrato(cnpj_c, ano_c, sequencial_c),
                        pncp_client.consultar_empenhos_contrato(cnpj_c, ano_c, sequencial_c),
                    )
            except Exception as exc:  # noqa: BLE001 - falha isolada não derruba a família inteira
                logger.warning(
                    "falha ao buscar termos/empenhos do contrato %s: %s",
                    numero_controle_contrato, exc,
                )
                termos, empenhos = [], []
            return {**contrato, "termos": termos, "empenhos": empenhos}

        contratos = list(
            await asyncio.gather(*(_com_termos_e_empenhos(c) for c in contratos))
        )

    return {
        "compra": compra,
        "arquivos_compra": arquivos_compra.get("arquivos", []),
        "ata": ata,
        "contratos": contratos,
        "avisos": avisos,
    }
