"""Testes de utils/texto_busca.py (normalização para busca "contém" tolerante)."""
from __future__ import annotations

from mcp_radardeprecos.utils.texto_busca import normalizar_para_busca


def test_normaliza_maiusculas_e_acentos():
    assert normalizar_para_busca("notebook") == "NOTEBOOK"
    assert normalizar_para_busca("Notébook") == "NOTEBOOK"
    assert normalizar_para_busca("AUTOMÓVEL") == "AUTOMOVEL"
    assert normalizar_para_busca("máquina de lavar") == "MAQUINA DE LAVAR"


def test_normaliza_string_vazia():
    assert normalizar_para_busca("") == ""


def test_normaliza_remove_espacos_nas_pontas():
    assert normalizar_para_busca("  caneta  ") == "CANETA"


# --- classificar_correspondencia ---------------------------------

from mcp_radardeprecos.utils.texto_busca import (  # noqa: E402
    classificar_correspondencia,
)


def test_classificador_caso_real_tic():
    # Achado de uso real: "TIC" casava com turísTICo/estatísTICo/plásTICo.
    assert classificar_correspondencia("TIC", normalizar_para_busca("Guia turístico")) == "parcial"
    assert classificar_correspondencia("TIC", normalizar_para_busca("Dados estatísticos")) == "parcial"
    assert classificar_correspondencia("TIC", normalizar_para_busca("Produtos plásticos")) == "parcial"
    assert (
        classificar_correspondencia(
            "TIC", normalizar_para_busca("Tecnologia da Informação e Comunicação (TIC)")
        )
        == "palavra_inteira"
    )
    assert classificar_correspondencia("TIC", normalizar_para_busca("TIC")) == "exata"


def test_classificador_multipalavra_e_ausencia():
    assert (
        classificar_correspondencia(
            normalizar_para_busca("limpeza predial"),
            normalizar_para_busca("SERVIÇO DE LIMPEZA PREDIAL"),
        )
        == "palavra_inteira"
    )
    assert (
        classificar_correspondencia(
            normalizar_para_busca("limpeza"), normalizar_para_busca("MANUTENÇÃO ELÉTRICA")
        )
        is None
    )
