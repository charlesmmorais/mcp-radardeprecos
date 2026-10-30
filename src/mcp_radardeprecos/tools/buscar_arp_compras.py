"""Tool MCP: busca Atas de Registro de Preço (ARP) no Compras.gov.br por vigência.

Módulo "ARP" do Compras.gov.br (``/modulo-arp/*``) — distinto da API de Ata
do PNCP já coberta por ``consultar_ata_registro_preco``: fontes/schemas
diferentes, e **coberturas diferentes**. Este módulo reflete o que transitou
pelo SIASG; o PNCP é o repositório de publicidade da Lei 14.133, onde publicam
também os entes fora do SIASG. Para fins de existência de ata, o PNCP é o
conjunto mais amplo — confirmado ao vivo em 2026-08-17 com atas vigentes do
TCU visíveis no índice do PNCP e ausentes aqui. Item 1 da lista de módulos do Compras.gov.br ainda não cobertos
por este servidor, priorizado pelo usuário (2026-07-09) por resolver
diretamente uma limitação encontrada em outra ferramenta MCP ("consulta de
ARP por UASG bloqueada, busca textual não-exaustiva").

Paths e nomes de campo confirmados ao vivo em 2026-07-09 contra
https://dadosabertos.compras.gov.br/v3/api-docs e chamadas reais (nunca só a
partir da spec OpenAPI) — ver docstring de ``clients/compras_client.py``.

**Achado real: cada ata já vem com ``numero_controle_pncp_ata``/
``numero_controle_pncp_compra`` prontos** — permite pivotar direto para as
tools do PNCP (``consultar_ata_registro_preco``, ``consultar_familia_contratacao_pncp``)
sem precisar montar o número de controle manualmente a partir de CNPJ/ano/
sequencial.

**Achado real: ``incluir_itens`` não tem filtro nativo por número da ata no
Compras.gov.br** — o endpoint de itens (``/modulo-arp/2_consultarARPItem``)
só filtra por unidade gerenciadora, vigência, modalidade, item, fornecedor,
PDM e número da compra; cada item devolvido TRAZ o número da ata, mas não dá
para pedir "os itens desta ata" diretamente ao servidor. Esta tool contorna
isso buscando pela unidade gerenciadora + a data exata de vigência inicial
da ata (reduz bastante o volume) e filtrando no cliente pelo número exato da
ata — necessário porque um mesmo número de compra pode gerar várias atas
distintas (confirmado ao vivo: 5 atas diferentes da mesma compra).

**Item 4 — filtro de item NO SERVIDOR.**
``/modulo-arp/2_consultarARPItem`` aceita ``codigoItem``/``codigoPdm``/
``niFornecedor`` nativamente (spec 2.5, já suportados por
``clients.compras_client.consultar_arp_itens``, nunca antes expostos por
esta tool). ``codigo_item``/``codigo_pdm``/``cnpj_fornecedor`` repassam esses
três filtros direto para a chamada de itens de cada ata — não é um
pós-filtro no cliente (diferente do filtro por número de ata acima, que
continua sendo client-side pela ausência documentada de suporte nativo).
Habilita o caso de uso "atas vigentes que registram o CATMAT X" numa única
chamada: quando qualquer um dos três é informado, ``incluir_itens`` é
forçado (o filtro só existe no endpoint de itens) e atas cujos itens
retornados ficarem vazios após o filtro são removidas do resultado — ou
seja, ``atas`` passa a listar só as que de fato registram o item buscado.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..clients import compras_client
from ..config import settings
from ..domain import cobertura as cobertura_mod
from ..domain.cobertura import MotivoInterrupcao, StatusCobertura
from ..logging_utils import get_logger
from ..utils.datas import janela_dias_atras_iso
from ..utils.documentos import mascarar_documento
from ..utils.paginacao import extrair_paginacao

logger = get_logger(__name__)

_JANELA_MAXIMA_DIAS = 365
#: Teto de páginas da listagem varridas quando há filtro por item. Com
#: 500 atas por página, cobre 10.000 atas — o suficiente para períodos
#: restritos, e um teto explícito para não varrer 144 mil registros
#: silenciosamente. Quando ele é atingido, o aviso diz que a leitura foi
#: parcial e que vazio NÃO significa ausência.
_MAX_PAGINAS_VARREDURA_ITEM = 20

_LIMITE_MAXIMO = 50
_LIMITE_MAXIMO_COM_ITENS = 10


def _formatar_ata(bruto: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    formatado = {
        "numero_ata_registro_preco": bruto.get("numeroAtaRegistroPreco"),
        "codigo_unidade_gerenciadora": bruto.get("codigoUnidadeGerenciadora"),
        "nome_unidade_gerenciadora": bruto.get("nomeUnidadeGerenciadora"),
        "codigo_orgao": bruto.get("codigoOrgao"),
        "nome_orgao": bruto.get("nomeOrgao"),
        "numero_compra": bruto.get("numeroCompra"),
        "ano_compra": bruto.get("anoCompra"),
        "modalidade": bruto.get("nomeModalidadeCompra"),
        "data_assinatura": bruto.get("dataAssinatura"),
        "data_vigencia_inicial": bruto.get("dataVigenciaInicial"),
        "data_vigencia_final": bruto.get("dataVigenciaFinal"),
        "valor_total": bruto.get("valorTotal"),
        "status_ata": bruto.get("statusAta"),
        "objeto": bruto.get("objeto"),
        "quantidade_itens": bruto.get("quantidadeItens"),
        "ata_excluido": bruto.get("ataExcluido"),
        "numero_controle_pncp_ata": bruto.get("numeroControlePncpAta"),
        "numero_controle_pncp_compra": bruto.get("numeroControlePncpCompra"),
        "link_ata_pncp": bruto.get("linkAtaPNCP"),
        "link_compra_pncp": bruto.get("linkCompraPNCP"),
    }
    if incluir_bruto:
        formatado["dados_originais"] = bruto
    return formatado


def _formatar_item(bruto: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    formatado = {
        "numero_item": bruto.get("numeroItem"),
        "codigo_item": bruto.get("codigoItem"),
        "descricao_item": bruto.get("descricaoItem"),
        "tipo_item": bruto.get("tipoItem"),
        "codigo_pdm": bruto.get("codigoPdm"),
        "nome_pdm": bruto.get("nomePdm"),
        "quantidade_homologada_item": bruto.get("quantidadeHomologadaItem"),
        "quantidade_homologada_vencedor": bruto.get("quantidadeHomologadaVencedor"),
        "valor_unitario": bruto.get("valorUnitario"),
        "valor_total": bruto.get("valorTotal"),
        "maximo_adesao": bruto.get("maximoAdesao"),
        "quantidade_empenhada": bruto.get("quantidadeEmpenhada"),
        "ni_fornecedor": mascarar_documento(bruto.get("niFornecedor")),
        "nome_fornecedor": bruto.get("nomeRazaoSocialFornecedor"),
        "situacao_sicaf": bruto.get("situacaoSicaf"),
        "item_excluido": bruto.get("itemExcluido"),
    }
    if incluir_bruto:
        formatado["dados_originais"] = bruto
    return formatado


async def buscar_arp_compras(
    data_vigencia_inicial_min: str | None = None,
    data_vigencia_inicial_max: str | None = None,
    janela_dias: int = 365,
    codigo_unidade_gerenciadora: str | None = None,
    codigo_modalidade_compra: str | None = None,
    numero_ata_registro_preco: str | None = None,
    data_assinatura_inicial: str | None = None,
    data_assinatura_final: str | None = None,
    incluir_itens: bool = False,
    codigo_item: int | None = None,
    codigo_pdm: int | None = None,
    cnpj_fornecedor: str | None = None,
    limite: int = 10,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Busca Atas de Registro de Preço (ARP) no Compras.gov.br por vigência inicial.

    Ver docstring do módulo para a origem (módulo "ARP" do Compras.gov.br,
    diferente da API de Ata do PNCP) e as duas limitações reais que moldam
    esta tool: o campo pronto de número de controle PNCP, e a ausência de
    filtro nativo por ata no endpoint de itens.

    Args:
        data_vigencia_inicial_min: Início do intervalo de vigência inicial
            (``AAAA-MM-DD``). Se omitido junto com ``data_vigencia_inicial_max``,
            usa os últimos ``janela_dias`` dias a partir de hoje.
        data_vigencia_inicial_max: Fim do intervalo (``AAAA-MM-DD``). O
            Compras.gov.br rejeita (HTTP 400) intervalos maiores que 365
            dias — confirmado ao vivo.
        janela_dias: Tamanho da janela (dias) usada quando as datas acima
            não são informadas (padrão 365, o máximo aceito pela API).
        codigo_unidade_gerenciadora: Código da UASG gerenciadora da ata.
        codigo_modalidade_compra: Código de modalidade **do Compras.gov.br**
            (diferente do código de modalidade do PNCP — ex.: 05=Pregão,
            06=Dispensa no Compras.gov.br; ver ``consultar_tabelas_dominio_pncp``
            para a tabela do PNCP, que NÃO se aplica aqui).
        numero_ata_registro_preco: Filtra por um número de ata específico
            (ex.: "00002/2025").
        data_assinatura_inicial: Filtra pela data de assinatura da ata
            (``AAAA-MM-DD``), início do intervalo.
        data_assinatura_final: Fim do intervalo de data de assinatura.
        incluir_itens: Se ``True``, busca também os itens de cada ata
            encontrada (preço registrado, fornecedor, teto de adesão,
            quantidade já empenhada) — uma chamada de rede extra por ata,
            com concorrência limitada. Reduz automaticamente ``limite`` para
            no máximo 10 nesse modo, para não gerar um fan-out grande.
            Forçado a ``True`` automaticamente quando ``codigo_item``/
            ``codigo_pdm``/``cnpj_fornecedor`` é informado (ver abaixo).
        codigo_item: Filtra os ITENS de cada ata por código de catálogo
            (CATMAT/CATSER) — filtro NO SERVIDOR,
            repassado direto ao endpoint de itens. Quando informado, ativa
            ``incluir_itens`` automaticamente e remove do resultado as atas
            que não registram esse item — habilita "atas vigentes que
            registram o CATMAT/CATSER X" numa única chamada.
        codigo_pdm: Filtra os itens por código de PDM — mesmo comportamento
            de ``codigo_item`` (filtro no servidor, força ``incluir_itens``,
            remove atas sem item correspondente).
        cnpj_fornecedor: Filtra os itens por CNPJ/CPF do fornecedor
            vencedor — mesmo comportamento de ``codigo_item``.
        limite: Número máximo de atas a retornar (padrão 10, máximo 50; 10
            se ``incluir_itens=True``). Aplicado ANTES do filtro por item —
            com ``codigo_item``/``codigo_pdm``/``cnpj_fornecedor``, o número
            de atas no resultado final pode ser menor que ``limite`` (só as
            que sobrarem após o filtro).
        incluir_bruto: Se True, cada ata (e cada item, quando
            ``incluir_itens=True``) também traz ``dados_originais`` com os
            campos exatos e completos da API, sem tradução (padrão False —
            não incluído por padrão para não duplicar o payload à toa).

    Returns:
        Dicionário com ``atas`` (lista, cada uma com ``numero_controle_pncp_ata``/
        ``numero_controle_pncp_compra`` prontos para uso em
        ``consultar_ata_registro_preco``/``consultar_familia_contratacao_pncp``
        do PNCP, e ``itens`` quando ``incluir_itens=True`` — já filtrados no
        servidor por ``codigo_item``/``codigo_pdm``/``cnpj_fornecedor`` quando
        informados, e com atas sem nenhum item correspondente removidas),
        ``total_no_periodo`` (total de atas reportado pelo Compras.gov.br
        ANTES do filtro por item — ver docstring de ``codigo_item``) e
        ``avisos``.

    Raises:
        ValueError: se só uma das datas de vigência for informada, ou se
            ``janela_dias`` ultrapassar 365.
    """
    if (data_vigencia_inicial_min is None) != (data_vigencia_inicial_max is None):
        raise ValueError(
            "informe data_vigencia_inicial_min e data_vigencia_inicial_max juntos, "
            "ou nenhum dos dois (para usar a janela padrão)"
        )
    if data_vigencia_inicial_min is None:
        janela_dias = max(1, min(janela_dias, _JANELA_MAXIMA_DIAS))
        data_vigencia_inicial_min, data_vigencia_inicial_max = janela_dias_atras_iso(janela_dias)

    avisos: list[str] = []
    filtro_item_ativo = bool(codigo_item or codigo_pdm or cnpj_fornecedor)
    if filtro_item_ativo and not incluir_itens:
        avisos.append(
            "incluir_itens foi ativado automaticamente porque codigo_item/codigo_pdm/"
            "cnpj_fornecedor foi informado — o filtro só existe no endpoint de itens "
            "."
        )
        incluir_itens = True

    limite_maximo = _LIMITE_MAXIMO_COM_ITENS if incluir_itens else _LIMITE_MAXIMO
    limite = max(1, min(limite, limite_maximo))

    logger.info(
        "buscar_arp_compras vigencia=%s..%s unidade=%s modalidade=%s numero_ata=%s "
        "incluir_itens=%s codigo_item=%s codigo_pdm=%s cnpj_fornecedor=%s limite=%s",
        data_vigencia_inicial_min, data_vigencia_inicial_max, codigo_unidade_gerenciadora,
        codigo_modalidade_compra, numero_ata_registro_preco, incluir_itens, codigo_item,
        codigo_pdm, cnpj_fornecedor, limite,
    )

    # Quantas atas BRUTAS pedir por página da listagem. Com filtro por item,
    # vale pedir páginas grandes: cada uma custa uma requisição e evita várias
    # rodadas do laço abaixo.
    tamanho_listagem = 500 if filtro_item_ativo else max(10, limite)

    # Guarda a ÚLTIMA resposta bruta da listagem: é dela que sai a paginação
    # padronizada devolvida ao cliente (``extrair_paginacao``), e com a
    # varredura por item a listagem passa a ter mais de uma página.
    ultima_resposta: dict[str, Any] | None = None

    async def _pagina_de_atas(pagina: int) -> tuple[list[dict[str, Any]], int]:
        nonlocal ultima_resposta
        resposta = await compras_client.consultar_arp(
            data_vigencia_inicial_min=data_vigencia_inicial_min,
            data_vigencia_inicial_max=data_vigencia_inicial_max,
            codigo_unidade_gerenciadora=codigo_unidade_gerenciadora,
            codigo_modalidade_compra=codigo_modalidade_compra,
            numero_ata_registro_preco=numero_ata_registro_preco,
            data_assinatura_inicial=data_assinatura_inicial,
            data_assinatura_final=data_assinatura_final,
            pagina=pagina,
            tamanho_pagina=tamanho_listagem,
        )
        ultima_resposta = resposta
        return (
            (resposta or {}).get("resultado", []) or [],
            (resposta or {}).get("totalRegistros", 0) or 0,
        )

    brutos, total_no_periodo = await _pagina_de_atas(1)
    atas = [_formatar_ata(a, incluir_bruto) for a in brutos[: (tamanho_listagem if filtro_item_ativo else limite)]]

    if not filtro_item_ativo and total_no_periodo > len(atas):
        avisos.append(
            f"O Compras.gov.br encontrou {total_no_periodo} ata(s) no período/filtros "
            f"informados, mas só {len(atas)} foram retornadas (limite={limite}). "
            "Restrinja por unidade gerenciadora/modalidade/número da ata, ou aumente "
            "limite, se esperava mais resultados."
        )

    if incluir_itens and atas:
        semaforo = asyncio.Semaphore(5)

        async def _itens_da_ata(ata: dict[str, Any]) -> list[dict[str, Any]]:
            data_vig = ata.get("data_vigencia_inicial")
            unidade = ata.get("codigo_unidade_gerenciadora")
            if not data_vig or not unidade:
                return []
            try:
                async with semaforo:
                    resposta_itens = await compras_client.consultar_arp_itens(
                        data_vigencia_inicial_min=data_vig,
                        data_vigencia_inicial_max=data_vig,
                        codigo_unidade_gerenciadora=unidade,
                        numero_compra=ata.get("numero_compra"),
                        # filtro NO SERVIDOR —
                        # diferente do filtro por número de ata logo abaixo
                        # (esse sim client-side, por ausência de suporte
                        # nativo — ver docstring do módulo).
                        codigo_item=codigo_item,
                        codigo_pdm=codigo_pdm,
                        ni_fornecedor=cnpj_fornecedor,
                        tamanho_pagina=500,
                    )
            except Exception as exc:  # noqa: BLE001 - falha isolada não derruba a busca inteira
                logger.warning(
                    "falha ao buscar itens da ata %s: %s", ata.get("numero_ata_registro_preco"), exc
                )
                return []
            itens_brutos = (resposta_itens or {}).get("resultado", []) or []
            # Sem filtro nativo por ata (ver docstring do módulo) — filtra no
            # cliente pelo número exato da ata, já que um mesmo numeroCompra
            # pode gerar várias atas distintas (confirmado ao vivo).
            return [
                _formatar_item(i, incluir_bruto)
                for i in itens_brutos
                if i.get("numeroAtaRegistroPreco") == ata.get("numero_ata_registro_preco")
            ]

        if not filtro_item_ativo:
            listas_de_itens = await asyncio.gather(*(_itens_da_ata(ata) for ata in atas))
            for ata, itens in zip(atas, listas_de_itens, strict=False):
                ata["itens"] = itens
        else:
            # VARREDURA. Antes, o `limite` era aplicado à listagem
            # BRUTA e só depois se olhava quais atas registravam o item — ou
            # seja, testava-se uma amostra arbitrária de 10 em 144 mil. Para
            # qualquer busca por CATMAT/PDM sem outros filtros o resultado era
            # vazio quase garantido, e vazio aqui se lê como "não há ata deste
            # item". Achado num teste real em 2026-08-21, com PDM 8435
            # (NOTEBOOK): 144.255 atas no período, 10 lidas, nenhuma com o
            # item.
            #
            # Agora o `limite` vale sobre o resultado FILTRADO: varre a
            # listagem em páginas até reunir `limite` atas que de fato
            # registram o item, ou até bater no teto de páginas / no orçamento
            # de tempo — e diz, no aviso, quantas atas brutas foram
            # examinadas para chegar lá.
            inicio = time.monotonic()
            orcamento = settings.tool_budget_seconds
            encontradas: list[dict[str, Any]] = []
            examinadas = 0
            pagina = 1
            esgotou = False
            while True:
                listas = await asyncio.gather(*(_itens_da_ata(a) for a in atas))
                for ata, itens in zip(atas, listas, strict=False):
                    examinadas += 1
                    if itens:
                        ata["itens"] = itens
                        encontradas.append(ata)
                        if len(encontradas) >= limite:
                            break
                if len(encontradas) >= limite:
                    break
                # Fim da listagem SÓ pelo total declarado ou por página vazia
                # (mais abaixo). Não por "página menor que a pedida": o
                # Compras.gov.br não garante páginas cheias, e usar isso como
                # sinal de fim encerra a varredura antes da hora — a mesma
                # parada precipitada que já custou caro neste projeto.
                if examinadas >= total_no_periodo:
                    esgotou = True
                    break
                if pagina >= _MAX_PAGINAS_VARREDURA_ITEM:
                    break
                if orcamento and orcamento > 0 and (time.monotonic() - inicio) >= orcamento:
                    break
                pagina += 1
                brutos_pag, _ = await _pagina_de_atas(pagina)
                if not brutos_pag:
                    esgotou = True
                    break
                atas = [_formatar_ata(a, incluir_bruto) for a in brutos_pag]

            atas = encontradas
            # Guardado para o bloco `cobertura` do retorno: a informação já
            # existia, só não era legível por programa.
            varredura_examinadas = examinadas
            varredura_esgotou = esgotou
            varredura_paginas = pagina
            if esgotou:
                texto_cobertura = (
                    f"as {examinadas} ata(s) do período foram TODAS examinadas"
                    if examinadas >= total_no_periodo
                    else f"{examinadas} ata(s) examinadas até o fim da listagem"
                )
            else:
                texto_cobertura = (
                    f"{examinadas} de {total_no_periodo} ata(s) do período foram "
                    "examinadas — a varredura parou antes de esgotar a listagem"
                )
            avisos.append(
                f"Filtro por item: {len(atas)} ata(s) registram o item buscado; "
                f"{texto_cobertura}. O 'limite' vale sobre as atas QUE REGISTRAM o item, "
                "não sobre a listagem bruta (mudou na v0.4.25)."
                + (
                    ""
                    if esgotou
                    else " Como nem toda a listagem foi lida, um resultado vazio ou "
                    "curto aqui NÃO permite concluir que não existam outras atas — "
                    "restrinja por unidade gerenciadora, modalidade ou período."
                )
            )

    # Achado real (2026-08-17, usuário): buscar ARPs do TCU aqui devolveu
    # vazio, enquanto o índice de Atas do PNCP mostrava várias vigentes. Não é
    # atraso nem falha — são universos diferentes. Este módulo reflete o que
    # transitou pelo SIASG; o PNCP é o repositório de PUBLICIDADE, onde a Lei
    # 14.133 obriga TODO ente a publicar, inclusive quem não opera no SIASG
    # (outros Poderes, órgãos de controle, estados, municípios).
    #
    # Sem este aviso, zero resultados aqui se lê como "não existem atas" — um
    # falso negativo que, numa decisão de adesão a ata ou numa pesquisa de
    # preços, custa caro e não deixa rastro de que houve um erro.
    if not atas:
        avisos.append(
            "Nenhuma ata encontrada NO MÓDULO ARP DO COMPRAS.GOV.BR, que cobre o "
            "que transitou pelo SIASG. Isso NÃO significa que não existam atas: "
            "órgãos fora do SIASG (outros Poderes, órgãos de controle, estados e "
            "municípios) publicam suas atas apenas no PNCP. Antes de concluir que "
            "não há ata, repita a busca com a tool consultar_ata_registro_preco, "
            "que consulta o índice do PNCP."
        )

    # campos padronizados, aditivos —
    # total_no_periodo acima é mantido (nome antigo).
    # `cobertura` estruturado. Os campos antigos — `total_no_periodo`
    # e o texto em `avisos` — continuam por uma versão, para não quebrar quem
    # já consome; saem na próxima, com aviso de depreciação.
    if not filtro_item_ativo:
        # Sem filtro por item não há varredura: a listagem é lida direto e o
        # `limite` corta. Três situações, e a primeira versão desta lógica
        # colapsava as três em INDETERMINADA — o que era generalizar demais:
        # quando o período inteiro coube no retorno, a consulta É exaustiva,
        # e um teste existente pegou isso.
        if not total_no_periodo:
            status, motivo = StatusCobertura.VAZIA, None
        elif len(atas) >= total_no_periodo:
            status, motivo = StatusCobertura.EXAUSTIVA, None
        else:
            status = StatusCobertura.PARCIAL
            motivo = MotivoInterrupcao.LIMITE_DE_VARREDURA
        bloco = cobertura_mod.montar(
            fonte="Compras.gov.br",
            status=status,
            registros_retornados=len(atas),
            registros_examinados=len(atas),
            total_no_universo=total_no_periodo,
            motivo=motivo,
        )
    elif varredura_esgotou:
        bloco = cobertura_mod.montar(
            fonte="Compras.gov.br",
            status=StatusCobertura.EXAUSTIVA,
            registros_retornados=len(atas),
            registros_examinados=varredura_examinadas,
            total_no_universo=total_no_periodo,
            paginas_lidas=varredura_paginas,
        )
    else:
        bloco = cobertura_mod.montar(
            fonte="Compras.gov.br",
            status=StatusCobertura.PARCIAL,
            registros_retornados=len(atas),
            registros_examinados=varredura_examinadas,
            total_no_universo=total_no_periodo,
            paginas_lidas=varredura_paginas,
            motivo=MotivoInterrupcao.LIMITE_DE_VARREDURA,
        )
    texto = cobertura_mod.aviso(bloco)
    if texto:
        avisos.insert(0, texto)

    return {
        "atas": atas,
        "total_no_periodo": total_no_periodo,
        "cobertura": bloco,
        "avisos": avisos,
        **extrair_paginacao(ultima_resposta),
    }
