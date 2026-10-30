"""Testes de integração leve das tools MCP, com o cliente PNCP mockado."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.buscar_arp_compras import buscar_arp_compras
from mcp_radardeprecos.tools.buscar_contratacoes_pncp import buscar_contratacoes_pncp
from mcp_radardeprecos.tools.buscar_contratos_compras import buscar_contratos_compras
from mcp_radardeprecos.tools.buscar_pncp_texto import buscar_pncp_texto
from mcp_radardeprecos.tools.listar_arquivos_pncp import listar_arquivos_pncp
from mcp_radardeprecos.tools.mapear_fornecedores_mercado import (
    mapear_fornecedores_mercado,
)
from mcp_radardeprecos.utils.varredura import (
    MAX_PAGINAS_BUSCA_PNCP,
    TAMANHO_PAGINA_BUSCA_PNCP,
)

AGORA = datetime.now(timezone.utc).isoformat()

EDITAL_HOMOLOGADO = {
    "title": "Edital nº 1/2026",
    "description": "Aquisição de notebooks",
    "orgao_nome": "Órgão Teste",
    "orgao_cnpj": "12345678000199",
    "uf": "SP",
    "municipio_nome": "São Paulo",
    "modalidade_licitacao_nome": "Pregão - Eletrônico",
    "data_publicacao_pncp": AGORA,
    "numero_controle_pncp": "12345678000199-1-000010/2026",
    "item_url": "/compras/12345678000199/2026/10",
    "tem_resultado": True,
}

CONTRATO_VIGENTE = {
    "title": "Contrato nº 1/2026",
    "description": "Fornecimento de notebooks",
    "orgao_nome": "Órgão Teste",
    "orgao_cnpj": "12345678000199",
    "uf": "SP",
    "municipio_nome": "São Paulo",
    "modalidade_licitacao_nome": "Pregão - Eletrônico",
    "valor_global": 50000.0,
    "data_publicacao_pncp": AGORA,
    "data_inicio_vigencia": AGORA,
    "data_fim_vigencia": AGORA,
    "numero_controle_pncp": "12345678000199-2-000010/2026",
    "item_url": "/contratos/12345678000199/2026/10",
}


async def test_buscar_pncp_texto_rejeita_tipo_documento_invalido():
    with pytest.raises(ValueError):
        await buscar_pncp_texto("notebook", "invalido")


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_repassa_para_o_cliente(mock_buscar):
    mock_buscar.return_value = {"items": [], "total": 0}
    resultado = await buscar_pncp_texto("notebook", "edital")
    assert resultado == {"items": [], "total": 0}
    mock_buscar.assert_awaited_once()


async def test_buscar_pncp_texto_rejeita_modalidade_desconhecida():
    with pytest.raises(ValueError):
        await buscar_pncp_texto("notebook", "edital", modalidade=999)


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_aceita_modalidade_valida(mock_buscar):
    mock_buscar.return_value = {"items": [], "total": 0}
    await buscar_pncp_texto("notebook", "edital", modalidade=6)  # 6 = Pregão Eletrônico
    mock_buscar.assert_awaited_once()


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_janelas_meses_filtra_por_data(mock_buscar):
    antigo = {
        **EDITAL_HOMOLOGADO,
        "numero_controle_pncp": "12345678000199-1-000011/2026",
        "data_publicacao_pncp": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
    }
    mock_buscar.return_value = {"items": [EDITAL_HOMOLOGADO, antigo], "total": 2}

    resultado = await buscar_pncp_texto("notebook", "edital", janelas_meses=6, tamanho_pagina=10)

    # Só o item recente sobrevive ao filtro; o "total" reflete o índice
    # completo do servidor, não a contagem pós-filtro.
    assert [i["numero_controle_pncp"] for i in resultado["items"]] == [
        EDITAL_HOMOLOGADO["numero_controle_pncp"]
    ]
    assert resultado["total"] == 2
    mock_buscar.assert_awaited_once()


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_janelas_meses_pagina_ate_encontrar_suficientes(mock_buscar):
    """Pagina enquanto os itens ainda estao DENTRO da janela.

    Nota historica, porque errei duas vezes aqui em sequencia. Na v0.4.20 eu
    reescrevi este teste alegando que a fixture original — pagina 1 antiga,
    pagina 2 com um item recente — seria "impossivel sob ordenacao
    decrescente por data de publicacao". Essa alegacao era falsa: o indice
    ordena por data de ATUALIZACAO (medido em 2026-08-21), entao paginas
    antigas seguidas de itens recentes sao exatamente o que ele produz.

    A fixture original estava certa e a minha justificativa, errada. O teste
    ficou nesta forma por cobrir o caso complementar (paginar enquanto os
    itens ainda entram na janela), e o caso da fixture original passou a ser
    coberto por
    test_buscar_pncp_texto_nao_para_por_data_pois_o_indice_ordena_por_atualizacao.
    """
    def _pagina(inicio: int, dias: int, quantidade: int):
        return {
            "items": [
                {
                    **EDITAL_HOMOLOGADO,
                    "numero_controle_pncp": f"12345678000199-1-{inicio + i:06d}/2026",
                    "data_publicacao_pncp": (
                        datetime.now(timezone.utc) - timedelta(days=dias)
                    ).isoformat(),
                }
                for i in range(quantidade)
            ],
            # 2 paginas exatas: e o "total" que define ultima_pagina, e com
            # ele o lote concorrente nao passa da pagina 2.
            "total": 2 * TAMANHO_PAGINA_BUSCA_PNCP,
        }

    # Pagina 1 cheia, toda dentro da janela, mas com menos itens que o limite
    # pedido (60) — obriga a buscar a pagina 2.
    mock_buscar.side_effect = [_pagina(0, 10, TAMANHO_PAGINA_BUSCA_PNCP),
                               _pagina(100, 20, TAMANHO_PAGINA_BUSCA_PNCP)]

    resultado = await buscar_pncp_texto("notebook", "edital", janelas_meses=6, tamanho_pagina=60)

    assert mock_buscar.await_count == 2
    assert len(resultado["items"]) == 60
    # pagina=1 na primeira chamada, pagina=2 na segunda — loop interno, não o
    # parametro "pagina" recebido pela tool.
    assert mock_buscar.call_args_list[0].kwargs["pagina"] == 1
    assert mock_buscar.call_args_list[1].kwargs["pagina"] == 2


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_nao_para_por_data_pois_o_indice_ordena_por_atualizacao(mock_buscar):
    """A varredura NAO pode encerrar ao ver um item fora da janela.

    A v0.4.20 tinha uma parada antecipada aqui, revertida no mesmo dia por
    medicao. Com q=notebook&ordenacao=-data, os 10 primeiros resultados do
    /api/search saem assim:

      data_publicacao_pncp   21/08, 11/08, 21/08, 10/04, 21/08, ...  (NAO monotonico)
      data_atualizacao_pncp  14:35:27 > 14:25:49 > 14:24:03 > ...    (decrescente)

    O indice ordena por data de ATUALIZACAO. Um edital publicado em abril e
    reeditado hoje ocupa a 4a posicao da 1a pagina; uma parada que olhasse a
    publicacao descartaria dali em diante — inclusive dezenas publicados hoje.

    Este teste trava a ausencia da parada: pagina cheia de itens antigos NAO
    encerra a varredura.
    """
    antigo = {
        **EDITAL_HOMOLOGADO,
        "data_publicacao_pncp": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
    }
    mock_buscar.return_value = {
        "items": [
            {**antigo, "numero_controle_pncp": f"12345678000199-1-{i:06d}/2026"}
            for i in range(TAMANHO_PAGINA_BUSCA_PNCP)
        ],
        "total": 10_000,
    }

    resultado = await buscar_pncp_texto("notebook", "edital", janelas_meses=6)

    assert mock_buscar.await_count > 1, "parou cedo — a parada por data voltou?"
    assert resultado["items"] == []


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_ordenacao_crescente_avisa_e_nao_para(mock_buscar):
    """Com ordenacao='data' a parada por janela e INVALIDA — e o vazio, enganoso.

    Ordenando do mais antigo para o mais novo, a varredura comeca na ponta
    errada do indice: nada se pode concluir sobre as paginas seguintes, entao
    a parada antecipada fica desligada. O resultado tende a ser vazio por
    esgotamento de orcamento, e sem aviso isso se leria como "nao existe nada
    no periodo" em vez de "a varredura nao chegou ao periodo".
    """
    antigo = {
        **EDITAL_HOMOLOGADO,
        "data_publicacao_pncp": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
    }
    mock_buscar.return_value = {
        "items": [
            {**antigo, "numero_controle_pncp": f"12345678000199-1-{i:06d}/2026"}
            for i in range(TAMANHO_PAGINA_BUSCA_PNCP)
        ],
        "total": 10_000,
    }

    resultado = await buscar_pncp_texto(
        "notebook", "edital", janelas_meses=6, ordenacao="data"
    )

    assert mock_buscar.await_count > 1  # nao parou na primeira pagina
    assert resultado["items"] == []
    assert any("ordenacao='data'" in a for a in resultado["avisos"])
    assert any("NÃO CHEGOU" in a for a in resultado["avisos"])


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_janelas_meses_respeita_limite_de_paginas(mock_buscar):
    antigo_template = {
        **EDITAL_HOMOLOGADO,
        "data_publicacao_pncp": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
    }
    pagina_cheia_sem_match = {
        "items": [
            {**antigo_template, "numero_controle_pncp": f"12345678000199-1-{i:06d}/2026"}
            for i in range(TAMANHO_PAGINA_BUSCA_PNCP)
        ],
        "total": 10_000,
    }
    mock_buscar.return_value = pagina_cheia_sem_match

    resultado = await buscar_pncp_texto("notebook", "edital", janelas_meses=6)

    assert mock_buscar.await_count == MAX_PAGINAS_BUSCA_PNCP
    assert resultado["items"] == []


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_agrega_itens(mock_busca, mock_itens):
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = [
        {
            "descricao": "Notebook",
            "quantidade": 10,
            "unidadeMedida": "UN",
            "valorUnitarioEstimado": 3500.0,
            "valorTotal": 35000.0,
            "situacaoCompraItemNome": "Homologado",
        }
    ]

    resultado = await buscar_contratacoes_pncp("notebook", limite=5)

    assert resultado["quantidade_retornada"] == 1
    contratacao = resultado["resultados"][0]
    assert contratacao["itens"][0]["valor_unitario_estimado"] == 3500.0
    mock_itens.assert_awaited_once_with("12345678000199", 2026, 10)


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_link_pncp_correto_sem_segmento_duplicado(
    mock_busca, mock_itens
):
    # Regressão: link_pncp construído a partir de item_url ("/compras/...")
    # gerava ".../app/editais/compras/..." (segmento duplicado), formato que
    # não existe no site e dá erro. O link tem que vir certo, construído a
    # partir de cnpj/ano/sequencial (numero_controle_pncp).
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = []

    resultado = await buscar_contratacoes_pncp("notebook")

    link = resultado["resultados"][0]["link_pncp"]
    assert link == "https://pncp.gov.br/app/editais/12345678000199/2026/10"
    assert "/editais/compras/" not in link


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_ignora_nao_homologadas_por_padrao(mock_busca):
    nao_homologado = {**EDITAL_HOMOLOGADO, "tem_resultado": False}
    mock_busca.return_value = {"items": [nao_homologado], "total": 1}
    resultado = await buscar_contratacoes_pncp("notebook")
    assert resultado["quantidade_retornada"] == 0


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_resultado_item",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_busca_valor_homologado_por_padrao(
    mock_busca, mock_itens, mock_resultado
):
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = [
        {
            "numeroItem": 1,
            "descricao": "Notebook",
            "quantidade": 10,
            "unidadeMedida": "UN",
            "valorUnitarioEstimado": 3500.0,
            "valorTotal": 35000.0,
            "situacaoCompraItemNome": "Homologado",
            "temResultado": True,
        }
    ]
    mock_resultado.return_value = [
        {
            "niFornecedor": "11222333000144",
            "nomeRazaoSocialFornecedor": "Fornecedor Vencedor Ltda",
            "quantidadeHomologada": 10,
            "valorUnitarioHomologado": 3299.0,
            "dataResultado": "2026-01-10",
        }
    ]

    resultado = await buscar_contratacoes_pncp("notebook", limite=5)

    item = resultado["resultados"][0]["itens"][0]
    # O valor estimado continua disponível, mas o homologado (o correto para
    # pesquisa de preços) também é preenchido por padrão.
    assert item["valor_unitario_estimado"] == 3500.0
    assert item["valor_unitario_homologado"] == 3299.0
    assert item["quantidade_homologada"] == 10
    assert item["fornecedor_vencedor"] == {
        "cnpj": "11222333000144",
        "nome": "Fornecedor Vencedor Ltda",
        # Promovidos na v0.4.18; None aqui porque o mock não os fornece.
        "porte": None,
        "tipo_pessoa": None,
    }
    assert item["data_resultado"] == "2026-01-10"
    mock_resultado.assert_awaited_once_with("12345678000199", 2026, 10, 1)


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_resultado_item",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_incluir_valor_homologado_false_nao_chama_resultado(
    mock_busca, mock_itens, mock_resultado
):
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = [
        {
            "numeroItem": 1,
            "descricao": "Notebook",
            "quantidade": 10,
            "unidadeMedida": "UN",
            "valorUnitarioEstimado": 3500.0,
            "valorTotal": 35000.0,
            "situacaoCompraItemNome": "Homologado",
            "temResultado": True,
        }
    ]

    resultado = await buscar_contratacoes_pncp(
        "notebook", limite=5, incluir_valor_homologado=False
    )

    item = resultado["resultados"][0]["itens"][0]
    assert item["valor_unitario_estimado"] == 3500.0
    assert item["valor_unitario_homologado"] is None
    mock_resultado.assert_not_awaited()


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_resultado_item",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_item_sem_resultado_nao_chama_endpoint(
    mock_busca, mock_itens, mock_resultado
):
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = [
        {
            "numeroItem": 1,
            "descricao": "Notebook",
            "quantidade": 10,
            "unidadeMedida": "UN",
            "valorUnitarioEstimado": 3500.0,
            "valorTotal": 35000.0,
            "situacaoCompraItemNome": "Em andamento",
            "temResultado": False,
        }
    ]

    resultado = await buscar_contratacoes_pncp("notebook", limite=5)

    item = resultado["resultados"][0]["itens"][0]
    assert item["valor_unitario_homologado"] is None
    mock_resultado.assert_not_awaited()


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_resultado_item",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_falha_no_resultado_nao_derruba_busca(
    mock_busca, mock_itens, mock_resultado
):
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = [
        {
            "numeroItem": 1,
            "descricao": "Notebook",
            "quantidade": 10,
            "unidadeMedida": "UN",
            "valorUnitarioEstimado": 3500.0,
            "valorTotal": 35000.0,
            "situacaoCompraItemNome": "Homologado",
            "temResultado": True,
        }
    ]
    mock_resultado.side_effect = RuntimeError("timeout")

    resultado = await buscar_contratacoes_pncp("notebook", limite=5)

    item = resultado["resultados"][0]["itens"][0]
    assert item["valor_unitario_estimado"] == 3500.0
    assert item["valor_unitario_homologado"] is None


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_filtra_por_cnpj(mock_busca):
    outro_orgao = {**CONTRATO_VIGENTE, "orgao_cnpj": "00000000000000"}
    mock_busca.return_value = {"items": [CONTRATO_VIGENTE, outro_orgao], "total": 2}
    resultado = await buscar_contratos_compras("notebook", cnpj_orgao="12345678000199")
    assert resultado["quantidade_retornada"] == 1
    assert resultado["resultados"][0]["cnpj_orgao"] == "12345678000199"
    # link_pncp é a página do site, nunca um link de download direto
    assert "app/contratos" in resultado["resultados"][0]["link_pncp"]


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_link_pncp_correto_sem_segmento_duplicado(mock_busca):
    # Regressão: link_pncp construído a partir de item_url ("/contratos/...")
    # gerava ".../app/contratos/contratos/..." (segmento duplicado), formato
    # que não existe no site e dá erro. O link tem que vir certo, construído
    # a partir de cnpj/ano/sequencial (numero_controle_pncp).
    mock_busca.return_value = {"items": [CONTRATO_VIGENTE], "total": 1}

    resultado = await buscar_contratos_compras("notebook")

    link = resultado["resultados"][0]["link_pncp"]
    assert link == "https://pncp.gov.br/app/contratos/12345678000199/2026/10"
    assert "/contratos/contratos/" not in link


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.consultar_arquivos",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_incluir_arquivos_traz_link_de_download(
    mock_busca, mock_arquivos
):
    mock_busca.return_value = {"items": [CONTRATO_VIGENTE], "total": 1}
    mock_arquivos.return_value = [
        {
            "titulo": "ContratoAssinado.pdf",
            "tipoDocumentoNome": "Contrato",
            "uri": "https://pncp.gov.br/pncp-api/v1/orgaos/12345678000199/contratos/2026/10/arquivos/1",
        }
    ]

    resultado = await buscar_contratos_compras("notebook", incluir_arquivos=True)

    contrato = resultado["resultados"][0]
    assert contrato["arquivos"][0]["url_download"] == (
        "https://pncp.gov.br/pncp-api/v1/orgaos/12345678000199/contratos/2026/10/arquivos/1"
    )
    mock_arquivos.assert_awaited_once_with("12345678000199", 2026, 10, "contratos")


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.consultar_arquivos",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_falha_isolada_em_arquivos_nao_derruba_busca(
    mock_busca, mock_arquivos
):
    mock_busca.return_value = {"items": [CONTRATO_VIGENTE], "total": 1}
    mock_arquivos.side_effect = RuntimeError("timeout")

    resultado = await buscar_contratos_compras("notebook", incluir_arquivos=True)

    assert resultado["resultados"][0]["arquivos"] == []


async def test_buscar_contratos_compras_sem_incluir_arquivos_nao_tem_o_campo():
    with patch(
        "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
        new_callable=AsyncMock,
    ) as mock_busca:
        mock_busca.return_value = {"items": [CONTRATO_VIGENTE], "total": 1}
        resultado = await buscar_contratos_compras("notebook")
    assert "arquivos" not in resultado["resultados"][0]


async def test_buscar_contratos_compras_rejeita_status_invalido():
    with pytest.raises(ValueError, match="status"):
        await buscar_contratos_compras("notebook", status="xyz")


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_nao_fixa_mais_status_vigente(mock_busca):
    # Correção v0.1.27: até a v0.1.26 o status="vigente" era fixo no código,
    # causando subcontagem severa (contratos com vigência já encerrada, como
    # empenhos de baixo valor, ficavam fora mesmo tendo sido assinados no
    # período pedido). Por padrão agora não filtra por status.
    mock_busca.return_value = {"items": [], "total": 0}
    await buscar_contratos_compras("notebook")
    _, kwargs = mock_busca.call_args
    assert kwargs["status"] is None


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_aceita_status_explicito(mock_busca):
    mock_busca.return_value = {"items": [], "total": 0}
    await buscar_contratos_compras("notebook", status="vigente")
    _, kwargs = mock_busca.call_args
    assert kwargs["status"] == "vigente"


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_avisa_quando_limite_e_atingido(mock_busca):
    itens = [
        {**CONTRATO_VIGENTE, "numero_controle_pncp": f"12345678000199-2-{i:06d}/2026"}
        for i in range(60)
    ]
    mock_busca.return_value = {"items": itens, "total": 60}
    resultado = await buscar_contratos_compras("notebook", limite=5)
    assert resultado["quantidade_retornada"] == 5
    assert any("truncado" in a.lower() for a in resultado["avisos"])
    assert any("consultar_contratos_orgao_pncp" in a for a in resultado["avisos"])


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_avisa_sobre_nao_exaustividade_com_cnpj(mock_busca):
    mock_busca.return_value = {"items": [CONTRATO_VIGENTE], "total": 1}
    resultado = await buscar_contratos_compras("notebook", cnpj_orgao="12345678000199")
    assert any("consultar_contratos_orgao_pncp" in a for a in resultado["avisos"])


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_arquivos",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_incluir_arquivos_traz_edital_e_retificacao(
    mock_busca, mock_itens, mock_arquivos
):
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = []
    mock_arquivos.return_value = [
        {
            "titulo": "Edital.pdf",
            "tipoDocumentoNome": "Edital",
            "uri": "https://pncp.gov.br/pncp-api/v1/orgaos/12345678000199/compras/2026/10/arquivos/1",
        },
        {
            "titulo": "Retificacao1.pdf",
            "tipoDocumentoNome": "Aviso de Retificação",
            "uri": "https://pncp.gov.br/pncp-api/v1/orgaos/12345678000199/compras/2026/10/arquivos/2",
        },
    ]

    resultado = await buscar_contratacoes_pncp("notebook", limite=5, incluir_arquivos=True)

    contratacao = resultado["resultados"][0]
    assert len(contratacao["arquivos"]) == 2
    assert contratacao["arquivos"][0]["tipo_documento"] == "Edital"
    assert contratacao["arquivos"][1]["tipo_documento"] == "Aviso de Retificação"
    assert contratacao["arquivos"][1]["url_download"].endswith("/arquivos/2")
    # recurso="compras" (não "contratos") — edital/retificação ficam na compra.
    mock_arquivos.assert_awaited_once_with("12345678000199", 2026, 10, "compras")


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_arquivos",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_falha_isolada_em_arquivos_nao_derruba_busca(
    mock_busca, mock_itens, mock_arquivos
):
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = []
    mock_arquivos.side_effect = RuntimeError("timeout")

    resultado = await buscar_contratacoes_pncp("notebook", limite=5, incluir_arquivos=True)

    assert resultado["resultados"][0]["arquivos"] == []


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_sem_incluir_arquivos_nao_tem_o_campo(mock_busca, mock_itens):
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = []

    resultado = await buscar_contratacoes_pncp("notebook", limite=5)

    assert "arquivos" not in resultado["resultados"][0]


async def test_listar_arquivos_pncp_rejeita_tipo_documento_invalido():
    with pytest.raises(ValueError):
        await listar_arquivos_pncp("invalido", "12345678000199", 2026, 10)


@patch(
    "mcp_radardeprecos.tools.listar_arquivos_pncp.pncp_client.consultar_arquivos",
    new_callable=AsyncMock,
)
async def test_listar_arquivos_pncp_usa_recurso_contratos_para_tipo_contrato(mock_arquivos):
    mock_arquivos.return_value = [
        {
            "titulo": "ContratoAssinado.pdf",
            "tipoDocumentoNome": "Outros Documentos",
            "dataPublicacaoPncp": "2026-07-03T17:08:44",
            "sequencialDocumento": 1,
            "uri": "https://pncp.gov.br/pncp-api/v1/orgaos/00509968000148/contratos/2026/1835/arquivos/1",
        }
    ]
    resultado = await listar_arquivos_pncp("contrato", "00509968000148", 2026, 1835)
    assert resultado["quantidade"] == 1
    assert resultado["arquivos"][0]["url_download"].endswith("/arquivos/1")
    mock_arquivos.assert_awaited_once_with(
        "00509968000148", 2026, 1835, "contratos", pagina=1, tamanho_pagina=50
    )


@patch(
    "mcp_radardeprecos.tools.listar_arquivos_pncp.pncp_client.consultar_arquivos",
    new_callable=AsyncMock,
)
async def test_listar_arquivos_pncp_usa_recurso_compras_para_edital_e_ata(mock_arquivos):
    mock_arquivos.return_value = []
    await listar_arquivos_pncp("edital", "12345678000199", 2026, 10)
    await listar_arquivos_pncp("ata", "12345678000199", 2026, 10)
    assert mock_arquivos.await_args_list[0].args[3] == "compras"
    assert mock_arquivos.await_args_list[1].args[3] == "compras"


# --- Regressão: aviso ausente quando a janela temporal (não o limite nem o
# cnpj_orgao) é a única causa de total_encontrado_no_indice > quantidade
# retornada. Achado real: uma busca por "dynatrace" (status vigente) trazia
# total_encontrado_no_indice=10 e quantidade_retornada=4, sem nenhum aviso —
# levando a suspeitar de bug de paginação em vez do efeito esperado de
# janelas_meses=12 (padrão). Ver CHANGELOG.


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_avisa_sobre_reducao_por_janela(mock_busca):
    recentes = [
        {**CONTRATO_VIGENTE, "numero_controle_pncp": f"12345678000199-2-{i:06d}/2026"}
        for i in range(4)
    ]
    antigo_data = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    antigos = [
        {
            **CONTRATO_VIGENTE,
            "numero_controle_pncp": f"12345678000199-2-{i:06d}/2025",
            "data_publicacao_pncp": antigo_data,
        }
        for i in range(4, 10)
    ]
    mock_busca.return_value = {"items": recentes + antigos, "total": 10}

    resultado = await buscar_contratos_compras("dynatrace")

    assert resultado["quantidade_retornada"] == 4
    assert resultado["total_encontrado_no_indice"] == 10
    assert any("janela" in a.lower() for a in resultado["avisos"])
    assert not any("truncado" in a.lower() for a in resultado["avisos"])


@patch(
    "mcp_radardeprecos.tools.buscar_contratos_compras.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratos_compras_sem_aviso_quando_nada_e_filtrado(mock_busca):
    mock_busca.return_value = {"items": [CONTRATO_VIGENTE], "total": 1}
    resultado = await buscar_contratos_compras("notebook")
    # Desde a v0.4.24 SEMPRE ha uma linha de procedencia dizendo por que a
    # varredura parou — pedido num teste real: sem ela nao da para separar
    # "parei porque ja tinha o que voce pediu" de "varri tudo e era so isso".
    # O que este teste garante e a ausencia do aviso de REDUCAO.
    assert len(resultado["avisos"]) == 1
    assert resultado["avisos"][0].startswith("Varredura:")
    assert not any("apenas" in a for a in resultado["avisos"])


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_avisa_sobre_reducao_por_janela(mock_busca, mock_itens):
    antigo = {
        **EDITAL_HOMOLOGADO,
        "numero_controle_pncp": "12345678000199-1-000099/2025",
        "data_publicacao_pncp": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
    }
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO, antigo], "total": 2}
    mock_itens.return_value = []

    resultado = await buscar_contratacoes_pncp("notebook")

    assert resultado["quantidade_retornada"] == 1
    assert resultado["total_encontrado_no_indice"] == 2
    assert any("janela" in a.lower() for a in resultado["avisos"])


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_sem_aviso_quando_nada_e_filtrado(mock_busca, mock_itens):
    mock_busca.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}
    mock_itens.return_value = []

    resultado = await buscar_contratacoes_pncp("notebook")

    # Desde a v0.4.24 SEMPRE ha uma linha de procedencia dizendo por que a
    # varredura parou — pedido num teste real: sem ela nao da para separar
    # "parei porque ja tinha o que voce pediu" de "varri tudo e era so isso".
    # O que este teste garante e a ausencia do aviso de REDUCAO.
    assert len(resultado["avisos"]) == 1
    assert resultado["avisos"][0].startswith("Varredura:")
    assert not any("apenas" in a for a in resultado["avisos"])


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.consultar_itens_contratacao",
    new_callable=AsyncMock,
)
@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.pncp_client.buscar_texto",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_avisa_quando_atinge_max_paginas(mock_busca, mock_itens):
    # Achado real (2026-07-10, apontado pelo usuário; teto elevado ao máximo
    # real da API em 2026-07-11): o índice do PNCP pagina normalmente
    # (pagina=1..N), mas a tool tem uma trava de segurança interna de 100
    # páginas (10.000 registros brutos — o teto real do backend, confirmado
    # ao vivo em 2026-07-11: pagina*tamanhoPagina<=10000). Em buscas com
    # filtro restritivo (apenas_homologadas=True aqui: nenhum item das 100
    # páginas é homologado), a varredura pode parar no teto sem atingir
    # `limite` nem esgotar o índice — o aviso deve dizer isso explicitamente,
    # não só atribuir a redução à janela/homologação/limite.
    mock_itens.return_value = []

    def _pagina(prefixo):
        items = [
            {
                **EDITAL_HOMOLOGADO,
                "numero_controle_pncp": f"{prefixo}-{i}",
                "tem_resultado": False,
            }
            for i in range(TAMANHO_PAGINA_BUSCA_PNCP)
        ]
        return {"items": items, "total": 10000}

    mock_busca.side_effect = [
        _pagina(f"pg{p}") for p in range(1, MAX_PAGINAS_BUSCA_PNCP + 1)
    ]

    resultado = await buscar_contratacoes_pncp("notebook", limite=20)

    assert mock_busca.await_count == MAX_PAGINAS_BUSCA_PNCP
    assert resultado["quantidade_retornada"] == 0
    assert resultado["total_encontrado_no_indice"] == 10000
    assert any(
        "varredura interna do índice parou" in a
        and f"{MAX_PAGINAS_BUSCA_PNCP} páginas" in a
        for a in resultado["avisos"]
    )


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_janelas_meses_avisa_quando_reduzido(mock_buscar):
    antigo = {
        **EDITAL_HOMOLOGADO,
        "numero_controle_pncp": "12345678000199-1-000011/2026",
        "data_publicacao_pncp": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
    }
    mock_buscar.return_value = {"items": [EDITAL_HOMOLOGADO, antigo], "total": 2}

    resultado = await buscar_pncp_texto("notebook", "edital", janelas_meses=6, tamanho_pagina=10)

    assert resultado["total"] == 2
    assert len(resultado["items"]) == 1
    assert any("janela" in a.lower() for a in resultado["avisos"])


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_janelas_meses_sem_aviso_quando_nada_e_filtrado(mock_buscar):
    mock_buscar.return_value = {"items": [EDITAL_HOMOLOGADO], "total": 1}

    resultado = await buscar_pncp_texto("notebook", "edital", janelas_meses=6, tamanho_pagina=10)

    # Desde a v0.4.24 SEMPRE ha uma linha de procedencia dizendo por que a
    # varredura parou — pedido num teste real: sem ela nao da para separar
    # "parei porque ja tinha o que voce pediu" de "varri tudo e era so isso".
    # O que este teste garante e a ausencia do aviso de REDUCAO.
    assert len(resultado["avisos"]) == 1
    assert resultado["avisos"][0].startswith("Varredura:")
    assert not any("apenas" in a for a in resultado["avisos"])


async def test_buscar_pncp_texto_sem_janelas_meses_nao_tem_chave_avisos():
    # Modo sem janelas_meses repassa direto o retorno do cliente
    # (pncp_client.buscar_texto), sem o pós-processamento que adiciona
    # "avisos" — comportamento inalterado por esta correção.
    with patch(
        "mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto",
        new_callable=AsyncMock,
    ) as mock_buscar:
        mock_buscar.return_value = {"items": [], "total": 0}
        resultado = await buscar_pncp_texto("notebook", "edital")
    assert "avisos" not in resultado


@patch(
    "mcp_radardeprecos.tools.buscar_contratacoes_pncp.varrer_indice",
    new_callable=AsyncMock,
)
async def test_buscar_contratacoes_pncp_avisa_quando_orcamento_estoura(mock_varredura):
    # v0.1.54: quando a varredura para pelo orçamento de tempo
    # (RADARDEPRECOS_TOOL_BUDGET_SECONDS), o parcial volta com um aviso
    # explícito — não silenciosamente reduzido.
    from mcp_radardeprecos.utils.varredura import ResultadoVarredura

    mock_varredura.return_value = ResultadoVarredura(
        coletados=[], total_indice=5000, paginas_percorridas=3,
        orcamento_estourado=True,
    )

    resultado = await buscar_contratacoes_pncp("notebook", limite=20)

    assert resultado["quantidade_retornada"] == 0
    assert any(
        "orçamento de tempo" in a and "RADARDEPRECOS_TOOL_BUDGET_SECONDS" in a
        for a in resultado["avisos"]
    )


@patch("mcp_radardeprecos.tools.buscar_arp_compras.compras_client.consultar_arp", new_callable=AsyncMock)
async def test_buscar_arp_compras_avisa_que_vazio_nao_significa_ausencia(mock_arp):
    """Falso negativo de cobertura.

    Achado do usuário em 2026-08-17: buscar ARPs do TCU aqui devolveu vazio,
    enquanto o índice de Atas do PNCP mostrava várias vigentes. São universos
    diferentes — SIASG vs. publicidade da Lei 14.133 — e sem aviso o zero se
    lê como "não existem atas".
    """
    mock_arp.return_value = {"resultado": [], "totalRegistros": 0}

    resultado = await buscar_arp_compras(limite=10)

    assert resultado["atas"] == []
    assert any(
        "SIASG" in a and "consultar_ata_registro_preco" in a
        for a in resultado["avisos"]
    ), resultado["avisos"]


# --- mapear_fornecedores_mercado ---------------------------------

def _contratacao(numero, orgao, uf, data, itens):
    return {
        "numero_controle_pncp": numero, "titulo": "t", "objeto": "o",
        "orgao": orgao, "cnpj_orgao": "1", "uf": uf, "municipio": "m",
        "modalidade": "Pregão", "data_publicacao_pncp": data,
        "link_pncp": "l", "itens": itens,
    }


def _item(cnpj, nome, unitario, qtd=1, porte="ME", tipo="PJ"):
    return {
        "descricao": "d", "quantidade": qtd, "unidade_medida": "UN",
        "valor_unitario_estimado": unitario, "valor_total": unitario * qtd,
        "situacao": "Homologado", "valor_unitario_homologado": unitario,
        "quantidade_homologada": qtd,
        "fornecedor_vencedor": {
            "cnpj": cnpj, "nome": nome, "porte": porte, "tipo_pessoa": tipo,
        },
        "data_resultado": "2026-01-01",
    }


@patch("mcp_radardeprecos.tools.mapear_fornecedores_mercado.buscar_contratacoes_pncp",
       new_callable=AsyncMock)
async def test_mapear_fornecedores_agrega_por_cnpj_e_ordena_por_recorrencia(mock_busca):
    mock_busca.return_value = {
        "resultados": [
            _contratacao("A", "Orgao 1", "DF", "2026-01-10",
                         [_item("111", "Alfa", 100.0, 2), _item("222", "Beta", 50.0)]),
            _contratacao("B", "Orgao 2", "SP", "2026-02-10",
                         [_item("111", "Alfa", 120.0)]),
        ],
        "avisos": ["aviso da busca"],
    }

    r = await mapear_fornecedores_mercado("microsoft", janelas_meses=12)

    assert r["total_fornecedores"] == 2
    primeiro = r["fornecedores"][0]
    assert primeiro["identificacao"] == "111"  # venceu 2 contratações
    assert primeiro["contratacoes_vencidas"] == 2
    assert primeiro["itens_vencidos"] == 2
    assert primeiro["preco_unitario"] == {"minimo": 100.0, "maximo": 120.0, "mediano": 110.0}
    assert primeiro["valor_total_homologado"] == 320.0  # 100*2 + 120*1
    assert primeiro["orgaos"] == ["Orgao 1", "Orgao 2"]
    assert primeiro["ufs"] == ["DF", "SP"]
    assert "aviso da busca" in r["avisos"]


@patch("mcp_radardeprecos.tools.mapear_fornecedores_mercado.buscar_contratacoes_pncp",
       new_callable=AsyncMock)
async def test_mapear_fornecedores_avisa_que_e_quem_venceu_nao_quem_participou(mock_busca):
    """O limite que mais engana: vencedor != participante."""
    mock_busca.return_value = {"resultados": [], "avisos": []}

    r = await mapear_fornecedores_mercado("microsoft")

    texto = " ".join(r["avisos"])
    assert "VENCEU, não de quem PARTICIPOU" in texto
    assert "NÃO significa incapacidade de fornecer" in texto
    assert "inexigibilidade" in texto


@patch("mcp_radardeprecos.tools.mapear_fornecedores_mercado.buscar_contratacoes_pncp",
       new_callable=AsyncMock)
async def test_mapear_fornecedores_sinaliza_pessoa_fisica(mock_busca):
    """tipo_pessoa='PF' significa nome civil e CPF — precisa ser dito."""
    mock_busca.return_value = {
        "resultados": [
            _contratacao("A", "Orgao", "DF", "2026-01-10",
                         [_item("12345678901", "JOSE DA SILVA", 10.0, tipo="PF")]),
        ],
        "avisos": [],
    }

    r = await mapear_fornecedores_mercado("microsoft")

    assert r["fornecedores"][0]["tipo_pessoa"] == "PF"
    assert any("PESSOA FÍSICA" in a and "dado pessoal" in a for a in r["avisos"])


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_ordenacao_desconhecida_avisa(mock_buscar):
    """Qualquer ordenacao que nao seja '-data' cai no lado seguro.

    A UI do PNCP oferece TRES ordenacoes — "Mais recente", "Mais antigo" e
    "Mais relevante" (visto em 2026-08-21) —, e o valor de parametro da
    terceira nao e conhecido. Relevancia nao diz nada sobre datas: autorizar
    a parada antecipada nela omitiria registros dentro da janela.

    Por isso a checagem e lista branca (== "-data") e nao prefixo ("-"): um
    valor desconhecido, hoje ou no futuro, gera o aviso em vez de passar em
    silencio.
    """
    antigo = {
        **EDITAL_HOMOLOGADO,
        "data_publicacao_pncp": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
    }
    mock_buscar.return_value = {
        "items": [
            {**antigo, "numero_controle_pncp": f"12345678000199-1-{i:06d}/2026"}
            for i in range(TAMANHO_PAGINA_BUSCA_PNCP)
        ],
        "total": 10_000,
    }

    for ordenacao in ("relevancia", "-relevancia", "qualquer-coisa"):
        mock_buscar.reset_mock()
        resultado = await buscar_pncp_texto(
            "notebook", "edital", janelas_meses=6, ordenacao=ordenacao
        )
        assert mock_buscar.await_count > 1, ordenacao
        assert any("ordenacao='data'" in a for a in resultado["avisos"]), ordenacao


# --- validacao de `ano` -------------------------------------------


@pytest.mark.parametrize("valor", ["2023,2024", "2023, 2024", "2023 2024"])
async def test_buscar_pncp_texto_recusa_multiplos_anos(valor):
    """Dois anos numa chamada falham MAL no indice — recusar e melhor.

    Medido em 2026-08-21 contra o /api/search:

        anos=2024 ............. 3.552 de 24.501, todos de 2024  (filtra bem)
        anos=2023&anos=2024 ... 3.552, so de 2024  (IGNORA o primeiro valor)
        anos=2023,2024 ........ total=0, silenciosamente

    Os dois ultimos devolvem algo que se le como fato sobre o acervo — "so ha
    3.552" ou "nao ha nenhum" — quando e artefato do parametro. Recusar na
    entrada e a unica forma de isso nao virar numero em pesquisa de preco.
    """
    with pytest.raises(ValueError) as exc:
        await buscar_pncp_texto("notebook", "edital", ano=valor)
    assert "UM ano" in str(exc.value)


@patch("mcp_radardeprecos.tools.buscar_pncp_texto.pncp_client.buscar_texto", new_callable=AsyncMock)
async def test_buscar_pncp_texto_aceita_ano_como_int_ou_string(mock_buscar):
    """Cliente MCP manda numero como string com frequencia — aceitar e converter."""
    mock_buscar.return_value = {"items": [], "total": 0}

    await buscar_pncp_texto("notebook", "edital", ano=2024)
    assert mock_buscar.call_args.kwargs["ano"] == 2024

    await buscar_pncp_texto("notebook", "edital", ano="2024")
    assert mock_buscar.call_args.kwargs["ano"] == 2024


async def test_buscar_pncp_texto_recusa_ano_invalido():
    with pytest.raises(ValueError):
        await buscar_pncp_texto("notebook", "edital", ano="ano passado")
    with pytest.raises(ValueError):
        await buscar_pncp_texto("notebook", "edital", ano=True)
