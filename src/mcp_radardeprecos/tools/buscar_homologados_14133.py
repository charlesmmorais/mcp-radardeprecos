"""Tool MCP: itens/resultados homologados da Lei 14.133 em massa (Compras.gov.br)."""
from __future__ import annotations

import re
from typing import Any

from ..clients import compras_client
from ..logging_utils import get_logger
from ..utils.paginacao import extrair_paginacao

logger = get_logger(__name__)

_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_AVISO_SPEC = (
    "tool baseada na especificação OpenAPI oficial do módulo de contratações "
    "14.133 do Compras.gov.br; os "
    "registros são devolvidos como vêm da API (campos originais preservados), "
    "sem tradução de schema — valide os campos relevantes antes de decisões."
)

#: Verificado na especificação viva em 05/09/2026, endpoint por endpoint.
#:
#: O endpoint de CABEÇALHO das contratações (``1_consultarContratacoes``)
#: tem o filtro ``contratacaoExcluida``, e sem ele a API devolve as
#: contratações desconsideradas junto das válidas — medido em 980 registros
#: sem o filtro contra 978 com ``false`` e 2 com ``true``, na mesma janela.
#:
#: Os dois endpoints que ESTA tool usa — ``2_consultarItensContratacoes`` e
#: ``3_consultarResultadoItens`` — **não têm esse filtro nem trazem o campo
#: na resposta**. Ou seja: não há como excluir, aqui, os itens de uma
#: contratação que foi desconsiderada, e tampouco como identificá-los.
#:
#: Este aviso existe porque a alternativa seria calar sobre um limite real.
#: Os registros trazem ``situacaoCompraItem``/``situacaoCompraItemNome`` (no
#: modo por catálogo) e ``motivoCancelamento`` (no modo por fornecedor/órgão),
#: que são sinais de nível de ITEM — próximos, mas não equivalentes à
#: exclusão da contratação inteira.
_AVISO_CONTRATACAO_EXCLUIDA = (
    "LIMITE CONHECIDO: os endpoints de itens e de resultados da 14.133 não "
    "permitem filtrar nem identificar contratações DESCONSIDERADAS/EXCLUÍDAS "
    "— esse filtro só existe no endpoint de cabeçalho das contratações. Logo, "
    "esta lista pode conter itens de contratações posteriormente excluídas. "
    "Para uso como referência de preço, confira 'situacaoCompraItem' e "
    "'motivoCancelamento' nos registros e, em contratações decisivas, valide "
    "a compra no PNCP antes de compor a média."
)


async def buscar_homologados_14133(
    data_inicio: str,
    data_fim: str,
    codigo_item_catalogo: int | None = None,
    cnpj_fornecedor: str | None = None,
    cnpj_orgao: str | None = None,
    pagina: int = 1,
    limite: int = 20,
) -> dict[str, Any]:
    """Busca em MASSA itens homologados de contratações da Lei 14.133/2021.

    Complementa ``buscar_contratacoes_pncp`` (que obtém o valor homologado
    com uma chamada POR ITEM — N+1) com o índice consolidado do
    Compras.gov.br, em dois modos:

    - **Por código de catálogo** (``codigo_item_catalogo`` informado): itens
      de contratações com ``temResultado=True`` para aquele CATMAT/CATSER,
      na janela de INCLUSÃO no PNCP — mais uma fonte de preços por item de
      catálogo, além de ``buscar_precos_praticados_compras``.
    - **Por fornecedor/órgão** (sem ``codigo_item_catalogo``): resultados
      homologados na janela de RESULTADO, filtráveis por
      ``cnpj_fornecedor``/``cnpj_orgao`` — responde "o que o fornecedor X
      vendeu (e por quanto) no período" ou "o que o órgão Y homologou",
      análises que nenhuma outra tool deste servidor faz.

    Args:
        data_inicio: Início da janela (YYYY-MM-DD) — obrigatória na API.
        data_fim: Fim da janela (YYYY-MM-DD) — obrigatória na API.
        codigo_item_catalogo: Código CATMAT/CATSER; ativa o modo por catálogo.
        cnpj_fornecedor: CNPJ/CPF do fornecedor (modo por fornecedor/órgão).
        cnpj_orgao: CNPJ do órgão (ambos os modos).
        pagina: Página (1-indexada).
        limite: Registros por página (padrão 20, máximo 100 nesta tool).

    Returns:
        Dicionário com ``modo`` ("por_catalogo" ou "por_fornecedor_orgao"),
        ``pagina``, ``total_registros``, ``quantidade_retornada``,
        ``registros`` (campos ORIGINAIS da API, preservados) e ``avisos``.
    """
    for nome, valor in (("data_inicio", data_inicio), ("data_fim", data_fim)):
        if not valor or not _RE_DATA.match(str(valor)):
            raise ValueError(f"{nome} deve estar no formato YYYY-MM-DD (recebido {valor!r})")
    if codigo_item_catalogo is None and cnpj_fornecedor is None and cnpj_orgao is None:
        raise ValueError(
            "informe codigo_item_catalogo (modo por catálogo) e/ou "
            "cnpj_fornecedor/cnpj_orgao (modo por fornecedor/órgão) — sem nenhum "
            "filtro, a janela inteira seria varrida sem propósito de pesquisa de preços"
        )
    limite = max(1, min(limite, 100))
    pagina = max(1, pagina)
    logger.info(
        "buscar_homologados_14133 janela=%s..%s catalogo=%s fornecedor=%s orgao=%s pagina=%s",
        data_inicio, data_fim, codigo_item_catalogo, cnpj_fornecedor, cnpj_orgao, pagina,
    )

    avisos = [_AVISO_SPEC, _AVISO_CONTRATACAO_EXCLUIDA]
    if codigo_item_catalogo is not None:
        modo = "por_catalogo"
        if cnpj_fornecedor:
            avisos.append(
                "cnpj_fornecedor é ignorado no modo por catálogo (o endpoint de itens "
                "não filtra por fornecedor) — para filtrar por fornecedor, omita "
                "codigo_item_catalogo."
            )
        resposta = await compras_client.consultar_itens_14133(
            data_inclusao_inicial=data_inicio,
            data_inclusao_final=data_fim,
            codigo_item_catalogo=codigo_item_catalogo,
            tem_resultado=True,
            orgao_entidade_cnpj=cnpj_orgao,
            pagina=pagina,
            tamanho_pagina=limite,
        )
    else:
        modo = "por_fornecedor_orgao"
        resposta = await compras_client.consultar_resultados_itens_14133(
            data_resultado_inicial=data_inicio,
            data_resultado_final=data_fim,
            ni_fornecedor=cnpj_fornecedor,
            orgao_entidade_cnpj=cnpj_orgao,
            pagina=pagina,
            tamanho_pagina=limite,
        )

    registros = (resposta or {}).get("resultado", []) or []
    total = (resposta or {}).get("totalRegistros", len(registros))
    # total_paginas/numero_pagina/paginas_restantes
    # aditivos quando a fonte devolver — total_registros já existia (mantido).
    paginacao = extrair_paginacao(resposta)
    paginacao.pop("total_registros", None)
    return {
        "modo": modo,
        "pagina": pagina,
        "total_registros": total,
        "quantidade_retornada": len(registros[:limite]),
        "registros": registros[:limite],
        "avisos": avisos,
        **paginacao,
    }
