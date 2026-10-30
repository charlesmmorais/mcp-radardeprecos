"""Tool MCP: atualização monetária de preços históricos por um índice do SGS/Banco Central.

Aceita os três índices de ``domain.dominios.INDICES_CORRECAO_MONETARIA``,
todos públicos, sem credencial e no mesmo formato (``clients/bcb_client.py``):

- ``"ipca"`` (padrão) — índice oficial de inflação, referência da
  IN SEGES/ME 65/2021 para pesquisa de preços.
- ``"igpm"`` — contratos com cláusula de reajuste IGP-M (aluguéis,
  contratos administrativos antigos). Pode ter DEFLAÇÃO (variação
  negativa/fator < 1), diferente do IPCA — a fórmula de fator composto já
  trata isso naturalmente, sem lógica especial.
- ``"ipc_fipe"`` — cesta do município de São Paulo, para comparações
  regionais SP.

Ao escolher um índice diferente de ``"ipca"``, um aviso fixo lembra que a
escolha deve ser justificada na formalização da pesquisa (Art. 3º, VI, da
IN 65/2021 — justificativa da metodologia).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..clients import bcb_client
from ..domain.dominios import INDICES_CORRECAO_MONETARIA
from ..logging_utils import get_logger

logger = get_logger(__name__)

_RE_COMPETENCIA = re.compile(r"^(\d{4})-(\d{2})")

_AVISO_INDICE_NAO_PADRAO = (
    "O IPCA é o índice padrão para pesquisa de preços conforme a IN SEGES/ME 65/2021 "
    "(Art. 3º, VI) — a escolha de outro índice deve ser justificada na formalização da "
    "pesquisa."
)


def _parse_competencia(valor: str) -> tuple[int, int]:
    """Extrai (ano, mês) de "AAAA-MM", "AAAA-MM-DD" ou timestamp ISO."""
    m = _RE_COMPETENCIA.match(str(valor).strip())
    if not m:
        raise ValueError(
            f"data {valor!r} inválida — use 'AAAA-MM' ou 'AAAA-MM-DD' (ISO)"
        )
    ano, mes = int(m.group(1)), int(m.group(2))
    if not 1 <= mes <= 12:
        raise ValueError(f"data {valor!r} inválida — mês fora de 1..12")
    return ano, mes


def _indice_temporal(ano: int, mes: int) -> int:
    return ano * 12 + (mes - 1)


async def atualizar_precos_indice(
    precos: list[dict[str, Any]],
    data_base: str | None = None,
    indice: str = "ipca",
) -> dict[str, Any]:
    """Atualiza preços históricos a valor presente por um índice do SGS/Banco Central (correção monetária).

    Numa pesquisa de preços, referências coletadas ao longo da janela de até
    12 meses (ou mais) não são diretamente comparáveis entre si: um preço de
    12 meses atrás está em moeda "mais fraca" (ou, no caso de deflação, mais
    "forte") que um do mês passado. Esta tool traz todos para a mesma
    data-base usando a variação mensal do índice escolhido — fonte oficial,
    pública, sem credencial —, viabilizando a análise crítica prevista na
    IN SEGES/ME nº 65/2021 (Art. 5º) antes de ``calcular_preco_referencia``.

    Convenção de cálculo (número-índice): um preço observado na competência
    ``M`` está expresso em moeda de ``M``; o fator de atualização até a
    data-base ``B`` é o produto de ``(1 + variação_mensal)`` das competências
    ``M+1`` até ``B``, inclusive. Preço na mesma competência da base tem
    fator 1,0 (nenhum ajuste). A fórmula já trata deflação corretamente
    (fator < 1) sem lógica especial — relevante para IGP-M, que historicamente
    tem meses de variação negativa.

    Args:
        precos: Lista de dicionários, cada um com ``valor`` (numérico > 0) e
            ``data`` ("AAAA-MM", "AAAA-MM-DD" ou timestamp ISO — só ano/mês
            são usados; ex.: a ``data_resultado`` devolvida por
            ``buscar_precos_praticados_compras``). Chaves extras (fornecedor,
            órgão etc.) são preservadas no resultado.
        data_base: Competência-alvo "AAAA-MM". Padrão: a última competência
            já publicada pelo índice escolhido. Informar uma competência
            ainda sem publicação gera ``ValueError`` (a tool não extrapola
            variação futura).
        indice: Chave do índice — ``"ipca"`` (padrão), ``"igpm"`` ou
            ``"ipc_fipe"`` (ver ``domain.dominios.INDICES_CORRECAO_MONETARIA``
            para a série SGS e o uso típico de cada um).

    Returns:
        Dicionário com ``indice`` (nome oficial + série SGS efetivamente
        usada, ex.: "IGP-M (FGV, série 189 do SGS/Banco Central)"),
        ``data_base`` efetiva, ``precos_atualizados`` (cada item com
        ``valor_original``, ``competencia``, ``fator_atualizacao`` e
        ``valor_atualizado``, mais as chaves extras de entrada),
        ``valores_atualizados`` (lista simples, pronta para o parâmetro
        ``precos`` de ``calcular_preco_referencia``) e ``avisos`` (aviso fixo
        quando ``indice != "ipca"``; preço com competência posterior à
        data-base fica com fator 1,0).

    Raises:
        ValueError: ``indice`` desconhecido; entrada malformada; data-base
            sem publicação do índice escolhido; competência faltante na
            série.
    """
    if indice not in INDICES_CORRECAO_MONETARIA:
        raise ValueError(
            f"indice deve ser um de {tuple(INDICES_CORRECAO_MONETARIA)}, recebido {indice!r}"
        )
    info_indice = INDICES_CORRECAO_MONETARIA[indice]
    codigo_serie = info_indice["serie_sgs"]

    if not isinstance(precos, list) or not precos:
        raise ValueError("precos deve ser uma lista não vazia de {valor, data}")

    entradas: list[tuple[float, int, dict[str, Any]]] = []
    for i, p in enumerate(precos):
        if not isinstance(p, dict) or "valor" not in p or "data" not in p:
            raise ValueError(f"precos[{i}] deve ser um dicionário com 'valor' e 'data'")
        try:
            valor = float(p["valor"])
        except (TypeError, ValueError):
            raise ValueError(f"precos[{i}].valor {p['valor']!r} não é numérico") from None
        if valor <= 0:
            raise ValueError(f"precos[{i}].valor deve ser positivo (recebido {valor})")
        ano, mes = _parse_competencia(p["data"])
        entradas.append((valor, _indice_temporal(ano, mes), p))

    logger.info(
        "atualizar_precos_indice indice=%s n=%s data_base=%s",
        indice, len(entradas), data_base or "(última publicada)",
    )

    # Busca a série do mês mais antigo até hoje — a última competência
    # publicada vem da própria resposta (o SGS não devolve meses futuros).
    indice_mais_antigo = min(e[1] for e in entradas)
    inicio = date(indice_mais_antigo // 12, indice_mais_antigo % 12 + 1, 1)
    serie = await bcb_client.obter_indice_mensal(codigo_serie, inicio, date.today())
    if not serie:
        raise ValueError(
            f"o SGS/Banco Central não devolveu nenhuma variação de {info_indice['nome']} para "
            f"o período iniciado em {inicio.isoformat()[:7]} — verifique as datas informadas"
        )
    variacao_por_indice: dict[int, float] = {}
    for r in serie:
        ano, mes = _parse_competencia(r["competencia"])
        variacao_por_indice[_indice_temporal(ano, mes)] = r["variacao_percentual"]
    ultimo_publicado = max(variacao_por_indice)

    if data_base is not None:
        ano_b, mes_b = _parse_competencia(data_base)
        indice_base = _indice_temporal(ano_b, mes_b)
        if indice_base > ultimo_publicado:
            ultima = f"{ultimo_publicado // 12:04d}-{ultimo_publicado % 12 + 1:02d}"
            raise ValueError(
                f"data_base {data_base!r} ainda não tem {info_indice['nome']} publicado — a "
                f"última competência disponível na série {codigo_serie} é {ultima}. Esta tool "
                "não extrapola variação futura; omita data_base para usar a última publicada."
            )
    else:
        indice_base = ultimo_publicado
    competencia_base = f"{indice_base // 12:04d}-{indice_base % 12 + 1:02d}"

    avisos: list[str] = []
    if indice != "ipca":
        avisos.append(_AVISO_INDICE_NAO_PADRAO)

    precos_atualizados: list[dict[str, Any]] = []
    for valor, indice_preco, original in entradas:
        fator = 1.0
        if indice_preco < indice_base:
            faltantes = [
                m for m in range(indice_preco + 1, indice_base + 1)
                if m not in variacao_por_indice
            ]
            if faltantes:
                comp = f"{faltantes[0] // 12:04d}-{faltantes[0] % 12 + 1:02d}"
                raise ValueError(
                    f"a série {codigo_serie} do SGS não tem a competência {comp}, necessária "
                    f"para atualizar um preço de {original['data']!r} até {competencia_base} — "
                    "tente novamente mais tarde ou confira as datas informadas"
                )
            for m in range(indice_preco + 1, indice_base + 1):
                fator *= 1.0 + variacao_por_indice[m] / 100.0
        elif indice_preco > indice_base:
            avisos.append(
                f"preço com data {original['data']!r} é POSTERIOR à data_base "
                f"{competencia_base} — mantido sem ajuste (fator 1,0); esta tool não "
                "desconta variação de datas futuras à base"
            )
        competencia_preco = f"{indice_preco // 12:04d}-{indice_preco % 12 + 1:02d}"
        precos_atualizados.append(
            {
                **{k: v for k, v in original.items() if k not in ("valor",)},
                "valor_original": valor,
                "competencia": competencia_preco,
                "fator_atualizacao": round(fator, 8),
                "valor_atualizado": round(valor * fator, 4),
            }
        )

    return {
        "indice": f"{info_indice['nome']} ({info_indice['fonte_oficial']}, série {codigo_serie} do SGS/Banco Central)",
        "indice_chave": indice,
        "data_base": competencia_base,
        "quantidade": len(precos_atualizados),
        "precos_atualizados": precos_atualizados,
        "valores_atualizados": [p["valor_atualizado"] for p in precos_atualizados],
        "avisos": avisos,
    }
