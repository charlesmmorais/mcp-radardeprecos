"""Testes de `_parse_args`/`main` — seleção de transporte MCP.

Cobre o comportamento de compatibilidade que motivou a mudança: sem
argumentos, o servidor tem que continuar em stdio (Claude Desktop não muda
nada na config); com --transport/variável de ambiente, o mesmo servidor
pode subir em HTTP (sse/streamable-http), para uso com clientes que não
suportam stdio (ex.: ChatGPT via túnel).

Não chamamos `mcp.run()` de verdade em nenhum teste (subiria um servidor de
fato) — `main()` é testado com `mcp.run` mockado.
"""
from __future__ import annotations

import json
from importlib.metadata import version as pkg_version
from unittest.mock import patch

import httpx
import pytest
from mcp.server.transport_security import TransportSecuritySettings

from mcp_radardeprecos import __version__, observability, server


def test_parse_args_default_e_stdio_sem_variavel_de_ambiente(monkeypatch):
    monkeypatch.delenv("RADARDEPRECOS_TRANSPORT", raising=False)
    args = server._parse_args([])
    assert args.transport == "stdio"
    assert args.host is None
    assert args.port is None


def test_parse_args_aceita_transport_explicito():
    for transporte in server._TRANSPORTES_VALIDOS:
        args = server._parse_args(["--transport", transporte])
        assert args.transport == transporte


def test_parse_args_rejeita_transport_desconhecido_via_cli():
    with pytest.raises(SystemExit):
        server._parse_args(["--transport", "bogus"])


def test_parse_args_version_imprime_a_versao(capsys):
    with pytest.raises(SystemExit) as saida:
        server._parse_args(["--version"])
    assert saida.value.code == 0
    assert capsys.readouterr().out.strip() == f"mcp-radardeprecos {__version__}"


def test_parse_args_le_host_e_port():
    args = server._parse_args(["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9001"])
    assert args.host == "0.0.0.0"
    assert args.port == 9001


def test_parse_args_usa_variavel_de_ambiente_como_default(monkeypatch):
    monkeypatch.setenv("RADARDEPRECOS_TRANSPORT", "sse")
    args = server._parse_args([])
    assert args.transport == "sse"


def test_parse_args_cli_tem_prioridade_sobre_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("RADARDEPRECOS_TRANSPORT", "sse")
    args = server._parse_args(["--transport", "streamable-http"])
    assert args.transport == "streamable-http"


def test_main_sem_argumentos_roda_stdio_e_nao_mexe_em_host_port(monkeypatch):
    monkeypatch.delenv("RADARDEPRECOS_TRANSPORT", raising=False)
    host_original = server.mcp.settings.host
    port_original = server.mcp.settings.port
    with patch.object(server.mcp, "run") as mock_run:
        server.main([])
    mock_run.assert_called_once_with(transport="stdio")
    assert server.mcp.settings.host == host_original
    assert server.mcp.settings.port == port_original


def test_main_com_transport_streamable_http_repassa_para_run_http():
    # Desde a v0.1.42, transportes HTTP não chamam mcp.run() diretamente —
    # main() delega para _run_http(), que envolve o app ASGI com
    # RateLimitMiddleware antes de subir o uvicorn (ver rate_limit.py).
    with patch.object(server, "_run_http") as mock_run_http:
        server.main(["--transport", "streamable-http"])
    mock_run_http.assert_called_once_with("streamable-http", 60)


def test_main_repassa_rate_limit_configurado_para_run_http(monkeypatch):
    monkeypatch.delenv("RADARDEPRECOS_RATE_LIMIT_PER_MINUTE", raising=False)
    with patch.object(server, "_run_http") as mock_run_http:
        server.main(["--transport", "sse", "--rate-limit-por-minuto", "10"])
    mock_run_http.assert_called_once_with("sse", 10)


def test_main_aplica_host_e_port_quando_informados():
    host_original = server.mcp.settings.host
    port_original = server.mcp.settings.port
    try:
        with patch.object(server, "_run_http"):
            server.main(["--transport", "sse", "--host", "0.0.0.0", "--port", "9002"])
        assert server.mcp.settings.host == "0.0.0.0"
        assert server.mcp.settings.port == 9002
    finally:
        server.mcp.settings.host = host_original
        server.mcp.settings.port = port_original


def test_main_nao_mexe_em_host_port_quando_omitidos():
    host_original = server.mcp.settings.host
    port_original = server.mcp.settings.port
    with patch.object(server, "_run_http"):
        server.main(["--transport", "streamable-http"])
    assert server.mcp.settings.host == host_original
    assert server.mcp.settings.port == port_original


def test_main_valida_transport_invalido_vindo_da_variavel_de_ambiente(monkeypatch):
    # O argparse só valida `choices` para valores vindos de argv — um valor
    # inválido na env var vira o `default` e passa direto pelo parser, então
    # `main` precisa da validação extra para não silenciosamente aceitar.
    monkeypatch.setenv("RADARDEPRECOS_TRANSPORT", "bogus")
    with pytest.raises(ValueError, match="transporte 'bogus' inválido"):
        server.main([])


async def test_health_check_responde_200_na_raiz_do_app_streamable_http():
    # Regressão: o Fly.io Launch (e outros provedores) testam "/" logo após
    # o deploy — sem essa rota, isso dava 404 mesmo com o servidor MCP
    # funcionando normalmente (protocolo real só responde em "/mcp").
    app = server.mcp.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["service"] == "mcp-radardeprecos"
    assert corpo["mcp_endpoint"] == "/mcp"


async def test_health_check_responde_200_na_raiz_do_app_sse():
    app = server.mcp.sse_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


def test_run_http_envolve_app_com_rate_limit_middleware():
    from mcp_radardeprecos.rate_limit import RateLimitMiddleware

    with (
        patch("mcp_radardeprecos.server.uvicorn") as mock_uvicorn,
        patch("mcp_radardeprecos.server.anyio") as mock_anyio,
    ):
        server._run_http("streamable-http", 42)

    mock_uvicorn.Config.assert_called_once()
    app_passado = mock_uvicorn.Config.call_args.args[0]
    assert isinstance(app_passado, RateLimitMiddleware)
    assert app_passado._limiter._limite == 42
    mock_anyio.run.assert_called_once()


def test_run_http_usa_sse_app_quando_transporte_sse():
    with (
        patch.object(server.mcp, "sse_app") as mock_sse_app,
        patch("mcp_radardeprecos.server.uvicorn"),
        patch("mcp_radardeprecos.server.anyio"),
    ):
        server._run_http("sse", 60)

    mock_sse_app.assert_called_once()


def test_run_http_desativa_protecao_dns_rebinding():
    # Regressão: o SDK MCP, por padrão, só aceita Host header de
    # localhost/127.0.0.1 (TransportSecuritySettings.allowed_hosts) — em
    # produção no Fly.io isso rejeitava toda chamada a /mcp com HTTP 421
    # "Invalid Host header", quebrando a conexão com ChatGPT/Claude. Este
    # servidor não tem sessão de navegador para um ataque de DNS rebinding
    # sequestrar, então a proteção é desativada deliberadamente para os
    # transportes HTTP remotos.
    host_original = server.mcp.settings.host
    try:
        with (
            patch("mcp_radardeprecos.server.uvicorn"),
            patch("mcp_radardeprecos.server.anyio"),
        ):
            server._run_http("streamable-http", 60)

        assert server.mcp.settings.transport_security.enable_dns_rebinding_protection is False
    finally:
        server.mcp.settings.host = host_original


async def test_run_http_aceita_host_header_nao_localhost_apos_desativar_protecao():
    # Teste comportamental, direto no app ASGI real (sem mockar uvicorn),
    # simulando o que o Fly.io recebe: um POST em /mcp com Host header do
    # domínio público. Antes da correção, isso devolvia 421 "Invalid Host
    # header" (bug real, confirmado em produção). O session manager do SDK
    # MCP só é inicializado dentro do lifespan do app Starlette (é isso
    # que `mcp.run()`/uvicorn fazem por baixo dos panos), então precisamos
    # entrar no lifespan manualmente para exercitar o fluxo real de uma
    # requisição em /mcp.
    #
    # O SDK cria o StreamableHTTPSessionManager de forma preguiçosa (só na
    # primeira chamada a streamable_http_app()) e o mantém em cache — se
    # outro teste já tiver criado o app antes deste (ex.: os testes de
    # health check acima), `mcp.settings.transport_security` já teria sido
    # "congelado" com o valor padrão. Resetamos o cache para reproduzir a
    # ordem real de produção, em que _run_http() sempre roda antes de
    # qualquer app ser construído.
    server.mcp._session_manager = None
    with (
        patch("mcp_radardeprecos.server.uvicorn") as mock_uvicorn,
        patch("mcp_radardeprecos.server.anyio"),
    ):
        server._run_http("streamable-http", 60)
        app_passado = mock_uvicorn.Config.call_args.args[0]

    # Cadeia: RateLimitMiddleware(base_app) — desembrulha para chegar ao app do FastMCP.
    base_app = app_passado._app
    async with base_app.router.lifespan_context(base_app):
        transport = httpx.ASGITransport(app=app_passado)
        async with httpx.AsyncClient(transport=transport, base_url="https://mcp.exemplo.gov.br") as client:
            resposta = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "teste", "version": "0"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )

    assert resposta.status_code != 421


def test_todos_os_transportes_validos_sao_aceitos_por_main():
    for transporte in server._TRANSPORTES_VALIDOS:
        if transporte == "stdio":
            with patch.object(server.mcp, "run") as mock_run:
                server.main(["--transport", transporte])
            mock_run.assert_called_once_with(transport="stdio")
        else:
            with patch.object(server, "_run_http") as mock_run_http:
                server.main(["--transport", transporte])
            mock_run_http.assert_called_once_with(transporte, 60)


async def test_registro_em_loop_mantem_as_tools_com_docstring():
    # Nome MCP = nome da função; descrição herdada do docstring via wraps.
    tools = await server.mcp.list_tools()
    nomes = [t.name for t in tools]
    assert len(nomes) == 48
    assert nomes[0] == "buscar_pncp_texto"  # ordem de registro preservada
    assert nomes[-1] == "exportar_trilha_auditoria"
    assert nomes == [f.__name__ for f in server._TOOLS]
    assert all(t.description for t in tools), "toda tool herda docstring via wraps"


# Item 13, v0.2.6: observabilidade mínima — o wrapper
# único de _registrar_tool registra chamada/erro/duração em observability.py,
# exposto em metrics no health check.


@pytest.fixture(autouse=True)
def _resetar_metricas_observabilidade():
    observability.resetar()
    yield
    observability.resetar()


async def test_chamar_tool_via_mcp_registra_metrica_de_sucesso():
    # classificar_objeto_tic é pura (sem chamada de rede) — ideal para
    # exercitar o wrapper real de registro sem precisar mockar HTTP.
    await server.mcp.call_tool("classificar_objeto_tic", {"texto": "Licenciamento de software"})

    metricas = observability.obter_metricas()
    assert metricas["classificar_objeto_tic"]["chamadas"] == 1
    assert metricas["classificar_objeto_tic"]["erros"] == 0
    assert metricas["classificar_objeto_tic"]["duracao_media_ms"] >= 0


async def test_chamar_tool_com_erro_via_mcp_registra_metrica_de_erro():
    # texto vazio faz classificar_objeto_tic levantar ValueError — o SDK MCP
    # embrulha em ToolError e repropaga (não engole a exceção); o wrapper
    # de _registrar_tool precisa ter registrado o erro ANTES de repropagar.
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        await server.mcp.call_tool("classificar_objeto_tic", {"texto": ""})

    metricas = observability.obter_metricas()
    assert metricas["classificar_objeto_tic"]["chamadas"] == 1
    assert metricas["classificar_objeto_tic"]["erros"] == 1


async def test_health_check_expoe_metrics_apos_chamada_de_tool():
    await server.mcp.call_tool("classificar_objeto_tic", {"texto": "Licenciamento de software"})

    app = server.mcp.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resposta = await client.get("/")

    corpo = resposta.json()
    assert "metrics" in corpo
    assert corpo["metrics"]["classificar_objeto_tic"]["chamadas"] == 1


async def test_health_check_metrics_vazio_sem_nenhuma_chamada():
    app = server.mcp.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resposta = await client.get("/")

    assert resposta.json()["metrics"] == {}


# --- Auth Entra ID (v0.3.0, itens 5 e 6) ---
#
# Regressão-chave do modo opcional: com entra_auth_habilitado=False (o
# padrão, sem ENTRA_TENANT_ID/ENTRA_CLIENT_ID), nada aqui deveria mudar —
# nem a cadeia de middlewares de _run_http, nem a lista de rotas custom.
# `server.app_settings` é o próprio objeto Settings importado por server.py
# (from .config import settings as app_settings) — dá para substituí-lo por
# um "habilitado" via monkeypatch sem precisar recarregar o módulo inteiro,
# porque _run_http lê app_settings.entra_auth_habilitado em tempo de
# chamada, não em tempo de import.


def test_run_http_sem_entra_habilitado_cadeia_e_so_rate_limit():
    from mcp_radardeprecos.auth.middleware import EntraAuthMiddleware
    from mcp_radardeprecos.rate_limit import RateLimitMiddleware

    assert server.app_settings.entra_auth_habilitado is False
    with (
        patch("mcp_radardeprecos.server.uvicorn") as mock_uvicorn,
        patch("mcp_radardeprecos.server.anyio"),
    ):
        server._run_http("streamable-http", 60)

    app_passado = mock_uvicorn.Config.call_args.args[0]
    assert isinstance(app_passado, RateLimitMiddleware)
    assert not isinstance(app_passado._app, EntraAuthMiddleware)


def test_run_http_com_entra_habilitado_envolve_com_entra_auth_middleware(monkeypatch):
    import dataclasses

    from mcp_radardeprecos.auth.middleware import EntraAuthMiddleware
    from mcp_radardeprecos.rate_limit import RateLimitMiddleware

    monkeypatch.setattr(
        server,
        "app_settings",
        dataclasses.replace(
            server.app_settings, entra_tenant_id="tenant-teste", entra_client_id="client-teste"
        ),
    )
    assert server.app_settings.entra_auth_habilitado is True

    with (
        patch("mcp_radardeprecos.server.uvicorn") as mock_uvicorn,
        patch("mcp_radardeprecos.server.anyio"),
    ):
        server._run_http("streamable-http", 60)

    app_passado = mock_uvicorn.Config.call_args.args[0]
    # Ordem exigida pelo item 6: RateLimitMiddleware(EntraAuthMiddleware(base_app))
    # — rate limit por FORA, auth por DENTRO.
    assert isinstance(app_passado, RateLimitMiddleware)
    assert isinstance(app_passado._app, EntraAuthMiddleware)


def test_well_known_oauth_protected_resource_nao_existe_por_padrao():
    # Sem ENTRA_TENANT_ID/ENTRA_CLIENT_ID (estado normal do processo de
    # teste), a rota do item 5 nem deveria ter sido definida no módulo.
    assert not hasattr(server, "oauth_protected_resource")


def _reload_config_e_server():
    """Recarrega config.py e depois server.py, nesta ordem.

    ``config.settings`` é um singleton criado uma única vez, na primeira
    importação do módulo (lê as env vars naquele instante). Recarregar só
    ``server`` não basta: ``server.py`` faz ``from .config import settings
    as app_settings``, e um `importlib.reload(server)` sozinho reexecuta
    esse import, mas ele resolve para o MESMO objeto `config.settings` já
    existente (o módulo `config` não foi recarregado, então seu estado —
    incluindo o singleton — continua o de antes). É preciso recarregar
    ``config`` primeiro, para o singleton ser reconstruído lendo as env
    vars monkeypatchadas, e só então recarregar ``server``.

    Também remove ``server.oauth_protected_resource`` antes do reload, se
    presente: ``importlib.reload`` reexecuta o código do módulo dentro do
    MESMO namespace já existente — nomes de uma execução anterior que a
    nova execução não reatribui (ex.: a rota condicional, se desta vez o
    branch ``if`` for falso) simplesmente permanecem no módulo. Sem essa
    remoção manual, desligar a auth Entra e recarregar não bastaria para
    apagar a rota registrada por um reload anterior com a auth ligada.
    """
    import importlib

    from mcp_radardeprecos import config as config_module

    importlib.reload(config_module)
    if hasattr(server, "oauth_protected_resource"):
        del server.oauth_protected_resource
    importlib.reload(server)


async def test_well_known_oauth_protected_resource_e_registrada_quando_entra_habilitado(monkeypatch):
    # A rota é registrada condicionalmente em tempo de IMPORTAÇÃO do módulo
    # (`if app_settings.entra_auth_habilitado:` no nível do módulo) — ao
    # contrário de _run_http, cuja checagem é em tempo de chamada. Para
    # exercitar o branch "habilitado" é preciso recarregar config+server com
    # as env vars já setadas; o `finally` recarrega de novo, sem as env
    # vars, para devolver ambos os módulos ao estado padrão (sem auth) para
    # os demais testes do processo — nenhum outro teste deveria depender de
    # identidade de objeto do módulo entre chamadas.
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-teste")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "client-teste")
    try:
        _reload_config_e_server()
        assert hasattr(server, "oauth_protected_resource")

        app = server.mcp.streamable_http_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get("/.well-known/oauth-protected-resource")

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["resource"] == "http://test"
        assert corpo["authorization_servers"] == [
            "https://login.microsoftonline.com/tenant-teste/v2.0"
        ]
        assert corpo["bearer_methods_supported"] == ["header"]
    finally:
        monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
        monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
        _reload_config_e_server()
        assert not hasattr(server, "oauth_protected_resource")


async def test_well_known_oauth_protected_resource_inclui_scopes_quando_configurado(monkeypatch):
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-teste")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "client-teste")
    monkeypatch.setenv("ENTRA_REQUIRED_SCOPE", "Leitura.Tools")
    try:
        _reload_config_e_server()
        app = server.mcp.streamable_http_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get("/.well-known/oauth-protected-resource")
        assert resposta.json()["scopes_supported"] == ["Leitura.Tools"]
    finally:
        monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
        monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
        monkeypatch.delenv("ENTRA_REQUIRED_SCOPE", raising=False)
        _reload_config_e_server()


async def test_registro_de_tools_preservado_apos_reload_com_entra_habilitado(monkeypatch):
    # Regressão: recarregar o módulo com a auth Entra ligada não pode mudar
    # nada nas tools registradas — só acrescenta a rota /.well-known.
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-teste")
    monkeypatch.setenv("ENTRA_CLIENT_ID", "client-teste")
    try:
        _reload_config_e_server()
        tools = await server.mcp.list_tools()
        assert len(tools) == 48
    finally:
        monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
        monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
        _reload_config_e_server()


# --- CORS ---


async def test_health_check_tem_header_cors():
    app = server.mcp.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resposta = await client.get("/")
    # CORS aberto só no endpoint público de status/métricas (não no /mcp).
    assert resposta.headers.get("access-control-allow-origin") == "*"


async def test_initialize_reporta_a_versao_do_projeto_nao_a_do_sdk(monkeypatch):
    # Regressão: "/" devolvia a versão do projeto e o
    # handshake devolvia 1.29.0 — a versão do SDK do MCP. FastMCP não aceita
    # ``version=`` e o servidor de baixo nível cai em ``pkg_version("mcp")``
    # quando ninguém preenche o campo.
    # run_http() desliga a proteção de DNS rebinding em produção (quem valida
    # o Host é o balanceador). Aqui reproduzimos essa configuração, senão o
    # app devolve 421 para qualquer Host de teste.
    monkeypatch.setattr(
        server.mcp.settings,
        "transport_security",
        TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    # streamable_http_app() cria o session manager na primeira chamada e
    # guarda as settings de segurança nele. Como outro teste do arquivo já
    # pode tê-lo criado, zeramos para que seja reconstruído com o patch acima.
    monkeypatch.setattr(server.mcp, "_session_manager", None)
    app = server.mcp.streamable_http_app()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1"},
        },
    }
    # O app streamable-http só funciona dentro do lifespan: é ele que cria o
    # task group do gerenciador de sessões. Sem isso, RuntimeError.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            resposta = await client.post(
                "/mcp",
                json=payload,
                headers={"Accept": "application/json, text/event-stream"},
            )

    assert resposta.status_code == 200
    # A resposta vem como SSE: linhas "event:" e "data:".
    dados = [
        json.loads(linha[len("data:"):].strip())
        for linha in resposta.text.splitlines()
        if linha.startswith("data:")
    ]
    assert dados, f"nenhum frame SSE em {resposta.text!r}"
    server_info = dados[0]["result"]["serverInfo"]
    assert server_info["name"] == "mcp-radardeprecos"
    assert server_info["version"] == __version__
    assert server_info["version"] != pkg_version("mcp")


async def test_ano_multivalorado_chega_a_tool_e_nao_morre_no_pydantic():
    """A validacao de `ano` tem que rodar PELA CAMADA MCP, nao so na funcao.

    Este teste existe porque o de tests/test_tools.py mentiu. Ele chamava
    `buscar_pncp_texto(...)` direto em Python, passava, e me deu confianca de
    que a mensagem de dominio chegava ao usuario. Nao chegava: a assinatura
    declarava `ano: int | None`, entao o Pydantic do FastMCP recusava a string
    ANTES de a funcao comecar, e o cliente recebia

        Input should be a valid integer, unable to parse string as an integer
        [type=int_parsing, input_value='2023,2024', ...]

    — que ensina que o campo e numerico e NAO ensina que o indice do PNCP
    aceita um ano por chamada, nem que a saida e fazer duas buscas. Relatado
    num teste real do MCP em 2026-08-21.

    Testar a funcao nao e testar a ferramenta. O schema publicado e parte do
    contrato, e so um teste que passe por ele pega esta classe de defeito.
    """
    tools = {t.name: t for t in await server.mcp.list_tools()}
    for nome in ("buscar_pncp_texto", "buscar_pncp_texto_booleano"):
        if nome not in tools:
            continue
        schema = tools[nome].inputSchema
        ano = schema["properties"]["ano"]
        # anyOf com string entre as opcoes: e o que deixa a string passar pelo
        # Pydantic e chegar em _validar_ano.
        alternativas = ano.get("anyOf") or [ano]
        tipos = {a.get("type") for a in alternativas}
        assert "string" in tipos, (
            f"{nome}.ano nao aceita string no schema ({tipos}) — o Pydantic vai "
            "barrar '2023,2024' antes da validacao de dominio, e o cliente "
            "recebera erro de tipo em vez da explicacao"
        )


async def test_toda_tool_declara_anotacoes():
    """Sem anotacoes, um cliente prudente pede confirmacao a CADA chamada.

    Relatado no Gemini em 2026-08-21: ele documenta exigir confirmacao manual
    para acoes de ESCRITA, mas sem a declaracao tratava consulta de preco
    publico como se fosse escrita. Confirmacao em excesso nao e so incomodo —
    treina o usuario a clicar "permitir" sem ler, o que corroi a protecao
    justamente nas poucas chamadas em que ela deveria importar.
    """
    tools = await server.mcp.list_tools()
    sem = [t.name for t in tools if t.annotations is None]
    assert not sem, f"tools sem ToolAnnotations: {sem}"


async def test_nenhuma_tool_que_escreve_se_declara_somente_leitura():
    """O erro perigoso e ANUNCIAR como inocua uma tool que modifica algo.

    A lista `_TOOLS_QUE_ESCREVEM` e mantida a mao, e mao esquece. Este teste
    varre o codigo-fonte de cada tool declarada somente-leitura procurando
    escrita em disco — se alguem adicionar uma tool que grava arquivo e
    esquecer de listá-la, o servidor passaria a mentir ao cliente sobre o
    efeito da chamada, e o teste falha antes disso chegar a producao.

    A heuristica erra para o lado seguro: no maximo acusa um falso positivo,
    que se resolve incluindo a tool na lista.
    """
    import inspect

    from mcp_radardeprecos import server as srv

    escritas = ("open(", ".save(", "write_text", "write_bytes", ".mkdir(")
    por_nome = {f.__name__: f for f in srv._TOOLS}
    suspeitas = []
    for tool in await srv.mcp.list_tools():
        if not tool.annotations.readOnlyHint:
            continue
        func = por_nome.get(tool.name)
        if func is None:
            continue
        try:
            fonte = inspect.getsource(inspect.getmodule(func))
        except (OSError, TypeError):
            continue
        achados = [p for p in escritas if p in fonte]
        if achados:
            suspeitas.append(f"{tool.name} (encontrado: {', '.join(achados)})")
    assert not suspeitas, (
        "tool(s) declaradas readOnlyHint=True mas com escrita em disco no "
        f"modulo — inclua em _TOOLS_QUE_ESCREVEM: {suspeitas}"
    )


def _alcanca_cliente(nome_tool: str, _vistos: set[str] | None = None) -> bool:
    """A tool chega a um cliente HTTP, direta ou indiretamente?

    Análise estática do módulo ``tools/<nome>.py``: procura ``from ..clients``
    e, recursivamente, segue os imports de outras tools do mesmo pacote —
    várias tools de orquestração (``pesquisar_cesta_precos``,
    ``buscar_pncp_texto_booleano``) não importam cliente algum, mas chamam
    tools que importam.
    """
    import ast
    import pathlib

    _vistos = _vistos if _vistos is not None else set()
    if nome_tool in _vistos:
        return False
    _vistos.add(nome_tool)

    caminho = (
        pathlib.Path(server.__file__).parent / "tools" / f"{nome_tool}.py"
    )
    if not caminho.exists():
        return False
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if not isinstance(no, ast.ImportFrom):
            continue
        modulo = no.module or ""
        # `from ..clients import x` / `from ..clients.y import z`
        if no.level == 2 and modulo.startswith("clients"):
            return True
        # `from .outra_tool import outra_tool`
        if no.level == 1 and modulo and _alcanca_cliente(modulo, _vistos):
            return True
    return False


def test_tools_sem_rede_nao_alcancam_nenhum_cliente_http():
    """Guarda do ``openWorldHint``.

    Até a v0.5.2 duas tools estavam em ``_TOOLS_SEM_REDE`` indevidamente:
    ``listar_filtros_pncp`` (chama ``/api/search/filters``) e
    ``converter_para_unidade_base`` (chama as unidades de fornecimento/medida
    no Compras.gov.br, em qualquer dos dois ramos).

    É um erro que não quebra teste nenhum e engana quem confia na anotação —
    um cliente MCP que use ``openWorldHint`` para decidir se pode chamar a
    tool offline, ou para julgar se o resultado é reprodutível, recebia a
    informação trocada. Esta guarda deriva a verdade do código, e não de uma
    lista mantida à mão.
    """
    indevidas = sorted(n for n in server._TOOLS_SEM_REDE if _alcanca_cliente(n))
    assert not indevidas, (
        f"tools marcadas como openWorldHint=False mas que alcançam um cliente "
        f"HTTP: {indevidas}"
    )


def test_a_guarda_de_openworldhint_realmente_detecta():
    """Verifica o detector, não só o conjunto.

    Sem isto, um ``_alcanca_cliente`` que devolvesse ``False`` para tudo
    faria o teste acima passar para sempre — a guarda passaria a vigiar nada.
    """
    assert _alcanca_cliente("listar_filtros_pncp"), "import direto de cliente"
    assert _alcanca_cliente("converter_para_unidade_base"), "import direto"
    assert _alcanca_cliente("buscar_pncp_texto_booleano"), "alcance transitivo"
    assert not _alcanca_cliente("calcular_preco_referencia"), "puro de verdade"


# ===========================================================================
# v0.6.2 — POST na raiz devolvia 405 mudo
# ===========================================================================
#
# Relatado em 10/09/2026: um cliente MCP configurado com a URL da raiz
# (`https://host/`, sem `/mcp`) recebia
#
#     405 Method Not Allowed for url 'https://host/'
#
# e quem operava concluiu que **o servidor não implementava Streamable HTTP**.
# Conclusão razoável a partir do que a resposta dizia, e errada: o transporte
# está em `/mcp` e funciona; a raiz é health check e só aceita GET.
#
# O 405 estava tecnicamente correto e ainda assim levou à conclusão oposta —
# o mesmo padrão que este projeto persegue nas fontes externas, agora do lado
# de dentro. Uma resposta certa que induz a leitura errada é um defeito.


async def test_post_na_raiz_aponta_o_endpoint_mcp_em_vez_de_405_mudo():
    """O corpo tem de dizer para onde ir, não só que aqui não dá."""
    from starlette.requests import Request

    escopo = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    resposta = await server.raiz_metodo_incorreto(Request(escopo))
    assert resposta.status_code == 405
    assert resposta.headers.get("allow") == "GET, HEAD"

    corpo = json.loads(bytes(resposta.body).decode("utf-8"))
    assert corpo["mcp_endpoint"] == "/mcp"
    assert "/mcp" in corpo["erro"]
    assert "streamable" in corpo["transporte"].lower()


async def test_a_raiz_continua_respondendo_get_para_o_health_check():
    """Controle: o balanceador que testa a raiz não pode passar a receber erro."""
    resposta = await server.health_check(None)
    assert resposta.status_code == 200
    corpo = json.loads(bytes(resposta.body).decode("utf-8"))
    assert corpo["status"] == "ok"
    assert corpo["mcp_endpoint"] == "/mcp"
