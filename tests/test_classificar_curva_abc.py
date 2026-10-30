"""Testes de `classificar_curva_abc` (tool pura, sem chamada de rede)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos.tools.classificar_curva_abc import classificar_curva_abc


async def test_rejeita_lista_vazia():
    with pytest.raises(ValueError):
        await classificar_curva_abc([])


async def test_rejeita_limites_invalidos():
    itens = [{"valor": 10.0}, {"valor": 20.0}]
    with pytest.raises(ValueError):
        await classificar_curva_abc(itens, limite_classe_a=95.0, limite_classe_b=80.0)
    with pytest.raises(ValueError):
        await classificar_curva_abc(itens, limite_classe_a=0)
    with pytest.raises(ValueError):
        await classificar_curva_abc(itens, limite_classe_b=101)


async def test_rejeita_item_com_valor_invalido():
    with pytest.raises(ValueError, match="item 1"):
        await classificar_curva_abc([{"valor": 10.0}, {"valor": -5.0}, {"valor": 3.0}])
    with pytest.raises(ValueError):
        await classificar_curva_abc([{"valor": 10.0}, {}, {"valor": 3.0}])


async def test_classificacao_basica_pareto():
    # A classificação usa o percentual acumulado APÓS incluir o próprio item.
    # Um item que já ultrapassa 80% sozinho (1000/1100 = ~90.9%) cai em
    # Classe B (pois ainda está <= 95%); os itens seguintes, que empurram o
    # acumulado para além de 95%, caem em Classe C.
    itens = [
        {"descricao": "item caro", "valor": 1000.0},
        {"descricao": "item medio", "valor": 60.0},
        {"descricao": "item barato", "valor": 40.0},
    ]
    resultado = await classificar_curva_abc(itens)

    assert resultado["valor_total"] == pytest.approx(1100.0)
    classes = [it["classe"] for it in resultado["itens_classificados"]]
    assert classes == ["B", "C", "C"]
    # O item mais caro vem primeiro (ordenado decrescente).
    assert resultado["itens_classificados"][0]["descricao"] == "item caro"
    assert resultado["itens_classificados"][0]["percentual_acumulado"] == pytest.approx(
        1000 / 1100 * 100, abs=0.01
    )


async def test_resumo_por_classe_soma_corretamente():
    itens = [{"valor": v} for v in (500.0, 300.0, 100.0, 50.0, 30.0, 20.0)]
    resultado = await classificar_curva_abc(itens)

    total_itens = sum(r["quantidade_itens"] for r in resultado["resumo_por_classe"].values())
    assert total_itens == len(itens)
    total_valor = sum(r["valor_total_classe"] for r in resultado["resumo_por_classe"].values())
    assert total_valor == pytest.approx(resultado["valor_total"])


async def test_aviso_poucos_itens():
    resultado = await classificar_curva_abc([{"valor": 10.0}, {"valor": 5.0}])
    assert any("a Curva ABC pressupõe" in a for a in resultado["avisos"])


async def test_sem_aviso_quando_ha_itens_suficientes():
    itens = [{"valor": v} for v in (100.0, 80.0, 60.0, 40.0, 20.0)]
    resultado = await classificar_curva_abc(itens)
    assert resultado["avisos"] == []


async def test_preserva_chaves_extras_do_item():
    itens = [
        {"valor": 100.0, "codigo_catmat": "123", "descricao": "cadeira"},
        {"valor": 50.0, "codigo_catmat": "456", "descricao": "mesa"},
        {"valor": 25.0, "codigo_catmat": "789", "descricao": "armário"},
    ]
    resultado = await classificar_curva_abc(itens)
    primeiro = resultado["itens_classificados"][0]
    assert primeiro["codigo_catmat"] == "123"
    assert primeiro["descricao"] == "cadeira"


async def test_limites_customizados():
    itens = [{"valor": v} for v in (70.0, 20.0, 10.0)]
    resultado = await classificar_curva_abc(itens, limite_classe_a=70.0, limite_classe_b=90.0)
    classes = [it["classe"] for it in resultado["itens_classificados"]]
    # 70/100 = 70% (<=70 -> A), (70+20)/100 = 90% (<=90 -> B), 100% (-> C)
    assert classes == ["A", "B", "C"]
