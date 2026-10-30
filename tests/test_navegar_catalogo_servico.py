"""Testes de `navegar_catalogo_servico` (navegação hierárquica do CATSER)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.navegar_catalogo_servico import navegar_catalogo_servico

_MODULO = "mcp_radardeprecos.tools.navegar_catalogo_servico.compras_client"

SECOES = [
    {"codigoSecao": 1, "nomeSecao": "SERVIÇOS DE TIC", "statusSecao": True},
    {"codigoSecao": 5, "nomeSecao": "SERVIÇO DE CONSTRUÇÃO", "statusSecao": True},
]

DIVISOES_SECAO_1 = [
    {"codigoSecao": 1, "codigoDivisao": 11, "nomeDivisao": "DESENVOLVIMENTO DE SOFTWARE", "statusDivisao": True},
]

GRUPOS_DIVISAO_11 = [
    {"codigoDivisao": 11, "codigoGrupo": 111, "nomeGrupo": "DESENVOLVIMENTO E MANUTENÇÃO", "statusGrupo": True},
]

CLASSES_TODAS = [
    {"codigoGrupo": 111, "nomeGrupo": "DESENVOLVIMENTO E MANUTENÇÃO", "codigoClasse": 1111, "nomeClasse": "DESENVOLVIMENTO"},
    {"codigoGrupo": 111, "nomeGrupo": "DESENVOLVIMENTO E MANUTENÇÃO", "codigoClasse": 1112, "nomeClasse": "MANUTENÇÃO EVOLUTIVA"},
    {"codigoGrupo": 131, "nomeGrupo": "COMPUTAÇÃO EM NUVEM", "codigoClasse": 1311, "nomeClasse": "NUVEM"},
]

SUBCLASSES_CLASSE_1111 = [
    {"codigoClasse": 1111, "nomeClasse": "DESENVOLVIMENTO", "codigoSubclasse": 11111, "nomeSubclasse": "SOB DEMANDA", "statusSubclasse": True},
]


async def test_nivel_none_equivale_a_secao():
    with patch(f"{_MODULO}.listar_secoes_servico", new_callable=AsyncMock) as mock_secoes:
        mock_secoes.return_value = SECOES
        resultado = await navegar_catalogo_servico()

    assert resultado["nivel"] == "secao"
    assert resultado["codigo_pai"] is None
    assert resultado["proximo_nivel"] == "divisao"
    assert resultado["campo_codigo_para_proximo_nivel"] == "codigoSecao"
    assert resultado["quantidade"] == 2
    assert resultado["registros"] == SECOES
    assert resultado["avisos"] == []


async def test_nivel_secao_explicito_ignora_codigo_pai():
    with patch(f"{_MODULO}.listar_secoes_servico", new_callable=AsyncMock) as mock_secoes:
        mock_secoes.return_value = SECOES
        resultado = await navegar_catalogo_servico(nivel="secao", codigo_pai=999)

    mock_secoes.assert_awaited_once_with()
    assert resultado["quantidade"] == 2


async def test_nivel_divisao_filtra_por_codigo_secao():
    with patch(f"{_MODULO}.listar_divisoes_servico", new_callable=AsyncMock) as mock_divisoes:
        mock_divisoes.return_value = DIVISOES_SECAO_1
        resultado = await navegar_catalogo_servico(nivel="divisao", codigo_pai=1)

    mock_divisoes.assert_awaited_once_with(1)
    assert resultado["nivel"] == "divisao"
    assert resultado["proximo_nivel"] == "grupo"
    assert resultado["campo_codigo_para_proximo_nivel"] == "codigoDivisao"
    assert resultado["registros"] == DIVISOES_SECAO_1


async def test_nivel_grupo_filtra_por_codigo_divisao():
    with patch(f"{_MODULO}.listar_grupos_servico", new_callable=AsyncMock) as mock_grupos:
        mock_grupos.return_value = GRUPOS_DIVISAO_11
        resultado = await navegar_catalogo_servico(nivel="grupo", codigo_pai=11)

    mock_grupos.assert_awaited_once_with(11)
    assert resultado["proximo_nivel"] == "classe"
    assert resultado["campo_codigo_para_proximo_nivel"] == "codigoGrupo"


async def test_nivel_classe_sem_codigo_pai_lista_todas():
    with patch(f"{_MODULO}.listar_classes_servico", new_callable=AsyncMock) as mock_classes:
        mock_classes.return_value = CLASSES_TODAS
        resultado = await navegar_catalogo_servico(nivel="classe")

    assert resultado["quantidade"] == 3
    assert resultado["proximo_nivel"] == "subclasse"
    assert resultado["campo_codigo_para_proximo_nivel"] == "codigoClasse"


async def test_nivel_classe_com_codigo_pai_filtra_no_cliente_por_grupo():
    with patch(f"{_MODULO}.listar_classes_servico", new_callable=AsyncMock) as mock_classes:
        mock_classes.return_value = CLASSES_TODAS
        resultado = await navegar_catalogo_servico(nivel="classe", codigo_pai=111)

    assert resultado["quantidade"] == 2
    assert all(c["codigoGrupo"] == 111 for c in resultado["registros"])


async def test_nivel_subclasse_exige_codigo_pai():
    with pytest.raises(ValueError, match="codigo_pai"):
        await navegar_catalogo_servico(nivel="subclasse")


async def test_nivel_subclasse_com_codigo_pai_delega_ao_cliente():
    with patch(f"{_MODULO}.listar_subclasses_servico", new_callable=AsyncMock) as mock_subclasses:
        mock_subclasses.return_value = SUBCLASSES_CLASSE_1111
        resultado = await navegar_catalogo_servico(nivel="subclasse", codigo_pai=1111)

    mock_subclasses.assert_awaited_once_with(1111)
    assert resultado["proximo_nivel"] is None
    assert resultado["campo_codigo_para_proximo_nivel"] is None
    assert resultado["registros"] == SUBCLASSES_CLASSE_1111


async def test_nivel_invalido_levanta_valueerror():
    with pytest.raises(ValueError, match="nivel"):
        await navegar_catalogo_servico(nivel="item")


async def test_lista_vazia_gera_aviso():
    with patch(f"{_MODULO}.listar_divisoes_servico", new_callable=AsyncMock) as mock_divisoes:
        mock_divisoes.return_value = []
        resultado = await navegar_catalogo_servico(nivel="divisao", codigo_pai=999)

    assert resultado["quantidade"] == 0
    assert len(resultado["avisos"]) == 1
    assert "999" in resultado["avisos"][0]
