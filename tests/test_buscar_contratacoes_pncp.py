"""Testes de `buscar_contratacoes_pncp` (cliente PNCP mockado).

Cobertura focada: comportamento básico da
varredura + incluir_bruto. Não é uma suíte exaustiva de todos os ramos da
tool (incluir_arquivos, orçamento de tempo etc.), que já são exercitados
indiretamente por outras tools que compartilham utils/varredura.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from mcp_radardeprecos.tools.buscar_contratacoes_pncp import buscar_contratacoes_pncp

_CLIENTE = "mcp_radardeprecos.clients.pncp_client"

_HOJE = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")

_EDITAL_BRUTO = {
    "numero_controle_pncp": "18457226000181-1-000015/2026",
    "title": "Aquisição de notebooks",
    "description": "Aquisição de notebooks para a rede municipal",
    "orgao_nome": "Município Teste",
    "orgao_cnpj": "18457226000181",
    "uf": "MG",
    "municipio_nome": "Santa Vitória",
    "modalidade_licitacao_nome": "Pregão - Eletrônico",
    "data_publicacao_pncp": _HOJE,
    "tem_resultado": True,
}

_ITEM_BRUTO = {
    "numeroItem": 1,
    "descricao": "Notebook 16GB RAM",
    "quantidade": 10,
    "unidadeMedida": "Unidade",
    "valorUnitarioEstimado": 3500.0,
    "valorTotal": 35000.0,
    "situacaoCompraItemNome": "Homologado",
    "temResultado": True,
}


def _resposta_indice(items, total=None):
    return {"items": items, "total": total if total is not None else len(items)}


async def test_retorna_contratacoes_com_itens_formatados():
    with patch(f"{_CLIENTE}.buscar_texto", new_callable=AsyncMock) as mock_busca, \
         patch(f"{_CLIENTE}.consultar_itens_contratacao", new_callable=AsyncMock) as mock_itens, \
         patch(f"{_CLIENTE}.consultar_resultado_item", new_callable=AsyncMock) as mock_resultado:
        mock_busca.return_value = _resposta_indice([_EDITAL_BRUTO])
        mock_itens.return_value = [_ITEM_BRUTO]
        mock_resultado.return_value = []
        resultado = await buscar_contratacoes_pncp("notebook")

    assert resultado["quantidade_retornada"] == 1
    contratacao = resultado["resultados"][0]
    assert contratacao["numero_controle_pncp"] == "18457226000181-1-000015/2026"
    assert contratacao["objeto"] == "Aquisição de notebooks para a rede municipal"
    item = contratacao["itens"][0]
    assert item["descricao"] == "Notebook 16GB RAM"
    assert item["valor_unitario_estimado"] == 3500.0
    assert "dados_originais" not in contratacao
    assert "dados_originais" not in item


async def test_incluir_bruto_true_inclui_dados_originais_em_contratacao_e_item():
    with patch(f"{_CLIENTE}.buscar_texto", new_callable=AsyncMock) as mock_busca, \
         patch(f"{_CLIENTE}.consultar_itens_contratacao", new_callable=AsyncMock) as mock_itens, \
         patch(f"{_CLIENTE}.consultar_resultado_item", new_callable=AsyncMock) as mock_resultado:
        mock_busca.return_value = _resposta_indice([_EDITAL_BRUTO])
        mock_itens.return_value = [_ITEM_BRUTO]
        mock_resultado.return_value = []
        resultado = await buscar_contratacoes_pncp("notebook", incluir_bruto=True)

    contratacao = resultado["resultados"][0]
    assert contratacao["dados_originais"] == _EDITAL_BRUTO
    assert contratacao["itens"][0]["dados_originais"] == _ITEM_BRUTO
