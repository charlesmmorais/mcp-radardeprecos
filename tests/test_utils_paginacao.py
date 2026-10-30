"""Testes de `utils.paginacao.extrair_paginacao` — o plano interno."""
from __future__ import annotations

from mcp_radardeprecos.utils.paginacao import extrair_paginacao


def test_extrai_os_4_campos_quando_todos_presentes():
    bruto = {
        "data": [],
        "totalRegistros": 120,
        "totalPaginas": 3,
        "numeroPagina": 2,
        "paginasRestantes": 1,
    }
    assert extrair_paginacao(bruto) == {
        "total_registros": 120,
        "total_paginas": 3,
        "numero_pagina": 2,
        "paginas_restantes": 1,
    }


def test_so_inclui_os_campos_que_a_fonte_realmente_devolveu():
    # Compras.gov.br típico: só totalRegistros (sem totalPaginas/numeroPagina/
    # paginasRestantes) — não deve inventar os demais.
    bruto = {"resultado": [], "totalRegistros": 40}
    assert extrair_paginacao(bruto) == {"total_registros": 40}


def test_envelope_vazio_ou_none_devolve_dict_vazio():
    assert extrair_paginacao({}) == {}
    assert extrair_paginacao(None) == {}


def test_ignora_valores_nao_inteiros():
    bruto = {
        "totalRegistros": "40",  # string, não int — API real nunca faz isso, mas defensivo
        "totalPaginas": None,
        "numeroPagina": True,  # bool é subclasse de int — deliberadamente excluído
        "paginasRestantes": 3.5,
    }
    assert extrair_paginacao(bruto) == {}


def test_nunca_inclui_chaves_ausentes():
    bruto = {"totalPaginas": 5}
    resultado = extrair_paginacao(bruto)
    assert resultado == {"total_paginas": 5}
    assert "total_registros" not in resultado
    assert "numero_pagina" not in resultado
    assert "paginas_restantes" not in resultado
