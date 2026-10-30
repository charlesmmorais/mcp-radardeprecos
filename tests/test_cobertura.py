"""Testes do contrato de cobertura.

O que estes testes protegem é uma distinção, não um formato: "a fonte não tem
o dado" e "a nossa varredura não chegou lá" precisam ser separáveis por
programa, sem interpretar texto de `avisos`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.domain.cobertura import (
    MotivoInterrupcao,
    StatusCobertura,
    aviso,
    montar,
)
from mcp_radardeprecos.tools.buscar_arp_compras import buscar_arp_compras
from mcp_radardeprecos.tools.buscar_precos_praticados_compras import (
    buscar_precos_praticados_compras,
)
from mcp_radardeprecos.tools.calcular_preco_referencia import (
    calcular_preco_referencia,
)

_CLI = "mcp_radardeprecos.tools.buscar_arp_compras.compras_client"


def test_exaustiva_autoriza_afirmar_inexistencia():
    c = montar(
        fonte="PNCP",
        status=StatusCobertura.EXAUSTIVA,
        registros_retornados=0,
        registros_examinados=120,
        total_no_universo=120,
    )
    assert c["exaustiva"] is True
    assert c["pode_afirmar_inexistencia"] is True
    assert c["percentual_cobertura"] == 100.0
    assert aviso(c) is None


def test_parcial_nao_autoriza_afirmar_inexistencia():
    """O caso do ARP: 500 de 13.335 atas."""
    c = montar(
        fonte="Compras.gov.br",
        status=StatusCobertura.PARCIAL,
        registros_retornados=3,
        registros_examinados=500,
        total_no_universo=13335,
        motivo=MotivoInterrupcao.LIMITE_DE_VARREDURA,
    )
    assert c["exaustiva"] is False
    assert c["pode_afirmar_inexistencia"] is False
    assert c["percentual_cobertura"] == 3.75
    assert c["motivo_interrupcao"] == "limite_de_varredura"
    assert "PARCIAL" in aviso(c)


def test_indeterminada_nao_e_parcial_nem_exaustiva():
    """O estado que dois booleanos não comportam.

    A fonte não informou o total: a varredura PODE ter percorrido tudo — e
    não há como saber. Tratar isso como "parcial" afirmaria uma incompletude
    não observada; como "exaustiva", afirmaria uma completude idem.
    """
    c = montar(
        fonte="PNCP",
        status=StatusCobertura.INDETERMINADA,
        registros_retornados=42,
        registros_examinados=42,
        total_no_universo=None,
        motivo=MotivoInterrupcao.TOTAL_NAO_INFORMADO,
    )
    assert c["exaustiva"] is False
    assert c["pode_afirmar_inexistencia"] is False
    assert c["percentual_cobertura"] is None
    assert "INDETERMINADA" in aviso(c)


def test_vazia_e_diferente_de_parcial_com_zero():
    """A fonte respondeu e disse que não há nada — isso é um fato.

    Uma varredura interrompida com zero resultados NÃO é o mesmo fato, e a
    diferença decide se a pesquisa de preços pode registrar 'não há'.
    """
    vazia = montar(
        fonte="PNCP", status=StatusCobertura.VAZIA, registros_retornados=0
    )
    parcial = montar(
        fonte="PNCP",
        status=StatusCobertura.PARCIAL,
        registros_retornados=0,
        motivo=MotivoInterrupcao.RATE_LIMIT,
    )
    assert vazia["pode_afirmar_inexistencia"] is True
    assert parcial["pode_afirmar_inexistencia"] is False


def test_exaustiva_nunca_carrega_motivo_de_interrupcao():
    """Não houve interrupção; um motivo aqui seria contradição no dado."""
    c = montar(
        fonte="PNCP",
        status=StatusCobertura.EXAUSTIVA,
        registros_retornados=5,
        motivo=MotivoInterrupcao.LIMITE_DE_VARREDURA,
    )
    assert c["motivo_interrupcao"] is None


def test_motivo_e_enumerado_e_serializa_como_texto():
    """Texto livre em `motivo` recriaria o problema que o módulo resolve."""
    assert MotivoInterrupcao.RATE_LIMIT.value == "rate_limit"
    assert StatusCobertura.PARCIAL.value == "parcial"
    c = montar(
        fonte="PNCP",
        status=StatusCobertura.PARCIAL,
        registros_retornados=1,
        motivo=MotivoInterrupcao.TIMEOUT,
    )
    assert isinstance(c["motivo_interrupcao"], str)


def test_erros_externos_sao_copiados_e_nao_referenciados():
    """A tool não pode mutar por acidente a lista que já entregou."""
    erros = ["429 do PNCP"]
    c = montar(
        fonte="PNCP",
        status=StatusCobertura.PARCIAL,
        registros_retornados=0,
        erros_externos=erros,
        motivo=MotivoInterrupcao.RATE_LIMIT,
    )
    erros.append("outro")
    assert c["erros_externos"] == ["429 do PNCP"]


# --- Integração: o caso real que motivou o contrato -------------------------


async def test_arp_varredura_parcial_declara_status_e_percentual():
    """O caso reportado: 500 de 13.335 atas examinadas, 3 encontradas.

    Antes, isso só aparecia em texto dentro de `avisos`. Um consumidor
    programático não tinha como saber que o resultado não era o universo.
    """
    ata = {
        "numeroAtaRegistroPreco": "00001/2026",
        "numeroControlePNCPAta": "x-1-1/2026-000001",
        "codigoUnidadeGerenciadora": "1",
    }
    with (
        patch(f"{_CLI}.consultar_arp", new_callable=AsyncMock) as m_arp,
        patch(f"{_CLI}.consultar_arp_itens", new_callable=AsyncMock) as m_itens,
    ):
        # Universo grande, listagem que nunca esgota → varredura para no teto.
        m_arp.return_value = {"resultado": [ata] * 500, "totalRegistros": 13335}
        m_itens.return_value = {"resultado": []}
        r = await buscar_arp_compras(
            data_vigencia_inicial_min="2026-08-01",
            data_vigencia_inicial_max="2026-09-30",
            codigo_item=267203,
        )
    c = r["cobertura"]
    assert c["status"] == "parcial"
    assert c["exaustiva"] is False
    assert c["pode_afirmar_inexistencia"] is False
    assert c["total_no_universo"] == 13335
    assert c["motivo_interrupcao"] == "limite_de_varredura"
    assert any("PARCIAL" in a for a in r["avisos"])


async def test_precos_praticados_pagina_unica_nao_afirma_exaustividade():
    """Paginação não é varredura, mas também não autoriza afirmar inexistência.

    Com `buscar_todas_paginas=False` a tool devolve UMA página por desenho.
    Declarar isso como exaustivo faria um usuário concluir que os 20 preços
    retornados são todos os que existem.
    """
    registro = {
        "precoUnitario": 1.5,
        "quantidade": 10,
        "niFornecedor": "11222333000144",
        "dataResultado": "2026-01-10",
        "siglaUnidadeFornecimento": "CX",
    }
    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(return_value={"resultado": [registro] * 20, "totalRegistros": 270}),
    ):
        r = await buscar_precos_praticados_compras(267203, "material", limite=20)
    c = r["cobertura"]
    assert c["status"] == "parcial"
    assert c["pode_afirmar_inexistencia"] is False
    assert c["total_no_universo"] == 270


async def test_precos_praticados_sem_resultado_e_vazia_nao_parcial():
    """A fonte respondeu e disse que não há — isso autoriza registrar 'não há'."""
    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(return_value={"resultado": [], "totalRegistros": 0}),
    ):
        r = await buscar_precos_praticados_compras(999999, "material")
    assert r["cobertura"]["status"] == "vazia"
    assert r["cobertura"]["pode_afirmar_inexistencia"] is True


# --- Homogeneidade propagada ao cálculo -------------------------------------


async def test_calculo_avisa_quando_a_serie_nao_e_homogenea():
    """Padrão escolhido: avisar e declarar, não bloquear.

    Bloqueio com sinalizador de contorno vira ritual — quem quer o número
    passa o sinalizador.
    """
    r = await calcular_preco_referencia([10.0, 12.0, 11.0], serie_homogenea=False)
    assert r["serie_homogenea"] is False
    assert any("NÃO HOMOGÊNEA" in a for a in r["avisos"])
    assert r["preco_referencia"] > 0, "o cálculo continua sendo devolvido"


async def test_calculo_avisa_quando_a_homogeneidade_nao_foi_informada():
    """O caso silencioso: quem chama sem informar está supondo.

    A tool recebe uma lista de números e não tem como saber a unidade — o
    coeficiente de variação é indício indireto e insuficiente.
    """
    r = await calcular_preco_referencia([10.0, 12.0, 11.0])
    assert r["serie_homogenea"] is None
    assert any("NÃO informada" in a for a in r["avisos"])


async def test_serie_homogenea_nao_gera_aviso_de_unidade():
    r = await calcular_preco_referencia([10.0, 12.0, 11.0], serie_homogenea=True)
    assert r["serie_homogenea"] is True
    assert not any("HOMOGÊNEA" in a.upper() and "UNIDADE" in a.upper() for a in r["avisos"])


async def test_modo_estrito_bloqueia_quando_pedido():
    """A trava rígida existe, mas por opção explícita de quem chama."""
    with pytest.raises(ValueError, match="exigir_serie_homogenea"):
        await calcular_preco_referencia(
            [10.0, 12.0], serie_homogenea=False, exigir_serie_homogenea=True
        )


async def test_modo_estrito_tambem_bloqueia_o_indeterminado():
    """`None` não é `True`: no modo estrito, não saber também impede."""
    with pytest.raises(ValueError):
        await calcular_preco_referencia([10.0, 12.0], exigir_serie_homogenea=True)
