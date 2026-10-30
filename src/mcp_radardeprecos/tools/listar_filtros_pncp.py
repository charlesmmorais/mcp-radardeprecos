"""Tool MCP: lista os filtros/facetas disponíveis na busca do PNCP.

Wrapper de ``/api/search/filters`` — o mesmo endpoint que o site do PNCP usa
para popular os menus de filtro nas páginas de busca (Editais, Atas,
Contratos). Útil para descobrir códigos válidos de modalidade, UF, órgão,
unidade e município antes de usar ``buscar_pncp_texto`` ou
``buscar_contratacoes_pncp`` com esses filtros — evita "achismo" de código.
"""
from __future__ import annotations

from typing import Any

from ..clients import pncp_client
from ..clients.base import UpstreamError
from ..domain.dominios import TIPOS_DOCUMENTO_BUSCA_PNCP
from ..logging_utils import get_logger

logger = get_logger(__name__)

# Facetas pequenas e estáveis (dezenas de itens) — sempre seguras de retornar por completo.
_FACETAS_PEQUENAS = (
    "modalidades",
    "ufs",
    "esferas",
    "poderes",
    "tipos",
    "tipos_contrato",
    "fontes_orcamentarias",
    "tipos_margens_preferencia",
    "anos",
)
# Facetas grandes (milhares de itens no índice nacional) — truncadas por padrão.
_FACETAS_GRANDES = ("orgaos", "unidades", "municipios")


async def listar_filtros_pncp(
    tipo_documento: str,
    campo: str | None = None,
    limite_por_campo: int = 30,
) -> dict[str, Any]:
    """Lista os filtros (facetas) disponíveis para um tipo de documento no PNCP.

    Args:
        tipo_documento: "edital", "ata" ou "contrato".
        campo: Nome de uma faceta específica a retornar por completo (ex.:
            "orgaos", "municipios"). Se omitido, retorna todas as facetas,
            com as grandes (órgãos/unidades/municípios) truncadas pelas de
            maior contagem — ver ``limite_por_campo``.
        limite_por_campo: Quantas entradas retornar por faceta grande quando
            ``campo`` não é informado (padrão 30, ordenadas por contagem
            decrescente). Ignorado se ``campo`` for informado.

    Returns:
        Dicionário no formato ``{"campo": [{"id"/"nome"/"total", ...}, ...]}``.
        As contagens (``total``) refletem o índice completo do PNCP, não uma
        busca textual específica.
    """
    if tipo_documento not in TIPOS_DOCUMENTO_BUSCA_PNCP:
        raise ValueError(f"tipo_documento deve ser um de {TIPOS_DOCUMENTO_BUSCA_PNCP}")

    logger.info("listar_filtros_pncp tipo=%s campo=%s", tipo_documento, campo)
    resultado = await pncp_client.listar_filtros(tipo_documento)  # type: ignore[arg-type]
    # Um dicionário vazio aqui seria lido como "este tipo de documento não tem
    # filtros", que é falso — todos têm. O cliente devolve None em 204 e em
    # corpo vazio, então o None significa que o índice não respondeu, não que
    # não há facetas.
    if resultado is None:
        raise UpstreamError(
            "pncp",
            None,
            f"o índice do PNCP não devolveu as facetas de '{tipo_documento}' "
            "(resposta sem conteúdo). Não é o mesmo que 'não há filtros' — "
            "tente novamente; se persistir, o índice pode estar indisponível.",
        )
    filtros: dict[str, Any] = resultado.get("filters", {})

    if campo:
        if campo not in filtros:
            raise ValueError(
                f"campo '{campo}' inválido. Campos disponíveis: {sorted(filtros.keys())}"
            )
        return {campo: filtros[campo]}

    saida: dict[str, Any] = {}
    for nome in _FACETAS_PEQUENAS:
        if nome in filtros:
            saida[nome] = filtros[nome]
    for nome in _FACETAS_GRANDES:
        valores = filtros.get(nome, [])
        saida[nome] = valores[:limite_por_campo]
        saida[f"{nome}_total_disponivel"] = len(valores)
    return saida
