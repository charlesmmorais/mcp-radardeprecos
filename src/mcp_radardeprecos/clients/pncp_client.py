"""Cliente para as APIs públicas do PNCP (Portal Nacional de Contratações Públicas).

Oito superfícies distintas do PNCP são usadas aqui:

1. API de busca indexada (``/api/search``) — a mesma API que o front-end
   oficial do PNCP (``pncp.gov.br/app/editais`` etc.) usa para popular a
   busca e os filtros. Não é documentada em Swagger, mas é pública, estável,
   e foi validada diretamente contra o comportamento do site (inspeção do
   bundle Angular e das chamadas de rede reais) — ver notas de parâmetros
   abaixo. Não exige informar modalidade ou período, o que a torna adequada
   para buscas exploratórias amplas.
2. API de Consulta oficial (``/api/consulta``), documentada em
   https://pncp.gov.br/api/consulta/swagger-ui/index.html — usada para
   consultas estruturadas por período/modalidade, detalhe de contratação por
   ID (:func:`consultar_contratacao_detalhe`) e contratos por data de
   publicação/CNPJ do órgão (:func:`consultar_contratos` — **não** tem
   filtro por CNPJ de fornecedor, ver correção na docstring da função).
3. Endpoint de itens de uma contratação (``/api/pncp/v1/orgaos/...``), usado
   para recuperar os preços unitários de cada item de uma licitação.
4. Endpoint de **resultado** de um item (``.../itens/{numero}/resultados``),
   usado para recuperar o valor efetivamente **homologado** (vencedor) de
   cada item — ver nota crítica abaixo sobre a diferença em relação ao
   endpoint de itens (nº 3).
5. Endpoints de **Ata de Registro de Preço** (detalhe, itens com saldo e
   arquivos — :func:`consultar_ata`, :func:`consultar_itens_ata`,
   :func:`consultar_arquivos_ata`), identificados na especificação
   OpenAPI oficial e confirmados ao vivo.
6. Endpoints de **Plano de Contratação Anual (PCA)** —
   :func:`consultar_pca_por_classificacao` (``/v1/pca/``, por ano + código de
   classificação superior — mesmo código de classe/grupo que
   ``descobrir_codigo_catalogo`` resolve) e :func:`consultar_pca_por_periodo`
   (``/v1/pca/atualizacao``, por período de atualização global + CNPJ do
   órgão opcional) — ambos confirmados contra o OpenAPI oficial
   (``/api/consulta/v3/api-docs``). Cobrem a fase de Planejamento do guia de
   pesquisa de preços (sinal antecipado do que será comprado), mas **não**
   substituem :func:`consultar_resultado_item` como referência de preço — o
   valor do PCA é estimativa orçamentária interna, não preço efetivamente
   pago (mesma distinção da nota crítica abaixo, item 3 vs. 4). Ver docstring
   da tool ``consultar_pca``.

Todos os endpoints de detalhe (itens, resultado, arquivos, ata) são
cacheados em memória por um TTL curto (``utils/cache.py``), já que mudam
raramente dentro do horizonte de uma pesquisa de preços — medido ao vivo. A busca textual
(:func:`buscar_texto`) nunca é cacheada, pois seu resultado muda a qualquer
momento com novos editais publicados.

**Nota crítica — estimado vs. homologado (confirmada ao vivo):** o endpoint de itens (nº 3, usado
por :func:`consultar_itens_contratacao`) só traz o valor **estimado antes da
disputa** (``valorUnitarioEstimado``). O valor efetivamente **vencedor/
homologado** — o único válido como referência de pesquisa de preços,
conforme o guia no guia de boas práticas de pesquisa de preços (Acórdãos TCU
6.405/2017-1C e 2.062/2016-1C) — só vem do endpoint de resultado (nº 4, usado
por :func:`consultar_resultado_item`). Testado com um caso real: mesmo item,
estimado R$ 240.220,00 vs. homologado R$ 225.880,00 (~6% de diferença). A
tool ``buscar_contratacoes_pncp`` usa os dois: itens para descobrir quais
existem, resultado para obter o preço de referência correto.

Notas de validação de ``/api/search`` (importante para manutenção futura —
todas testadas com chamadas reais, comparando o total retornado com e sem
cada filtro):

- O parâmetro de UF é ``ufs`` (plural) — ``uf`` (singular) é **silenciosamente
  ignorado** pelo servidor (retorna o total não filtrado, sem erro). Isso foi
  a causa de resultados incorretos em uma versão anterior deste cliente.
- ``municipios`` espera o **ID interno do PNCP** (ex.: São Paulo = ``3830``),
  **não** o código IBGE de 7 dígitos (São Paulo = ``3550308``). O ID correto
  para cada município é obtido via ``listar_filtros(...)['filters']['municipios']``.
- ``possui_emenda_parlamentar`` (não ``emenda_parlamentar``) é o parâmetro
  correto para o filtro "Emenda Parlamentar" — o nome de exibição na UI não
  bate com o nome do parâmetro. Confirmado: ``emenda_parlamentar=false`` não
  tem efeito algum (mesmo total da busca sem filtro).
- ``exigencia_conteudo_nacional``, ``possui_emenda_parlamentar`` e
  ``permite_adesao`` (este último específico de atas de registro de preço)
  são filtros booleanos (``true``/``false``) e **não aparecem** na lista de
  facetas de ``/api/search/filters`` (que só lista campos categóricos).
- ``tam_pagina`` aceita valores bem maiores que os 10 usados por padrão na
  UI — testado e confirmado funcionando com 1000 (o servidor parece limitar
  em torno disso). Usar páginas maiores reduz o número de requisições
  necessárias para buscas amplas, e portanto o risco de timeout acumulado.
- Seleção múltipla do mesmo filtro (ex.: ``ufs=SP&ufs=RJ`` ou
  ``ufs=SP,RJ``) **não funciona como OR no servidor**: parâmetros repetidos
  fazem o último valor vencer, e uma string separada por vírgula é tratada
  como um único valor inválido (0 resultados). Para múltiplos valores, é
  necessário fazer uma chamada por valor e mesclar os resultados no cliente.
- Valores válidos de ``status``: para ``tipo_documento="edital"`` —
  ``recebendo_proposta`` | ``propostas_encerradas`` | ``encerradas`` |
  ``todos``; para ``"ata"``/``"contrato"`` — ``vigente`` | ``nao_vigente`` |
  ``todos``. Omitir o parâmetro equivale a ``todos``.
- ``ordenacao`` aceita ``-data`` (mais recentes primeiro, usado por padrão
  pela UI) ou ``data`` (mais antigos primeiro).
- ``tipos_contrato`` (exposto como ``tipo_contrato`` em :func:`buscar_texto`)
  só tem efeito para ``tipo_documento="contrato"``; para ``"edital"`` o único
  valor de faceta existente é ``null`` (não se aplica). Confirmado ao vivo:
  ``tipos_contrato=7`` (Empenho) filtra de 470.612 para 266.904 resultados.

Notas sobre o endpoint de arquivos (``/api/pncp/v1/orgaos/.../arquivos`` —
usado pela aba "Arquivos" do site, essencial para baixar o edital/contrato
original em uma pesquisa de preços), confirmadas ao vivo via inspeção das
chamadas de rede da aba "Arquivos" do site:

- O endpoint retorna uma **lista JSON simples** (não ``{"items": [...]}"``).
  Cada item já vem com um campo ``uri``/``url`` pronto para download direto —
  não é preciso montá-lo manualmente.
- **Atenção**: o host do link de download (``pncp.gov.br/pncp-api/v1/...``)
  é diferente do host usado para *listar* os arquivos
  (``pncp.gov.br/api/pncp/v1/...``, o mesmo de :func:`consultar_itens_contratacao`).
  Isso é uma particularidade do PNCP, não um erro — os dois hosts servem o
  mesmo conteúdo em rotas distintas.
- Para **editais** (``tipo_documento="edital"``), use
  ``/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/arquivos``.
- Para **contratos** (``tipo_documento="contrato"``), use
  ``/v1/orgaos/{cnpj}/contratos/{ano}/{sequencial}/arquivos``.
- Para **atas de registro de preço** (``tipo_documento="ata"``), os arquivos
  da **contratação (compra) que a originou** continuam disponíveis em
  ``/compras/{ano}/{sequencial}/arquivos`` (CNPJ/ano/sequencial **da
  compra**, via :func:`consultar_arquivos`). No resultado de ``buscar_texto``
  para atas, esse sequencial vem no campo ``numero_sequencial_compra_ata``
  (não confundir com ``numero_sequencial``, que é o sequencial da própria
  ata dentro da compra).
- **Correção:** uma versão anterior deste módulo afirmava que não
  existia um endpoint de arquivos específico da própria ata (só o da compra
  de origem, acima). Isso estava **errado** — confirmado ao vivo por teste direto: existe sim
  ``/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/atas/{sequencialAta}/arquivos``
  (usado por :func:`consultar_arquivos_ata`), aninhado sob a ata específica
  dentro da compra — distinto do endpoint de arquivos da compra em si. Os
  dois podem ser úteis: o da ata para o PDF da própria ata assinada, o da
  compra para o edital/termo de referência que a originou.
"""
from __future__ import annotations

from typing import Any, Literal

from ..config import settings
from ..utils.cache import TTL_5_MIN, TTL_30_MIN
from .base import get_json

TipoDocumento = Literal["edital", "ata", "contrato"]

SOURCE = "pncp"


async def buscar_texto(
    termo_busca: str,
    tipo_documento: TipoDocumento,
    *,
    uf: str | None = None,
    municipio: str | None = None,
    modalidade: int | None = None,
    ano: int | None = None,
    tipo_instrumento: int | None = None,
    tipo_contrato: int | None = None,
    orgao: str | None = None,
    unidade: str | None = None,
    esfera: str | None = None,
    poder: str | None = None,
    fonte_orcamentaria: str | None = None,
    tipo_margem_preferencia: str | None = None,
    exigencia_conteudo_nacional: bool | None = None,
    possui_emenda_parlamentar: bool | None = None,
    permite_adesao: bool | None = None,
    status: str | None = None,
    ordenacao: str = "-data",
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Busca textual indexada no PNCP (``/api/search``) — mesmo backend do site.

    Retorna metadados de editais, atas de registro de preço ou contratos que
    mencionem ``termo_busca`` no objeto. Diferente da API de consulta oficial,
    não exige informar período nem modalidade, o que a torna adequada para
    buscas exploratórias amplas. Cobre todos os filtros disponíveis na página
    de busca do site (Editais/Atas/Contratos).

    Cada filtro categórico (``uf``, ``municipio``, ``modalidade``, ``ano``,
    ``tipo_instrumento``, ``orgao``, ``unidade``, ``esfera``, ``poder``,
    ``fonte_orcamentaria``, ``tipo_margem_preferencia``) aceita apenas **um
    valor por chamada** — o servidor não combina múltiplos valores do mesmo
    filtro como OR (ver notas no topo do módulo). Para múltiplos valores,
    faça uma chamada por valor. Use ``listar_filtros`` para descobrir os
    códigos/IDs válidos de cada um.

    **Limitação conhecida de ``termo_busca`` — item 6 da lista priorizada de
    melhorias (análise cruzada ChatGPT/Claude, 2026-07-08), confirmada ao
    vivo neste mesmo dia contra ``/api/search``:**

    1. **Aspas NÃO funcionam como busca por frase exata.** Aspas em torno de
       uma única palavra são **completamente ignoradas** — ``'"notebook"'``
       devolveu exatamente o mesmo ``total`` (22.635) e o mesmo primeiro
       resultado que ``"notebook"`` sem aspas. Aspas em torno de uma frase de
       duas palavras produzem um comportamento **diferente e imprevisível**
       (não documentado pela API): ``'"notebook dell"'`` devolveu
       ``total=277``, um número que não bate nem com a busca sem aspas das
       mesmas duas palavras (``total=1.150``) nem com a palavra isolada — ou
       seja, as aspas não isolam uma frase exata de forma confiável. **Não
       use aspas para tentar restringir a uma frase exata** — não há
       nenhuma sintaxe de frase exata suportada por este endpoint.
    2. **Múltiplas palavras funcionam como "E" (bag-of-words), não como
       frase, e são independentes de ordem** — confirmado ao vivo:
       ``"notebook dell"`` e ``"dell notebook"`` devolveram exatamente o
       mesmo ``total`` (1.150) e o mesmo primeiro resultado. Para restringir
       resultados, adicione mais palavras discriminantes (ou os filtros
       estruturados desta função) — não espere que a ordem das palavras
       influencie a relevância.
    3. **Termos curtos casam por prefixo, não por palavra inteira** —
       confirmado ao vivo: ``termo_busca="note"`` (só um prefixo de
       "notebook") devolveu ``total=20.852``, quase o mesmo volume que
       ``termo_busca="notebook"`` (``total=22.635``, ~92% de sobreposição).
       Termos de busca curtos ou genéricos tendem a trazer muito mais ruído
       do que o esperado de uma busca por "palavra inteira" — prefira termos
       mais longos/específicos, e combine com os filtros estruturados desta
       função (``uf``, ``modalidade``, ``orgao`` etc.) para reduzir ruído em
       vez de tentar restringir só via ``termo_busca``.

    Args:
        orgao: ID do órgão (campo ``id`` da faceta ``orgaos``, não o CNPJ).
        unidade: ID da unidade (campo ``id`` da faceta ``unidades``, não o
            código da unidade).
        tipo_contrato: Código do tipo de contrato (específico de
            ``tipo_documento="contrato"`` — ex.: 1 = Contrato (termo
            inicial), 7 = Empenho, 6 = Convênio; ver ``listar_filtros`` para
            a lista completa via a faceta ``tipos_contrato``).
        municipio: ID interno do PNCP para o município (campo ``id`` da
            faceta ``municipios`` — **não** é o código IBGE de 7 dígitos).
        esfera: "F" (Federal), "E" (Estadual), "M" (Municipal), "D"
            (Distrital) ou "N" (Não se aplica).
        poder: "E" (Executivo), "L" (Legislativo), "J" (Judiciário) ou "N"
            (Não se aplica).
        exigencia_conteudo_nacional: Filtro booleano; omitir para não filtrar.
        possui_emenda_parlamentar: Filtro booleano; omitir para não filtrar.
        permite_adesao: Filtro booleano ("Permite Adesão", específico de
            atas de registro de preço); omitir para não filtrar.
    """
    tamanho_pagina = max(1, min(tamanho_pagina, 100))
    params: dict[str, Any] = {
        "q": termo_busca,
        "tipos_documento": tipo_documento,
        "status": status,
        "ufs": uf,
        "municipios": municipio,
        "modalidades": modalidade,
        "anos": ano,
        "tipos": tipo_instrumento,
        "tipos_contrato": tipo_contrato,
        "orgaos": orgao,
        "unidades": unidade,
        "esferas": esfera,
        "poderes": poder,
        "fontes_orcamentarias": fonte_orcamentaria,
        "tipos_margens_preferencia": tipo_margem_preferencia,
        "ordenacao": ordenacao,
        "pagina": pagina,
        "tam_pagina": tamanho_pagina,
    }
    if exigencia_conteudo_nacional is not None:
        params["exigencia_conteudo_nacional"] = str(exigencia_conteudo_nacional).lower()
    if possui_emenda_parlamentar is not None:
        params["possui_emenda_parlamentar"] = str(possui_emenda_parlamentar).lower()
    if permite_adesao is not None:
        params["permite_adesao"] = str(permite_adesao).lower()
    return await get_json(settings.pncp_search_base_url, "", params, source=SOURCE)


async def listar_filtros(tipo_documento: TipoDocumento) -> dict[str, Any]:
    """Lista as facetas de filtro disponíveis para um tipo de documento (``/api/search/filters``).

    Mesmo endpoint usado pelo site do PNCP para popular os menus de filtro
    (modalidades, órgãos, unidades, UFs, municípios, esferas, poderes, tipos,
    tipos de contrato, fontes orçamentárias, tipos de margem de preferência).
    Cada entrada vem com uma contagem (``total``) de documentos correspondentes
    no índice — útil para descobrir códigos válidos antes de filtrar uma busca.

    Não inclui os filtros booleanos "Exigência de Conteúdo Nacional"
    (``exigencia_conteudo_nacional``) e "Emenda Parlamentar"
    (``possui_emenda_parlamentar``) — esses são passados diretamente como
    ``true``/``false`` em :func:`buscar_texto`, sem lista de opções.
    """
    return await get_json(
        settings.pncp_search_base_url, "/filters", {"tipos_documento": tipo_documento}, source=SOURCE
    )


async def consultar_itens_contratacao(
    cnpj: str, ano: int, sequencial: int
) -> list[dict[str, Any]]:
    """Lista os itens (e preços unitários ESTIMADOS) de uma contratação do PNCP.

    ``cnpj``/``ano``/``sequencial`` são extraídos do número de controle PNCP no
    formato ``CNPJ-1-SEQUENCIAL/ANO`` (ex.: ``33683111000107-1-000084/2025``) —
    ver :func:`parse_numero_controle_pncp`.

    **Atenção:** ``valorUnitarioEstimado`` aqui é o valor ANTES da disputa —
    não é referência válida de pesquisa de preços. Para o valor efetivamente
    homologado (vencedor), use :func:`consultar_resultado_item` com o
    ``numeroItem`` de cada item retornado aqui (ver nota no topo do módulo).
    """
    path = f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens"
    cache_key = f"itens_contratacao:{cnpj}:{ano}:{sequencial}"
    resultado = await get_json(
        settings.pncp_pncp_base_url, path, {}, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )
    return resultado or []


async def consultar_resultado_item(
    cnpj: str, ano: int, sequencial: int, numero_item: int
) -> list[dict[str, Any]]:
    """Retorna o resultado (proposta vencedora/HOMOLOGADA) de um item específico.

    Endpoint ``/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numero_item}/resultados``
    — distinto do endpoint de itens (:func:`consultar_itens_contratacao`), que
    só traz o valor estimado antes da disputa. Este é o endpoint que traz o
    valor efetivamente vencedor, válido como referência de pesquisa de
    preços (ver nota crítica no topo do módulo).

    ``numero_item`` vem do campo ``numeroItem`` de cada item retornado por
    :func:`consultar_itens_contratacao`.

    Returns:
        Lista de resultados (normalmente 1 por item, mas pode haver mais de
        um fornecedor/quantidade em casos de rateio). Cada item traz, entre
        outros campos: ``niFornecedor``, ``nomeRazaoSocialFornecedor``,
        ``quantidadeHomologada``, ``valorUnitarioHomologado``,
        ``valorTotalHomologado`` e ``dataResultado``. Lista vazia se o item
        ainda não tem resultado.
    """
    path = f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numero_item}/resultados"
    cache_key = f"resultado_item:{cnpj}:{ano}:{sequencial}:{numero_item}"
    resultado = await get_json(
        settings.pncp_pncp_base_url, path, {}, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )
    return resultado or []


RecursoArquivo = Literal["compras", "contratos"]


async def consultar_arquivos(
    cnpj: str,
    ano: int,
    sequencial: int,
    recurso: RecursoArquivo,
    *,
    pagina: int = 1,
    tamanho_pagina: int = 50,
) -> list[dict[str, Any]]:
    """Lista os arquivos anexados a uma compra (edital) ou contrato do PNCP.

    Endpoint ``/api/pncp/v1/orgaos/{cnpj}/{compras|contratos}/{ano}/{sequencial}/arquivos``
    — o mesmo usado pela aba "Arquivos" do site do PNCP. Retorna uma lista
    (não envelopada em ``items``/``total``); cada item já traz um campo
    ``uri``/``url`` pronto para download direto (edital, termo de referência,
    contrato assinado etc.) — ver notas no topo do módulo sobre a diferença de
    host entre listagem e download. Para os arquivos da própria ata de
    registro de preço (não da compra que a originou), use
    :func:`consultar_arquivos_ata`.

    Args:
        cnpj: CNPJ do órgão (14 posições, sem máscara — pode conter letras).
        ano: Ano da compra/contrato.
        sequencial: Sequencial da compra (para ``recurso="compras"``, inclui
            editais e as compras que originaram atas de registro de preço) ou
            do contrato (para ``recurso="contratos"``) no PNCP.
        recurso: ``"compras"`` (editais e atas — via a compra de origem) ou
            ``"contratos"``.
        pagina: Página dos resultados (padrão 1).
        tamanho_pagina: Registros por página (padrão 50).

    Returns:
        Lista de dicionários com ``titulo`` (nome do arquivo),
        ``tipoDocumentoNome``, ``dataPublicacaoPncp``, ``sequencialDocumento``
        e ``uri``/``url`` (link de download direto, sem autenticação).
    """
    path = f"/v1/orgaos/{cnpj}/{recurso}/{ano}/{sequencial}/arquivos"
    params = {"pagina": pagina, "tamanhoPagina": max(1, min(tamanho_pagina, 100))}
    cache_key = f"arquivos:{cnpj}:{recurso}:{ano}:{sequencial}:{pagina}:{tamanho_pagina}"
    resultado = await get_json(
        settings.pncp_pncp_base_url, path, params, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )
    return resultado or []


def parse_numero_controle_pncp(numero_controle: str) -> tuple[str, int, int] | None:
    """Extrai ``(cnpj, ano, sequencial)`` de um número de controle PNCP.

    Formato esperado: ``CNPJ-1-SEQUENCIAL/ANO`` (contratações) ou
    ``CNPJ-2-SEQUENCIAL/ANO`` (contratos). Retorna ``None`` se o formato for
    inesperado, para que o chamador decida como lidar (ex.: pular o item).
    """
    try:
        cnpj, _tipo, resto = numero_controle.split("-", 2)
        sequencial_str, ano_str = resto.split("/")
        return cnpj, int(ano_str), int(sequencial_str)
    except (ValueError, AttributeError):
        return None


def parse_numero_controle_pncp_ata(numero_controle_ata: str) -> tuple[str, int, int, int] | None:
    """Extrai ``(cnpj, ano_compra, sequencial_compra, sequencial_ata)`` do
    número de controle PNCP de uma **ata** de registro de preço.

    Formato esperado: ``CNPJ-1-SEQUENCIAL_COMPRA/ANO-SEQUENCIAL_ATA`` (ex.:
    ``18457226000181-1-000015/2023-000001``, como retornado pelo campo
    ``numero_controle_pncp``/``numeroControlePNCPAta`` de uma ata em
    :func:`buscar_texto` com ``tipo_documento="ata"``). Note que é um
    formato distinto do de contratações/contratos
    (:func:`parse_numero_controle_pncp`) — tem um segmento a mais
    (``-SEQUENCIAL_ATA``) no final. Retorna ``None`` se o formato for
    inesperado.
    """
    try:
        cnpj, _tipo, resto = numero_controle_ata.split("-", 2)
        resto_compra, sequencial_ata_str = resto.rsplit("-", 1)
        sequencial_compra_str, ano_str = resto_compra.split("/")
        return cnpj, int(ano_str), int(sequencial_compra_str), int(sequencial_ata_str)
    except (ValueError, AttributeError):
        return None


def classificar_numero_controle_pncp(numero_controle: str) -> str:
    """Identifica o TIPO de instrumento de um número de controle PNCP.

    O dígito de tipo e a estrutura do número distinguem os instrumentos —
    informação que :func:`parse_numero_controle_pncp` descarta de propósito
    (ela é tipo-agnóstica, reusada para extrair cnpj/ano/sequencial tanto de
    contratações quanto de contratos). Quando o tipo IMPORTA — como em
    ``consultar_contratacao_pncp``, que só faz sentido para contratações —,
    use esta função para não confundir instrumentos e evitar substituição
    silenciosa (achado real 2026-07-28: passar um contrato ``-2-`` devolvia,
    sem avisar, a contratação ``-1-`` de mesmo sequencial, um objeto
    totalmente diferente).

    Formatos:

    - **Contratação** (edital/compra): ``CNPJ-1-SEQ/ANO`` — 3 segmentos
      separados por ``-``, dígito de tipo ``1``.
    - **Contrato**: ``CNPJ-2-SEQ/ANO`` — 3 segmentos, dígito de tipo ``2``.
    - **Ata de registro de preço**: ``CNPJ-1-SEQ/ANO-SEQ_ATA`` — 4 segmentos
      (um a mais no fim); o dígito de tipo é ``1``, então é a ESTRUTURA que a
      distingue de uma contratação (ver :func:`parse_numero_controle_pncp_ata`).

    Returns:
        ``"contratacao"``, ``"contrato"``, ``"ata"`` ou ``"desconhecido"``.
    """
    if not numero_controle or not isinstance(numero_controle, str):
        return "desconhecido"
    partes = numero_controle.strip().split("-")
    if len(partes) == 4:
        return "ata"
    if len(partes) == 3:
        if partes[1] == "1":
            return "contratacao"
        if partes[1] == "2":
            return "contrato"
    return "desconhecido"


async def consultar_contratacoes_publicacao(
    *,
    data_inicial: str,
    data_final: str,
    codigo_modalidade_contratacao: int,
    uf: str | None = None,
    codigo_municipio_ibge: str | None = None,
    cnpj: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 50,
) -> dict[str, Any]:
    """Consulta oficial de contratações por data de publicação.

    Endpoint ``/v1/contratacoes/publicacao`` da API de Consulta do PNCP. Datas
    no formato ``AAAAMMDD``. ``tamanho_pagina`` máximo é 50 (limite da própria
    API). Note que esta API usa o código IBGE de fato (diferente de
    ``buscar_texto``, que usa o ID interno do PNCP para município). Não é
    usada diretamente pelas tools desta versão (que priorizam a busca
    textual indexada), mas é mantida disponível para extensões futuras que
    precisem de consultas exatas por modalidade/período.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 50))
    params = {
        "dataInicial": data_inicial,
        "dataFinal": data_final,
        "codigoModalidadeContratacao": codigo_modalidade_contratacao,
        "uf": uf,
        "codigoMunicipioIbge": codigo_municipio_ibge,
        "cnpj": cnpj,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
    }
    return await get_json(
        settings.pncp_consulta_base_url, "/v1/contratacoes/publicacao", params, source=SOURCE
    )


async def consultar_contratacao_detalhe(cnpj: str, ano: int, sequencial: int) -> dict[str, Any]:
    """Detalhe completo de uma contratação já conhecida (por CNPJ/ano/sequencial).

    Endpoint ``/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}`` da API de
    Consulta oficial — confirmado ao vivo contra a especificação
    OpenAPI oficial. Traz
    campos que **não** vêm da busca textual (:func:`buscar_texto`) nem do
    endpoint de itens (:func:`consultar_itens_contratacao`): ``srp``
    (indica se é uma contratação por Sistema de Registro de Preços),
    ``valorTotalHomologado`` (já agregado no nível da contratação, sem
    precisar somar item a item), ``modoDisputaNome``, ``amparoLegal``
    (código/nome/descrição do embasamento legal da modalidade),
    ``dataAberturaProposta``/``dataEncerramentoProposta`` e
    ``situacaoCompraNome``.

    Complementa :func:`consultar_itens_contratacao` (que só traz os itens) —
    use os dois juntos quando precisar tanto do contexto da contratação
    quanto do detalhe por item.
    """
    path = f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}"
    cache_key = f"contratacao_detalhe:{cnpj}:{ano}:{sequencial}"
    return await get_json(
        settings.pncp_consulta_base_url, path, {}, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )


async def consultar_contratos(
    *,
    data_inicial: str,
    data_final: str,
    cnpj_orgao: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 50,
) -> dict[str, Any]:
    """Consulta oficial de contratos por data de publicação, com filtro por CNPJ do ÓRGÃO.

    Endpoint ``/v1/contratos`` da API de Consulta oficial (``operationId``
    ``consultarContratosPorDataPublicacao``).

    **Correção — não existe filtro por CNPJ do fornecedor nesta
    API.** Uma versão anterior deste cliente aceitava um parâmetro
    ``cnpj_fornecedor`` (mapeado para ``cnpjFornecedor``), baseado numa suposição
    nunca conferida contra a especificação OpenAPI oficial — a suposta "confirmação ao
    vivo" da época não detectou o problema porque a chamada retorna HTTP 200
    e uma lista de contratos normalmente, só que **sem filtrar por
    fornecedor**: o parâmetro desconhecido é silenciosamente ignorado pelo
    servidor (comportamento comum em APIs Spring), e o resultado é apenas a
    listagem geral de contratos no período, paginada — em uma janela de 365
    dias isso são mais de 2 milhões de registros. Reportado por um usuário
    em uso real (contratos completamente não relacionados ao fornecedor
    pedido, ``totalRegistros`` na casa dos milhões) e confirmado contra a
    especificação OpenAPI oficial (``/api/consulta/v3/api-docs``): os únicos
    parâmetros reais deste endpoint são ``dataInicial``, ``dataFinal``,
    ``cnpjOrgao``, ``codigoUnidadeAdministrativa``, ``usuarioId``, ``pagina``
    e ``tamanhoPagina`` — nenhum filtro por fornecedor existe em nenhum
    endpoint desta API. Não há, hoje, uma forma de buscar contratos por CNPJ
    de fornecedor diretamente no lado do servidor do PNCP; a alternativa
    real é buscar pelo NOME do fornecedor via ``buscar_contratos_compras``
    (busca textual — usada com sucesso pelos usuários deste projeto mesmo
    antes desta correção).

    Datas no formato ``AAAAMMDD`` (ver :func:`~mcp_radardeprecos.utils.datas.janela_dias_atras`).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 50))
    params = {
        "dataInicial": data_inicial,
        "dataFinal": data_final,
        "cnpjOrgao": cnpj_orgao,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
    }
    cache_key = f"contratos:{data_inicial}:{data_final}:{cnpj_orgao}:{pagina}:{tamanho_pagina}"
    return await get_json(
        settings.pncp_consulta_base_url, "/v1/contratos", params, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_5_MIN,
    )


async def consultar_ata(
    cnpj: str, ano_compra: int, sequencial_compra: int, sequencial_ata: int
) -> dict[str, Any]:
    """Detalhe de uma Ata de Registro de Preço específica.

    Endpoint ``/v1/orgaos/{cnpj}/compras/{ano_compra}/{sequencial_compra}/atas/{sequencial_ata}``
    — confirmado ao vivo contra a especificação
    OpenAPI oficial. Traz
    órgão/unidade, vigência, data de assinatura, situação e se está
    cancelada — mas **não** os itens (ver :func:`consultar_itens_ata`).
    """
    path = f"/v1/orgaos/{cnpj}/compras/{ano_compra}/{sequencial_compra}/atas/{sequencial_ata}"
    cache_key = f"ata:{cnpj}:{ano_compra}:{sequencial_compra}:{sequencial_ata}"
    return await get_json(
        settings.pncp_pncp_base_url, path, {}, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )


async def consultar_itens_ata(
    cnpj: str, ano_compra: int, sequencial_compra: int, sequencial_ata: int
) -> list[dict[str, Any]]:
    """Lista os itens de uma Ata de Registro de Preço, com preço e saldo.

    Endpoint ``/v1/orgaos/{cnpj}/compras/{ano_compra}/{sequencial_compra}/atas/{sequencial_ata}/itens``
    — confirmado ao vivo contra a especificação OpenAPI oficial. Quando preenchido pelo
    órgão, cada item traz ``valorUnitario`` (o preço registrado na ata — a
    3ª fonte prioritária de pesquisa de preços, "atas de outros órgãos", no
    guia no guia de boas práticas de pesquisa de preços), ``quantidade``
    original, ``saldoQuantidade`` (quanto ainda pode ser aderido por outros
    órgãos) e o fornecedor (``niFornecedor``/``nomeRazaoSocialFornecedor``).

    **Atenção — lacuna de dados conhecida (confirmada ao vivo em 4 atas de
    amostra distintas, incluindo uma federal de TI):** este endpoint retorna
    lista vazia com frequência, mesmo para atas vigentes e sem cancelamento
    — aparentemente nem todo órgão preenche o detalhamento de itens da ata
    no PNCP (o preenchimento dos itens da *contratação* que originou a ata,
    via :func:`consultar_itens_contratacao`, é bem mais consistente). Uma
    lista vazia aqui **não** deve ser tratada como erro — trate como "PNCP
    não tem esse detalhamento" e considere consultar os itens da
    contratação de origem como alternativa (sem saldo, mas com o valor
    histórico do item).
    """
    path = (
        f"/v1/orgaos/{cnpj}/compras/{ano_compra}/{sequencial_compra}"
        f"/atas/{sequencial_ata}/itens"
    )
    cache_key = f"itens_ata:{cnpj}:{ano_compra}:{sequencial_compra}:{sequencial_ata}"
    resultado = await get_json(
        settings.pncp_pncp_base_url, path, {}, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )
    return resultado or []


async def consultar_arquivos_ata(
    cnpj: str, ano_compra: int, sequencial_compra: int, sequencial_ata: int
) -> list[dict[str, Any]]:
    """Lista os arquivos anexados diretamente a uma Ata de Registro de Preço.

    Endpoint ``/v1/orgaos/{cnpj}/compras/{ano_compra}/{sequencial_compra}/atas/{sequencial_ata}/arquivos``
    — confirmado ao vivo (corrige uma nota anterior deste módulo, que
    afirmava não existir endpoint de arquivos próprio da ata; ver a "Nota de
    correção" no topo do módulo). Distinto de
    ``consultar_arquivos(..., recurso="compras")``, que traz os arquivos da
    **contratação** que originou a ata (edital, termo de referência) — este
    traz o PDF da própria ata assinada.
    """
    path = (
        f"/v1/orgaos/{cnpj}/compras/{ano_compra}/{sequencial_compra}"
        f"/atas/{sequencial_ata}/arquivos"
    )
    cache_key = f"arquivos_ata:{cnpj}:{ano_compra}:{sequencial_compra}:{sequencial_ata}"
    resultado = await get_json(
        settings.pncp_pncp_base_url, path, {}, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )
    return resultado or []


async def consultar_pca_por_classificacao(
    ano_pca: int,
    codigo_classificacao_superior: str,
    *,
    pagina: int = 1,
    tamanho_pagina: int = 500,
) -> dict[str, Any]:
    """Consulta itens do PCA (Plano de Contratação Anual) por ano + classificação.

    Endpoint ``/v1/pca/`` da API de Consulta oficial (``operationId``
    ``consultarItensPorAno``), confirmado contra o OpenAPI oficial
    (``/api/consulta/v3/api-docs``). ``codigo_classificacao_superior`` é o
    código de classe de material (CATMAT) ou grupo de serviço (CATSER) — o
    mesmo tipo de código que ``compras_client``/``descobrir_codigo_catalogo``
    resolvem a partir de uma descrição textual. Este endpoint não tem filtro
    por CNPJ do órgão; para restringir a um órgão específico, use
    :func:`consultar_pca_por_periodo`.

    ``tamanho_pagina`` é limitado a 500 pela própria API (mínimo 10).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "anoPca": ano_pca,
        "codigoClassificacaoSuperior": codigo_classificacao_superior,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
    }
    cache_key = (
        f"pca_classificacao:{ano_pca}:{codigo_classificacao_superior}:{pagina}:{tamanho_pagina}"
    )
    return await get_json(
        settings.pncp_consulta_base_url, "/v1/pca/", params, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )


async def consultar_atas_periodo(
    *,
    data_inicial: str,
    data_final: str,
    cnpj: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 500,
) -> dict[str, Any]:
    """Listagem oficial de Atas de Registro de Preço por período de vigência (``/v1/atas``).

    Endpoint ``/v1/atas`` da API de Consulta oficial do PNCP (achado 3.3,
    a análise das specs oficiais) — complementa a via já usada por
    este projeto (busca textual indexada + módulo ARP do Compras.gov.br,
    ver :func:`~mcp_radardeprecos.clients.compras_client.consultar_arp`)
    com a fonte oficial: o retorno inclui ``possibilidadeAdesao`` (indica se
    a ata aceita carona) e cancelamento, que a busca textual não traz da
    mesma forma.

    **Datas no formato ``AAAAMMDD``** (sem hífens) — pegadinha confirmada na
    spec oficial: diferente do ``AAAA-MM-DD`` usado pelo módulo ARP do
    Compras.gov.br para o mesmo tipo de consulta (ver
    :func:`~mcp_radardeprecos.utils.datas.janela_dias_a_frente` vs.
    :func:`~mcp_radardeprecos.utils.datas.janela_dias_a_frente_iso`).
    ``pagina`` é obrigatório na API real; ``tamanho_pagina`` limitado a 500
    (mesmo teto de :func:`consultar_contratos`/:func:`consultar_pca_por_periodo`).

    Usada como complemento opcional em ``radar_vencimentos`` (``tipo="atas"``)
    — uma falha aqui não deve derrubar o resultado principal (fonte primária
    é o módulo ARP do Compras.gov.br).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "dataInicial": data_inicial,
        "dataFinal": data_final,
        "cnpj": cnpj,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
    }
    return await get_json(
        settings.pncp_consulta_base_url, "/v1/atas", params, source=SOURCE,
    )


async def consultar_contratacoes_proposta_aberta(
    *,
    data_final: str,
    codigo_modalidade_contratacao: int | None = None,
    uf: str | None = None,
    codigo_municipio_ibge: str | None = None,
    cnpj: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 50,
) -> dict[str, Any]:
    """Contratações com propostas ABERTAS agora, até ``data_final`` (``/v1/contratacoes/proposta``).

    Endpoint da API de Consulta oficial do PNCP (achado 3.2,
    a análise das specs oficiais) — "o que está aberto para propor",
    irmão de :func:`consultar_contratacoes_publicacao` (mesma família
    ``/api/consulta/v1/contratacoes/...``, mesmo cliente de paginação), mas
    sem ``data_inicial``: a janela é implicitamente "a partir de agora até
    ``data_final``".

    **Formato de ``data_final`` não confirmado ao vivo nesta versão** — a
    spec pública não descreve o formato explicitamente (ver plano v0.2.2,
    item 4). Usa ``AAAAMMDD`` por analogia com os demais endpoints desta
    mesma família já confirmados nesse formato
    (:func:`consultar_contratos`/:func:`consultar_contratacoes_publicacao`).
    Vigiado por ``tests/test_live_smoke.py`` (``pytest -m live``): se a API
    real exigir ``AAAA-MM-DD``, o smoke test falha e sinaliza a correção.

    ``tamanho_pagina`` tem teto de **50** — diferente dos 500/100 de outros
    endpoints da API de Consulta (confirmado na spec oficial; ver
    a análise das specs oficiais, seções 1 e 3.6). ``pagina`` é
    obrigatório na API real.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 50))
    params = {
        "dataFinal": data_final,
        "codigoModalidadeContratacao": codigo_modalidade_contratacao,
        "uf": uf,
        "codigoMunicipioIbge": codigo_municipio_ibge,
        "cnpj": cnpj,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
    }
    return await get_json(
        settings.pncp_consulta_base_url, "/v1/contratacoes/proposta", params, source=SOURCE,
    )


async def consultar_termos_contrato(
    cnpj: str, ano: int, sequencial: int, *, pagina: int = 1, tamanho_pagina: int = 50
) -> list[dict[str, Any]]:
    """Termos aditivos/apostilamentos de um contrato (``/v1/orgaos/{cnpj}/contratos/{ano}/{sequencial}/termos``).

    Endpoint do portal do PNCP (``/api/pncp``, GET público — achado 4.1,
    a análise das specs oficiais): aditivos mudam valor e vigência de
    um contrato já assinado, e até a v0.2.1 ``consultar_familia_contratacao_pncp``
    não os trazia — lacuna real. **Schema de retorno não documentado em
    detalhe pela spec pública** — os campos originais são preservados sem
    tradução (ver :func:`consultar_empenhos_contrato`, par deste endpoint, e
    a tool ``consultar_familia_contratacao_pncp``, que consome os dois via
    ``incluir_termos_e_empenhos``).
    """
    path = f"/v1/orgaos/{cnpj}/contratos/{ano}/{sequencial}/termos"
    params = {"pagina": pagina, "tamanhoPagina": max(1, min(tamanho_pagina, 100))}
    cache_key = f"termos_contrato:{cnpj}:{ano}:{sequencial}:{pagina}:{tamanho_pagina}"
    resultado = await get_json(
        settings.pncp_pncp_base_url, path, params, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )
    if isinstance(resultado, dict):
        return resultado.get("data") or resultado.get("content") or []
    return resultado or []


async def consultar_empenhos_contrato(
    cnpj: str, ano: int, sequencial: int, *, pagina: int = 1, tamanho_pagina: int = 50
) -> list[dict[str, Any]]:
    """Empenhos vinculados a um contrato (``/v1/orgaos/{cnpj}/contratos/{ano}/{sequencial}/empenhos``).

    Par de :func:`consultar_termos_contrato` (achado 4.2,
    a análise das specs oficiais) — mesma família de endpoint do
    portal, mesma ressalva sobre schema não documentado em detalhe.
    """
    path = f"/v1/orgaos/{cnpj}/contratos/{ano}/{sequencial}/empenhos"
    params = {"pagina": pagina, "tamanhoPagina": max(1, min(tamanho_pagina, 100))}
    cache_key = f"empenhos_contrato:{cnpj}:{ano}:{sequencial}:{pagina}:{tamanho_pagina}"
    resultado = await get_json(
        settings.pncp_pncp_base_url, path, params, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )
    if isinstance(resultado, dict):
        return resultado.get("data") or resultado.get("content") or []
    return resultado or []

async def consultar_instrumentos_cobranca_periodo(
    *,
    data_inicial: str,
    data_final: str,
    cnpj_orgao: str | None = None,
    tipo_instrumento_cobranca: int | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 100,
) -> dict[str, Any]:
    """Instrumentos de cobrança (com NF-e itemizada) incluídos num período (``/v1/instrumentoscobranca/inclusao``).

    Endpoint da API de Consulta oficial do PNCP (achado 3.1,
    a análise das specs oficiais) — fonte inédita entre os projetos de
    referência estudados: cada instrumento de cobrança traz, quando
    aplicável, um ``NotaFiscalEletronicaConsultaDTO`` com os **itens da NF-e**
    (``descricaoProdutoServico``, ``codigoNCM``, ``quantidade``,
    ``valorUnitario``) e eventos — o preço efetivamente **FATURADO**, um
    degrau além do homologado. Ver docstring da tool
    ``consultar_notas_fiscais`` para o uso recomendado (execução contratual/
    auditoria, não fonte primária de pesquisa de preços) e a normalização
    dos campos.

    **Schema de retorno não confirmado ao vivo nesta versão** — a spec
    pública documenta a existência e os campos citados acima, mas não foi
    testada com uma chamada real ainda; vigiado por
    ``tests/test_live_smoke.py`` (``pytest -m live``).

    ``data_inicial``/``data_final`` (``AAAAMMDD``) são obrigatórias na API
    real; ``cnpj_orgao`` e ``tipo_instrumento_cobranca`` são opcionais.
    ``tamanho_pagina`` tem teto de **100** (menor que os 500 de outros
    endpoints desta mesma API — confirmado na spec oficial).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 100))
    params = {
        "dataInicial": data_inicial,
        "dataFinal": data_final,
        "cnpjOrgao": cnpj_orgao,
        "tipoInstrumentoCobranca": tipo_instrumento_cobranca,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
    }
    return await get_json(
        settings.pncp_consulta_base_url, "/v1/instrumentoscobranca/inclusao", params, source=SOURCE,
    )


async def consultar_instrumentos_cobranca_contrato(
    cnpj: str, ano: int, sequencial: int, *, pagina: int = 1, tamanho_pagina: int = 100
) -> list[dict[str, Any]]:
    """Instrumentos de cobrança de um contrato já conhecido (``/v1/orgaos/{cnpj}/contratos/{ano}/{seqContrato}/instrumentocobranca``).

    Endpoint do portal do PNCP
    — acesso direto à mesma fonte de :func:`consultar_instrumentos_cobranca_periodo`
    (achado 3.1), quando o contrato já é conhecido (``cnpj``/``ano``/
    ``sequencial``, extraídos via :func:`parse_numero_controle_pncp`), sem
    precisar varrer um período inteiro. Mesma ressalva de schema não
    confirmado ao vivo (ver docstring da função irmã).
    """
    path = f"/v1/orgaos/{cnpj}/contratos/{ano}/{sequencial}/instrumentocobranca"
    params = {"pagina": pagina, "tamanhoPagina": max(1, min(tamanho_pagina, 100))}
    cache_key = f"instrumentos_cobranca_contrato:{cnpj}:{ano}:{sequencial}:{pagina}:{tamanho_pagina}"
    resultado = await get_json(
        settings.pncp_pncp_base_url, path, params, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )
    if isinstance(resultado, dict):
        return resultado.get("data") or resultado.get("content") or []
    return resultado or []


async def consultar_pca_por_periodo(
    data_inicio: str,
    data_fim: str,
    *,
    cnpj: str | None = None,
    codigo_unidade: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 500,
) -> dict[str, Any]:
    """Consulta itens do PCA por período de atualização global, com CNPJ opcional.

    Endpoint ``/v1/pca/atualizacao`` da API de Consulta oficial
    (``operationId`` ``consultarItensPorUsuarioAno_1``), confirmado contra o
    OpenAPI oficial. Diferente de :func:`consultar_pca_por_classificacao`,
    não exige código de classificação — filtra por período (``dataInicio``/
    ``dataFim``, formato ``AAAAMMDD``) e, opcionalmente, por ``cnpj`` do
    órgão e/ou ``codigo_unidade``. É o caminho prático para "qual é o PCA
    deste órgão", sem precisar descobrir o ``idUsuario`` (ID do
    portal/sistema que publicou), exigido pelo endpoint alternativo
    ``/v1/pca/usuario`` e por isso não implementado aqui.

    ``tamanho_pagina`` é limitado a 500 pela própria API (mínimo 10).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "dataInicio": data_inicio,
        "dataFim": data_fim,
        "cnpj": cnpj,
        "codigoUnidade": codigo_unidade,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
    }
    cache_key = (
        f"pca_periodo:{data_inicio}:{data_fim}:{cnpj}:{codigo_unidade}:{pagina}:{tamanho_pagina}"
    )
    return await get_json(
        settings.pncp_consulta_base_url, "/v1/pca/atualizacao", params, source=SOURCE,
        cache_key=cache_key, cache_ttl_seconds=TTL_30_MIN,
    )
