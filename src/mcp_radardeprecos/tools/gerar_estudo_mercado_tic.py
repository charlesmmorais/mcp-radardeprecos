"""Tool MCP: monta a matriz de comparabilidade de soluções técnicas de TIC candidatas.

Cobre uma exigência específica de contratações de TIC que não é a pesquisa
de **preço** (coberta por
`calcular_preco_referencia`), mas a etapa anterior, de **Estudo de
Mercado** do Estudo Técnico Preliminar (ETP): o **Art. 11, VI, da IN
SGD/ME nº 94/2022** exige "avaliação das alternativas possíveis, e, em
caso de mais de uma solução ser tecnicamente viável, [...] justificativa
técnica e econômica da escolha do tipo de solução". Ou seja: antes de
pesquisar o preço de UMA solução já escolhida, é preciso registrar QUAIS
soluções concorrentes foram avaliadas e POR QUE uma delas foi escolhida —
uma comparação de alternativas técnicas/tecnológicas, não de fornecedores
do mesmo item (isso já é papel de `calcular_preco_referencia` e das tools
de busca de preços praticados).

**Critérios de comparação são deliberadamente livres.** O IPPC-TIC e a IN
94/2022 não fixam uma lista taxativa de critérios técnicos/econômicos
válidos para toda e qualquer contratação de TIC (eles variam demais entre
"licença de software", "solução em nuvem", "outsourcing de impressão"
etc.) — diferente do método estatístico de saneamento de preços (Art. 6º
da IN 65/2021), que é objetivo e replicável, então IMPLEMENTADO como
critério fixo em `calcular_preco_referencia`. Esta tool só monta e valida
a MATRIZ (uma linha por critério, uma coluna por solução) a partir de
``criterios`` livres informados por solução — quem conduz o estudo decide
quais critérios técnicos/econômicos comparar (ex.: modelo de
licenciamento, TCO estimado, aderência a requisitos obrigatórios, riscos
de dependência de fornecedor).

Esta tool é **pura**: não consulta nenhuma API, só estrutura/valida dados
já levantados manualmente (mesmo padrão de `classificar_curva_abc` e
`calcular_preco_referencia`). O resultado devolvido é o mesmo formato de
entrada esperado pelo novo parâmetro opcional ``estudo_mercado`` de
``gerar_relatorio_word`` — mesmo padrão de acoplamento entre
`calcular_preco_referencia` e `gerar_relatorio_word`/`gerar_relatorio_excel`
já usado neste projeto.
"""
from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger

logger = get_logger(__name__)


def _validar_solucoes(solucoes: list[dict[str, Any]]) -> list[str]:
    if not solucoes:
        raise ValueError("solucoes não pode ser uma lista vazia")

    nomes: list[str] = []
    for i, solucao in enumerate(solucoes):
        if not isinstance(solucao, dict):
            raise ValueError(f"solucoes[{i}] deve ser um dicionário")
        nome = solucao.get("nome")
        if not nome or not str(nome).strip():
            raise ValueError(f"solucoes[{i}] não tem 'nome' válido")
        criterios = solucao.get("criterios")
        if criterios is not None and not isinstance(criterios, dict):
            raise ValueError(f"solucoes[{i}] ('{nome}'): 'criterios' deve ser um dicionário")
        nomes.append(str(nome))

    duplicados = sorted({n for n in nomes if nomes.count(n) > 1})
    if duplicados:
        raise ValueError(f"nomes de solução duplicados: {duplicados}")

    return nomes


async def gerar_estudo_mercado_tic(
    solucoes: list[dict[str, Any]],
    solucao_recomendada: str | None = None,
    justificativa_escolha: str | None = None,
) -> dict[str, Any]:
    """Monta a matriz de comparabilidade de soluções técnicas de TIC candidatas.

    Estrutura o **Estudo de Mercado** do ETP (Art. 11, VI, da IN SGD/ME nº
    94/2022): recebe uma lista de soluções tecnicamente candidatas, cada
    uma com seus próprios critérios de avaliação (livres — ver docstring do
    módulo), e devolve uma matriz pronta para virar tabela num relatório
    (uma linha por critério, uma coluna por solução), junto com avisos de
    comparação incompleta/inconsistente.

    Esta tool é **pura** — não acessa nenhuma API. As soluções e seus
    critérios devem ser previamente levantados (ex.: por pesquisa de
    mercado, benchmarking com outros órgãos, ou catálogos de fabricantes).

    Args:
        solucoes: Lista de soluções candidatas. Cada uma é um dicionário
            com ``nome`` (obrigatório, único entre as soluções) e
            ``criterios`` (opcional — dicionário livre de
            critério→valor, ex.: ``{"modelo_licenciamento": "SaaS anual",
            "tco_estimado_36_meses": 450000.0, "atende_requisitos_obrigatorios": True}``).
            Quaisquer outras chaves de cada solução (ex.: ``fabricante``,
            ``observacoes``) são preservadas no retorno, mas não entram na
            matriz.
        solucao_recomendada: Nome de uma das soluções em ``solucoes`` —
            marca qual foi escolhida. Deve corresponder exatamente a um
            ``nome`` informado.
        justificativa_escolha: Texto livre com a justificativa técnica e
            econômica da escolha (exigida pelo Art. 11, VI, da IN 94/2022
            quando há mais de uma solução tecnicamente viável). Sem isso,
            e havendo ``solucao_recomendada`` com mais de uma solução no
            total, um aviso é incluído no retorno.

    Returns:
        Dicionário com:
        - ``solucoes``: a lista de entrada, preservada como veio.
        - ``criterios_comparados``: lista dos nomes de critério (união de
          todas as chaves de ``criterios`` de todas as soluções, na ordem
          de primeira aparição).
        - ``matriz``: lista de linhas, uma por critério — cada linha é um
          dicionário ``{"criterio": ..., "<nome da solução 1>": valor,
          "<nome da solução 2>": valor, ...}`` (``None`` quando a solução
          não informou aquele critério), pronta para virar tabela.
        - ``solucao_recomendada``, ``justificativa_escolha``: ecoados da
          entrada.
        - ``avisos``: alertas de comparação incompleta (nem todas as
          soluções têm todos os critérios), matriz vazia (nenhum critério
          informado), uma única solução (não há de fato "comparação" a
          fazer) ou solução recomendada sem justificativa registrada.
    """
    nomes = _validar_solucoes(solucoes)

    if solucao_recomendada is not None and solucao_recomendada not in nomes:
        raise ValueError(
            f"solucao_recomendada={solucao_recomendada!r} não corresponde a nenhum "
            f"nome em solucoes ({nomes})"
        )

    logger.info(
        "gerar_estudo_mercado_tic quantidade_solucoes=%d solucao_recomendada=%r",
        len(solucoes), solucao_recomendada,
    )

    criterios_comparados: list[str] = []
    for solucao in solucoes:
        for chave in (solucao.get("criterios") or {}).keys():
            if chave not in criterios_comparados:
                criterios_comparados.append(chave)

    matriz: list[dict[str, Any]] = []
    for criterio in criterios_comparados:
        linha: dict[str, Any] = {"criterio": criterio}
        for solucao, nome in zip(solucoes, nomes, strict=False):
            linha[nome] = (solucao.get("criterios") or {}).get(criterio)
        matriz.append(linha)

    avisos: list[str] = []
    if len(solucoes) < 2:
        avisos.append(
            "Apenas 1 solução informada — o Art. 11, VI, da IN SGD/ME nº 94/2022 "
            "exige avaliação de alternativas possíveis; com uma única solução, "
            "registre no processo a justificativa de que não há outra alternativa "
            "tecnicamente viável, em vez de uma comparação."
        )
    if not criterios_comparados:
        avisos.append(
            "Nenhuma solução trouxe critérios de comparação ('criterios') — a "
            "matriz ficou vazia. Informe ao menos um critério técnico/econômico "
            "por solução para fundamentar a escolha."
        )
    else:
        incompletas = []
        for solucao, nome in zip(solucoes, nomes, strict=False):
            chaves_solucao = set((solucao.get("criterios") or {}).keys())
            faltantes = [c for c in criterios_comparados if c not in chaves_solucao]
            if faltantes:
                incompletas.append(f"{nome}: falta(m) {faltantes}")
        if incompletas:
            avisos.append(
                "Comparação incompleta — nem todas as soluções têm todos os "
                "critérios preenchidos (" + "; ".join(incompletas) + "). Preencha "
                "os critérios faltantes para uma comparação homogênea, ou registre "
                "explicitamente que o critério não se aplica."
            )
    if solucao_recomendada and not justificativa_escolha and len(solucoes) > 1:
        avisos.append(
            "solucao_recomendada informada sem justificativa_escolha — o Art. 11, "
            "VI, da IN SGD/ME nº 94/2022 exige justificativa técnica e econômica "
            "da escolha quando há mais de uma solução tecnicamente viável."
        )

    return {
        "solucoes": solucoes,
        "criterios_comparados": criterios_comparados,
        "matriz": matriz,
        "solucao_recomendada": solucao_recomendada,
        "justificativa_escolha": justificativa_escolha,
        "avisos": avisos,
    }
