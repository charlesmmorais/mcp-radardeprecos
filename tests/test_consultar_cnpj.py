"""Testes da tool consultar_cnpj (cliente cnpj_client mockado)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mcp_radardeprecos.tools import consultar_cnpj as consultar_cnpj_mod

CNPJ_LIMPO = "30051023000196"

DADOS_COMPLETOS = {
    "cnpj": CNPJ_LIMPO,
    "razao_social": "EMPRESA TESTE LTDA",
    "nome_fantasia": "TESTE",
    "descricao_situacao_cadastral": "ATIVA",
    "situacao_cadastral": 2,
    "data_situacao_cadastral": "1998-07-28",
    "descricao_motivo_situacao_cadastral": "SEM MOTIVO",
    "natureza_juridica": "Sociedade Empresária Limitada",
    "porte": "DEMAIS",
    "capital_social": 100000,
    "data_inicio_atividade": "2017-05-10",
    "cnae_fiscal": 6201500,
    "cnae_fiscal_descricao": "Desenvolvimento de programas de computador",
    "cnaes_secundarios": [],
    "logradouro": "RUA TESTE",
    "numero": "123",
    "complemento": "",
    "bairro": "CENTRO",
    "municipio": "RIO DE JANEIRO",
    "uf": "RJ",
    "cep": "20000000",
    "ddd_telefone_1": "2100000000",
    "email": "contato@empresateste.com.br",
    "opcao_pelo_simples": True,
    "opcao_pelo_mei": False,
    "qsa": [
        {
            "nome_socio": "FULANO DE TAL",
            "qualificacao_socio": "Sócio-Administrador",
            "data_entrada_sociedade": "2017-05-10",
            "cnpj_cpf_do_socio": "***123456**",
        }
    ],
    "_provider": "brasilapi",
}

DADOS_SEM_SOCIOS = {**DADOS_COMPLETOS, "qsa": []}


async def test_consultar_cnpj_rejeita_cnpj_com_tamanho_invalido():
    with pytest.raises(ValueError):
        await consultar_cnpj_mod.consultar_cnpj("123")


async def test_consultar_cnpj_rejeita_cnpj_nao_numerico():
    with pytest.raises(ValueError):
        await consultar_cnpj_mod.consultar_cnpj("abcdefghijklmn")


async def test_consultar_cnpj_aceita_cnpj_formatado_e_limpa(monkeypatch):
    mock_cliente = AsyncMock(return_value=DADOS_COMPLETOS)
    monkeypatch.setattr(consultar_cnpj_mod.cnpj_client, "consultar_cnpj", mock_cliente)

    resultado = await consultar_cnpj_mod.consultar_cnpj("30.051.023/0001-96")

    mock_cliente.assert_awaited_once_with(CNPJ_LIMPO)
    assert resultado["cnpj"] == CNPJ_LIMPO


async def test_consultar_cnpj_normaliza_campos_principais(monkeypatch):
    mock_cliente = AsyncMock(return_value=DADOS_COMPLETOS)
    monkeypatch.setattr(consultar_cnpj_mod.cnpj_client, "consultar_cnpj", mock_cliente)

    resultado = await consultar_cnpj_mod.consultar_cnpj(CNPJ_LIMPO)

    assert resultado["razao_social"] == "EMPRESA TESTE LTDA"
    assert resultado["nome_fantasia"] == "TESTE"
    assert resultado["situacao_cadastral"] == "ATIVA"
    assert resultado["codigo_situacao_cadastral"] == 2
    assert resultado["cnae_principal"] == {
        "codigo": 6201500,
        "descricao": "Desenvolvimento de programas de computador",
    }
    assert resultado["endereco"]["municipio"] == "RIO DE JANEIRO"
    assert resultado["endereco"]["uf"] == "RJ"
    assert resultado["email"] == "contato@empresateste.com.br"
    assert resultado["fonte"] == "brasilapi"


async def test_consultar_cnpj_normaliza_socios(monkeypatch):
    mock_cliente = AsyncMock(return_value=DADOS_COMPLETOS)
    monkeypatch.setattr(consultar_cnpj_mod.cnpj_client, "consultar_cnpj", mock_cliente)

    resultado = await consultar_cnpj_mod.consultar_cnpj(CNPJ_LIMPO)

    assert resultado["socios"] == [
        {
            "nome": "FULANO DE TAL",
            "qualificacao": "Sócio-Administrador",
            "data_entrada_sociedade": "2017-05-10",
            "cnpj_cpf": "***123456**",
        }
    ]
    assert "aviso" not in resultado


async def test_consultar_cnpj_avisa_quando_qsa_vazio(monkeypatch):
    mock_cliente = AsyncMock(return_value=DADOS_SEM_SOCIOS)
    monkeypatch.setattr(consultar_cnpj_mod.cnpj_client, "consultar_cnpj", mock_cliente)

    resultado = await consultar_cnpj_mod.consultar_cnpj(CNPJ_LIMPO)

    assert resultado["socios"] == []
    assert "aviso" in resultado
    assert "sócio" in resultado["aviso"].lower()
