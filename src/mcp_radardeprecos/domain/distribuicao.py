"""Detecção de mistura de objetos numa série de preços.

Por que isto não é "mais um filtro de outlier"
----------------------------------------------
Outlier e mistura de objetos exigem tratamentos opostos, e a diferença decide
se o preço de referência significa alguma coisa:

- **outlier** é um valor errado ou atípico dentro de UM mercado. Remover é o
  tratamento correto — é o que a média saneada e o escore Z fazem.
- **mistura de objetos** é a série conter DOIS mercados. Aí não há um centro a
  encontrar, e remover valores não limpa ruído: **escolhe um dos grupos**, em
  silêncio, pelo caminho que o algoritmo tomar.

O caso que motivou o módulo (CATMAT 434228, esfigmomanômetro de pedestal,
verificado em 09/09/2026, 19 preços com cobertura exaustiva):

    33,75  58,00  64,06  66,00  74,90  83,00  92,16  99,90  129,99
    -------------------- lacuna de 2,27x --------------------
    294,90  347,00  348,99  349,99  357,50  360,00  369,00  390,00  466,66  544,05

Todos os 19 têm a mesma descrição, o mesmo PDM e a mesma unidade. O código é
do produto **com pedestal**, e é usado também para comprar o modelo comum e
peças avulsas — dois objetos sob um código só. **Nenhum metadado os separa;
só o preço.** Por isso ``agrupar_por_comparabilidade``, que agrupa por
dimensões declaradas, não alcança este caso.

O que os métodos fizeram com essa série:

===============  ============  ==================================
método           resultado     o que aconteceu
===============  ============  ==================================
media_saneada    R$ 253,64     ficou no meio do vazio entre os grupos
escore_z         R$  77,97     removeu os 10 caros e devolveu a média dos baratos
mediana          R$ 294,90     caiu na borda inferior do grupo caro
===============  ============  ==================================

O escore Z não removeu outliers: escolheu o cluster barato — o que **não**
corresponde ao objeto do código — e produziu uma estimativa 4,9 vezes menor,
com CV final de 35% e aparência de série saneada.

Como o detector funciona, e por que ele é declarado como heurística
-------------------------------------------------------------------
Ordena a série, encontra a **maior lacuna** entre valores consecutivos (com
pelo menos ``_MIN_POR_LADO`` de cada lado) e verifica duas condições:

1. a lacuna é grande perto do espaçamento típico da série
   (``lacuna / mediana dos espaçamentos >= _LIMIAR_LACUNA``);
2. separar ali reduz substancialmente a dispersão
   (``1 - dp_interno/dp_total >= _LIMIAR_REDUCAO``).

A segunda condição sozinha não serve: **qualquer** série pode ser partida de
modo a reduzir a variância interna — uma amostra uniforme de n=30 chegou a
65,7% de redução no teste de calibração. É a lacuna que distingue.

**Taxas medidas em 09/09/2026**, 1.000 sorteios por célula:

- falso positivo em séries unimodais: 0,0% a 2,0% (lognormal σ=0,35 e 0,6,
  normal com CV 13% e 30%, uniforme); 6,8% a 8,9% em exponencial pura, que é
  assimetria extrema e rara numa série de preços já filtrada;
- detecção de bimodalidade sintética (n=20, metade em cada grupo): 1,9% com
  separação de 1,5x, 42,5% com 2x, 97,0% com 3x, 99,9% com 5x.

Ou seja: o detector **erra**, e erra mais para menos do que para mais. Por
isso o resultado nunca bloqueia nem altera o cálculo — ele aparece como aviso
e como bloco declarado (``metodo: "heuristica_de_lacuna"``), para que ninguém
confunda a suspeita com uma classificação da fonte. É a mesma disciplina do
``tipo_inferido_de`` usado nos aditivos.
"""
from __future__ import annotations

import statistics
from typing import Any

#: Mínimo de valores de cada lado da lacuna. Com menos, "dois grupos" e "um
#: grupo com dois valores atípicos" ficam indistinguíveis.
_MIN_POR_LADO = 3

#: Abaixo disto não há amostra para julgar a forma da distribuição, e o
#: diagnóstico é `None` (não sei), nunca `False` (não há mistura).
_MIN_AMOSTRA = 8

#: Lacuna, em múltiplos do espaçamento típico. Calibrado para separar o 434228
#: (18,4x) de uma amostra uniforme (10,0x), que é o pior caso unimodal.
_LIMIAR_LACUNA = 12.0

#: Redução mínima do desvio-padrão ao separar nos dois grupos.
_LIMIAR_REDUCAO = 0.5


def _cv(valores: list[float]) -> float | None:
    if len(valores) < 2:
        return None
    media = statistics.mean(valores)
    return statistics.stdev(valores) / media * 100 if media else None


def _resumo(valores: list[float]) -> dict[str, Any]:
    return {
        "quantidade": len(valores),
        "minimo": min(valores),
        "maximo": max(valores),
        "media": round(statistics.mean(valores), 4),
        "coeficiente_variacao_percentual": (
            round(c, 2) if (c := _cv(valores)) is not None else None
        ),
    }


def diagnosticar(precos: list[float]) -> dict[str, Any]:
    """Procura indício de que a série reúne mais de um objeto.

    Args:
        precos: Série de preços unitários positivos.

    Returns:
        ``possivel_mistura_de_objetos`` com **três estados**: ``True``
        (indício encontrado), ``False`` (procurado e não encontrado) e ``None``
        (não foi possível avaliar). ``None`` não é "não há mistura" — é
        "não sei", e a diferença importa numa amostra pequena, onde a mistura é
        justamente mais provável de passar despercebida.

        Quando há indício, ``grupos`` traz as estatísticas de cada lado e
        ``corte_sugerido`` o último valor antes da lacuna. Nada disso é
        aplicado ao cálculo: separar a série é decisão de quem conhece o
        objeto.
    """
    limpos = sorted(float(p) for p in precos if p is not None)
    if len(limpos) < _MIN_AMOSTRA:
        return {
            "possivel_mistura_de_objetos": None,
            "motivo": "amostra_pequena",
            "metodo": "heuristica_de_lacuna",
        }

    # `strict=False` de propósito: `limpos[1:]` é UM elemento menor que
    # `limpos`, por construção — é o que faz o par ser consecutivo.
    espacamentos = [b - a for a, b in zip(limpos, limpos[1:], strict=False)]
    positivos = [e for e in espacamentos if e > 0]
    tipico = statistics.median(espacamentos)
    if tipico <= 0:
        # Mediana zero (muitos valores repetidos): usa o menor espaçamento
        # real, senão a razão seria divisão por zero.
        tipico = min(positivos) if positivos else 0.0
    total = statistics.pstdev(limpos)
    if tipico <= 0 or total <= 0:
        return {
            "possivel_mistura_de_objetos": None,
            "motivo": "serie_sem_dispersao",
            "metodo": "heuristica_de_lacuna",
        }

    n = len(limpos)
    lacuna, k = max(
        (limpos[i] - limpos[i - 1], i) for i in range(_MIN_POR_LADO, n - _MIN_POR_LADO + 1)
    )
    a, b = limpos[:k], limpos[k:]
    dentro = (
        (len(a) * statistics.pvariance(a) + len(b) * statistics.pvariance(b)) / n
    ) ** 0.5
    reducao = 1 - dentro / total
    razao_lacuna = lacuna / tipico

    misturado = razao_lacuna >= _LIMIAR_LACUNA and reducao >= _LIMIAR_REDUCAO
    saida: dict[str, Any] = {
        "possivel_mistura_de_objetos": misturado,
        "metodo": "heuristica_de_lacuna",
        "lacuna_em_espacamentos_tipicos": round(razao_lacuna, 1),
        "reducao_do_desvio_ao_separar": round(reducao, 4),
        "corte_sugerido": limpos[k - 1],
    }
    if misturado:
        saida["grupos"] = [_resumo(a), _resumo(b)]
    return saida


def aviso(diagnostico: dict[str, Any], metodo_calculo: str) -> str | None:
    """Texto de alerta, ou ``None`` quando não há indício de mistura.

    O texto diz o que fazer (separar), não só o que há (mistura) — e nomeia a
    consequência de ignorar, que é o algoritmo de outliers escolher um grupo
    em vez de limpar ruído.
    """
    if not diagnostico.get("possivel_mistura_de_objetos"):
        return None
    grupos = diagnostico.get("grupos") or []
    if len(grupos) != 2:
        return None
    a, b = grupos
    detalhe = (
        f"{a['quantidade']} preços entre {a['minimo']:,.2f} e {a['maximo']:,.2f} "
        f"(CV {a['coeficiente_variacao_percentual']:.1f}%) e "
        f"{b['quantidade']} entre {b['minimo']:,.2f} e {b['maximo']:,.2f} "
        f"(CV {b['coeficiente_variacao_percentual']:.1f}%)"
    )
    consequencia = (
        "Num caso assim, remover outliers NÃO limpa ruído: escolhe um dos "
        "grupos em silêncio, e o preço de referência passa a ser o de um "
        "objeto que pode não ser o seu."
        if metodo_calculo in ("media_saneada", "escore_z")
        else "Média e mediana sobre dois grupos não descrevem nenhum deles."
    )
    return (
        f"POSSÍVEL MISTURA DE OBJETOS na série: há uma lacuna de preço que a "
        f"separa em {detalhe}. Cada grupo é mais homogêneo que o conjunto, o "
        f"que costuma indicar dois produtos sob o mesmo código — modelos "
        f"diferentes, ou o produto e suas peças. {consequencia} Separe com "
        f"agrupar_por_comparabilidade (ou pela descrição/marca dos registros) "
        f"e calcule sobre UM grupo. Este é um indício estatístico, não uma "
        f"classificação da fonte: confira as descrições antes de decidir."
    )
