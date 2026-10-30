"""Testes do parser de capacidade — inclusive dos casos que ele RECUSA."""
from __future__ import annotations

from decimal import Decimal

import pytest

from mcp_radardeprecos.domain.capacidade import interpretar_capacidade


@pytest.mark.parametrize(
    ("texto", "fator", "base"),
    [
        ("50 UN", Decimal(50), "unidade"),
        ("45 PACOTES", Decimal(45), "pacote"),
        ("4000 FOLHAS", Decimal(4000), "folha"),
        ("100 UNIDADES", Decimal(100), "unidade"),
        ("caixa com 100 unidades", Decimal(100), "unidade"),
        ("1,5 L", Decimal("1.5"), "litro"),
        ("FOLHAS 4000", Decimal(4000), "folha"),
    ],
)
def test_interpreta_capacidades_claras(texto, fator, base):
    c = interpretar_capacidade(texto)
    assert c is not None
    assert c.fator == fator
    assert c.base == base
    assert c.texto_original == texto


@pytest.mark.parametrize(
    "texto",
    [
        None,
        "",
        "   ",
        "UNIDADE",          # sem número: nada a converter
        "GLOBAL",
        "CAIXA 10 X 20",    # ambíguo: produto ou dimensões?
        "DE 50 A 100",      # faixa
        "50 XPTO",          # unidade desconhecida
        "0 UN",             # fator não positivo
    ],
)
def test_recusa_o_que_nao_e_seguro(texto):
    """Devolver None é resultado legítimo: significa 'não converta'."""
    assert interpretar_capacidade(texto) is None


def test_acento_e_caixa_nao_atrapalham():
    c = interpretar_capacidade("12 Cápsulas")
    assert c is not None and c.fator == Decimal(12) and c.base == "capsula"
