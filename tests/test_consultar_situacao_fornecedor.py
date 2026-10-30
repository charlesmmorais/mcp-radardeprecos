"""Testes da tool consultar_situacao_fornecedor (cliente compras_client mockado)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mcp_radardeprecos.tools import consultar_situacao_fornecedor as tool_mod

CNPJ_LIMPO = "05340845000140"
CPF_LIMPO = "12345678901"

REGISTRO_ATIVO = {
    "ativo": True,
    "cnpj": CNPJ_LIMPO,
    "cpf": None,
    "habilitadoLicitar": True,
    "codigoCnae": 6201501,
    "nomeCnae": "DESENVOLVIMENTO DE PROGRAMAS DE COMPUTADOR SOB ENCOMENDA",
    "nomeMunicipio": "BRASÍLIA",
    "naturezaJuridicaId": 2062,
    "naturezaJuridicaNome": "SOCIEDADE EMPRESÁRIA LIMITADA",
    "porteEmpresaId": 5,
    "porteEmpresaNome": "DEMAIS",
    "nomeRazaoSocialFornecedor": "ZELLO TECNOLOGIA DA INFORMACAO LTDA",
    "ufSigla": "DF",
}


async def test_rejeita_quando_nenhum_documento_informado():
    with pytest.raises(ValueError):
        await tool_mod.consultar_situacao_fornecedor()


async def test_rejeita_quando_os_dois_documentos_informados():
    with pytest.raises(ValueError):
        await tool_mod.consultar_situacao_fornecedor(cnpj="123", cpf="456")


async def test_rejeita_cnpj_com_tamanho_invalido():
    with pytest.raises(ValueError):
        await tool_mod.consultar_situacao_fornecedor(cnpj="123")


async def test_rejeita_cpf_com_tamanho_invalido():
    with pytest.raises(ValueError):
        await tool_mod.consultar_situacao_fornecedor(cpf="123")


async def test_encontrado_ativo_na_primeira_tentativa(monkeypatch):
    mock_consultar = AsyncMock(return_value={"resultado": [REGISTRO_ATIVO]})
    monkeypatch.setattr(tool_mod.compras_client, "consultar_fornecedor", mock_consultar)

    resultado = await tool_mod.consultar_situacao_fornecedor(cnpj="05.340.845/0001-40")

    assert resultado["cnpj"] == CNPJ_LIMPO
    assert resultado["situacao"] == "ATIVO"
    assert resultado["habilitado_a_licitar"] is True
    assert resultado["razao_social"] == "ZELLO TECNOLOGIA DA INFORMACAO LTDA"
    assert resultado["cnae"] == {
        "codigo": 6201501,
        "descricao": "DESENVOLVIMENTO DE PROGRAMAS DE COMPUTADOR SOB ENCOMENDA",
    }
    assert "aviso" in resultado
    mock_consultar.assert_awaited_once_with(ativo=True, cnpj=CNPJ_LIMPO)


async def test_cai_para_inativo_quando_ativo_nao_encontra(monkeypatch):
    registro_inativo = {**REGISTRO_ATIVO, "ativo": False, "habilitadoLicitar": False}

    async def fake_consultar(*, ativo, **kwargs):
        if ativo:
            return {"resultado": []}
        return {"resultado": [registro_inativo]}

    mock_consultar = AsyncMock(side_effect=fake_consultar)
    monkeypatch.setattr(tool_mod.compras_client, "consultar_fornecedor", mock_consultar)

    resultado = await tool_mod.consultar_situacao_fornecedor(cnpj=CNPJ_LIMPO)

    assert resultado["situacao"] == "INATIVO"
    assert resultado["habilitado_a_licitar"] is False
    assert mock_consultar.await_count == 2


async def test_nao_encontrado_quando_nenhum_provedor_tem_registro(monkeypatch):
    mock_consultar = AsyncMock(return_value={"resultado": []})
    monkeypatch.setattr(tool_mod.compras_client, "consultar_fornecedor", mock_consultar)

    resultado = await tool_mod.consultar_situacao_fornecedor(cnpj=CNPJ_LIMPO)

    assert resultado["situacao"] == "NAO_ENCONTRADO"
    assert resultado["habilitado_a_licitar"] is None
    assert resultado["razao_social"] is None
    assert mock_consultar.await_count == 2


async def test_aceita_cpf(monkeypatch):
    mock_consultar = AsyncMock(return_value={"resultado": [REGISTRO_ATIVO]})
    monkeypatch.setattr(tool_mod.compras_client, "consultar_fornecedor", mock_consultar)

    resultado = await tool_mod.consultar_situacao_fornecedor(cpf="123.456.789-01")

    assert resultado["cpf"] == CPF_LIMPO
    mock_consultar.assert_awaited_once_with(ativo=True, cpf=CPF_LIMPO)


async def test_aviso_de_escopo_sempre_presente(monkeypatch):
    mock_consultar = AsyncMock(return_value={"resultado": []})
    monkeypatch.setattr(tool_mod.compras_client, "consultar_fornecedor", mock_consultar)

    resultado = await tool_mod.consultar_situacao_fornecedor(cnpj=CNPJ_LIMPO)

    assert "sanç" in resultado["aviso"].lower() or "sanc" in resultado["aviso"].lower()
