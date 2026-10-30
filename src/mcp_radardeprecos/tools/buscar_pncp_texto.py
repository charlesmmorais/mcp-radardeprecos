"""Tool MCP: busca textual livre no PNCP (editais, atas de registro de preço e contratos).

**Limitação conhecida de ``termo_busca`` — confirmada ao vivo em 2026-07-08
contra ``/api/search`` (ver docstring completa em
``clients.pncp_client.buscar_texto``):** aspas NÃO funcionam como busca por
frase exata (em torno de 1 palavra são ignoradas; em torno de uma frase
produzem um resultado diferente e imprevisível, não uma restrição exata);
múltiplas palavras funcionam como "E" (bag-of-words) e são independentes de
ordem, não como frase; termos curtos casam por **prefixo**, não por palavra
inteira (``"note"`` trouxe quase o mesmo volume que ``"notebook"``). Prefira
termos mais longos/específicos e os filtros estruturados desta tool (``uf``,
``modalidade``, ``orgao`` etc.) para reduzir ruído, em vez de aspas.
"""
from __future__ import annotations

from typing import Any

from ..clients import pncp_client
from ..config import settings
from ..domain.dominios import MODALIDADES_PNCP, TIPOS_DOCUMENTO_BUSCA_PNCP
from ..logging_utils import get_logger
from ..utils.datas import aviso_indice_parcial, dentro_da_janela
from ..utils.varredura import (
    MAX_PAGINAS_BUSCA_PNCP,
    TAMANHO_PAGINA_BUSCA_PNCP,
    aviso_motivo_da_parada,
    aviso_orcamento,
    aviso_ordenacao_crescente_com_janela,
    aviso_paginas_com_falha,
    varrer_indice,
)

logger = get_logger(__name__)

# 100 páginas * 100 registros = 10.000, o teto REAL do índice de busca do
# PNCP (pagina*tamanhoPagina<=10000, HTTP 400 acima disso — confirmado ao
# vivo em 2026-07-11 e documentado por Transparência Brasil/OCP, 06/2024).
# Mesmo teto usado por buscar_contratacoes_pncp/buscar_contratos_compras.
_MAX_PAGINAS_JANELA = MAX_PAGINAS_BUSCA_PNCP
_TAMANHO_PAGINA_BUSCA_JANELA = TAMANHO_PAGINA_BUSCA_PNCP


def _validar_ano(ano: Any) -> int | None:
    """Aceita UM ano; recusa em voz alta qualquer coisa que o índice engoliria.

    Medido em 2026-08-21 contra o ``/api/search``:

    - ``anos=2024`` .............. 3.552 de 24.501, todos de 2024 — filtra bem.
    - ``anos=2023&anos=2024`` .... 3.552, só de 2024 — IGNORA o primeiro valor.
    - ``anos=2023,2024`` ......... **total=0**, silenciosamente.

    Os dois últimos são a razão desta função. Quem pedir dois anos recebe um
    só, ou recebe zero — e nos dois casos a resposta se parece com um fato
    sobre o acervo ("só há 3.552 registros", "não há nenhum") quando é
    artefato do parâmetro. É o falso negativo que este projeto mais combate,
    e ele estava a um argumento de distância.

    Recusar é melhor que corrigir: se aceitássemos ``"2023,2024"`` e
    fizéssemos duas buscas, a soma não bateria com o ``total`` devolvido, e a
    inconsistência apareceria depois, mais difícil de explicar.
    """
    if ano is None:
        return None
    if isinstance(ano, bool):  # bool é subclasse de int — barra antes
        raise ValueError("ano deve ser um ano civil (ex.: 2026), não booleano")
    if isinstance(ano, int):
        return ano
    texto = str(ano).strip()
    if "," in texto or " " in texto:
        raise ValueError(
            f"ano={ano!r}: o índice do PNCP aceita UM ano por chamada. Vírgula "
            "faz o servidor devolver ZERO resultados sem erro, e repetir o "
            "parâmetro faz ele considerar só o último valor — nos dois casos a "
            "resposta parece um fato sobre o acervo e não é. Faça uma chamada "
            "por ano, ou use janelas_meses (que filtra por data de publicação "
            "no cliente)."
        )
    try:
        return int(texto)
    except ValueError:
        raise ValueError(f"ano={ano!r} não é um ano civil válido (ex.: 2026)") from None


async def buscar_pncp_texto(
    termo_busca: str,
    tipo_documento: str,
    uf: str | None = None,
    municipio: str | None = None,
    modalidade: int | None = None,
    # `int | str` de propósito, e não `int`: com `int`, o Pydantic do FastMCP
    # recusa "2023,2024" ANTES de a função começar, e o cliente recebe
    # "Input should be a valid integer ... type=int_parsing" — que ensina que
    # o campo é numérico e NÃO ensina que o índice do PNCP aceita um ano por
    # chamada, nem que a saída é fazer duas buscas. Relatado num teste real em
    # 2026-08-21. Aceitar str aqui deixa `_validar_ano` rodar e falar de
    # domínio; ela devolve int, então nada muda para o cliente HTTP.
    ano: int | str | None = None,
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
    janelas_meses: int | None = None,
    ordenacao: str = "-data",
    pagina: int = 1,
    tamanho_pagina: int = 10,
) -> dict[str, Any]:
    """Busca textual no PNCP via endpoint indexado (``/api/search``) — mesmo backend do site.

    Cobre todos os filtros disponíveis nas páginas de busca do PNCP
    (Editais/Atas/Contratos). Use ``listar_filtros_pncp`` para descobrir os
    códigos/IDs válidos de cada filtro categórico antes de usá-los aqui.

    Args:
        termo_busca: Termos de busca sobre o objeto do documento. **Aspas
            não funcionam como frase exata** (ignoradas para 1 palavra;
            comportamento diferente e imprevisível para frases — ver
            docstring do módulo). Múltiplas palavras casam como "E"
            (bag-of-words, independente de ordem), não como frase. Termos
            curtos casam por prefixo, não por palavra inteira — prefira
            termos mais longos/específicos.

            **O casamento NÃO se limita à descrição exibida.** Observado em
            2026-08-21: o primeiro resultado de ``"notebook"`` foi um edital
            de locação de tendas e sonorização em São José das Palmeiras-PR,
            sem a palavra em nenhum ponto da descrição. O índice do PNCP casa
            em campos que não vêm na resposta — provavelmente os itens da
            contratação, embora o backend não documente quais. Consequência
            prática: um resultado aparentemente fora do tema pode ser um
            acerto legítimo num item avulso, e não lixo. Antes de descartar,
            confira os itens com ``consultar_contratacao_pncp``.
        tipo_documento: "edital", "ata" (registro de preços) ou "contrato".

            **"edital" é mais amplo do que o nome sugere** e NÃO significa só
            licitação: é a categoria do backend, e traz ``tipo_id`` 1 (Edital),
            2 (Aviso de Contratação Direta) e 3 (Ato que autoriza a Contratação
            Direta) — ou seja, dispensa e inexigibilidade entram no mesmo bolo.
            Os três foram observados numa mesma bateria de testes. Para
            restringir a licitações de fato, use ``tipo_instrumento=1``.
        uf: Sigla da UF (ex: SP, DF, RS). Uma UF por chamada.
        municipio: ID interno do PNCP do município (campo ``id`` retornado
            por ``listar_filtros_pncp`` — **não** é o código IBGE).
        modalidade: Código de modalidade PNCP (ex.: 6 = Pregão Eletrônico).
        ano: Ano para filtrar, UM por chamada (filtro nativo do servidor).

            **NÃO é o ano de publicação.** É o ano da CONTRATAÇÃO, o mesmo que
            aparece em ``numero_controle_pncp``. Verificado em 2026-08-21: um
            "Edital nº 800111/2024", com ``ano="2024"``, tem
            ``data_publicacao_pncp`` de 26/01/2026. Filtrar por ano e esperar
            recorte de período produz omissão silenciosa — para janela
            temporal use ``janelas_meses``.

            Dois anos numa chamada não funcionam, e falham mal: vírgula
            (``"2023,2024"``) faz o servidor devolver ZERO sem erro, e repetir
            o parâmetro faz ele considerar só o último valor. A tool recusa
            ambos em voz alta, em vez de deixar a resposta parecer um fato
            sobre o acervo.
        tipo_instrumento: Código do tipo de instrumento convocatório (1 =
            Edital, 2 = Aviso de Contratação Direta, 3 = Ato que autoriza
            Contratação Direta, 4 = Edital de Chamamento Público).
        tipo_contrato: Código do tipo de contrato (específico de
            tipo_documento="contrato" — ex.: 1 = Contrato (termo inicial),
            7 = Empenho, 6 = Convênio; ver ``listar_filtros_pncp``).
        orgao: ID do órgão (campo ``id`` da faceta "orgaos", não o CNPJ).
        unidade: ID da unidade (campo ``id`` da faceta "unidades", não o
            código da unidade).
        esfera: "F" (Federal), "E" (Estadual), "M" (Municipal), "D"
            (Distrital) ou "N" (Não se aplica).
        poder: "E" (Executivo), "L" (Legislativo), "J" (Judiciário) ou "N"
            (Não se aplica).
        fonte_orcamentaria: Código da fonte orçamentária.
        tipo_margem_preferencia: Código do tipo de margem de preferência.
        exigencia_conteudo_nacional: Filtro booleano (true/false); omitir
            para não filtrar.
        possui_emenda_parlamentar: Filtro booleano (true/false); omitir para
            não filtrar.
        permite_adesao: Filtro booleano "Permite Adesão" (específico de atas
            de registro de preço); omitir para não filtrar.
        status: Depende do tipo — para edital: "recebendo_proposta" |
            "propostas_encerradas" | "encerradas" | "todos"; para ata/contrato:
            "vigente" | "nao_vigente" | "todos". Omitir equivale a "todos".
        janelas_meses: Se informado, filtra os resultados por data de
            publicação (``data_publicacao_pncp``) dentro dos últimos N meses
            a partir de hoje. **Filtro aplicado no cliente**: o backend do
            PNCP (`/api/search`) só filtra por ano civil completo via ``ano``,
            não por janela relativa — não existe parâmetro nativo para isso.

            **O índice NÃO é ordenável por este campo.** Medido em
            2026-08-21: ``ordenacao="-data"`` ordena por
            ``data_atualizacao_pncp``, não por publicação — um edital de abril
            reeditado hoje aparece no topo. A consequência prática é que a
            varredura não tem como parar cedo e precisa percorrer o índice
            até o teto de páginas ou o orçamento de tempo; em buscas amplas,
            espere resultado parcial com aviso. Restringir por ``uf``,
            ``modalidade`` ou ``ano`` reduz o universo e melhora a cobertura
            muito mais do que aumentar ``tamanho_pagina``.
            Quando informado, a tool busca internamente até
            100 páginas de 100 resultados do índice (10.000 registros — o
            teto real da API do PNCP, ``pagina×tamanhoPagina<=10000; mesmo
            limite de ``buscar_contratacoes_pncp``/``buscar_contratos_compras``),
            filtra por data e para ao reunir ``tamanho_pagina`` resultados
            dentro da janela — **``pagina`` é ignorado neste modo** (a busca
            sempre recomeça do início do índice).
        ordenacao: "-data" (padrão) ou "data". **Ordena por data de
            ATUALIZAÇÃO** (``data_atualizacao_pncp``), não de publicação —
            medido em 2026-08-21, e é o que a própria UI do PNCP exibe em
            cada resultado ("Última Atualização"). A UI oferece ainda "Mais
            relevante"; omitir o parâmetro produz essa ordem, com as datas
            embaralhadas. Com ``janelas_meses``, qualquer valor diferente de
            "-data" faz a tool emitir aviso, porque começar pela atualização
            mais antiga torna quase certo terminar no orçamento sem alcançar
            um período recente.
        pagina: Número da página (padrão 1). Ignorado se ``janelas_meses``
            for informado.
        tamanho_pagina: Resultados por página, máximo 100 (padrão 10). Com
            ``janelas_meses``, é o número máximo de resultados a retornar.

    Returns:
        Dicionário com ``items`` (lista de documentos encontrados) e ``total``
        (total no índice do PNCP — não descontado pelo filtro de
        ``janelas_meses``, que é aplicado depois, no cliente).

        **Cuidado com dois campos de nome parecido e sentido diferente.** Em
        ``tipo_documento="contrato"``, ``tipo_nome`` descreve o instrumento de
        ORIGEM (``"Edital"``, ``"Ato que autoriza a Contratação Direta"``), e
        não o contrato; o tipo do contrato em si está em
        ``tipo_contrato_nome`` (``"Contrato (termo inicial)"``, ``"Empenho"``).
        Trocar um pelo outro produz uma afirmação errada que parece certa.

        Quando
        ``janelas_meses`` é informado, o dicionário também traz ``avisos``:
        alerta quando ``total`` supera a quantidade de itens retornados,
        explicando que a diferença normalmente vem da própria janela
        temporal (não um bug de paginação).
    """
    if tipo_documento not in TIPOS_DOCUMENTO_BUSCA_PNCP:
        raise ValueError(f"tipo_documento deve ser um de {TIPOS_DOCUMENTO_BUSCA_PNCP}")
    ano = _validar_ano(ano)
    if modalidade is not None and modalidade not in MODALIDADES_PNCP:
        raise ValueError(
            f"modalidade {modalidade} desconhecida. Códigos válidos: "
            f"{sorted(MODALIDADES_PNCP)} (ver listar_filtros_pncp para nomes)."
        )

    logger.info(
        "buscar_pncp_texto termo=%r tipo=%s uf=%s modalidade=%s orgao=%s status=%s "
        "janelas_meses=%s pagina=%s",
        termo_busca, tipo_documento, uf, modalidade, orgao, status, janelas_meses, pagina,
    )

    if janelas_meses is None:
        return await pncp_client.buscar_texto(
            termo_busca,
            tipo_documento,  # type: ignore[arg-type]
            uf=uf,
            municipio=municipio,
            modalidade=modalidade,
            ano=ano,
            tipo_instrumento=tipo_instrumento,
            tipo_contrato=tipo_contrato,
            orgao=orgao,
            unidade=unidade,
            esfera=esfera,
            poder=poder,
            fonte_orcamentaria=fonte_orcamentaria,
            tipo_margem_preferencia=tipo_margem_preferencia,
            exigencia_conteudo_nacional=exigencia_conteudo_nacional,
            possui_emenda_parlamentar=possui_emenda_parlamentar,
            permite_adesao=permite_adesao,
            status=status,
            ordenacao=ordenacao,
            pagina=pagina,
            tamanho_pagina=tamanho_pagina,
        )

    # Modo "janela de meses": o backend não tem esse filtro, então buscamos
    # várias páginas do índice (helper compartilhado com
    # buscar_contratacoes_pncp/buscar_contratos_compras desde a v0.1.54 —
    # páginas em lotes concorrentes + orçamento de tempo; ver
    # utils/varredura.py) e filtramos por data no cliente.
    limite = max(1, min(tamanho_pagina, 100))

    def _buscar_pagina(p: int):
        return pncp_client.buscar_texto(
            termo_busca,
            tipo_documento,  # type: ignore[arg-type]
            uf=uf,
            municipio=municipio,
            modalidade=modalidade,
            ano=ano,
            tipo_instrumento=tipo_instrumento,
            tipo_contrato=tipo_contrato,
            orgao=orgao,
            unidade=unidade,
            esfera=esfera,
            poder=poder,
            fonte_orcamentaria=fonte_orcamentaria,
            tipo_margem_preferencia=tipo_margem_preferencia,
            exigencia_conteudo_nacional=exigencia_conteudo_nacional,
            possui_emenda_parlamentar=possui_emenda_parlamentar,
            permite_adesao=permite_adesao,
            status=status,
            ordenacao=ordenacao,
            pagina=p,
            tamanho_pagina=_TAMANHO_PAGINA_BUSCA_JANELA,
        )

    # SEM parada antecipada por janela — ver a nota longa em varredura.py
    # (``passou_da_janela``). Resumo: o ``-data`` do /api/search ordena por
    # ``data_atualizacao_pncp``, não pela data de publicação que este filtro
    # usa, então nenhuma ordenação oferecida pelo índice autoriza concluir
    # algo sobre as páginas seguintes.
    #
    # A ordenação ainda importa para o AVISO: começar pela atualização mais
    # antiga (``ordenacao="data"``) torna quase certo que a varredura acabe
    # no orçamento sem alcançar um período recente.
    ordenacao_decrescente = ordenacao == "-data"
    varredura = await varrer_indice(
        _buscar_pagina,
        lambda item: dentro_da_janela(item.get("data_publicacao_pncp"), janelas_meses),
        limite=limite,
        tamanho_pagina=_TAMANHO_PAGINA_BUSCA_JANELA,
        max_paginas=_MAX_PAGINAS_JANELA,
        orcamento_segundos=settings.tool_budget_seconds,
    )
    total_indice = varredura.total_indice
    resultado_final = varredura.coletados[:limite]

    # Aviso quando total (do índice, antes do filtro de janela) supera a
    # quantidade retornada — sem isso, a diferença parece um bug de
    # paginação em vez do efeito esperado de janelas_meses (achado real:
    # busca com total=10 devolvendo só 4 itens, sem nenhuma explicação).
    avisos: list[str] = []
    motivos_reducao = [f"janela de busca de {janelas_meses} mes(es) (parâmetro janelas_meses)"]
    if len(resultado_final) >= limite:
        motivos_reducao.append(f"tamanho_pagina de {limite} resultado(s)")
    aviso_reducao = aviso_indice_parcial(total_indice, len(resultado_final), motivos_reducao)
    if aviso_reducao:
        avisos.append(aviso_reducao)
    # Antes dos demais: se a ordenação sabotou a varredura, esse é o fato que
    # explica todos os outros números, inclusive um resultado vazio.
    if not ordenacao_decrescente:
        avisos.insert(0, aviso_ordenacao_crescente_com_janela(janelas_meses))
    avisos.append(aviso_motivo_da_parada(varredura, limite))
    if varredura.paginas_com_falha:
        avisos.append(aviso_paginas_com_falha(varredura.paginas_com_falha))
    if varredura.orcamento_estourado:
        avisos.append(aviso_orcamento(settings.tool_budget_seconds))

    return {"items": resultado_final, "total": total_indice, "avisos": avisos}
