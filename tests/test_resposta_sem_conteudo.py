"""Regressão: resposta 204 / corpo vazio das fontes não pode virar crash.

``clients/base.get_json`` devolve ``None`` em HTTP 204 e em corpo vazio com
2xx — comportamento deliberado e documentado lá, para que quem chama decida o
significado. Cinco tools usavam ``.get(...)`` direto sobre esse retorno e
estouravam ``'NoneType' object has no attribute 'get'``.

Encontrado em produção chamando
``consultar_contratos_orgao_pncp`` para um órgão federal: o endpoint de
contratos do PNCP responde **204 numa janela sem contratos**, situação normal
numa varredura de 30 em 30 dias. O erro estourava FORA do ``try`` que protege
cada fatia, abortando a varredura inteira — inclusive as fatias com dados.

O ponto destes testes não é só "não quebrar". É que **o significado do vazio
muda conforme a tool**, e cada uma tem de dizer a coisa certa:

- varredura de contratos e PCA → vazio é resposta legítima, segue em frente;
- detalhe de UMA contratação → vazio é "não encontrada", falha em voz alta;
- facetas de filtro → vazio é "o índice não respondeu", falha em voz alta.

Um ``or {}`` uniforme nos cinco pontos teria calado os dois últimos casos,
transformando "a fonte não respondeu" em "não há dados" — o falso negativo
que este projeto existe para evitar.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.clients.base import UpstreamError
from mcp_radardeprecos.tools.consultar_contratacao_pncp import consultar_contratacao_pncp
from mcp_radardeprecos.tools.consultar_contratos_orgao_pncp import (
    consultar_contratos_orgao_pncp,
)
from mcp_radardeprecos.tools.consultar_pca import consultar_pca
from mcp_radardeprecos.tools.listar_filtros_pncp import listar_filtros_pncp

CNPJ_ORGAO = "33683111000107"


# --- Vazio LEGÍTIMO: a tool segue em frente ---------------------------------


async def test_contratos_por_orgao_tolera_fatia_sem_conteudo():
    """O caso exato reportado em produção."""
    with patch(
        "mcp_radardeprecos.tools.consultar_contratos_orgao_pncp.pncp_client.consultar_contratos",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = None  # 204 em todas as fatias
        r = await consultar_contratos_orgao_pncp(
            CNPJ_ORGAO, data_inicial="20260101", data_final="20260131"
        )
    assert r["quantidade_retornada"] == 0
    assert r["cnpj_orgao"] == CNPJ_ORGAO


async def test_contratos_por_orgao_nao_afirma_total_que_a_fonte_nao_deu():
    """Sem `totalRegistros`, o total não pode ser apresentado como confiável.

    É a diferença entre "o órgão tem zero contratos" e "a fonte não disse
    quantos são".
    """
    with patch(
        "mcp_radardeprecos.tools.consultar_contratos_orgao_pncp.pncp_client.consultar_contratos",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = None
        r = await consultar_contratos_orgao_pncp(
            CNPJ_ORGAO, data_inicial="20260101", data_final="20260131"
        )
    assert r.get("total_registros") is None or r.get("total_registros_confiavel") is False


async def test_contratos_por_orgao_nao_perde_as_fatias_que_tinham_dados():
    """Regressão do que mais doeu: uma fatia vazia abortava a varredura toda."""
    contrato = {
        "numeroControlePNCP": "33683111000107-2-000001/2026",
        "objetoContrato": "objeto de teste",
        "niFornecedor": "11222333000181",
    }
    with patch(
        "mcp_radardeprecos.tools.consultar_contratos_orgao_pncp.pncp_client.consultar_contratos",
        new_callable=AsyncMock,
    ) as mock:
        # 1ª fatia vazia (204), 2ª com dado. Antes, a 1ª derrubava tudo.
        mock.side_effect = [None, {"data": [contrato], "totalRegistros": 1}] + [
            {"data": [], "totalRegistros": 0}
        ] * 40
        r = await consultar_contratos_orgao_pncp(CNPJ_ORGAO, janelas_meses=3)
    assert r["quantidade_retornada"] == 1


async def test_pca_tolera_resposta_sem_conteudo():
    with patch(
        "mcp_radardeprecos.tools.consultar_pca.pncp_client.consultar_pca_por_periodo",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = None
        r = await consultar_pca(data_inicio="20260101", data_fim="20260131")
    assert r["itens_planejados"] == []
    assert any("Nenhum item de PCA" in a for a in r["avisos"])


# --- Vazio AMBÍGUO: a tool falha em voz alta --------------------------------


async def test_detalhe_de_contratacao_sem_conteudo_nao_vira_casca_de_nulls():
    """204 aqui é "não encontrada", não "encontrada e vazia".

    Um `detalhe or {}` devolveria um registro com todos os campos None, que
    quem lê não distingue de uma contratação real mal preenchida.
    """
    with patch(
        "mcp_radardeprecos.tools.consultar_contratacao_pncp.pncp_client.consultar_contratacao_detalhe",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = None
        with pytest.raises(UpstreamError, match="não encontrada"):
            await consultar_contratacao_pncp(cnpj=CNPJ_ORGAO, ano=2026, sequencial=999999)


async def test_filtros_sem_conteudo_nao_viram_lista_vazia_de_filtros():
    """`{}` seria lido como "este tipo de documento não tem filtros" — falso."""
    with patch(
        "mcp_radardeprecos.tools.listar_filtros_pncp.pncp_client.listar_filtros",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = None
        with pytest.raises(UpstreamError, match="não devolveu as facetas"):
            await listar_filtros_pncp(tipo_documento="edital")
