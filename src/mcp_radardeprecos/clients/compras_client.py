"""Cliente para a API de Dados Abertos do Compras.gov.br.

``consultar_contratacoes_lei14133`` segue reservada para fases futuras
(cruzar contratações do PNCP com o cadastro oficial do Compras.gov.br) —
não usada por nenhuma tool ainda.

``consultar_precos_material``/``consultar_precos_servico`` (módulo "Pesquisa
de Preço") já são usados pela tool ``buscar_precos_praticados_compras`` —
essa é a fonte de **preços praticados no setor público**, priorizada pela
IN SEGES/ME 65/2021 acima de qualquer outra na pesquisa de preços (ver
``docs/BOAS_PRATICAS_PESQUISA_PRECOS.md``).

Endpoints confirmados contra a especificação OpenAPI publicada em
https://dadosabertos.compras.gov.br/v3/api-docs (testados manualmente antes
de escrever este cliente).

``consultar_fornecedor`` dá suporte à tool
``consultar_situacao_fornecedor`` — due diligence de CNPJ/CPF no SICAF
(situação de habilitação para licitar/contratar). Necessário porque
o cadastro de CNPJ na Receita Federal (``consultar_cnpj``/``cnpj_client.py``)
não tem o campo ``habilitadoLicitar`` — só o SICAF (Compras.gov.br) tem.

``listar_grupos_material``/``listar_classes_material``/``listar_pdms_material_ativos``/
``listar_classes_servico``/``listar_itens_material_por_pdm``/
``listar_itens_servico_por_classe`` dão suporte à tool
``descobrir_codigo_catalogo``. Ver a docstring dessa tool para o
achado central que motivou essas funções: o parâmetro ``descricaoItem`` do
módulo de materiais — que parece uma busca textual livre — na prática exige
igualdade exata com o campo completo (confirmado ao vivo), então a única
forma real de "buscar por descrição" é montar um índice no lado do cliente
a partir dos nomes do catálogo (grupo/classe/PDM) e comparar localmente.

``consultar_uasg``/``consultar_orgao``/``listar_uasgs_ativas``/
``listar_orgaos_ativos`` dão suporte à tool ``descobrir_uasg`` —
nasceu de um estudo completo do spec OpenAPI deste módulo (todas as 15 tags,
~60 endpoints, lido direto do Swagger em
https://dadosabertos.compras.gov.br/swagger-ui/index.html). Achado: nem o módulo
``05 - UASG`` (``consultarUasg``/``consultarOrgao``) nem nenhum outro
endpoint do Compras.gov.br aceitam busca textual por nome — só filtros
exatos (código, CNPJ, UF, status) — mesmo padrão de limitação já visto no
catálogo de materiais/serviços, resolvido aqui do mesmo jeito: paginar tudo
e buscar no lado do cliente.

``consultar_arp``/``consultar_arp_itens``/``consultar_arp_unidades_item``/
``consultar_arp_empenhos_item``/``consultar_arp_adesoes_item`` dão
suporte às tools ``buscar_arp_compras``/``consultar_arp_detalhe_compras`` —
módulo "ARP" (Ata de Registro de Preço) do Compras.gov.br, distinto da API
de Ata do PNCP já coberta por ``consultar_ata_registro_preco``: aqui há
granularidade de item que o PNCP não tem (saldo de adesão, saldo de
remanejamento, empenhos por item). Paths confirmados ao vivo em
2026-07-09 contra https://dadosabertos.compras.gov.br/v3/api-docs
(``/modulo-arp/1_consultarARP``, ``2_consultarARPItem``,
``3_consultarUnidadesItem``, ``4_consultarEmpenhosSaldoItem``,
``5_consultarAdesoesItem``) — os nomes de parâmetro e de campo de retorno
também foram confirmados com chamadas reais antes de escrever este código
(nunca só a partir da spec OpenAPI, que às vezes diverge do comportamento
real — ver limitações já documentadas em outros endpoints deste módulo).

**Achado real: ``2_consultarARPItem`` NÃO tem filtro por
``numeroAtaRegistroPreco``** — só por unidade gerenciadora, vigência,
modalidade, item, fornecedor, PDM e número da compra. Cada item retornado
TRAZ o campo ``numeroAtaRegistroPreco`` (confirmado ao vivo), mas não dá
para pedir "os itens da ata X" diretamente ao servidor — é preciso filtrar
por unidade+vigência (e opcionalmente ``numeroCompra``, se já conhecido) e
então filtrar no cliente pelos itens cujo ``numeroAtaRegistroPreco`` bate
com o pedido. Ver ``tools/buscar_arp_compras.py``.

``consultar_contratos_itens`` dá suporte à tool
``consultar_itens_contrato_compras`` — módulo "09 - CONTRATOS" do
Compras.gov.br (``/modulo-contratos/2_consultarContratosItem``), item
priorizado pelo usuário (2026-07-10) após comparação com o Swagger completo
do módulo. Ver docstring da função para os dois achados reais (parâmetro
``codigoOrgao`` obrigatório e janela de vigência limitada a 365 dias).

``consultar_contratos`` (expandida em v0.1.47) dá suporte à tool
``consultar_contratos_compras`` — mesmo módulo "09 - CONTRATOS", mas o
endpoint cabeçalho (``/modulo-contratos/1_consultarContratos``), com uma
linha por contrato em vez de por item. Comparado com
``consultar_contratos_itens``, traz campos que a itemização não tem
(``objeto``, ``codigoTipo``/``nomeTipo``, ``codigoCategoria``/``nomeCategoria``,
``receitaDespesa``, ``informacoesComplementares``, parcelas) — por isso
valeu implementar as duas tools, não é redundante. Ver docstring da função
para o achado real de 2026-07-10 (``codigoOrgao`` obrigatório, divergente do
schema de um plugin MCP de terceiros).

``consultar_contratos_fim_vigencia``/``consultar_arp_fim_vigencia``
são as variantes ``_FimVigencia`` dos dois endpoints "irmãos" acima — mesmos
campos de retorno, só trocando o filtro de vigência inicial pelo de vigência
final (quando o contrato/ata VENCE, não quando começa). Dão suporte à tool
``radar_vencimentos``.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..utils import cache
from ..utils.cache import TTL_1_DIA, TTL_30_MIN
from .base import get_json

SOURCE = "compras.gov.br"


async def consultar_contratacoes_lei14133(
    *,
    data_publicacao_pncp_inicial: str,
    data_publicacao_pncp_final: str,
    codigo_modalidade: int,
    codigo_orgao: int | None = None,
    orgao_entidade_cnpj: str | None = None,
    unidade_orgao_uf_sigla: str | None = None,
    contratacao_excluida: bool | None = False,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta contratações da Lei 14.133/2021 (``/modulo-contratacoes``).

    Datas no formato ``YYYY-MM-DD``; intervalo máximo de 365 dias. A
    codificação de modalidade aqui é a do Compras.gov.br, DIFERENTE da do
    PNCP (ex.: 5=Pregão, 6=Dispensa no Compras.gov.br vs. 6=Pregão, 8=Dispensa
    no PNCP) — não confundir os dois códigos ao integrar com
    :mod:`mcp_radardeprecos.clients.pncp_client`.

    Contratações excluídas: por que o padrão é ``False``
    ---------------------------------------------------
    O endpoint aceita ``contratacaoExcluida``, que marca a contratação como
    desconsiderada/excluída. **Sem o parâmetro, a API devolve as excluídas
    junto com as válidas.** Medido em 05/09/2026, mesma janela
    (``codigoModalidade=6``, publicação de 01 a 05/08/2026):

    ========================================  ================
    Consulta                                  totalRegistros
    ========================================  ================
    sem o parâmetro                           980
    ``contratacaoExcluida=false``             978
    ``contratacaoExcluida=true``              2
    ========================================  ================

    980 = 978 + 2. Até a v0.5.0 não enviávamos o parâmetro, de modo que
    contratações desconsideradas entravam nas pesquisas de preço sem nenhuma
    marca. São 0,2% da amostra nesta janela — proporção pequena o bastante
    para não saltar aos olhos numa conferência manual e grande o bastante
    para deslocar uma média, o que é exatamente o pior dos dois mundos.

    Por isso o padrão passou a ser ``False``. Quem precisar do comportamento
    anterior (ou quiser justamente auditar as excluídas) informa
    explicitamente ``None`` ou ``True``.

    Args:
        contratacao_excluida: ``False`` (padrão) exclui as desconsideradas;
            ``True`` traz **somente** elas; ``None`` omite o parâmetro e
            devolve as duas misturadas, como a API faz por omissão.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "dataPublicacaoPncpInicial": data_publicacao_pncp_inicial,
        "dataPublicacaoPncpFinal": data_publicacao_pncp_final,
        "codigoModalidade": codigo_modalidade,
        "codigoOrgao": codigo_orgao,
        "orgaoEntidadeCnpj": orgao_entidade_cnpj,
        "unidadeOrgaoUfSigla": unidade_orgao_uf_sigla,
        # Booleano explícito: ``None`` cai fora em get_json (omitido), mas
        # ``False`` precisa chegar como "false" na query string. Se algum dia
        # a limpeza de params passar a descartar valores falsy, este filtro
        # some em silêncio e o defeito de 0,2% volta — daí o teste dedicado.
        "contratacaoExcluida": (
            None if contratacao_excluida is None else str(contratacao_excluida).lower()
        ),
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-contratacoes/1_consultarContratacoes_PNCP_14133",
        params,
        source=SOURCE,
    )


async def consultar_itens_14133(
    *,
    data_inclusao_inicial: str,
    data_inclusao_final: str,
    codigo_item_catalogo: int | None = None,
    tem_resultado: bool | None = None,
    material_ou_servico: str | None = None,
    codigo_classe: int | None = None,
    codigo_grupo: int | None = None,
    orgao_entidade_cnpj: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Itens de contratações da Lei 14.133 (``/modulo-contratacoes/2_...``).

    Janela ``dataInclusaoPncpInicial/Final`` (YYYY-MM-DD) OBRIGATÓRIA na
    spec oficial. ``codItemCatalogo`` + ``temResultado=True`` permitem achar
    itens homologados por código CATMAT/CATSER em massa — ver
    a análise das specs oficiais, seção 2.3 (parâmetros conforme a spec;
    comportamento vigiado pelos smoke tests ao vivo).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "dataInclusaoPncpInicial": data_inclusao_inicial,
        "dataInclusaoPncpFinal": data_inclusao_final,
        "codItemCatalogo": codigo_item_catalogo,
        "temResultado": tem_resultado,
        "materialOuServico": material_ou_servico,
        "codigoClasse": codigo_classe,
        "codigoGrupo": codigo_grupo,
        "orgaoEntidadeCnpj": orgao_entidade_cnpj,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133",
        params,
        source=SOURCE,
    )


async def consultar_resultados_itens_14133(
    *,
    data_resultado_inicial: str,
    data_resultado_final: str,
    ni_fornecedor: str | None = None,
    orgao_entidade_cnpj: str | None = None,
    valor_unitario_homologado_inicial: float | None = None,
    valor_unitario_homologado_final: float | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Resultados HOMOLOGADOS de itens 14.133 (``/modulo-contratacoes/3_...``).

    Janela ``dataResultadoPncpInicial/Final`` (YYYY-MM-DD) OBRIGATÓRIA.
    Filtros por fornecedor (``niFornecedor``), órgão e faixa de valor
    homologado — resultados em massa, sem o fan-out por item do PNCP
.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "dataResultadoPncpInicial": data_resultado_inicial,
        "dataResultadoPncpFinal": data_resultado_final,
        "niFornecedor": ni_fornecedor,
        "orgaoEntidadeCnpj": orgao_entidade_cnpj,
        "valorUnitarioHomologadoInicial": valor_unitario_homologado_inicial,
        "valorUnitarioHomologadoFinal": valor_unitario_homologado_final,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-contratacoes/3_consultarResultadoItensContratacoes_PNCP_14133",
        params,
        source=SOURCE,
    )


async def consultar_contratos(
    *,
    codigo_orgao: str,
    data_vigencia_inicial_min: str,
    data_vigencia_inicial_max: str,
    codigo_unidade_gestora: str | None = None,
    codigo_unidade_gestora_origem_contrato: str | None = None,
    codigo_unidade_realizadora_compra: str | None = None,
    codigo_modalidade_compra: str | None = None,
    codigo_tipo: str | None = None,
    codigo_categoria: str | None = None,
    ni_fornecedor: str | None = None,
    numero_contrato: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta contratos por vigência, nível cabeçalho (``/modulo-contratos/1_consultarContratos``).

    Dá suporte à tool ``consultar_contratos_compras``. Devolve uma
    linha por **contrato** (não por item — ver :func:`consultar_contratos_itens`
    para a itemização), com campos que a itemização não traz: ``objeto``
    (descrição completa do objeto contratado), ``codigoTipo``/``nomeTipo``,
    ``codigoCategoria``/``nomeCategoria``, ``receitaDespesa``,
    ``informacoesComplementares`` (fundamento legal), ``numeroParcelas``/
    ``valorParcela``/``valorAcumulado``/``totalDespesasAcessorias``.

    ``codigo_orgao`` é **obrigatório** — confirmado ao vivo em 2026-07-10:
    chamando este endpoint só com a janela de vigência (sem ``codigoOrgao``),
    a API devolve HTTP 404 "Resource not found" (mesma armadilha de
    "parece sem resultados, mas na verdade é parâmetro obrigatório ausente"
    já documentada em ``consultar_contratos_itens``) — isso resolve, a favor
    do Swagger público, uma divergência com o schema declarado por um plugin
    MCP de terceiros que marcava ``codigoOrgao`` como opcional.
    ``data_vigencia_inicial_min``/``data_vigencia_inicial_max`` também são
    obrigatórios; mesma janela máxima de 365 dias dos demais endpoints deste
    módulo.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "codigoOrgao": codigo_orgao,
        "codigoUnidadeGestora": codigo_unidade_gestora,
        "codigoUnidadeGestoraOrigemContrato": codigo_unidade_gestora_origem_contrato,
        "codigoUnidadeRealizadoraCompra": codigo_unidade_realizadora_compra,
        "codigoModalidadeCompra": codigo_modalidade_compra,
        "codigoTipo": codigo_tipo,
        "codigoCategoria": codigo_categoria,
        "dataVigenciaInicialMin": data_vigencia_inicial_min,
        "dataVigenciaInicialMax": data_vigencia_inicial_max,
        "niFornecedor": ni_fornecedor,
        "numeroContrato": numero_contrato,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-contratos/1_consultarContratos",
        params,
        source=SOURCE,
    )


async def consultar_contratos_itens(
    *,
    codigo_orgao: int,
    data_vigencia_inicial_min: str,
    data_vigencia_inicial_max: str,
    codigo_unidade_gestora: str | None = None,
    codigo_unidade_gestora_origem_contrato: str | None = None,
    codigo_unidade_realizadora_compra: str | None = None,
    numero_contrato: str | None = None,
    codigo_modalidade_compra: str | None = None,
    tipo_item: str | None = None,
    codigo_item: int | None = None,
    ni_fornecedor: str | None = None,
    poder: str | None = None,
    esfera: str | None = None,
    id_compra: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta itens de contrato por vigência (``/modulo-contratos/2_consultarContratosItem``).

    Diferente de :func:`consultar_contratos` (que só traz o valor global do
    contrato), este endpoint devolve a **itemização** — preço unitário por
    item (``valorUnitarioItem``), com o código de catálogo (CATMAT/CATSER)
    em ``codigoItem`` — uma fonte de preço de referência real (contrato já
    assinado, não estimado) na granularidade de item, que nenhuma outra tool
    deste servidor cobre hoje.

    ``codigo_orgao`` é **obrigatório** (confirmado ao vivo — sem ele a API
    devolve HTTP 404 "Resource not found", mesmo com um intervalo de datas
    válido; não é um erro de "sem resultados", é parâmetro ausente).
    ``data_vigencia_inicial_min``/``data_vigencia_inicial_max`` também são
    obrigatórios e o Compras.gov.br rejeita (HTTP 400) intervalos maiores
    que 365 dias — mesma regra já vista em ``consultar_arp``.

    Cada item devolvido traz ``numeroControlePncpContrato``/
    ``numeroControlePncpCompra`` prontos para pivotar às tools do PNCP
    (``consultar_contratacao_pncp``, ``consultar_familia_contratacao_pncp``).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "codigoOrgao": codigo_orgao,
        "codigoUnidadeGestora": codigo_unidade_gestora,
        "codigoUnidadeGestoraOrigemContrato": codigo_unidade_gestora_origem_contrato,
        "codigoUnidadeRealizadoraCompra": codigo_unidade_realizadora_compra,
        "numeroContrato": numero_contrato,
        "codigoModalidadeCompra": codigo_modalidade_compra,
        "tipoItem": tipo_item,
        "codigoItem": codigo_item,
        "niFornecedor": ni_fornecedor,
        "dataVigenciaInicialMin": data_vigencia_inicial_min,
        "dataVigenciaInicialMax": data_vigencia_inicial_max,
        "poder": poder,
        "esfera": esfera,
        "idCompra": id_compra,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-contratos/2_consultarContratosItem",
        params,
        source=SOURCE,
    )


async def consultar_contratos_fim_vigencia(
    *,
    codigo_orgao: str,
    data_vigencia_final_min: str,
    data_vigencia_final_max: str,
    codigo_unidade_gestora: str | None = None,
    codigo_unidade_gestora_origem_contrato: str | None = None,
    codigo_unidade_realizadora_compra: str | None = None,
    codigo_modalidade_compra: str | None = None,
    codigo_tipo: str | None = None,
    codigo_categoria: str | None = None,
    ni_fornecedor: str | None = None,
    numero_contrato: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta contratos por FIM de vigência — radar de vencimento (``/modulo-contratos/1.2_consultarContratos_FimVigencia``).

    Variante de :func:`consultar_contratos` que filtra pela janela de
    ``dataVigenciaFinal`` (quando o contrato VENCE) em vez de
    ``dataVigenciaInicial`` — achado 2.4,
    dá suporte à tool ``radar_vencimentos`` (planejamento de renovação/
    repactuação antes do fim da vigência). Mesma forma de retorno de
    :func:`consultar_contratos` (mesmo endpoint "irmão", só muda o filtro de
    data) — inclusive a mesma pegadinha real já confirmada nele:
    ``codigo_orgao`` **obrigatório** (HTTP 404 "Resource not found" sem ele,
    não uma lista vazia — ver docstring de :func:`consultar_contratos`).
    ``data_vigencia_final_min``/``data_vigencia_final_max`` também são
    obrigatórios, formato ``AAAA-MM-DD``.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "codigoOrgao": codigo_orgao,
        "codigoUnidadeGestora": codigo_unidade_gestora,
        "codigoUnidadeGestoraOrigemContrato": codigo_unidade_gestora_origem_contrato,
        "codigoUnidadeRealizadoraCompra": codigo_unidade_realizadora_compra,
        "codigoModalidadeCompra": codigo_modalidade_compra,
        "codigoTipo": codigo_tipo,
        "codigoCategoria": codigo_categoria,
        "dataVigenciaFinalMin": data_vigencia_final_min,
        "dataVigenciaFinalMax": data_vigencia_final_max,
        "niFornecedor": ni_fornecedor,
        "numeroContrato": numero_contrato,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-contratos/1.2_consultarContratos_FimVigencia",
        params,
        source=SOURCE,
    )


async def consultar_arp_fim_vigencia(
    *,
    data_vigencia_final_min: str,
    data_vigencia_final_max: str,
    codigo_unidade_gerenciadora: str | None = None,
    codigo_modalidade_compra: str | None = None,
    numero_ata_registro_preco: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta ARP por FIM de vigência — radar de vencimento (``/modulo-arp/1.2_consultarARP_FimVigencia``).

    Variante de :func:`consultar_arp` que filtra pela janela de
    ``dataVigenciaFinal`` (quando a ata deixa de valer, inclusive para
    novas adesões/caronas) em vez de ``dataVigenciaInicial`` — achado 2.4
, dá suporte à tool
    ``radar_vencimentos``. Diferente da variante de contratos
    (:func:`consultar_contratos_fim_vigencia`), ``codigo_unidade_gerenciadora``
    é **opcional** aqui — mesmo padrão de :func:`consultar_arp`, cuja janela
    de datas sozinha já é um filtro válido no servidor.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "codigoUnidadeGerenciadora": codigo_unidade_gerenciadora,
        "codigoModalidadeCompra": codigo_modalidade_compra,
        "numeroAtaRegistroPreco": numero_ata_registro_preco,
        "dataVigenciaFinalMin": data_vigencia_final_min,
        "dataVigenciaFinalMax": data_vigencia_final_max,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-arp/1.2_consultarARP_FimVigencia",
        params,
        source=SOURCE,
    )


async def consultar_precos_material(
    codigo_item_catalogo: int,
    *,
    tipo_codigo: str = "codigoItemCatalogo",
    codigo_uasg: str | None = None,
    estado: str | None = None,
    codigo_municipio: int | None = None,
    data_resultado: bool | None = None,
    codigo_classe: int | None = None,
    data_compra_inicio: str | None = None,
    data_compra_fim: str | None = None,
    poder: str | None = None,
    esfera: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta preços praticados em compras de um item de material (CATMAT).

    ``data_compra_inicio``/``data_compra_fim`` (YYYY-MM-DD), ``poder`` e
    ``esfera`` vêm da spec oficial (v0.2.1 — ver
    a análise das specs oficiais, 2.1): o recorte de data NO SERVIDOR
    mitiga a não-ordenação por data confirmada na v0.1.49.

    Endpoint ``/modulo-pesquisa-preco/1_consultarMaterial`` — a fonte de
    maior prioridade normativa (IN SEGES/ME 65/2021) para pesquisa de
    preços, confirmada ao vivo com dados reais e ricos (preço unitário,
    fornecedor, marca, órgão, UASG, UF, data do resultado).

    **Mudança de contrato da API (confirmada ao vivo 2026-07-28, v0.3.12):**
    este endpoint trocou o parâmetro obrigatório ``codigoItemCatalogo``
    (inteiro) por um par ``tipo`` + ``codigo``, onde ``tipo`` é um enum com
    dois valores — ``"codigoItemCatalogo"`` (buscar por código de ITEM
    CATMAT, padrão) ou ``"codigoPdm"`` (buscar por código de PDM, a
    "família de produto"). Com o parâmetro antigo, o endpoint passou a
    retornar erro (HTTP 404) para qualquer código. O endpoint de SERVIÇO
    (``3_consultarServico``) NÃO mudou — serviço não tem o nível de PDM, por
    isso o discriminador Item/PDM só existe para material.

    ``codigo_item_catalogo`` é o código CATMAT (não confundir com o número
    de item de uma contratação do PNCP) — descubra-o no catálogo de
    materiais do Compras.gov.br. ``tipo_codigo`` indica se ele é um código de
    item (padrão) ou de PDM.

    ``tamanho_pagina``: mínimo 10, máximo 500 (confirmado ao vivo — valores
    fora dessa faixa retornam HTTP 400).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "tipo": tipo_codigo,
        "codigo": codigo_item_catalogo,
        "codigoUasg": codigo_uasg,
        "estado": estado,
        "codigoMunicipio": codigo_municipio,
        "dataResultado": data_resultado,
        "codigoClasse": codigo_classe,
        "dataCompraInicio": data_compra_inicio,
        "dataCompraFim": data_compra_fim,
        "poder": poder,
        "esfera": esfera,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-pesquisa-preco/1_consultarMaterial",
        params,
        source=SOURCE,
    )


async def consultar_precos_servico(
    codigo_item_catalogo: int,
    *,
    codigo_uasg: str | None = None,
    estado: str | None = None,
    codigo_municipio: int | None = None,
    data_resultado: bool | None = None,
    data_compra_inicio: str | None = None,
    data_compra_fim: str | None = None,
    poder: str | None = None,
    esfera: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta preços praticados em compras de um item de serviço (CATSER).

    Filtros de data/poder/esfera: mesmos da função de material.

    Endpoint ``/modulo-pesquisa-preco/3_consultarServico`` — mesma fonte
    prioritária de :func:`consultar_precos_material`, para serviços.

    **Achado real (2026-07-10, corrige suposição anterior deste projeto):**
    este endpoint ACEITA sim ``tamanhoPagina`` — confirmado ao vivo (chamada
    direta com ``codigoItemCatalogo=27332``/``tamanhoPagina=100`` devolveu
    ~100 registros, não os 10 da página padrão). A suposição anterior (de
    que o parâmetro não existia aqui) estava errada e limitava
    ``buscar_precos_praticados_compras`` a só 10 resultados por chamada para
    serviços, mesmo quando ``limite`` pedia mais. O Swagger público
    (https://dadosabertos.compras.gov.br/swagger-ui) confirma o parâmetro,
    com valor padrão 10 — mantido o mesmo teto de 500 já usado no endpoint
    de material, por cautela (não testado acima de 100 ao vivo).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "codigoItemCatalogo": codigo_item_catalogo,
        "codigoUasg": codigo_uasg,
        "estado": estado,
        "codigoMunicipio": codigo_municipio,
        "dataResultado": data_resultado,
        "dataCompraInicio": data_compra_inicio,
        "dataCompraFim": data_compra_fim,
        "poder": poder,
        "esfera": esfera,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-pesquisa-preco/3_consultarServico",
        params,
        source=SOURCE,
    )


async def listar_grupos_material() -> list[dict[str, Any]]:
    """Lista todos os grupos do catálogo de materiais (CATMAT) — nível mais amplo.

    Endpoint ``/modulo-material/1_consultarGrupoMaterial``. Confirmado ao
    vivo que este endpoint IGNORA os parâmetros de paginação e sempre
    devolve a lista completa (79 registros ativos+inativos) numa única
    chamada — por isso cacheada por :data:`TTL_1_DIA` sem paginar.
    """
    resposta = await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-material/1_consultarGrupoMaterial",
        {"pagina": 1},
        source=SOURCE,
        cache_key="compras:grupos_material",
        cache_ttl_seconds=TTL_1_DIA,
    )
    return (resposta or {}).get("resultado", []) or []


async def listar_classes_material() -> list[dict[str, Any]]:
    """Lista todas as classes do catálogo de materiais (CATMAT).

    Endpoint ``/modulo-material/2_consultarClasseMaterial``. Mesmo
    comportamento de :func:`listar_grupos_material` — ignora paginação e
    devolve os ~325 registros completos numa só chamada. Cacheada por
    :data:`TTL_1_DIA`.
    """
    resposta = await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-material/2_consultarClasseMaterial",
        {"pagina": 1},
        source=SOURCE,
        cache_key="compras:classes_material",
        cache_ttl_seconds=TTL_1_DIA,
    )
    return (resposta or {}).get("resultado", []) or []


async def listar_secoes_servico() -> list[dict[str, Any]]:
    """Lista todas as seções do catálogo de serviços (CATSER) — nível mais amplo.

    Endpoint ``/modulo-servico/1_consultarSecaoServico``. Confirmado ao vivo
 que o endpoint devolve os 6 registros
    completos (``totalPaginas: 1``) numa única chamada com ``pagina=1``, sem
    precisar paginar. Cada registro traz ``codigoSecao``, ``nomeSecao``,
    ``statusSecao`` e ``dataHoraAtualizacao``. Cacheada por :data:`TTL_1_DIA`.
    """
    resposta = await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-servico/1_consultarSecaoServico",
        {"pagina": 1},
        source=SOURCE,
        cache_key="compras:secoes_servico",
        cache_ttl_seconds=TTL_1_DIA,
    )
    return (resposta or {}).get("resultado", []) or []


async def listar_divisoes_servico(codigo_secao: int | None = None) -> list[dict[str, Any]]:
    """Lista divisões do catálogo de serviços (CATSER), opcionalmente por seção.

    Endpoint ``/modulo-servico/2_consultarDivisaoServico``. Confirmado ao
    vivo com ``codigoSecao=1`` (7
    registros, ``totalPaginas: 1``) e com um código inexistente (resultado
    vazio, sem erro HTTP). Cada registro traz ``codigoSecao``/``nomeSecao``
    além de ``codigoDivisao``/``nomeDivisao``/``statusDivisao``. Sem cache
    (lista relativamente pequena e navegação interativa via
    ``navegar_catalogo_servico``).
    """
    params: dict[str, Any] = {"pagina": 1}
    if codigo_secao is not None:
        params["codigoSecao"] = codigo_secao
    resposta = await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-servico/2_consultarDivisaoServico",
        params,
        source=SOURCE,
    )
    return (resposta or {}).get("resultado", []) or []


async def listar_grupos_servico(codigo_divisao: int | None = None) -> list[dict[str, Any]]:
    """Lista grupos do catálogo de serviços (CATSER), opcionalmente por divisão.

    Endpoint ``/modulo-servico/3_consultarGrupoServico``. Confirmado ao vivo
 que, sem filtro, devolve os 148
    registros completos numa única chamada (``totalPaginas: 1``, mesmo
    comportamento de ignorar paginação das demais listas deste módulo).
    Cada registro traz ``codigoDivisao``/``nomeDivisao`` além de
    ``codigoGrupo``/``nomeGrupo``/``statusGrupo`` (``nomeSecao`` vem sempre
    ``null`` neste endpoint). Sem cache quando filtrado por divisão; lista
    completa cacheada por :data:`TTL_1_DIA` quando chamada sem filtro.
    """
    params: dict[str, Any] = {"pagina": 1}
    if codigo_divisao is not None:
        params["codigoDivisao"] = codigo_divisao
        resposta = await get_json(
            settings.compras_dadosabertos_base_url,
            "/modulo-servico/3_consultarGrupoServico",
            params,
            source=SOURCE,
        )
        return (resposta or {}).get("resultado", []) or []
    resposta = await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-servico/3_consultarGrupoServico",
        params,
        source=SOURCE,
        cache_key="compras:grupos_servico",
        cache_ttl_seconds=TTL_1_DIA,
    )
    return (resposta or {}).get("resultado", []) or []


async def listar_classes_servico() -> list[dict[str, Any]]:
    """Lista todas as classes do catálogo de serviços (CATSER).

    Endpoint ``/modulo-servico/4_consultarClasseServico``. Mesmo
    comportamento das listas de material acima — ignora paginação e
    devolve os ~276 registros completos numa só chamada. Cacheada por
    :data:`TTL_1_DIA`.

    Cada registro já traz ``codigoGrupo``/``nomeGrupo`` além de
    ``codigoClasse``/``nomeClasse`` — suficiente para
    ``descobrir_codigo_catalogo`` buscar por nome sem precisar de uma
    chamada extra para o nível de grupo.
    """
    resposta = await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-servico/4_consultarClasseServico",
        {"pagina": 1},
        source=SOURCE,
        cache_key="compras:classes_servico",
        cache_ttl_seconds=TTL_1_DIA,
    )
    return (resposta or {}).get("resultado", []) or []


async def listar_subclasses_servico(codigo_classe: int) -> list[dict[str, Any]]:
    """Lista subclasses do catálogo de serviços (CATSER) de uma classe específica.

    Endpoint ``/modulo-servico/5_consultarSubClasseServico`` filtrado por
    ``codigoClasse`` — exigido porque, confirmado ao vivo,
    a chamada sem filtro devolve um volume grande
    de registros (centenas, ao contrário das listas de seção/grupo/classe
    acima, que cabem numa única página). Nem toda classe tem subclasses
    cadastradas (algumas devolvem lista vazia — comportamento normal, não é
    erro). Cada registro traz ``codigoClasse``/``nomeClasse`` além de
    ``codigoSubclasse``/``nomeSubclasse``/``statusSubclasse``. Sem cache
    (navegação pontual via ``navegar_catalogo_servico``).
    """
    resposta = await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-servico/5_consultarSubClasseServico",
        {"pagina": 1, "codigoClasse": codigo_classe},
        source=SOURCE,
    )
    return (resposta or {}).get("resultado", []) or []


async def listar_pdms_material_ativos() -> list[dict[str, Any]]:
    """Lista TODOS os PDMs ativos do catálogo de materiais (CATMAT), paginando.

    Um PDM ("Padrão Descritivo de Material") é o nível de "família de
    produto" do CATMAT (ex.: "NOTEBOOK", "CARTUCHO CANETA TINTEIRO") — mais
    específico que classe/grupo, porém sem a explosão combinatória dos
    itens individuais (~15 mil PDMs ativos contra centenas de milhares de
    itens). É o nível mais granular sobre o qual dá para fazer uma busca
    textual completa e barata no lado do cliente, já que a API não oferece
    busca por substring (ver módulo).

    **Paginação POR GRUPO (v0.3.12, correção de drift confirmado ao vivo
    2026-07-28):** até a v0.3.11 esta função varria todos os ~15 mil PDMs
    numa lista única, paginando a 1000 por vez. A API do Compras.gov.br
    passou a **limitar o offset (pagina × tamanhoPagina) a ~10.000
    registros**: como há 15.020 PDMs ativos, a partir da 11ª página (offset
    10.000) o endpoint retorna HTTP 400 — e como esta listagem roda ANTES de
    qualquer casamento de termo, ``descobrir_codigo_catalogo`` quebrava para
    QUALQUER termo de material (o de serviço, que usa o catálogo raso de
    classes, seguia funcionando). Confirmado ao vivo: ``pagina=1`` OK,
    ``pagina=11&tamanhoPagina=1000`` (offset 10.000, dentro do total) já dá
    erro.

    A correção contorna o teto paginando **por grupo** (filtro
    ``codigoGrupo`` sobre os 79 grupos do catálogo): cada grupo tem no
    máximo alguns milhares de PDMs (o maior confirmado ao vivo, INFORMÁTICA,
    tem 338), então cada varredura fica muito abaixo do teto e a cobertura
    continua completa. Custa ~79 requisições na primeira chamada da sessão;
    o resultado agregado é cacheado por :data:`TTL_1_DIA`.
    """
    cache_key = "compras:pdms_material_ativos"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    grupos = await listar_grupos_material()
    todos: list[dict[str, Any]] = []
    tamanho_pagina = 500
    for grupo in grupos:
        codigo_grupo = grupo.get("codigoGrupo")
        if codigo_grupo is None:
            continue
        pagina = 1
        total_paginas = 1
        while pagina <= total_paginas:
            resposta = await get_json(
                settings.compras_dadosabertos_base_url,
                "/modulo-material/3_consultarPdmMaterial",
                {
                    "pagina": pagina,
                    "tamanhoPagina": tamanho_pagina,
                    "statusPdm": True,
                    "codigoGrupo": codigo_grupo,
                },
                source=SOURCE,
            )
            pagina_itens = (resposta or {}).get("resultado", []) or []
            if not pagina_itens:
                break
            todos.extend(pagina_itens)
            total_paginas = (resposta or {}).get("totalPaginas", 1) or 1
            pagina += 1

    cache.set(cache_key, todos, TTL_1_DIA)
    return todos


async def listar_itens_material_por_pdm(
    codigo_pdm: int, *, pagina: int = 1, tamanho_pagina: int = 10
) -> dict[str, Any]:
    """Lista itens (com código CATMAT real) de um PDM do catálogo de materiais.

    Endpoint ``/modulo-material/4_consultarItemMaterial`` filtrado por
    ``codigoPdm`` — usado por ``descobrir_codigo_catalogo`` para mostrar uma
    amostra de itens reais (``codigoItem``/``descricaoItem``, os valores
    que ``buscar_precos_praticados_compras`` espera em
    ``codigo_item_catalogo``) dentro de um PDM encontrado por busca textual
    no lado do cliente. Cacheada por :data:`TTL_30_MIN`.

    **Bug real encontrado ao vivo:** ``tamanho_pagina`` era limitado
    a ``max(1, min(tamanho_pagina, 100))`` — permitindo valores abaixo de 10.
    ``descobrir_codigo_catalogo`` chama esta função com ``tamanho_pagina=5``
    (amostra de itens de exemplo), e o endpoint rejeita qualquer valor fora
    do intervalo 10-500 com HTTP 400 ("Informe um número de paginação no
    intervalo de 10 a 500") — confirmado ao vivo, reproduzido de forma
    determinística (funciona quando a busca não encontra PDM nenhum, e
    quebra assim que encontra um PDM e tenta buscar a amostra de itens).
    Mesmo limite documentado (10-500) já usado em ``consultar_precos_material``
    e outros endpoints deste cliente — só faltava aqui.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-material/4_consultarItemMaterial",
        {
            "pagina": pagina,
            "tamanhoPagina": tamanho_pagina,
            "codigoPdm": codigo_pdm,
            "statusItem": True,
        },
        source=SOURCE,
        cache_key=f"compras:itens_material_pdm:{codigo_pdm}:{pagina}:{tamanho_pagina}",
        cache_ttl_seconds=TTL_30_MIN,
    )


async def listar_itens_servico_por_classe(
    codigo_classe: int, *, pagina: int = 1, tamanho_pagina: int = 10
) -> dict[str, Any]:
    """Lista itens (com código CATSER real) de uma classe do catálogo de serviços.

    Endpoint ``/modulo-servico/6_consultarItemServico`` filtrado por
    ``codigoClasse`` — usado por ``descobrir_codigo_catalogo`` para mostrar
    uma amostra de serviços reais (``codigoServico``/``nomeServico``)
    dentro de uma classe encontrada por busca textual no lado do cliente.
    Cacheada por :data:`TTL_30_MIN`.

    Diferente do módulo de materiais, este endpoint não tem um nível
    intermediário equivalente ao PDM — ``codigoSubclasse`` existe no
    schema, mas confirmado ao vivo que vem ``null`` na maioria dos
    registros (não é populado de forma consistente), então
    ``descobrir_codigo_catalogo`` usa apenas classe/grupo para a busca.

    **Mesmo bug de ``listar_itens_material_por_pdm``** — o limite
    aqui também permitia ``tamanho_pagina`` abaixo de 10 (chamada real de
    ``descobrir_codigo_catalogo`` usa 5), e o endpoint rejeita com HTTP 400.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-servico/6_consultarItemServico",
        {
            "pagina": pagina,
            "tamanhoPagina": tamanho_pagina,
            "codigoClasse": codigo_classe,
            "statusServico": True,
        },
        source=SOURCE,
        cache_key=f"compras:itens_servico_classe:{codigo_classe}:{pagina}:{tamanho_pagina}",
        cache_ttl_seconds=TTL_30_MIN,
    )


async def consultar_fornecedor(
    *,
    ativo: bool,
    cnpj: str | None = None,
    cpf: str | None = None,
    natureza_juridica_id: int | None = None,
    porte_empresa_id: int | None = None,
    codigo_cnae: int | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta o cadastro de fornecedor no SICAF (``/modulo-fornecedor/1_consultarFornecedor``).

    Endpoint confirmado na especificação OpenAPI oficial e testado ao vivo — resposta real inclui ``habilitadoLicitar``
    (booleano indicando se o fornecedor está apto a licitar/contratar no
    SICAF), além de ``ativo``, ``nomeRazaoSocialFornecedor``, CNAE, natureza
    jurídica, porte e UF/município. **Não** confundir com o cadastro de CNPJ
    na Receita Federal (``clients/cnpj_client.py``) — são fontes diferentes;
    só este endpoint tem ``habilitadoLicitar``.

    ``ativo`` é **obrigatório** na API real (confirmado ao vivo) — filtra
    fornecedores com cadastro ativo (``True``) ou inativo (``False``) no
    SICAF. Um CNPJ pode não aparecer com ``ativo=True`` mas aparecer com
    ``ativo=False`` (cadastro existente porém inativo) — quem chama esta
    função precisa tentar os dois valores para diferenciar "inativo" de
    "nunca cadastrado" (ver ``tools/consultar_situacao_fornecedor.py``, que
    já faz essa tentativa dupla).

    Cacheada por :data:`TTL_30_MIN` — situação de habilitação no SICAF pode
    mudar, então não usa o TTL longo (:data:`TTL_1_DIA`) reservado para
    catálogos estáticos.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "cnpj": cnpj,
        "cpf": cpf,
        "naturezaJuridicaId": natureza_juridica_id,
        "porteEmpresaId": porte_empresa_id,
        "codigoCnae": codigo_cnae,
        "ativo": ativo,
    }
    cache_key = (
        f"compras:fornecedor:{cnpj}:{cpf}:{natureza_juridica_id}:"
        f"{porte_empresa_id}:{codigo_cnae}:{ativo}:{pagina}:{tamanho_pagina}"
    )
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-fornecedor/1_consultarFornecedor",
        params,
        source=SOURCE,
        cache_key=cache_key,
        cache_ttl_seconds=TTL_30_MIN,
    )


async def consultar_uasg(
    *,
    status_uasg: bool,
    codigo_uasg: str | None = None,
    cnpj_cpf_orgao: str | None = None,
    cnpj_cpf_orgao_vinculado: str | None = None,
    cnpj_cpf_orgao_superior: str | None = None,
    sigla_uf: str | None = None,
    uso_sisg: bool | None = None,
    pagina: int = 1,
) -> dict[str, Any]:
    """Consulta UASGs (``/modulo-uasg/1_consultarUasg``).

    ``status_uasg`` é **obrigatório** na API real (confirmado ao vivo) —
    filtra UASGs ativas (``True``) ou inativas (``False``).

    **Atenção:** este endpoint **não aceita** ``tamanhoPagina`` — confirmado
    ao vivo (nem sequer é declarado como parâmetro na especificação
    OpenAPI): a página sempre vem com 500 registros, ignorando qualquer
    valor solicitado. Mesmo padrão de cautela já adotado neste projeto para
    outras pegadinhas de API (ver ``consultar_precos_servico`` acima e
    ``pncp_client.py``) — por isso a função nem expõe esse parâmetro, para
    não sugerir um controle que não funciona.

    Não cacheada individualmente (usada internamente por
    :func:`listar_uasgs_ativas`, que cacheia o agregado paginado).
    """
    params = {
        "pagina": pagina,
        "codigoUasg": codigo_uasg,
        "cnpjCpfOrgao": cnpj_cpf_orgao,
        "cnpjCpfOrgaoVinculado": cnpj_cpf_orgao_vinculado,
        "cnpjCpfOrgaoSuperior": cnpj_cpf_orgao_superior,
        "siglaUf": sigla_uf,
        "usoSisg": uso_sisg,
        "statusUasg": status_uasg,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-uasg/1_consultarUasg",
        params,
        source=SOURCE,
    )


async def consultar_orgao(
    *,
    status_orgao: bool,
    codigo_orgao: int | None = None,
    cnpj_cpf_orgao: str | None = None,
    cnpj_cpf_orgao_vinculado: str | None = None,
    cnpj_cpf_orgao_superior: str | None = None,
    uso_sisg: bool | None = None,
    pagina: int = 1,
) -> dict[str, Any]:
    """Consulta órgãos (``/modulo-uasg/2_consultarOrgao``).

    ``status_orgao`` é **obrigatório** na API real (confirmado ao vivo).
    Diferente de :func:`consultar_uasg`, este endpoint **não tem filtro de
    UF** — órgãos são entidades nacionais, não vinculadas a um único
    estado (a UF é um atributo da UASG, não do órgão). Também não aceita
    ``tamanhoPagina`` (mesma pegadinha, confirmada ao vivo — 500 por
    página, fixo).

    Não cacheada individualmente (usada internamente por
    :func:`listar_orgaos_ativos`).
    """
    params = {
        "pagina": pagina,
        "codigoOrgao": codigo_orgao,
        "cnpjCpfOrgao": cnpj_cpf_orgao,
        "cnpjCpfOrgaoVinculado": cnpj_cpf_orgao_vinculado,
        "cnpjCpfOrgaoSuperior": cnpj_cpf_orgao_superior,
        "usoSisg": uso_sisg,
        "statusOrgao": status_orgao,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-uasg/2_consultarOrgao",
        params,
        source=SOURCE,
    )


async def listar_uasgs_ativas(*, sigla_uf: str | None = None) -> list[dict[str, Any]]:
    """Lista TODAS as UASGs ativas, paginando (``statusUasg=True``).

    Confirmado ao vivo: ~21.941 UASGs ativas no Brasil todo (44 páginas de
    500) — sem filtro de UF, a primeira chamada de uma sessão pode levar
    vários segundos. Informar ``sigla_uf`` filtra no SERVIDOR antes de
    paginar (ex.: SP sozinho tem ~3.123 UASGs, 7 páginas) — muito mais
    rápido; use sempre que souber o estado, mesmo que aproximado.

    Cacheada por :data:`TTL_1_DIA` (cadastro de UASGs muda raramente),
    com uma chave por valor de ``sigla_uf`` (``None`` = lista nacional
    completa, cacheada separadamente das listas por UF).
    """
    cache_key = f"compras:uasgs_ativas:{sigla_uf or 'BR'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    todos: list[dict[str, Any]] = []
    pagina = 1
    total_paginas = 1
    while pagina <= total_paginas:
        resposta = await consultar_uasg(status_uasg=True, sigla_uf=sigla_uf, pagina=pagina)
        pagina_itens = (resposta or {}).get("resultado", []) or []
        if not pagina_itens:
            break
        todos.extend(pagina_itens)
        total_paginas = (resposta or {}).get("totalPaginas", 1) or 1
        pagina += 1

    cache.set(cache_key, todos, TTL_1_DIA)
    return todos


async def consultar_arp(
    *,
    data_vigencia_inicial_min: str,
    data_vigencia_inicial_max: str,
    codigo_unidade_gerenciadora: str | None = None,
    codigo_modalidade_compra: str | None = None,
    numero_ata_registro_preco: str | None = None,
    data_assinatura_inicial: str | None = None,
    data_assinatura_final: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta Atas de Registro de Preço por vigência (``/modulo-arp/1_consultarARP``).

    ``data_vigencia_inicial_min``/``data_vigencia_inicial_max`` são
    obrigatórios na API real (confirmado ao vivo), formato ``AAAA-MM-DD``.
    Resposta real inclui ``numeroControlePncpAta``/``numeroControlePncpCompra``
    já prontos — permitem pivotar direto para
    ``pncp_client.consultar_ata_registro_preco``/``consultar_contratacao_pncp``
    sem precisar montar o número manualmente.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "codigoUnidadeGerenciadora": codigo_unidade_gerenciadora,
        "codigoModalidadeCompra": codigo_modalidade_compra,
        "numeroAtaRegistroPreco": numero_ata_registro_preco,
        "dataVigenciaInicialMin": data_vigencia_inicial_min,
        "dataVigenciaInicialMax": data_vigencia_inicial_max,
        "dataAssinaturaInicial": data_assinatura_inicial,
        "dataAssinaturaFinal": data_assinatura_final,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url, "/modulo-arp/1_consultarARP", params, source=SOURCE,
    )


async def consultar_arp_itens(
    *,
    data_vigencia_inicial_min: str,
    data_vigencia_inicial_max: str,
    codigo_unidade_gerenciadora: int | None = None,
    codigo_modalidade_compra: str | None = None,
    data_assinatura_inicial: str | None = None,
    data_assinatura_final: str | None = None,
    numero_item: str | None = None,
    codigo_item: int | None = None,
    tipo_item: str | None = None,
    ni_fornecedor: str | None = None,
    codigo_pdm: int | None = None,
    numero_compra: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta itens de ARP por vigência (``/modulo-arp/2_consultarARPItem``).

    **Não tem filtro por ``numeroAtaRegistroPreco``** (confirmado ao vivo —
    ausente da spec e do comportamento real) — cada item devolvido TRAZ esse
    campo, mas filtrar "os itens desta ata" exige filtrar no cliente pelo
    resultado (por unidade+vigência, opcionalmente com ``numero_compra`` se
    já conhecido). Ver nota no topo do módulo.

    Resposta real inclui, por item: ``valorUnitario`` (preço registrado —
    referência válida, é o preço da ata, não uma estimativa),
    ``quantidadeHomologadaVencedor``, ``maximoAdesao`` (teto de adesão por
    "carona"), ``quantidadeEmpenhada``, ``niFornecedor``/
    ``nomeRazaoSocialFornecedor``, ``codigoPdm``/``nomePdm``.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "codigoUnidadeGerenciadora": codigo_unidade_gerenciadora,
        "codigoModalidadeCompra": codigo_modalidade_compra,
        "dataVigenciaInicialMin": data_vigencia_inicial_min,
        "dataVigenciaInicialMax": data_vigencia_inicial_max,
        "dataAssinaturaInicial": data_assinatura_inicial,
        "dataAssinaturaFinal": data_assinatura_final,
        "numeroItem": numero_item,
        "codigoItem": codigo_item,
        "tipoItem": tipo_item,
        "niFornecedor": ni_fornecedor,
        "codigoPdm": codigo_pdm,
        "numeroCompra": numero_compra,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url, "/modulo-arp/2_consultarARPItem", params, source=SOURCE,
    )


async def consultar_arp_unidades_item(
    *,
    numero_ata: str,
    unidade_gerenciadora: str,
    numero_item: str,
    data_atualizacao: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta unidades participantes de um item de ARP (``/modulo-arp/3_consultarUnidadesItem``).

    ``numero_ata``, ``unidade_gerenciadora`` e ``numero_item`` são
    obrigatórios (confirmado ao vivo) — é uma consulta de DETALHE de um item
    já conhecido, não uma busca. Resposta real inclui ``quantidadeRegistrada``,
    ``saldoAdesoes``, ``saldoRemanejamentoEmpenho``, ``qtdLimiteAdesao``,
    ``aceitaAdesao``.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "numeroAta": numero_ata,
        "unidadeGerenciadora": unidade_gerenciadora,
        "numeroItem": numero_item,
        "dataAtualizacao": data_atualizacao,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url, "/modulo-arp/3_consultarUnidadesItem", params, source=SOURCE,
    )


async def consultar_arp_empenhos_item(
    *,
    numero_ata: str,
    unidade_gerenciadora: str,
    data_atualizacao: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta empenhos e saldo de itens de uma ARP (``/modulo-arp/4_consultarEmpenhosSaldoItem``).

    ``numero_ata`` e ``unidade_gerenciadora`` são obrigatórios (confirmado
    ao vivo). Diferente de :func:`consultar_arp_unidades_item`, **não** aceita
    ``numero_item`` — devolve os empenhos de TODOS os itens da ata numa
    chamada só (cada registro já traz ``numeroItem``). Resposta real inclui
    ``quantidadeRegistrada``, ``quantidadeEmpenhada``, ``saldoEmpenho``.
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "numeroAta": numero_ata,
        "unidadeGerenciadora": unidade_gerenciadora,
        "dataAtualizacao": data_atualizacao,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url, "/modulo-arp/4_consultarEmpenhosSaldoItem", params, source=SOURCE,
    )


async def consultar_arp_adesoes_item(
    *,
    numero_ata: str,
    unidade_gerenciadora: str,
    numero_item: str,
    unidade: str | None = None,
    data_atualizacao: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Consulta adesões ("caronas") de um item de ARP (``/modulo-arp/5_consultarAdesoesItem``).

    ``numero_ata``, ``unidade_gerenciadora`` e ``numero_item`` são
    obrigatórios (confirmado ao vivo). ``unidade`` filtra por uma unidade
    solicitante específica da adesão; sem ele, devolve todas as adesões
    daquele item. Lista vazia é uma resposta normal (item sem adesões ainda
    — confirmado ao vivo, não é erro).
    """
    tamanho_pagina = max(10, min(tamanho_pagina, 500))
    params = {
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "numeroAta": numero_ata,
        "unidadeGerenciadora": unidade_gerenciadora,
        "numeroItem": numero_item,
        "unidade": unidade,
        "dataAtualizacao": data_atualizacao,
    }
    return await get_json(
        settings.compras_dadosabertos_base_url, "/modulo-arp/5_consultarAdesoesItem", params, source=SOURCE,
    )


async def listar_orgaos_ativos() -> list[dict[str, Any]]:
    """Lista TODOS os órgãos ativos, paginando (``statusOrgao=True``).

    Confirmado ao vivo: ~11.840 órgãos ativos (24 páginas de 500) — sem
    filtro de UF disponível nesta API (ver :func:`consultar_orgao`), então
    sempre pagina a lista nacional completa. Cacheada por :data:`TTL_1_DIA`
    (cadastro de órgãos muda raramente) — primeira chamada de uma sessão
    paga o custo de paginar; as seguintes, dentro do TTL, são instantâneas.
    """
    cache_key = "compras:orgaos_ativos"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    todos: list[dict[str, Any]] = []
    pagina = 1
    total_paginas = 1
    while pagina <= total_paginas:
        resposta = await consultar_orgao(status_orgao=True, pagina=pagina)
        pagina_itens = (resposta or {}).get("resultado", []) or []
        if not pagina_itens:
            break
        todos.extend(pagina_itens)
        total_paginas = (resposta or {}).get("totalPaginas", 1) or 1
        pagina += 1

    cache.set(cache_key, todos, TTL_1_DIA)
    return todos


async def listar_unidades_fornecimento_material(
    codigo_pdm: int, *, apenas_ativas: bool = True
) -> list[dict[str, Any]]:
    """Unidades de fornecimento válidas de um PDM de material (CATMAT).

    Endpoint ``/modulo-material/6_consultarMaterialUnidadeFornecimento``.
    Devolve, por PDM (família de produto), as unidades em que aquele
    material pode ser fornecido — ``siglaUnidadeFornecimento``,
    ``nomeUnidadeFornecimento`` (ex.: "UNIDADE", "PACOTE", "CAIXA"),
    ``descricaoUnidadeFornecimento``, ``capacidadeUnidadeFornecimento``
    (ex.: "50 UN") e ``siglaUnidadeMedida``.

    É a tabela de conversão OFICIAL do catálogo: com a capacidade dá para
    trazer um preço praticado "por pacote com 50" para a base unitária, em
    vez de compará-lo diretamente com um preço "por unidade". Tabela de
    domínio, muda raramente — cacheada por :data:`TTL_1_DIA` por PDM.
    """
    resposta = await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-material/6_consultarMaterialUnidadeFornecimento",
        {
            "pagina": 1,
            "tamanhoPagina": 500,
            "codigoPdm": codigo_pdm,
            "statusUnidadeFornecimentoPdm": apenas_ativas or None,
        },
        source=SOURCE,
        cache_key=f"compras:unidades_pdm:{codigo_pdm}:{apenas_ativas}",
        cache_ttl_seconds=TTL_1_DIA,
    )
    return (resposta or {}).get("resultado", []) or []


async def listar_unidades_medida_servico(
    codigo_servico: int, *, apenas_ativas: bool = True
) -> list[dict[str, Any]]:
    """Unidades de medida válidas de um item de serviço (CATSER).

    Endpoint ``/modulo-servico/7_consultarUndMedidaServico``. Equivalente
    de :func:`listar_unidades_fornecimento_material` para serviços — que
    não têm o nível de PDM, por isso a chave é o próprio código CATSER.
    Cacheada por :data:`TTL_1_DIA`.
    """
    resposta = await get_json(
        settings.compras_dadosabertos_base_url,
        "/modulo-servico/7_consultarUndMedidaServico",
        {
            "pagina": 1,
            "codigoServico": codigo_servico,
            "statusUnidadeMedida": apenas_ativas or None,
        },
        source=SOURCE,
        cache_key=f"compras:unidades_servico:{codigo_servico}:{apenas_ativas}",
        cache_ttl_seconds=TTL_1_DIA,
    )
    return (resposta or {}).get("resultado", []) or []
