"""Testes de `buscar_pncp_texto_booleano` (E/OU/NÃO), composição sobre buscar_pncp_texto.

Segue o padrão já usado em test_consultar_familia_contratacao_pncp.py: patch
de `mcp_radardeprecos.clients.pncp_client.buscar_texto` diretamente, já que
`buscar_pncp_texto` (a tool composta aqui) importa `pncp_client` como módulo
(`from ..clients import pncp_client`), então o patch afeta uniformemente
todas as sub-consultas desta tool.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.buscar_pncp_texto_booleano import buscar_pncp_texto_booleano

_ALVO_CLIENTE = "mcp_radardeprecos.clients.pncp_client.buscar_texto"


def _item(numero, titulo="", descricao="", data="2026-01-01T00:00:00"):
    return {
        "id": numero,
        "numero_controle_pncp": numero,
        "title": titulo,
        "description": descricao,
        "data_publicacao_pncp": data,
    }


async def test_rejeita_tipo_documento_invalido():
    with pytest.raises(ValueError, match="tipo_documento"):
        await buscar_pncp_texto_booleano(tipo_documento="invalido", termos_e=["a"])


async def test_rejeita_modalidade_invalida():
    with pytest.raises(ValueError, match="modalidade"):
        await buscar_pncp_texto_booleano(tipo_documento="edital", termos_e=["a"], modalidade=9999)


async def test_rejeita_sem_termos_e_e_sem_termos_ou():
    with pytest.raises(ValueError, match="ao menos um termo"):
        await buscar_pncp_texto_booleano(tipo_documento="edital")


async def test_rejeita_termos_e_so_com_espacos_em_branco():
    with pytest.raises(ValueError, match="ao menos um termo"):
        await buscar_pncp_texto_booleano(tipo_documento="edital", termos_e=["   ", ""])


async def test_rejeita_mais_de_8_termos_ou():
    with pytest.raises(ValueError, match="no máximo 8"):
        await buscar_pncp_texto_booleano(
            tipo_documento="edital", termos_ou=[f"t{i}" for i in range(9)]
        )


async def test_rejeita_termo_nao_conflitante_com_termos_e():
    with pytest.raises(ValueError, match="contraditório"):
        await buscar_pncp_texto_booleano(
            tipo_documento="edital", termos_e=["VMware"], termos_nao=["vmware"]
        )


async def test_rejeita_termo_nao_conflitante_com_termos_ou_tolerante_a_acento():
    with pytest.raises(ValueError, match="contraditório"):
        await buscar_pncp_texto_booleano(
            tipo_documento="edital", termos_ou=["licença"], termos_nao=["LICENCA"]
        )


async def test_busca_apenas_e_faz_uma_unica_subconsulta():
    resultado_mock = {"items": [_item("1")], "total": 1}
    mock_busca = AsyncMock(return_value=resultado_mock)
    with patch(_ALVO_CLIENTE, new=mock_busca):
        resultado = await buscar_pncp_texto_booleano(
            tipo_documento="edital", termos_e=["VMware", "subscrição"]
        )
    assert mock_busca.await_count == 1
    termo_busca_usado = mock_busca.await_args.args[0]
    assert "VMware" in termo_busca_usado and "subscrição" in termo_busca_usado
    assert resultado["quantidade_retornada"] == 1
    assert resultado["items"][0]["numero_controle_pncp"] == "1"


async def test_busca_ou_dispara_uma_subconsulta_por_termo_e_deduplica():
    respostas = [
        {"items": [_item("1"), _item("2")], "total": 2},
        {"items": [_item("2"), _item("3")], "total": 2},
    ]
    mock_busca = AsyncMock(side_effect=respostas)
    with patch(_ALVO_CLIENTE, new=mock_busca):
        resultado = await buscar_pncp_texto_booleano(
            tipo_documento="edital", termos_ou=["VVF", "vSphere"]
        )
    assert mock_busca.await_count == 2
    ids = {item["numero_controle_pncp"] for item in resultado["items"]}
    assert ids == {"1", "2", "3"}
    assert resultado["quantidade_retornada"] == 3
    assert any("OU implementado" in a for a in resultado["avisos"])


async def test_busca_e_mais_ou_combina_termos_em_cada_subconsulta():
    mock_busca = AsyncMock(return_value={"items": [], "total": 0})
    with patch(_ALVO_CLIENTE, new=mock_busca):
        await buscar_pncp_texto_booleano(
            tipo_documento="edital", termos_e=["VMware"], termos_ou=["VVF", "vSphere"]
        )
    assert mock_busca.await_count == 2
    termos_usados = {call.args[0] for call in mock_busca.await_args_list}
    assert termos_usados == {"VMware VVF", "VMware vSphere"}


async def test_termos_nao_exclui_por_substring_no_titulo_ou_descricao():
    resultado_mock = {
        "items": [
            _item("1", titulo="Contratação VMware VVF perpétua"),
            _item("2", titulo="Contratação VMware VVF assinatura"),
        ],
        "total": 2,
    }
    mock_busca = AsyncMock(return_value=resultado_mock)
    with patch(_ALVO_CLIENTE, new=mock_busca):
        resultado = await buscar_pncp_texto_booleano(
            tipo_documento="edital", termos_e=["VMware", "VVF"], termos_nao=["perpétua"]
        )
    ids = {item["numero_controle_pncp"] for item in resultado["items"]}
    assert ids == {"2"}
    assert any("removido" in a for a in resultado["avisos"])
    assert any("NÃO implementado" in a for a in resultado["avisos"])


async def test_termos_nao_tolerante_a_acentuacao_e_maiusculas():
    resultado_mock = {
        "items": [_item("1", titulo="Solução PERPETUA de licenciamento")],
        "total": 1,
    }
    mock_busca = AsyncMock(return_value=resultado_mock)
    with patch(_ALVO_CLIENTE, new=mock_busca):
        resultado = await buscar_pncp_texto_booleano(
            tipo_documento="edital", termos_e=["licenciamento"], termos_nao=["perpétua"]
        )
    assert resultado["items"] == []


async def test_limite_final_trunca_apos_uniao():
    resultado_mock = {
        "items": [_item(str(i), data=f"2026-01-{i + 1:02d}T00:00:00") for i in range(5)],
        "total": 5,
    }
    mock_busca = AsyncMock(return_value=resultado_mock)
    with patch(_ALVO_CLIENTE, new=mock_busca):
        resultado = await buscar_pncp_texto_booleano(
            tipo_documento="edital", termos_e=["x"], tamanho_pagina=3
        )
    assert resultado["quantidade_retornada"] == 3
    assert any("descartado" in a for a in resultado["avisos"])


async def test_subconsulta_com_falha_isolada_nao_derruba_a_busca():
    mock_busca = AsyncMock(side_effect=[Exception("timeout"), {"items": [_item("1")], "total": 1}])
    with patch(_ALVO_CLIENTE, new=mock_busca):
        resultado = await buscar_pncp_texto_booleano(tipo_documento="edital", termos_ou=["a", "b"])
    assert resultado["quantidade_retornada"] == 1
    assert any("falhou" in a for a in resultado["avisos"])


async def test_sem_termos_ou_nao_gera_aviso_de_ou():
    mock_busca = AsyncMock(return_value={"items": [], "total": 0})
    with patch(_ALVO_CLIENTE, new=mock_busca):
        resultado = await buscar_pncp_texto_booleano(tipo_documento="edital", termos_e=["x"])
    assert not any("OU implementado" in a for a in resultado["avisos"])
    assert not any("NÃO implementado" in a for a in resultado["avisos"])
