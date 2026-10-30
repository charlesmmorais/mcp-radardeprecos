"""Tool MCP: busca textual booleana (E / OU / NÃO) no PNCP, sobre buscar_pncp_texto.

Pedido do usuário, na sequência do item 6 (limitação de ``termo_busca``):
"queria implementar uma busca usando 'E', 'OU', 'Não'".

**Por que orquestração no cliente, e não um operador nativo do PNCP.** O
backend de busca do PNCP (``/api/search``) não tem NENHUM operador booleano
nativo — confirmado ao vivo e já documentado em ``clients.pncp_client.buscar_texto``
e ``tools.buscar_pncp_texto``: múltiplas palavras em ``termo_busca`` já
funcionam como "E" (bag-of-words, independente de ordem), mas não existe
"OU" nem "NÃO" (aspas não fazem frase exata, e não há sintaxe de exclusão).
Por isso, cada operador é implementado assim:

- **E** (``termos_e``): usa diretamente o comportamento nativo de
  bag-of-words de ``termo_busca`` — uma única sub-consulta com todos os
  termos concatenados.
- **OU** (``termos_ou``): dispara uma sub-consulta por alternativa (cada uma
  combinando ``termos_e`` + 1 termo de ``termos_ou``) e une os resultados,
  deduplicados por ``numero_controle_pncp`` — não existe "OR" nativo, então
  isso custa 1 chamada de rede por termo de ``termos_ou`` (limitado a 8 por
  chamada, para não gerar um fan-out descontrolado).
- **NÃO** (``termos_nao``): pós-filtro no cliente — remove, do conjunto já
  reunido, qualquer resultado cujo título+descrição (os únicos campos de
  texto que a busca devolve) contenha algum termo de ``termos_nao`` (mesma
  normalização tolerante a maiúsculas/acentos de
  ``utils.texto_busca.normalizar_para_busca``). **Isso é uma exclusão por
  substring, não uma negação lógica do índice do PNCP** — mesmo teto de
  precisão conhecido de qualquer filtro por palavra-chave deste projeto
  (ver ``tools.classificar_objeto_tic``): só enxerga o texto que a busca já
  devolveu (título/descrição), não o edital inteiro.

Composição pura sobre ``tools.buscar_pncp_texto`` — reaproveita toda a
validação, os outros filtros estruturados (uf, modalidade, órgão etc.) e o
modo ``janelas_meses`` já implementados lá, sem duplicar essa lógica.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..domain.dominios import MODALIDADES_PNCP, TIPOS_DOCUMENTO_BUSCA_PNCP
from ..logging_utils import get_logger
from ..utils.texto_busca import normalizar_para_busca
from .buscar_pncp_texto import _validar_ano, buscar_pncp_texto

logger = get_logger(__name__)

# Cada termo de termos_ou dispara uma sub-consulta separada ao PNCP — limite
# de segurança contra fan-out descontrolado (mesmo espírito do
# _MAX_PAGINAS_JANELA em buscar_pncp_texto.py).
_MAX_TERMOS_OU = 8


def _limpar_termos(termos: list[str] | None) -> list[str]:
    if not termos:
        return []
    return [t.strip() for t in termos if t and t.strip()]


async def buscar_pncp_texto_booleano(
    tipo_documento: str,
    termos_e: list[str] | None = None,
    termos_ou: list[str] | None = None,
    termos_nao: list[str] | None = None,
    uf: str | None = None,
    municipio: str | None = None,
    modalidade: int | None = None,
    # `int | str`: ver a nota em buscar_pncp_texto — com `int`, o Pydantic
    # do FastMCP barra antes e o cliente recebe erro de tipo em vez da
    # explicacao de que o indice aceita UM ano por chamada.
    ano: int | str | None = None,
    tipo_instrumento: int | None = None,
    tipo_contrato: int | None = None,
    orgao: str | None = None,
    unidade: str | None = None,
    esfera: str | None = None,
    poder: str | None = None,
    fonte_orcamentaria: str | None = None,
    tipo_margem_preferencia: str | None = None,
    exigencia_conteudo_nacional: bool | None = None,
    possui_emenda_parlamentar: bool | None = None,
    permite_adesao: bool | None = None,
    status: str | None = None,
    janelas_meses: int | None = None,
    ordenacao: str = "-data",
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Busca textual booleana (E / OU / NÃO) no PNCP, sobre buscar_pncp_texto.

    Ver docstring do módulo para como cada operador é implementado (E via
    bag-of-words nativo, OU via fan-out de sub-consultas + união
    deduplicada, NÃO via pós-filtro por substring) e o teto de precisão que
    isso implica — sempre confira os resultados antes de decisões
    automatizadas, sobretudo os excluídos por ``termos_nao``.

    Args:
        tipo_documento: "edital" (licitações), "ata" (registro de preços) ou "contrato".
        termos_e: Termos que devem aparecer TODOS no texto (bag-of-words —
            não precisam estar juntos nem na mesma ordem). Ao menos um de
            ``termos_e``/``termos_ou`` é obrigatório.
        termos_ou: Termos alternativos — cada resultado deve conter
            ``termos_e`` E (ao menos) um destes. Máximo 8 (cada um dispara
            uma sub-consulta separada ao PNCP). Ao menos um de
            ``termos_e``/``termos_ou`` é obrigatório.
        termos_nao: Termos a excluir — remove, do conjunto já reunido,
            qualquer resultado cujo título+descrição contenha algum destes
            termos (substring, tolerante a maiúsculas/acentos). Não pode
            repetir um termo já presente em ``termos_e``/``termos_ou``
            (contraditório — levanta erro).
        uf: Sigla da UF (ex: SP, DF, RS). Uma UF por chamada.
        municipio: ID interno do PNCP do município (ver ``listar_filtros_pncp``).
        modalidade: Código de modalidade PNCP (ex.: 6 = Pregão Eletrônico).
        ano: Ano para filtrar (ano civil completo).
        tipo_instrumento: Código do tipo de instrumento convocatório.
        tipo_contrato: Código do tipo de contrato (específico de tipo_documento="contrato").
        orgao: ID do órgão (campo ``id`` da faceta "orgaos", não o CNPJ).
        unidade: ID da unidade (campo ``id`` da faceta "unidades").
        esfera: "F" (Federal), "E" (Estadual), "M" (Municipal), "D" (Distrital) ou "N".
        poder: "E" (Executivo), "L" (Legislativo), "J" (Judiciário) ou "N".
        fonte_orcamentaria: Código da fonte orçamentária.
        tipo_margem_preferencia: Código do tipo de margem de preferência.
        exigencia_conteudo_nacional: Filtro booleano; omitir para não filtrar.
        possui_emenda_parlamentar: Filtro booleano; omitir para não filtrar.
        permite_adesao: Filtro booleano (específico de atas); omitir para não filtrar.
        status: Depende do tipo — ver docstring de ``buscar_pncp_texto``.
        janelas_meses: Filtro de janela temporal em meses (aplicado dentro
            de cada sub-consulta — ver ``buscar_pncp_texto``).
        ordenacao: "-data" (mais recentes primeiro, padrão) ou "data" — usada
            tanto em cada sub-consulta quanto para reordenar a união final.
        tamanho_pagina: Máximo de resultados por sub-consulta e também
            limite final após união/dedup/exclusão (padrão 10, máx. 100).
            O total final pode ser MENOR que este número mesmo havendo mais
            resultados no índice: a dedup e a exclusão por ``termos_nao``
            acontecem depois de cada sub-consulta já ter aplicado seu
            próprio limite.

    Returns:
        Dicionário com ``items`` (união deduplicada por
        ``numero_controle_pncp``, reordenada conforme ``ordenacao`` e
        truncada em ``tamanho_pagina``), ``quantidade_retornada``,
        ``total_bruto_por_subconsulta`` (soma do ``total`` de cada
        sub-consulta — **não** é o total real após dedup/exclusão: pode
        contar o mesmo resultado mais de uma vez quando ele casa com mais
        de um termo de ``termos_ou``, e não desconta ``termos_nao``; é só
        um indicativo bruto do volume no índice) e ``avisos`` (sempre
        explica como OU/NÃO foram implementados quando usados, além de
        avisos de falha isolada de sub-consulta ou truncamento pelo limite).
    """
    if tipo_documento not in TIPOS_DOCUMENTO_BUSCA_PNCP:
        raise ValueError(f"tipo_documento deve ser um de {TIPOS_DOCUMENTO_BUSCA_PNCP}")
    if modalidade is not None and modalidade not in MODALIDADES_PNCP:
        raise ValueError(
            f"modalidade {modalidade} desconhecida. Códigos válidos: "
            f"{sorted(MODALIDADES_PNCP)} (ver listar_filtros_pncp para nomes)."
        )

    termos_e = _limpar_termos(termos_e)
    termos_ou = _limpar_termos(termos_ou)
    termos_nao = _limpar_termos(termos_nao)

    if not termos_e and not termos_ou:
        raise ValueError("informe ao menos um termo em termos_e ou termos_ou")

    if len(termos_ou) > _MAX_TERMOS_OU:
        raise ValueError(
            f"no máximo {_MAX_TERMOS_OU} termos_ou por chamada (cada um dispara "
            "uma sub-consulta separada ao PNCP)"
        )

    termos_nao_norm = {normalizar_para_busca(t) for t in termos_nao}
    termos_incluidos_norm = {normalizar_para_busca(t) for t in termos_e + termos_ou}
    conflito = sorted(termos_nao_norm & termos_incluidos_norm)
    if conflito:
        raise ValueError(
            f"termo(s) em termos_nao também presentes em termos_e/termos_ou "
            f"(contraditório): {conflito}"
        )

    # Mesma validação de buscar_pncp_texto: o índice aceita UM ano, e recusa
    # mal — vírgula devolve zero em silêncio, parâmetro repetido considera só
    # o último valor (medido em 2026-08-21).
    ano = _validar_ano(ano)

    limite_final = max(1, min(tamanho_pagina, 100))

    sub_consultas = (
        [termos_e + [alternativa] for alternativa in termos_ou] if termos_ou else [termos_e]
    )

    logger.info(
        "buscar_pncp_texto_booleano tipo=%s termos_e=%s termos_ou=%s termos_nao=%s "
        "sub_consultas=%d",
        tipo_documento, termos_e, termos_ou, termos_nao, len(sub_consultas),
    )

    filtros_comuns: dict[str, Any] = dict(
        uf=uf,
        municipio=municipio,
        modalidade=modalidade,
        ano=ano,
        tipo_instrumento=tipo_instrumento,
        tipo_contrato=tipo_contrato,
        orgao=orgao,
        unidade=unidade,
        esfera=esfera,
        poder=poder,
        fonte_orcamentaria=fonte_orcamentaria,
        tipo_margem_preferencia=tipo_margem_preferencia,
        exigencia_conteudo_nacional=exigencia_conteudo_nacional,
        possui_emenda_parlamentar=possui_emenda_parlamentar,
        permite_adesao=permite_adesao,
        status=status,
        janelas_meses=janelas_meses,
        ordenacao=ordenacao,
        pagina=1,
        tamanho_pagina=limite_final,
    )

    avisos: list[str] = []

    async def _sub_consulta(termos: list[str]) -> dict[str, Any]:
        termo_busca = " ".join(termos)
        try:
            return await buscar_pncp_texto(termo_busca, tipo_documento, **filtros_comuns)
        except Exception as exc:  # noqa: BLE001 - falha isolada de 1 sub-consulta não derruba as demais
            logger.warning("falha na sub-consulta %r: %s", termo_busca, exc)
            avisos.append(f"sub-consulta '{termo_busca}' falhou e foi ignorada: {exc}")
            return {"items": [], "total": 0}

    resultados_sub = await asyncio.gather(*(_sub_consulta(termos) for termos in sub_consultas))

    total_bruto = sum(r.get("total", 0) for r in resultados_sub)

    unidos: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for resultado in resultados_sub:
        for item in resultado.get("items", []):
            chave = item.get("numero_controle_pncp") or item.get("id")
            if chave and chave in vistos:
                continue
            if chave:
                vistos.add(chave)
            unidos.append(item)

    if termos_nao:
        antes = len(unidos)
        unidos = [
            item
            for item in unidos
            if not any(
                termo_norm
                in normalizar_para_busca(f"{item.get('title', '')} {item.get('description', '')}")
                for termo_norm in termos_nao_norm
            )
        ]
        excluidos = antes - len(unidos)
        if excluidos:
            avisos.append(
                f"{excluidos} resultado(s) removido(s) por conter termo(s) de termos_nao "
                "no título/descrição (pós-filtro no cliente, não um operador do PNCP)."
            )

    unidos.sort(key=lambda item: item.get("data_publicacao_pncp") or "", reverse=ordenacao != "data")

    items_finais = unidos[:limite_final]

    if len(unidos) > len(items_finais):
        avisos.append(
            f"{len(unidos) - len(items_finais)} resultado(s) adicional(is) descartado(s) "
            f"pelo limite de tamanho_pagina={limite_final} após união/dedup/exclusão."
        )

    if termos_ou:
        avisos.append(
            f"OU implementado como {len(sub_consultas)} sub-consulta(s) separada(s) ao PNCP "
            "(1 chamada de rede por termo de termos_ou), unidas e deduplicadas por "
            "numero_controle_pncp — não é um operador nativo do PNCP."
        )
    if termos_nao:
        avisos.append(
            "NÃO implementado como exclusão por substring no título/descrição já "
            "devolvidos pela busca — não é uma negação lógica do índice do PNCP nem "
            "garante ver o edital inteiro (teto de precisão conhecido, mesmo espírito "
            "de classificar_objeto_tic)."
        )

    return {
        "items": items_finais,
        "quantidade_retornada": len(items_finais),
        "total_bruto_por_subconsulta": total_bruto,
        "avisos": avisos,
    }
