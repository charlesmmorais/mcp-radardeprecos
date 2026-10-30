"""Testes da impressão digital do catálogo, e do invariante da especificação.

Substituem `test_list_changed.py`, removido na v0.5.10 junto com a
notificação. O teste central aqui é o invariante normativo que a v0.5.8
violava: **``tools/list`` não pode variar como efeito colateral de outra
requisição na conexão**. Chamar uma tool não altera o catálogo.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp_radardeprecos import server
from mcp_radardeprecos.catalogo import descrever_catalogo


def _tool(nome, descricao="d", parametros=None):
    return SimpleNamespace(
        name=nome, description=descricao, parameters=parametros or {"type": "object"}
    )


# --- Invariante da especificação -------------------------------------------


async def test_chamar_uma_tool_nao_altera_o_catalogo():
    """O invariante que a v0.5.8 violava.

    A especificação determina que o conjunto de `tools/list` não varie como
    efeito colateral de outras requisições. A v0.5.8 disparava
    `notifications/tools/list_changed` na primeira chamada de cada sessão, o
    que fazia o cliente invalidar a lista recém-carregada — e produzia
    `Resource not found` até a redescoberta.
    """
    antes = descrever_catalogo(await server.mcp.list_tools())
    with patch(
        "mcp_radardeprecos.tools.classificar_objeto_tic.classificar_objeto_tic",
        new=AsyncMock(return_value={}),
    ):
        await server.obter_diretrizes_pesquisa_precos()
    depois = descrever_catalogo(await server.mcp.list_tools())
    assert antes["digest"] == depois["digest"]
    assert antes["tools_count"] == depois["tools_count"]


async def test_o_servidor_nao_anuncia_que_notifica_mudanca():
    """Removido na v0.5.10, e o padrão do SDK volta a valer.

    Anunciar `listChanged: true` sem nunca notificar autorizaria o cliente a
    cachear confiando num aviso que não vem. Como o conjunto de tools deste
    servidor é fixo no import, a notificação correta nunca dispararia — então
    a declaração honesta é `False`.
    """
    opcoes = server.mcp._mcp_server.create_initialization_options()
    assert opcoes.capabilities.tools.listChanged is False


def test_a_versao_declarada_continua_sendo_a_nossa():
    """Guarda de regressão: o FastMCP não aceita `version=`.

    Sem o remendo em `mcp._mcp_server.version`, o handshake cai no fallback
    `pkg_version("mcp")` e todo cliente vê a versão do SDK. A remoção do
    embrulho de `create_initialization_options` na v0.5.10 não pode ter
    levado essa correção junto.
    """
    opcoes = server.mcp._mcp_server.create_initialization_options()
    assert opcoes.server_version == server.__version__


# --- Digest ----------------------------------------------------------------


def test_digest_e_estavel_entre_chamadas():
    tools = [_tool("b"), _tool("a")]
    assert descrever_catalogo(tools)["digest"] == descrever_catalogo(tools)["digest"]


def test_digest_independe_da_ordem_de_registro():
    """Sem ordenar, dois processos com o MESMO catálogo divergiriam.

    E a comparação — única razão de o campo existir — acusaria diferença onde
    não há, que é o modo de falha mais caro num verificador.
    """
    a = descrever_catalogo([_tool("x"), _tool("y")])
    b = descrever_catalogo([_tool("y"), _tool("x")])
    assert a["digest"] == b["digest"]
    assert a["tools"] == b["tools"] == ["x", "y"]


def test_tool_nova_muda_o_digest():
    base = descrever_catalogo([_tool("x")])
    nova = descrever_catalogo([_tool("x"), _tool("y")])
    assert base["digest"] != nova["digest"]


def test_mudanca_de_schema_muda_o_digest():
    """O caso mais traiçoeiro: mesmo nome, contrato diferente.

    Um cliente com cache continuaria chamando com o schema antigo — e nada
    acusaria, porque a contagem e os nomes seriam idênticos.
    """
    antes = descrever_catalogo([_tool("x", parametros={"type": "object"})])
    depois = descrever_catalogo(
        [_tool("x", parametros={"type": "object", "required": ["novo"]})]
    )
    assert antes["tools"] == depois["tools"]
    assert antes["tools_count"] == depois["tools_count"]
    assert antes["digest"] != depois["digest"]


def test_mudanca_de_descricao_muda_o_digest():
    """A descrição muda a decisão do modelo sobre quando chamar a tool."""
    antes = descrever_catalogo([_tool("x", descricao="busca preços")])
    depois = descrever_catalogo([_tool("x", descricao="busca preços e atas")])
    assert antes["digest"] != depois["digest"]


async def test_rota_raiz_expoe_o_catalogo_fora_do_protocolo():
    """É o ponto do módulo: verificável por `curl`, imune a cache de cliente."""
    import json

    resposta = await server.health_check(None)
    corpo = json.loads(bytes(resposta.body).decode("utf-8"))
    assert corpo["catalogo"]["tools_count"] == len(await server.mcp.list_tools())
    assert "digest" in corpo["catalogo"]
    assert "contar_pncp" in corpo["catalogo"]["tools"]
