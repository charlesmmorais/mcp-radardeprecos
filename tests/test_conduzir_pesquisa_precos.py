"""Testes do MCP Prompt `conduzir_pesquisa_precos` (função pura, sem chamada de rede)."""
from __future__ import annotations

from mcp_radardeprecos.prompts.conduzir_pesquisa_precos import conduzir_pesquisa_precos


def test_retorna_string():
    resultado = conduzir_pesquisa_precos("notebook i5 8GB")
    assert isinstance(resultado, str)


def test_inclui_objeto_informado():
    resultado = conduzir_pesquisa_precos("notebook i5 8GB")
    assert "notebook i5 8GB" in resultado


def test_sem_agente_responsavel_orienta_perguntar():
    resultado = conduzir_pesquisa_precos("notebook i5 8GB")
    assert "ainda não informado" in resultado
    assert "perguntar" in resultado.lower() or "pergunte" in resultado.lower()


def test_com_agente_responsavel_inclui_nome():
    resultado = conduzir_pesquisa_precos("notebook i5 8GB", agente_responsavel="Fulano de Tal")
    assert "Fulano de Tal" in resultado
    assert "ainda não informado" not in resultado


def test_agente_responsavel_em_branco_trata_como_ausente():
    resultado = conduzir_pesquisa_precos("notebook i5 8GB", agente_responsavel="   ")
    assert "ainda não informado" in resultado


def test_cita_todas_as_tools_na_ordem_recomendada():
    resultado = conduzir_pesquisa_precos("notebook i5 8GB")
    tools_na_ordem = [
        "obter_diretrizes_pesquisa_precos",
        "classificar_curva_abc",
        "descobrir_codigo_catalogo",
        "buscar_precos_praticados_compras",
        "buscar_contratacoes_pncp",
        "buscar_contratos_compras",
        "consultar_ata_registro_preco",
        "normalizar_precos_unidade",
        "agrupar_por_comparabilidade",
        "calcular_preco_referencia",
        "gerar_memoria_pesquisa",
    ]
    posicoes = [resultado.index(nome) for nome in tools_na_ordem]
    assert posicoes == sorted(posicoes), "as tools devem aparecer na ordem recomendada pelo guia"


def test_passo_de_tratamento_antes_do_calculo():
    # Normalizar unidade e agrupar comparabilidade
    # devem vir ANTES de calcular_preco_referencia no roteiro.
    resultado = conduzir_pesquisa_precos("Microsoft 365 E3")
    assert "normalizar_precos_unidade" in resultado
    assert "agrupar_por_comparabilidade" in resultado
    assert resultado.index("normalizar_precos_unidade") < resultado.index(
        "calcular_preco_referencia"
    )
    assert resultado.index("agrupar_por_comparabilidade") < resultado.index(
        "calcular_preco_referencia"
    )


def test_menciona_janela_temporal_e_minimo_de_referencias():
    resultado = conduzir_pesquisa_precos("notebook i5 8GB")
    assert "janelas_meses" in resultado
    assert "mínimo de 3" in resultado or "mínimo 3" in resultado


def test_menciona_registro_de_buscas_frustradas():
    resultado = conduzir_pesquisa_precos("notebook i5 8GB")
    assert "buscas_frustradas" in resultado
