"""Testes da tool montar_cesta_precos (pura — correção estrutural v0.4.2)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos.tools.montar_cesta_precos import montar_cesta_precos


async def test_extrai_precos_de_precos_praticados():
    # Formato de buscar_precos_praticados_compras (campo preco_unitario).
    registros = [
        {"preco_unitario": 100.0, "fornecedor": {"cnpj": "1"}, "descricao_item": "X"},
        {"preco_unitario": 110.0, "descricao_item": "X"},
        {"preco_unitario": 120.0, "descricao_item": "X"},
    ]
    r = await montar_cesta_precos(registros)
    assert r["precos"] == [100.0, 110.0, 120.0]
    assert r["resumo"]["com_valor"] == 3
    assert r["resumo"]["campo_valor_usado"] == ["preco_unitario"]
    # contexto preservado + valor acrescentado
    assert r["cesta"][0]["fornecedor"] == {"cnpj": "1"}
    assert r["cesta"][0]["valor"] == 100.0


async def test_registros_sem_preco_vao_para_sem_valor():
    registros = [
        {"preco_unitario": 50.0},
        {"descricao": "sem preço aqui"},        # nenhum campo de preço
        {"preco_unitario": 0},                   # não positivo
    ]
    r = await montar_cesta_precos(registros)
    assert r["precos"] == [50.0]
    assert r["resumo"]["sem_valor"] == 2
    motivos = " ".join(x["motivo"] for x in r["sem_valor"])
    assert "sem campo" in motivos and "não positivo" in motivos
    assert any("fora da cesta" in a.lower() for a in r["avisos"])


async def test_formato_brasileiro_e_variantes_de_campo():
    registros = [
        {"valor_unitario_item": "1.234,56"},     # itens de contrato + formato BR
        {"valorUnitarioEstimado": 200},           # variante crua
    ]
    r = await montar_cesta_precos(registros)
    assert r["precos"][0] == pytest.approx(1234.56)
    assert r["precos"][1] == 200.0
    assert len(r["resumo"]["campo_valor_usado"]) == 2  # avisa campos diferentes
    assert any("campos diferentes" in a for a in r["avisos"])


async def test_campo_valor_override():
    registros = [{"meu_preco": 10.0}, {"meu_preco": 20.0}, {"meu_preco": 30.0}]
    r = await montar_cesta_precos(registros, campo_valor="meu_preco")
    assert r["precos"] == [10.0, 20.0, 30.0]


async def test_nao_usa_valor_global_por_padrao():
    # valor_global NÃO é preço unitário — não deve entrar sem override.
    r = await montar_cesta_precos([{"valor_global": 99999.0}])
    assert r["precos"] == []
    assert r["resumo"]["sem_valor"] == 1


async def test_aviso_cesta_pequena():
    r = await montar_cesta_precos([{"preco_unitario": 10.0}, {"preco_unitario": 12.0}])
    assert any("abaixo do mínimo de 3" in a for a in r["avisos"])


async def test_saida_alimenta_calcular(  ):
    # A saída 'precos' entra direto em calcular_preco_referencia.
    from mcp_radardeprecos.tools.calcular_preco_referencia import (
        calcular_preco_referencia,
    )

    registros = [{"preco_unitario": v} for v in (100.0, 105.0, 110.0)]
    cesta = await montar_cesta_precos(registros)
    calc = await calcular_preco_referencia(cesta["precos"])
    assert calc["amostra_original"]["quantidade"] == 3


# --- v0.4.7: cesta sinaliza mistura de unidades de fornecimento ---

async def test_cesta_sinaliza_mistura_de_unidades():
    registros = [
        {"preco_unitario": 0.60, "unidade_fornecimento": {"nome": "UNIDADE", "capacidade": None}},
        {"preco_unitario": 21.01, "unidade_fornecimento": {"nome": "PACOTE", "capacidade": "50 UN"}},
        {"preco_unitario": 153.90, "unidade_fornecimento": {"nome": "CAIXA", "capacidade": "45 PCT"}},
    ]
    r = await montar_cesta_precos(registros)

    assert r["unidades"]["unidades_distintas"] == 3
    assert any("mistura 3 unidades" in a for a in r["avisos"])


async def test_cesta_sem_unidade_nao_gera_falso_alarme():
    registros = [{"preco_unitario": v} for v in (10.0, 11.0, 12.0)]
    r = await montar_cesta_precos(registros)

    assert r["unidades"]["unidades_distintas"] == 1
    assert not any("mistura" in a for a in r["avisos"])
