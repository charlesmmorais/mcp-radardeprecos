"""Tool MCP: agrupa preços por comparabilidade, com grau A–D (pura, sem rede).

Problema que resolve: encontrar vários
preços não significa que todos possam ser comparados. Misturar Microsoft 365
E3 com E5, hora júnior com sênior, ou 100 com 20.000 unidades numa mesma média
é o erro nº 1 que o tutorial alerta (seções 11–12) e o que a IN SEGES/ME
65/2021 exige tratar (condições comerciais + análise crítica de variação).

Esta tool faz duas coisas, sempre por **regras explícitas e declaradas** (nada
de clustering opaco por NLP — o agrupamento precisa ser justificável no
processo):

1. **Agrupa** os registros por dimensões de comparabilidade (unidade de
   fornecimento, faixa de quantidade, período), com pré-estatística por grupo.
2. **Classifica** cada registro numa escala de comparabilidade **A–D**,
   relativa a um ``alvo`` (o objeto que se quer contratar), quando informado:

   - **A — idêntico:** contém todos os termos-núcleo do alvo e atende à
     métrica/modalidade.
   - **B — altamente comparável:** mesmo produto, mas difere num termo de
     variação (ex.: com/sem Teams, programa comercial, vigência) ou na
     métrica/modalidade.
   - **C — parcialmente comparável:** substituto próximo (ex.: Office 365 E3
     no lugar de Microsoft 365 E3).
   - **D — não comparável:** bundle/equipamento/serviço agregado, descrição
     insuficiente, ou não corresponde ao alvo → vai para ``nao_comparaveis`` e
     **não** entra em nenhum grupo/estatística.

Sem ``alvo``, a tool ainda agrupa e detecta os D intrínsecos (descrição
insuficiente / termos desqualificadores), mas não atribui A/B/C (não há
referência para "idêntico").

A extração dos termos-núcleo/variação/substituto do alvo é decisão de quem
chama (o assistente/equipe) — é justamente onde entra o julgamento técnico.
A tool aplica as regras de forma transparente e reprodutível.
"""
from __future__ import annotations

import statistics
import unicodedata
from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)

#: Termos que, por si, marcam um registro como não comparável (bundle,
#: equipamento, serviço agregado) — sobrescrevíveis via parâmetro.
_DESQUALIFICADORES_PADRAO = [
    "locação", "locacao", "aluguel", "outsourcing de impressão",
    "kit", "bundle", "equipamento", "notebook", "desktop", "computador",
    "servidor físico", "servidor fisico",
]

#: Faixas de quantidade padrão (limiares em ordem crescente).
_FAIXAS_PADRAO = [10, 100, 1000]

#: Tamanho mínimo (caracteres) da descrição para ser classificável.
_MIN_DESCRICAO = 15

_CAMPOS_PADRAO = {
    "descricao": ["descricao", "objeto", "descricao_item", "descricaoItem",
                  "descricao_objeto", "descricaoObjeto"],
    "unidade": ["unidade", "unidade_fornecimento", "unidadeFornecimento",
                "unidade_medida"],
    "quantidade": ["quantidade", "qtd", "quantidade_item"],
    "meses": ["meses", "periodo_meses", "vigencia_meses"],
    "valor": ["valor", "valor_normalizado", "preco_unitario", "valor_unitario",
              "valorUnitario", "valor_unitario_item"],
}


def _norm(s: object) -> str:
    """Minúsculas, sem acento, espaços colapsados."""
    txt = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(txt.lower().split())


def _num(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(str(v).strip().replace(".", "").replace(",", ".")) if (
            isinstance(v, str) and "," in v
        ) else float(v)
    except (TypeError, ValueError):
        return None


def _primeiro_campo(registro: dict, candidatos: list[str]) -> Any:
    for c in candidatos:
        if c in registro and registro[c] not in (None, ""):
            return registro[c]
    return None


def _faixa_quantidade(q: float | None, limiares: list[int]) -> str:
    if q is None:
        return "sem_quantidade"
    prev = 1
    for t in sorted(limiares):
        if q < t:
            return f"{prev}-{t - 1}"
        prev = t
    return f"{prev}+"


def _contem_todos(texto: str, termos: list[str]) -> bool:
    return all(_norm(t) in texto for t in termos)


def _contem_algum(texto: str, termos: list[str]) -> tuple[bool, str | None]:
    for t in termos:
        if _norm(t) in texto:
            return True, t
    return False, None


def _classificar(
    texto: str, alvo: dict | None, desqualificadores: list[str]
) -> tuple[str | None, str]:
    """Retorna (grau, motivo). grau em {A,B,C,D} ou None (sem alvo, não-D)."""
    if len(texto) < _MIN_DESCRICAO:
        return "D", "descrição insuficiente para avaliar comparabilidade"
    achou, termo = _contem_algum(texto, desqualificadores)
    if achou:
        return "D", f"contém termo desqualificador ({termo!r}) — possível bundle/equipamento/agregado"

    if not alvo:
        return None, "sem alvo informado — apenas agrupado (A–D não avaliado)"

    nucleo = alvo.get("termos_nucleo") or []
    variacao = alvo.get("termos_variacao") or []
    substitutos = alvo.get("termos_substituto") or []
    metrica = alvo.get("metrica")
    modalidade = alvo.get("modalidade")

    tem_nucleo = bool(nucleo) and _contem_todos(texto, nucleo)
    if tem_nucleo:
        difere = []
        if metrica and _norm(metrica) not in texto:
            difere.append(f"métrica ({metrica})")
        if modalidade and _norm(modalidade) not in texto:
            difere.append(f"modalidade ({modalidade})")
        achou_var, termo_var = _contem_algum(texto, variacao)
        if achou_var:
            difere.append(f"variação ({termo_var})")
        if difere:
            return "B", "mesmo produto, difere em: " + ", ".join(difere)
        return "A", "idêntico ao alvo (termos-núcleo + métrica/modalidade)"

    achou_sub, termo_sub = _contem_algum(texto, substitutos)
    if achou_sub:
        return "C", f"substituto próximo do alvo ({termo_sub})"

    return "D", "não corresponde ao alvo (sem termos-núcleo nem substituto)"


def _estatistica(valores: list[float]) -> dict | None:
    if not valores:
        return None
    n = len(valores)
    media = statistics.fmean(valores)
    mediana = statistics.median(valores)
    cv = None
    if n >= 2 and media:
        desvio = statistics.stdev(valores)
        cv = round(desvio / media * 100, 2)
    return {
        "n": n,
        "minimo": round(min(valores), 4),
        "maximo": round(max(valores), 4),
        "mediana": round(mediana, 4),
        "media": round(media, 4),
        "cv_percent": cv,
    }


async def agrupar_por_comparabilidade(
    registros: list[dict[str, Any]],
    alvo: dict[str, Any] | None = None,
    dimensoes: list[str] | None = None,
    faixas_quantidade: list[int] | None = None,
    termos_desqualificadores: list[str] | None = None,
    campos: dict[str, str] | None = None,
    limiar_cv_homogeneo: float = 25.0,
) -> dict[str, Any]:
    """Agrupa preços por comparabilidade e classifica cada um na escala A–D.

    Tool **pura** (sem rede). Passo recomendado ANTES de
    ``calcular_preco_referencia``: evita o erro de tirar média entre objetos
    diferentes. Combina bem com ``normalizar_precos_unidade`` (normalize a
    unidade primeiro; agrupe depois).

    **O grau A–D é correspondência TEXTUAL/estrutural ao alvo — NÃO é atestado
    de que os preços são comparáveis.** São dois eixos distintos: o grau (a
    descrição bate com o objeto?) e a homogeneidade dos preços (o CV). Um grupo
    grau A com CV alto significa que a descrição corresponde, mas os preços não
    são homogêneos — sinal forte de mistura de escala/unidade (ex.: contrato
    global anual junto com preço unitário). Por isso cada grupo carrega
    ``homogeneo`` e ``confiavel_para_calculo`` (ver Returns), e há dois portões
    contra rótulo A indevido:

    - **Portão de unidade:** se o ``alvo`` declara ``unidade``, um registro com
      unidade diferente cai no máximo para C — impede que um insumo (ex.:
      sabonete, unidade "frasco") entre como "idêntico" a um serviço (unidade
      "posto"/"m²") só por citar o termo do objeto.
    - **Portão de CV:** um grupo com CV acima de ``limiar_cv_homogeneo`` é
      marcado ``homogeneo=False`` e ``confiavel_para_calculo=False``, com um
      alerta explícito, mesmo que o grau textual seja A.

    **Uso seguro (nunca decida pelo ``grau`` sozinho).** O ``grau`` é só
    aderência textual — um consumidor que olhe apenas ele será induzido a
    tratar A como comparável. Para cálculo, use **exclusivamente** grupos com
    ``confiavel_para_calculo=True`` (veja também ``resumo.
    grupos_confiaveis_para_calculo``). Para serviços, recomenda-se: (1) sempre
    informar ``alvo.unidade``; (2) passar ``termos_desqualificadores`` com
    insumos comuns (ex.: sabonete, detergente, papel, dispenser, insumo,
    material) para não misturar serviço com material; (3) normalizar contratos
    globais (``normalizar_precos_unidade``) ANTES de agrupar.

    Args:
        registros: lista de dicts (saída de qualquer tool de busca, idealmente
            já normalizada). Campos lidos por nome, com alternativas (ver
            ``campos``): descrição, unidade, quantidade, meses e valor. Todos
            os campos originais são preservados na saída.
        alvo: opcional — o objeto que se quer contratar, para atribuir A–D.
            Chaves reconhecidas: ``termos_nucleo`` (lista; todos devem aparecer
            para A/B), ``termos_variacao`` (diferença menor → B),
            ``termos_substituto`` (substituto próximo → C), ``metrica`` e
            ``modalidade`` (strings que, se ausentes no texto, rebaixam A→B) e
            ``unidade`` (unidade de fornecimento esperada — registro com
            unidade diferente cai para C). Sem ``alvo``, a tool agrupa e detecta
            D intrínseco, mas não dá A/B/C. Dica para SERVIÇOS: declare
            ``unidade`` e passe ``termos_desqualificadores`` com insumos comuns
            para não misturar serviço com material.
        dimensoes: dimensões de agrupamento. Padrão:
            ``["unidade", "faixa_quantidade"]`` (o grau, quando há alvo, também
            entra na chave, para cada grupo ser homogêneo). Valores possíveis:
            ``"unidade"``, ``"faixa_quantidade"``, ``"periodo_meses"``.
        faixas_quantidade: limiares das faixas (padrão ``[10, 100, 1000]`` →
            "1-9", "10-99", "100-999", "1000+").
        termos_desqualificadores: termos que marcam D (padrão inclui
            locação, equipamento, kit, bundle etc.).
        campos: mapeamento opcional de nome de campo (ex.:
            ``{"descricao": "objeto", "valor": "valor_normalizado"}``).
        limiar_cv_homogeneo: CV (%) máximo para um grupo ser considerado
            homogêneo nos preços (padrão 25, alinhado ao guia). Acima dele o
            grupo é marcado ``homogeneo=False``/``confiavel_para_calculo=False``.

    Returns:
        Dicionário com ``alvo``, ``dimensoes``, ``faixas_quantidade``,
        ``total``, ``resumo`` (contagem por grau A/B/C/D e sem_classificacao),
        ``grupos`` e ``nao_comparaveis`` (grau D, com ``motivo``) e ``avisos``.
        Cada grupo tem ``grau``, ``chave`` das dimensões, ``contagem``,
        ``estatistica`` (min/mediana/média/CV dos valores do grupo),
        ``homogeneo`` (bool, do CV vs ``limiar_cv_homogeneo``),
        ``confiavel_para_calculo`` (bool = homogêneo E grau A/B/C E ≥ 3 preços),
        ``alertas`` (lista — CV alto e/ou amostra pequena) e ``registros``.
        Grupos ordenados por grau (A→C) e contagem.
    """
    dimensoes = dimensoes or ["unidade", "faixa_quantidade"]
    dimensoes_validas = {"unidade", "faixa_quantidade", "periodo_meses"}
    invalidas = [d for d in dimensoes if d not in dimensoes_validas]
    if invalidas:
        raise ValueError(
            f"dimensoes inválidas: {invalidas}. Use: {sorted(dimensoes_validas)}"
        )

    limiares = faixas_quantidade or _FAIXAS_PADRAO
    desqualificadores = (
        termos_desqualificadores if termos_desqualificadores is not None
        else _DESQUALIFICADORES_PADRAO
    )
    mapa = {**_CAMPOS_PADRAO}
    if campos:
        # cada override vira o primeiro candidato daquele campo
        for chave, nome in campos.items():
            mapa[chave] = [nome, *mapa.get(chave, [])]

    grupos: dict[tuple, dict[str, Any]] = {}
    nao_comparaveis: list[dict[str, Any]] = []
    resumo = {"A": 0, "B": 0, "C": 0, "D": 0, "sem_classificacao": 0}

    for registro in registros:
        descricao = _primeiro_campo(registro, mapa["descricao"]) or ""
        texto = _norm(descricao)
        grau, motivo = _classificar(texto, alvo, desqualificadores)

        if grau == "D":
            nao_comparaveis.append({**registro, "grau": "D", "motivo": motivo})
            resumo["D"] += 1
            continue

        unidade = _norm(_primeiro_campo(registro, mapa["unidade"])) or "sem_unidade"
        quantidade = _num(_primeiro_campo(registro, mapa["quantidade"]))
        meses = _num(_primeiro_campo(registro, mapa["meses"]))

        # Portão de UNIDADE: grau A/B exige a MESMA unidade de
        # fornecimento do alvo, quando o alvo a declara. Correspondência
        # textual não basta — sem este portão, um INSUMO (ex.: sabonete,
        # unidade "frasco") que cite o termo do objeto entrava como "idêntico"
        # a um SERVIÇO (unidade "posto"/"m²"). Unidade diferente do alvo => no
        # máximo C (parcialmente comparável), nunca A/B.
        unidade_alvo = _norm(alvo.get("unidade")) if (alvo and alvo.get("unidade")) else None
        if (
            unidade_alvo
            and grau in ("A", "B")
            and unidade not in ("sem_unidade", unidade_alvo)
        ):
            grau = "C"
            motivo = (
                f"unidade divergente do alvo ({unidade} vs {unidade_alvo}) — "
                "rebaixado de correspondência textual para parcialmente comparável "
                "(provável insumo/escopo diferente do objeto do alvo)"
            )

        resumo[grau if grau else "sem_classificacao"] += 1

        chave_dim: dict[str, Any] = {}
        for d in dimensoes:
            if d == "unidade":
                chave_dim["unidade"] = unidade
            elif d == "faixa_quantidade":
                chave_dim["faixa_quantidade"] = _faixa_quantidade(quantidade, limiares)
            elif d == "periodo_meses":
                chave_dim["periodo_meses"] = f"{int(meses)}m" if meses else "sem_periodo"

        chave = (grau, tuple(sorted(chave_dim.items())))
        grupo = grupos.setdefault(
            chave,
            {"grau": grau, "chave": chave_dim, "registros": [], "_valores": []},
        )
        grupo["registros"].append({**registro, "grau": grau, "motivo_grau": motivo})
        valor = _num(_primeiro_campo(registro, mapa["valor"]))
        if valor is not None and valor > 0:
            grupo["_valores"].append(valor)

    # monta saída de grupos
    ordem_grau = {"A": 0, "B": 1, "C": 2, None: 3}
    grupos_saida = []
    for grupo in grupos.values():
        valores = grupo.pop("_valores")
        est = _estatistica(valores)
        cv = est.get("cv_percent") if est else None
        n_valores = est.get("n") if est else 0
        # Portão de CV: o grau é correspondência TEXTUAL; o CV mede
        # a homogeneidade dos PREÇOS. Um grupo textualmente A com CV alto NÃO é
        # comparável de fato (sinal forte de mistura de escala/unidade — ex.:
        # contrato global anual junto com preço unitário). Antes, o CV só saía
        # como aviso solto e o grupo seguia rotulado "A idêntico"; agora cada
        # grupo carrega 'homogeneo' e 'confiavel_para_calculo', e um alerta
        # explícito quando o grau textual não é respaldado pelos preços.
        homogeneo = cv is None or cv <= limiar_cv_homogeneo
        confiavel = homogeneo and grupo["grau"] in ("A", "B", "C") and (n_valores or 0) >= 3
        alertas_grupo: list[str] = []
        if cv is not None and not homogeneo:
            alertas_grupo.append(
                f"CV {cv}% (> {limiar_cv_homogeneo:g}%): a descrição corresponde ao "
                f"alvo (grau {grupo['grau']}), mas os PREÇOS não são homogêneos — "
                "sinal forte de mistura de objeto/escala/unidade (ex.: contrato "
                "global com preço unitário, ou serviço com insumo). Grau é "
                "correspondência textual, NÃO atestado de comparabilidade de preço."
            )
        if n_valores and n_valores < 3:
            alertas_grupo.append(
                f"amostra pequena ({n_valores} preço(s) válido(s)) — amplie antes "
                "de alegar robustez estatística."
            )
        # Rótulo explícito: o grau A–D é só correspondência textual.
        # Sem um rótulo claro, "grau A" era lido como "comparável" mesmo com CV
        # de 150% (achado real 2026-07-29). O rótulo deixa a aptidão para
        # cálculo inequívoca na própria apresentação.
        grau_txt = grupo["grau"] or "sem classificação"
        if confiavel:
            rotulo = f"Grau {grau_txt} textual — apto para cálculo"
        else:
            razoes = []
            if cv is not None and not homogeneo:
                razoes.append(f"CV {cv}% elevado")
            if (n_valores or 0) < 3:
                razoes.append("amostra < 3")
            if grupo["grau"] not in ("A", "B", "C"):
                razoes.append("sem grau de comparabilidade (informe 'alvo')")
            motivo = "; ".join(razoes) or "revisar"
            rotulo = (
                f"Grau {grau_txt} textual — NÃO utilizável para cálculo "
                f"({motivo}). O grau reflete só aderência textual ao alvo, não "
                "comparabilidade econômica."
            )
        grupos_saida.append(
            {
                "grau": grupo["grau"],
                "rotulo": rotulo,
                "chave": grupo["chave"],
                "contagem": len(grupo["registros"]),
                "estatistica": est,
                "homogeneo": homogeneo,
                "confiavel_para_calculo": confiavel,
                "alertas": alertas_grupo,
                "registros": grupo["registros"],
            }
        )
    grupos_saida.sort(key=lambda g: (ordem_grau.get(g["grau"], 9), -g["contagem"]))

    avisos: list[str] = []
    if nao_comparaveis:
        avisos.append(
            f"{len(nao_comparaveis)} de {len(registros)} registro(s) marcados como "
            "NÃO comparáveis (grau D) e fora dos grupos/estatística — ver "
            "'nao_comparaveis' e o motivo de cada um."
        )
    n_nao_confiaveis = sum(1 for g in grupos_saida if not g["confiavel_para_calculo"])
    if n_nao_confiaveis:
        avisos.append(
            f"{n_nao_confiaveis} de {len(grupos_saida)} grupo(s) NÃO são confiáveis "
            "para cálculo direto (CV alto, unidade divergente do alvo, ou amostra "
            "< 3) — ver 'alertas' e 'confiavel_para_calculo' em cada grupo. "
            "Lembrete: o grau A–D é correspondência TEXTUAL ao alvo; um grau A com "
            "CV alto significa que a descrição bate mas os preços não são "
            "homogêneos. Normalize a unidade (normalizar_precos_unidade) e cheque "
            "inconsistências (detectar_inconsistencias) antes de calcular."
        )
    if alvo is None:
        avisos.append(
            "Sem 'alvo' informado: registros foram apenas agrupados; a escala A–C "
            "não foi atribuída (só o grau D intrínseco). Informe 'alvo' com "
            "termos_nucleo/variacao/substituto (e, idealmente, 'unidade') para a "
            "classificação relativa."
        )

    # Aptidão visível já no resumo: um consumidor que olhe só o
    # `grau` (ex.: PrecifiCA) seria induzido a tratar A como comparável — o
    # resumo passa a dizer, de cara, quantos grupos são realmente utilizáveis.
    resumo["grupos_total"] = len(grupos_saida)
    resumo["grupos_confiaveis_para_calculo"] = sum(
        1 for g in grupos_saida if g["confiavel_para_calculo"]
    )

    logger.info(
        "agrupar_por_comparabilidade total=%d grupos=%d confiaveis=%d nao_comparaveis=%d",
        len(registros), len(grupos_saida),
        resumo["grupos_confiaveis_para_calculo"], len(nao_comparaveis),
    )

    return {
        "alvo": alvo,
        "dimensoes": dimensoes,
        "faixas_quantidade": limiares,
        "total": len(registros),
        "resumo": resumo,
        "grupos": grupos_saida,
        "nao_comparaveis": nao_comparaveis,
        "avisos": avisos,
    }
