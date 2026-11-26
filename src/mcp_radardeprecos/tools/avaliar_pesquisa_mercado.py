"""Tool MCP: avaliação de pesquisa de mercado com vários itens (método da média dos demais preços).

Reproduz a planilha "Avaliação de Pesquisa de Mercado" (v5.3) do Superior
Tribunal de Justiça, baseada no Manual de Pesquisa de Preços do tribunal. Para
cada preço:

1. **Excessivamente elevado:** preço acima de ``1 + percentual_excessivo``
   (padrão 125%) da média dos demais preços.
2. **Inexequível:** entre os que sobraram, preço abaixo de
   ``percentual_inexequivel`` (padrão 75%) da média dos demais.
3. **Preços públicos:** um preço inexequível volta a valer se for de fonte
   pública (PNCP, Painel de Preços, ata ou contrato) ou igual a um preço
   público. Se for maior que o menor preço público, é marcado como válido,
   mas — como na planilha — não entra no cálculo (ver ``_avaliar_item``).
4. **Método:** com coeficiente de variação até ``cv_maximo`` (padrão 25%), o
   preço de mercado é a média; acima, a mediana; ou o preço mínimo, se
   ``usar_preco_minimo``. Com um único preço válido, não há preço de mercado.

Checagens do Manual: fontes públicas devem ser a maioria, e deve haver pelo
menos 3 preços válidos.

**Sem estado:** a tool não guarda nada. Recebe o estudo inteiro e devolve a
versão seguinte (``versao + 1``), para o estudo viver na conversa. Os dados do
estudo não vão para os logs.
"""
from __future__ import annotations

import statistics
import unicodedata
from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)

CREDITO = "Baseado na planilha de Avaliação de pesquisa de mercado do STJ"

PADRAO_EXCESSIVO = 0.25
PADRAO_INEXEQUIVEL = 0.75
PADRAO_CV_MAXIMO = 0.25
MINIMO_PRECOS_VALIDOS = 3

# Tipos de fonte. "COMPRASNET" é o nome antigo, aceito como PNCP.
_PUBLICOS = {"PNCP": "PNCP", "PAINEL DE PRECOS": "PAINEL DE PREÇOS", "ATA": "ATA",
             "CONTRATO": "CONTRATO", "COMPRASNET": "PNCP"}
_OUTROS = {"FORNECEDOR": "FORNECEDOR", "PESQUISA NA INTERNET": "PESQUISA NA INTERNET",
           "PESQUISA INTERNET": "PESQUISA NA INTERNET", "MIDIA ESPECIALIZADA": "MÍDIA ESPECIALIZADA",
           "OUTROS": "OUTROS"}
TIPOS_DE_FONTE = sorted(set(_PUBLICOS.values()) | set(_OUTROS.values()))

VALIDO = "VÁLIDO"
EXCESSIVO = "EXCESSIVAMENTE ELEVADO"
INEXEQUIVEL = "INEXEQUÍVEL"
VALIDO_PUBLICO = "VÁLIDO - PREÇO PÚBLICO"
VALIDO_IGUAL = "VÁLIDO - IGUAL A PREÇO PÚBLICO"
VALIDO_MAIOR = "VÁLIDO - MAIOR QUE PREÇO PÚBLICO"

PRECO_UNICO = "PREÇO ÚNICO"
PRECO_MINIMO = "PREÇO MÍNIMO"
MEDIA = "MÉDIA"
MEDIANA = "MEDIANA"


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _tipo(bruto: Any) -> tuple[str | None, bool]:
    """Nome canônico do tipo de fonte e se é preço público."""
    chave = " ".join(_sem_acento(str(bruto or "")).upper().split())
    if chave in _PUBLICOS:
        return _PUBLICOS[chave], True
    if chave in _OUTROS:
        return _OUTROS[chave], False
    return None, False


def _pct(x: float) -> str:
    """Percentual no formato da planilha: 72,55%."""
    texto = f"{x * 100:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".") + "%"


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).replace("R$", "").strip()
    if "," in texto:  # formato brasileiro: 4.900,00
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _observacao(final: str, ha_excessivo: bool, razao1: float | None, razao2: float | None) -> str:
    """Texto da coluna OBSERVAÇÃO, como na planilha (INEXEQ.!M)."""
    retirando = "Retirando preço(s) excessivamente elevado(s), o valor é "
    if final == INEXEQUIVEL:
        if ha_excessivo and razao2 is not None:
            return f"{retirando}{_pct(razao2)} da média dos demais preços."
        r = razao2 if razao2 is not None else razao1
        return f"O valor é {_pct(r)} da média dos demais preços." if r is not None else ""
    if final == EXCESSIVO and razao1 is not None:
        return f"O valor é {_pct(razao1 - 1)} superior à média dos demais preços."
    motivos = {
        VALIDO_PUBLICO: ("Todavia é considerado válido por ser um preço praticado pela Administração Pública.",
                         "Todavia é considerado válido por ser um preço praticado pela Administração Pública."),
        VALIDO_IGUAL: ("Porém, é considerado válido por ser igual a um preço praticado pela Administração Pública.",
                       "No entanto, é considerado válido por ser igual a um preço praticado pela Administração Pública."),
        VALIDO_MAIOR: ("Porém, é considerado válido por ser maior do que um preço praticado pela Administração Pública.",
                       "No entanto, é considerado válido por ser maior do que um preço praticado pela Administração Pública."),
    }
    if final in motivos:
        r = razao2 if razao2 is not None else razao1
        texto_r = f" ({_pct(r)} da média dos demais preços)" if r is not None else ""
        if ha_excessivo:
            return f"{retirando}inexequível{texto_r}. {motivos[final][0]}"
        return f"O valor é inexequível{texto_r}. {motivos[final][1]}"
    return ""


def _avaliar_item(item: dict[str, Any], indice: int, opcoes: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    avisos: list[str] = []
    rotulo = f"Item {indice} ({item.get('descricao') or 'sem descrição'})"
    precos_saida: list[dict[str, Any]] = []
    completos: list[dict[str, Any]] = []

    for n, bruto in enumerate(item.get("precos") or [], start=1):
        if not isinstance(bruto, dict):
            raise ValueError(f"{rotulo}, preço {n}: cada preço deve ser um objeto com fonte, tipo, localizador e valor.")
        valor = _numero(bruto.get("valor"))
        if valor is None or valor <= 0:
            raise ValueError(f"{rotulo}, preço {n}: valor ausente ou inválido ({bruto.get('valor')!r}).")
        tipo, publico = _tipo(bruto.get("tipo"))
        linha = {
            "fonte": bruto.get("fonte"),
            "tipo": tipo or bruto.get("tipo"),
            "localizador": bruto.get("localizador"),
            "valor": valor,
            "publico": publico,
        }
        if not bruto.get("fonte") or tipo is None:
            linha.update(avaliacao="INCOMPLETO", observacao="Informe a fonte e um tipo de fonte válido.",
                         usado_no_calculo=False)
            avisos.append(f"{rotulo}, preço {n}: falta a fonte ou o tipo ({', '.join(TIPOS_DE_FONTE)}); o preço ficou fora da avaliação.")
        else:
            completos.append(linha)
            if not bruto.get("localizador"):
                avisos.append(f"{rotulo}, preço {n}: sem localizador do documento no processo.")
        precos_saida.append(linha)

    # Avaliação 1: excessivamente elevado, contra a média dos demais preços.
    soma, qtd = sum(p["valor"] for p in completos), len(completos)
    for p in completos:
        demais = (soma - p["valor"]) / (qtd - 1) if qtd > 1 else p["valor"]
        p["_razao1"] = p["valor"] / demais
        p["media_dos_demais"] = demais
        p["_av1"] = EXCESSIVO if p["_razao1"] > 1 + opcoes["percentual_excessivo"] else VALIDO

    # Avaliação 2: inexequível, só entre os que passaram na 1.
    restantes = [p for p in completos if p["_av1"] == VALIDO]
    soma2, qtd2 = sum(p["valor"] for p in restantes), len(restantes)
    for p in completos:
        p["_razao2"] = None
        if p["_av1"] == VALIDO and qtd2 > 1:
            demais2 = (soma2 - p["valor"]) / (qtd2 - 1)
            p["_razao2"] = p["valor"] / demais2
            p["media_dos_demais"] = demais2
        p["_av2"] = INEXEQUIVEL if p["_razao2"] is not None and p["_razao2"] < opcoes["percentual_inexequivel"] else p["_av1"]
    ha_excessivo = any(p["_av2"] == EXCESSIVO for p in completos)

    # Avaliação 3: preços públicos.
    publicos = [p["valor"] for p in completos if p["publico"]]
    menor_publico = min(publicos) if publicos else None
    for p in completos:
        igual_publico = (not p["publico"]) and p["valor"] in publicos
        parte2 = p["_av2"]
        if parte2 == INEXEQUIVEL and opcoes["preservar_publicos_inexequiveis"]:
            if p["publico"]:
                parte2 = VALIDO_PUBLICO
            elif igual_publico:
                parte2 = VALIDO_IGUAL
        final = parte2
        if (parte2 == INEXEQUIVEL and opcoes["preservar_publicos_inexequiveis"] and not igual_publico
                and menor_publico is not None and p["valor"] > menor_publico):
            final = VALIDO_MAIOR
        # Como na planilha: o cálculo usa a "Parte 2" da avaliação 3. Um preço
        # "maior que preço público" aparece como válido, mas fica fora da conta.
        p["usado_no_calculo"] = parte2 not in (EXCESSIVO, INEXEQUIVEL)
        p["avaliacao"] = final
        p["observacao"] = _observacao(final, ha_excessivo, p["_razao1"], p["_razao2"])
        p["percentual_em_relacao_aos_demais"] = round((p["_razao2"] if p["_razao2"] is not None else p["_razao1"]) * 100, 2)
        p["media_dos_demais"] = round(p["media_dos_demais"], 2)
        for chave in ("_razao1", "_razao2", "_av1", "_av2"):
            p.pop(chave, None)

    # Estatística e método.
    validos = [p["valor"] for p in completos if p["usado_no_calculo"]]
    media = statistics.mean(validos) if validos else None
    desvio = statistics.stdev(validos) if len(validos) >= 2 else None
    cv = desvio / media if desvio is not None and media else None
    if cv is None:
        metodo = PRECO_UNICO
    elif opcoes["usar_preco_minimo"]:
        metodo = PRECO_MINIMO
    elif cv <= opcoes["cv_maximo"]:
        metodo = MEDIA
    else:
        metodo = MEDIANA
    preco = {PRECO_MINIMO: min(validos) if validos else None, MEDIA: media,
             MEDIANA: statistics.median(validos) if validos else None}.get(metodo)

    problemas: list[str] = []
    qtd_publicos = sum(1 for p in completos if p["publico"])
    if completos and not qtd_publicos > len(completos) / 2:
        problemas.append(f"Os preços praticados pela Administração Pública não são a maioria das fontes ({qtd_publicos} de {len(completos)}).")
    if len(validos) < opcoes["minimo_precos_validos"]:
        problemas.append(f"Pesquisa com menos de {opcoes['minimo_precos_validos']} preços válidos ({len(validos)}).")
    if metodo == PRECO_UNICO and completos:
        problemas.append("Devido às poucas fontes válidas, não foi possível obter o preço de mercado. Amplie a pesquisa ou justifique a impossibilidade de ampliação.")

    quantidade = _numero(item.get("quantidade"))
    contratado = _numero(item.get("preco_contratado"))
    prorrogacao = None
    if opcoes["prorrogacao"] and contratado is not None:
        referencia = min(validos) if metodo == PRECO_UNICO and validos else preco
        desvantajoso = referencia is not None and contratado > referencia
        prorrogacao = {
            "preco_contratado": contratado,
            "desvantajoso": desvantajoso,
            "mensagem": "Preço contratado é desvantajoso. Negociar preços." if desvantajoso else "",
        }

    if not completos:
        status = "sem_precos"
    elif metodo == PRECO_UNICO or len(validos) < opcoes["minimo_precos_validos"]:
        status = "poucos_precos"
    else:
        status = "pronto"

    resultado = {
        "descricao": item.get("descricao"),
        "metrica": item.get("metrica"),
        "quantidade": quantidade,
        "precos": precos_saida,
        "resultado": {
            "preco_mercado": round(preco, 2) if preco is not None else None,
            "metodo_aplicado": metodo,
            "media": round(media, 2) if media is not None else None,
            "mediana": round(statistics.median(validos), 2) if validos else None,
            "preco_minimo": min(validos) if validos else None,
            "desvio_padrao": round(desvio, 4) if desvio is not None else None,
            "coeficiente_variacao_percentual": round(cv * 100, 2) if cv is not None else None,
            "precos_validos": len(validos),
            "valor_total": round(preco * quantidade, 2) if preco is not None and quantidade else None,
        },
        "problemas": problemas,
        "prorrogacao": prorrogacao,
        "status": status,
    }
    return resultado, avisos


async def avaliar_pesquisa_mercado(
    itens: list[dict[str, Any]],
    processo: str | None = None,
    objeto: str | None = None,
    responsavel: str | None = None,
    prorrogacao: bool = False,
    percentual_excessivo: float = PADRAO_EXCESSIVO,
    percentual_inexequivel: float = PADRAO_INEXEQUIVEL,
    cv_maximo: float = PADRAO_CV_MAXIMO,
    usar_preco_minimo: bool = False,
    preservar_publicos_inexequiveis: bool = True,
    minimo_precos_validos: int = MINIMO_PRECOS_VALIDOS,
    versao: int = 0,
) -> dict[str, Any]:
    """Avalia a pesquisa de mercado de um ou mais itens e calcula o preço de mercado de cada um.

    Use quando o usuário pedir uma "avaliação de pesquisa de mercado" ou quiser
    saber, preço a preço, quais são válidos, excessivamente elevados ou
    inexequíveis. Os preços podem vir das buscas deste servidor (PNCP,
    Compras.gov.br, atas) ou ser digitados, como as propostas de fornecedores.

    **O estudo vive na conversa.** A tool não guarda nada: a cada mudança,
    chame-a de novo com o estudo inteiro (todos os itens e opções) e o
    ``versao`` devolvido na última chamada. Ela devolve a versão seguinte.

    Args:
        itens: Lista de itens. Cada item: ``descricao``, ``metrica`` (ex.:
            "usuário/ano", "unidade", "hora"), ``quantidade``, ``precos`` e,
            na prorrogação, ``preco_contratado``. Cada preço: ``fonte`` (nome
            do fornecedor ou órgão), ``tipo`` (PNCP, Painel de Preços, Ata,
            Contrato, Fornecedor, Pesquisa na internet, Mídia especializada ou
            Outros), ``localizador`` (onde o documento está no processo) e
            ``valor`` (preço unitário na métrica do item).
        processo: Número do processo (SEI ou outro).
        objeto: Objeto da contratação.
        responsavel: Responsável pela pesquisa.
        prorrogacao: Se é prorrogação contratual; compara o preço contratado
            de cada item com o preço de mercado.
        percentual_excessivo: Acima de ``1 + este valor`` da média dos demais,
            o preço é excessivamente elevado. Padrão 0,25 (25%).
        percentual_inexequivel: Abaixo deste valor da média dos demais, o preço
            é inexequível. Padrão 0,75 (75%).
        cv_maximo: Coeficiente de variação até o qual se usa a média; acima,
            a mediana. Padrão 0,25 (25%).
        usar_preco_minimo: Usa o menor preço válido como preço de mercado.
        preservar_publicos_inexequiveis: Mantém válidos os preços públicos
            inexequíveis (e os iguais a eles). Padrão: sim.
        minimo_precos_validos: Mínimo de preços válidos por item. Padrão 3.
        versao: Versão do estudo recebida na última chamada (0 se for novo).

    Returns:
        O estudo avaliado: dados do estudo, ``opcoes``, ``itens`` (cada preço
        com ``avaliacao``, ``observacao``, ``percentual_em_relacao_aos_demais``
        e ``usado_no_calculo``; cada item com ``resultado``, ``problemas``,
        ``prorrogacao`` e ``status``: pronto, poucos_precos ou sem_precos),
        ``resumo`` (valor total estimado e itens prontos), ``avisos``,
        ``versao`` e ``credito``.

    Raises:
        ValueError: nenhum item, preço sem valor válido ou opção fora da faixa.
    """
    if not itens:
        raise ValueError("Informe pelo menos um item, com descrição, métrica, quantidade e preços.")
    if not 0 < percentual_excessivo <= 10:
        raise ValueError("percentual_excessivo deve estar entre 0 e 10 (ex.: 0.25 para 25%).")
    if not 0 < percentual_inexequivel < 1:
        raise ValueError("percentual_inexequivel deve estar entre 0 e 1 (ex.: 0.75 para 75%).")
    if not 0 < cv_maximo <= 1:
        raise ValueError("cv_maximo deve estar entre 0 e 1 (ex.: 0.25 para 25%).")
    if minimo_precos_validos < 1:
        raise ValueError("minimo_precos_validos deve ser pelo menos 1.")

    opcoes = {
        "metodo": "media_dos_demais",
        "percentual_excessivo": percentual_excessivo,
        "percentual_inexequivel": percentual_inexequivel,
        "cv_maximo": cv_maximo,
        "usar_preco_minimo": usar_preco_minimo,
        "preservar_publicos_inexequiveis": preservar_publicos_inexequiveis,
        "minimo_precos_validos": minimo_precos_validos,
        "prorrogacao": prorrogacao,
    }
    avisos: list[str] = []
    for nome, valor, padrao in (("excessivamente elevado", percentual_excessivo, PADRAO_EXCESSIVO),
                                ("inexequível", percentual_inexequivel, PADRAO_INEXEQUIVEL),
                                ("coeficiente de variação máximo", cv_maximo, PADRAO_CV_MAXIMO)):
        if abs(valor - padrao) > 1e-9:
            avisos.append(f"O percentual de {nome} ({_pct(valor)}) difere do padrão ({_pct(padrao)}). A alteração deve ser justificada no processo.")
    if not preservar_publicos_inexequiveis:
        avisos.append("Preços públicos inexequíveis não foram preservados; justifique no processo.")

    itens_saida = []
    for i, item in enumerate(itens, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {i}: cada item deve ser um objeto com descrição, métrica, quantidade e preços.")
        saida, avisos_item = _avaliar_item(item, i, opcoes)
        itens_saida.append(saida)
        avisos.extend(avisos_item)

    totais = [i["resultado"]["valor_total"] for i in itens_saida if i["resultado"]["valor_total"] is not None]
    logger.info("avaliar_pesquisa_mercado: %d item(ns), versão %d", len(itens_saida), versao + 1)
    return {
        "versao": versao + 1,
        "processo": processo,
        "objeto": objeto,
        "responsavel": responsavel,
        "prorrogacao": prorrogacao,
        "opcoes": opcoes,
        "itens": itens_saida,
        "resumo": {
            "total_itens": len(itens_saida),
            "itens_prontos": sum(1 for i in itens_saida if i["status"] == "pronto"),
            "valor_total_estimado": round(sum(totais), 2) if totais else None,
        },
        "avisos": avisos,
        "credito": CREDITO,
    }
