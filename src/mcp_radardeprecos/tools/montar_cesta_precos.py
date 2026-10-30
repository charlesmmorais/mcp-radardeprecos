"""Tool MCP: monta a cesta de preços a partir dos resultados de busca (pura).

Correção estrutural da causa-raiz do "amostra pequena". Até aqui, o
modelo lia o JSON de uma busca (ex.: ``buscar_precos_praticados_compras``,
``buscar_contratacoes_pncp``) e **transcrevia à mão** os preços num
``list[float]`` para ``calcular_preco_referencia``. Essa transcrição manual é
intrinsecamente perdedora: o modelo pega uns poucos valores (ainda mais quando
os resultados são heterogêneos), produzindo amostras artificialmente pequenas
(observado ao vivo: busca de Figma com 99 editais no PNCP virando "2 preços").

Esta tool tira o modelo dessa alça: recebe a **lista de registros que a busca
já devolveu** e extrai a série de preços unitários automaticamente, sem
transcrição. Cada preço sai com o registro original preservado (descrição,
unidade, quantidade, fornecedor, data...), pronto para alimentar o pipeline:
``montar_cesta_precos`` → ``normalizar_precos_unidade`` →
``agrupar_por_comparabilidade`` → ``calcular_preco_referencia``. Nada é
descartado em silêncio: registros sem preço válido vão para ``sem_valor`` com
o motivo.
"""
from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger
from .buscar_precos_praticados_compras import _capacidade_texto, _texto

logger = get_logger(__name__)

#: Campos de PREÇO UNITÁRIO reconhecidos nos retornos das tools de busca deste
#: servidor, em ordem de prioridade. Deliberadamente NÃO inclui valor global/
#: total (não é preço unitário) — para usar um campo fora desta lista, informe
#: ``campo_valor`` explicitamente.
_CAMPOS_VALOR_PADRAO = [
    "valor_normalizado",          # já normalizado (normalizar_precos_unidade)
    "preco_unitario",             # buscar_precos_praticados_compras
    "valor_unitario_estimado",    # itens de contratação (PNCP)
    "valor_unitario_item",        # itens de contrato (Compras.gov.br)
    "valor_unitario",             # genérico
    "valorUnitario", "precoUnitario", "valorUnitarioEstimado",  # variantes cruas
]


def _num(v: object) -> float | None:
    """Coerção tolerante a número (aceita formato brasileiro '1.234,56')."""
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, str):
            s = v.strip()
            if "," in s:
                s = s.replace(".", "").replace(",", ".")
            return float(s)
        return float(v)
    except (TypeError, ValueError):
        return None


def _extrair_valor(
    registro: dict[str, Any], campo_valor: str | None
) -> tuple[float | None, str | None]:
    """Extrai o preço unitário de um registro. Devolve (valor, campo_usado)."""
    candidatos = [campo_valor] if campo_valor else _CAMPOS_VALOR_PADRAO
    for campo in candidatos:
        if campo and campo in registro:
            v = _num(registro[campo])
            if v is not None:
                return v, campo
    return None, None


def _resumir_unidades(cesta: list[dict[str, Any]]) -> dict[str, Any]:
    """Conta os itens da cesta por unidade de fornecimento.

    Só registros vindos de ``buscar_precos_praticados_compras`` trazem
    ``unidade_fornecimento``; para as demais fontes o rótulo fica como não
    informado, e a contagem degrada para um único balde (sem falso alarme).
    """
    contagem: dict[str, int] = {}
    for item in cesta:
        unidade = item.get("unidade_fornecimento") or {}
        if isinstance(unidade, dict):
            # `capacidade` chega como número em parte dos itens do
            # Compras.gov.br — ver `_texto`/`_capacidade_texto` em
            # buscar_precos_praticados_compras, onde a mesma suposição
            # derrubava a ferramenta inteira.
            nome = _texto(unidade.get("nome") or unidade.get("sigla"))
            capacidade = _capacidade_texto(unidade.get("capacidade"))
        else:
            nome, capacidade = _texto(unidade), ""
        rotulo = " ".join(p for p in (nome, capacidade) if p) or "(não informada)"
        contagem[rotulo] = contagem.get(rotulo, 0) + 1
    ordenado = dict(sorted(contagem.items(), key=lambda par: (-par[1], par[0])))
    return {
        "unidades_distintas": len(ordenado),
        "contagem_por_unidade": ordenado,
    }


async def montar_cesta_precos(
    registros: list[dict[str, Any]],
    campo_valor: str | None = None,
) -> dict[str, Any]:
    """Monta a cesta de preços a partir dos REGISTROS de uma busca — sem transcrição manual.

    Passe a lista de registros que uma tool de busca já devolveu (ex.: o campo
    ``precos`` de ``buscar_precos_praticados_compras``, ``registros`` de
    ``buscar_homologados_14133``, ``itens`` de ``consultar_itens_contrato_compras``,
    ou os itens de contratações). A tool extrai o preço unitário de CADA
    registro automaticamente — assim a amostra reflete os DADOS, não quantos
    preços o modelo transcreveu à mão (causa real de amostras artificialmente
    pequenas). É pura (sem rede).

    Detecta o campo de preço unitário por uma lista de nomes conhecidos
    (``preco_unitario``, ``valor_unitario_estimado``, ``valor_unitario_item``,
    ``valor_unitario``, ``valor_normalizado``...); para um campo fora dessa
    lista, informe ``campo_valor``. **Não usa valor global/total** (não é
    preço unitário). **Nada é descartado em silêncio:** registros sem preço
    unitário válido (> 0) vão para ``sem_valor`` com o motivo.

    Cada item da cesta preserva o registro original inteiro e acrescenta
    ``valor`` — pronto para alimentar, na ordem: ``normalizar_precos_unidade``
    (mesma unidade), ``agrupar_por_comparabilidade`` (separar objetos) e
    ``calcular_preco_referencia`` (o campo ``precos`` já vem como lista de
    floats para o caso simples).

    Args:
        registros: lista de dicts vinda de qualquer tool de busca.
        campo_valor: nome do campo de preço a usar (sobrescreve a
            auto-detecção) — útil se a fonte usar um nome não reconhecido.

    Returns:
        Dicionário com ``total_registros``, ``resumo`` (com_valor, sem_valor,
        campo_valor_usado), ``cesta`` (registros COM preço, cada um com
        ``valor`` acrescentado), ``precos`` (lista de floats, pronta para
        ``calcular_preco_referencia``), ``sem_valor`` (registros sem preço
        válido, com ``motivo``) e ``avisos``.
    """
    cesta: list[dict[str, Any]] = []
    sem_valor: list[dict[str, Any]] = []
    campos_usados: set[str] = set()

    for registro in registros:
        if not isinstance(registro, dict):
            sem_valor.append({"registro": registro, "motivo": "registro não é um objeto"})
            continue
        valor, campo = _extrair_valor(registro, campo_valor)
        if valor is None:
            sem_valor.append({**registro, "motivo": "sem campo de preço unitário reconhecido"})
        elif valor <= 0:
            sem_valor.append({**registro, "motivo": f"preço não positivo ({valor})"})
        else:
            cesta.append({**registro, "valor": valor})
            if campo:
                campos_usados.add(campo)

    precos = [item["valor"] for item in cesta]

    avisos: list[str] = []
    if sem_valor:
        avisos.append(
            f"{len(sem_valor)} de {len(registros)} registro(s) sem preço unitário "
            "válido ficaram FORA da cesta (ver 'sem_valor' e o motivo). Se a fonte "
            "usa outro nome de campo, informe 'campo_valor'."
        )
    if len(campos_usados) > 1:
        avisos.append(
            f"Preços vieram de campos diferentes ({sorted(campos_usados)}) — confira "
            "se são todos preço UNITÁRIO comparável antes de calcular."
        )
    if len(precos) < 3:
        avisos.append(
            f"Cesta com {len(precos)} preço(s) — abaixo do mínimo de 3. AMPLIE a "
            "busca (mais termos/sinônimos e fontes: preços praticados, atas, "
            "homologados) em vez de transcrever manualmente; depois normalize a "
            "unidade e agrupe por comparabilidade antes de calcular."
        )

    # v0.4.7: quando os registros vêm de buscar_precos_praticados_compras,
    # eles carregam a unidade de fornecimento praticada. Uma cesta com mais
    # de uma unidade não é uma amostra de um preço só — avisar aqui evita
    # que a mistura chegue silenciosamente a calcular_preco_referencia.
    unidades = _resumir_unidades(cesta)
    if unidades["unidades_distintas"] > 1:
        rotulos = ", ".join(
            f"{rotulo} ({qtd})"
            for rotulo, qtd in list(unidades["contagem_por_unidade"].items())[:5]
        )
        avisos.append(
            f"Cesta mistura {unidades['unidades_distintas']} unidades de "
            f"fornecimento ({rotulos}) — NÃO calcule o preço de referência "
            "antes de normalizar (normalizar_precos_unidade) ou de separar a "
            "série por unidade. Estatística sobre unidades distintas agrega "
            "grandezas incomensuráveis."
        )

    logger.info(
        "montar_cesta_precos total=%d com_valor=%d sem_valor=%d",
        len(registros), len(cesta), len(sem_valor),
    )

    return {
        "total_registros": len(registros),
        "resumo": {
            "com_valor": len(cesta),
            "sem_valor": len(sem_valor),
            "campo_valor_usado": sorted(campos_usados),
        },
        "cesta": cesta,
        "precos": precos,
        "unidades": unidades,
        "sem_valor": sem_valor,
        "avisos": avisos,
    }
