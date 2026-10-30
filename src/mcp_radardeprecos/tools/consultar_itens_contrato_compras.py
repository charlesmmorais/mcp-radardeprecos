"""Tool MCP: consulta itens de contrato (preço unitário) no Compras.gov.br.

Módulo "09 - CONTRATOS" do Compras.gov.br (``/modulo-contratos/2_consultarContratosItem``)
— item priorizado pelo usuário (2026-07-10) após comparação com o Swagger
completo do módulo (https://dadosabertos.compras.gov.br/swagger-ui/index.html#/09%20-%20CONTRATOS)
e teste ao vivo confirmando valor real: nenhuma outra tool deste servidor
itemiza contratos por preço unitário — ``buscar_contratos_compras`` e
``consultar_contratos_orgao_pncp`` só trazem o valor global do contrato.

**Achado real: ``codigo_orgao`` é obrigatório** — testado ao vivo sem esse
parâmetro (só com janela de datas, inclusive uma janela de 6 anos) e a API
sempre devolveu HTTP 404 "Resource not found", que parecia sinalizar "sem
resultados" mas na verdade era parâmetro obrigatório ausente (mesma classe de
armadilha já documentada em outros endpoints deste módulo — ver
``docs/ARQUITETURA.md``/CHANGELOG). Confirmado funcionando com
``codigo_orgao=25201`` (Banco Central do Brasil) e uma janela de 365 dias.

**Achado real: janela de vigência limitada a 365 dias** — a API rejeita
(HTTP 400 "Período inicial e final maior que 365 dias") intervalos maiores,
mesma regra já vista em ``consultar_arp``/``buscar_arp_compras``.
"""
from __future__ import annotations

from typing import Any

from ..clients import compras_client
from ..logging_utils import get_logger
from ..utils.codigos import normalizar_codigo_orgao
from ..utils.datas import janela_dias_atras_iso
from ..utils.documentos import mascarar_documento
from ..utils.numeros import identificador
from ..utils.paginacao import extrair_paginacao

logger = get_logger(__name__)

_JANELA_MAXIMA_DIAS = 365
_LIMITE_MAXIMO = 100


def _formatar_item(bruto: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    """Projeta um item de contrato.

    **Limitação da fonte:** o endpoint NÃO devolve unidade de
    fornecimento nem unidade de medida — só ``quantidadeItem`` e
    ``valorUnitarioItem``. Isso significa que o "valor unitário" daqui não é
    diretamente comparável com o de ``buscar_precos_praticados_compras``, que
    traz a unidade praticada: dois itens com valores unitários diferentes
    podem estar na mesma unidade ou não, e a resposta não permite saber.
    Não é um campo descartado por este servidor; é ausência na origem.
    """
    formatado = {
        "numero_contrato": bruto.get("numeroContrato"),
        "numero_item": bruto.get("numeroItem"),
        "codigo_item": bruto.get("codigoItem"),
        "descricao_item": bruto.get("descricaoIitem"),
        "tipo_item": bruto.get("tipoItem"),
        "quantidade_item": bruto.get("quantidadeItem"),
        "valor_unitario_item": bruto.get("valorUnitarioItem"),
        "valor_total_item": bruto.get("valorTotalItem"),
        "valor_global_contrato": bruto.get("valorGlobal"),
        "ni_fornecedor": mascarar_documento(bruto.get("niFornecedor")),
        "nome_fornecedor": bruto.get("nomeRazaoSocialFornecedor"),
        "codigo_orgao": bruto.get("codigoOrgao"),
        "nome_orgao": bruto.get("nomeOrgao"),
        "codigo_unidade_gestora": bruto.get("codigoUnidadeGestora"),
        "nome_unidade_gestora": bruto.get("nomeUnidadeGestora"),
        "modalidade": bruto.get("nomeModalidadeCompra"),
        "numero_compra": bruto.get("numeroCompra"),
        "data_vigencia_inicial": bruto.get("dataVigenciaInicial"),
        "data_vigencia_final": bruto.get("dataVigenciaFinal"),
        "processo": bruto.get("processo"),
        "poder": bruto.get("poder"),
        "esfera": bruto.get("esfera"),
        "contrato_excluido": bruto.get("contratoExcluido"),
        "item_excluido": bruto.get("contratoItemExcluido"),
        "numero_controle_pncp_contrato": bruto.get("numeroControlePncpContrato"),
        "numero_controle_pncp_compra": bruto.get("numeroControlePncpCompra"),
        "id_compra": identificador(bruto.get("idCompra")),
        "data_hora_exclusao_item": bruto.get("dataHoraExclusaoItem"),
        "data_hora_exclusao_contrato": bruto.get("dataHoraExclusaoContrato"),
    }
    if incluir_bruto:
        formatado["dados_originais"] = bruto
    return formatado


async def consultar_itens_contrato_compras(
    codigo_orgao: str,
    data_vigencia_inicial_min: str | None = None,
    data_vigencia_inicial_max: str | None = None,
    janela_dias: int = 365,
    codigo_item: int | None = None,
    tipo_item: str | None = None,
    ni_fornecedor: str | None = None,
    numero_contrato: str | None = None,
    codigo_modalidade_compra: str | None = None,
    codigo_unidade_gestora: str | None = None,
    limite: int = 50,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Consulta itens de contrato (preço unitário) de um órgão, por vigência.

    Fonte: módulo "09 - CONTRATOS" do Compras.gov.br. Complementa
    ``buscar_contratos_compras``/``consultar_contratos_orgao_pncp`` (que só
    trazem o valor **global** do contrato) trazendo o preço **unitário por
    item**, com o código de catálogo (CATMAT/CATSER) — uma fonte de preço de
    referência real (contrato já assinado, não estimado) na granularidade de
    item.

    Args:
        codigo_orgao: Código do órgão com 5 dígitos, como texto (ex.: "03000";
            aceita 3000 e completa o zero). **Obrigatório** — não é o CNPJ; use
            ``descobrir_uasg`` com ``tipo="orgao"`` para descobrir o código a
            partir do nome, ou o campo ``codigo_orgao`` já devolvido por
            outras tools deste servidor, ex.: ``buscar_arp_compras``).
        data_vigencia_inicial_min: Início do intervalo de vigência inicial
            do contrato (``AAAA-MM-DD``). Se omitido junto com
            ``data_vigencia_inicial_max``, usa os últimos ``janela_dias``
            dias a partir de hoje.
        data_vigencia_inicial_max: Fim do intervalo (``AAAA-MM-DD``). O
            Compras.gov.br rejeita (HTTP 400) intervalos maiores que 365
            dias — confirmado ao vivo.
        janela_dias: Tamanho da janela (dias) usada quando as datas acima
            não são informadas (padrão 365, o máximo aceito pela API).
        codigo_item: Filtra por um código de item de catálogo
            (CATMAT/CATSER) específico — use para "qual o preço deste item
            nos contratos deste órgão".
        tipo_item: Filtra por tipo do item (ex.: "Material" ou "Serviço").
        ni_fornecedor: Filtra por CNPJ/CPF do fornecedor.
        numero_contrato: Filtra por número de contrato específico.
        codigo_modalidade_compra: Código de modalidade **do Compras.gov.br**
            (diferente do código de modalidade do PNCP — ver
            ``buscar_arp_compras`` para a mesma ressalva).
        codigo_unidade_gestora: Filtra por código da unidade gestora
            responsável pelo contrato.
        limite: Número máximo de itens a retornar (padrão 50, máximo 100).

    Returns:
        Dicionário com ``itens`` (lista, cada um com ``numero_controle_pncp_contrato``/
        ``numero_controle_pncp_compra`` prontos para uso em
        ``consultar_contratacao_pncp``/``consultar_familia_contratacao_pncp``
        do PNCP), ``total_no_periodo`` (total reportado pelo Compras.gov.br
        antes do limite) e ``avisos``.

    Raises:
        ValueError: se só uma das datas de vigência for informada, ou se
            ``janela_dias`` ultrapassar 365.
    """
    codigo_orgao = normalizar_codigo_orgao(codigo_orgao)
    if not codigo_orgao:
        raise ValueError("codigo_orgao é obrigatório (ex.: '03000' para o TCU)")
    if (data_vigencia_inicial_min is None) != (data_vigencia_inicial_max is None):
        raise ValueError(
            "informe data_vigencia_inicial_min e data_vigencia_inicial_max juntos, "
            "ou nenhum dos dois (para usar a janela padrão)"
        )
    if data_vigencia_inicial_min is None:
        janela_dias = max(1, min(janela_dias, _JANELA_MAXIMA_DIAS))
        data_vigencia_inicial_min, data_vigencia_inicial_max = janela_dias_atras_iso(janela_dias)

    limite = max(1, min(limite, _LIMITE_MAXIMO))

    logger.info(
        "consultar_itens_contrato_compras codigo_orgao=%s vigencia=%s..%s codigo_item=%s "
        "ni_fornecedor=%s limite=%s",
        codigo_orgao, data_vigencia_inicial_min, data_vigencia_inicial_max, codigo_item,
        ni_fornecedor, limite,
    )

    resposta = await compras_client.consultar_contratos_itens(
        codigo_orgao=codigo_orgao,
        data_vigencia_inicial_min=data_vigencia_inicial_min,
        data_vigencia_inicial_max=data_vigencia_inicial_max,
        codigo_item=codigo_item,
        tipo_item=tipo_item,
        ni_fornecedor=ni_fornecedor,
        numero_contrato=numero_contrato,
        codigo_modalidade_compra=codigo_modalidade_compra,
        codigo_unidade_gestora=codigo_unidade_gestora,
        tamanho_pagina=max(10, limite),
    )
    brutos = (resposta or {}).get("resultado", []) or []
    total_no_periodo = (resposta or {}).get("totalRegistros", 0) or 0

    itens = [_formatar_item(i, incluir_bruto) for i in brutos[:limite]]

    avisos: list[str] = []
    if total_no_periodo > len(itens):
        avisos.append(
            f"O Compras.gov.br encontrou {total_no_periodo} item(ns) no período/filtros "
            f"informados, mas só {len(itens)} foram retornados (limite={limite}). "
            "Restrinja por codigo_item/ni_fornecedor/numero_contrato, ou aumente limite, "
            "se esperava mais resultados."
        )

    if not itens:
        avisos.append(
            f"Nenhum registro para o órgão {codigo_orgao} com vigência inicial entre "
            f"{data_vigencia_inicial_min} e {data_vigencia_inicial_max}. Confira o código do "
            "órgão (5 dígitos, com zero à esquerda — ex.: '03000'), que não é o código da "
            "UASG nem o CNPJ; descobrir_uasg(tipo='orgao') mostra o código pelo nome."
        )

    # campos padronizados, aditivos —
    # total_no_periodo acima é mantido (nome antigo).
    return {
        "itens": itens,
        "total_no_periodo": total_no_periodo,
        "avisos": avisos,
        **extrair_paginacao(resposta),
    }
