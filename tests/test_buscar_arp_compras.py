"""Testes de `buscar_arp_compras` — busca de ARP no Compras.gov.br (módulo distinto do PNCP)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.buscar_arp_compras import buscar_arp_compras

_CLIENTE = "mcp_radardeprecos.clients.compras_client"


def _ata_bruta(numero="00002/2025", numero_compra="90022", unidade="155021", **overrides):
    base = {
        "numeroAtaRegistroPreco": numero,
        "codigoUnidadeGerenciadora": unidade,
        "nomeUnidadeGerenciadora": "HOSPITAL DAS CLINICAS DA UFMG",
        "codigoOrgao": 26443,
        "nomeOrgao": "EMPRESA BRASILEIRA DE SERVICOS HOSPITALARES",
        "numeroCompra": numero_compra,
        "anoCompra": "2024",
        "codigoModalidadeCompra": "05",
        "nomeModalidadeCompra": "Pregão",
        "dataAssinatura": "2025-01-07",
        "dataVigenciaInicial": "2025-01-10",
        "dataVigenciaFinal": "2026-01-10",
        "valorTotal": 569400.0,
        "statusAta": "Ata de Registro de Preços",
        "objeto": "Objeto de teste",
        "quantidadeItens": 1,
        "ataExcluido": False,
        "numeroControlePncpAta": "15126437000143-1-001219/2024-000004",
        "numeroControlePncpCompra": "15126437000143-1-001219/2024",
        "linkAtaPNCP": "https://pncp.gov.br/app/atas/x",
        "linkCompraPNCP": "https://pncp.gov.br/app/editais/x",
    }
    base.update(overrides)
    return base


def _item_bruto(numero_item, numero_ata, **overrides):
    base = {
        "numeroAtaRegistroPreco": numero_ata,
        "numeroItem": numero_item,
        "codigoItem": 614724,
        "descricaoItem": "ITEM DE TESTE",
        "tipoItem": "Material",
        "codigoPdm": 30162,
        "nomePdm": "PDM TESTE",
        "quantidadeHomologadaItem": 300,
        "quantidadeHomologadaVencedor": 300,
        "valorUnitario": 1898.0,
        "valorTotal": 569400.0,
        "maximoAdesao": 600,
        "quantidadeEmpenhada": 0,
        "niFornecedor": "09174668000120",
        "nomeRazaoSocialFornecedor": "FORNECEDOR TESTE LTDA",
        "situacaoSicaf": "1",
        "itemExcluido": False,
    }
    base.update(overrides)
    return base


async def test_rejeita_so_uma_data_de_vigencia_informada():
    with pytest.raises(ValueError, match="juntos"):
        await buscar_arp_compras(data_vigencia_inicial_min="2025-01-01")
    with pytest.raises(ValueError, match="juntos"):
        await buscar_arp_compras(data_vigencia_inicial_max="2025-01-01")


async def test_usa_janela_padrao_quando_datas_nao_informadas():
    mock_arp = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp):
        await buscar_arp_compras()
    _, kwargs = mock_arp.call_args
    assert kwargs["data_vigencia_inicial_min"] is not None
    assert kwargs["data_vigencia_inicial_max"] is not None
    assert kwargs["data_vigencia_inicial_min"] <= kwargs["data_vigencia_inicial_max"]


async def test_retorna_atas_formatadas():
    mock_arp = AsyncMock(return_value={"resultado": [_ata_bruta()], "totalRegistros": 1})
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp):
        resultado = await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01", data_vigencia_inicial_max="2025-06-30"
        )
    assert resultado["total_no_periodo"] == 1
    ata = resultado["atas"][0]
    assert ata["numero_ata_registro_preco"] == "00002/2025"
    assert ata["numero_controle_pncp_ata"] == "15126437000143-1-001219/2024-000004"
    assert ata["numero_controle_pncp_compra"] == "15126437000143-1-001219/2024"
    assert resultado["avisos"] == []


async def test_aviso_quando_total_maior_que_retornado():
    mock_arp = AsyncMock(return_value={"resultado": [_ata_bruta()], "totalRegistros": 50})
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp):
        resultado = await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01", data_vigencia_inicial_max="2025-06-30", limite=1
        )
    assert any("50 ata" in a for a in resultado["avisos"])


async def test_incluir_itens_filtra_pelo_numero_da_ata():
    # Duas atas diferentes compartilham o mesmo numeroCompra (achado real) —
    # a tool precisa filtrar no cliente pelo numeroAtaRegistroPreco exato.
    ata_alvo = _ata_bruta(numero="00021/2024", numero_compra="90003")
    mock_arp = AsyncMock(return_value={"resultado": [ata_alvo], "totalRegistros": 1})
    itens_mesma_compra = {
        "resultado": [
            _item_bruto("00001", "00021/2024"),
            _item_bruto("00001", "00022/2024"),  # outra ata, mesmo numeroCompra
        ],
        "totalRegistros": 2,
    }
    mock_itens = AsyncMock(return_value=itens_mesma_compra)
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp), patch(
        f"{_CLIENTE}.consultar_arp_itens", new=mock_itens
    ):
        resultado = await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01",
            data_vigencia_inicial_max="2025-06-30",
            incluir_itens=True,
        )
    itens = resultado["atas"][0]["itens"]
    assert len(itens) == 1
    assert itens[0]["numero_item"] == "00001"


async def test_incluir_itens_limita_a_10():
    mock_arp = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp):
        await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01",
            data_vigencia_inicial_max="2025-06-30",
            incluir_itens=True,
            limite=50,
        )
    _, kwargs = mock_arp.call_args
    assert kwargs["tamanho_pagina"] <= 10 or kwargs["tamanho_pagina"] == 10


async def test_falha_isolada_ao_buscar_itens_nao_derruba_busca():
    mock_arp = AsyncMock(return_value={"resultado": [_ata_bruta()], "totalRegistros": 1})
    mock_itens = AsyncMock(side_effect=Exception("timeout"))
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp), patch(
        f"{_CLIENTE}.consultar_arp_itens", new=mock_itens
    ):
        resultado = await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01",
            data_vigencia_inicial_max="2025-06-30",
            incluir_itens=True,
        )
    assert resultado["atas"][0]["itens"] == []


# --- filtro de item NO SERVIDOR --------------


async def test_codigo_item_ativa_incluir_itens_automaticamente_e_filtra_no_servidor():
    ata = _ata_bruta(numero="00021/2024", numero_compra="90003")
    mock_arp = AsyncMock(return_value={"resultado": [ata], "totalRegistros": 1})
    mock_itens = AsyncMock(
        return_value={"resultado": [_item_bruto("00001", "00021/2024")], "totalRegistros": 1}
    )
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp), patch(
        f"{_CLIENTE}.consultar_arp_itens", new=mock_itens
    ):
        resultado = await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01",
            data_vigencia_inicial_max="2025-06-30",
            codigo_item=614724,
        )
    # incluir_itens=False não foi passado explicitamente, mas o filtro de
    # item exige a busca de itens — deve ser ativado automaticamente.
    _, kwargs_itens = mock_itens.call_args
    assert kwargs_itens["codigo_item"] == 614724
    assert any("incluir_itens foi ativado automaticamente" in a for a in resultado["avisos"])
    assert len(resultado["atas"]) == 1
    assert resultado["atas"][0]["itens"][0]["codigo_item"] == 614724


async def test_cnpj_fornecedor_e_codigo_pdm_repassados_para_consultar_arp_itens():
    ata = _ata_bruta()
    mock_arp = AsyncMock(return_value={"resultado": [ata], "totalRegistros": 1})
    mock_itens = AsyncMock(return_value={"resultado": [], "totalRegistros": 0})
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp), patch(
        f"{_CLIENTE}.consultar_arp_itens", new=mock_itens
    ):
        await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01",
            data_vigencia_inicial_max="2025-06-30",
            codigo_pdm=30162,
            cnpj_fornecedor="09174668000120",
        )
    _, kwargs_itens = mock_itens.call_args
    assert kwargs_itens["codigo_pdm"] == 30162
    assert kwargs_itens["ni_fornecedor"] == "09174668000120"


async def test_atas_sem_item_correspondente_sao_removidas_do_resultado():
    # Caso de uso central do item 4: "atas vigentes que registram o CATMAT X"
    # numa única chamada — duas atas, só uma tem o item buscado.
    ata_com_item = _ata_bruta(numero="00021/2024", numero_compra="90003")
    ata_sem_item = _ata_bruta(numero="00099/2024", numero_compra="90099")
    mock_arp = AsyncMock(
        return_value={"resultado": [ata_com_item, ata_sem_item], "totalRegistros": 2}
    )

    async def _consultar_arp_itens(**kwargs):
        # O servidor já filtra por codigo_item — só a ata "00021/2024" tem
        # itens correspondentes nesta simulação (a outra devolve vazio).
        if kwargs.get("numero_compra") == "90003":
            return {"resultado": [_item_bruto("00001", "00021/2024")], "totalRegistros": 1}
        return {"resultado": [], "totalRegistros": 0}

    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp), patch(
        f"{_CLIENTE}.consultar_arp_itens", new=AsyncMock(side_effect=_consultar_arp_itens)
    ):
        resultado = await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01",
            data_vigencia_inicial_max="2025-06-30",
            codigo_item=614724,
        )
    assert len(resultado["atas"]) == 1
    assert resultado["atas"][0]["numero_ata_registro_preco"] == "00021/2024"
    # v0.4.25: o aviso deixou de contar as DESCARTADAS e passou a declarar a
    # cobertura da varredura — quantas atas registram o item e quantas foram
    # examinadas para chegar lá. A contagem de descartadas era enganosa: dizia
    # "2 de 10 removidas" quando as 10 eram uma amostra de 144 mil, e isso se
    # lia como se o universo tivesse sido avaliado.
    aviso_filtro = next(a for a in resultado["avisos"] if a.startswith("Filtro por item:"))
    assert "1 ata(s) registram o item buscado" in aviso_filtro
    assert "examinada" in aviso_filtro
    # Listagem esgotada (2 atas, totalRegistros=2): sem ressalva de leitura
    # parcial, porque aqui o universo REALMENTE foi todo avaliado.
    assert "NÃO permite concluir" not in aviso_filtro


# --- incluir_bruto opt-in ---


async def test_incluir_bruto_false_por_padrao_nao_inclui_dados_originais():
    ata = _ata_bruta()
    mock_arp = AsyncMock(return_value={"resultado": [ata], "totalRegistros": 1})
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp):
        resultado = await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01", data_vigencia_inicial_max="2025-06-30"
        )
    assert "dados_originais" not in resultado["atas"][0]


async def test_incluir_bruto_true_inclui_dados_originais_em_atas_e_itens():
    ata = _ata_bruta(numero="00021/2024", numero_compra="90003")
    item = _item_bruto("00001", "00021/2024")
    mock_arp = AsyncMock(return_value={"resultado": [ata], "totalRegistros": 1})
    mock_itens = AsyncMock(return_value={"resultado": [item], "totalRegistros": 1})
    with patch(f"{_CLIENTE}.consultar_arp", new=mock_arp), patch(
        f"{_CLIENTE}.consultar_arp_itens", new=mock_itens
    ):
        resultado = await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01",
            data_vigencia_inicial_max="2025-06-30",
            incluir_itens=True,
            incluir_bruto=True,
        )
    assert resultado["atas"][0]["dados_originais"] == ata
    assert resultado["atas"][0]["itens"][0]["dados_originais"] == item


@patch("mcp_radardeprecos.tools.buscar_arp_compras.compras_client.consultar_arp_itens", new_callable=AsyncMock)
@patch("mcp_radardeprecos.tools.buscar_arp_compras.compras_client.consultar_arp", new_callable=AsyncMock)
async def test_filtro_por_item_varre_a_listagem_em_vez_de_amostrar(mock_arp, mock_itens):
    """O `limite` vale sobre as atas QUE REGISTRAM o item.

    Antes, o `limite` cortava a listagem BRUTA e so depois se olhava quais
    atas tinham o item — testava-se uma amostra arbitraria de 10 em 144 mil.
    Para qualquer busca por CATMAT/PDM sem outros filtros o resultado era
    vazio quase garantido, e vazio aqui se le como "nao existe ata deste
    item". Achado num teste real em 2026-08-21 com o PDM 8435 (NOTEBOOK):
    144.255 atas no periodo, 10 lidas, nenhuma com o item.

    Cenario: 3 paginas de listagem; so a ata da 3a pagina registra o item.
    O comportamento antigo devolveria vazio.
    """
    paginas = {
        1: [_ata_bruta("00001/2024", "90001"), _ata_bruta("00002/2024", "90002")],
        2: [_ata_bruta("00003/2024", "90003")],
        3: [_ata_bruta("00099/2024", "90099")],
    }

    async def _listagem(**kwargs):
        pagina = kwargs.get("pagina", 1)
        return {"resultado": paginas.get(pagina, []), "totalRegistros": 4}

    mock_arp.side_effect = _listagem

    async def _itens(**kwargs):
        # So a compra da ata 00099/2024 registra o PDM pedido.
        if kwargs.get("numero_compra") == "90099":
            return {"resultado": [_item_bruto("00001", "00099/2024")], "totalRegistros": 1}
        return {"resultado": [], "totalRegistros": 0}

    mock_itens.side_effect = _itens

    resultado = await buscar_arp_compras(codigo_pdm=8435, limite=5)

    assert [a["numero_ata_registro_preco"] for a in resultado["atas"]] == ["00099/2024"]
    assert mock_arp.await_count >= 2, "nao paginou a listagem — voltou a amostrar"
    aviso = next(a for a in resultado["avisos"] if a.startswith("Filtro por item:"))
    assert "1 ata(s) registram o item buscado" in aviso
