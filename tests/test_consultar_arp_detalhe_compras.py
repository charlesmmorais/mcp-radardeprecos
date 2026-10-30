"""Testes de `consultar_arp_detalhe_compras` — saldo/adesões/empenho de item de ARP (Compras.gov.br)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.consultar_arp_detalhe_compras import (
    consultar_arp_detalhe_compras,
)

_CLIENTE = "mcp_radardeprecos.clients.compras_client"

_UNIDADE_BRUTA = {
    "quantidadeRegistrada": 300,
    "saldoAdesoes": 600,
    "saldoRemanejamentoEmpenho": 150,
    "qtdLimiteAdesao": 600,
    "aceitaAdesao": True,
    "fornecedor": "09174668000120 - FORNECEDOR TESTE LTDA",
}

_EMPENHO_BRUTO = {
    "numeroItem": "00009",
    "unidade": "155021 - HOSPITAL DAS CLINICAS DA UFMG",
    "tipo": "GERENCIADORA",
    "quantidadeRegistrada": 300,
    "quantidadeEmpenhada": 150,
    "saldoEmpenho": 150,
}


async def _rejeita(campo, **kwargs):
    with pytest.raises(ValueError, match=campo):
        await consultar_arp_detalhe_compras(**kwargs)


async def test_rejeita_numero_ata_vazio():
    await _rejeita("numero_ata", numero_ata="", unidade_gerenciadora="155021", numero_item="00009")


async def test_rejeita_unidade_gerenciadora_vazia():
    await _rejeita(
        "unidade_gerenciadora", numero_ata="00002/2025", unidade_gerenciadora="  ", numero_item="00009"
    )


async def test_rejeita_numero_item_vazio():
    await _rejeita(
        "numero_item", numero_ata="00002/2025", unidade_gerenciadora="155021", numero_item=""
    )


async def test_consolida_saldo_adesoes_empenho():
    mock_unidades = AsyncMock(return_value={"resultado": [_UNIDADE_BRUTA]})
    mock_adesoes = AsyncMock(return_value={"resultado": []})
    mock_empenhos = AsyncMock(return_value={"resultado": [_EMPENHO_BRUTO]})
    with patch(f"{_CLIENTE}.consultar_arp_unidades_item", new=mock_unidades), patch(
        f"{_CLIENTE}.consultar_arp_adesoes_item", new=mock_adesoes
    ), patch(f"{_CLIENTE}.consultar_arp_empenhos_item", new=mock_empenhos):
        resultado = await consultar_arp_detalhe_compras(
            numero_ata="00002/2025", unidade_gerenciadora="155021", numero_item="00009"
        )
    assert resultado["saldo_unidade"] == {
        "quantidade_registrada": 300,
        "saldo_adesoes": 600,
        "saldo_remanejamento_empenho": 150,
        "qtd_limite_adesao": 600,
        "aceita_adesao": True,
        "fornecedor": "09174668000120 - FORNECEDOR TESTE LTDA",
    }
    assert resultado["empenho"] == {
        "quantidade_registrada": 300,
        "quantidade_empenhada": 150,
        "saldo_empenho": 150,
    }
    assert resultado["adesoes"] == []
    assert resultado["avisos"] == []


async def test_aviso_quando_saldo_nao_encontrado():
    mock_unidades = AsyncMock(return_value={"resultado": []})
    mock_adesoes = AsyncMock(return_value={"resultado": []})
    mock_empenhos = AsyncMock(return_value={"resultado": [_EMPENHO_BRUTO]})
    with patch(f"{_CLIENTE}.consultar_arp_unidades_item", new=mock_unidades), patch(
        f"{_CLIENTE}.consultar_arp_adesoes_item", new=mock_adesoes
    ), patch(f"{_CLIENTE}.consultar_arp_empenhos_item", new=mock_empenhos):
        resultado = await consultar_arp_detalhe_compras(
            numero_ata="00002/2025", unidade_gerenciadora="155021", numero_item="00009"
        )
    assert resultado["saldo_unidade"] is None
    assert any("saldo de unidade" in a for a in resultado["avisos"])


async def test_aviso_quando_empenho_do_item_nao_encontrado():
    mock_unidades = AsyncMock(return_value={"resultado": [_UNIDADE_BRUTA]})
    mock_adesoes = AsyncMock(return_value={"resultado": []})
    # Empenho de um item DIFERENTE do pedido.
    mock_empenhos = AsyncMock(
        return_value={"resultado": [{**_EMPENHO_BRUTO, "numeroItem": "99999"}]}
    )
    with patch(f"{_CLIENTE}.consultar_arp_unidades_item", new=mock_unidades), patch(
        f"{_CLIENTE}.consultar_arp_adesoes_item", new=mock_adesoes
    ), patch(f"{_CLIENTE}.consultar_arp_empenhos_item", new=mock_empenhos):
        resultado = await consultar_arp_detalhe_compras(
            numero_ata="00002/2025", unidade_gerenciadora="155021", numero_item="00009"
        )
    assert resultado["empenho"] is None
    assert any("empenho" in a for a in resultado["avisos"])


async def test_empenho_filtra_pelo_numero_item_certo_entre_varios():
    mock_unidades = AsyncMock(return_value={"resultado": [_UNIDADE_BRUTA]})
    mock_adesoes = AsyncMock(return_value={"resultado": []})
    mock_empenhos = AsyncMock(
        return_value={
            "resultado": [
                {**_EMPENHO_BRUTO, "numeroItem": "00001", "saldoEmpenho": 10},
                {**_EMPENHO_BRUTO, "numeroItem": "00009", "saldoEmpenho": 150},
                {**_EMPENHO_BRUTO, "numeroItem": "00020", "saldoEmpenho": 20},
            ]
        }
    )
    with patch(f"{_CLIENTE}.consultar_arp_unidades_item", new=mock_unidades), patch(
        f"{_CLIENTE}.consultar_arp_adesoes_item", new=mock_adesoes
    ), patch(f"{_CLIENTE}.consultar_arp_empenhos_item", new=mock_empenhos):
        resultado = await consultar_arp_detalhe_compras(
            numero_ata="00002/2025", unidade_gerenciadora="155021", numero_item="00009"
        )
    assert resultado["empenho"]["saldo_empenho"] == 150


async def test_adesoes_devolvidas_cruas_sem_traducao_de_campo():
    adesao_bruta_hipotetica = {"unidadeSolicitante": "999999", "quantidadeAdesao": 42}
    mock_unidades = AsyncMock(return_value={"resultado": [_UNIDADE_BRUTA]})
    mock_adesoes = AsyncMock(return_value={"resultado": [adesao_bruta_hipotetica]})
    mock_empenhos = AsyncMock(return_value={"resultado": [_EMPENHO_BRUTO]})
    with patch(f"{_CLIENTE}.consultar_arp_unidades_item", new=mock_unidades), patch(
        f"{_CLIENTE}.consultar_arp_adesoes_item", new=mock_adesoes
    ), patch(f"{_CLIENTE}.consultar_arp_empenhos_item", new=mock_empenhos):
        resultado = await consultar_arp_detalhe_compras(
            numero_ata="00002/2025", unidade_gerenciadora="155021", numero_item="00009"
        )
    assert resultado["adesoes"] == [adesao_bruta_hipotetica]
