"""Tool MCP: lista itens individuais (código CATMAT/CATSER real) de um PDM ou classe."""
from __future__ import annotations

from typing import Any

from ..clients import compras_client
from ..domain.dominios import TIPOS_ITEM_CATALOGO_COMPRAS
from ..logging_utils import get_logger
from ..utils.paginacao import extrair_paginacao
from ..utils.texto_busca import (
    QUALIDADE_PARCIAL,
    classificar_correspondencia,
    normalizar_para_busca,
)

logger = get_logger(__name__)


async def listar_itens_catalogo(
    tipo_item: str,
    codigo: int,
    termo_filtro: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 50,
) -> dict[str, Any]:
    """Lista os itens individuais de uma categoria do catálogo, com filtro textual local.

    Completa o fluxo iniciado por ``descobrir_codigo_catalogo`` (que devolve
    PDMs/classes com só uma AMOSTRA de itens, e apenas para as 3 primeiras
    categorias): aqui você percorre TODOS os itens da categoria, paginando,
    até achar o ``codigo_item``/``codigo_servico`` exato para usar em
    ``buscar_precos_praticados_compras``. Fluxo típico (achado de uso real,
    v0.2.1): termo → classe CATSER → itens da classe → código do serviço →
    preços praticados.

    Args:
        tipo_item: "material" (itens de um PDM CATMAT) ou "servico" (itens
            de uma classe CATSER).
        codigo: Código do PDM (material) ou da classe (serviço) — os campos
            ``codigo_pdm``/``codigo_classe`` de ``descobrir_codigo_catalogo``.
        termo_filtro: Filtro textual LOCAL opcional sobre a descrição dos
            itens da página (tolerante a acento/maiúsculas, com fronteira de
            palavra — "TIC" não casa dentro de "plásTICo"). Aplica-se só aos
            itens da página retornada pela API, não ao catálogo inteiro.
        pagina: Página da API (1-indexada, padrão 1).
        tamanho_pagina: Itens por página (10–500, padrão 50).

    Returns:
        Dicionário com ``tipo_item``, ``codigo``, ``pagina``,
        ``total_registros`` (do catálogo, ANTES do filtro local),
        ``quantidade_retornada``, ``itens`` (cada um com
        ``codigo_item``/``codigo_servico`` e descrição/nome) e ``avisos``
        (ex.: quando o filtro local zera a página, sugerindo avançar
        ``pagina``).
    """
    if tipo_item not in TIPOS_ITEM_CATALOGO_COMPRAS:
        raise ValueError(f"tipo_item deve ser um de {TIPOS_ITEM_CATALOGO_COMPRAS}")
    pagina = max(1, pagina)
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    logger.info(
        "listar_itens_catalogo tipo_item=%s codigo=%s termo_filtro=%r pagina=%s",
        tipo_item, codigo, termo_filtro, pagina,
    )

    if tipo_item == "material":
        resposta = await compras_client.listar_itens_material_por_pdm(
            codigo, pagina=pagina, tamanho_pagina=tamanho_pagina
        )
        brutos = (resposta or {}).get("resultado", []) or []
        itens = [
            {"codigo_item": i.get("codigoItem"), "descricao_item": i.get("descricaoItem")}
            for i in brutos
        ]
        campo_texto = "descricao_item"
    else:
        resposta = await compras_client.listar_itens_servico_por_classe(
            codigo, pagina=pagina, tamanho_pagina=tamanho_pagina
        )
        brutos = (resposta or {}).get("resultado", []) or []
        itens = [
            {"codigo_servico": i.get("codigoServico"), "nome_servico": i.get("nomeServico")}
            for i in brutos
        ]
        campo_texto = "nome_servico"

    total_registros = (resposta or {}).get("totalRegistros", len(itens))
    avisos: list[str] = []

    if termo_filtro and termo_filtro.strip():
        termo_norm = normalizar_para_busca(termo_filtro)
        filtrados = [
            item for item in itens
            if classificar_correspondencia(termo_norm, normalizar_para_busca(item.get(campo_texto) or ""))
            not in (None, QUALIDADE_PARCIAL)
        ]
        if not filtrados and itens:
            avisos.append(
                f"o filtro local {termo_filtro!r} não casou com nenhum dos "
                f"{len(itens)} item(ns) desta página — o filtro é aplicado por página, "
                "não no catálogo inteiro; avance 'pagina' para continuar procurando "
                f"(total de {total_registros} registro(s) na categoria)."
            )
        itens = filtrados

    # total_paginas/numero_pagina/paginas_restantes
    # aditivos quando a fonte devolver — total_registros já existia (mantido).
    paginacao = extrair_paginacao(resposta)
    paginacao.pop("total_registros", None)

    return {
        "tipo_item": tipo_item,
        "codigo": codigo,
        "pagina": pagina,
        "total_registros": total_registros,
        "quantidade_retornada": len(itens),
        "itens": itens,
        "avisos": avisos,
        **paginacao,
    }
