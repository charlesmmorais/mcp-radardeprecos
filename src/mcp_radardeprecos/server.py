"""Servidor MCP mcp-radardeprecos.

Camada fina de registro: nenhuma lógica de negócio mora aqui. Cada tool é
implementada em ``tools/<nome>.py``, cuja assinatura e docstring são a única
fonte do schema e da descrição que o cliente MCP vê (``functools.wraps`` em
:func:`_registrar_tool`). Ver ``docs/ARQUITETURA.md``.

Transportes:

- ``stdio`` (padrão): uso local, ex.: Claude Desktop.
- ``sse`` / ``streamable-http``: hospedagem via HTTP, com rate limit por
  origem, autenticação Microsoft Entra ID opcional e ``caminho_saida``
  desabilitado (o disco é o do servidor, não o do usuário).
"""
from __future__ import annotations

import argparse
import functools
import os
import time
from collections.abc import Awaitable, Callable
from importlib import resources
from typing import Any

import anyio
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import __version__, auditoria, observability
from .auth.middleware import EntraAuthMiddleware
from .catalogo import descrever_catalogo
from .config import settings as app_settings
from .domain.diretrizes_pesquisa_precos import renderizar_markdown
from .logging_utils import configure_logging, get_logger, new_request_id
from .observability import obter_metricas, registrar_chamada
from .prompts.conduzir_pesquisa_precos import (
    conduzir_pesquisa_precos as _conduzir_pesquisa_precos,
)
from .rate_limit import RateLimiter, RateLimitMiddleware
from .tools.agrupar_por_comparabilidade import agrupar_por_comparabilidade
from .tools.atualizar_precos_indice import atualizar_precos_indice
from .tools.buscar_arp_compras import buscar_arp_compras
from .tools.buscar_contratacoes_pncp import buscar_contratacoes_pncp
from .tools.buscar_contratos_compras import buscar_contratos_compras
from .tools.buscar_homologados_14133 import buscar_homologados_14133
from .tools.buscar_pncp_texto import buscar_pncp_texto
from .tools.buscar_pncp_texto_booleano import buscar_pncp_texto_booleano
from .tools.buscar_precos_praticados_compras import buscar_precos_praticados_compras
from .tools.buscar_precos_saude_bps import buscar_precos_saude_bps
from .tools.buscar_propostas_abertas import buscar_propostas_abertas
from .tools.calcular_preco_referencia import calcular_preco_referencia
from .tools.classificar_curva_abc import classificar_curva_abc
from .tools.classificar_objeto_tic import classificar_objeto_tic
from .tools.consultar_arp_detalhe_compras import consultar_arp_detalhe_compras
from .tools.consultar_ata_registro_preco import consultar_ata_registro_preco
from .tools.consultar_cnpj import consultar_cnpj
from .tools.consultar_contratacao_pncp import consultar_contratacao_pncp
from .tools.consultar_contratos_compras import consultar_contratos_compras
from .tools.consultar_contratos_orgao_pncp import consultar_contratos_orgao_pncp
from .tools.consultar_familia_contratacao_pncp import consultar_familia_contratacao_pncp
from .tools.consultar_itens_contrato_compras import consultar_itens_contrato_compras
from .tools.consultar_notas_fiscais import consultar_notas_fiscais
from .tools.consultar_pca import consultar_pca
from .tools.consultar_sancoes_fornecedor import consultar_sancoes_fornecedor
from .tools.consultar_situacao_fornecedor import consultar_situacao_fornecedor
from .tools.consultar_tabelas_dominio_pncp import consultar_tabelas_dominio_pncp
from .tools.contar_pncp import contar_pncp
from .tools.converter_para_unidade_base import converter_para_unidade_base
from .tools.descobrir_codigo_catalogo import descobrir_codigo_catalogo
from .tools.descobrir_uasg import descobrir_uasg
from .tools.detectar_inconsistencias import detectar_inconsistencias
from .tools.exportar_resultados import exportar_resultados
from .tools.exportar_trilha_auditoria import exportar_trilha_auditoria
from .tools.gerar_estudo_mercado_tic import gerar_estudo_mercado_tic
from .tools.gerar_memoria_pesquisa import gerar_memoria_pesquisa
from .tools.gerar_relatorio_excel import gerar_relatorio_excel
from .tools.gerar_relatorio_word import gerar_relatorio_word
from .tools.listar_arquivos_pncp import listar_arquivos_pncp
from .tools.listar_filtros_pncp import listar_filtros_pncp
from .tools.listar_itens_catalogo import listar_itens_catalogo
from .tools.mapear_fornecedores_mercado import mapear_fornecedores_mercado
from .tools.montar_cesta_precos import montar_cesta_precos
from .tools.navegar_catalogo_servico import navegar_catalogo_servico
from .tools.normalizar_precos_unidade import normalizar_precos_unidade
from .tools.obter_diretrizes_pesquisa_precos import obter_diretrizes_pesquisa_precos
from .tools.pesquisar_cesta_precos import pesquisar_cesta_precos
from .tools.radar_vencimentos import radar_vencimentos
from .utils.arquivo_saida import ENV_PERMITIR_CAMINHO_SAIDA, permitir_gravacao_em_disco
from .utils.numeros import aviso_rede_de_seguranca, proteger_inteiros_grandes

configure_logging()
logger = get_logger(__name__)

mcp = FastMCP(
    name="mcp-radardeprecos",
    instructions=(
        "Ferramentas de pesquisa de contratações e contratos públicos "
        "brasileiros (PNCP), de cálculo de preço de referência (média "
        "saneada, mediana, escore Z, mínimo), de matriz de comparabilidade "
        "de soluções técnicas de TIC (gerar_estudo_mercado_tic), das "
        "diretrizes metodológicas de uma pesquisa de preços e de geração "
        "de relatórios reais (Excel/Word) da pesquisa, para apoiar a "
        "pesquisa conforme IN SEGES/ME 65/2021. Consulte a tool "
        "obter_diretrizes_pesquisa_precos antes de iniciar uma pesquisa, "
        "ou o prompt conduzir_pesquisa_precos para um roteiro completo."
    ),
)

# FastMCP não aceita ``version=``; sem isto o handshake anuncia a versão do SDK.
mcp._mcp_server.version = __version__


# A ordem desta lista é a ordem em que os clientes MCP exibem as tools.
_TOOLS: list[Callable[..., Awaitable[object]]] = [
    buscar_pncp_texto,
    buscar_pncp_texto_booleano,
    contar_pncp,
    listar_filtros_pncp,
    listar_arquivos_pncp,
    buscar_contratacoes_pncp,
    buscar_contratos_compras,
    calcular_preco_referencia,
    atualizar_precos_indice,
    buscar_precos_praticados_compras,
    buscar_precos_saude_bps,
    buscar_homologados_14133,
    buscar_arp_compras,
    consultar_arp_detalhe_compras,
    consultar_ata_registro_preco,
    consultar_contratacao_pncp,
    descobrir_codigo_catalogo,
    listar_itens_catalogo,
    obter_diretrizes_pesquisa_precos,
    classificar_curva_abc,
    gerar_memoria_pesquisa,
    consultar_pca,
    consultar_cnpj,
    consultar_situacao_fornecedor,
    consultar_sancoes_fornecedor,
    descobrir_uasg,
    gerar_relatorio_excel,
    gerar_relatorio_word,
    consultar_tabelas_dominio_pncp,
    consultar_contratos_orgao_pncp,
    consultar_familia_contratacao_pncp,
    consultar_itens_contrato_compras,
    consultar_contratos_compras,
    pesquisar_cesta_precos,
    gerar_estudo_mercado_tic,
    classificar_objeto_tic,
    radar_vencimentos,
    buscar_propostas_abertas,
    consultar_notas_fiscais,
    exportar_resultados,
    navegar_catalogo_servico,
    mapear_fornecedores_mercado,
    montar_cesta_precos,
    normalizar_precos_unidade,
    converter_para_unidade_base,
    agrupar_por_comparabilidade,
    detectar_inconsistencias,
    exportar_trilha_auditoria,
]

#: Tools que geram arquivo — as únicas anunciadas como não somente-leitura.
#: Lista por exceção: esquecer uma tool aqui faria o servidor dizer ao
#: cliente que uma chamada que escreve é inócua.
_TOOLS_QUE_ESCREVEM = frozenset({
    "exportar_resultados",
    "exportar_trilha_auditoria",
    "gerar_relatorio_excel",
    "gerar_relatorio_word",
    "gerar_memoria_pesquisa",
})

#: Tools que respondem só com cálculo local ou tabelas embutidas
#: (``openWorldHint=False``). ``tests/test_server.py`` confere esta lista
#: contra os imports reais de cada módulo.
_TOOLS_SEM_REDE = frozenset({
    "consultar_tabelas_dominio_pncp",
    "obter_diretrizes_pesquisa_precos",
    "classificar_objeto_tic",
    "normalizar_precos_unidade",
    "agrupar_por_comparabilidade",
    "calcular_preco_referencia",
    "classificar_curva_abc",
    "detectar_inconsistencias",
})


def _anotacoes(nome: str) -> ToolAnnotations:
    """Dicas de comportamento que o cliente usa para decidir quando pedir confirmação.

    Sem elas, clientes prudentes pedem autorização a cada consulta de preço
    público, o que treina o usuário a aprovar sem ler. Nenhuma tool apaga ou
    sobrescreve dado alheio, então ``destructiveHint`` é sempre ``False``.
    """
    escreve = nome in _TOOLS_QUE_ESCREVEM
    return ToolAnnotations(
        readOnlyHint=not escreve,
        destructiveHint=False,
        idempotentHint=not escreve,
        openWorldHint=nome not in _TOOLS_SEM_REDE,
    )


def _registrar_tool(func: Callable[..., Awaitable[object]]) -> None:
    """Registra ``func`` como tool MCP.

    O wrapper é o ponto único de instrumentação de todas as tools: request_id,
    métricas em memória, trilha de auditoria e a conversão de inteiros acima
    de 2^53-1 para texto (o transporte MCP os arredondaria em silêncio). Erros
    são contabilizados e sempre repropagados.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        new_request_id()
        inicio = time.monotonic()
        sucesso = True
        token = auditoria.definir_tool_atual(func.__name__)
        try:
            resultado = await func(*args, **kwargs)
            if isinstance(resultado, dict):
                resultado, convertidos = proteger_inteiros_grandes(resultado)
                if convertidos:
                    logger.warning(
                        "inteiro acima do limite seguro convertido para texto "
                        "em %s: %s", func.__name__, ", ".join(convertidos),
                    )
                    avisos = resultado.get("avisos")
                    if isinstance(avisos, list):
                        avisos.append(aviso_rede_de_seguranca(convertidos))
            return resultado
        except Exception:
            sucesso = False
            raise
        finally:
            auditoria.limpar_tool_atual(token)
            registrar_chamada(func.__name__, time.monotonic() - inicio, sucesso)
            observability.registrar_sessao(observability.sessao_atual(), func.__name__)
            observability.registrar_protocolo(observability.protocolo_atual())

    mcp.tool(name=func.__name__, annotations=_anotacoes(func.__name__))(wrapper)


for _tool in _TOOLS:
    _registrar_tool(_tool)


@mcp.prompt(name="conduzir_pesquisa_precos")
@functools.wraps(_conduzir_pesquisa_precos)
def conduzir_pesquisa_precos(*args, **kwargs):
    new_request_id()
    return _conduzir_pesquisa_precos(*args, **kwargs)


@mcp.resource(
    "docs://boas-praticas-pesquisa-precos",
    name="Boas práticas de pesquisa de preços",
    description=(
        "Premissas de uma pesquisa de preços (fases, fontes prioritárias, "
        "regras de amostra, janela temporal, métodos de cálculo, Curva ABC "
        "e checklist de formalização), em Markdown. Mesmo conteúdo da tool "
        "obter_diretrizes_pesquisa_precos, em formato de leitura corrida."
    ),
    mime_type="text/markdown",
)
def boas_praticas_pesquisa_precos() -> str:
    return renderizar_markdown()


@mcp.custom_route("/", methods=["POST", "PUT", "DELETE", "PATCH"])
async def raiz_metodo_incorreto(request: Request) -> Response:
    """Responde 405 dizendo onde está o endpoint MCP.

    Um 405 sem corpo leva quem configurou o cliente com a URL da raiz a concluir
    que o servidor não suporta Streamable HTTP.
    """
    return JSONResponse(
        {
            "erro": (
                "Esta é a raiz do servidor, que só responde GET (health check). "
                "O endpoint do protocolo MCP é /mcp — configure o cliente com "
                "a URL terminando em /mcp."
            ),
            "mcp_endpoint": "/mcp",
            "transporte": "streamable-http (POST em /mcp)",
            "metodos_aceitos_aqui": ["GET", "HEAD"],
            "exemplo": f"{request.url.scheme}://{request.url.netloc}/mcp",
        },
        status_code=405,
        headers={"Allow": "GET, HEAD"},
    )


@mcp.custom_route("/", methods=["GET"])
async def health_check(request: Request) -> Response:
    """Health check: versão, catálogo de tools (com digest) e métricas em memória.

    O catálogo permite distinguir cliente com cache velho de deploy que não
    aplicou. As métricas reiniciam a cada reinício do processo.
    """
    return JSONResponse(
        {
            "status": "ok",
            "service": "mcp-radardeprecos",
            "version": __version__,
            "mcp_endpoint": "/mcp",
            "catalogo": descrever_catalogo(await mcp.list_tools()),
            "metrics": obter_metricas(),
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


_FAVICON = (resources.files(__package__) / "static" / "favicon.png").read_bytes()


@mcp.custom_route("/favicon.ico", methods=["GET"])
async def favicon(request: Request) -> Response:
    """Ícone que o navegador pede ao abrir qualquer página do servidor."""
    return Response(
        content=_FAVICON,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


if app_settings.entra_auth_habilitado:

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
    async def oauth_protected_resource(request: Request) -> Response:
        """Metadados de recurso protegido (RFC 9728): aponta o tenant Entra como authorization server."""
        recurso = str(request.base_url).rstrip("/")
        corpo: dict[str, object] = {
            "resource": recurso,
            "authorization_servers": [
                f"https://login.microsoftonline.com/{app_settings.entra_tenant_id}/v2.0"
            ],
            "bearer_methods_supported": ["header"],
        }
        if app_settings.entra_required_scope:
            corpo["scopes_supported"] = [app_settings.entra_required_scope]
        return JSONResponse(corpo)


_TRANSPORTES_VALIDOS = ("stdio", "sse", "streamable-http")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mcp-radardeprecos",
        description=(
            "Servidor MCP mcp-radardeprecos. Sem argumentos, roda em "
            "stdio (uso local, ex.: Claude Desktop). Use --transport para "
            "expor via HTTP."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--transport",
        choices=_TRANSPORTES_VALIDOS,
        default=os.environ.get("RADARDEPRECOS_TRANSPORT", "stdio"),
        help=(
            "Transporte MCP: 'stdio' (padrão), 'sse' ou 'streamable-http'. "
            "Também via RADARDEPRECOS_TRANSPORT."
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host para os transportes HTTP. Padrão: 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Porta para os transportes HTTP. Padrão: 8000.",
    )
    parser.add_argument(
        "--rate-limit-por-minuto",
        type=int,
        default=int(os.environ.get("RADARDEPRECOS_RATE_LIMIT_PER_MINUTE", "60")),
        help=(
            "Requisições por minuto por origem, nos transportes HTTP. "
            "Também via RADARDEPRECOS_RATE_LIMIT_PER_MINUTE. Padrão: 60."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    # O valor default vindo do ambiente não passa pelo `choices` do argparse.
    if args.transport not in _TRANSPORTES_VALIDOS:
        raise ValueError(
            f"transporte {args.transport!r} inválido — use um de {_TRANSPORTES_VALIDOS} "
            "(via --transport ou RADARDEPRECOS_TRANSPORT)"
        )

    if args.host is not None:
        mcp.settings.host = args.host
    if args.port is not None:
        mcp.settings.port = args.port

    detalhe_http = (
        f", host={mcp.settings.host}:{mcp.settings.port}"
        f", rate_limit={args.rate_limit_por_minuto}/min"
        if args.transport != "stdio"
        else ""
    )
    logger.info(
        "iniciando mcp-radardeprecos v%s (transport=%s%s)",
        __version__, args.transport, detalhe_http,
    )

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        _run_http(args.transport, args.rate_limit_por_minuto)


def _run_http(transport: str, rate_limit_por_minuto: int) -> None:
    """Sobe os transportes HTTP com a cadeia de middlewares do servidor.

    Cadeia, de fora para dentro: ``RateLimitMiddleware`` → ``EntraAuthMiddleware``
    (só se configurado) → app do FastMCP. O rate limit
    fica por fora para barrar abuso antes de gastar CPU validando JWT.

    A proteção contra DNS rebinding do SDK é desligada: ela só aceita Host de
    localhost e rejeita (421) qualquer domínio público. O ataque que ela
    previne mira servidores locais acessados por navegador, cenário que não
    se aplica a um servidor hospedado atrás de HTTPS.
    """
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    # O disco é o do servidor, compartilhado entre clientes. Opt-in só para
    # quem roda HTTP na própria máquina (ex.: túnel local).
    permitir_disco = os.environ.get(ENV_PERMITIR_CAMINHO_SAIDA, "").strip().lower() in (
        "1", "true", "sim", "yes",
    )
    permitir_gravacao_em_disco(permitir_disco)
    logger.info("caminho_saida %s no transporte HTTP",
                "PERMITIDO (opt-in)" if permitir_disco else "recusado")

    limiter = RateLimiter(limite_por_minuto=rate_limit_por_minuto)

    app: Any = mcp.sse_app() if transport == "sse" else mcp.streamable_http_app()
    if app_settings.entra_auth_habilitado:
        app = EntraAuthMiddleware(app)
    app = RateLimitMiddleware(app, limiter=limiter)

    config = uvicorn.Config(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    anyio.run(server.serve)


if __name__ == "__main__":
    main()
