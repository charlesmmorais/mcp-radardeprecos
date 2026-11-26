"""Tela MCP Apps de avaliar_pesquisa_mercado: declaração no servidor e conteúdo."""
from __future__ import annotations

import re

from mcp_radardeprecos import server as srv


async def test_resource_da_tela_tem_o_mime_do_mcp_apps():
    recursos = {str(r.uri): r for r in await srv.mcp.list_resources()}
    tela = recursos[srv.TELA_AVALIACAO_URI]
    assert tela.mimeType == "text/html;profile=mcp-app"
    assert tela.meta == {"ui": {"prefersBorder": True}}


async def test_tool_aponta_para_a_tela_nas_duas_formas():
    tools = {t.name: t for t in await srv.mcp.list_tools()}
    meta = tools["avaliar_pesquisa_mercado"].meta
    assert meta["ui"]["resourceUri"] == srv.TELA_AVALIACAO_URI
    assert meta["ui/resourceUri"] == srv.TELA_AVALIACAO_URI
    # As outras tools não ganham tela.
    assert tools["calcular_preco_referencia"].meta is None


async def _html() -> str:
    conteudo = list(await srv.mcp.read_resource(srv.TELA_AVALIACAO_URI))
    assert conteudo[0].mime_type == "text/html;profile=mcp-app"
    return conteudo[0].content


async def test_tela_tem_titulo_subtitulo_e_credito():
    html = await _html()
    assert "<h1>Avaliação de pesquisa de mercado</h1>" in html
    assert "Método do Manual de Pesquisa de Preços" in html
    assert "Baseado na planilha de Avaliação de pesquisa de mercado do STJ" in html
    # O STJ só aparece no crédito.
    assert html.count("STJ") == 1


async def test_tela_e_autocontida():
    """O CSP padrão do MCP Apps bloqueia rede: nada pode vir de fora."""
    html = await _html()
    assert not re.search(r"""(src|href)\s*=\s*["']https?:""", html)
    assert "@import" not in html
    assert "fetch(" not in html


async def test_tela_conversa_pelo_protocolo_do_mcp_apps():
    html = await _html()
    for metodo in ("ui/initialize", "ui/notifications/initialized", "tools/call",
                   "ui/notifications/tool-result", "ui/message", "ui/download-file"):
        assert f'"{metodo}"' in html
    assert '"2026-01-26"' in html
    assert '"gerar_pdf_avaliacao_pesquisa_mercado"' in html  # botão Gerar PDF
    assert "e.source !== window.parent" in html


async def test_tela_oferece_os_tipos_de_fonte_da_tool():
    from mcp_radardeprecos.tools.avaliar_pesquisa_mercado import TIPOS_DE_FONTE

    html = await _html()
    tipos = re.search(r"var TIPOS = \[(.*?)\];", html, re.S).group(1)
    assert sorted(re.findall(r'"([^"]+)"', tipos)) == sorted(TIPOS_DE_FONTE)
    assert "COMPRASNET" not in tipos
