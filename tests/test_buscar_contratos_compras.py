"""Testes de `buscar_contratos_compras` (cliente PNCP mockado).

Cobertura focada: comportamento básico da
varredura + incluir_bruto. Não é uma suíte exaustiva de todos os ramos da
tool (incluir_arquivos, status, orçamento de tempo etc.).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from mcp_radardeprecos.tools.buscar_contratos_compras import buscar_contratos_compras

_CLIENTE = "mcp_radardeprecos.clients.pncp_client"

_HOJE = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")

_CONTRATO_BRUTO = {
    "numero_controle_pncp": "18457226000181-2-000010/2026",
    "title": "Contrato de manutenção predial",
    "description": "Manutenção predial da sede",
    "orgao_nome": "Município Teste",
    "orgao_cnpj": "18457226000181",
    "uf": "MG",
    "municipio_nome": "Santa Vitória",
    "modalidade_licitacao_nome": "Pregão - Eletrônico",
    "valor_global": 120000.0,
    "data_publicacao_pncp": _HOJE,
    "data_inicio_vigencia": "2026-01-01",
    "data_fim_vigencia": "2026-12-31",
}


def _resposta_indice(items, total=None):
    return {"items": items, "total": total if total is not None else len(items)}


async def test_retorna_contratos_formatados():
    with patch(f"{_CLIENTE}.buscar_texto", new_callable=AsyncMock) as mock_busca:
        mock_busca.return_value = _resposta_indice([_CONTRATO_BRUTO])
        resultado = await buscar_contratos_compras("manutenção predial")

    assert resultado["quantidade_retornada"] == 1
    contrato = resultado["resultados"][0]
    assert contrato["numero_controle_pncp"] == "18457226000181-2-000010/2026"
    assert contrato["objeto"] == "Manutenção predial da sede"
    assert contrato["valor_global"] == 120000.0
    assert "dados_originais" not in contrato


async def test_incluir_bruto_true_inclui_dados_originais():
    with patch(f"{_CLIENTE}.buscar_texto", new_callable=AsyncMock) as mock_busca:
        mock_busca.return_value = _resposta_indice([_CONTRATO_BRUTO])
        resultado = await buscar_contratos_compras("manutenção predial", incluir_bruto=True)

    assert resultado["resultados"][0]["dados_originais"] == _CONTRATO_BRUTO
