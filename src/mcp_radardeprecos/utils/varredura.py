"""Varredura paginada do índice de busca do PNCP (``/api/search``), com concorrência e orçamento de tempo.

Extraída na v0.1.54 do padrão que ``buscar_contratacoes_pncp``,
``buscar_contratos_compras`` e ``buscar_pncp_texto`` (modo ``janelas_meses``)
repetiam individualmente — um ``while`` sequencial de até 100 páginas. Duas
melhorias sobre aquele padrão, motivadas pela elevação do teto de varredura
para 100 páginas na v0.1.51 (com 5 páginas, nenhuma das duas fazia
diferença):

1. **Páginas em lotes concorrentes.** A página 1 é buscada sozinha (é dela
   que vem o ``total`` do índice, que delimita a última página real); as
   seguintes são buscadas em lotes de ``lote_concorrente`` simultâneas.
   Numa varredura ampla, isso divide o tempo total por ~``lote_concorrente``
   em relação à busca sequencial. Os itens continuam sendo processados em
   ordem de página (o ``gather`` preserva a ordem do lote), então
   deduplicação e corte por ``limite`` produzem o mesmo resultado da
   varredura sequencial. No caso comum (a página 1 já rende ``limite``
   resultados), nenhum lote é disparado — mesmo custo de antes.

2. **Orçamento de tempo (``orcamento_segundos``).** Uma varredura de 100
   páginas com timeout de 30s e retries por página não tinha teto global —
   o cliente MCP (Claude Desktop/ChatGPT) podia desistir antes de a tool
   responder, perdendo inclusive o trabalho já feito. O orçamento é checado
   entre lotes: ao estourar, a varredura para e devolve o que já coletou,
   com ``orcamento_estourado=True`` para a tool sinalizar em ``avisos``
   (mesmo princípio de transparência de ``atingiu_max_paginas``).
   ``None``/``<= 0`` desativa. O orçamento cobre a varredura do índice — a
   fase de fan-out por resultado (itens/arquivos) é limitada por ``limite``
   (<= 50) e não cresce com o índice.

3. **Tolerância a página que falha.** Uma página do lote que não
   responde é pulada e registrada em ``paginas_com_falha``; a varredura
   segue e a tool devolve o parcial com aviso. Antes, o ``gather`` sem
   ``return_exceptions`` transformava uma falha isolada em falha total,
   descartando tudo que já havia sido coletado. Medido ao vivo em
   2026-08-12: o ``/api/search`` devolve ``ReadError`` de forma
   intermitente em páginas de 100 registros, e um lote de 5 multiplica a
   chance de pelo menos uma falhar — era a causa das "falhas de rede do
   PNCP" relatadas.

A deduplicação por ``numero_controle_pncp`` (itens repetidos entre páginas
do índice) vive aqui; filtros específicos de cada tool (janela temporal,
``tem_resultado``, CNPJ do órgão) entram via ``aceitar_item``.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

#: Registros por página nas varreduras do ``/api/search`` do PNCP.
#:
#: Era 100 até a v0.4.13. Medição ao vivo em 2026-08-12: com 100 registros o
#: endpoint devolve ``ReadError`` de forma intermitente (página 1 passou,
#: página 3 falhou, ambas sequenciais); com 5 registros nunca falhou, nem na
#: página 60. A resposta grande demora o bastante para estourar a leitura.
#: 50 é o meio-termo: metade do tempo de resposta, mesmo alcance total.
TAMANHO_PAGINA_BUSCA_PNCP = 50

#: Teto de páginas correspondente. O PNCP limita ``pagina * tamanhoPagina`` a
#: 10.000, então dobrar o número de páginas ao dividir o tamanho pela metade
#: preserva exatamente o mesmo alcance de 10.000 registros — sem isso, reduzir
#: a página teria cortado pela metade o universo varrido.
MAX_PAGINAS_BUSCA_PNCP = 200


@dataclass
class ResultadoVarredura:
    """Estado final de uma varredura — insumo para os ``avisos`` das tools."""

    coletados: list[dict[str, Any]] = field(default_factory=list)
    total_indice: int = 0
    paginas_percorridas: int = 0
    indice_esgotado: bool = False
    atingiu_max_paginas: bool = False
    orcamento_estourado: bool = False
    #: A varredura parou porque cruzou o limite inferior da janela temporal
    #: (só possível com ordenação decrescente por data). Diferente dos demais
    #: motivos de parada, este NÃO torna o resultado parcial: tudo que restava
    #: estava fora da janela por construção. Ver :func:`varrer_indice`.
    parou_por_janela: bool = False
    #: Páginas (>= 2) que falharam e foram puladas. Cada entrada é
    #: ``(numero_da_pagina, repr_do_erro)``.
    paginas_com_falha: list[tuple[int, str]] = field(default_factory=list)


async def varrer_indice(
    buscar_pagina: Callable[[int], Awaitable[dict[str, Any]]],
    aceitar_item: Callable[[dict[str, Any]], bool],
    *,
    limite: int,
    tamanho_pagina: int,
    max_paginas: int = 100,
    lote_concorrente: int = 5,
    orcamento_segundos: float | None = None,
    passou_da_janela: Callable[[dict[str, Any]], bool] | None = None,
) -> ResultadoVarredura:
    """Varre o índice página a página até coletar ``limite`` itens aceitos.

    Args:
        buscar_pagina: corrotina que recebe o número da página (1-based) e
            devolve o dicionário bruto do índice (``items`` + ``total``).
        aceitar_item: filtro no cliente (janela temporal, homologação etc.);
            a deduplicação por ``numero_controle_pncp`` já acontece antes.
        limite: quantos itens aceitos coletar no máximo.
        tamanho_pagina: tamanho de página usado por ``buscar_pagina`` — uma
            página com menos itens que isso indica o fim do índice.
        max_paginas: teto de páginas. O limite real do PNCP é
            ``pagina × tamanhoPagina <= 10000``, então o teto depende do
            tamanho de página — use :data:`MAX_PAGINAS_BUSCA_PNCP` junto com
            :data:`TAMANHO_PAGINA_BUSCA_PNCP` para varrer os 10.000.
        lote_concorrente: quantas páginas buscar em paralelo após a primeira.
        orcamento_segundos: teto de tempo da varredura (checado entre lotes);
            ``None``/``<= 0`` desativa.
        passou_da_janela: predicado opcional que responde "este item já está
            ALÉM do fim da janela pedida, e todos os seguintes também". Ao
            devolver ``True``, a varredura para e marca ``parou_por_janela``.

            **NENHUM chamador deste módulo o utiliza hoje, e há um motivo
            medido para isso.** O parâmetro foi criado na v0.4.20 para evitar
            que uma janela curta sobre um índice grande queimasse os 120s de
            orçamento varrendo páginas que já não podiam entrar. A premissa
            era que ``ordenacao="-data"`` do ``/api/search`` do PNCP ordenasse
            por ``data_publicacao_pncp`` — o mesmo campo que o filtro de
            janela usa.

            **A premissa é falsa.** Medido em 2026-08-21, 10 primeiros
            resultados de ``q=notebook&ordenacao=-data``:

            - ``data_publicacao_pncp`` NÃO é decrescente. Quebra já no 2º
              item (21/08 → 11/08 → 21/08 → 10/04 → 21/08 …).
            - ``data_atualizacao_pncp`` É estritamente decrescente, sem uma
              violação em 10 itens.

            O índice ordena por data de ATUALIZAÇÃO. Um edital publicado em
            abril e reeditado hoje aparece no topo; um predicado que olhasse
            a publicação concluiria "passei da janela" na 4ª posição da 1ª
            página e descartaria todo o resto — incluindo dezenas publicados
            hoje. Omitir registro é pior que gastar orçamento, então a
            otimização foi desativada em todos os chamadores.

            O parâmetro e seus testes permanecem porque o mecanismo está
            correto; o que falta é uma fonte cuja ordenação se alinhe ao
            filtro. Antes de usá-lo com qualquer índice, MEÇA a monotonicidade
            do campo filtrado ao longo de várias páginas
            (``scripts/verificar_ordenacao_pncp.py`` faz isso para o PNCP).
    """
    inicio = time.monotonic()

    def _estourou() -> bool:
        return (
            orcamento_segundos is not None
            and orcamento_segundos > 0
            and (time.monotonic() - inicio) >= orcamento_segundos
        )

    r = ResultadoVarredura()
    vistos: set[str] = set()

    def _processar(items: list[dict[str, Any]]) -> None:
        for item in items:
            # Antes da deduplicação: um item repetido continua provando que
            # já passamos do fim da janela.
            if passou_da_janela is not None and passou_da_janela(item):
                r.parou_por_janela = True
                return
            numero_controle = item.get("numero_controle_pncp")
            if numero_controle and numero_controle in vistos:
                continue
            if numero_controle:
                vistos.add(numero_controle)
            if not aceitar_item(item):
                continue
            r.coletados.append(item)
            if len(r.coletados) >= limite:
                return

    # Página 1 sozinha: precisamos do "total" dela para saber a última página
    # real antes de disparar lotes (e, no caso comum, ela já basta).
    primeira = await buscar_pagina(1)
    r.paginas_percorridas = 1
    r.total_indice = primeira.get("total", 0) or 0
    items = primeira.get("items", [])
    if items:
        _processar(items)
    if not items or len(items) < tamanho_pagina:
        r.indice_esgotado = True

    if r.total_indice > 0:
        ultima_pagina = min(max_paginas, math.ceil(r.total_indice / tamanho_pagina))
    else:
        ultima_pagina = max_paginas

    proxima = 2
    while (
        not r.indice_esgotado
        and not r.parou_por_janela
        and len(r.coletados) < limite
        and proxima <= ultima_pagina
    ):
        if _estourou():
            r.orcamento_estourado = True
            break
        fim_lote = min(proxima + lote_concorrente - 1, ultima_pagina)
        paginas_do_lote = range(proxima, fim_lote + 1)
        # ``return_exceptions=True`` é o ponto central desta função.
        # Sem ele, UMA página que falha derrubava o ``gather``, a varredura e a
        # tool inteira — jogando fora tudo que já havia sido coletado. E falhar
        # é comum: medido ao vivo em 2026-08-12, o ``/api/search`` do PNCP
        # devolve ``ReadError`` de forma intermitente em páginas grandes, e um
        # lote de 5 páginas eleva a chance de pelo menos uma falhar para
        # ``1-(1-p)^5``. O módulo já devolvia parcial com aviso quando o
        # orçamento estourava ou o teto de páginas era atingido; não fazia isso
        # justamente no modo de falha mais provável.
        respostas = await asyncio.gather(
            *(buscar_pagina(p) for p in paginas_do_lote), return_exceptions=True
        )
        r.paginas_percorridas += len(respostas)
        # Processa em ordem de página (gather preserva a ordem do lote) — o
        # resultado é idêntico ao da varredura sequencial; a única diferença
        # é que ao atingir `limite` no meio de um lote as páginas restantes
        # do lote já foram buscadas (custo aceito em troca do paralelismo).
        for numero_pagina, resposta in zip(paginas_do_lote, respostas, strict=True):
            if isinstance(resposta, BaseException):
                # Página pulada. NÃO marca ``indice_esgotado``: não sabemos se
                # o índice acabou — só que esta página não respondeu. Encerrar
                # aqui esconderia resultados que as páginas seguintes teriam.
                r.paginas_com_falha.append((numero_pagina, repr(resposta)))
                continue
            items = resposta.get("items", [])
            r.total_indice = resposta.get("total", r.total_indice) or r.total_indice
            if not items:
                r.indice_esgotado = True
                break
            _processar(items)
            if r.parou_por_janela:
                break
            if len(items) < tamanho_pagina:
                r.indice_esgotado = True
                break
            if len(r.coletados) >= limite:
                break
        proxima = fim_lote + 1

    r.atingiu_max_paginas = (
        not r.indice_esgotado
        and not r.orcamento_estourado
        and not r.parou_por_janela
        and len(r.coletados) < limite
        and proxima > min(max_paginas, ultima_pagina)
        and r.paginas_percorridas >= min(max_paginas, ultima_pagina)
    )
    return r


def aviso_paginas_com_falha(paginas_com_falha: list[tuple[int, str]]) -> str:
    """Texto padrão de aviso quando páginas do índice não responderam.

    Nomeia as páginas e o erro para que quem leu o resultado saiba que ele é
    incompleto por falha de rede — e não porque o índice acabou ou os filtros
    descartaram tudo. Confundir esses casos leva a conclusões erradas numa
    pesquisa de preços.
    """
    numeros = ", ".join(str(p) for p, _ in paginas_com_falha)
    erros = sorted({erro.split("(")[0] for _, erro in paginas_com_falha})
    return (
        f"{len(paginas_com_falha)} página(s) do índice não responderam e foram "
        f"puladas (página(s) {numeros}; erro(s): {', '.join(erros)}) — o resultado "
        "é PARCIAL e pode omitir registros que existiam nessas páginas. Repita a "
        "chamada para tentar de novo, ou reduza o universo da busca "
        "(termo_busca/filtros) para precisar de menos páginas."
    )


def aviso_motivo_da_parada(r: ResultadoVarredura, limite: int) -> str:
    """Diz POR QUE a varredura parou e quanto do índice ela chegou a ler.

    Existe por um achado de teste em 2026-08-21: o aviso de redução listava as
    causas possíveis juntas — "janela de N meses; tamanho_pagina de N" — sem
    dizer qual delas efetivamente encerrou a varredura, quantas páginas brutas
    foram lidas, nem se o teto do índice foi atingido. Com isso é impossível
    distinguir **"parei porque já tinha o que você pediu"** de **"varri tudo o
    que consegui e era só isso"**.

    A diferença é o que separa um recorte de uma conclusão. No primeiro caso
    ampliar ``tamanho_pagina`` traz mais; no segundo, não traz — e insistir
    sugere ausência onde há apenas teto de API. Numa pesquisa de preços
    auditável, essa frase é o que sustenta a afirmação "o mercado tem N
    fornecedores".
    """
    lidas = f"{r.paginas_percorridas} página(s) do índice lida(s)"
    if r.orcamento_estourado:
        motivo = "o ORÇAMENTO DE TEMPO da varredura estourou"
        consequencia = "há mais registros não lidos; refine os filtros"
    elif r.atingiu_max_paginas:
        motivo = "o TETO DE PÁGINAS da API do PNCP foi atingido (10.000 registros)"
        consequencia = (
            "é o limite do próprio backend — aumentar tamanho_pagina NÃO ajuda; "
            "reduza o universo por termo_busca/uf/modalidade"
        )
    elif r.indice_esgotado:
        motivo = "o ÍNDICE ACABOU — todos os registros da busca foram lidos"
        consequencia = (
            "este é o universo completo para estes filtros; o que ficou de fora "
            "foi descartado pelos filtros do cliente, não por falta de leitura"
        )
    elif len(r.coletados) >= limite:
        motivo = f"o LIMITE PEDIDO ({limite}) foi alcançado"
        consequencia = (
            "há mais registros no índice que não chegaram a ser lidos; "
            "aumente tamanho_pagina se quiser mais"
        )
    else:
        motivo = "a varredura terminou sem um motivo único identificável"
        consequencia = "trate o resultado como parcial"
    extra = ""
    if r.paginas_com_falha:
        extra = f"; {len(r.paginas_com_falha)} página(s) falharam e foram puladas"
    return f"Varredura: {motivo} ({lidas}{extra}) — {consequencia}."


def aviso_ordenacao_crescente_com_janela(janelas_meses: int) -> str:
    """Aviso quando a ordenação escolhida sabota a busca por janela.

    Com ``ordenacao="data"`` a varredura começa pelos registros de atualização
    mais ANTIGA, que quase certamente estão fora de uma janela recente. A
    varredura vai até o orçamento ou o teto de páginas, provavelmente sem
    alcançar o período pedido, e devolve vazio.

    Essa é a parte perigosa: vazio se lê como "não existe nada no período"
    quando o correto é "a varredura não chegou ao período".
    """
    return (
        f"ATENÇÃO — ordenacao='data' combinada com janelas_meses={janelas_meses} "
        "percorre o índice a partir dos registros de atualização MAIS ANTIGA, "
        "que estão quase todos fora da janela: a varredura termina no orçamento "
        "de tempo ou no teto de páginas, provavelmente antes de alcançar o "
        "período pedido. Um resultado vazio aqui indica que a varredura NÃO "
        "CHEGOU ao período — NÃO que o período esteja vazio. Para janelas "
        "recentes, use ordenacao='-data' (padrão)."
    )


def aviso_orcamento(orcamento_segundos: float | None) -> str:
    """Texto padrão de aviso quando a varredura para por orçamento de tempo."""
    return (
        f"a varredura interna do índice parou ao atingir o orçamento de tempo de "
        f"{orcamento_segundos:.0f}s por chamada (RADARDEPRECOS_TOOL_BUDGET_SECONDS) — "
        "os resultados retornados são parciais; refine termo_busca/filtros para "
        "reduzir o universo da busca, ou aumente o orçamento se o cliente MCP "
        "tolerar respostas mais lentas"
    )
