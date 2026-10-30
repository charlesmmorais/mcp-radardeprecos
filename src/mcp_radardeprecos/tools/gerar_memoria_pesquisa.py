"""Tool MCP: consolida uma pesquisa de preços em um documento único de formalização.

Implementa a fase de **Formalização** de "Pesquisa de preços — um guia
prático de sobrevivência" (Franklin Brasil, Set/2020) — ver
o guia de boas práticas de pesquisa de preços, seção 5. O guia lista os
elementos que a documentação da pesquisa deve conter (consolidando vários
Acórdãos TCU): agente responsável, identificação completa de cada fonte
(informante, meio de consulta, data, URL, CNPJ, quantidade, valor,
especificação, condições de pagamento/entrega), metodologia aplicada,
conclusões e o registro das buscas frustradas — não só das bem-sucedidas.

Assim como ``calcular_preco_referencia`` e ``classificar_curva_abc``, esta é
uma tool **pura**: não consulta nenhuma API nem chama outras tools
internamente — ela só consolida em um documento único o que já foi coletado
com as demais tools deste servidor (``buscar_pncp_texto``,
``buscar_contratacoes_pncp``, ``buscar_precos_praticados_compras`` etc.) e o
resultado de ``calcular_preco_referencia``, que deve ser chamado antes e
passado como argumento aqui.

Aceita opcionalmente ``correcao_monetaria``
(o dicionário devolvido por ``atualizar_precos_indice``, ou o campo
``correcao_monetaria`` de um item de ``pesquisar_cesta_precos(corrigir_indice=True)``)
para formalizar no documento QUAL índice/série do SGS/Banco Central e QUAL
data-base foram usados para trazer preços de datas diferentes à mesma moeda
antes do cálculo — parte da metodologia exigida pelo Art. 3º, VI e VII, da
IN SEGES/ME nº 65/2021.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..domain.dominios import FORMATOS_MEMORIA_PESQUISA
from ..logging_utils import get_logger

logger = get_logger(__name__)

_CAMPOS_OBRIGATORIOS_FONTE = ("informante", "meio_consulta", "valor_unitario", "data_referencia")
_CAMPOS_OBRIGATORIOS_BUSCA_FRUSTRADA = ("meio_consulta", "motivo")


def _validar_fontes(fontes: list[dict[str, Any]]) -> None:
    if not fontes:
        raise ValueError("fontes não pode ser uma lista vazia")
    for i, fonte in enumerate(fontes):
        faltantes = [c for c in _CAMPOS_OBRIGATORIOS_FONTE if not fonte.get(c)]
        if faltantes:
            raise ValueError(f"fontes[{i}] não informou: {faltantes}")


def _validar_buscas_frustradas(buscas_frustradas: list[dict[str, Any]]) -> None:
    for i, busca in enumerate(buscas_frustradas):
        faltantes = [c for c in _CAMPOS_OBRIGATORIOS_BUSCA_FRUSTRADA if not busca.get(c)]
        if faltantes:
            raise ValueError(f"buscas_frustradas[{i}] não informou: {faltantes}")


def _renderizar_markdown(memoria: dict[str, Any]) -> str:
    linhas = [
        "# Memória de Pesquisa de Preços",
        "",
        f"**Objeto:** {memoria['objeto']}",
        f"**Agente responsável:** {memoria['agente_responsavel']}",
        f"**Data da pesquisa:** {memoria['data_pesquisa']}",
        "",
        "## Metodologia",
        "",
        f"Método aplicado: **{memoria['metodologia']['metodo_utilizado']}**",
        f"Preço de referência: **R$ {memoria['metodologia']['preco_referencia']:.4f}**",
    ]
    estatisticas = memoria["metodologia"].get("estatisticas") or {}
    if estatisticas:
        linhas.append(
            "Estatísticas da amostra: média R$ {media:.4f}, mediana R$ {mediana:.4f}, "
            "mínimo R$ {minimo:.4f}, máximo R$ {maximo:.4f}, desvio-padrão "
            "{desvio_padrao:.4f}, CV {cv:.2f}%".format(
                media=estatisticas.get("media", 0),
                mediana=estatisticas.get("mediana", 0),
                minimo=estatisticas.get("minimo", 0),
                maximo=estatisticas.get("maximo", 0),
                desvio_padrao=estatisticas.get("desvio_padrao", 0),
                cv=estatisticas.get("coeficiente_variacao_percentual", 0),
            )
        )
    correcao = memoria["metodologia"].get("correcao_monetaria")
    if correcao:
        linhas.append(
            f"Correção monetária: preços trazidos a valor presente por "
            f"**{correcao.get('indice')}**, data-base **{correcao.get('data_base')}** "
            "(Art. 3º, VI e VII, IN SEGES/ME nº 65/2021)."
        )
    linhas.append("")
    linhas.append(f"## Fontes consultadas ({memoria['quantidade_fontes']})")
    linhas.append("")
    for i, fonte in enumerate(memoria["fontes_consultadas"], start=1):
        linhas.append(
            f"{i}. **{fonte.get('informante')}**"
            + (f" (CNPJ {fonte['cnpj']})" if fonte.get("cnpj") else "")
            + f" — {fonte.get('meio_consulta')}"
        )
        detalhe = f"   Valor: R$ {fonte.get('valor_unitario')} | Data: {fonte.get('data_referencia')}"
        if fonte.get("quantidade") is not None:
            detalhe += f" | Quantidade: {fonte['quantidade']}"
        linhas.append(detalhe)
        if fonte.get("especificacao"):
            linhas.append(f"   Especificação: {fonte['especificacao']}")
        if fonte.get("condicoes"):
            linhas.append(f"   Condições: {fonte['condicoes']}")
        if fonte.get("url"):
            linhas.append(f"   URL: {fonte['url']}")
        elif fonte.get("evidencia_acesso"):
            linhas.append(f"   Evidência de acesso: {fonte['evidencia_acesso']}")
        else:
            linhas.append("   [PENDÊNCIA: informar URL ou evidência de acesso a esta fonte]")
        linhas.append("")

    if memoria["buscas_frustradas"]:
        linhas.append(f"## Buscas frustradas ({len(memoria['buscas_frustradas'])})")
        linhas.append("")
        for i, busca in enumerate(memoria["buscas_frustradas"], start=1):
            termo = f' — termo: "{busca["termo_busca"]}"' if busca.get("termo_busca") else ""
            linhas.append(f"{i}. {busca.get('meio_consulta')}{termo} — motivo: {busca.get('motivo')}")
        linhas.append("")

    if memoria["avisos"]:
        linhas.append("## Avisos")
        linhas.append("")
        for aviso in memoria["avisos"]:
            linhas.append(f"- {aviso}")
        linhas.append("")

    linhas.append("## Conclusão")
    linhas.append("")
    linhas.append(
        f"Preço de referência adotado: **R$ {memoria['metodologia']['preco_referencia']:.4f}**, "
        f"calculado pelo método **{memoria['metodologia']['metodo_utilizado']}** a partir de "
        f"{memoria['quantidade_fontes']} fonte(s)."
    )
    return "\n".join(linhas)


async def gerar_memoria_pesquisa(
    objeto: str,
    agente_responsavel: str,
    fontes: list[dict[str, Any]],
    resultado_calculo: dict[str, Any],
    buscas_frustradas: list[dict[str, Any]] | None = None,
    data_pesquisa: str | None = None,
    formato: str = "json",
    correcao_monetaria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Consolida uma pesquisa de preços num documento único de formalização.

    Reúne o que o guia de pesquisa de preços exige na fase de Formalização:
    quem conduziu a pesquisa, cada fonte consultada com seus dados de
    rastreabilidade, a metodologia de cálculo aplicada (via o resultado já
    produzido por ``calcular_preco_referencia``), as buscas que não
    retornaram resultado (o guia exige registrá-las, não só as
    bem-sucedidas) e uma conclusão.

    Esta tool é **pura** — não acessa nenhuma API nem chama outras tools.
    Rode as buscas (``buscar_pncp_texto``, ``buscar_contratacoes_pncp``,
    ``buscar_precos_praticados_compras`` etc.) e ``calcular_preco_referencia``
    antes, e passe os resultados aqui para montar o documento final.

    Args:
        objeto: Descrição do item/serviço pesquisado.
        agente_responsavel: Nome/cargo de quem conduziu a pesquisa —
            exigido pelo guia para rastreabilidade.
        fontes: Lista das fontes de preço efetivamente usadas no cálculo.
            Cada uma é um dicionário com, no mínimo, ``informante`` (nome do
            fornecedor/órgão), ``meio_consulta`` (ex.: "PNCP - busca textual",
            "Compras.gov.br - preços praticados", "Painel de Preços",
            "Cotação direta"), ``valor_unitario`` e ``data_referencia``.
            Campos opcionais recomendados pelo guia: ``cnpj``, ``quantidade``,
            ``url``, ``especificacao`` e ``condicoes`` (pagamento/entrega).
            ``url`` deve ser o link direto da fonte (ex.: a página do
            PNCP/Compras.gov.br do contrato, ata ou edital — ``link_pncp`` já
            vem pronto nos resultados de ``buscar_contratacoes_pncp``/
            ``buscar_contratos_compras``/``consultar_ata_registro_preco``).
            Quando não houver URL (ex.: cotação direta por e-mail/telefone),
            preencha ``evidencia_acesso`` com um texto livre descrevendo como
            a fonte pode ser verificada (ex.: "e-mail de cotação anexado ao
            processo, fls. 12-15"). Uma fonte sem ``url`` e sem
            ``evidencia_acesso`` gera um aviso — o Art. 3º, III, da IN
            SEGES/ME nº 65/2021 exige caracterizar as fontes consultadas, e
            ``gerar_relatorio_excel``/``gerar_relatorio_word`` marcam essa
            ausência como pendência visível no documento gerado.
        resultado_calculo: O dicionário devolvido por
            ``calcular_preco_referencia`` para a amostra de preços destas
            mesmas fontes — traz o método aplicado, o preço de referência e
            as estatísticas/avisos que compõem a metodologia do documento.
        buscas_frustradas: Buscas que não retornaram resultado (o guia exige
            registrá-las para mostrar a amplitude real da pesquisa, não só
            os acertos). Cada uma com, no mínimo, ``meio_consulta`` e
            ``motivo``; ``termo_busca`` é recomendado.
        data_pesquisa: Data da pesquisa, formato livre (ex.: "2026-07-04").
            Se omitida, usa a data atual (UTC).
        formato: "json" (padrão — estrutura de dados) ou "markdown"
            (documento em texto corrido, pronto para copiar/anexar ao
            processo).
        correcao_monetaria: Opcional — formaliza
            no documento que os preços foram trazidos a valor presente antes
            do cálculo (Art. 3º, VI e VII, IN SEGES/ME nº 65/2021). Aceita o
            dicionário devolvido por ``atualizar_precos_indice`` (usa
            ``indice``/``data_base``), ou o campo ``correcao_monetaria`` de
            um item de ``pesquisar_cesta_precos(corrigir_indice=True)``. Sem
            validação estrita de formato — chaves ausentes simplesmente não
            aparecem no documento.

    Returns:
        Dicionário com ``objeto``, ``agente_responsavel``, ``data_pesquisa``,
        ``metodologia`` (extraída de ``resultado_calculo``, e com
        ``correcao_monetaria`` quando informada), ``fontes_consultadas``,
        ``quantidade_fontes``, ``buscas_frustradas`` e ``avisos``. Quando
        ``formato="markdown"``, inclui também ``documento_markdown`` com o
        texto pronto.
    """
    if not objeto or not objeto.strip():
        raise ValueError("objeto não pode ser vazio")
    if not agente_responsavel or not agente_responsavel.strip():
        raise ValueError("agente_responsavel não pode ser vazio")
    if formato not in FORMATOS_MEMORIA_PESQUISA:
        raise ValueError(f"formato deve ser um de {FORMATOS_MEMORIA_PESQUISA}")
    if "metodo_utilizado" not in resultado_calculo or "preco_referencia" not in resultado_calculo:
        raise ValueError(
            "resultado_calculo não parece vir de calcular_preco_referencia "
            "(faltam 'metodo_utilizado'/'preco_referencia')"
        )

    _validar_fontes(fontes)
    buscas_frustradas = buscas_frustradas or []
    _validar_buscas_frustradas(buscas_frustradas)

    logger.info(
        "gerar_memoria_pesquisa objeto=%r quantidade_fontes=%d quantidade_buscas_frustradas=%d "
        "formato=%s correcao_monetaria=%s",
        objeto, len(fontes), len(buscas_frustradas), formato, bool(correcao_monetaria),
    )

    avisos: list[str] = list(resultado_calculo.get("avisos") or [])
    quantidade_amostra_calculo = (resultado_calculo.get("amostra_original") or {}).get("quantidade")
    if quantidade_amostra_calculo is not None and quantidade_amostra_calculo != len(fontes):
        avisos.append(
            f"O número de fontes informadas ({len(fontes)}) é diferente do tamanho da "
            f"amostra usada em resultado_calculo ({quantidade_amostra_calculo}) — confira "
            "se todas as fontes do cálculo estão listadas em 'fontes'."
        )
    if not buscas_frustradas:
        avisos.append(
            "Nenhuma busca frustrada foi registrada. Se alguma fonte consultada não "
            "retornou resultado, o guia recomenda registrá-la mesmo assim, para mostrar "
            "a amplitude real da pesquisa."
        )
    for i, fonte in enumerate(fontes, start=1):
        if not fonte.get("url") and not fonte.get("evidencia_acesso"):
            avisos.append(
                f"Fonte {i} ({fonte.get('informante')}) não tem 'url' nem "
                "'evidencia_acesso' preenchidos — o Art. 3º, III, da IN SEGES/ME "
                "nº 65/2021 exige caracterizar as fontes consultadas. Inclua o link "
                "da página do PNCP/Compras.gov.br do contrato/ata/edital, ou "
                "descreva como a fonte pode ser verificada (ex.: e-mail de cotação "
                "anexado ao processo)."
            )

    metodologia: dict[str, Any] = {
        "metodo_utilizado": resultado_calculo["metodo_utilizado"],
        "preco_referencia": resultado_calculo["preco_referencia"],
        "estatisticas": resultado_calculo.get("estatisticas"),
    }
    if correcao_monetaria:
        metodologia["correcao_monetaria"] = correcao_monetaria

    memoria: dict[str, Any] = {
        "objeto": objeto,
        "agente_responsavel": agente_responsavel,
        "data_pesquisa": data_pesquisa or datetime.now(timezone.utc).date().isoformat(),
        "metodologia": metodologia,
        "fontes_consultadas": fontes,
        "quantidade_fontes": len(fontes),
        "buscas_frustradas": buscas_frustradas,
        "avisos": avisos,
    }

    if formato == "markdown":
        memoria["documento_markdown"] = _renderizar_markdown(memoria)

    return memoria
