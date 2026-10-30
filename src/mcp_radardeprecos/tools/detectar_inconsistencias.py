"""Tool MCP: sinaliza inconsistências em registros de preço (pura, sem rede).

Heurísticas sobre campos estruturados que
já temos, apontando armadilhas comuns ANTES de o valor entrar na cesta:
quantidade 1 para um lote, homologado acima do estimado, preço unitário que
aparenta ser global, objeto que mistura licença + implantação + suporte, etc.

Princípio: cada alerta é **informativo**, com o motivo e os campos
envolvidos — a tool **nunca exclui** um registro sozinha. Descartar um preço
exige justificativa humana (regra do projeto e da IN 65/2021). O objetivo é
dar ao agente/equipe uma lista de pontos a investigar, não decidir por eles.
"""
from __future__ import annotations

import statistics
import unicodedata
from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)

_CAMPOS_PADRAO: dict[str, list[str]] = {
    "valor_unitario": ["valor_unitario", "preco_unitario", "valorUnitario",
                       "valor_unitario_item", "valor_normalizado"],
    "valor_total": ["valor_total", "valorTotal", "valor_total_item",
                    "valor_global", "valorGlobal"],
    "valor_estimado": ["valor_estimado", "valorEstimado", "valor_total_estimado",
                       "valorTotalEstimado", "valor_unitario_estimado"],
    "valor_homologado": ["valor_homologado", "valorHomologado",
                         "valor_total_homologado", "valor_unitario_homologado"],
    "quantidade": ["quantidade", "qtd", "quantidade_homologada", "quantidadeHomologada"],
    "quantidade_estimada": ["quantidade_estimada", "quantidade_prevista",
                            "quantidadeEstimada", "quantidade_edital"],
    "descricao_objeto": ["objeto", "descricao_objeto", "descricaoObjeto",
                         "descricao_contratacao"],
    "descricao_item": ["descricao_item", "descricaoItem", "descricao"],
}

_TERMOS_LICENCA = ["licença", "licenca", "subscrição", "subscricao", "assinatura"]
_TERMOS_AGREGADO = [
    "implantação", "implantacao", "instalação", "instalacao", "suporte",
    "treinamento", "capacitação", "capacitacao", "migração", "migracao",
    "consultoria", "customização", "customizacao",
]

#: Um preço unitário acima deste fator × mediana "aparenta global".
_FATOR_OUTLIER_PADRAO = 20.0


def _norm(s: object) -> str:
    txt = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(txt.lower().split())


def _num(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, str) and "," in v:
            return float(v.strip().replace(".", "").replace(",", "."))
        return float(v)
    except (TypeError, ValueError):
        return None


def _campo(registro: dict, mapa: dict, chave: str) -> Any:
    for c in mapa.get(chave, []):
        if c in registro and registro[c] not in (None, ""):
            return registro[c]
    return None


def _tokens(texto: str) -> set[str]:
    return {t for t in _norm(texto).split() if len(t) > 3}


def _contem_algum(texto: str, termos: list[str]) -> bool:
    return any(t in texto for t in termos)


async def detectar_inconsistencias(
    registros: list[dict[str, Any]],
    campos: dict[str, str] | None = None,
    fator_outlier: float = _FATOR_OUTLIER_PADRAO,
) -> dict[str, Any]:
    """Sinaliza inconsistências em registros de preço, sem descartar nada.

    Tool **pura** (sem rede). Roda idealmente logo após a coleta (e após
    ``normalizar_precos_unidade``), como uma checagem de sanidade antes de
    agrupar/calcular. **Nunca remove** registros — só aponta o que investigar.

    Verificações (cada alerta traz ``tipo``, ``gravidade`` e ``mensagem``):

    - ``quantidade_suspeita``: quantidade <= 1 mas o valor total é bem maior
      que o unitário — o preço "unitário" pode ser global ou a quantidade
      estar errada.
    - ``homologado_acima_estimado``: valor homologado maior que o estimado
      (normalmente a disputa reduz o valor — o contrário merece olhar).
    - ``quantidade_divergente``: quantidade difere da quantidade estimada/
      prevista informada.
    - ``preco_aparenta_global``: preço unitário muito acima da mediana dos
      demais (por padrão > ``fator_outlier`` ×) — pode ser um valor global no
      campo de unitário.
    - ``preco_muito_abaixo``: preço unitário muito abaixo da mediana (< mediana
      / ``fator_outlier``) — pode ser inexequível, unidade diferente ou erro.
    - ``objeto_composto``: descrição mistura licença/subscrição com
      implantação/suporte/treinamento — preço não é comparável item a item.
    - ``descricoes_divergentes``: descrição do objeto e do item com pouca
      sobreposição de termos — confira se o item é o que o objeto diz.
    - ``valor_ausente``: sem valor unitário numérico > 0 (qualidade de dado).

    Args:
        registros: lista de dicts (saída de qualquer tool de busca). Campos
            lidos por nome, com alternativas (ver ``campos``).
        campos: mapeamento opcional de nome de campo (ex.:
            ``{"valor_unitario": "preco", "quantidade": "qtd"}``).
        fator_outlier: fator multiplicativo para os alertas de preço
            alto/baixo em relação à mediana (padrão 20).

    Returns:
        Dicionário com ``total``, ``com_inconsistencia`` (nº de registros com
        ao menos um alerta), ``resumo_por_tipo`` (contagem por tipo),
        ``alertas`` (só os registros com alertas, cada um preservando os campos
        originais e acrescentando ``inconsistencias``: lista de
        ``{tipo, gravidade, mensagem}``) e ``avisos``.
    """
    mapa = {**_CAMPOS_PADRAO}
    if campos:
        for chave, nome in campos.items():
            mapa[chave] = [nome, *mapa.get(chave, [])]

    # Mediana dos preços unitários positivos, para os alertas de outlier.
    unitarios = [
        u for u in (_num(_campo(r, mapa, "valor_unitario")) for r in registros)
        if u is not None and u > 0
    ]
    mediana = statistics.median(unitarios) if len(unitarios) >= 3 else None

    alertas: list[dict[str, Any]] = []
    resumo: dict[str, int] = {}

    def _reg(tipo: str, gravidade: str, mensagem: str, lista: list) -> None:
        lista.append({"tipo": tipo, "gravidade": gravidade, "mensagem": mensagem})
        resumo[tipo] = resumo.get(tipo, 0) + 1

    for registro in registros:
        inc: list[dict[str, Any]] = []
        v_unit = _num(_campo(registro, mapa, "valor_unitario"))
        v_total = _num(_campo(registro, mapa, "valor_total"))
        v_estimado = _num(_campo(registro, mapa, "valor_estimado"))
        v_homolog = _num(_campo(registro, mapa, "valor_homologado"))
        qtd = _num(_campo(registro, mapa, "quantidade"))
        qtd_est = _num(_campo(registro, mapa, "quantidade_estimada"))
        desc_obj = _campo(registro, mapa, "descricao_objeto")
        desc_item = _campo(registro, mapa, "descricao_item")

        if v_unit is None or v_unit <= 0:
            _reg("valor_ausente", "media",
                 "sem valor unitário numérico > 0 — verifique a fonte", inc)

        if qtd is not None and qtd <= 1 and v_total and v_unit and v_total > v_unit * 1.5:
            _reg("quantidade_suspeita", "media",
                 f"quantidade {qtd:g} mas valor total ({v_total:g}) bem maior que o "
                 f"unitário ({v_unit:g}) — unitário pode ser global ou quantidade errada",
                 inc)

        if v_homolog is not None and v_estimado is not None and v_homolog > v_estimado * 1.01:
            _reg("homologado_acima_estimado", "alta",
                 f"valor homologado ({v_homolog:g}) acima do estimado ({v_estimado:g}) "
                 "— incomum (a disputa costuma reduzir); confirme", inc)

        if qtd is not None and qtd_est is not None and qtd != qtd_est:
            _reg("quantidade_divergente", "media",
                 f"quantidade ({qtd:g}) difere da estimada/prevista ({qtd_est:g})", inc)

        if mediana and v_unit and v_unit > mediana * fator_outlier:
            _reg("preco_aparenta_global", "media",
                 f"preço unitário ({v_unit:g}) > {fator_outlier:g}× a mediana "
                 f"({mediana:g}) — pode ser um valor global no campo de unitário", inc)
        elif mediana and v_unit and 0 < v_unit < mediana / fator_outlier:
            _reg("preco_muito_abaixo", "media",
                 f"preço unitário ({v_unit:g}) < mediana/{fator_outlier:g} "
                 f"({mediana / fator_outlier:g}) — inexequível, unidade diferente ou erro",
                 inc)

        texto_desc = _norm(f"{desc_obj or ''} {desc_item or ''}")
        if _contem_algum(texto_desc, _TERMOS_LICENCA) and _contem_algum(texto_desc, _TERMOS_AGREGADO):
            _reg("objeto_composto", "media",
                 "descrição mistura licença/subscrição com implantação/suporte/"
                 "treinamento — preço não é comparável item a item", inc)

        if desc_obj and desc_item:
            t_obj, t_item = _tokens(desc_obj), _tokens(desc_item)
            if t_obj and t_item:
                jaccard = len(t_obj & t_item) / len(t_obj | t_item)
                if jaccard < 0.15:
                    _reg("descricoes_divergentes", "baixa",
                         "descrição do objeto e do item com pouca sobreposição de "
                         "termos — confirme se o item corresponde ao objeto", inc)

        if inc:
            alertas.append({**registro, "inconsistencias": inc})

    avisos = [
        "Os alertas são INFORMATIVOS: nenhum registro foi excluído. Investigue "
        "cada ponto e, se descartar um preço, registre a justificativa (IN 65/2021).",
    ]
    if mediana is None and registros:
        avisos.append(
            "Menos de 3 preços unitários válidos — os alertas de outlier "
            "(preço alto/baixo vs. mediana) não foram avaliados."
        )

    logger.info(
        "detectar_inconsistencias total=%d com_inconsistencia=%d tipos=%s",
        len(registros), len(alertas), sorted(resumo),
    )

    return {
        "total": len(registros),
        "com_inconsistencia": len(alertas),
        "resumo_por_tipo": resumo,
        "alertas": alertas,
        "avisos": avisos,
    }
