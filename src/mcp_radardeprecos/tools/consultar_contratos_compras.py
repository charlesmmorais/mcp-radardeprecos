"""Tool MCP: consulta contratos (nível cabeçalho) no Compras.gov.br.

Módulo "09 - CONTRATOS" do Compras.gov.br (``/modulo-contratos/1_consultarContratos``)
— endpoint irmão de ``consultar_itens_contrato_compras``, mas com
uma linha por **contrato** em vez de por item. Implementada em v0.1.47 após
comparar ao vivo os campos deste endpoint com os da itemização: traz dados
que a itemização não tem — ``objeto`` (descrição completa do objeto
contratado), tipo/categoria do contrato, natureza (receita/despesa),
fundamento legal (``informacoes_complementares``) e parcelas — por isso não
é redundante com a tool de itens, apesar de ambas consultarem o mesmo
módulo/janela de vigência.

**Achado real (2026-07-10): ``codigo_orgao`` é obrigatório** — testado ao
vivo sem esse parâmetro (só com a janela de datas) e a API devolveu HTTP 404
"Resource not found", mesma armadilha de "parece sem resultados, mas é
parâmetro obrigatório ausente" já documentada em
``consultar_itens_contrato_compras``. Isso confirma o Swagger público
(https://dadosabertos.compras.gov.br/swagger-ui) e contraria o schema
declarado por um plugin MCP de terceiros, que marcava ``codigoOrgao`` como
opcional para este endpoint.

**Achado real: janela de vigência limitada a 365 dias** — mesma regra já
vista em ``consultar_arp``/``consultar_contratos_itens``.
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


def _formatar_contrato(bruto: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    formatado = {
        "numero_contrato": bruto.get("numeroContrato"),
        "objeto": bruto.get("objeto"),
        "tipo": bruto.get("nomeTipo"),
        "codigo_tipo": bruto.get("codigoTipo"),
        "categoria": bruto.get("nomeCategoria"),
        "codigo_categoria": bruto.get("codigoCategoria"),
        "subcategoria": bruto.get("nomeSubcategoria"),
        "receita_despesa": bruto.get("receitaDespesa"),
        "modalidade": bruto.get("nomeModalidadeCompra"),
        "numero_compra": bruto.get("numeroCompra"),
        "ni_fornecedor": mascarar_documento(bruto.get("niFornecedor")),
        "nome_fornecedor": bruto.get("nomeRazaoSocialFornecedor"),
        "codigo_orgao": bruto.get("codigoOrgao"),
        "nome_orgao": bruto.get("nomeOrgao"),
        "codigo_unidade_gestora": bruto.get("codigoUnidadeGestora"),
        "nome_unidade_gestora": bruto.get("nomeUnidadeGestora"),
        "data_vigencia_inicial": bruto.get("dataVigenciaInicial"),
        "data_vigencia_final": bruto.get("dataVigenciaFinal"),
        "valor_global": bruto.get("valorGlobal"),
        "numero_parcelas": bruto.get("numeroParcelas"),
        "valor_parcela": bruto.get("valorParcela"),
        "valor_acumulado": bruto.get("valorAcumulado"),
        "total_despesas_acessorias": bruto.get("totalDespesasAcessorias"),
        "processo": bruto.get("processo"),
        "informacoes_complementares": bruto.get("informacoesComplementares"),
        "contrato_excluido": bruto.get("contratoExcluido"),
        # v0.4.10: `contrato_excluido` sozinho não diz QUANDO deixou de valer —
        # sem a data não dá para saber se o contrato esteve vigente durante o
        # período analisado. `unidades_requisitantes` identifica quem demandou
        # (a UG que assina nem sempre é quem usa), e `id_compra` é a chave de
        # junção com a contratação de origem.
        "data_hora_exclusao": bruto.get("dataHoraExclusao"),
        "unidades_requisitantes": bruto.get("unidadesRequisitantes"),
        "id_compra": identificador(bruto.get("idCompra")),
        "numero_controle_pncp_contrato": bruto.get("numeroControlePncpContrato"),
        "numero_controle_pncp_compra": bruto.get("numeroControlePncpCompra"),
    }
    if incluir_bruto:
        formatado["dados_originais"] = bruto
    return formatado


async def consultar_contratos_compras(
    codigo_orgao: str | int,
    data_vigencia_inicial_min: str | None = None,
    data_vigencia_inicial_max: str | None = None,
    janela_dias: int = 365,
    ni_fornecedor: str | None = None,
    numero_contrato: str | None = None,
    codigo_modalidade_compra: str | None = None,
    codigo_tipo: str | None = None,
    codigo_categoria: str | None = None,
    codigo_unidade_gestora: str | None = None,
    limite: int = 50,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Consulta contratos (uma linha por contrato) de um órgão, por vigência.

    Fonte: módulo "09 - CONTRATOS" do Compras.gov.br, endpoint cabeçalho.
    Complementa ``consultar_itens_contrato_compras`` (que itemiza por preço
    unitário) trazendo o objeto completo do contrato, tipo/categoria,
    natureza (receita/despesa), fundamento legal e parcelas — dados que não
    aparecem na itemização. Use esta tool quando quiser entender "do que
    trata este contrato" ou levantar todos os contratos de um órgão num
    período; use ``consultar_itens_contrato_compras`` quando quiser preço
    unitário por item de catálogo.

    Args:
        codigo_orgao: Código do órgão com 5 dígitos, como texto (ex.: "03000";
            aceita 3000 e completa o zero). **Obrigatório** — não é o CNPJ; use
            ``descobrir_uasg`` com ``tipo="orgao"`` para descobrir o código a
            partir do nome).
        data_vigencia_inicial_min: Início do intervalo de vigência inicial
            do contrato (``AAAA-MM-DD``). Se omitido junto com
            ``data_vigencia_inicial_max``, usa os últimos ``janela_dias``
            dias a partir de hoje.
        data_vigencia_inicial_max: Fim do intervalo (``AAAA-MM-DD``). O
            Compras.gov.br rejeita (HTTP 400) intervalos maiores que 365
            dias — confirmado ao vivo.
        janela_dias: Tamanho da janela (dias) usada quando as datas acima
            não são informadas (padrão 365, o máximo aceito pela API).
        ni_fornecedor: Filtra por CNPJ/CPF do fornecedor.
        numero_contrato: Filtra por número de contrato específico.
        codigo_modalidade_compra: Código de modalidade **do Compras.gov.br**
            (diferente do código de modalidade do PNCP).
        codigo_tipo: Código do tipo de contrato (ex.: Contrato, Empenho,
            Concessão — ver campo ``tipo`` no retorno para os nomes).
        codigo_categoria: Código da categoria do contrato (ex.: Serviços,
            Compras, Cessão — ver campo ``categoria`` no retorno).
        codigo_unidade_gestora: Filtra por código da unidade gestora
            responsável pelo contrato.
        limite: Número máximo de contratos a retornar (padrão 50, máximo 100).

    Returns:
        Dicionário com ``contratos`` (lista, cada um com
        ``numero_controle_pncp_contrato``/``numero_controle_pncp_compra``
        prontos para uso em ``consultar_contratacao_pncp``/
        ``consultar_familia_contratacao_pncp`` do PNCP), ``total_no_periodo``
        (total reportado pelo Compras.gov.br antes do limite) e ``avisos``.

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
        "consultar_contratos_compras codigo_orgao=%s vigencia=%s..%s "
        "ni_fornecedor=%s limite=%s",
        codigo_orgao, data_vigencia_inicial_min, data_vigencia_inicial_max,
        ni_fornecedor, limite,
    )

    resposta = await compras_client.consultar_contratos(
        codigo_orgao=codigo_orgao,
        data_vigencia_inicial_min=data_vigencia_inicial_min,
        data_vigencia_inicial_max=data_vigencia_inicial_max,
        codigo_unidade_gestora=codigo_unidade_gestora,
        codigo_modalidade_compra=codigo_modalidade_compra,
        codigo_tipo=codigo_tipo,
        codigo_categoria=codigo_categoria,
        ni_fornecedor=ni_fornecedor,
        numero_contrato=numero_contrato,
        tamanho_pagina=max(10, limite),
    )
    brutos = (resposta or {}).get("resultado", []) or []
    total_no_periodo = (resposta or {}).get("totalRegistros", 0) or 0

    contratos = [_formatar_contrato(c, incluir_bruto) for c in brutos[:limite]]

    avisos: list[str] = []
    if total_no_periodo > len(contratos):
        avisos.append(
            f"O Compras.gov.br encontrou {total_no_periodo} contrato(s) no período/filtros "
            f"informados, mas só {len(contratos)} foram retornados (limite={limite}). "
            "Restrinja por ni_fornecedor/numero_contrato/codigo_tipo/codigo_categoria, ou "
            "aumente limite, se esperava mais resultados."
        )

    if not contratos:
        avisos.append(
            f"Nenhum registro para o órgão {codigo_orgao} com vigência inicial entre "
            f"{data_vigencia_inicial_min} e {data_vigencia_inicial_max}. Confira o código do "
            "órgão (5 dígitos, com zero à esquerda — ex.: '03000'), que não é o código da "
            "UASG nem o CNPJ; descobrir_uasg(tipo='orgao') mostra o código pelo nome."
        )

    # campos padronizados, aditivos —
    # total_no_periodo acima é mantido (nome antigo).
    return {
        "contratos": contratos,
        "total_no_periodo": total_no_periodo,
        "avisos": avisos,
        **extrair_paginacao(resposta),
    }
