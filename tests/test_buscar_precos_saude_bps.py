"""Testes da tool do Banco de Preços em Saúde.

Os registros de exemplo são REAIS, colhidos da API em 2026-08-27 (CATMAT
268252, dipirona sódica 500 mg/ml injetável) e reduzidos aos campos que os
testes examinam. Usar resposta real evita que o teste valide um formato que a
origem não pratica.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.buscar_precos_saude_bps import (
    _iso,
    buscar_precos_saude_bps,
)

_PATCH = "mcp_radardeprecos.tools.buscar_precos_saude_bps.bps_client.consultar_bps"

_REGISTRO = {
    "anoCompra": 2026,
    "nomeInstituicao": "CONSORCIO INTERMUNICIPAL DO VALE DO SAO FRANCISCO - CONIVALES",
    "cnpjInstituicao": "28715986000103",
    "municipio": "AMPARO DE SAO FRANCISCO",
    "estado": "SE",
    "dataCompra": "2026-07-14",
    "codigoCatmat": "268252",
    "descricaoItem": "DIPIRONA SÓDICA, DOSAGEM:500 MG/ML, APRESENTAÇÃO:SOLUÇÃO INJETÁVEL",
    "unidadeFornecimento": "AMPOLA",
    "capacidade": 200.0,
    "unidadeMedidaCapacidade": "AMPOLA 2,00 ML",
    "siglaUnidadeMedida": "ML",
    "generico": "N",
    "registroAnvisa": "1108500180048",
    "modalidade": "Pregão",
    "cnpjFornecedor": "08778201000126",
    "nomeFornecedor": "DROGAFONTE LTDA",
    "cnpjFabricante": "06628333000146",
    "nomeFabricante": "FARMACE - INDUSTRIA QUIMICO-FARMACEUTICA CEARENSE LTDA",
    "quantidade": 166470,
    "precoUnitario": 0.549,
    "precoTotal": 91392.03,
    "esfera": "MUNICIPAL",
}


async def test_exige_catmat_ou_cnpj_e_explica_por_que():
    """Sem filtro, a origem recusa. A mensagem precisa dizer o que fazer."""
    with pytest.raises(ValueError) as erro:
        await buscar_precos_saude_bps()
    assert "descobrir_codigo_catalogo" in str(erro.value)


@patch(_PATCH, new_callable=AsyncMock)
async def test_formata_campos_essenciais(mock):
    mock.side_effect = [[_REGISTRO], []]
    r = await buscar_precos_saude_bps(codigo_catmat="268252")

    reg = r["registros"][0]
    assert reg["preco_unitario"] == 0.549
    assert reg["comprador"]["uf"] == "SE"
    assert reg["comprador"]["esfera"] == "MUNICIPAL"
    assert reg["registro_anvisa"] == "1108500180048"


@patch(_PATCH, new_callable=AsyncMock)
async def test_fornecedor_e_fabricante_ficam_separados(mock):
    """Quando diferem, há revenda no meio — e isso muda a leitura do preço.

    O Compras.gov.br não faz essa distinção; achatá-la aqui perderia
    informação que a origem oferece de graça.
    """
    mock.side_effect = [[_REGISTRO], []]
    reg = (await buscar_precos_saude_bps(codigo_catmat="268252"))["registros"][0]

    assert reg["fornecedor"]["nome"] == "DROGAFONTE LTDA"
    assert reg["fabricante"]["nome"].startswith("FARMACE")
    assert reg["fornecedor"]["cnpj"] != reg["fabricante"]["cnpj"]


@patch(_PATCH, new_callable=AsyncMock)
async def test_preserva_o_trio_que_decide_comparabilidade(mock):
    """`unidadeFornecimento` sozinha não permite comparar.

    "AMPOLA" não diz de quantos ml. Sem `capacidade` e
    `unidadeMedidaCapacidade`, preços de embalagens diferentes seriam somados
    como se fossem a mesma coisa — o erro que converter_para_unidade_base
    existe para evitar.
    """
    mock.side_effect = [[_REGISTRO], []]
    reg = (await buscar_precos_saude_bps(codigo_catmat="268252"))["registros"][0]

    assert reg["unidade_fornecimento"] == "AMPOLA"
    assert reg["capacidade"] == 200.0
    assert reg["unidade_medida_capacidade"] == "AMPOLA 2,00 ML"


@patch(_PATCH, new_callable=AsyncMock)
async def test_nunca_afirma_cobertura_completa(mock):
    """A origem não devolve total — então completude não é afirmável.

    Sem esta declaração, uma lista curta se lê como "é só isso que existe",
    que é precisamente o falso negativo que este projeto combate.
    """
    mock.side_effect = [[_REGISTRO], []]
    r = await buscar_precos_saude_bps(codigo_catmat="268252")

    assert r["cobertura"]["completude_verificavel"] is False
    assert r["cobertura"]["total_no_universo"] is None
    assert any("NÃO é possível afirmar" in a for a in r["avisos"])


@patch(_PATCH, new_callable=AsyncMock)
async def test_pagina_curta_nao_encerra_a_varredura(mock):
    """Só página VAZIA é fim.

    Tratar "página menor que a pedida" como fim já encerrou varreduras cedo
    demais duas vezes neste projeto (no PNCP e nas atas do Compras.gov.br).
    Aqui a origem sequer informa o total, então essa heurística seria ainda
    mais cega.
    """
    mock.side_effect = [[_REGISTRO], [_REGISTRO], []]
    r = await buscar_precos_saude_bps(codigo_catmat="268252", limite=50)

    assert r["quantidade_retornada"] == 2
    assert r["cobertura"]["paginas_lidas"] == 3
    assert mock.await_count == 3


@patch(_PATCH, new_callable=AsyncMock)
async def test_nao_envia_ordenacao(mock):
    """`ordenacao` destrói a ordem padrão sem produzir erro.

    Medido em 2026-08-27: três valores distintos devolveram saída idêntica e
    não ordenada, E trocaram o conjunto de resultados. A ordem padrão (por
    dataCompra, decrescente) só se mantém quando o parâmetro é omitido.
    """
    mock.side_effect = [[], []]
    await buscar_precos_saude_bps(codigo_catmat="268252")
    assert "ordenacao" not in mock.await_args.kwargs


@patch(_PATCH, new_callable=AsyncMock)
async def test_vazio_orienta_a_conferir_a_classe_do_catmat(mock):
    """Foi assim que a primeira consulta real falhou.

    "DIPIRONA SÓDICA" existe na classe 6810 (padrão analítico de laboratório),
    na 6509 (veterinário) e na 6505 (medicamentos). A consulta com o código da
    6810 voltou vazia — e vazio, sem explicação, se lê como "não há compras".
    """
    mock.side_effect = [[], []]
    r = await buscar_precos_saude_bps(codigo_catmat="403422")

    assert r["quantidade_retornada"] == 0
    assert any("6505" in a and "6810" in a for a in r["avisos"])


@patch(_PATCH, new_callable=AsyncMock)
async def test_limite_respeitado_e_declarado(mock):
    mock.side_effect = [[_REGISTRO] * 5, []]
    r = await buscar_precos_saude_bps(codigo_catmat="268252", limite=3)

    assert r["quantidade_retornada"] == 3
    assert "limite" in r["cobertura"]["motivo_fim"]


@patch(_PATCH, new_callable=AsyncMock)
async def test_aviso_de_escopo_sempre_presente(mock):
    mock.side_effect = [[], []]
    r = await buscar_precos_saude_bps(codigo_catmat="268252")
    assert any("MEDICAMENTOS e DISPOSITIVOS MÉDICOS" in a for a in r["avisos"])


def test_aceita_os_dois_formatos_de_data():
    """As demais tools usam AAAAMMDD; a origem exige AAAA-MM-DD.

    Converter num lugar só evita que o usuário tenha de lembrar qual formato
    vale para qual fonte.
    """
    assert _iso("20260714") == "2026-07-14"
    assert _iso("2026-07-14") == "2026-07-14"
    assert _iso(None) is None


@patch(_PATCH, new_callable=AsyncMock)
async def test_data_convertida_chega_ao_cliente(mock):
    mock.side_effect = [[], []]
    await buscar_precos_saude_bps(codigo_catmat="268252", data_inicio="20260101")
    assert mock.await_args.kwargs["data_compra_inicio"] == "2026-01-01"
