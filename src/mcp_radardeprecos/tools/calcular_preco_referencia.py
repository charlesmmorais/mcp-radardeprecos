"""Tool MCP: calcula o preço de referência a partir de uma cesta de preços coletados.

Implementa a metodologia descrita em "Pesquisa de preços — um guia prático
de sobrevivência" (Franklin Brasil, Set/2020) — ver
o guia de boas práticas de pesquisa de preços para o mapeamento completo. Ao
contrário das demais tools deste servidor, esta é **pura**: não consulta
nenhuma API, apenas trata estatisticamente uma lista de preços já coletados
(por exemplo, via ``buscar_pncp_texto``/``buscar_contratacoes_pncp``/
``buscar_contratos_compras``, ou de outras fontes como cotações de
fornecedores e o Painel de Preços).
"""
from __future__ import annotations

import statistics
from enum import Enum
from typing import Any

from ..domain import distribuicao
from ..domain.dominios import METODOS_CALCULO_PRECO
from ..logging_utils import get_logger

logger = get_logger(__name__)

# CV <= 25% é o limiar de homogeneidade aceitável citado no guia para
# validar a média saneada como preço de referência.
_CV_ACEITAVEL_PERCENTUAL = 25.0
# O guia recomenda ao menos 3 referências para o tratamento estatístico.
_AMOSTRA_MINIMA_RECOMENDADA = 3
# Acima deste percentual de exclusão, o resultado traz um aviso para revisão.
# É informativo: não muda o status. O escore Z não tem teto de iterações — para
# na meta de CV ou no piso de 3 referências, e cada volta remove um valor, então
# o laço sempre termina.
_PERCENTUAL_EXCLUSAO_ALERTA = 20.0
# O alerta só vale a partir deste tamanho de amostra. Em amostras pequenas cada
# exclusão pesa demais no percentual: o exemplo oficial do IPPC-TIC remove 3 de
# 8 preços (37,5%) e é o resultado correto do método.
_AMOSTRA_MINIMA_ALERTA_EXCLUSAO = 20


class MotivoParadaSaneamento(str, Enum):
    """Por que o saneamento parou — enumerado, não inferido do resultado.

    Existe porque até a v0.5.11 "parei porque convergi" e "parei porque
    desisti" produziam saídas indistinguíveis. Os nomes foram fixados na
    v0.5.17 a pedido de quem usa o resultado no processo: cada um responde
    "posso usar este número?" sem consultar mais nada.
    """

    #: O CV chegou à meta removendo outliers. É a única parada que significa
    #: saneamento bem-sucedido.
    META_CV_ATINGIDA = "meta_cv_atingida"
    #: A amostra já estava homogênea e NADA foi removido — `valores_excluidos`
    #: vem vazio e `iteracoes_saneamento` vem 0. Até a v0.5.15 o corte era
    #: aplicado assim mesmo, descartando preços válidos de uma série boa.
    CV_INICIAL_JA_ACEITAVEL = "cv_inicial_ja_aceitavel"
    #: Guarda: continuar deixaria menos de 3 referências. Para mesmo com CV
    #: acima da meta — reduzir a 2 para "forçar" o número não torna a amostra
    #: representativa.
    PISO_MINIMO_AMOSTRA = "piso_minimo_amostra"
    #: Todos os valores são iguais: o escore Z é indefinido (divisão por zero)
    #: e não há dispersão a tratar.
    DESVIO_PADRAO_ZERO = "desvio_padrao_zero"
    #: Nenhum valor caiu fora do critério do método — na média saneada, nada
    #: ficou fora de ``[média - dp, média + dp]``, cujos limites são
    #: inclusivos. NÃO é o mesmo que "o CV já estava na meta": em
    #: ``[74, 100, 126]`` o CV é 26% e mesmo assim não há o que remover.
    #: Acontece também em amostras maiores que 3.
    SEM_OUTLIER_PELO_CRITERIO = "sem_outlier_pelo_criterio"
    #: Só em `media_saneada`: o corte em bloco foi aplicado uma vez e alcançou
    #: a meta.
    PASSE_UNICO_CONCLUIDO = "passe_unico_concluido"
    #: Só em `media_saneada`: um passe não bastou. O método é de passe único e
    #: **não garante** a meta; iterar para persegui-la foi o defeito da
    #: v0.5.11, e é por isso que ele deixou de ser o método padrão.
    META_NAO_ATINGIDA = "meta_nao_atingida"


#: Paradas que significam saneamento bem-sucedido. Tudo que não estiver aqui
#: exige revisão humana antes de o número virar preço de referência.
_PARADAS_DE_SUCESSO = {
    MotivoParadaSaneamento.META_CV_ATINGIDA,
    MotivoParadaSaneamento.CV_INICIAL_JA_ACEITAVEL,
    MotivoParadaSaneamento.PASSE_UNICO_CONCLUIDO,
    MotivoParadaSaneamento.DESVIO_PADRAO_ZERO,
}

#: Paradas que invalidam o número: ou um guarda agiu, ou a meta não foi
#: alcançada. Em qualquer delas o resultado reflete onde o algoritmo parou.
_PARADAS_QUE_INVALIDAM = {
    MotivoParadaSaneamento.PISO_MINIMO_AMOSTRA,
    MotivoParadaSaneamento.META_NAO_ATINGIDA,
    MotivoParadaSaneamento.SEM_OUTLIER_PELO_CRITERIO,
}

#: Paradas que são um limite agindo, não um critério estatístico satisfeito.
_PARADAS_POR_GUARDA = {
    MotivoParadaSaneamento.PISO_MINIMO_AMOSTRA,
}

# Orientação padrão quando a amostra é pequena ou heterogênea — empurra para a
# AÇÃO certa (ampliar + normalizar + agrupar), em vez de "trocar o método"
# (anti-padrão real observado: trocar média por mediana numa amostra de 2 não
# resolve nada; mediana de 2 é a média dos 2).
_ORIENTACAO_AMPLIAR = (
    "Trocar o método estatístico (média/mediana/escore Z) NÃO resolve amostra "
    "pequena nem mistura de objetos. Antes de recalcular: (1) AMPLIE a coleta "
    "— mais termos/sinônimos e as fontes prioritárias "
    "(buscar_precos_praticados_compras, consultar_ata_registro_preco, "
    "buscar_homologados_14133); (2) monte a série com montar_cesta_precos a "
    "partir dos RESULTADOS da busca (não transcreva preço a preço — é o que "
    "gera amostra pequena); (3) traga tudo à mesma unidade com "
    "normalizar_precos_unidade; (4) separe objetos comparáveis com "
    "agrupar_por_comparabilidade e calcule só sobre UM grupo homogêneo."
)


def _desvio_padrao(valores: list[float]) -> float:
    """Desvio-padrão AMOSTRAL (n-1 no denominador).

    Convenção única do módulo desde a v0.5.15. Antes havia duas: o
    ``media_saneada`` usava populacional (``pstdev``) e o ``escore_z``
    amostral (``stdev``), o que tornava o "CV final" incomparável entre os
    métodos — na amostra de piso, 33,33% num contra 27,22% no outro, seis
    pontos de diferença que vinham só da convenção.

    A unificação escolheu a amostral porque era a única com **âncora
    verificada**: é ela que reproduz os CV do exemplo oficial do IPPC-TIC
    (40,12%/35,65%/25,06%/14,48%, AGU/MGI 2024, p. 71). O populacional se
    justificava por uma alegação sobre "as planilhas de saneamento mais comuns
    no setor público" que este projeto nunca conferiu contra fonte alguma —
    exatamente o tipo de suposição confortável que já custou caro aqui.

    É também o ``DESVPAD.A`` do Excel, o padrão de ``statistics.stdev``, e o
    que ``agrupar_por_comparabilidade`` já usava nesta mesma base.

    Efeitos colaterais medidos da mudança, todos na direção de podar menos: a
    banda ``média ± dp`` fica um pouco mais larga (numa normal de n=100, 28
    exclusões em vez de 29), e a meta de CV <= 25% fica um pouco mais rígida,
    o que pode fazer o ``escore_z`` remover um valor a mais em casos de
    fronteira.

    Com menos de 2 valores devolve 0 — não há dispersão a medir, e
    ``statistics.stdev`` levantaria exceção.
    """
    if len(valores) < 2:
        return 0.0
    return statistics.stdev(valores)


def _sanear_amostra(
    valores: list[float],
) -> tuple[list[float], list[float], int, MotivoParadaSaneamento, list[dict[str, Any]]]:
    """Média Saneada: UM corte em bloco na faixa média ± desvio-padrão.

    Calcula média e desvio-padrão da amostra **uma vez**, descarta os valores
    fora de ``[média - dp, média + dp]`` e devolve a média do que restou. Não
    itera — e a ausência de iteração é o ponto, não uma simplificação.

    Por que deixou de iterar
    ----------------------------------
    A versão anterior repetia o corte sobre a amostra já depurada, dizendo
    parar "até não haver mais exclusões". Essa condição é inalcançável para
    qualquer amostra contínua: a faixa de ±1 dp deixa ~32% dos valores de
    fora; removidos eles, o que sobra está truncado, o dp encolhe, e a faixa
    seguinte é proporcionalmente mais estreita — de novo ~30% a 44% cai fora.
    O laço só terminava ao esbarrar no teto de 10 iterações ou no piso de 3
    valores.

    Medido em 08/09/2026, amostra lognormal de 200 preços com CV inicial
    37,1%: o passe único retém 150 valores (75%) com CV 21,0%; o laço retinha
    4 valores (2%) com CV 0,1%. O defeito foi encontrado por comparação com um
    cálculo independente que fazia o corte em bloco, exatamente como a
    documentação da ferramenta anuncia.

    O CV baixo era a armadilha: apresentado como indicador de qualidade,
    era o sintoma. Quanto menor o CV devolvido, mais da amostra havia sido
    consumida para produzi-lo.

    Piso de 3 preservado: se o corte deixaria menos de 3 valores,
    ele não é aplicado — a amostra original é devolvida intacta e o CV alto
    remanescente vira aviso. Reduzir a 2 para "forçar" um CV baixo não torna
    a amostra representativa.

    Returns:
        ``(amostra, excluídos, iterações, motivo_da_parada)``. ``iterações``
        é 1 quando houve corte e 0 quando não houve — o campo é mantido por
        compatibilidade com consumidores da v0.4.
    """
    if not valores:
        return [], [], 0, MotivoParadaSaneamento.CV_INICIAL_JA_ACEITAVEL, []

    media = statistics.mean(valores)
    dp = _desvio_padrao(valores)

    # v0.5.16: se a série já está dentro da meta, não há outlier a remover, e
    # cortar assim mesmo removeria ~30% de uma amostra boa — o corte em bloco
    # não tem parada por CV, então a poda seria ruído, não saneamento.
    if media and (dp / media * 100) <= _CV_ACEITAVEL_PERCENTUAL:
        return list(valores), [], 0, MotivoParadaSaneamento.CV_INICIAL_JA_ACEITAVEL, []

    limite_inferior = media - dp
    limite_superior = media + dp

    dentro = [v for v in valores if limite_inferior <= v <= limite_superior]
    fora = [v for v in valores if v < limite_inferior or v > limite_superior]

    if not fora:
        # v0.5.19: era CV_INICIAL_JA_ACEITAVEL, o que produzia a contradição
        # de anunciar "CV aceitável" com CV de 26%. Os limites da faixa são
        # inclusivos, então em [74, 100, 126] os três valores ficam dentro e
        # não há o que remover — fato diferente de "o CV já estava na meta".
        return list(valores), [], 0, MotivoParadaSaneamento.SEM_OUTLIER_PELO_CRITERIO, []
    if len(dentro) < _AMOSTRA_MINIMA_RECOMENDADA:
        # Preserva a amostra inteira: cortar aqui trocaria dispersão real por
        # uma amostra degenerada, que é a troca que este módulo recusa.
        return list(valores), [], 0, MotivoParadaSaneamento.PISO_MINIMO_AMOSTRA, []

    # v0.5.16: o passe único NÃO garante a meta — e é honesto dizer qual dos
    # dois desfechos ocorreu. Iterar até alcançá-la foi o defeito da v0.5.11.
    media_final = statistics.mean(dentro)
    dp_final = _desvio_padrao(dentro)
    cv_depois = (dp_final / media_final * 100) if media_final else 0.0
    alcancou = bool(media_final) and cv_depois <= _CV_ACEITAVEL_PERCENTUAL
    motivo = (
        MotivoParadaSaneamento.PASSE_UNICO_CONCLUIDO
        if alcancou
        else MotivoParadaSaneamento.META_NAO_ATINGIDA
    )
    # UMA entrada, com a lista inteira: é o que distingue este método do
    # escore Z no histórico. `valores_excluidos` no plural, e sem `escore_z`,
    # porque o critério do corte em bloco não é o escore Z — uniformizar a
    # forma esconderia que os dois removem de modos diferentes.
    historico = [
        {
            "iteracao": 1,
            "criterio": "media_mais_ou_menos_um_desvio",
            "quantidade_antes": len(valores),
            "media_antes": round(media, 4),
            "desvio_padrao_antes": round(dp, 4),
            "cv_antes_percentual": round(dp / media * 100, 2) if media else 0.0,
            "valores_excluidos": list(fora),
            "cv_depois_percentual": round(cv_depois, 2),
        }
    ]
    return dentro, fora, 1, motivo, historico


def _sanear_amostra_escore_z(
    valores: list[float],
) -> tuple[list[float], list[float], int, MotivoParadaSaneamento, list[dict[str, Any]]]:
    """Aplica o saneamento por Escore Z do IPPC-TIC (AGU/MGI, 2024, p. 70-72).

    Mesmo critério de parada da Média Saneada (CV = DP/M x 100 <= 25%), mas
    a cada iteração remove **apenas o valor de maior |Escore Z|** — não todo
    o lote fora da faixa [média - desvio-padrão, média + desvio-padrão] de
    uma vez, como faz ``_sanear_amostra``. Escore Z de um valor V:
    ``Z = (V - média) / desvio_padrão``.

    Algoritmo e exemplo numérico confirmados no texto integral do IPPC-TIC
    (upload do usuário à Claude, 142 páginas, seção "Pesquisa de Preços",
    p. 71 — "Item 02"): amostra [10.18, 9.92, 12.50, 12.11, 6.24, 14.00,
    4.20, 18.14], CV inicial 40,12%, 4 iterações removendo 1 valor por vez
    (18.14, depois 4.20, depois 6.24) até CV 14,48% — replicado em
    ``tests/test_calcular_preco_referencia.py``. Ver
    o guia de boas práticas de pesquisa de preços seção 6.

    Desvio-padrão **amostral** (n-1): é a única forma de reproduzir os CV
    exatos do exemplo oficial (40,12%/35,65%/25,06%/14,48%). Desde a v0.5.15
    é a convenção de todo o módulo — ver :func:`_desvio_padrao`.

    Retorna ``(amostra, excluídos, iterações, motivo_da_parada)``. O motivo
    separa 'cheguei à meta de CV' de 'esbarrei num guarda de
    segurança' — indistinguíveis até então, e a segunda é a que invalida o
    resultado para uso no processo.
    """
    atual = list(valores)
    excluidos: list[float] = []
    historico: list[dict[str, Any]] = []
    iteracoes = 0

    # Piso de 3: para ao chegar em 3 valores, mesmo com CV > 25% —
    # não degenera a amostra abaixo do mínimo recomendado só para baixar o CV.
    # Estrutura conforme a especificação de 09/09/2026. A ordem dos testes é
    # o contrato: mérito primeiro, guardas depois. Se o CV já está na meta, a
    # parada é sucesso — atribuí-la a um limite seria mentir sobre o motivo.
    motivo = MotivoParadaSaneamento.META_CV_ATINGIDA
    while True:
        media = statistics.mean(atual) if atual else 0.0
        dp = _desvio_padrao(atual)

        if not dp:
            # Todos iguais: o escore Z é (x - média)/0. Não há dispersão a
            # tratar, e dividir por zero produziria NaN silencioso.
            motivo = (
                MotivoParadaSaneamento.DESVIO_PADRAO_ZERO
                if not iteracoes
                else MotivoParadaSaneamento.META_CV_ATINGIDA
            )
            break

        cv = (dp / media * 100) if media else 0.0
        if cv <= _CV_ACEITAVEL_PERCENTUAL:
            motivo = (
                MotivoParadaSaneamento.META_CV_ATINGIDA
                if iteracoes
                else MotivoParadaSaneamento.CV_INICIAL_JA_ACEITAVEL
            )
            break
        if len(atual) <= _AMOSTRA_MINIMA_RECOMENDADA:
            motivo = MotivoParadaSaneamento.PISO_MINIMO_AMOSTRA
            break
        # Sem teto de iterações: um teto fixo (era 10) interrompia amostras
        # grandes antes da meta — 375 preços de um CATMAT precisavam de 49
        # exclusões. O percentual excluído é informado e, acima de
        # _PERCENTUAL_EXCLUSAO_ALERTA, gera aviso.

        # Remove só o valor de maior |Escore Z| desta iteração (em caso de
        # empate, o primeiro na ordem original — critério determinístico).
        indice_pior = max(range(len(atual)), key=lambda i: abs((atual[i] - media) / dp))
        valor = atual[indice_pior]
        # v0.5.19: a docstring prometia "cada exclusão com o CV que a motivou"
        # e o retorno só trazia o CV inicial e o final. Sem o passo a passo,
        # quem audita não consegue distinguir uma remoção que era claramente
        # necessária de uma que foi de fronteira.
        registro = {
            "iteracao": iteracoes + 1,
            "criterio": "maior_escore_z",
            "quantidade_antes": len(atual),
            "media_antes": round(media, 4),
            "desvio_padrao_antes": round(dp, 4),
            "cv_antes_percentual": round(cv, 2),
            "valor_excluido": valor,
            "escore_z": round((valor - media) / dp, 4),
        }
        excluidos.append(atual.pop(indice_pior))
        iteracoes += 1
        media_depois = statistics.mean(atual) if atual else 0.0
        dp_depois = _desvio_padrao(atual)
        registro["cv_depois_percentual"] = (
            round(dp_depois / media_depois * 100, 2) if media_depois else 0.0
        )
        historico.append(registro)

    return atual, excluidos, iteracoes, motivo, historico


async def calcular_preco_referencia(
    precos: list[float],
    metodo: str | None = None,
    serie_homogenea: bool | None = None,
    exigir_serie_homogenea: bool = False,
) -> dict[str, Any]:
    """Calcula o preço de referência a partir de uma cesta de preços coletados.

    **Método padrão: Escore Z iterativo**. Calcula o CV da amostra;
    se já estiver em 25% ou menos, **não remove nada** — não há outlier a
    tratar numa série homogênea. Acima disso, remove **um valor por iteração**,
    o de maior |Escore Z|, e recalcula o CV a cada remoção, até atingir a meta
    ou chegar ao piso de 3 referências; não há teto de iterações. Em amostras de
    20 preços ou mais, excluir mais de 20% gera um aviso de revisão. É o
    método preferencial para TIC segundo o IPPC-TIC (AGU/MGI, 2024) e a
    orientação "Análise Crítica na Pesquisa de Preços" (SGD, 2026, item 1.4),
    e é o mais auditável: cada exclusão fica registrada com o CV que a
    motivou.

    A **Média Saneada** (``metodo="media_saneada"``, usada pelo TCU no Acórdão
    355/2019-P) continua disponível, mas **não é mais o padrão**. Ela corta em
    UM passe todos os valores fora de ``[média - dp, média + dp]``, o que tem
    duas consequências: remove vários preços de uma vez, e **não garante** CV
    <= 25% — limitação declarada em ``motivo_parada_saneamento`` como
    ``meta_nao_atingida``, em vez de silenciada. Reaplicar o corte para
    perseguir a meta não converge e consome a amostra; foi o defeito corrigido
    na v0.5.12.

    Nos dois métodos, o saneamento **nunca reduz a amostra abaixo de 3**
    (mínimo do guia), mesmo que o CV permaneça acima de 25% — reduzir a 2 ou 1
    para "forçar" um CV baixo não torna a amostra representativa; nesse caso o
    CV alto é sinalizado em ``avisos``, orientando ampliar/normalizar/agrupar
    em vez de trocar o método.

    **Mediana** e **Mínimo** seguem a jurisprudência do TCU citada no guia: a
    mediana é mais robusta a valores discrepantes que a média simples
    (Acórdãos 631/2014-P e 3033/2013-P); o mínimo deve ficar restrito a
    mercados com poucos fornecedores (Acórdão 8.514/2017-2C). Nenhum dos dois
    aplica saneamento.

    Esta tool é **pura** — não acessa nenhuma API. Os preços informados
    devem ser previamente coletados (com as demais tools deste servidor ou
    outras fontes) e já filtrados para conter apenas preços de itens
    efetivamente vencedores/homologados/contratados: o guia adverte que
    preços estimados em editais e propostas desclassificadas não são
    referências válidas.

    Args:
        precos: Lista de preços unitários coletados (valores positivos).
            O guia recomenda ao menos 3 referências para que o tratamento
            estatístico seja confiável; amostras menores ainda são
            calculadas, mas geram aviso.
        metodo: Método a aplicar. Se omitido, usa "escore_z" (padrão desde a
            v0.5.17 — remove 1 outlier por vez, pelo maior |Escore Z|, até
            CV <= 25%, e não remove nada se o CV inicial já estiver na meta).
            Alternativas: "media_saneada" (corte em bloco de um passe em
            média ± desvio-padrão, Acórdão TCU 355/2019-P; não garante a
            meta de CV), "mediana" (baixo risco ou amostra heterogênea) e
            "minimo" (uso excepcional, mercado restrito).

    Returns:
        Dicionário com:
        - ``metodo_utilizado``: método efetivamente aplicado.
        - ``preco_referencia``: valor final proposto (arredondado a 4 casas).
        - ``estatisticas``: média, mediana, mínimo, máximo, desvio_padrao e
          coeficiente_variacao_percentual da amostra final considerada
          (após saneamento, quando aplicável).
        - ``amostra_original``: quantidade e valores informados, para
          rastreabilidade na formalização da pesquisa.
        - ``amostra_saneada``: valores restantes após o saneamento (igual à
          amostra original quando ``metodo`` é "mediana" ou "minimo").
        - ``valores_excluidos``: valores removidos pelo saneamento — em
          lote, fora da faixa média ± desvio-padrão ("media_saneada"), ou
          um por iteração, pelo maior |Escore Z| ("escore_z"); vazio para
          "mediana"/"minimo".
        - ``iteracoes_saneamento``: passes de saneamento. Em "media_saneada"
          é 0 ou 1 (o método é de passe único); em "escore_z", quantos valores
          foram removidos um a um.
        - ``motivo_parada_saneamento``: por que o saneamento parou.
          ``meta_cv_atingida`` (removeu outliers e chegou à meta),
          ``cv_inicial_ja_aceitavel`` (nada foi removido — a série já estava
          homogênea), ``sem_outlier_pelo_criterio`` (nada ficou fora da faixa
          do método, o que NÃO implica CV na meta), ``piso_minimo_amostra``,
          ``desvio_padrao_zero``,
          ``passe_unico_concluido`` e ``meta_nao_atingida`` (estes dois só na
          média saneada); ``None`` em "mediana"/"minimo".
        - ``status_resultado``: ``"apto"``, ``"requer_revisao"`` ou
          ``"nao_apto"`` — resposta direta a "posso usar este número?", sem
          precisar cruzar quatro campos. É ``nao_apto`` quando há indício de
          mistura de objetos, quando a parada foi por guarda, ou quando
          ``serie_homogenea=False``; ``requer_revisao`` quando a homogeneidade
          de unidade não foi informada.
        - ``apto_para_preco_referencia``: booleano equivalente a
          ``status_resultado == "apto"``, para consumidores que só precisam do
          sim/não.
        - ``historico_saneamento``: uma entrada por passo, com quantidade,
          média, desvio-padrão e CV **antes**, o que foi removido e o CV
          **depois**. No escore Z traz ``valor_excluido`` e ``escore_z``; na
          média saneada, ``valores_excluidos`` (plural, o lote do passe
          único) e nenhum escore — as formas diferem porque os critérios de
          remoção diferem.
        - ``percentual_excluido``: quanto da amostra o saneamento removeu. Lido
          junto com o CV, impede a leitura invertida que o defeito da v0.5.11
          produzia — CV baixo por ter sobrado quase nada.
        - ``cv_inicial_percentual`` e ``cv_final_percentual``: o CV antes e
          depois do saneamento. O par é o que torna a exclusão auditável —
          mostra de onde a série partiu e aonde chegou.
        - ``meta_cv_percentual``: o limiar contra o qual a parada foi
          decidida (25%), explícito para que o número não precise ser
          lembrado de fora.
        - ``diagnostico_distribuicao``: indício de que a série reúne mais de
          um objeto (dois produtos sob o mesmo código, ou produto e peças).
          ``possivel_mistura_de_objetos`` tem TRÊS estados — ``true``,
          ``false`` e ``null`` ("não foi possível avaliar", em amostra
          pequena). É **heurística declarada** (``metodo:
          "heuristica_de_lacuna"``), nunca bloqueia nem altera o cálculo.
          Importa porque, numa série com dois grupos, remover outliers não
          limpa ruído: escolhe um dos grupos.
        - ``avisos``: alertas (amostra pequena, CV acima de 25% mesmo após
          o saneamento, parada pelo piso de 3 referências, mais de 20% da
          amostra excluída no escore Z com 20 preços ou mais, possível mistura de
          objetos, uso do método "minimo") — não impedem o cálculo, mas
          indicam pontos a justificar na formalização da pesquisa.
    """
    if not precos:
        raise ValueError("precos não pode ser uma lista vazia")
    if any(p <= 0 for p in precos):
        raise ValueError("todos os preços devem ser valores positivos")
    if metodo is not None and metodo not in METODOS_CALCULO_PRECO:
        raise ValueError(f"metodo deve ser um de {METODOS_CALCULO_PRECO}")

    # v0.5.17: o padrão passou a ser o escore Z iterativo. A média saneada
    # continua disponível, mas não como padrão — ela remove vários preços de
    # uma vez e, sendo de passe único, não garante a meta de CV. O escore Z
    # remove um por vez e para no critério, o que é mais controlável e mais
    # auditável: cada exclusão fica registrada com o CV que a motivou.
    metodo_utilizado = metodo or "escore_z"
    avisos: list[str] = []

    if len(precos) < _AMOSTRA_MINIMA_RECOMENDADA:
        avisos.append(
            f"Amostra com {len(precos)} valor(es) — abaixo do mínimo de "
            f"{_AMOSTRA_MINIMA_RECOMENDADA} do guia. {_ORIENTACAO_AMPLIAR} "
            "Se, após ampliar, o mercado for mesmo restrito, justifique a "
            "limitação/desinteresse de fornecedores no processo."
        )

    logger.info(
        "calcular_preco_referencia metodo=%s tamanho_amostra=%d",
        metodo_utilizado, len(precos),
    )

    valores_excluidos: list[float] = []
    iteracoes = 0
    # Sobre a amostra ORIGINAL, de propósito: depois do saneamento a lacuna
    # pode ter sido apagada justamente pela poda que ela deveria desaconselhar.
    diagnostico = distribuicao.diagnosticar(precos)
    media_inicial = statistics.mean(precos)
    cv_inicial = (
        _desvio_padrao(precos) / media_inicial * 100 if media_inicial else None
    )
    motivo_parada: MotivoParadaSaneamento | None = None
    historico: list[dict[str, Any]] = []

    if metodo_utilizado == "mediana":
        amostra_final = list(precos)
        preco_referencia = statistics.median(amostra_final)
    elif metodo_utilizado == "minimo":
        amostra_final = list(precos)
        preco_referencia = min(amostra_final)
        avisos.append(
            "Método 'minimo' deve ficar restrito a mercados com poucos "
            "fornecedores (Acórdão TCU 8.514/2017-2C) — justificar no "
            "processo."
        )
    elif metodo_utilizado == "escore_z":
        amostra_final, valores_excluidos, iteracoes, motivo_parada, historico = (
            _sanear_amostra_escore_z(precos)
        )
        preco_referencia = statistics.mean(amostra_final)
    else:
        amostra_final, valores_excluidos, iteracoes, motivo_parada, historico = (
            _sanear_amostra(precos)
        )
        preco_referencia = statistics.mean(amostra_final)

    media_final = statistics.mean(amostra_final)
    # v0.5.15: uma convenção só (amostral) para todos os métodos. Antes o
    # ramo abaixo escolhia por método, e o mesmo campo `desvio_padrao`
    # significava coisas diferentes conforme quem chamava.
    dp_final = _desvio_padrao(amostra_final)
    cv_final = (dp_final / media_final * 100) if media_final else 0.0

    if metodo_utilizado in ("media_saneada", "escore_z"):
        # v0.5.12: um limite de segurança que age precisa dizer que agiu. Sem
        # este aviso, "parei porque convergi" e "parei porque desisti"
        # produziam a mesma saída, e a segunda invalida o número para uso no
        # processo — foi o que manteve invisível a poda excessiva do laço
        # antigo da média saneada.
        if motivo_parada in _PARADAS_POR_GUARDA:
            avisos.append(
                f"O saneamento parou por LIMITE de segurança "
                f"({motivo_parada.value}), não por atingir o critério "
                f"estatístico. O resultado reflete onde o algoritmo parou, não "
                f"uma amostra saneada até a meta — reveja antes de usar como "
                f"preço de referência. {_ORIENTACAO_AMPLIAR}"
            )
        if len(amostra_final) < _AMOSTRA_MINIMA_RECOMENDADA:
            avisos.append(
                f"Após o saneamento restaram {len(amostra_final)} valor(es), "
                f"abaixo do mínimo de {_AMOSTRA_MINIMA_RECOMENDADA}. "
                f"{_ORIENTACAO_AMPLIAR}"
            )
        elif cv_final > _CV_ACEITAVEL_PERCENTUAL:
            # v0.5.19: o texto era fixo e citava o piso de 3 mesmo quando
            # sobravam 5 ou 8 valores — atribuía à guarda uma parada que fora
            # do método. Um aviso só, com o motivo verdadeiro.
            if motivo_parada == MotivoParadaSaneamento.PISO_MINIMO_AMOSTRA:
                contexto = (
                    f"O saneamento atingiu o piso mínimo de "
                    f"{_AMOSTRA_MINIMA_RECOMENDADA} referências e parou."
                )
            elif motivo_parada == MotivoParadaSaneamento.META_NAO_ATINGIDA:
                contexto = (
                    "A Média Saneada executou seu único passe e o CV permaneceu "
                    "acima da meta — o método não garante alcançá-la, e repetir "
                    "o corte consumiria a amostra sem torná-la representativa."
                )
            elif motivo_parada == MotivoParadaSaneamento.SEM_OUTLIER_PELO_CRITERIO:
                contexto = (
                    "Nenhum valor ficou fora da faixa média ± desvio-padrão, "
                    "então não havia o que remover pelo critério do método."
                )
            else:
                contexto = "A meta de CV não foi atingida."
            avisos.append(
                f"Coeficiente de Variação final de {cv_final:.1f}% acima de "
                f"{_CV_ACEITAVEL_PERCENTUAL:.0f}%. {contexto} A amostra NÃO deve "
                "ser considerada homogênea — é sinal forte de objetos, planos ou "
                "unidades diferentes na mesma cesta. Separe com "
                "agrupar_por_comparabilidade e traga à mesma base com "
                "normalizar_precos_unidade; calcule só sobre o grupo homogêneo. "
                "Trocar o método não torna preços heterogêneos comparáveis."
            )
        # Só no escore Z: a média saneada corta ~30% de qualquer amostra num
        # passe, por definição, e o aviso viraria ruído.
        percentual_removido = len(valores_excluidos) / len(precos) * 100
        if (
            metodo_utilizado == "escore_z"
            and len(precos) >= _AMOSTRA_MINIMA_ALERTA_EXCLUSAO
            and percentual_removido > _PERCENTUAL_EXCLUSAO_ALERTA
        ):
            avisos.append(
                f"O saneamento excluiu {len(valores_excluidos)} de {len(precos)} "
                f"preços ({percentual_removido:.1f}%), acima de "
                f"{_PERCENTUAL_EXCLUSAO_ALERTA:.0f}% da amostra. Uma série que só "
                "fica homogênea descartando tanto costuma misturar objetos, "
                "apresentações ou unidades — revise os excluídos (historico_saneamento) "
                "antes de usar o preço."
            )

    # Homogeneidade de UNIDADE, propagada de quem coletou a série.
    #
    # Esta tool recebe uma lista de números; não tem como saber, sozinha, se
    # eles estão na mesma unidade de fornecimento. O coeficiente de variação
    # acima é um indício indireto — uma série de unidades diferentes pode ter
    # CV baixo e ainda assim ser incomparável (100 caixas de 10 e 100 unidades
    # avulsas com preços parecidos).
    #
    # O padrão é AVISAR e devolver o campo legível por máquina, não bloquear.
    # Bloqueio com sinalizador de contorno vira ritual: quem quer o número
    # passa o sinalizador e a proteção não protege ninguém. Além disso há caso
    # legítimo — série já normalizada por fora. Quem precisa da trava rígida
    # pede `exigir_serie_homogenea=True`.
    if serie_homogenea is False:
        avisos.append(
            "SÉRIE NÃO HOMOGÊNEA na origem: os preços foram coletados em "
            "unidades de fornecimento DIFERENTES. O preço de referência abaixo "
            "agrega grandezas incomensuráveis e não deve ser usado sem antes "
            "separar por unidade (agrupar_por_comparabilidade) ou converter à "
            "mesma base (normalizar_precos_unidade)."
        )
    elif serie_homogenea is None and precos:
        avisos.append(
            "Homogeneidade de unidade NÃO informada por quem montou a série. "
            "Este cálculo assume que todos os preços estão na mesma unidade de "
            "fornecimento — se não estiverem, o resultado não tem significado. "
            "Passe 'serie_homogenea' vindo de buscar_precos_praticados_compras "
            "para que esta verificação deixe de ser uma suposição."
        )
    if exigir_serie_homogenea and serie_homogenea is not True:
        raise ValueError(
            "exigir_serie_homogenea=True e a série não é comprovadamente "
            f"homogênea (serie_homogenea={serie_homogenea!r}). Separe por "
            "unidade com agrupar_por_comparabilidade, ou converta à mesma base "
            "com normalizar_precos_unidade, e calcule sobre o grupo homogêneo."
        )

    # v0.5.19: status legível por MÁQUINA. Sem ele, um agente que lê só
    # `preco_referencia` não tem como saber que metade da amostra foi
    # eliminada, ou que a série reúne dois objetos — a informação existia,
    # mas só no texto de `avisos`, que ninguém garante que será lido.
    #
    # O `preco_referencia` NÃO é apagado: ele serve à auditoria e mostra o que
    # o algoritmo teria feito. O que muda é que passa a vir acompanhado de um
    # campo que diz se serve.
    if diagnostico.get("possivel_mistura_de_objetos") is True:
        status_resultado = "nao_apto"
    elif motivo_parada in _PARADAS_QUE_INVALIDAM:
        status_resultado = "nao_apto"
    elif serie_homogenea is False:
        status_resultado = "nao_apto"
    elif serie_homogenea is None:
        # Quem não informou está SUPONDO que os preços estão na mesma unidade.
        # Suposição não é verificação, e o status diz isso sem bloquear.
        status_resultado = "requer_revisao"
    elif motivo_parada in _PARADAS_DE_SUCESSO or motivo_parada is None:
        status_resultado = "apto"
    else:
        status_resultado = "requer_revisao"

    texto_mistura = distribuicao.aviso(diagnostico, metodo_utilizado)
    if texto_mistura:
        # No topo: quando a série mistura objetos, os avisos de CV alto e de
        # exclusão são sintomas dela, e lidos primeiro levam ao tratamento
        # errado (remover mais).
        avisos.insert(0, texto_mistura)

    return {
        "metodo_utilizado": metodo_utilizado,
        "serie_homogenea": serie_homogenea,
        "preco_referencia": round(preco_referencia, 4),
        "estatisticas": {
            "media": round(media_final, 4),
            "mediana": round(statistics.median(amostra_final), 4),
            "minimo": round(min(amostra_final), 4),
            "maximo": round(max(amostra_final), 4),
            "desvio_padrao": round(dp_final, 4),
            "coeficiente_variacao_percentual": round(cv_final, 2),
        },
        "amostra_original": {
            "quantidade": len(precos),
            "valores": precos,
        },
        "amostra_saneada": amostra_final,
        "valores_excluidos": valores_excluidos,
        "iteracoes_saneamento": iteracoes,
        # v0.5.12: os dois campos que teriam tornado o defeito visível sem
        # depurar. `percentual_excluido` dá escala ao CV — um CV baixo com 98%
        # da amostra excluída não é homogeneidade, é o resíduo da poda.
        "motivo_parada_saneamento": motivo_parada.value if motivo_parada else None,
        # "apto" | "requer_revisao" | "nao_apto" — resposta direta a "posso
        # usar este número?", sem precisar interpretar quatro campos.
        "status_resultado": status_resultado,
        "apto_para_preco_referencia": status_resultado == "apto",
        # Cada exclusão com o CV que a motivou. Era prometido no docstring
        # desde a v0.5.17 e não existia no retorno.
        "historico_saneamento": historico,
        # O par inicial/final é o que torna a exclusão auditável: mostra de
        # onde a série partiu, aonde chegou, e contra qual meta.
        "cv_inicial_percentual": round(cv_inicial, 2) if cv_inicial is not None else None,
        "cv_final_percentual": round(cv_final, 2),
        "meta_cv_percentual": _CV_ACEITAVEL_PERCENTUAL,
        # Três estados: True (indício), False (procurado, não achado) e None
        # (não foi possível avaliar) — ver domain/distribuicao.py.
        "diagnostico_distribuicao": diagnostico,
        "percentual_excluido": (
            round(len(valores_excluidos) / len(precos) * 100, 2) if precos else 0.0
        ),
        "avisos": avisos,
    }
