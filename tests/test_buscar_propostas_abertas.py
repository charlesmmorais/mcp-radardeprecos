"""Testes de `buscar_propostas_abertas` (cliente PNCP mockado).

Patch aplicado diretamente em `mcp_radardeprecos.clients.pncp_client`
(mesmo padrão de `test_consultar_familia_contratacao_pncp.py`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from mcp_radardeprecos.tools.buscar_propostas_abertas import buscar_propostas_abertas

_PATCH_ALVO = (
    "mcp_radardeprecos.clients.pncp_client.consultar_contratacoes_proposta_aberta"
)

_PROPOSTA_BRUTA = {
    "numeroControlePNCP": "18457226000181-1-000015/2026",
    "objetoCompra": "Aquisição de notebooks",
    "orgaoEntidade": {"cnpj": "18457226000181", "razaoSocial": "Município Teste"},
    "unidadeOrgao": {"nomeUnidade": "Secretaria de TI", "ufSigla": "MG", "municipioNome": "Santa Vitória"},
    "modalidadeNome": "Pregão - Eletrônico",
    "dataAberturaProposta": "2026-07-05T10:00:00",
    "dataEncerramentoProposta": "2026-08-01T18:00:00",
    "valorTotalEstimado": 250000.0,
}


def _resposta(itens, total=None):
    return {"data": itens, "totalRegistros": total if total is not None else len(itens)}


async def test_usa_janela_padrao_de_30_dias_a_frente():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([])
        resultado = await buscar_propostas_abertas()
    assert resultado["periodo"]["dias_a_frente"] == 30
    kwargs = mock.call_args.kwargs
    assert kwargs["data_final"] == resultado["periodo"]["data_final"]
    # data_final deve ser ~30 dias a partir de hoje, em AAAAMMDD.
    assert resultado["periodo"]["data_final"] > datetime.now(timezone.utc).strftime("%Y%m%d")


async def test_limite_e_limitado_a_50():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([])
        await buscar_propostas_abertas(limite=9999)
    assert mock.call_args.kwargs["tamanho_pagina"] == 50


async def test_repassa_filtros_uf_modalidade_cnpj_e_pagina():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([])
        await buscar_propostas_abertas(
            uf="SP", modalidade=6, cnpj_orgao="18457226000181", pagina=2,
        )
    kwargs = mock.call_args.kwargs
    assert kwargs["uf"] == "SP"
    assert kwargs["codigo_modalidade_contratacao"] == 6
    assert kwargs["cnpj"] == "18457226000181"
    assert kwargs["pagina"] == 2


async def test_aviso_de_valor_estimado_esta_sempre_presente():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([_PROPOSTA_BRUTA])
        resultado = await buscar_propostas_abertas()
    assert any("ESTIMADOS" in a for a in resultado["avisos"])


async def test_formata_proposta_e_monta_link_pagina_pncp():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([_PROPOSTA_BRUTA])
        resultado = await buscar_propostas_abertas()
    proposta = resultado["propostas"][0]
    assert proposta["numero_controle_pncp"] == "18457226000181-1-000015/2026"
    assert proposta["objeto"] == "Aquisição de notebooks"
    assert proposta["orgao"] == "Município Teste"
    assert proposta["cnpj_orgao"] == "18457226000181"
    assert proposta["unidade"] == "Secretaria de TI"
    assert proposta["uf"] == "MG"
    assert proposta["municipio"] == "Santa Vitória"
    assert proposta["modalidade"] == "Pregão - Eletrônico"
    assert proposta["valor_total_estimado"] == 250000.0
    assert proposta["link_pagina_pncp"] == (
        "https://pncp.gov.br/app/editais/18457226000181/2026/15"
    )


async def test_link_pagina_pncp_none_quando_numero_controle_ausente():
    bruto_sem_numero = {**_PROPOSTA_BRUTA, "numeroControlePNCP": None}
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([bruto_sem_numero])
        resultado = await buscar_propostas_abertas()
    assert resultado["propostas"][0]["link_pagina_pncp"] is None


async def test_aviso_quando_nenhuma_proposta_encontrada():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([])
        resultado = await buscar_propostas_abertas()
    assert resultado["quantidade_retornada"] == 0
    assert any("Nenhuma contratação" in a for a in resultado["avisos"])


async def test_aviso_quando_total_no_periodo_excede_retornado():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([_PROPOSTA_BRUTA], total=120)
        resultado = await buscar_propostas_abertas()
    assert resultado["total_no_periodo"] == 120
    assert resultado["quantidade_retornada"] == 1
    assert any("120 contratação" in a for a in resultado["avisos"])


# --- incluir_bruto opt-in ---


async def test_incluir_bruto_false_por_padrao_nao_inclui_dados_originais():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([_PROPOSTA_BRUTA])
        resultado = await buscar_propostas_abertas()
    assert "dados_originais" not in resultado["propostas"][0]


async def test_incluir_bruto_true_inclui_dados_originais():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta([_PROPOSTA_BRUTA])
        resultado = await buscar_propostas_abertas(incluir_bruto=True)
    assert resultado["propostas"][0]["dados_originais"] == _PROPOSTA_BRUTA
