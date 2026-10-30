"""Tool MCP: normaliza preços coletados para uma unidade comum (pura, sem rede).

Problema que resolve: o mesmo objeto
aparece no PNCP/Compras em unidades diferentes — R$/usuário/mês,
R$/usuário/ano, preço para 36 meses, valor global de um lote, uma única
unidade para todo o serviço. Comparar sem trazer tudo para a mesma base é a
fonte nº 1 de erro de cálculo em pesquisa de preços (o tutorial alerta nas
seções 12–13). Esta tool faz a aritmética de conversão de forma TRANSPARENTE
e AUDITÁVEL, deixando explícito, por linha: a fórmula, as premissas usadas e a
origem de cada insumo.

Princípio central (anti-erro-silencioso): a tool **nunca chuta** um fator que
não foi informado. Se falta a quantidade ou o número de meses necessário para
o alvo, o registro vai para ``nao_normalizaveis`` com o motivo — em vez de
assumir 1 em silêncio e devolver um preço errado com cara de certo.

A extração dos fatores (quantos usuários? quantos meses? qual o valor?) do
registro cru — que pode estar no texto do objeto ou dentro do edital — é
trabalho de quem chama (o assistente), não desta tool: aqui entram valores já
identificados. Isso mantém a tool pura, previsível e testável, e a
orquestração no LLM (não num monólito).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)

#: Alvos suportados: (base_de_quantidade, periodo). base None = não divide por
#: quantidade; periodo None = não divide por tempo.
_ALVOS: dict[str, tuple[str | None, str | None]] = {
    "usuario_mes": ("usuário", "mes"),
    "usuario_ano": ("usuário", "ano"),
    "licenca_mes": ("licença", "mes"),
    "licenca_ano": ("licença", "ano"),
    "dispositivo_mes": ("dispositivo", "mes"),
    "dispositivo_ano": ("dispositivo", "ano"),
    "unidade_mes": ("unidade", "mes"),
    "unidade_ano": ("unidade", "ano"),
    "usuario": ("usuário", None),
    "licenca": ("licença", None),
    "unidade": ("unidade", None),
    "mes": (None, "mes"),
    "ano": (None, "ano"),
}


def _para_decimal(valor: object) -> Decimal | None:
    """Converte para Decimal de forma tolerante.

    Trata o formato numérico brasileiro: se houver vírgula, ela é o separador
    decimal e os pontos são separadores de milhar (``"1.200,00"`` → 1200.00);
    sem vírgula, o ponto é o separador decimal (``"120376.40"`` → 120376.40).
    """
    if valor is None or isinstance(valor, bool):
        return None
    s = str(valor).strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _resolver_fator(
    registro: dict,
    chave: str,
    premissas: dict,
    campo_key: str,
    default_key: str,
) -> tuple[Decimal | None, str | None]:
    """Resolve um fator (quantidade/meses) do registro ou das premissas.

    Ordem: chave direta no registro → campo mapeado em premissas[campo_key] →
    default global em premissas[default_key]. Devolve (valor, origem), onde
    origem é ``"registro"``, ``"premissa"`` ou ``None`` (não encontrado).
    """
    if chave in registro:
        v = _para_decimal(registro[chave])
        if v is not None:
            return v, "registro"
    campo = premissas.get(campo_key)
    if campo and campo in registro:
        v = _para_decimal(registro[campo])
        if v is not None:
            return v, "registro"
    if default_key in premissas:
        v = _para_decimal(premissas[default_key])
        if v is not None:
            return v, "premissa"
    return None, None


def _resolver_valor(registro: dict, premissas: dict) -> tuple[Decimal | None, str | None]:
    """Resolve o valor monetário do registro (chave 'valor' ou mapeada)."""
    if "valor" in registro:
        v = _para_decimal(registro["valor"])
        if v is not None:
            return v, "valor"
    campo = premissas.get("valor_campo")
    if campo and campo in registro:
        v = _para_decimal(registro[campo])
        if v is not None:
            return v, campo
    return None, None


async def normalizar_precos_unidade(
    registros: list[dict[str, Any]],
    unidade_alvo: str,
    premissas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Converte uma lista de preços para uma unidade comum, com transparência total.

    Tool **pura** (não acessa rede). Traz preços coletados em unidades
    heterogêneas para uma base comparável (ex.: preço por usuário por mês),
    aplicando fatores explícitos e registrando, por linha, a fórmula, as
    premissas e a origem de cada insumo. Passo recomendado ANTES de agrupar
    (``agrupar_por_comparabilidade``, quando existir) e de calcular o preço de
    referência (``calcular_preco_referencia``).

    Como cada registro é lido:

    - **valor** (obrigatório): a chave ``valor`` do registro, ou a chave
      apontada por ``premissas["valor_campo"]``. Sem valor numérico > 0, o
      registro vai para ``nao_normalizaveis``.
    - **quantidade** (nº de usuários/licenças/dispositivos/unidades que o
      valor cobre): a chave ``quantidade`` do registro, ou a apontada por
      ``premissas["quantidade_campo"]``, ou o default ``premissas["quantidade"]``.
    - **meses** (nº de meses que o valor cobre): a chave ``meses`` do registro,
      ou a apontada por ``premissas["meses_campo"]``, ou o default
      ``premissas["meses"]``.

    A conversão é ``valor / (fator_quantidade × fator_periodo)``, onde
    ``fator_quantidade`` = quantidade (se o alvo tem base de quantidade) ou 1;
    ``fator_periodo`` = meses (alvo …_mes), ou meses/12 (alvo …_ano), ou 1
    (alvo sem período). Um registro já na unidade-alvo é convertido com
    quantidade=1 e meses=1 (resultado = o próprio valor).

    **Nunca assume em silêncio:** se o alvo exige um fator (quantidade e/ou
    meses) que não veio do registro nem das premissas, o registro vai para
    ``nao_normalizaveis`` com o motivo — premissa não declarada seria erro
    silencioso, o oposto do objetivo.

    Args:
        registros: lista de dicts. Cada um deve conter ``valor`` (ou a chave
            mapeada) e, conforme o alvo, ``quantidade`` e/ou ``meses`` (ou
            defaults em ``premissas``). Demais campos são preservados na saída.
        unidade_alvo: um de ``usuario_mes``, ``usuario_ano``, ``licenca_mes``,
            ``licenca_ano``, ``dispositivo_mes``, ``dispositivo_ano``,
            ``unidade_mes``, ``unidade_ano``, ``usuario``, ``licenca``,
            ``unidade``, ``mes``, ``ano``.
        premissas: opcional. Defaults globais e mapeamentos de campo:
            ``quantidade``/``meses`` (valores default), ``valor_campo``/
            ``quantidade_campo``/``meses_campo`` (nomes de chave alternativos
            no registro).

    Returns:
        Dicionário com ``unidade_alvo``, ``premissas`` (ecoadas), ``total``,
        ``normalizados`` (cada item preserva os campos originais e acrescenta
        ``valor_original``, ``quantidade``, ``meses``, ``valor_normalizado``,
        ``fator_aplicado``, ``formula`` (texto legível), ``confianca``
        (``"alta"`` se todos os fatores vieram do registro; ``"media"`` se
        algum veio de premissa global) e ``origem`` (de onde veio cada
        insumo)), ``nao_normalizaveis`` (com ``motivo``) e ``avisos``.

    Raises:
        ValueError: se ``unidade_alvo`` não for um dos valores suportados.
    """
    if unidade_alvo not in _ALVOS:
        raise ValueError(
            f"unidade_alvo inválida: {unidade_alvo!r}. Valores suportados: "
            + ", ".join(sorted(_ALVOS))
        )

    premissas = premissas or {}
    base, periodo = _ALVOS[unidade_alvo]
    normalizados: list[dict[str, Any]] = []
    nao_normalizaveis: list[dict[str, Any]] = []

    for registro in registros:
        valor, origem_valor = _resolver_valor(registro, premissas)
        if valor is None:
            nao_normalizaveis.append(
                {**registro, "motivo": "valor ausente ou não numérico (use a "
                 "chave 'valor' ou premissas.valor_campo)"}
            )
            continue
        if valor <= 0:
            nao_normalizaveis.append({**registro, "motivo": f"valor não positivo ({valor})"})
            continue

        origem: dict[str, str] = {"valor": origem_valor or "valor"}
        fator_qtd = Decimal(1)
        fator_per = Decimal(1)
        qtd_out: Decimal | None = None
        meses_out: Decimal | None = None
        partes_formula: list[str] = []

        if base is not None:
            qtd, origem_qtd = _resolver_fator(
                registro, "quantidade", premissas, "quantidade_campo", "quantidade"
            )
            if qtd is None:
                nao_normalizaveis.append(
                    {**registro, "motivo": f"quantidade de {base} não informada "
                     "(no registro ou em premissas) — necessária para o alvo "
                     f"{unidade_alvo!r}"}
                )
                continue
            if qtd <= 0:
                nao_normalizaveis.append({**registro, "motivo": f"quantidade não positiva ({qtd})"})
                continue
            fator_qtd = qtd
            qtd_out = qtd
            origem["quantidade"] = origem_qtd or "registro"
            partes_formula.append(f"{_num(qtd)} {base}(s)")

        if periodo is not None:
            meses, origem_meses = _resolver_fator(
                registro, "meses", premissas, "meses_campo", "meses"
            )
            if meses is None:
                nao_normalizaveis.append(
                    {**registro, "motivo": "número de meses não informado (no "
                     f"registro ou em premissas) — necessário para o alvo {unidade_alvo!r}"}
                )
                continue
            if meses <= 0:
                nao_normalizaveis.append({**registro, "motivo": f"meses não positivo ({meses})"})
                continue
            meses_out = meses
            origem["meses"] = origem_meses or "registro"
            if periodo == "mes":
                fator_per = meses
                partes_formula.append(f"{_num(meses)} meses")
            else:  # ano
                fator_per = meses / Decimal(12)
                partes_formula.append(f"({_num(meses)}/12) anos")

        divisor = fator_qtd * fator_per
        valor_norm = valor / divisor
        formula = f"{_num(valor)}"
        if partes_formula:
            formula += " / (" + " × ".join(partes_formula) + ")"
        confianca = "alta"
        if any(o == "premissa" for o in origem.values()):
            confianca = "media"

        normalizados.append(
            {
                **registro,
                "valor_original": _float(valor),
                "quantidade": _float(qtd_out) if qtd_out is not None else None,
                "meses": _float(meses_out) if meses_out is not None else None,
                "valor_normalizado": _float(valor_norm.quantize(Decimal("0.0001"))),
                "fator_aplicado": _float(divisor),
                "formula": formula,
                "unidade_alvo": unidade_alvo,
                "confianca": confianca,
                "origem": origem,
            }
        )

    avisos: list[str] = []
    if nao_normalizaveis:
        avisos.append(
            f"{len(nao_normalizaveis)} de {len(registros)} registro(s) não puderam "
            "ser normalizados por falta de insumo — ver 'nao_normalizaveis' (não "
            "foram descartados nem estimados; decida caso a caso)."
        )
    if any(n.get("confianca") == "media" for n in normalizados):
        avisos.append(
            "Alguns valores usaram premissa global (quantidade/meses default) em vez "
            "de dado do próprio registro — confiança 'media'. Confirme a premissa "
            "antes de usar no cálculo."
        )

    logger.info(
        "normalizar_precos_unidade alvo=%s total=%d normalizados=%d nao=%d",
        unidade_alvo, len(registros), len(normalizados), len(nao_normalizaveis),
    )

    return {
        "unidade_alvo": unidade_alvo,
        "premissas": premissas,
        "total": len(registros),
        "normalizados": normalizados,
        "nao_normalizaveis": nao_normalizaveis,
        "avisos": avisos,
    }


def _num(d: Decimal) -> str:
    """Formata um Decimal para a fórmula, sem zeros/ponto sobrando."""
    d = d.normalize()
    s = format(d, "f")
    return s


def _float(d: Decimal) -> float:
    return float(d)
