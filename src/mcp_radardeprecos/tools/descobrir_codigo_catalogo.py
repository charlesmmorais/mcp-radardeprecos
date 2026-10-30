"""Tool MCP: descobre códigos de catálogo (CATMAT/CATSER) a partir de texto livre."""
from __future__ import annotations

from typing import Any

from ..clients import compras_client
from ..domain.dominios import TIPOS_ITEM_CATALOGO_COMPRAS
from ..logging_utils import get_logger
from ..utils.texto_busca import (
    QUALIDADE_PARCIAL,
    classificar_correspondencia,
    normalizar_para_busca,
    ordem_qualidade,
)

logger = get_logger(__name__)

# Número de categorias (PDM/classe) para as quais buscamos uma amostra real
# de itens — limitado para não multiplicar chamadas de rede a cada busca.
_MAX_CATEGORIAS_COM_ITENS = 3
_MAX_ITENS_POR_CATEGORIA = 5


def _rankear(candidatos: list[tuple[str, dict[str, Any]]], termo_norm: str) -> tuple[list[tuple[str, dict[str, Any]]], int]:
    """Classifica, ordena e poda candidatos pela qualidade da correspondência.

    ``candidatos``: pares (nome_para_busca, registro_bruto). Retorna a lista
    de pares (qualidade, registro), ordenada por qualidade e tamanho do
    nome, e a quantidade de correspondências "parciais" DESCARTADAS.

    Regra (v0.2.1, motivada pelo caso real "TIC" → turísTICo/estatísTICo/
    plásTICo): correspondência "parcial" (termo só aparece dentro de outra
    palavra) é descartada sempre que existe ao menos uma correspondência
    melhor (exata/palavra inteira). Se SÓ existirem parciais, elas são
    mantidas (um termo que só ocorre dentro de palavras continua
    encontrável), com aviso.
    """
    classificados: list[tuple[str, str, dict[str, Any]]] = []
    for nome, registro in candidatos:
        qualidade = classificar_correspondencia(termo_norm, normalizar_para_busca(nome))
        if qualidade is not None:
            classificados.append((qualidade, nome, registro))

    tem_melhor_que_parcial = any(q != QUALIDADE_PARCIAL for q, _, _ in classificados)
    descartadas = 0
    if tem_melhor_que_parcial:
        descartadas = sum(1 for q, _, _ in classificados if q == QUALIDADE_PARCIAL)
        classificados = [c for c in classificados if c[0] != QUALIDADE_PARCIAL]

    classificados.sort(key=lambda c: (ordem_qualidade(c[0]), len(c[1] or "")))
    return [(q, r) for q, _, r in classificados], descartadas


def _aviso_descartes(descartadas: int) -> str:
    return (
        f"{descartadas} correspondência(s) em que o termo só aparece DENTRO de outra "
        "palavra (ex.: 'TIC' em 'turíSTICo') foram descartadas por haver correspondências "
        "de palavra inteira — se procurava exatamente isso, use um termo mais específico."
    )


async def descobrir_codigo_catalogo(
    termo_busca: str,
    tipo_item: str = "material",
    limite: int = 10,
) -> dict[str, Any]:
    """Descobre códigos CATMAT/CATSER a partir de uma descrição textual livre.

    Resolve o pré-requisito manual de ``buscar_precos_praticados_compras``
    (que exige ``codigo_item_catalogo`` já conhecido): o caso mais comum é o
    usuário saber o NOME do item/serviço, não o código.

    **Limitação real da API, confirmada ao vivo:** nem o Compras.gov.br nem
    o PNCP expõem busca textual ("contém") sobre a descrição de itens de
    catálogo — o parâmetro ``descricaoItem`` exige igualdade EXATA com o
    campo completo, e o catálogo de serviços não tem NENHUM parâmetro de
    texto. Esta tool contorna isso buscando no lado do cliente
    (case/acento-insensível) sobre os NOMES do catálogo:

    - ``tipo_item="material"`` (CATMAT): sobre os ~15 mil PDMs ativos
      (família de produto), cacheados por 1 dia;
    - ``tipo_item="servico"`` (CATSER): sobre nomes de GRUPO e CLASSE
      (~276 classes, cacheadas) — cobertura menor; para listar os serviços
      individuais (código CATSER real) de uma classe encontrada, use a tool
      ``listar_itens_catalogo``.

    **Ranking por qualidade:** cada resultado traz
    ``qualidade_correspondencia`` — ``"exata"`` (o nome é o termo),
    ``"palavra_inteira"`` (toda palavra do termo aparece como palavra
    inteira) ou ``"parcial"`` (termo só aparece dentro de outra palavra,
    ex.: "TIC" em "turíSTICo"). Correspondências parciais são DESCARTADAS
    quando existem melhores (com aviso contando os descartes) — só são
    retornadas quando são a única opção.

    Args:
        termo_busca: Texto livre (ex.: "notebook", "TIC", "serviço de limpeza").
        tipo_item: "material" (CATMAT) ou "servico" (CATSER). Padrão "material".
        limite: Máximo de categorias a retornar (padrão 10, máximo 50).

    Returns:
        Dicionário com ``termo_busca``, ``tipo_item``,
        ``total_correspondencias``, ``resultados`` (cada um com códigos da
        hierarquia, ``qualidade_correspondencia`` e ``itens_exemplo`` — até
        5, preenchidos só para as 3 primeiras categorias; para as demais,
        use ``listar_itens_catalogo``) e ``avisos``.
    """
    if tipo_item not in TIPOS_ITEM_CATALOGO_COMPRAS:
        raise ValueError(f"tipo_item deve ser um de {TIPOS_ITEM_CATALOGO_COMPRAS}")
    if not termo_busca or not termo_busca.strip():
        raise ValueError("termo_busca não pode ser vazio")

    limite = max(1, min(limite, 50))
    termo_norm = normalizar_para_busca(termo_busca)
    logger.info(
        "descobrir_codigo_catalogo termo_busca=%s tipo_item=%s limite=%s",
        termo_busca, tipo_item, limite,
    )

    if tipo_item == "material":
        return await _descobrir_material(termo_norm, termo_busca, limite)
    return await _descobrir_servico(termo_norm, termo_busca, limite)


def _aviso_amostras(n_resultados: int, tipo_item: str) -> list[str]:
    if n_resultados <= _MAX_CATEGORIAS_COM_ITENS:
        return []
    return [
        f"itens_exemplo foram buscados só para as {_MAX_CATEGORIAS_COM_ITENS} primeiras "
        "categorias (para limitar chamadas de rede) — para listar os itens das demais, "
        f"use listar_itens_catalogo(tipo_item='{tipo_item}', codigo=...)."
    ]


async def _descobrir_material(termo_norm: str, termo_busca: str, limite: int) -> dict[str, Any]:
    pdms = await compras_client.listar_pdms_material_ativos()
    ranqueados, descartadas = _rankear(
        [(p.get("nomePdm", ""), p) for p in pdms], termo_norm
    )

    resultados: list[dict[str, Any]] = [
        {
            "codigo_pdm": p.get("codigoPdm"),
            "nome_pdm": p.get("nomePdm"),
            "codigo_classe": p.get("codigoClasse"),
            "nome_classe": p.get("nomeClasse"),
            "codigo_grupo": p.get("codigoGrupo"),
            "nome_grupo": p.get("nomeGrupo"),
            "qualidade_correspondencia": qualidade,
            "itens_exemplo": [],
        }
        for qualidade, p in ranqueados[:limite]
    ]

    for resultado in resultados[:_MAX_CATEGORIAS_COM_ITENS]:
        codigo_pdm = resultado["codigo_pdm"]
        if codigo_pdm is None:
            continue
        resposta_itens = await compras_client.listar_itens_material_por_pdm(
            codigo_pdm, tamanho_pagina=_MAX_ITENS_POR_CATEGORIA
        )
        resultado["itens_exemplo"] = [
            {"codigo_item": i.get("codigoItem"), "descricao_item": i.get("descricaoItem")}
            for i in (resposta_itens or {}).get("resultado", []) or []
        ][:_MAX_ITENS_POR_CATEGORIA]

    avisos = _aviso_amostras(len(resultados), "material")
    if descartadas:
        avisos.append(_aviso_descartes(descartadas))
    resposta: dict[str, Any] = {
        "termo_busca": termo_busca,
        "tipo_item": "material",
        "total_correspondencias": len(ranqueados),
        "resultados": resultados,
        "avisos": avisos,
    }
    if not ranqueados:
        resposta["aviso"] = (
            "Nenhum PDM (família de produto) do CATMAT contém esse termo no "
            "nome. Tente um termo mais genérico, no singular, ou sem "
            "adjetivos/marcas (ex.: 'notebook' em vez de 'notebook dell "
            "usado para programação')."
        )
    return resposta


async def _descobrir_servico(termo_norm: str, termo_busca: str, limite: int) -> dict[str, Any]:
    classes = await compras_client.listar_classes_servico()

    def _nome_para_busca(c: dict[str, Any]) -> str:
        # Grupo e classe entram juntos na comparação (mesma cobertura de
        # antes), mas o ranking usa o nome combinado.
        return f"{c.get('nomeClasse', '')} {c.get('nomeGrupo', '')}"

    ranqueados, descartadas = _rankear(
        [(_nome_para_busca(c), c) for c in classes], termo_norm
    )

    resultados: list[dict[str, Any]] = [
        {
            "codigo_classe": c.get("codigoClasse"),
            "nome_classe": c.get("nomeClasse"),
            "codigo_grupo": c.get("codigoGrupo"),
            "nome_grupo": c.get("nomeGrupo"),
            "qualidade_correspondencia": qualidade,
            "itens_exemplo": [],
        }
        for qualidade, c in ranqueados[:limite]
    ]

    for resultado in resultados[:_MAX_CATEGORIAS_COM_ITENS]:
        codigo_classe = resultado["codigo_classe"]
        if codigo_classe is None:
            continue
        resposta_itens = await compras_client.listar_itens_servico_por_classe(
            codigo_classe, tamanho_pagina=_MAX_ITENS_POR_CATEGORIA
        )
        resultado["itens_exemplo"] = [
            {"codigo_servico": i.get("codigoServico"), "nome_servico": i.get("nomeServico")}
            for i in (resposta_itens or {}).get("resultado", []) or []
        ][:_MAX_ITENS_POR_CATEGORIA]

    avisos = _aviso_amostras(len(resultados), "servico")
    if descartadas:
        avisos.append(_aviso_descartes(descartadas))
    resposta: dict[str, Any] = {
        "termo_busca": termo_busca,
        "tipo_item": "servico",
        "total_correspondencias": len(ranqueados),
        "resultados": resultados,
        "avisos": avisos,
    }
    if not ranqueados:
        resposta["aviso"] = (
            "Nenhuma classe do CATSER contém esse termo no nome de grupo/"
            "classe. Diferente do CATMAT, o catálogo de serviços não tem um "
            "nível de busca mais granular, e a API oficial não permite "
            "busca textual em nenhum nível do catálogo de serviços "
            "(confirmado na especificação OpenAPI: consultarItemServico só "
            "aceita códigos). Tente um termo mais genérico (ex.: 'limpeza' "
            "em vez de um serviço muito específico)."
        )
    return resposta
