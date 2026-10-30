"""Testes de `gerar_memoria_pesquisa` (tool pura, sem chamada de rede)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos.tools.gerar_memoria_pesquisa import gerar_memoria_pesquisa

_RESULTADO_CALCULO = {
    "metodo_utilizado": "media_saneada",
    "preco_referencia": 10.05,
    "amostra_original": {"quantidade": 2, "valores": [10.0, 10.1]},
    "amostra_saneada": [10.0, 10.1],
    "valores_excluidos": [],
    "iteracoes_saneamento": 0,
    "estatisticas": {
        "media": 10.05,
        "mediana": 10.05,
        "minimo": 10.0,
        "maximo": 10.1,
        "desvio_padrao": 0.05,
        "coeficiente_variacao_percentual": 0.5,
    },
    "avisos": [],
}

_FONTES = [
    {
        "informante": "Fornecedor A Ltda",
        "cnpj": "11111111000111",
        "meio_consulta": "PNCP - busca textual",
        "data_referencia": "2026-06-01",
        "valor_unitario": 10.0,
        "quantidade": 5,
        "url": "https://pncp.gov.br/exemplo",
        "especificacao": "Papel A4 75g/m2",
        "condicoes": "Entrega em 30 dias",
    },
    {
        "informante": "Fornecedor B Ltda",
        "meio_consulta": "Compras.gov.br - preços praticados",
        "data_referencia": "2026-06-02",
        "valor_unitario": 10.1,
    },
]


async def test_rejeita_objeto_vazio():
    with pytest.raises(ValueError):
        await gerar_memoria_pesquisa("", "Fulano", _FONTES, _RESULTADO_CALCULO)


async def test_rejeita_agente_vazio():
    with pytest.raises(ValueError):
        await gerar_memoria_pesquisa("Papel A4", "  ", _FONTES, _RESULTADO_CALCULO)


async def test_rejeita_formato_invalido():
    with pytest.raises(ValueError):
        await gerar_memoria_pesquisa(
            "Papel A4", "Fulano", _FONTES, _RESULTADO_CALCULO, formato="pdf"
        )


async def test_rejeita_resultado_calculo_sem_campos_esperados():
    with pytest.raises(ValueError):
        await gerar_memoria_pesquisa("Papel A4", "Fulano", _FONTES, {"algo": 1})


async def test_rejeita_fontes_vazia():
    with pytest.raises(ValueError):
        await gerar_memoria_pesquisa("Papel A4", "Fulano", [], _RESULTADO_CALCULO)


async def test_rejeita_fonte_sem_campo_obrigatorio():
    fontes_incompletas = [{"informante": "Fornecedor A", "valor_unitario": 10.0}]
    with pytest.raises(ValueError, match="fontes\\[0\\]"):
        await gerar_memoria_pesquisa("Papel A4", "Fulano", fontes_incompletas, _RESULTADO_CALCULO)


async def test_rejeita_busca_frustrada_sem_campo_obrigatorio():
    with pytest.raises(ValueError, match="buscas_frustradas\\[0\\]"):
        await gerar_memoria_pesquisa(
            "Papel A4",
            "Fulano",
            _FONTES,
            _RESULTADO_CALCULO,
            buscas_frustradas=[{"meio_consulta": "Painel de Preços"}],
        )


async def test_formato_json_padrao_nao_inclui_markdown():
    resultado = await gerar_memoria_pesquisa("Papel A4", "Fulano", _FONTES, _RESULTADO_CALCULO)
    assert "documento_markdown" not in resultado
    assert resultado["objeto"] == "Papel A4"
    assert resultado["agente_responsavel"] == "Fulano"
    assert resultado["quantidade_fontes"] == 2
    assert resultado["metodologia"]["metodo_utilizado"] == "media_saneada"
    assert resultado["metodologia"]["preco_referencia"] == 10.05


async def test_data_pesquisa_default_e_customizada():
    resultado = await gerar_memoria_pesquisa("Papel A4", "Fulano", _FONTES, _RESULTADO_CALCULO)
    assert resultado["data_pesquisa"]  # preenchida automaticamente

    resultado2 = await gerar_memoria_pesquisa(
        "Papel A4", "Fulano", _FONTES, _RESULTADO_CALCULO, data_pesquisa="2026-01-15"
    )
    assert resultado2["data_pesquisa"] == "2026-01-15"


async def test_aviso_quando_nenhuma_busca_frustrada_registrada():
    resultado = await gerar_memoria_pesquisa("Papel A4", "Fulano", _FONTES, _RESULTADO_CALCULO)
    assert any("Nenhuma busca frustrada" in a for a in resultado["avisos"])


async def test_sem_aviso_quando_busca_frustrada_informada():
    resultado = await gerar_memoria_pesquisa(
        "Papel A4",
        "Fulano",
        _FONTES,
        _RESULTADO_CALCULO,
        buscas_frustradas=[
            {"meio_consulta": "Painel de Preços", "termo_busca": "papel a4", "motivo": "sem resultado"}
        ],
    )
    assert not any("Nenhuma busca frustrada" in a for a in resultado["avisos"])
    assert resultado["buscas_frustradas"][0]["motivo"] == "sem resultado"


async def test_aviso_quando_quantidade_fontes_diverge_da_amostra():
    resultado = await gerar_memoria_pesquisa(
        "Papel A4", "Fulano", _FONTES[:1], _RESULTADO_CALCULO
    )
    assert any("diferente do tamanho da" in a for a in resultado["avisos"])


async def test_formato_markdown_inclui_documento_e_secoes_esperadas():
    resultado = await gerar_memoria_pesquisa(
        "Papel A4",
        "Fulano",
        _FONTES,
        _RESULTADO_CALCULO,
        buscas_frustradas=[
            {"meio_consulta": "Painel de Preços", "termo_busca": "papel a4", "motivo": "sem resultado"}
        ],
        formato="markdown",
    )
    doc = resultado["documento_markdown"]
    assert "# Memória de Pesquisa de Preços" in doc
    assert "Papel A4" in doc
    assert "## Fontes consultadas (2)" in doc
    assert "Fornecedor A Ltda" in doc
    assert "## Buscas frustradas (1)" in doc
    assert "## Conclusão" in doc


async def test_aviso_quando_fonte_sem_url_e_sem_evidencia_acesso():
    # _FONTES[1] (Fornecedor B Ltda) não tem "url" nem "evidencia_acesso".
    resultado = await gerar_memoria_pesquisa("Papel A4", "Fulano", _FONTES, _RESULTADO_CALCULO)
    assert any(
        "Fonte 2 (Fornecedor B Ltda)" in a and "evidencia_acesso" in a
        for a in resultado["avisos"]
    )


async def test_sem_aviso_de_evidencia_quando_fonte_tem_url():
    fontes = [_FONTES[0]]  # tem "url"
    resultado = await gerar_memoria_pesquisa(
        "Papel A4", "Fulano", fontes, _RESULTADO_CALCULO,
        buscas_frustradas=[{"meio_consulta": "x", "motivo": "y"}],
    )
    assert not any("nem 'evidencia_acesso'" in a for a in resultado["avisos"])


async def test_sem_aviso_de_evidencia_quando_fonte_tem_evidencia_acesso():
    fontes = [
        {
            "informante": "Fornecedor C",
            "meio_consulta": "Cotação direta",
            "data_referencia": "2026-06-03",
            "valor_unitario": 10.2,
            "evidencia_acesso": "E-mail de cotação anexado ao processo, fls. 12-15",
        }
    ]
    resultado = await gerar_memoria_pesquisa(
        "Papel A4", "Fulano", fontes, _RESULTADO_CALCULO,
        buscas_frustradas=[{"meio_consulta": "x", "motivo": "y"}],
    )
    assert not any("nem 'evidencia_acesso'" in a for a in resultado["avisos"])


async def test_markdown_mostra_evidencia_de_acesso_ou_pendencia():
    resultado = await gerar_memoria_pesquisa(
        "Papel A4",
        "Fulano",
        _FONTES,
        _RESULTADO_CALCULO,
        buscas_frustradas=[{"meio_consulta": "x", "motivo": "y"}],
        formato="markdown",
    )
    doc = resultado["documento_markdown"]
    assert "URL: https://pncp.gov.br/exemplo" in doc
    assert "[PENDÊNCIA: informar URL ou evidência de acesso a esta fonte]" in doc


# --- correcao_monetaria opcional ---

_CORRECAO_MONETARIA = {
    "indice": "IPCA (IBGE, série 433 do SGS/Banco Central)",
    "indice_chave": "ipca",
    "data_base": "2026-06",
    "quantidade_precos_corrigidos": 2,
}


async def test_sem_correcao_monetaria_nao_aparece_na_metodologia():
    memoria = await gerar_memoria_pesquisa("Papel A4", "Fulano", _FONTES, _RESULTADO_CALCULO)
    assert "correcao_monetaria" not in memoria["metodologia"]


async def test_correcao_monetaria_aparece_na_metodologia():
    memoria = await gerar_memoria_pesquisa(
        "Papel A4", "Fulano", _FONTES, _RESULTADO_CALCULO,
        correcao_monetaria=_CORRECAO_MONETARIA,
    )
    assert memoria["metodologia"]["correcao_monetaria"] == _CORRECAO_MONETARIA


async def test_correcao_monetaria_aparece_no_markdown():
    memoria = await gerar_memoria_pesquisa(
        "Papel A4", "Fulano", _FONTES, _RESULTADO_CALCULO,
        correcao_monetaria=_CORRECAO_MONETARIA, formato="markdown",
    )
    assert "Correção monetária" in memoria["documento_markdown"]
    assert "IPCA (IBGE, série 433 do SGS/Banco Central)" in memoria["documento_markdown"]
    assert "2026-06" in memoria["documento_markdown"]
