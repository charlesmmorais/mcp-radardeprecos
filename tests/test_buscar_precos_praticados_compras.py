"""Testes da tool buscar_precos_praticados_compras, com o cliente Compras.gov.br mockado."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.buscar_precos_praticados_compras import (
    _capacidade_texto,
    _rotulo_unidade,
    _texto,
    buscar_precos_praticados_compras,
)

# ---------------------------------------------------------------------------
# Regressão de 2026-09-04 — CATMAT 267203 e 268252 (dipirona sódica).
#
# A ferramenta falhava por completo nesses itens com
# `'float' object has no attribute 'strip'`: o código assumia que
# `capacidade` era texto, e a API do Compras.gov.br a devolve como NÚMERO
# quando há capacidade real.
#
# O defeito ficou escondido porque a origem usa `capacidade: 0` para unidades
# sem capacidade ("UNIDADE", "SERVIÇO"), e zero é FALSO em Python: `0 or ""`
# devolve `""`, e o `.strip()` funcionava. O erro se escondia justamente onde
# o campo é irrelevante e disparava justamente onde ele é essencial para
# comparar preços — embalagens (ampola, caixa, pacote).
# ---------------------------------------------------------------------------


def test_capacidade_numerica_nao_derruba_a_ferramenta():
    """O caso que quebrou em produção (dipirona, ampola de 200 ml)."""
    preco = {"unidade_fornecimento": {"nome": "AMPOLA", "capacidade": 200.0}}
    assert _rotulo_unidade(preco) == "AMPOLA 200"


def test_capacidade_zero_continua_fora_do_rotulo():
    """O rótulo do notebook é "UNIDADE", não "UNIDADE 0".

    Registro real: `{"sigla": "UN", "nome": "UNIDADE", "capacidade": 0}`. O
    zero significa ausência de capacidade e não distingue nada; incluí-lo
    criaria um balde de agrupamento diferente para a mesma unidade.

    Este teste existe porque a primeira versão da correção quebrava isto: ao
    converter tudo para texto, `0` viraria `"0"` e TODOS os rótulos mudariam
    — uma regressão silenciosa em cima de um conserto.
    """
    preco = {"unidade_fornecimento": {"sigla": "UN", "nome": "UNIDADE", "capacidade": 0}}
    assert _rotulo_unidade(preco) == "UNIDADE"
    assert _capacidade_texto(0) == ""
    assert _capacidade_texto(0.0) == ""


def test_capacidade_inteira_nao_ganha_casa_decimal():
    """200.0 vira "200", não "200.0".

    O rótulo é lido por pessoas e agrupa a série. A casa decimal vazia sugere
    precisão que a origem não declarou, e criaria dois baldes distintos para a
    mesma unidade se um registro viesse como texto ("200") e outro como
    número (200.0).
    """
    assert _texto(200.0) == "200"
    assert _texto(2.5) == "2.5"


def test_unidade_como_texto_puro_e_aceita():
    """A origem já devolveu a unidade fora de um objeto em alguns itens."""
    assert _rotulo_unidade({"unidade_fornecimento": "CAIXA"}) == "CAIXA"


def test_unidade_ausente_devolve_None_e_nao_um_rotulo():
    """Mudou na v0.5.5, e a mudança é o conserto de um defeito.

    Antes, unidade desconhecida virava a string "(unidade não informada)".
    Como toda a série sem unidade produzia o MESMO rótulo, a contagem dava
    uma unidade distinta e `serie_homogenea` saía `True` — ausência total de
    informação apresentada como uniformidade. Agora o desconhecido é `None` e
    é contado à parte (ver `test_serie_sem_unidade_...` em
    tests/test_regressoes_bateria_v074.py).
    """
    assert _rotulo_unidade({}) is None
    assert _rotulo_unidade({"unidade_fornecimento": {}}) is None


def test_unidade_de_servico_cai_para_unidade_medida():
    """CATSER traz a unidade em `unidade_medida`; `unidade_fornecimento` é nulo."""
    assert _rotulo_unidade(
        {"unidade_fornecimento": None, "unidade_medida": {"sigla": "UST"}}
    ) == "UST"


def test_nome_numerico_tambem_e_tolerado():
    """Nenhum campo da unidade tem tipo garantido pela origem."""
    preco = {"unidade_fornecimento": {"nome": 12, "capacidade": "UN"}}
    assert _rotulo_unidade(preco) == "12 UN"

REGISTRO_MATERIAL = {
    "precoUnitario": 3299.0,
    "quantidade": 10,
    "niFornecedor": "11222333000144",
    "nomeFornecedor": "Fornecedor Vencedor Ltda",
    "marca": "MarcaX",
    "nomeOrgao": "Órgão Teste",
    "codigoUasg": "925943",
    "nomeUasg": "UASG Teste",
    "estado": "SP",
    "municipio": "São Paulo",
    "dataResultado": "2026-01-10",
    "descricaoDetalhadaItem": "Notebook 16GB RAM",
    "idCompra": 123456,
}

REGISTRO_SERVICO = {
    "precoUnitario": 150.0,
    "quantidade": 1,
    "niFornecedor": "99888777000166",
    "nomeFornecedor": "Serviço Vencedor Ltda",
    "marca": None,
    "nomeOrgao": "Órgão Teste 2",
    "codigoUasg": "925944",
    "nomeUasg": "UASG Teste 2",
    "estado": "DF",
    "municipio": "Brasília",
    "dataResultado": "2026-02-05",
    "descricaoItem": "Manutenção de ar condicionado",
    "idCompra": 654321,
}


async def test_buscar_precos_praticados_compras_rejeita_tipo_item_invalido():
    with pytest.raises(ValueError):
        await buscar_precos_praticados_compras(150912, "invalido")


async def test_rejeita_pdm_com_servico():
    # v0.3.18: PDM só existe em material; PDM + serviço é erro de validação.
    with pytest.raises(ValueError, match="PDM"):
        await buscar_precos_praticados_compras(
            17708, "servico", tipo_codigo="codigoPdm"
        )


async def test_rejeita_tipo_codigo_invalido():
    with pytest.raises(ValueError, match="tipo_codigo"):
        await buscar_precos_praticados_compras(
            150912, "material", tipo_codigo="qualquer"
        )


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_busca_por_pdm_material_envia_tipo_codigo(mock_material):
    # Busca por PDM: a tool
    # deve repassar tipo_codigo="codigoPdm" ao cliente.
    mock_material.return_value = {"resultado": [], "totalRegistros": 0}
    resultado = await buscar_precos_praticados_compras(
        17708, "material", tipo_codigo="codigoPdm"
    )
    assert resultado["tipo_codigo"] == "codigoPdm"
    _, kwargs = mock_material.call_args
    assert kwargs["tipo_codigo"] == "codigoPdm"


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_padrao_e_por_item(mock_material):
    mock_material.return_value = {"resultado": [], "totalRegistros": 0}
    resultado = await buscar_precos_praticados_compras(267203, "material")
    assert resultado["tipo_codigo"] == "codigoItemCatalogo"
    _, kwargs = mock_material.call_args
    assert kwargs["tipo_codigo"] == "codigoItemCatalogo"


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_buscar_precos_praticados_compras_material_mapeia_campos(mock_material):
    mock_material.return_value = {
        "resultado": [REGISTRO_MATERIAL],
        "totalRegistros": 1,
    }

    resultado = await buscar_precos_praticados_compras(150912, "material", uf="SP")

    assert resultado["tipo_item"] == "material"
    assert resultado["codigo_item_catalogo"] == 150912
    assert resultado["total_encontrado"] == 1
    assert resultado["quantidade_retornada"] == 1
    preco = resultado["precos"][0]
    assert preco["preco_unitario"] == 3299.0
    assert preco["quantidade"] == 10
    assert preco["fornecedor"] == {
        "cnpj": "11222333000144",
        "nome": "Fornecedor Vencedor Ltda",
    }
    assert preco["marca"] == "MarcaX"
    assert preco["orgao"] == "Órgão Teste"
    assert preco["uasg"] == {"codigo": "925943", "nome": "UASG Teste"}
    assert preco["uf"] == "SP"
    assert preco["municipio"] == "São Paulo"
    assert preco["data_resultado"] == "2026-01-10"
    assert preco["descricao_item"] == "Notebook 16GB RAM"
    # v0.6.3: identificador passou a sair como TEXTO. Um `id_compra` de 17
    # dígitos não sobrevive à camada de transporte do MCP, que trata todo
    # número como double — 37 de 86 valores reais perdiam precisão. O tipo
    # é texto SEMPRE, e não só quando o valor é grande: tipo que depende da
    # magnitude impede quem consome de escrever código correto.
    assert preco["id_compra"] == "123456"
    mock_material.assert_awaited_once()
    _, kwargs = mock_material.call_args
    assert kwargs["estado"] == "SP"
    assert kwargs["data_resultado"] is True
    assert kwargs["tamanho_pagina"] == 20
    assert kwargs["pagina"] == 1


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_servico",
    new_callable=AsyncMock,
)
async def test_buscar_precos_praticados_compras_servico_usa_endpoint_correto_e_corta_no_limite(
    mock_servico,
):
    mock_servico.return_value = {
        "resultado": [REGISTRO_SERVICO] * 12,
        "totalRegistros": 12,
    }

    # v0.5.14: era `limite=2`, e o teste afirmava `tamanho_pagina == 2`. Isso
    # codificava o defeito: o cliente aplica `max(10, ...)`, então o 2 nunca
    # chegava à fonte — o mock é que o deixava passar. Um valor dentro da faixa
    # real preserva a intenção do teste (o limite VIRA o tamanho de página) sem
    # afirmar um contrato que a fonte não honra.
    resultado = await buscar_precos_praticados_compras(9999, "servico", limite=11)

    assert resultado["tipo_item"] == "servico"
    assert resultado["total_encontrado"] == 12
    assert resultado["quantidade_retornada"] == 11
    preco = resultado["precos"][0]
    assert preco["preco_unitario"] == 150.0
    assert preco["marca"] is None
    assert preco["descricao_item"] == "Manutenção de ar condicionado"
    mock_servico.assert_awaited_once()
    _, kwargs = mock_servico.call_args
    # Achado real (2026-07-10): /3_consultarServico ACEITA tamanhoPagina
    # (corrige suposição anterior deste projeto de que não aceitava) —
    # confirmado ao vivo com codigoItemCatalogo=27332/tamanhoPagina=100.
    assert kwargs["tamanho_pagina"] == 11


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_buscar_precos_praticados_compras_apenas_com_resultado_false_nao_filtra_data(
    mock_material,
):
    mock_material.return_value = {"resultado": [], "totalRegistros": 0}

    await buscar_precos_praticados_compras(150912, "material", apenas_com_resultado=False)

    _, kwargs = mock_material.call_args
    assert kwargs["data_resultado"] is None


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_servico",
    new_callable=AsyncMock,
)
async def test_buscar_precos_praticados_compras_repassa_pagina(mock_servico):
    # Achado real (2026-07-10, usuário): a API pagina normalmente
    # (pagina=1,2,... com tamanhoPagina até 500) mas NÃO garante ordenação
    # por data — uma pesquisa exaustiva precisa iterar pagina e consolidar
    # antes de filtrar por período. Confirmado ao vivo com
    # codigoItemCatalogo=27332 (859 registros no total).
    mock_servico.return_value = {"resultado": [], "totalRegistros": 859}

    resultado = await buscar_precos_praticados_compras(27332, "servico", limite=100, pagina=3)

    _, kwargs = mock_servico.call_args
    assert kwargs["pagina"] == 3
    assert kwargs["tamanho_pagina"] == 100
    assert resultado["pagina"] == 3
    assert resultado["total_encontrado"] == 859


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_buscar_precos_praticados_compras_pagina_minima_e_1(mock_material):
    mock_material.return_value = {"resultado": [], "totalRegistros": 0}

    resultado = await buscar_precos_praticados_compras(150912, "material", pagina=0)

    _, kwargs = mock_material.call_args
    assert kwargs["pagina"] == 1
    assert resultado["pagina"] == 1


# --- incluir_bruto opt-in ---


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_incluir_bruto_false_por_padrao_nao_inclui_dados_originais(mock_material):
    mock_material.return_value = {"resultado": [REGISTRO_MATERIAL], "totalRegistros": 1}
    resultado = await buscar_precos_praticados_compras(150912, "material")
    assert "dados_originais" not in resultado["precos"][0]


@patch(
    "mcp_radardeprecos.tools.buscar_precos_praticados_compras.compras_client.consultar_precos_material",
    new_callable=AsyncMock,
)
async def test_incluir_bruto_true_inclui_dados_originais(mock_material):
    mock_material.return_value = {"resultado": [REGISTRO_MATERIAL], "totalRegistros": 1}
    resultado = await buscar_precos_praticados_compras(150912, "material", incluir_bruto=True)
    assert resultado["precos"][0]["dados_originais"] == REGISTRO_MATERIAL


# --- v0.4.7: unidade de fornecimento preservada e mistura sinalizada ---

def _registro(preco: float, unidade: str, capacidade: str | None) -> dict:
    """Registro cru do Compras.gov.br com a unidade praticada."""
    return {
        **REGISTRO_MATERIAL,
        "precoUnitario": preco,
        "siglaUnidadeFornecimento": unidade[:3].upper(),
        "nomeUnidadeFornecimento": unidade,
        "capacidadeUnidadeFornecimento": capacidade,
        "siglaUnidadeMedida": "UN",
        "nomeUnidadeMedida": "UNIDADE",
        "codigoPdm": 4321,
        "nomePdm": "GUARDANAPO DE PAPEL",
        "codigoClasse": 7530,
        "nomeClasse": "ARTIGOS DE PAPEL",
        "criterioJulgamento": "MENOR PRECO",
        "percentualMaiorDesconto": None,
    }


async def test_preco_preserva_unidade_pdm_e_classe():
    """Os campos de normalização vinham da API e eram descartados até a v0.4.6."""
    resposta = {"resultado": [_registro(0.60, "UNIDADE", None)], "totalRegistros": 1}
    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(return_value=resposta),
    ):
        r = await buscar_precos_praticados_compras(27332, "material")

    preco = r["precos"][0]
    assert preco["unidade_fornecimento"] == {
        "sigla": "UNI", "nome": "UNIDADE", "capacidade": None,
    }
    assert preco["unidade_medida"] == {"sigla": "UN", "nome": "UNIDADE"}
    assert preco["pdm"] == {"codigo": 4321, "nome": "GUARDANAPO DE PAPEL"}
    assert preco["classe"] == {"codigo": 7530, "nome": "ARTIGOS DE PAPEL"}
    assert preco["criterio_julgamento"] == "MENOR PRECO"


async def test_serie_homogenea_nao_gera_aviso_de_mistura():
    resposta = {
        "resultado": [_registro(0.60, "UNIDADE", None), _registro(0.55, "UNIDADE", None)],
        "totalRegistros": 2,
    }
    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(return_value=resposta),
    ):
        r = await buscar_precos_praticados_compras(27332, "material")

    assert r["unidades"]["serie_homogenea"] is True
    assert r["unidades"]["unidades_distintas"] == 1
    assert not any("NÃO homogênea" in a for a in r["avisos"])


async def test_mistura_de_unidades_e_sinalizada():
    """Caso real: mesmo CATMAT com unidade, pacote com 50 e caixa."""
    resposta = {
        "resultado": [
            _registro(0.60, "UNIDADE", None),
            _registro(21.01, "PACOTE", "50 UN"),
            _registro(153.90, "CAIXA", "45 PACOTES"),
        ],
        "totalRegistros": 3,
    }
    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(return_value=resposta),
    ):
        r = await buscar_precos_praticados_compras(27332, "material")

    unidades = r["unidades"]
    assert unidades["serie_homogenea"] is False
    assert unidades["unidades_distintas"] == 3
    assert unidades["contagem_por_unidade"]["PACOTE 50 UN"] == 1
    assert any("NÃO homogênea" in a for a in r["avisos"])


async def test_capacidade_distingue_pacotes_diferentes():
    """'PACOTE' sozinho não identifica a unidade: 50 e 100 são grandezas distintas."""
    resposta = {
        "resultado": [
            _registro(21.01, "PACOTE", "50 UN"),
            _registro(38.00, "PACOTE", "100 UN"),
        ],
        "totalRegistros": 2,
    }
    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(return_value=resposta),
    ):
        r = await buscar_precos_praticados_compras(27332, "material")

    assert r["unidades"]["unidades_distintas"] == 2


async def test_unidade_ausente_nao_quebra_o_mapeamento():
    """Fontes antigas/sem os campos continuam funcionando (degradação suave)."""
    resposta = {"resultado": [REGISTRO_SERVICO], "totalRegistros": 1}
    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_servico",
        new=AsyncMock(return_value=resposta),
    ):
        r = await buscar_precos_praticados_compras(999, "servico")

    preco = r["precos"][0]
    assert preco["unidade_fornecimento"] == {"sigla": None, "nome": None, "capacidade": None}
    # `None`, não `True`: sem unidade informada não se sabe se a série é
    # homogênea. A asserção anterior (`is True`) codificava o defeito
    # corrigido na v0.5.5.
    assert r["unidades"]["serie_homogenea"] is None
    assert r["unidades"]["registros_sem_unidade"] == 1
    assert any("INDETERMINADA" in a for a in r["avisos"])


# ===========================================================================
# v0.5.13 — a intermitência do defeito de capacidade numérica
# ===========================================================================
#
# O relato de 08/09/2026: o CATMAT 267203 falhou numa tentativa e funcionou na
# seguinte; o 435624 falhou duas vezes, mas funcionou com `limite=20` e sem
# `buscar_todas_paginas`. A objeção era procedente — "a capacidade deste item
# é numérica" não prediz intermitência, prediz falha constante.
#
# Falta a metade que explica a variação: o defeito é POR REGISTRO, não por
# item. Um único registro com capacidade numérica derruba a chamada inteira, e
# o conjunto de registros que volta muda entre execuções, porque:
#
#   1. sem `buscar_todas_paginas`, só a página 1 é formatada — se o registro
#      ruim está na página 7, ele nunca é tocado (foi o caso do 435624);
#   2. com `buscar_todas_paginas`, o orçamento de tempo interrompe a varredura
#      num ponto que depende da latência da rede. Simulado em 08/09/2026, 20
#      execuções com parâmetros IDÊNTICOS e latência de 0,03-0,30s por página:
#      2 falharam e 18 devolveram resultado parcial.
#
# O corolário incômodo, e a razão de este teste existir: nas 18 execuções que
# "funcionaram", o resultado era PARCIAL. Sucesso e falha não eram dois
# desfechos da mesma consulta — a que funcionou tinha lido menos páginas.


async def test_capacidade_numerica_em_pagina_posterior_nao_derruba_a_varredura():
    """A regressão que só aparece com `buscar_todas_paginas=True`.

    A página 1 é sadia e a 3 traz capacidade numérica. Antes da v0.5.0 esta
    combinação produzia sucesso sem varredura e falha com varredura — a
    assimetria que fazia o defeito parecer intermitente.
    """

    async def api(_codigo, *, tipo_codigo=None, pagina=1, **_kw):
        capacidade = 200.0 if pagina == 3 else 0
        return {
            "resultado": [_registro(1.5, "AMPOLA", capacidade)] * 20,
            "totalRegistros": 100,
        }

    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(side_effect=api),
    ):
        so_pagina_um = await buscar_precos_praticados_compras(267203, "material", limite=20)
        varredura = await buscar_precos_praticados_compras(
            267203, "material", limite=20, buscar_todas_paginas=True
        )

    assert len(so_pagina_um["precos"]) == 20
    assert len(varredura["precos"]) == 100, (
        "a varredura tem de atravessar a página com capacidade numérica"
    )
    # A capacidade numérica vira rótulo legível, sem casa decimal vazia.
    assert "AMPOLA 200" in varredura["unidades"]["contagem_por_unidade"]


# ===========================================================================
# v0.5.14 — dois limites discordando na mesma chamada
# ===========================================================================
#
# Medido ao vivo em 08/09/2026 (CATMAT 267203, `limite=5`): a cobertura
# reportou `registros_examinados: 10` contra `registros_retornados: 5`.
#
# O número estava certo e o desenho é que estava errado. A tool aceitava
# `limite` de 1 a 100; o cliente, logo abaixo, faz
# `tamanho_pagina = max(10, min(tamanho_pagina, 500))`. Pedir 5 buscava 10
# registros da fonte e descartava 5 em silêncio — pagos, trazidos e jogados
# fora. Dois clamps na mesma pilha discordando sobre a faixa válida.
#
# A consequência menos óbvia é aritmética: a varredura calcula
# `ultima = ceil(total / limite)` e anuncia "primeiras 50 páginas
# (50 * limite registros)". Com `limite` abaixo do piso da fonte, esse anúncio
# subestima o que foi realmente lido — um resultado parcial descrito com o
# número errado, que é pior que não descrever.


async def test_limite_abaixo_do_piso_da_fonte_e_elevado_e_avisado():
    """Pedir menos que o piso não pode descartar registros em silêncio."""
    capturado = {}

    async def api(_codigo, *, tipo_codigo=None, pagina=1, tamanho_pagina=10, **_kw):
        capturado["tamanho_pagina"] = tamanho_pagina
        return {
            "resultado": [_registro(1.5, "COMPRIMIDO", 0)] * tamanho_pagina,
            "totalRegistros": 2102,
        }

    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(side_effect=api),
    ):
        r = await buscar_precos_praticados_compras(267203, "material", limite=5)

    assert r["cobertura"]["registros_examinados"] == r["cobertura"]["registros_retornados"], (
        "examinado e retornado só divergem quando registros são lidos e "
        "descartados — e descartar em silêncio é o defeito"
    )
    assert r["quantidade_retornada"] == 10
    assert any("limite" in a and "10" in a for a in r["avisos"])


async def test_limite_dentro_da_faixa_nao_gera_aviso_nem_divergencia():
    """Controle: o caso normal não pode ganhar ruído por causa da correção."""

    async def api(_codigo, *, tipo_codigo=None, pagina=1, tamanho_pagina=10, **_kw):
        return {
            "resultado": [_registro(1.5, "COMPRIMIDO", 0)] * tamanho_pagina,
            "totalRegistros": 2102,
        }

    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(side_effect=api),
    ):
        r = await buscar_precos_praticados_compras(267203, "material", limite=20)

    assert r["quantidade_retornada"] == 20
    assert r["cobertura"]["registros_examinados"] == 20
    assert not any("elevado" in a for a in r["avisos"])
