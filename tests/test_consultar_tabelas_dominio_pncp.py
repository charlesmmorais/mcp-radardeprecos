"""Testes de `consultar_tabelas_dominio_pncp` (tool pura — sem chamada de API)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos.domain.dominios import MODALIDADES_PNCP, TABELAS_DOMINIO_PNCP
from mcp_radardeprecos.tools.consultar_tabelas_dominio_pncp import (
    consultar_tabelas_dominio_pncp,
)


async def test_rejeita_tabela_invalida():
    with pytest.raises(ValueError, match="tabela"):
        await consultar_tabelas_dominio_pncp(tabela="essa_tabela_nao_existe")


async def test_sem_argumento_devolve_todas_as_tabelas():
    resultado = await consultar_tabelas_dominio_pncp()
    assert set(resultado["tabelas"].keys()) == set(TABELAS_DOMINIO_PNCP.keys())
    assert len(resultado["tabelas"]) == 15


async def test_tabela_especifica_devolve_so_essa_tabela():
    resultado = await consultar_tabelas_dominio_pncp(tabela="criterio_julgamento")
    assert list(resultado["tabelas"].keys()) == ["criterio_julgamento"]
    codigos = {item["codigo"] for item in resultado["tabelas"]["criterio_julgamento"]}
    assert codigos == {1, 2, 4, 5, 6, 7, 8, 9}


async def test_amparo_legal_tem_80_codigos():
    resultado = await consultar_tabelas_dominio_pncp(tabela="amparo_legal")
    amparo_legal = resultado["tabelas"]["amparo_legal"]
    assert len(amparo_legal) == 80
    codigos = sorted(item["codigo"] for item in amparo_legal)
    assert codigos == list(range(1, 81))


async def test_modalidade_contratacao_consistente_com_modalidades_pncp():
    """Evita drift entre TABELAS_DOMINIO_PNCP e a fonte única MODALIDADES_PNCP
    já usada por buscar_pncp_texto/buscar_contratacoes_pncp."""
    resultado = await consultar_tabelas_dominio_pncp(tabela="modalidade_contratacao")
    tabela = resultado["tabelas"]["modalidade_contratacao"]
    assert len(tabela) == len(MODALIDADES_PNCP)
    for item in tabela:
        assert MODALIDADES_PNCP[item["codigo"]] == item["nome"]


async def test_todas_as_entradas_tem_codigo_e_nome():
    resultado = await consultar_tabelas_dominio_pncp()
    for nome_tabela, entradas in resultado["tabelas"].items():
        assert len(entradas) > 0, nome_tabela
        for entrada in entradas:
            assert "codigo" in entrada, (nome_tabela, entrada)
            assert "nome" in entrada, (nome_tabela, entrada)
