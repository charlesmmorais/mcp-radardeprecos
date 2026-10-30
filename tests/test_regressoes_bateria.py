"""Reprodução dos defeitos encontrados na bateria manual da v0.7.4 (07/09/2026).

Escritos ANTES da correção, para falharem primeiro. Um teste que nasce verde
não prova que pega o defeito — prova que o defeito não estava onde se olhou.

Dois grupos, com causas independentes:

**Ata de Registro de Preço.** Duas atas reais, encontradas pelo próprio MCP,
falharam com HTTP 404 em ``/atas/{n}/itens``. O ponto é que a tool **já tem**
o comportamento correto escrito — quando não há itens, monta ``itens: []`` e
acrescenta um aviso explicando que a lacuna é comum. Esse trecho nunca
executa, porque as três chamadas (detalhe, itens, arquivos) vão num
``asyncio.gather`` sem ``return_exceptions=True``: o 404 de uma derruba as
outras duas, que responderam bem.

**Homogeneidade de unidade.** No CATSER 26077 (SaaS) a série trazia ``UN``,
``UST`` e ``USN``, e a tool declarou ``serie_homogenea: true``. A causa
imediata é que ``_rotulo_unidade`` lê apenas ``unidade_fornecimento``, nulo em
serviços, ignorando ``unidade_medida``. A causa profunda é pior e sobrevive à
correção do fallback: quando a unidade é desconhecida, o rótulo devolvido é a
string ``"(unidade não informada)"``, que **conta como uma unidade**. Uma
série em que ninguém informou unidade sai como homogênea — ausência de
informação apresentada como uniformidade, que é exatamente o inverso do que
esta trava metodológica existe para dizer.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.clients.base import UpstreamError
from mcp_radardeprecos.tools.buscar_precos_praticados_compras import resumir_unidades
from mcp_radardeprecos.tools.consultar_ata_registro_preco import (
    consultar_ata_registro_preco,
)

# Ata real da bateria manual, que devolveu 404 nos itens.
ATA_REAL = "13864377000130-1-001182/2026-000001"
_ATA = "mcp_radardeprecos.tools.consultar_ata_registro_preco.pncp_client"

_ATA_OK = {
    "numeroControlePNCPAta": ATA_REAL,
    "cancelado": False,
    "vigenciaFim": "2027-01-31",
}


# --- Ata -------------------------------------------------------------------


async def test_404_nos_itens_nao_derruba_o_detalhe_da_ata():
    """O caso reproduzido duas vezes na bateria manual.

    O detalhe da ata respondeu bem; só os itens deram 404. Perder o detalhe
    inteiro por causa disso é desperdiçar dado que a fonte entregou.
    """
    with (
        patch(f"{_ATA}.consultar_ata", new_callable=AsyncMock) as m_ata,
        patch(f"{_ATA}.consultar_itens_ata", new_callable=AsyncMock) as m_itens,
    ):
        m_ata.return_value = _ATA_OK
        m_itens.side_effect = UpstreamError("pncp", 404, "Not Found")
        r = await consultar_ata_registro_preco(numero_controle_pncp_ata=ATA_REAL)

    assert r["itens"] == []
    assert r["numero_controle_pncp_ata"] == ATA_REAL


async def test_404_nos_itens_vira_aviso_e_nao_silencio():
    """Lista vazia sem explicação seria ler "esta ata não tem itens".

    A diferença entre "a ata não tem itens" e "o PNCP não nos deu os itens"
    é a diferença entre um fato e uma lacuna.
    """
    with (
        patch(f"{_ATA}.consultar_ata", new_callable=AsyncMock) as m_ata,
        patch(f"{_ATA}.consultar_itens_ata", new_callable=AsyncMock) as m_itens,
    ):
        m_ata.return_value = _ATA_OK
        m_itens.side_effect = UpstreamError("pncp", 404, "Not Found")
        r = await consultar_ata_registro_preco(numero_controle_pncp_ata=ATA_REAL)

    assert r["avisos"], "lacuna de itens tem de ser declarada"
    assert any("404" in a or "não retornou itens" in a for a in r["avisos"])


async def test_404_no_DETALHE_da_ata_continua_sendo_erro():
    """A contrapartida: nem todo 404 é lacuna.

    Sem os metadados, não há ata. Devolver um envelope vazio aqui seria
    inventar uma ata que a fonte disse não existir.
    """
    with (
        patch(f"{_ATA}.consultar_ata", new_callable=AsyncMock) as m_ata,
        patch(f"{_ATA}.consultar_itens_ata", new_callable=AsyncMock) as m_itens,
    ):
        m_ata.side_effect = UpstreamError("pncp", 404, "Not Found")
        m_itens.return_value = []
        with pytest.raises(UpstreamError):
            await consultar_ata_registro_preco(numero_controle_pncp_ata=ATA_REAL)


async def test_detalhe_da_ata_sem_conteudo_nao_estoura_attributeerror():
    """Quinto ponto do bug de 204 da v0.5.4, que a auditoria perdeu.

    A varredura estática procurava `x = await client.fn()` e não casou com o
    desempacotamento de `asyncio.gather`.
    """
    with (
        patch(f"{_ATA}.consultar_ata", new_callable=AsyncMock) as m_ata,
        patch(f"{_ATA}.consultar_itens_ata", new_callable=AsyncMock) as m_itens,
    ):
        m_ata.return_value = None  # 204 / corpo vazio
        m_itens.return_value = []
        with pytest.raises(UpstreamError):
            await consultar_ata_registro_preco(numero_controle_pncp_ata=ATA_REAL)


# --- Homogeneidade de unidade ----------------------------------------------


def test_servico_usa_unidade_medida_quando_nao_ha_unidade_de_fornecimento():
    """CATSER 26077 (SaaS): UN, UST e USN reportados como uma unidade só.

    Em serviço, `unidade_fornecimento` vem nulo — a unidade real está em
    `unidade_medida`.
    """
    serie = [
        {"unidade_fornecimento": None, "unidade_medida": {"sigla": "UN"}},
        {"unidade_fornecimento": None, "unidade_medida": {"sigla": "UST"}},
        {"unidade_fornecimento": None, "unidade_medida": {"sigla": "USN"}},
    ]
    r = resumir_unidades(serie)
    assert r["unidades_distintas"] == 3
    assert r["serie_homogenea"] is False


def test_serie_sem_unidade_nenhuma_nao_pode_ser_declarada_homogenea():
    """O defeito profundo, que sobrevive à correção do fallback.

    Todos os registros sem unidade produzem o mesmo rótulo
    "(unidade não informada)", que contado como unidade dá
    `unidades_distintas: 1` e `serie_homogenea: true`. Não se sabe nada
    sobre as unidades e a tool afirma que são todas iguais.
    """
    serie = [
        {"unidade_fornecimento": None, "unidade_medida": None},
        {"unidade_fornecimento": None, "unidade_medida": None},
    ]
    r = resumir_unidades(serie)
    assert r["serie_homogenea"] is not True, (
        "sem informação de unidade não se pode afirmar homogeneidade"
    )


def test_unidade_conhecida_e_de_verdade_homogenea_continua_homogenea():
    """Guarda contra o exagero oposto: não transformar tudo em não-homogêneo."""
    serie = [
        {"unidade_fornecimento": {"nome": "COMPRIMIDO"}},
        {"unidade_fornecimento": {"nome": "COMPRIMIDO"}},
    ]
    r = resumir_unidades(serie)
    assert r["unidades_distintas"] == 1
    assert r["serie_homogenea"] is True


def test_mistura_de_conhecida_com_desconhecida_nao_e_homogenea():
    serie = [
        {"unidade_fornecimento": {"nome": "COMPRIMIDO"}},
        {"unidade_fornecimento": None, "unidade_medida": None},
    ]
    r = resumir_unidades(serie)
    assert r["serie_homogenea"] is not True


async def test_ausencia_de_itens_e_legivel_por_programa():
    """Item 5 da solicitação da v0.7.6.

    Obrigar o consumidor a procurar substring em `avisos` para saber se a ata
    tem itens é o mesmo defeito que o contrato de cobertura resolve.
    """
    with (
        patch(f"{_ATA}.consultar_ata", new_callable=AsyncMock) as m_ata,
        patch(f"{_ATA}.consultar_itens_ata", new_callable=AsyncMock) as m_itens,
    ):
        m_ata.return_value = _ATA_OK
        m_itens.side_effect = UpstreamError("pncp", 404, "Not Found")
        r = await consultar_ata_registro_preco(numero_controle_pncp_ata=ATA_REAL)
    assert r["itens_disponiveis"] is False
    assert r["motivo_itens_indisponiveis"] == "PNCP_HTTP_404"


async def test_ata_com_itens_marca_disponivel():
    with (
        patch(f"{_ATA}.consultar_ata", new_callable=AsyncMock) as m_ata,
        patch(f"{_ATA}.consultar_itens_ata", new_callable=AsyncMock) as m_itens,
    ):
        m_ata.return_value = _ATA_OK
        m_itens.return_value = [{"numeroItem": 1, "precoUnitarioRegistrado": 1.5}]
        r = await consultar_ata_registro_preco(numero_controle_pncp_ata=ATA_REAL)
    assert r["itens_disponiveis"] is True
    assert r["motivo_itens_indisponiveis"] is None
