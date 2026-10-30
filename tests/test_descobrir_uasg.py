"""Testes da tool descobrir_uasg (cliente compras_client mockado)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mcp_radardeprecos.tools import descobrir_uasg as tool_mod

UASGS = [
    {
        "codigoUasg": "030204",
        "nomeUasg": "TCU - SECRETARIA DE INFORMATICA",
        "siglaUf": "DF",
        "nomeMunicipioIbge": "BRASÍLIA",
        "codigoOrgao": 3000,
        "cnpjCpfOrgao": "00414607000118",
        "usoSisg": False,
    },
    {
        "codigoUasg": "030001",
        "nomeUasg": "TCU-TRIBUNAL DE CONTAS DA UNIAO/DF",
        "siglaUf": "DF",
        "nomeMunicipioIbge": "BRASÍLIA",
        "codigoOrgao": 3000,
        "cnpjCpfOrgao": "00414607000118",
        "usoSisg": True,
    },
]

ORGAOS = [
    {
        "codigoOrgao": 3000,
        "nomeOrgao": "TRIBUNAL DE CONTAS DA UNIAO",
        "nomeMnemonicoOrgao": "TCU",
        "cnpjCpfOrgao": "00414607000118",
        "poder": "Judiciário",
        "esfera": "Federal",
        "nomeOrgaoSuperior": None,
    },
]


async def test_rejeita_tipo_invalido():
    with pytest.raises(ValueError):
        await tool_mod.descobrir_uasg("tribunal", tipo="invalido")


async def test_rejeita_termo_busca_vazio():
    with pytest.raises(ValueError):
        await tool_mod.descobrir_uasg("   ")


async def test_rejeita_uf_com_tipo_orgao():
    with pytest.raises(ValueError):
        await tool_mod.descobrir_uasg("tribunal", tipo="orgao", uf="DF")


async def test_descobrir_uasg_encontra_por_nome(monkeypatch):
    mock_listar = AsyncMock(return_value=UASGS)
    monkeypatch.setattr(tool_mod.compras_client, "listar_uasgs_ativas", mock_listar)

    resultado = await tool_mod.descobrir_uasg("tribunal de contas", tipo="uasg", uf="DF")

    mock_listar.assert_awaited_once_with(sigla_uf="DF")
    assert resultado["tipo"] == "uasg"
    assert resultado["uf"] == "DF"
    assert resultado["total_correspondencias"] == 1
    assert resultado["resultados"][0]["codigo_uasg"] == "030001"
    assert "aviso" not in resultado


async def test_descobrir_uasg_busca_acento_case_insensivel(monkeypatch):
    mock_listar = AsyncMock(return_value=UASGS)
    monkeypatch.setattr(tool_mod.compras_client, "listar_uasgs_ativas", mock_listar)

    resultado = await tool_mod.descobrir_uasg("SECRETARIA DE INFORMATICA")

    assert resultado["total_correspondencias"] == 1
    assert resultado["resultados"][0]["codigo_uasg"] == "030204"


async def test_descobrir_uasg_aviso_quando_nao_encontra(monkeypatch):
    mock_listar = AsyncMock(return_value=UASGS)
    monkeypatch.setattr(tool_mod.compras_client, "listar_uasgs_ativas", mock_listar)

    resultado = await tool_mod.descobrir_uasg("hospital inexistente xyz")

    assert resultado["total_correspondencias"] == 0
    assert "aviso" in resultado


async def test_descobrir_orgao_encontra_por_nome_ou_mnemonico(monkeypatch):
    mock_listar = AsyncMock(return_value=ORGAOS)
    monkeypatch.setattr(tool_mod.compras_client, "listar_orgaos_ativos", mock_listar)

    resultado = await tool_mod.descobrir_uasg("TCU", tipo="orgao")

    mock_listar.assert_awaited_once_with()
    assert resultado["tipo"] == "orgao"
    assert resultado["uf"] is None
    assert resultado["total_correspondencias"] == 1
    assert resultado["resultados"][0]["codigo_orgao"] == 3000
    assert resultado["resultados"][0]["poder"] == "Judiciário"


async def test_descobrir_orgao_aviso_quando_nao_encontra(monkeypatch):
    mock_listar = AsyncMock(return_value=ORGAOS)
    monkeypatch.setattr(tool_mod.compras_client, "listar_orgaos_ativos", mock_listar)

    resultado = await tool_mod.descobrir_uasg("ministerio inexistente xyz", tipo="orgao")

    assert resultado["total_correspondencias"] == 0
    assert "aviso" in resultado


async def test_limite_e_respeitado(monkeypatch):
    muitas_uasgs = [
        {**UASGS[0], "codigoUasg": str(i), "nomeUasg": f"TRIBUNAL {i}"} for i in range(20)
    ]
    mock_listar = AsyncMock(return_value=muitas_uasgs)
    monkeypatch.setattr(tool_mod.compras_client, "listar_uasgs_ativas", mock_listar)

    resultado = await tool_mod.descobrir_uasg("tribunal", limite=5)

    assert resultado["total_correspondencias"] == 20
    assert len(resultado["resultados"]) == 5
