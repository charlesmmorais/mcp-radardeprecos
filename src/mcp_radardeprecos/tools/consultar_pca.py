"""Tool MCP: consulta itens do Plano de Contratação Anual (PCA).

Preenche a fase de **Planejamento** do guia de pesquisa de preços (ver
o guia de boas práticas de pesquisa de preços) com um sinal antecipado do que os
órgãos públicos pretendem comprar — o PCA é uma exigência da Lei 14.133/2021
(art. 12) e é publicado antes de qualquer licitação. Endpoints confirmados
contra o OpenAPI oficial do PNCP (``/api/consulta/v3/api-docs``); ver
``clients/pncp_client.consultar_pca_por_classificacao``/
``consultar_pca_por_periodo``.
"""
from __future__ import annotations

from typing import Any

from ..clients import pncp_client
from ..logging_utils import get_logger

logger = get_logger(__name__)

_AVISO_ESTIMATIVA = (
    "valor_unitario_estimado e valor_total_estimado do PCA são estimativas "
    "orçamentárias internas do órgão (planejamento da futura contratação), NÃO "
    "preços efetivamente pagos/homologados — não usar como entrada de "
    "calcular_preco_referencia. O PCA serve só como sinal antecipado do que será "
    "comprado (fase de Planejamento do guia); para referência de preço válida, "
    "use buscar_contratacoes_pncp/consultar_resultado_item, "
    "buscar_precos_praticados_compras ou consultar_ata_registro_preco."
)


def _flatten_itens_pca(entradas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    itens_planejados: list[dict[str, Any]] = []
    for entrada in entradas:
        contexto = {
            "orgao": entrada.get("orgaoEntidadeRazaoSocial"),
            "cnpj_orgao": entrada.get("orgaoEntidadeCnpj"),
            "codigo_unidade": entrada.get("codigoUnidade"),
            "nome_unidade": entrada.get("nomeUnidade"),
            "ano_pca": entrada.get("anoPca"),
            "data_publicacao_pncp": entrada.get("dataPublicacaoPNCP"),
        }
        for item in entrada.get("itens") or []:
            itens_planejados.append(
                {
                    **contexto,
                    "descricao": item.get("descricaoItem"),
                    "quantidade_estimada": item.get("quantidadeEstimada"),
                    "valor_unitario_estimado": item.get("valorUnitario"),
                    "valor_total_estimado": item.get("valorTotal"),
                    "unidade_fornecimento": item.get("unidadeFornecimento"),
                    "data_desejada": item.get("dataDesejada"),
                    "codigo_item": item.get("codigoItem"),
                    "classificacao_catalogo": (
                        item.get("classificacaoSuperiorNome") or item.get("pdmDescricao")
                    ),
                    "codigo_classificacao": (
                        item.get("classificacaoSuperiorCodigo") or item.get("pdmCodigo")
                    ),
                    "categoria_item_pca": item.get("categoriaItemPcaNome"),
                }
            )
    return itens_planejados


async def consultar_pca(
    ano_pca: int | None = None,
    codigo_classificacao_superior: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    cnpj_orgao: str | None = None,
    codigo_unidade: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 500,
) -> dict[str, Any]:
    """Consulta itens planejados no PCA (Plano de Contratação Anual) de órgãos públicos.

    Use um dos dois modos de busca, mutuamente exclusivos:

    1. **Por classificação de catálogo** (``ano_pca`` +
       ``codigo_classificacao_superior``): busca em todos os órgãos que
       planejaram comprar algo daquela classe de material (CATMAT) ou grupo
       de serviço (CATSER) naquele ano. Use ``descobrir_codigo_catalogo``
       para achar o código a partir de uma descrição textual (ex.:
       "notebook"). Este modo não filtra por órgão.
    2. **Por período + CNPJ do órgão** (``data_inicio`` + ``data_fim``, com
       ``cnpj_orgao``/``codigo_unidade`` opcionais): busca por data de
       atualização global do PCA, restringindo a um órgão/unidade específico
       quando informado. Use este modo quando já se sabe QUEM se quer
       consultar, em vez de QUAL item.

    **Atenção — PCA não é referência de preço válida:** os valores do PCA
    (``valor_unitario_estimado``/``valor_total_estimado``) são estimativas
    orçamentárias do órgão para o planejamento da contratação futura, feitas
    antes de qualquer disputa — análogas ao ``valorUnitarioEstimado`` do
    endpoint de itens de uma contratação (ver nota crítica em
    ``clients/pncp_client.py``), não ao valor efetivamente homologado. Use o
    PCA para saber O QUE será comprado e ter uma primeira noção de
    orçamento (fase de Planejamento), não como entrada de
    ``calcular_preco_referencia``.

    Args:
        ano_pca: Ano do PCA (ex.: 2026). Obrigatório junto com
            ``codigo_classificacao_superior`` no modo por classificação.
        codigo_classificacao_superior: Código da classe de material (CATMAT)
            ou grupo de serviço (CATSER), conforme catálogo — ver
            ``descobrir_codigo_catalogo``.
        data_inicio: Início do período de atualização global do PCA, formato
            ``AAAAMMDD``. Obrigatório junto com ``data_fim`` no modo por
            período.
        data_fim: Fim do período, formato ``AAAAMMDD``.
        cnpj_orgao: CNPJ do órgão (14 posições) — só válido no modo por
            período; restringe a esse órgão.
        codigo_unidade: Código da unidade do órgão — só válido no modo por
            período, junto com ou em vez de ``cnpj_orgao``.
        pagina: Página dos resultados (padrão 1).
        tamanho_pagina: Registros por página (10-500, padrão 500 — limite da
            própria API).

    Returns:
        Dicionário com ``itens_planejados`` (lista achatada: cada item do
        PCA de cada órgão retornado, com o contexto do órgão/unidade
        embutido — ``orgao``, ``cnpj_orgao``, ``nome_unidade``, ``ano_pca``,
        ``data_publicacao_pncp``, ``descricao``, ``quantidade_estimada``,
        ``valor_unitario_estimado``, ``valor_total_estimado``,
        ``unidade_fornecimento``, ``data_desejada``, ``codigo_item``,
        ``classificacao_catalogo``, ``codigo_classificacao``,
        ``categoria_item_pca``), ``total_registros``, ``pagina``,
        ``total_paginas`` e ``avisos`` (sempre inclui o aviso sobre os
        valores serem estimativas orçamentárias, não preços válidos).
    """
    modo_classificacao = ano_pca is not None or codigo_classificacao_superior is not None
    modo_periodo = data_inicio is not None or data_fim is not None

    if modo_classificacao and modo_periodo:
        raise ValueError(
            "Use OU (ano_pca + codigo_classificacao_superior) OU (data_inicio + data_fim "
            "[+ cnpj_orgao/codigo_unidade]) — não os dois modos ao mesmo tempo."
        )

    if modo_classificacao:
        if ano_pca is None or not codigo_classificacao_superior:
            raise ValueError(
                "No modo por classificação, informe ano_pca E codigo_classificacao_superior juntos."
            )
        if cnpj_orgao is not None or codigo_unidade is not None:
            raise ValueError(
                "cnpj_orgao/codigo_unidade só se aplicam ao modo por período "
                "(data_inicio/data_fim) — o endpoint por classificação não filtra por órgão."
            )
        logger.info(
            "consultar_pca modo=classificacao ano_pca=%s codigo_classificacao_superior=%s",
            ano_pca, codigo_classificacao_superior,
        )
        resultado_bruto = await pncp_client.consultar_pca_por_classificacao(
            ano_pca, codigo_classificacao_superior, pagina=pagina, tamanho_pagina=tamanho_pagina,
        )
    elif modo_periodo:
        if not data_inicio or not data_fim:
            raise ValueError("No modo por período, informe data_inicio E data_fim juntos.")
        logger.info(
            "consultar_pca modo=periodo data_inicio=%s data_fim=%s cnpj_orgao=%s",
            data_inicio, data_fim, cnpj_orgao,
        )
        resultado_bruto = await pncp_client.consultar_pca_por_periodo(
            data_inicio, data_fim, cnpj=cnpj_orgao, codigo_unidade=codigo_unidade,
            pagina=pagina, tamanho_pagina=tamanho_pagina,
        )
    else:
        raise ValueError(
            "Informe um dos dois modos: (ano_pca + codigo_classificacao_superior) para buscar "
            "por classificação de catálogo, ou (data_inicio + data_fim) para buscar por "
            "período/CNPJ do órgão."
        )

    # 204/corpo vazio (o cliente devolve None) significa "nenhum item de PCA
    # para estes filtros" — resposta legítima, já coberta pelo aviso de lista
    # vazia mais abaixo. Sem esta guarda, virava
    # 'NoneType' object has no attribute 'get'.
    #
    # Normalizado numa linha só, e não em cada `.get` adiante: a primeira
    # versão desta correção protegeu apenas o `.get("data")` e deixou passar
    # os três `.get` do dicionário de retorno, logo abaixo. Guarda por ponto
    # de uso é frágil — basta alguém acrescentar um campo novo.
    resultado_bruto = resultado_bruto or {}
    entradas = resultado_bruto.get("data") or []
    itens_planejados = _flatten_itens_pca(entradas)

    avisos = [_AVISO_ESTIMATIVA]
    if not itens_planejados:
        avisos.append("Nenhum item de PCA encontrado para os filtros informados.")

    return {
        "itens_planejados": itens_planejados,
        "total_registros": resultado_bruto.get("totalRegistros", 0),
        "pagina": resultado_bruto.get("numeroPagina", pagina),
        "total_paginas": resultado_bruto.get("totalPaginas", 0),
        "avisos": avisos,
    }
