"""Tool MCP: classifica itens de uma compra pela Curva ABC (Pareto 80/20).

Implementa a recomendação de "Pesquisa de preços — um guia prático de
sobrevivência" (Franklin Brasil, Set/2020) para a fase de Planejamento —
ver o guia de boas práticas de pesquisa de preços, seção 2. Assim como
``calcular_preco_referencia``, esta é uma tool **pura**: não consulta
nenhuma API, apenas classifica uma lista de itens já coletados (por
exemplo, do Plano de Contratação Anual, de um edital em elaboração, ou dos
resultados de ``buscar_contratacoes_pncp``/``buscar_pncp_texto``).
"""
from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)

# Faixas-padrão da Curva ABC (Pareto 80/20): grupo A concentra ~80% do valor
# total em poucos itens, grupo B vai até 95%, grupo C são os 5% finais,
# tipicamente a maioria dos itens em quantidade. Configuráveis porque
# algumas organizações adotam variações (ex.: 70/90) — ver Acórdão TCU
# 2.096/2013-P, que recomenda o critério mas não fixa os percentuais.
_LIMITE_CLASSE_A_PADRAO = 80.0
_LIMITE_CLASSE_B_PADRAO = 95.0


async def classificar_curva_abc(
    itens: list[dict[str, Any]],
    limite_classe_a: float = _LIMITE_CLASSE_A_PADRAO,
    limite_classe_b: float = _LIMITE_CLASSE_B_PADRAO,
) -> dict[str, Any]:
    """Classifica itens de uma compra em grupos A/B/C pelo valor acumulado (Curva ABC).

    Ordena os itens por valor (decrescente) e calcula o percentual
    acumulado do valor total: grupo A são os itens de maior valor que juntos
    somam até ``limite_classe_a`` (padrão 80%) do total — tipicamente poucos
    itens, que concentram a maior parte do valor da compra e por isso
    exigem pesquisa de preços mais exaustiva (mais fontes, amostra maior).
    Grupo B vai até ``limite_classe_b`` (padrão 95%) — pesquisa moderada.
    Grupo C são os itens restantes — tipicamente numerosos, mas de baixo
    valor individual e agregado, onde uma pesquisa mais simplificada é
    aceitável. Critério recomendado pelo Acórdão TCU 2.096/2013-P (não fixa
    os percentuais exatos — 80/95 é a convenção mais comum do método
    Pareto, mas pode ser ajustada via os parâmetros).

    Esta tool é **pura** — não acessa nenhuma API. Os itens devem ser
    previamente coletados (ex.: de um Plano de Contratação Anual, de um
    edital em elaboração, ou de buscas já feitas com as demais tools deste
    servidor).

    Args:
        itens: Lista de itens a classificar. Cada item é um dicionário com
            ao menos a chave ``valor`` (número positivo — valor total do
            item na compra, isto é, quantidade × preço unitário estimado,
            não o preço unitário isolado). Quaisquer outras chaves (ex.:
            ``descricao``, ``codigo_catmat``) são preservadas no retorno
            para identificar o item.
        limite_classe_a: Percentual acumulado (0-100) até o qual os itens
            são classe A. Padrão 80.
        limite_classe_b: Percentual acumulado (0-100) até o qual os itens
            são classe B (acima de ``limite_classe_a``). Itens além desse
            percentual são classe C. Padrão 95. Deve ser maior que
            ``limite_classe_a``.

    Returns:
        Dicionário com:
        - ``valor_total``: soma do valor de todos os itens.
        - ``itens_classificados``: a lista de entrada, na ordem decrescente
          de valor, cada item acrescido de ``percentual_individual``,
          ``percentual_acumulado`` e ``classe`` ("A", "B" ou "C").
        - ``resumo_por_classe``: para cada classe presente, ``quantidade_itens``,
          ``percentual_da_quantidade``, ``valor_total_classe`` e
          ``percentual_do_valor``.
        - ``avisos``: alertas (ex.: menos de 3 itens, o que torna a
          classificação pouco informativa — a Curva ABC pressupõe um
          conjunto de itens grande o bastante para haver concentração de
          valor a identificar).
    """
    if not itens:
        raise ValueError("itens não pode ser uma lista vazia")
    if not (0 < limite_classe_a < limite_classe_b <= 100):
        raise ValueError(
            "limites inválidos: exige-se 0 < limite_classe_a < limite_classe_b <= 100"
        )

    for i, item in enumerate(itens):
        valor = item.get("valor")
        if valor is None or not isinstance(valor, (int, float)) or valor <= 0:
            raise ValueError(
                f"item {i} tem 'valor' inválido ({valor!r}) — deve ser um número positivo"
            )

    logger.info(
        "classificar_curva_abc quantidade_itens=%d limite_classe_a=%s limite_classe_b=%s",
        len(itens), limite_classe_a, limite_classe_b,
    )

    itens_ordenados = sorted(itens, key=lambda it: it["valor"], reverse=True)
    valor_total = sum(it["valor"] for it in itens_ordenados)

    itens_classificados: list[dict[str, Any]] = []
    acumulado = 0.0
    for item in itens_ordenados:
        acumulado += item["valor"]
        percentual_acumulado = (acumulado / valor_total) * 100
        percentual_individual = (item["valor"] / valor_total) * 100
        if percentual_acumulado <= limite_classe_a:
            classe = "A"
        elif percentual_acumulado <= limite_classe_b:
            classe = "B"
        else:
            classe = "C"
        itens_classificados.append(
            {
                **item,
                "percentual_individual": round(percentual_individual, 2),
                "percentual_acumulado": round(percentual_acumulado, 2),
                "classe": classe,
            }
        )

    resumo_por_classe: dict[str, dict[str, Any]] = {}
    for classe in ("A", "B", "C"):
        do_grupo = [it for it in itens_classificados if it["classe"] == classe]
        if not do_grupo:
            continue
        valor_classe = sum(it["valor"] for it in do_grupo)
        resumo_por_classe[classe] = {
            "quantidade_itens": len(do_grupo),
            "percentual_da_quantidade": round(len(do_grupo) / len(itens_ordenados) * 100, 2),
            "valor_total_classe": round(valor_classe, 4),
            "percentual_do_valor": round(valor_classe / valor_total * 100, 2),
        }

    avisos: list[str] = []
    if len(itens) < 3:
        avisos.append(
            f"Apenas {len(itens)} item(ns) informado(s) — a Curva ABC pressupõe um "
            "conjunto maior de itens para identificar concentração de valor; com "
            "poucos itens, a classificação tem pouco valor prático."
        )

    return {
        "valor_total": round(valor_total, 4),
        "itens_classificados": itens_classificados,
        "resumo_por_classe": resumo_por_classe,
        "avisos": avisos,
    }
