"""Cliente da consulta consolidada de Pessoa Jurídica do TCU (due diligence de fornecedor).

Endpoint público, sem credencial (mesmo perfil das demais fontes do projeto):
``GET https://certidoes-apf.apps.tcu.gov.br/api/rest/publico/certidoes/{cnpj}``
com ``seEmitirPDF=false``. Confirmado ao vivo nesta sessão (2026-07-25).

O grande valor desta fonte — motivo de ela virar tool própria em vez de mais
uma consulta ao Portal da Transparência — é que **uma única chamada agrega
quatro bases de sanção/idoneidade de três órgãos diferentes**, o próprio TCU
fazendo a orquestração server-side:

- **TCU — Licitantes Inidôneos** (impedidos de licitar por decisão do TCU);
- **CNJ — CNIA** (Cadastro Nacional de Condenações Cíveis por Ato de
  Improbidade Administrativa e Inelegibilidade);
- **Portal da Transparência — CEIS** (Cadastro Nacional de Empresas
  Inidôneas e Suspensas);
- **Portal da Transparência — CNEP** (Cadastro Nacional de Empresas Punidas).

Consequência prática importante: **CEIS e CNEP são consultados aqui SEM
precisar da chave de API do Portal da Transparência** — o TCU faz essa ponte.
Isso torna a verificação de sanções acessível sem gerenciar credencial de
terceiro (a chave pessoal do Portal da Transparência, com rate limit por
chave, deixa de ser um pré-requisito para o caso de uso mais comum).

Formato de resposta confirmado ao vivo::

    {
      "cnpj": "33.683.111/0001-07",
      "razaoSocial": "Serviço Federal de Processamento de Dados",
      "nomeFantasia": "Empresa Exemplo",
      "uf": null,
      "seCnpjEncontradoNaBaseTcu": true,
      "dataHoraGeracaoInMillis": 1785025358845,
      "certidaoPDF": null,          # base64 do PDF quando seEmitirPDF=true
      "certidoes": [
        {"tipo": "Inidôneos", "descricao": "...", "emissor": "TCU",
         "situacao": "NADA_CONSTA", "observacao": null,
         "dataHoraEmissao": "25/07/2026 21:22",
         "linkConsultaManual": "https://...", "tempoGeracao": 16},
        ... (CNIA, CEIS, CNEP)
      ]
    }

Um CNPJ inexistente/inválido devolve corpo vazio (não um JSON) — tratado como
:class:`~mcp_radardeprecos.clients.base.UpstreamError` por
:func:`~mcp_radardeprecos.clients.base.get_json` (204/JSON vazio) e
convertido aqui num erro claro.

Cache curto (30 min): sanção é relativamente estável, mas é um dado de
decisão (aceitar ou não uma cotação/contratação) — não convém servir um
"nada consta" de horas atrás. Cada chamada ao endpoint dispara consultas ao
vivo às quatro bases (visível no campo ``tempoGeracao`` por fonte), então
evitar refazê-la na mesma pesquisa também poupa o upstream.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..utils.cache import TTL_30_MIN
from .base import UpstreamError, get_json

SOURCE = "TCU/certidoes-apf"


async def consultar_certidoes_pj(cnpj: str) -> dict[str, Any]:
    """Consulta consolidada de PJ do TCU para ``cnpj`` (14 posições, já limpo).

    ``cnpj`` deve vir só com dígitos (use
    :func:`~mcp_radardeprecos.clients.cnpj_client.limpar_cnpj` antes).
    Não pede o PDF (``seEmitirPDF=false``) — a tool consome o JSON estruturado.

    Returns:
        O dicionário cru da API (ver o módulo para o formato).

    Raises:
        UpstreamError: rede/timeout/5xx (via ``get_json``), ou resposta vazia
            (CNPJ inexistente/inválido na base — o endpoint devolve corpo
            vazio nesse caso).
    """
    dados = await get_json(
        settings.tcu_certidoes_base_url,
        f"/api/rest/publico/certidoes/{cnpj}",
        {"seEmitirPDF": "false"},
        source=SOURCE,
        cache_key=f"tcu:certidoes:{cnpj}",
        cache_ttl_seconds=TTL_30_MIN,
        # Fonte lenta para CNPJ COM registro (busca ao vivo em 4 bases) —
        # timeout maior e dedicado, sem afetar as demais fontes.
        timeout_seconds=settings.tcu_timeout_seconds,
    )
    if not dados or not isinstance(dados, dict):
        raise UpstreamError(
            SOURCE,
            None,
            f"CNPJ {cnpj} não retornou dados na consulta consolidada do TCU "
            "(resposta vazia) — CNPJ inexistente, inválido, ou serviço "
            "indisponível no momento (o TCU avisa possível indisponibilidade "
            "das 20h às 21h).",
        )
    return dados
