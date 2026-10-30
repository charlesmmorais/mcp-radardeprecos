"""Testes das diretrizes de pesquisa de preços (domínio + tool, sem rede)."""
from __future__ import annotations

from mcp_radardeprecos.domain.diretrizes_pesquisa_precos import (
    DIRETRIZES_PESQUISA_PRECOS,
    renderizar_markdown,
)
from mcp_radardeprecos.tools.obter_diretrizes_pesquisa_precos import (
    obter_diretrizes_pesquisa_precos,
)


def test_estrutura_tem_as_chaves_esperadas():
    chaves_esperadas = {
        "fonte",
        "conceito_central",
        "fases",
        "fontes_prioritarias",
        "regras_amostra",
        "janela_temporal",
        "metodos_calculo",
        "curva_abc",
        "checklist_formalizacao",
    }
    assert chaves_esperadas.issubset(DIRETRIZES_PESQUISA_PRECOS.keys())


def test_fases_cobrem_as_cinco_etapas_do_guia():
    nomes_fase = {f["fase"] for f in DIRETRIZES_PESQUISA_PRECOS["fases"]}
    assert nomes_fase == {
        "objeto",
        "planejamento",
        "coleta",
        "tratamento",
        "formalizacao",
    }
    for fase in DIRETRIZES_PESQUISA_PRECOS["fases"]:
        assert fase["pontos_chave"], f"fase {fase['fase']} sem pontos_chave"


def test_fontes_prioritarias_estao_em_ordem_e_cotacao_e_a_ultima():
    fontes = DIRETRIZES_PESQUISA_PRECOS["fontes_prioritarias"]
    posicoes = [f["posicao"] for f in fontes]
    assert posicoes == sorted(posicoes)
    assert "fornecedores" in fontes[-1]["fonte"].lower()


def test_fonte_prioridade_1_referencia_a_tool_que_ja_cobre_ela():
    # Regressão: a observação chegou a dizer, por vários meses,
    # que a fonte de maior prioridade normativa "ainda não" era coberta por
    # nenhuma tool — na verdade buscar_precos_praticados_compras cobre isso
    # desde a v0.1.9. Esse texto é servido ao vivo por
    # obter_diretrizes_pesquisa_precos e pelo MCP Resource, então uma
    # informação errada aqui pode levar quem consulta a diretriz a preferir
    # uma fonte de prioridade mais baixa sem necessidade.
    fontes = DIRETRIZES_PESQUISA_PRECOS["fontes_prioritarias"]
    prioridade_1 = next(f for f in fontes if f["posicao"] == 1)
    assert "buscar_precos_praticados_compras" in prioridade_1["observacao"]
    assert "ainda não" not in prioridade_1["observacao"].lower()


def test_regras_amostra_exige_minimo_de_tres_e_apenas_precos_validos():
    regras = DIRETRIZES_PESQUISA_PRECOS["regras_amostra"]
    assert regras["minimo_referencias"] == 3
    assert "homologad" in regras["apenas_precos_validos"].lower()


def test_janela_temporal_reflete_o_limite_da_nll():
    janela = DIRETRIZES_PESQUISA_PRECOS["janela_temporal"]
    # Mesmo limite usado pelo parâmetro janelas_meses das tools de busca.
    assert janela["limite_legal_nll_meses"] == 6


def test_janela_temporal_detalha_prazo_por_fonte():
    # v0.2.7: regressão do texto genérico "6 meses para tudo" — a IN
    # SEGES/ME 65/2021 varia o prazo por fonte (contratações públicas
    # similares e notas fiscais admitem até 1 ano; só mídia/cotação direta
    # ficam em 6 meses). Aplicar 6 meses indistintamente sub-utiliza as
    # fontes de prazo mais longo.
    janela = DIRETRIZES_PESQUISA_PRECOS["janela_temporal"]
    por_fonte = janela["por_fonte"]
    assert len(por_fonte) >= 4
    for item in por_fonte:
        assert item["fonte"]
        assert item["prazo"]

    prazos_por_fonte = {item["fonte"]: item["prazo"] for item in por_fonte}
    contratacoes_similares = next(
        prazo for fonte, prazo in prazos_por_fonte.items()
        if "contrata" in fonte.lower() and "similar" in fonte.lower()
    )
    assert "1" in contratacoes_similares and "ano" in contratacoes_similares.lower()

    cotacao_direta = next(
        prazo for fonte, prazo in prazos_por_fonte.items() if "cotação direta" in fonte.lower()
    )
    assert "6" in cotacao_direta and "meses" in cotacao_direta.lower()

    sistemas_oficiais = next(
        prazo for fonte, prazo in prazos_por_fonte.items()
        if "painel de preços" in fonte.lower()
    )
    assert "sem prazo" in sistemas_oficiais.lower()

    # A observação não pode mais implicar que 6 meses vale para todas as
    # fontes sem ressalva.
    assert "por_fonte" in janela["observacao"] or "varia" in janela["observacao"].lower()


def test_metodos_calculo_referencia_a_tool_correta():
    assert DIRETRIZES_PESQUISA_PRECOS["metodos_calculo"]["tool"] == "calcular_preco_referencia"


async def test_tool_devolve_exatamente_a_estrutura_de_dominio():
    resultado = await obter_diretrizes_pesquisa_precos()
    assert resultado == DIRETRIZES_PESQUISA_PRECOS


def test_renderizar_markdown_inclui_secoes_principais():
    texto = renderizar_markdown()
    assert texto.startswith("# Diretrizes de pesquisa de preços")
    for titulo in (
        "## Fases da pesquisa de preços",
        "## Fontes de referência, por prioridade",
        "## Regras da amostra",
        "## Janela temporal",
        "## Métodos de cálculo",
        "## Curva ABC",
        "## Checklist de formalização",
    ):
        assert titulo in texto


def test_renderizar_markdown_e_deterministica():
    # Mesma estrutura -> mesmo texto (sem timestamps ou aleatoriedade).
    assert renderizar_markdown() == renderizar_markdown()
