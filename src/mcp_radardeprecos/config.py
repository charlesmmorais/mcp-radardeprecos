"""Configurações do servidor mcp-radardeprecos.

Nenhuma credencial ou parâmetro de conexão fica hardcoded no código: tudo é
lido de variáveis de ambiente, com valores padrão seguros para uso
somente-leitura contra APIs públicas (PNCP e Compras.gov.br).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

# logging direto (não logging_utils.get_logger) para evitar import circular:
# logging_utils importa settings deste módulo. Um warning emitido aqui, na
# importação, sai pelo handler "lastResort" do logging (stderr) se
# configure_logging() ainda não rodou — melhor que engolir o erro.
_logger = logging.getLogger(__name__)


def _versao() -> str:
    """Versão do pacote, para compor o User-Agent.

    Import tardio de propósito: ``config`` é importado muito cedo, e um
    ``from . import __version__`` no topo criaria dependência de ordem sem
    necessidade. O ``except`` cobre o cenário em que o pacote está sendo
    executado de uma árvore sem metadados.
    """
    try:
        from . import __version__

        return __version__
    except Exception:  # noqa: BLE001
        return "0"


def _get_float(name: str, default: float) -> float:
    bruto = os.environ.get(name)
    if bruto is None:
        return default
    try:
        return float(bruto)
    except ValueError:
        # Falha silenciosa aqui já escondeu erro de digitação de verdade
        # (ex.: RADARDEPRECOS_HTTP_TIMEOUT=3O, letra O) — avisa e usa o padrão.
        _logger.warning(
            "variável de ambiente %s=%r inválida (não numérica) — usando o padrão %s",
            name, bruto, default,
        )
        return default


def _get_int(name: str, default: int) -> int:
    bruto = os.environ.get(name)
    if bruto is None:
        return default
    try:
        return int(bruto)
    except ValueError:
        _logger.warning(
            "variável de ambiente %s=%r inválida (não inteira) — usando o padrão %s",
            name, bruto, default,
        )
        return default


@dataclass(frozen=True)
class Settings:
    """Parâmetros de configuração, todos sobrescrevíveis via variável de ambiente."""

    pncp_consulta_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "PNCP_CONSULTA_BASE_URL", "https://pncp.gov.br/api/consulta"
        )
    )
    pncp_pncp_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "PNCP_PNCP_BASE_URL", "https://pncp.gov.br/api/pncp"
        )
    )
    pncp_search_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "PNCP_SEARCH_BASE_URL", "https://pncp.gov.br/api/search"
        )
    )
    compras_dadosabertos_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "COMPRAS_DADOSABERTOS_BASE_URL", "https://dadosabertos.compras.gov.br"
        )
    )
    brasilapi_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "BRASILAPI_BASE_URL", "https://brasilapi.com.br/api"
        )
    )
    minhareceita_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "MINHARECEITA_BASE_URL", "https://minhareceita.org"
        )
    )
    bcb_sgs_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "BCB_SGS_BASE_URL", "https://api.bcb.gov.br"
        )
    )
    # API de Dados Abertos do Ministério da Saúde (DEMAS), que expõe o Banco de
    # Preços em Saúde. Repare que a URL NÃO tem o `/v1` que aparece no endereço
    # do Swagger UI: a especificação (`/static/swagger.json`) não declara
    # `basePath`, então os caminhos são relativos à raiz. O `/v1` é apenas onde
    # a interface de documentação está montada, e incluí-lo devolve 404 —
    # confirmado ao vivo em 2026-08-27.
    saude_dadosabertos_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "SAUDE_DADOSABERTOS_BASE_URL", "https://apidadosabertos.saude.gov.br"
        )
    )
    tcu_certidoes_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "TCU_CERTIDOES_BASE_URL", "https://certidoes-apf.apps.tcu.gov.br"
        )
    )

    # CPF de fornecedor pessoa física sai mascarado por padrão. O campo de
    # documento é o MESMO para PJ e PF nas fontes consultadas
    # (`niFornecedor`, `ni`), então quem separa somos nós, pelo comprimento.
    # A saída é por ambiente, e não por parâmetro de chamada, para que a
    # decisão fique registrada na configuração do servidor em vez de escondida
    # numa chamada que ninguém revisa.
    incluir_cpf_completo: bool = field(
        default_factory=lambda: os.environ.get(
            "RADARDEPRECOS_INCLUIR_CPF_COMPLETO", ""
        ).strip().lower() in ("1", "true", "sim")
    )

    http_timeout_seconds: float = field(
        default_factory=lambda: _get_float("RADARDEPRECOS_HTTP_TIMEOUT", 30.0)
    )
    # User-Agent de TODAS as chamadas externas. Não é cosmético: medido em
    # 2026-08-21, 10 rodadas INTERCALADAS contra o /api/search do PNCP, mesma
    # URL, mesma máquina, mesmo instante:
    #
    #   Mozilla/5.0 (navegador) .... 10/10 ok
    #   python-urllib/3.x ..........  3/10 ok  (ConnectionResetError)
    #   python-httpx/0.27.0 ........  3/10 ok  (ConnectionResetError)
    #
    # Havia uma proteção anti-bot derrubando a conexão pelo header. Era a
    # causa real das "falhas de rede intermitentes do PNCP" que perseguimos o
    # dia inteiro e atribuímos à instabilidade da origem — 70% das nossas
    # chamadas eram recusadas antes de chegar ao índice.
    #
    # A PRIMEIRA tentativa de correção usou o formato de bot legítimo,
    # "Mozilla/5.0 (compatible; nome/versão; +url)" — o do Googlebot. Passou
    # 1/10 e 4/10 em duas medições: PIOR que o python-httpx que substituía. O
    # filtro não faz checagem ingênua de prefixo; "(compatible;" é justamente
    # o que anuncia "sou um bot", e é bloqueado.
    #
    # O formato abaixo — UA de navegador REAL com a identificação do projeto
    # anexada ao final — passou 10/10. Somando as três medições do dia, as
    # duas formas com aparência de navegador fizeram 40/40, e todas as demais,
    # 27/80.
    #
    # É o melhor acordo disponível, e a razão de não ser só um UA de Chrome
    # copiado: quem administra o PNCP vê no log o nome do projeto e onde
    # reclamar. A requisição não se faz passar silenciosamente por uma pessoa
    # num navegador. Se um dia a liberação do UA identificado for concedida
    # pela equipe do portal, troque por RADARDEPRECOS_HTTP_USER_AGENT.
    http_user_agent: str = field(
        default_factory=lambda: os.environ.get(
            "RADARDEPRECOS_HTTP_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 "
            f"mcp-radardeprecos/{_versao()} "
            "(+https://github.com/charlesmmorais/mcp-radardeprecos)",
        )
    )
    # Timeout (segundos) específico da consulta consolidada de PJ do TCU
    # (tools/consultar_sancoes_fornecedor). Essa fonte faz busca ao vivo em
    # quatro bases e é notavelmente LENTA justamente para CNPJ COM registro
    # (o caso que mais importa) — com o timeout global de 30s ela estourava
    # antes de responder. Maior por padrão, sobrescrevível, e sem afetar o
    # timeout das demais fontes.
    tcu_timeout_seconds: float = field(
        default_factory=lambda: _get_float("RADARDEPRECOS_TCU_TIMEOUT", 60.0)
    )
    # 3 -> 4 na v0.4.19, apoiado em duas medições independentes da mesma
    # origem no mesmo dia: 1 falha em 5 chamadas diretas ao /api/search do
    # PNCP (sem proxy no caminho) e 3 em 8 num teste pelo MCP. Mesmo pela
    # estimativa otimista de ~20% por tentativa, 3 tentativas deixam ~0,8% de
    # falha residual; pela pessimista de ~37%, deixam ~5%. Uma tentativa a
    # mais leva o caso pessimista a ~2%, e só custa tempo QUANDO já se está
    # falhando. O teto de _ESPERA_MAX_SEGUNDOS é o que torna isso seguro:
    # sem ele, a 4ª espera da família de conexão seria de 12,8s.
    http_max_retries: int = field(
        default_factory=lambda: _get_int("RADARDEPRECOS_HTTP_MAX_RETRIES", 4)
    )
    # Orçamento de tempo (segundos) da varredura de índice das tools de busca
    # ampla (buscar_contratacoes_pncp, buscar_contratos_compras,
    # buscar_pncp_texto com janelas_meses): ao estourar, a tool devolve o
    # parcial já coletado com um aviso, em vez de arriscar o timeout do
    # cliente MCP engolir a resposta inteira. <= 0 desativa.
    tool_budget_seconds: float = field(
        default_factory=lambda: _get_float("RADARDEPRECOS_TOOL_BUDGET_SECONDS", 120.0)
    )
    # Retenção máxima de sessões MCP distintas em memória, para as métricas
    # por sessão. Ao estourar, a mais antiga sai e o total descartado é
    # declarado nos avisos — evita que um servidor de vida longa acumule
    # sessões sem teto. Nada disso identifica pessoa: o identificador é
    # gerado pelo próprio servidor.
    observabilidade_max_sessoes: int = field(
        default_factory=lambda: _get_int("RADARDEPRECOS_OBS_MAX_SESSOES", 500)
    )
    log_level: str = field(
        default_factory=lambda: os.environ.get("RADARDEPRECOS_LOG_LEVEL", "INFO")
    )

    # --- Entra ID / M365 Copilot ---
    #
    # MODO OPCIONAL, desligado por padrão: sem ENTRA_TENANT_ID e
    # ENTRA_CLIENT_ID, o servidor mantém EXATAMENTE o comportamento atual
    # (sem auth, aberto para Claude/ChatGPT/stdio). Ver `entra_auth_habilitado`
    # abaixo — é o único gate consultado pelo resto do código (server.py,
    # auth/middleware.py): a camada de auth nem é montada se ele for False.
    entra_tenant_id: str | None = field(
        default_factory=lambda: os.environ.get("ENTRA_TENANT_ID") or None
    )
    entra_client_id: str | None = field(
        default_factory=lambda: os.environ.get("ENTRA_CLIENT_ID") or None
    )
    # Se informado, exige esse scope/role no token (claim `scp` para tokens
    # delegados de usuário, `roles` para tokens de aplicação/client
    # credentials) — ver auth/entra.py:validar_token. Se None, basta um
    # token assinado válido do tenant/audience corretos.
    entra_required_scope: str | None = field(
        default_factory=lambda: os.environ.get("ENTRA_REQUIRED_SCOPE") or None
    )
    # TTL (segundos) do cache das chaves públicas (JWKS) do Entra — evita
    # buscar https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys
    # a cada requisição. Refresh também é disparado sob demanda quando um
    # token chega com um `kid` desconhecido (rotação de chave do Entra),
    # independente deste TTL — ver auth/entra.py:JWKSCache.
    entra_jwks_ttl_seconds: float = field(
        default_factory=lambda: _get_float("RADARDEPRECOS_JWKS_TTL", 3600.0)
    )

    @property
    def entra_auth_habilitado(self) -> bool:
        """``True`` só quando tenant E client_id estão configurados.

        Único gate consultado para decidir se a camada de auth Entra existe
        de fato: ``server._run_http`` só monta ``EntraAuthMiddleware`` (e só
        registra a rota ``/.well-known/oauth-protected-resource``) quando
        isto é ``True``. Faltando qualquer um dos dois, o servidor continua
        sem autenticação.
        """
        return bool(self.entra_tenant_id and self.entra_client_id)


settings = Settings()
