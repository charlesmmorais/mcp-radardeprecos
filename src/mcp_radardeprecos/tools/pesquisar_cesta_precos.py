"""Tool MCP: pesquisa preços de vários itens de uma vez (cesta), com totais.

Simula o fluxo da ferramenta oficial "Pesquisa de Preços Lite"
(Compras.gov.br, v1.0, jun/26 — ver ``tutorial-pesquisa-de-precos-lite.pdf``,
estudado ao vivo): lá, o usuário monta uma "cotação" com vários itens
(cada um com quantidade/unidade), e a ferramenta busca os preços praticados
de cada item nos últimos 12 meses, calcula estatísticas (menor preço, média,
mediana, desvio padrão, coeficiente de variação) e soma um valor total da
pesquisa.

Este projeto já tinha todas as peças soltas (``buscar_precos_praticados_compras``
para coletar preços praticados, ``calcular_preco_referencia`` para o
tratamento estatístico) — faltava uma tool que orquestrasse as duas para uma
LISTA de itens de uma vez, com o total consolidado. Esta tool não
reimplementa nenhuma lógica: chama as duas tools existentes internamente,
item por item, com concorrência limitada (mesmo padrão de fan-out usado em
``buscar_contratacoes_pncp``/``buscar_contratos_compras``).

Diferente da ferramenta oficial (que também deixa o usuário DESCOBRIR o
código do catálogo dentro do próprio fluxo), aqui cada item já precisa vir
com ``codigo_item_catalogo`` resolvido — use ``descobrir_codigo_catalogo``
antes, um item de cada vez, para descobrir esse código a partir de uma
descrição livre.

Correção monetária integrada:
``corrigir_indice=True`` aplica ``atualizar_precos_indice`` (IPCA/IGP-M/
IPC-Fipe) aos preços coletados de CADA item ANTES de
``calcular_preco_referencia``, usando ``data_resultado`` como competência de
cada preço — traz a amostra toda para a mesma data-base antes do tratamento
estatístico, viabilizando a comparação entre preços coletados em datas
diferentes dentro da janela de pesquisa (Art. 3º, VI e VII, IN SEGES/ME
65/2021). Best-effort por item: uma falha na correção de um item (ex.: série
do SGS indisponível) não derruba a cesta inteira — o item cai de volta para
o cálculo SEM correção, com aviso explicando.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..domain.dominios import (
    INDICES_CORRECAO_MONETARIA,
    METODOS_CALCULO_PRECO,
    TIPOS_ITEM_CATALOGO_COMPRAS,
)
from ..logging_utils import get_logger
from .atualizar_precos_indice import atualizar_precos_indice as _atualizar_precos_indice
from .buscar_precos_praticados_compras import (
    buscar_precos_praticados_compras as _buscar_precos_praticados_compras,
)
from .calcular_preco_referencia import calcular_preco_referencia as _calcular_preco_referencia

logger = get_logger(__name__)

# Trava de segurança contra cestas muito grandes (cada item dispara pelo
# menos uma chamada de rede) — mesmo espírito dos limites de segurança já
# usados em outras tools deste projeto (ex.: max_paginas em buscar_pncp_texto).
_MAX_ITENS_CESTA = 30
# Concorrência limitada no fan-out de itens — mesmo padrão de
# buscar_contratacoes_pncp/buscar_contratos_compras, para não estourar o
# número de conexões simultâneas contra a API do Compras.gov.br.
_CONCORRENCIA_MAXIMA = 5


async def pesquisar_cesta_precos(
    itens: list[dict[str, Any]],
    uf: str | None = None,
    codigo_municipio: int | None = None,
    codigo_uasg: str | None = None,
    apenas_com_resultado: bool = True,
    metodo: str | None = None,
    limite_precos_por_item: int = 20,
    corrigir_indice: bool = False,
    indice: str = "ipca",
    data_base: str | None = None,
) -> dict[str, Any]:
    """Pesquisa preços praticados de vários itens de uma vez (cesta), com total.

    Cada item da lista ``itens`` precisa de ``codigo_item_catalogo`` (CATMAT
    ou CATSER, já descoberto via ``descobrir_codigo_catalogo``) e
    ``tipo_item`` ("material" ou "servico"). Para cada item, esta tool busca
    os preços praticados (``buscar_precos_praticados_compras``) e calcula o
    preço de referência (``calcular_preco_referencia``, padrão "media_saneada"),
    multiplicando pelo ``quantidade`` do item para obter o valor total do
    item — e soma todos os itens no ``valor_total_cesta``, igual ao "Valor
    total da pesquisa de preços" da ferramenta oficial "Pesquisa de Preços
    Lite" do Compras.gov.br.

    Os filtros ``uf``/``codigo_municipio``/``codigo_uasg``/
    ``apenas_com_resultado``/``metodo``/``limite_precos_por_item`` informados
    aqui valem como padrão para TODOS os itens da cesta, mas cada item pode
    sobrescrever qualquer um deles individualmente (chaves com o mesmo nome
    dentro do dicionário do item) — por exemplo, para pesquisar um item
    específico numa UF diferente do restante da cesta.

    Args:
        itens: Lista de itens da cesta (máx. 30). Cada item é um dicionário
            com:
            - ``codigo_item_catalogo`` (obrigatório): código CATMAT/CATSER.
            - ``tipo_item`` (obrigatório): "material" ou "servico".
            - ``descricao`` (opcional): rótulo livre para identificar o item
              no resultado (ex.: "Notebook i5 8GB"). Se omitido, usa
              ``descricao_item`` do primeiro preço encontrado, ou o próprio
              código.
            - ``quantidade`` (opcional, padrão 1): quantidade a contratar —
              multiplica o preço de referência para compor o valor total do
              item.
            - ``uf``/``codigo_municipio``/``codigo_uasg``/
              ``apenas_com_resultado``/``metodo``/``limite_precos_por_item``
              (opcionais): sobrescrevem o valor padrão desta chamada só para
              este item.
            - ``corrigir_indice``/``indice``/``data_base`` (opcionais):
              sobrescrevem, só para este item, os parâmetros abaixo de mesmo
              nome.
        uf: Sigla da UF padrão para todos os itens (ex: SP, DF).
        codigo_municipio: Código IBGE do município padrão.
        codigo_uasg: Código da UASG padrão.
        apenas_com_resultado: Se True (padrão), considera só compras já
            concluídas com preço efetivamente pago (não estimativas).
        metodo: Método de cálculo padrão ("media_saneada", "escore_z",
            "mediana" ou "minimo" — ver ``calcular_preco_referencia``).
            Padrão "media_saneada" quando omitido.
        limite_precos_por_item: Número máximo de preços coletados por item
            antes do tratamento estatístico (padrão 20, máximo 100).
        corrigir_indice: Se True, aplica
            correção monetária (``atualizar_precos_indice``) aos preços
            coletados de CADA item, usando ``data_resultado`` como
            competência, ANTES de calcular o preço de referência — traz toda
            a amostra à mesma data-base antes do tratamento estatístico.
            Preços sem ``data_resultado`` são ignorados na correção (e no
            cálculo), com aviso. Falha isolada na correção de um item (ex.:
            série do SGS indisponível) não derruba a cesta — o item cai de
            volta para o cálculo SEM correção, com aviso explicando.
        indice: Índice usado quando ``corrigir_indice=True`` — ``"ipca"``
            (padrão), ``"igpm"`` ou ``"ipc_fipe"`` (ver
            ``atualizar_precos_indice``).
        data_base: Competência-alvo "AAAA-MM" da correção monetária. Padrão:
            a última competência já publicada pelo índice escolhido (ver
            ``atualizar_precos_indice``). Só usado com ``corrigir_indice=True``.

    Returns:
        Dicionário com ``quantidade_itens``, ``valor_total_cesta`` (soma dos
        valores totais dos itens com preço encontrado), ``itens`` — lista
        com, por item: ``descricao``, ``codigo_item_catalogo``, ``tipo_item``,
        ``quantidade``, ``metodo_utilizado``, ``preco_referencia``,
        ``valor_total_item``, ``estatisticas`` (média, mediana, mínimo,
        máximo, desvio padrão, CV%), ``quantidade_amostra`` e ``avisos``
        (repassados de ``calcular_preco_referencia``, ex.: amostra pequena ou
        CV alto) — e ``avisos_gerais`` (itens sem nenhum preço encontrado).
        Quando ``corrigir_indice=True`` e a correção foi aplicada com sucesso
        a um item, esse item também traz ``correcao_monetaria`` (``indice``,
        ``indice_chave``, ``data_base`` e ``quantidade_precos_corrigidos``) —
        pronto para repassar a ``gerar_memoria_pesquisa(correcao_monetaria=...)``.
    """
    if not itens:
        raise ValueError("itens não pode ser uma lista vazia")
    if len(itens) > _MAX_ITENS_CESTA:
        raise ValueError(f"itens não pode ter mais de {_MAX_ITENS_CESTA} elementos")
    if corrigir_indice and indice not in INDICES_CORRECAO_MONETARIA:
        raise ValueError(
            f"indice deve ser um de {tuple(INDICES_CORRECAO_MONETARIA)}, recebido {indice!r}"
        )
    for idx, item in enumerate(itens):
        if not item.get("codigo_item_catalogo"):
            raise ValueError(f"itens[{idx}] não tem codigo_item_catalogo")
        tipo_item_item = item.get("tipo_item")
        if tipo_item_item not in TIPOS_ITEM_CATALOGO_COMPRAS:
            raise ValueError(
                f"itens[{idx}].tipo_item deve ser um de {TIPOS_ITEM_CATALOGO_COMPRAS}"
            )
        metodo_item = item.get("metodo")
        if metodo_item is not None and metodo_item not in METODOS_CALCULO_PRECO:
            raise ValueError(f"itens[{idx}].metodo deve ser um de {METODOS_CALCULO_PRECO}")

    logger.info(
        "pesquisar_cesta_precos quantidade_itens=%d corrigir_indice=%s indice=%s",
        len(itens), corrigir_indice, indice,
    )

    semaforo = asyncio.Semaphore(_CONCORRENCIA_MAXIMA)

    async def _processar_item(idx: int, item: dict[str, Any]) -> dict[str, Any]:
        codigo = item["codigo_item_catalogo"]
        tipo_item_item = item["tipo_item"]
        quantidade = item.get("quantidade", 1) or 1
        metodo_item = item.get("metodo", metodo)
        limite_item = item.get("limite_precos_por_item", limite_precos_por_item)

        async with semaforo:
            try:
                resposta_precos = await _buscar_precos_praticados_compras(
                    codigo,
                    tipo_item_item,
                    uf=item.get("uf", uf),
                    codigo_municipio=item.get("codigo_municipio", codigo_municipio),
                    codigo_uasg=item.get("codigo_uasg", codigo_uasg),
                    apenas_com_resultado=item.get(
                        "apenas_com_resultado", apenas_com_resultado
                    ),
                    limite=limite_item,
                )
            except Exception as exc:  # noqa: BLE001 - falha isolada não derruba a cesta inteira
                logger.warning(
                    "falha ao buscar preços do item %d (codigo=%s tipo=%s): %s",
                    idx, codigo, tipo_item_item, exc,
                )
                return {
                    "descricao": item.get("descricao") or f"item {idx + 1} (código {codigo})",
                    "codigo_item_catalogo": codigo,
                    "tipo_item": tipo_item_item,
                    "quantidade": quantidade,
                    "preco_referencia": None,
                    "valor_total_item": None,
                    "avisos": [f"Falha ao consultar preços praticados: {exc}"],
                }

        precos_brutos = resposta_precos.get("precos", [])

        descricao = item.get("descricao")
        if not descricao and precos_brutos:
            descricao = precos_brutos[0].get("descricao_item")
        descricao = descricao or f"item {idx + 1} (código {codigo})"

        valores = [
            p["preco_unitario"]
            for p in precos_brutos
            if isinstance(p.get("preco_unitario"), (int, float)) and p["preco_unitario"] > 0
        ]

        if not valores:
            return {
                "descricao": descricao,
                "codigo_item_catalogo": codigo,
                "tipo_item": tipo_item_item,
                "quantidade": quantidade,
                "preco_referencia": None,
                "valor_total_item": None,
                "avisos": [
                    "Nenhum preço praticado encontrado para este item no período "
                    "consultado — não é possível calcular preço de referência."
                ],
            }

        # correção monetária ANTES do cálculo do
        # preço de referência, item a item — best-effort (falha isolada cai
        # de volta para os preços sem correção, com aviso).
        avisos_correcao: list[str] = []
        correcao_info: dict[str, Any] | None = None
        item_corrigir_indice = item.get("corrigir_indice", corrigir_indice)
        if item_corrigir_indice:
            item_indice = item.get("indice", indice)
            item_data_base = item.get("data_base", data_base)
            entradas_corrigir = [
                {"valor": p["preco_unitario"], "data": p["data_resultado"]}
                for p in precos_brutos
                if isinstance(p.get("preco_unitario"), (int, float))
                and p["preco_unitario"] > 0
                and p.get("data_resultado")
            ]
            ignorados = len(valores) - len(entradas_corrigir)
            if not entradas_corrigir:
                avisos_correcao.append(
                    "corrigir_indice=True, mas nenhum preço deste item tem data_resultado "
                    "— preço de referência calculado SEM correção monetária."
                )
            else:
                try:
                    resultado_correcao = await _atualizar_precos_indice(
                        entradas_corrigir, data_base=item_data_base, indice=item_indice,
                    )
                    valores = resultado_correcao["valores_atualizados"]
                    correcao_info = {
                        "indice": resultado_correcao["indice"],
                        "indice_chave": resultado_correcao["indice_chave"],
                        "data_base": resultado_correcao["data_base"],
                        "quantidade_precos_corrigidos": resultado_correcao["quantidade"],
                    }
                    avisos_correcao.extend(resultado_correcao["avisos"])
                    if ignorados:
                        avisos_correcao.append(
                            f"{ignorados} preço(s) sem data_resultado foram ignorados na "
                            "correção monetária (fora do preço de referência corrigido)."
                        )
                except Exception as exc:  # noqa: BLE001 - correção monetária é best-effort por item
                    logger.warning(
                        "falha na correção monetária do item %d (codigo=%s indice=%s): %s",
                        idx, codigo, item_indice, exc,
                    )
                    avisos_correcao.append(
                        f"Falha ao aplicar correção monetária (índice={item_indice}): {exc}. "
                        "Preço de referência calculado SEM correção monetária para este item."
                    )

        calculo = await _calcular_preco_referencia(valores, metodo_item)
        valor_total_item = round(calculo["preco_referencia"] * quantidade, 4)

        resultado_item: dict[str, Any] = {
            "descricao": descricao,
            "codigo_item_catalogo": codigo,
            "tipo_item": tipo_item_item,
            "quantidade": quantidade,
            "metodo_utilizado": calculo["metodo_utilizado"],
            "preco_referencia": calculo["preco_referencia"],
            "valor_total_item": valor_total_item,
            "estatisticas": calculo["estatisticas"],
            "quantidade_amostra": len(valores),
            "avisos": calculo["avisos"] + avisos_correcao,
        }
        if correcao_info:
            resultado_item["correcao_monetaria"] = correcao_info
        return resultado_item

    resultados_itens = await asyncio.gather(
        *(_processar_item(idx, item) for idx, item in enumerate(itens))
    )

    valor_total_cesta = round(
        sum(r["valor_total_item"] for r in resultados_itens if r["valor_total_item"] is not None),
        4,
    )

    avisos_gerais: list[str] = []
    itens_sem_preco = [r["descricao"] for r in resultados_itens if r["preco_referencia"] is None]
    if itens_sem_preco:
        avisos_gerais.append(
            f"{len(itens_sem_preco)} de {len(itens)} item(ns) sem preço encontrado, "
            f"não incluído(s) no valor total da cesta: {', '.join(itens_sem_preco)}."
        )

    return {
        "quantidade_itens": len(itens),
        "valor_total_cesta": valor_total_cesta,
        "itens": resultados_itens,
        "avisos_gerais": avisos_gerais,
    }
