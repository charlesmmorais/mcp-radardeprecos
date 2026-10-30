"""Tool MCP: busca o detalhe completo de uma contratação já conhecida no PNCP."""
from __future__ import annotations

import asyncio
from typing import Any

from ..clients import pncp_client
from ..clients.base import UpstreamError
from ..logging_utils import get_logger

logger = get_logger(__name__)

_RECOMENDACAO = {
    "contrato": (
        "É um CONTRATO (tipo 2). Para contratos use consultar_contratos_orgao_pncp "
        "(contratos de um órgão por CNPJ + período) ou "
        "consultar_familia_contratacao_pncp (consolida edital + ata + contratos)."
    ),
    "ata": (
        "É uma ATA de registro de preço. Use consultar_ata_registro_preco."
    ),
    "desconhecido": (
        "Formato não reconhecido. Esperado CNPJ-1-SEQUENCIAL/ANO (contratação), "
        "ex.: 33683111000107-1-000084/2025."
    ),
}


def _erro_instrumento(numero_controle_pncp: str, tipo_instrumento: str) -> dict[str, Any]:
    """Erro ESTRUTURADO (não-exceção) de instrumento incompatível.

    Devolvido em vez de ``raise`` para que a mensagem chegue como resposta
    funcional auditável no transporte streamable-http (uma exceção aqui estava
    virando "Session terminated" no cliente, sem erro claro — achado real
    2026-07-29). Não faz nenhuma consulta: garante que NUNCA se devolve a
    contratação de mesmo sequencial (objeto diferente) por engano.
    """
    logger.info(
        "consultar_contratacao_pncp: instrumento incompatível numero=%s tipo=%s",
        numero_controle_pncp, tipo_instrumento,
    )
    return {
        "erro": "instrumento_incompativel",
        "numero_controle_pncp": numero_controle_pncp,
        "instrumento_detectado": tipo_instrumento,
        "esperado": "contratacao (formato CNPJ-1-SEQUENCIAL/ANO)",
        "mensagem": (
            f"O número informado não é de uma contratação (detectado: "
            f"{tipo_instrumento}). Esta tool consulta apenas contratações "
            "(editais/compras, tipo 1); nenhuma consulta foi feita para não "
            "retornar um objeto diferente por engano."
        ),
        "recomendacao": _RECOMENDACAO.get(tipo_instrumento, _RECOMENDACAO["desconhecido"]),
    }


async def consultar_contratacao_pncp(
    numero_controle_pncp: str | None = None,
    cnpj: str | None = None,
    ano: int | None = None,
    sequencial: int | None = None,
    incluir_itens: bool = False,
) -> dict[str, Any]:
    """Busca o detalhe completo de uma contratação já conhecida (por ID), via API oficial.

    Complementa ``buscar_contratacoes_pncp`` (que só encontra contratações
    via busca textual) para o caso em que você já sabe qual contratação
    quer — por exemplo, uma que apareceu numa ata (``consultar_ata_registro_preco``)
    ou num contrato (``buscar_contratos_compras``). Usa a API de
    Consulta oficial (``/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}``),
    confirmada ao vivo contra a
    especificação OpenAPI oficial.

    Traz campos que **não** vêm da busca textual nem do endpoint de itens:
    ``srp`` (se é uma contratação por Sistema de Registro de Preços —
    relevante para saber se ela pode ter atas associadas),
    ``valor_total_homologado`` (já agregado no nível da contratação, sem
    precisar somar item a item), ``modo_disputa``, ``amparo_legal`` e as
    datas de abertura/encerramento de proposta.

    Também traz ``link_sistema_origem`` — o link direto
    para a página de acompanhamento da contratação no sistema de origem
    (ex.: ComprasNet-web/Compras.gov.br, quando a contratação foi feita por
    lá) — e ``link_processo_eletronico`` (quando o órgão usa um processo
    eletrônico externo, ex.: SEI). O link de "Acompanhar Contratação" do
    ComprasNet-web é útil, mas essa página específica é protegida por captcha (hCaptcha) em
    todas as chamadas de API por trás dela — não dá para automatizar a
    coleta de dados de lá — mas o **link para abrir a página num navegador**
    já vem pronto, sem captcha, direto do campo ``linkSistemaOrigem`` da API
    de Consulta oficial do PNCP (confirmado ao vivo). É só um link para o
    usuário clicar e ver a página com seus próprios olhos — não é o mesmo
    que consultar aquela API.

    Também traz ``link_pagina_pncp`` — o link direto para a
    própria página do edital no site do PNCP (``pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}``),
    construído localmente a partir de ``cnpj``/``ano``/``sequencial`` (não
    depende de nenhum campo devolvido pela API). Motivo: um cliente MCP
    (ChatGPT, testado ao vivo) tinha tentado montar esse mesmo link sozinho e
    errado, inserindo um segmento ``/compras/`` a mais
    (``.../app/editais/compras/{cnpj}/...``, formato que não existe e dá erro
    no site) — construir o link certo aqui, uma vez, elimina esse risco de
    adivinhação em qualquer cliente.

    Identifique a contratação de uma das duas formas:

    1. ``numero_controle_pncp``: a string completa no formato
       ``CNPJ-1-SEQUENCIAL/ANO`` (ex.: ``33683111000107-1-000084/2025``);
       **ou**
    2. os três parâmetros discretos ``cnpj``/``ano``/``sequencial``
       separadamente.

    **Valida o tipo de instrumento:** o dígito de tipo do
    número de controle é conferido. Se você passar por engano um número de
    **contrato** (``-2-``) ou de **ata** (formato com um segmento a mais), a
    tool **devolve um erro estruturado e auditável** (dict com ``erro``,
    ``instrumento_detectado``, ``mensagem`` e ``recomendacao`` apontando a tool
    correta) — em vez de devolver silenciosamente a contratação de mesmo
    sequencial (que é um objeto diferente). Desde a v0.3.16 é um RETORNO, não
    uma exceção, para chegar como resposta funcional no transporte HTTP (uma
    exceção estava virando "Session terminated" sem erro claro). Corrige
    achados reais (2026-07-28 e 2026-07-29).

    Args:
        numero_controle_pncp: Número de controle completo (ver acima). Se
            informado, os 3 parâmetros discretos são ignorados.
        cnpj: CNPJ do órgão (14 posições), se não usar ``numero_controle_pncp``.
        ano: Ano da contratação.
        sequencial: Sequencial da contratação.
        incluir_itens: Se True, busca também os itens da contratação (via
            ``consultar_itens_contratacao`` — mesma tool interna usada por
            ``buscar_contratacoes_pncp``, sem o valor homologado por item;
            use ``buscar_contratacoes_pncp`` se precisar do homologado).

    Returns:
        Dicionário com ``numero_controle_pncp``, ``numero_compra``,
        ``processo``, ``orgao``/``cnpj_orgao``, ``uf``, ``modalidade``,
        ``modo_disputa``, ``srp``, ``objeto``, ``valor_total_estimado``,
        ``valor_total_homologado``, ``situacao``, ``amparo_legal``,
        ``data_publicacao_pncp``, ``data_abertura_proposta``,
        ``data_encerramento_proposta``, ``link_sistema_origem``,
        ``link_processo_eletronico``, ``link_pagina_pncp`` e, se
        ``incluir_itens``, a lista ``itens``.
    """
    if numero_controle_pncp:
        # Valida o TIPO de instrumento antes de consultar — sem isso, um
        # número de CONTRATO (-2-) ou de ATA era "parseado" só por
        # cnpj/ano/sequencial e caía no endpoint de contratação, devolvendo
        # SILENCIOSAMENTE um objeto diferente (achado real 2026-07-28).
        #
        # Retorna um ERRO ESTRUTURADO (dict), NÃO levanta exceção: no
        # transporte streamable-http, um erro de instrumento incompatível
        # precisa chegar como resposta funcional auditável ao usuário, e não
        # como "Session terminated" (achado real 2026-07-29). Ver
        # _erro_instrumento.
        tipo_instrumento = pncp_client.classificar_numero_controle_pncp(
            numero_controle_pncp
        )
        parsed = pncp_client.parse_numero_controle_pncp(numero_controle_pncp)
        if tipo_instrumento != "contratacao" or not parsed:
            return _erro_instrumento(numero_controle_pncp, tipo_instrumento)
        cnpj, ano, sequencial = parsed
    elif not all(v is not None for v in (cnpj, ano, sequencial)):
        raise ValueError(
            "Informe numero_controle_pncp OU os 3 parâmetros discretos "
            "(cnpj, ano, sequencial)."
        )

    logger.info(
        "consultar_contratacao_pncp cnpj=%s ano=%s sequencial=%s incluir_itens=%s",
        cnpj, ano, sequencial, incluir_itens,
    )

    if incluir_itens:
        detalhe, itens_brutos = await asyncio.gather(
            pncp_client.consultar_contratacao_detalhe(cnpj, ano, sequencial),
            pncp_client.consultar_itens_contratacao(cnpj, ano, sequencial),
        )
    else:
        detalhe = await pncp_client.consultar_contratacao_detalhe(cnpj, ano, sequencial)
        itens_brutos = None

    # Aqui o None NÃO é "vazio legítimo": o cliente devolve None em 204 e em
    # corpo vazio, e para a consulta de UMA contratação específica isso
    # significa que ela não foi encontrada. Um `detalhe or {}` produziria um
    # registro com todos os campos None — indistinguível, para quem lê, de
    # uma contratação real mal preenchida. Falha em voz alta.
    if detalhe is None:
        raise UpstreamError(
            "pncp",
            None,
            f"contratação {cnpj}/{ano}/{sequencial} não encontrada no PNCP "
            "(a fonte respondeu sem conteúdo). Confira CNPJ, ano e sequencial "
            "— o sequencial é por órgão e por ano, não é o número do edital.",
        )

    amparo_legal_bruto = detalhe.get("amparoLegal") or {}
    resultado: dict[str, Any] = {
        "numero_controle_pncp": detalhe.get("numeroControlePNCP"),
        "numero_compra": detalhe.get("numeroCompra"),
        "processo": detalhe.get("processo"),
        "orgao": (detalhe.get("orgaoEntidade") or {}).get("razaoSocial"),
        "cnpj_orgao": (detalhe.get("orgaoEntidade") or {}).get("cnpj"),
        "uf": (detalhe.get("unidadeOrgao") or {}).get("ufSigla"),
        "municipio": (detalhe.get("unidadeOrgao") or {}).get("municipioNome"),
        "modalidade": detalhe.get("modalidadeNome"),
        "modo_disputa": detalhe.get("modoDisputaNome"),
        "srp": detalhe.get("srp"),
        "objeto": detalhe.get("objetoCompra"),
        "valor_total_estimado": detalhe.get("valorTotalEstimado"),
        "valor_total_homologado": detalhe.get("valorTotalHomologado"),
        "situacao": detalhe.get("situacaoCompraNome"),
        "amparo_legal": {
            "codigo": amparo_legal_bruto.get("codigo"),
            "nome": amparo_legal_bruto.get("nome"),
            "descricao": amparo_legal_bruto.get("descricao"),
        }
        if amparo_legal_bruto
        else None,
        "data_publicacao_pncp": detalhe.get("dataPublicacaoPncp"),
        "data_abertura_proposta": detalhe.get("dataAberturaProposta"),
        "data_encerramento_proposta": detalhe.get("dataEncerramentoProposta"),
        "link_sistema_origem": detalhe.get("linkSistemaOrigem"),
        "link_processo_eletronico": detalhe.get("linkProcessoEletronico"),
        "link_pagina_pncp": f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}",
    }
    if incluir_itens:
        resultado["itens"] = [
            {
                "descricao": it.get("descricao"),
                "quantidade": it.get("quantidade"),
                "unidade_medida": it.get("unidadeMedida"),
                "valor_unitario_estimado": it.get("valorUnitarioEstimado"),
                "valor_total": it.get("valorTotal"),
                "situacao": it.get("situacaoCompraItemNome"),
            }
            for it in (itens_brutos or [])
        ]
    return resultado
