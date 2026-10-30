"""Tool MCP: lista exaustivamente os contratos/empenhos de um órgão no PNCP.

Por que existe: a pergunta "quantos contratos o órgão X assinou em 2026?"
tinha respostas muito diferentes — 47 via ``buscar_contratos_compras``
(busca textual) contra 176+ consultando o PNCP filtrado por CNPJ do órgão,
período a período. Mesmo sem o antigo filtro fixo de vigência,
``buscar_contratos_compras`` continua sendo busca textual (depende do termo aparecer no índice, tem teto
de resultados) e não uma listagem exaustiva por órgão.

Esta tool fecha essa lacuna usando a API de Consulta oficial do PNCP
(``clients.pncp_client.consultar_contratos``, endpoint ``/v1/contratos``,
``operationId`` ``consultarContratosPorDataPublicacao``) — que já existia no
cliente desde a v0.1.13 (criada durante a correção do achado de
``buscar_contratos_fornecedor_pncp``) mas nunca tinha sido usada por nenhuma tool. Diferente da busca
textual, este endpoint filtra **no servidor** por ``cnpjOrgao`` — não depende
de o objeto do contrato mencionar o nome do órgão, e cobre tanto Termos de
Contrato formais quanto Empenhos com força de contrato.

**Tradução oficial do schema — pendência da v0.1.27 fechada na v0.2.2.**
Até a v0.2.1, esta tool devolvia cada registro de contrato praticamente
cru, com os nomes de campo exatos da API. A partir da v0.2.2, cada registro
é traduzido para ``snake_case`` com base no schema oficial documentado
(``RecuperarContratoDTO`` — API de Consulta do PNCP, ver
a análise das specs oficiais, seção 3.4): ``numero_controle_pncp``,
``objeto``, ``fornecedor`` (``cnpj``/``nome``), ``tipo_contrato``
(``id``/``nome`` — ainda assim, para decodificar outros códigos de domínio
encontrados nos registros, use ``consultar_tabelas_dominio_pncp``),
``valores`` (``valor_inicial``/``valor_global``/``valor_acumulado``/
``valor_parcela``), ``datas`` (``data_assinatura``/``data_vigencia_inicio``/
``data_vigencia_fim``), ``fruto_adesao``, ``tem_remanejamento``,
``receita``, ``emenda_parlamentar``, ``numero_parcelas``,
``numero_retificacao``, ``categoria_processo``, ``orgao`` (``cnpj``/
``razao_social``) e ``unidade`` (``codigo``/``nome``/``uf``/``municipio``).
Validado com casos reais antes de fechar esta pendência (contratos do TCU,
mesma amostra usada no achado de ``compra_origem`` — v0.1.36). Os campos
originais e completos da API continuam disponíveis, sem tradução, em
``dados_originais`` quando ``incluir_bruto=True`` for passado (padrão
``False`` — não incluído por padrão para não duplicar o payload à toa).

**Vínculo contrato → compra de origem — confirmado ao vivo e IMPLEMENTADO
(v0.1.36).** Pedido de usuário (via análise cruzada com um relatório do
ChatGPT sobre o que faltava no MCP): dado um contrato, encontrar
automaticamente o edital/TR/ETP/anexos que o originaram. Testado ao vivo em
2026-07-08 contra contratos reais do TCU (CNPJ 00414607000118, via o
próprio MCP conectado): o campo ``numeroControlePncpCompra`` vem sempre
preenchido — inclusive em registros com ``tipoContrato`` "Empenho" — no
mesmo formato ``CNPJ-1-SEQUENCIAL/ANO`` já tratado por
``pncp_client.parse_numero_controle_pncp()``. Cada registro devolvido por
esta tool agora inclui um campo adicional ``compra_origem`` (``cnpj``,
``ano``, ``sequencial``, prontos para ``listar_arquivos_pncp(tipo_documento="edital", ...)``,
e ``link_pagina_pncp``, mesmo padrão de URL usado por
``consultar_contratacao_pncp`` desde a v0.1.30) — ``None`` só no caso raro
de o campo vir ausente ou em formato inesperado.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from ..clients import pncp_client
from ..clients.pncp_client import parse_numero_controle_pncp
from ..domain import cobertura as cobertura_mod
from ..domain.cobertura import MotivoInterrupcao, StatusCobertura
from ..logging_utils import get_logger
from ..utils.datas import janela_dias_atras
from ..utils.documentos import aviso_cnpj_alfanumerico, mascarar_documento, validar_cnpj

logger = get_logger(__name__)

_DIAS_POR_FATIA = 30
_MAX_FATIAS = 40  # ~3,3 anos de teto de segurança por chamada
_TAMANHO_PAGINA = 50  # limite documentado da própria API de Consulta
_LIMITE_MAXIMO = 2000
_CAMPOS_CHAVE_CANDIDATOS = (
    "numeroControlePNCP",
    "numeroControlePncpCompra",
    "numeroContratoEmpenho",
    "id",
)


def _fatiar_periodo(data_inicial: str, data_final: str) -> tuple[list[tuple[str, str]], bool]:
    """Divide ``[data_inicial, data_final]`` (``AAAAMMDD``) em fatias de
    ``_DIAS_POR_FATIA`` dias — reduz o tamanho de cada chamada à API de
    Consulta oficial (mais estável sob instabilidade do PNCP do que uma
    única chamada cobrindo um período longo,).

    Retorna ``(fatias, truncado)`` — ``truncado=True`` se o período pedido
    excedeu ``_MAX_FATIAS`` fatias (teto de segurança contra chamadas com
    período absurdamente longo).
    """
    inicio = datetime.strptime(data_inicial, "%Y%m%d")
    fim = datetime.strptime(data_final, "%Y%m%d")
    if inicio > fim:
        inicio, fim = fim, inicio

    fatias: list[tuple[str, str]] = []
    cursor = inicio
    truncado = False
    while cursor <= fim:
        if len(fatias) >= _MAX_FATIAS:
            truncado = True
            break
        fim_fatia = min(cursor + timedelta(days=_DIAS_POR_FATIA - 1), fim)
        fatias.append((cursor.strftime("%Y%m%d"), fim_fatia.strftime("%Y%m%d")))
        cursor = fim_fatia + timedelta(days=1)
    return fatias, truncado


def _compra_origem(registro: dict[str, Any]) -> dict[str, Any] | None:
    """Extrai a identificação da compra/edital que originou este contrato/
    empenho, a partir de ``numeroControlePncpCompra`` — confirmado ao vivo
    em 2026-07-08 (contratos reais do TCU, CNPJ 00414607000118), presente
    mesmo em registros de Empenho. Devolve ``cnpj``/``ano``/``sequencial``
    já prontos para ``listar_arquivos_pncp(tipo_documento="edital", ...)``
    (obtém TR/ETP/anexos) e ``link_pagina_pncp`` (mesmo padrão de URL de
    ``consultar_contratacao_pncp``, v0.1.30). ``None`` se o campo estiver
    ausente ou em formato inesperado — nunca derruba o restante do
    resultado.
    """
    numero = registro.get("numeroControlePncpCompra")
    if not numero:
        return None
    parsed = parse_numero_controle_pncp(numero)
    if parsed is None:
        return None
    cnpj, ano, sequencial = parsed
    return {
        "cnpj": cnpj,
        "ano": ano,
        "sequencial": sequencial,
        "numero_controle_pncp_compra": numero,
        "link_pagina_pncp": f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}",
    }


def _traduzir_contrato(registro: dict[str, Any]) -> dict[str, Any]:
    """Traduz um registro cru da API de Consulta oficial (``RecuperarContratoDTO``)
    para ``snake_case`` — ver docstring do módulo (pendência da v0.1.27,
    fechada na v0.2.2 com base no schema oficial documentado em
    a análise das specs oficiais, seção 3.4).
    """
    tipo_contrato = registro.get("tipoContrato") or {}
    orgao_entidade = registro.get("orgaoEntidade") or {}
    unidade_orgao = registro.get("unidadeOrgao") or {}
    return {
        "numero_controle_pncp": registro.get("numeroControlePNCP"),
        "objeto": registro.get("objetoContrato"),
        "fornecedor": {
            "cnpj": mascarar_documento(registro.get("niFornecedor")),
            "nome": registro.get("nomeRazaoSocialFornecedor"),
        },
        "tipo_contrato": {
            "id": tipo_contrato.get("id"),
            "nome": tipo_contrato.get("nome"),
        },
        "valores": {
            "valor_inicial": registro.get("valorInicial"),
            "valor_global": registro.get("valorGlobal"),
            "valor_acumulado": registro.get("valorAcumulado"),
            "valor_parcela": registro.get("valorParcela"),
        },
        "datas": {
            "data_assinatura": registro.get("dataAssinatura"),
            "data_vigencia_inicio": registro.get("dataVigenciaInicio"),
            "data_vigencia_fim": registro.get("dataVigenciaFim"),
        },
        "fruto_adesao": registro.get("frutoAdesao"),
        "tem_remanejamento": registro.get("temRemanejamento"),
        "receita": registro.get("receita"),
        "emenda_parlamentar": registro.get("emendaParlamentar"),
        "numero_parcelas": registro.get("numeroParcelas"),
        "numero_retificacao": registro.get("numeroRetificacao"),
        "categoria_processo": registro.get("categoriaProcesso"),
        "orgao": {
            "cnpj": orgao_entidade.get("cnpj"),
            "razao_social": orgao_entidade.get("razaoSocial"),
        },
        "unidade": {
            "codigo": unidade_orgao.get("codigoUnidade"),
            "nome": unidade_orgao.get("nomeUnidade"),
            "uf": unidade_orgao.get("ufSigla"),
            "municipio": unidade_orgao.get("municipioNome"),
        },
        "numero_controle_pncp_compra": registro.get("numeroControlePncpCompra"),
        "numero_controle_pncp_ata": registro.get("numeroControlePncpAta"),
    }


def _formatar_registro(registro: dict[str, Any], incluir_bruto: bool) -> dict[str, Any]:
    """Monta o registro final devolvido pela tool: campos traduzidos +
    ``compra_origem`` + ``dados_originais`` só quando
    ``incluir_bruto=True`` (ver docstring do módulo)."""
    formatado = _traduzir_contrato(registro)
    formatado["compra_origem"] = _compra_origem(registro)
    if incluir_bruto:
        formatado["dados_originais"] = registro
    return formatado


def _chave_registro(registro: dict[str, Any]) -> str:
    """Chave de deduplicação defensiva — tenta campos plausíveis de
    identificação única (nomes exatos não confirmados ao vivo nesta versão,
    ver docstring do módulo); na ausência de todos, cai para um hash
    determinístico do conteúdo do registro (nunca falha, na pior das
    hipóteses trata dois registros idênticos como duplicata legítima)."""
    for campo in _CAMPOS_CHAVE_CANDIDATOS:
        valor = registro.get(campo)
        if valor:
            return f"{campo}:{valor}"
    return "hash:" + json.dumps(registro, sort_keys=True, default=str)


async def consultar_contratos_orgao_pncp(
    cnpj_orgao: str,
    data_inicial: str | None = None,
    data_final: str | None = None,
    janelas_meses: int = 12,
    limite: int = 500,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Lista exaustivamente os contratos/empenhos de um órgão no PNCP, por CNPJ + período.

    Complementa ``buscar_contratos_compras`` (busca textual, não exaustiva)
    para perguntas do tipo "quantos contratos o órgão X assinou no período
    Y" — usa a API de Consulta oficial do PNCP, filtrada no servidor por
    ``cnpjOrgao`` (não depende de o objeto do contrato mencionar o nome do
    órgão no texto). Ver docstring do módulo para a limitação conhecida
    sobre o formato exato dos campos de cada registro.

    Internamente, o período pedido é fatiado em janelas de ~30 dias (mais
    resiliente à instabilidade conhecida do PNCP do que uma única chamada
    cobrindo um período longo) e cada fatia é paginada até o fim
    (``tamanhoPagina=50``, teto da própria API). Uma falha isolada numa
    fatia (ex.: PNCP fora do ar) não derruba a consulta inteira — fica
    registrada em ``avisos``, e o resultado das demais fatias é devolvido
    mesmo assim (deixando claro que pode estar incompleto).

    Args:
        cnpj_orgao: CNPJ do órgão contratante (14 posições, com ou sem
            máscara — obrigatório; sem ele, o endpoint devolveria a
            listagem geral de contratos de todo o PNCP no período, que
            pode chegar a milhões de registros).
        data_inicial: Início do período, formato ``AAAAMMDD``. Se omitido
            junto com ``data_final``, usa os últimos ``janelas_meses``
            meses a partir de hoje.
        data_final: Fim do período, formato ``AAAAMMDD``.
        janelas_meses: Janela em meses a partir de hoje, usada só quando
            ``data_inicial``/``data_final`` não são informados (padrão 12).
        limite: Número máximo de registros a devolver (padrão 500, máx.
            2000 — teto de segurança; períodos muito longos de órgãos
            grandes podem ter dezenas de milhares de registros no PNCP).
        incluir_bruto: Se True, cada registro também traz ``dados_originais``
            com os campos exatos e completos da API, sem tradução (padrão
            False — ver docstring do módulo).

    Returns:
        Dicionário com ``cnpj_orgao``, ``periodo`` (``data_inicial``/
        ``data_final`` efetivamente usados), ``quantidade_retornada``,
        ``contratos`` (lista de registros traduzidos para ``snake_case`` —
        ver docstring do módulo para o mapeamento completo — cada um com um
        campo adicional ``compra_origem``: ``cnpj``/``ano``/``sequencial``
        da compra/edital que originou o contrato, prontos para
        ``listar_arquivos_pncp(tipo_documento="edital", ...)``, e
        ``link_pagina_pncp`` já montado; ``None`` no raro caso de o campo
        de origem vir ausente) e ``avisos`` (falhas parciais por fatia,
        truncamento por ``limite`` ou por período excessivamente longo, e
        ausência de resultados).
    """
    if not cnpj_orgao or not cnpj_orgao.strip():
        raise ValueError("cnpj_orgao é obrigatório")
    cnpj_limpo = validar_cnpj(cnpj_orgao, campo="cnpj_orgao")
    aviso_alfanumerico = aviso_cnpj_alfanumerico(cnpj_limpo)

    if bool(data_inicial) != bool(data_final):
        raise ValueError("Informe data_inicial E data_final juntos, ou nenhum dos dois.")
    if data_inicial and data_final:
        inicio, fim = data_inicial, data_final
    else:
        inicio, fim = janela_dias_atras(janelas_meses * 30)

    limite = max(1, min(limite, _LIMITE_MAXIMO))

    logger.info(
        "consultar_contratos_orgao_pncp cnpj_orgao=%s data_inicial=%s data_final=%s limite=%s",
        cnpj_limpo, inicio, fim, limite,
    )

    fatias, periodo_truncado = _fatiar_periodo(inicio, fim)

    resultados: list[dict[str, Any]] = []
    vistos: set[str] = set()
    avisos: list[str] = []
    if aviso_alfanumerico:
        # Primeiro da lista de propósito: se a fonte recusar o formato novo,
        # esta tool devolve zero contratos, e zero contratos é a resposta
        # legítima para um órgão que de fato não contratou no período.
        avisos.append(aviso_alfanumerico)
    limite_atingido = False
    # esta tool não tem UM envelope de resposta
    # (faz fan-out em fatias de ~30 dias, cada uma paginada até o fim), então
    # `total_paginas`/`numero_pagina`/`paginas_restantes` do DTO oficial não
    # têm um significado único aqui — omitidos de propósito. `total_registros`
    # É somável com segurança (fatias são janelas de data disjuntas, um
    # mesmo contrato só pode cair numa fatia): soma o `totalRegistros` da
    # primeira página de cada fatia processada com sucesso. Só é incluído no
    # retorno se TODAS as fatias tocadas confirmaram o campo — caso
    # contrário seria uma soma parcial travestida de total real.
    soma_total_registros = 0
    total_registros_confiavel = True
    fatias_com_erro: list[str] = []

    for fatia_inicio, fatia_fim in fatias:
        if len(resultados) >= limite:
            limite_atingido = True
            total_registros_confiavel = False
            break
        pagina = 1
        while True:
            try:
                bruto = await pncp_client.consultar_contratos(
                    data_inicial=fatia_inicio, data_final=fatia_fim,
                    cnpj_orgao=cnpj_limpo, pagina=pagina, tamanho_pagina=_TAMANHO_PAGINA,
                )
            except Exception as exc:  # noqa: BLE001 - falha isolada não deve derrubar a consulta inteira
                fatias_com_erro.append(f"{fatia_inicio}-{fatia_fim}")
                logger.warning(
                    "falha ao consultar contratos %s-%s (página %s): %s",
                    fatia_inicio, fatia_fim, pagina, exc,
                )
                avisos.append(
                    f"Falha ao consultar o período {fatia_inicio}-{fatia_fim} (página "
                    f"{pagina}): {exc}. O resultado pode estar incompleto para este "
                    "período — tente novamente mais tarde ou estreite o período."
                )
                total_registros_confiavel = False
                break

            # `get_json` devolve None em HTTP 204 e em corpo vazio — e o
            # endpoint de contratos do PNCP responde 204 para uma janela sem
            # contratos, que é situação NORMAL numa varredura de 30 em 30
            # dias. Até a v0.5.3 o `bruto.get` logo abaixo estourava
            # 'NoneType' object has no attribute 'get' FORA do try, abortando
            # a varredura inteira — inclusive as fatias que tinham dados.
            #
            # Tratar como página vazia é a leitura correta: o laço abaixo já
            # faz `break` quando não há dados, e `total_fatia` fica None, o
            # que marca `total_registros_confiavel = False` — exatamente o
            # que se quer dizer quando a fonte não informou o total.
            bruto = bruto or {}

            if pagina == 1:
                total_fatia = bruto.get("totalRegistros")
                if isinstance(total_fatia, int) and not isinstance(total_fatia, bool):
                    soma_total_registros += total_fatia
                else:
                    total_registros_confiavel = False

            dados = bruto.get("data") or []
            if not dados:
                break

            for registro in dados:
                chave = _chave_registro(registro)
                if chave in vistos:
                    continue
                vistos.add(chave)
                # Nunca mutação in-place: `registro` pode ser a MESMA
                # instância de dict devolvida em chamadas diferentes (o mock
                # de teste reusa `return_value`; o cache em memória de
                # `pncp_client` também pode devolver o mesmo objeto
                # cacheado) — mutar o original faria `_chave_registro` de
                # uma repetição futura calcular hash sobre um dict já
                # alterado, quebrando a deduplicação. `_formatar_registro`
                # sempre constrói um dict novo (via `_traduzir_contrato`).
                resultados.append(_formatar_registro(registro, incluir_bruto))
                if len(resultados) >= limite:
                    limite_atingido = True
                    break

            if limite_atingido:
                break

            total_paginas = bruto.get("totalPaginas") or 1
            if pagina >= total_paginas or len(dados) < _TAMANHO_PAGINA:
                break
            pagina += 1

        if limite_atingido:
            break

    if periodo_truncado:
        avisos.append(
            f"Período pedido excede o teto de {_MAX_FATIAS * _DIAS_POR_FATIA} dias "
            f"processados por chamada — resultado cobre só {fatias[0][0]} a "
            f"{fatias[-1][1]}, não o período completo pedido. Faça uma nova chamada "
            "para o restante do período."
        )
        total_registros_confiavel = False
    if limite_atingido:
        avisos.append(
            f"Resultado truncado no limite de {limite} registro(s) — pode haver mais "
            "contratos/empenhos além dos retornados aqui. Aumente 'limite' ou estreite "
            "o período (data_inicial/data_final) para uma nova chamada."
        )
    if not resultados:
        avisos.append(
            "Nenhum contrato/empenho encontrado para este CNPJ no período informado."
        )

    resultado_final: dict[str, Any] = {
        "cnpj_orgao": cnpj_limpo,
        "periodo": {"data_inicial": inicio, "data_final": fim},
        "quantidade_retornada": len(resultados),
        "contratos": resultados,
        "avisos": avisos,
    }
    # total_registros só entra quando a soma por
    # fatia é confiável (nenhuma fatia faltando total, sem truncamento) — ver
    # comentário acima do loop. total_paginas/numero_pagina/paginas_restantes
    # deliberadamente omitidos (sem significado de página única nesta tool).
    if total_registros_confiavel:
        resultado_final["total_registros"] = soma_total_registros

    # `cobertura` estruturado. Traduz para um contrato comum o que
    # `total_registros_confiavel` e os avisos já diziam em prosa — a diferença
    # é que agora dá para decidir por programa se o resultado autoriza
    # afirmar inexistência.
    if fatias_com_erro:
        status = StatusCobertura.PARCIAL
        motivo = MotivoInterrupcao.ERRO_DA_FONTE
    elif limite_atingido or periodo_truncado:
        status = StatusCobertura.PARCIAL
        motivo = (
            MotivoInterrupcao.LIMITE_DE_VARREDURA
            if limite_atingido
            else MotivoInterrupcao.ORCAMENTO_EXECUCAO
        )
    elif not total_registros_confiavel:
        # A varredura terminou sem erro, mas a fonte não informou os totais:
        # não dá para dizer que percorreu tudo, nem que não percorreu.
        status = StatusCobertura.INDETERMINADA
        motivo = MotivoInterrupcao.TOTAL_NAO_INFORMADO
    elif not resultados:
        status, motivo = StatusCobertura.VAZIA, None
    else:
        status, motivo = StatusCobertura.EXAUSTIVA, None

    bloco = cobertura_mod.montar(
        fonte="PNCP",
        status=status,
        registros_retornados=len(resultados),
        total_no_universo=soma_total_registros if total_registros_confiavel else None,
        motivo=motivo,
        erros_externos=[a for a in avisos if "Falha ao consultar o período" in a],
        detalhes={
            "quantidade_janelas": len(fatias),
            "janelas_com_erro": fatias_com_erro,
            "periodo_truncado": periodo_truncado,
        },
    )
    texto = cobertura_mod.aviso(bloco)
    if texto:
        avisos.insert(0, texto)
    resultado_final["cobertura"] = bloco
    return resultado_final
