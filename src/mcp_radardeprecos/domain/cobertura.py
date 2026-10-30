"""Contrato único de cobertura de uma consulta externa.

Por que existe
--------------
A informação de completude sempre esteve no projeto, mas com quatro nomes
diferentes — ``total_registros_confiavel``, ``completude_verificavel``,
``parcial``, ``confiavel_para_calculo`` — e boa parte apenas em texto livre
dentro de ``avisos``. Um humano lendo a resposta se vira; um programa que
consome o MCP, não. Para pesquisa de preços isso é decisivo, porque as
perguntas que o resultado precisa responder são categóricas:

- a fonte não tem o dado, ou a nossa varredura não chegou até ele?
- este total é o universo, ou o que coube no orçamento de execução?
- o vazio veio de "não existe" ou de "a fonte recusou/caiu"?

Quatro estados, não dois booleanos
----------------------------------
A proposta original pedia ``exaustiva`` e ``parcial`` como dois campos. São
redundantes — e, pior, podem divergir e produzir um estado impossível. Além
disso dois booleanos não comportam o caso que mais aparece na prática: **não
se sabe**. É exatamente o que ``total_registros_confiavel=False`` já dizia em
``consultar_contratos_orgao_pncp`` quando a fonte não informou o total.

- ``EXAUSTIVA``     — o universo foi percorrido. Pode afirmar inexistência.
- ``PARCIAL``       — parou antes do fim, e sabe-se onde parou.
- ``INDETERMINADA`` — não há como saber se percorreu tudo (a fonte não
  informou total, ou o total não é confiável).
- ``VAZIA``         — a fonte respondeu, sem registros. Distinto de PARCIAL
  com zero resultados, que não autoriza a mesma conclusão.

``motivo`` é enumerado de propósito
-----------------------------------
Texto livre em ``motivo`` recriaria o problema que este módulo resolve. Os
motivos são poucos e estáveis, e cada um leva a uma ação diferente de quem
consome: ``LIMITE_DE_VARREDURA`` pede aumentar o limite; ``RATE_LIMIT`` pede
esperar e repetir; ``ERRO_DA_FONTE`` pede tentar mais tarde; ``SEM_CONTEUDO``
não pede nada, é resposta legítima.
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class StatusCobertura(str, Enum):
    """Herda de ``str`` para serializar como texto no JSON do MCP."""

    EXAUSTIVA = "exaustiva"
    PARCIAL = "parcial"
    INDETERMINADA = "indeterminada"
    VAZIA = "vazia"


class MotivoInterrupcao(str, Enum):
    LIMITE_DE_VARREDURA = "limite_de_varredura"
    ORCAMENTO_EXECUCAO = "orcamento_execucao"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    ERRO_DA_FONTE = "erro_da_fonte"
    SEM_CONTEUDO = "sem_conteudo"
    TOTAL_NAO_INFORMADO = "total_nao_informado"


#: Texto anexado a ``avisos`` quando a cobertura NÃO é exaustiva. Existe
#: porque o campo estruturado serve ao programa e este texto serve à pessoa
#: que lê a resposta — e é a pessoa que assina a pesquisa de preços.
_AVISO_POR_STATUS = {
    StatusCobertura.PARCIAL: (
        "RESULTADO PARCIAL: a consulta NÃO examinou todo o universo. Não use "
        "para afirmar inexistência, quantidade total ou participação de "
        "mercado sem complementar a pesquisa."
    ),
    StatusCobertura.INDETERMINADA: (
        "COBERTURA INDETERMINADA: não há como saber se a consulta percorreu "
        "todo o universo, porque a fonte não informou o total. O resultado "
        "pode estar completo — ou não, e não é possível distinguir."
    ),
}


def montar(
    *,
    fonte: str,
    status: StatusCobertura,
    registros_retornados: int,
    registros_examinados: int | None = None,
    total_no_universo: int | None = None,
    paginas_lidas: int | None = None,
    motivo: MotivoInterrupcao | None = None,
    erros_externos: list[str] | None = None,
    detalhes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Monta o bloco ``cobertura`` de uma resposta de tool.

    Args:
        fonte: Nome da origem consultada (``"PNCP"``, ``"Compras.gov.br"``).
        status: Um de :class:`StatusCobertura`.
        registros_retornados: Quantos vieram na resposta (após ``limite``).
        registros_examinados: Quantos foram lidos da fonte antes de filtrar.
        total_no_universo: Total declarado pela fonte, se houver. ``None``
            quando a fonte não informa — é o que leva a ``INDETERMINADA``.
        paginas_lidas: Páginas efetivamente percorridas.
        motivo: Obrigatório quando o status não é ``EXAUSTIVA``; ignorado
            (forçado a ``None``) quando é.
        erros_externos: Mensagens de falha da fonte, uma por ocorrência.
        detalhes: Campos específicos da tool (janelas com erro, períodos não
            consultados). Fica aninhado para não poluir o contrato comum.

    Returns:
        Dicionário pronto para entrar na resposta, com
        ``percentual_cobertura`` calculado quando os dois lados existem.
    """
    if status is StatusCobertura.EXAUSTIVA:
        motivo = None

    percentual: float | None = None
    if total_no_universo and registros_examinados is not None:
        # Arredondado para 2 casas: a precisão aqui é ilustrativa, e um
        # número com 12 decimais sugeriria uma exatidão que a contagem
        # (que muda enquanto se varre) não tem.
        percentual = round(100 * registros_examinados / total_no_universo, 2)

    bloco: dict[str, Any] = {
        "status": status.value,
        "fonte": fonte,
        "registros_retornados": registros_retornados,
        "registros_examinados": registros_examinados,
        "total_no_universo": total_no_universo,
        "percentual_cobertura": percentual,
        "paginas_lidas": paginas_lidas,
        "motivo_interrupcao": motivo.value if motivo else None,
        "erros_externos": list(erros_externos or []),
        # Redundante com `status`, e de propósito: é o teste que quem consome
        # vai escrever de qualquer jeito, e melhor que ele leia um campo
        # nosso do que reimplemente a regra e erre no `INDETERMINADA`.
        "exaustiva": status is StatusCobertura.EXAUSTIVA,
        "pode_afirmar_inexistencia": status
        in (StatusCobertura.EXAUSTIVA, StatusCobertura.VAZIA),
    }
    if detalhes:
        bloco["detalhes"] = detalhes
    return bloco


def aviso(cobertura: dict[str, Any]) -> str | None:
    """Texto para ``avisos`` correspondente ao status, ou ``None``.

    Mantém a redação num só lugar: sete tools repetindo a mesma advertência
    com palavras diferentes é como se chega a quatro nomes para a mesma
    coisa.
    """
    try:
        status = StatusCobertura(cobertura.get("status"))
    except ValueError:
        return None
    texto = _AVISO_POR_STATUS.get(status)
    if texto is None:
        return None
    total = cobertura.get("total_no_universo")
    examinados = cobertura.get("registros_examinados")
    if total and examinados is not None:
        texto = (
            f"{texto} Examinados {examinados:,} de {total:,} "
            f"({cobertura.get('percentual_cobertura')}%)."
        ).replace(",", ".")
    return texto
