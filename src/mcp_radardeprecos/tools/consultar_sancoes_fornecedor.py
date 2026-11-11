"""Tool MCP: due diligence de fornecedor — sanções/idoneidade (consulta consolidada do TCU)."""
from __future__ import annotations

from typing import Any

from ..clients import tcu_client
from ..clients.base import BloqueioFirewallError, UpstreamError
from ..logging_utils import get_logger
from ..utils.documentos import aviso_cnpj_alfanumerico, validar_cnpj

logger = get_logger(__name__)

#: Valor de ``situacao`` (por fonte) que significa "sem apontamento".
_NADA_CONSTA = "NADA_CONSTA"

#: Trechos que indicam base que não respondeu. O valor exato que o TCU usa
#: para "Sistema indisponível" (visto no PDF da consulta da Oracle,
#: 11/11/2026, para o CNJ) não foi medido no JSON — a API estava bloqueada
#: pelo firewall. Por isso a busca é por trecho, na situação e na observação.
_MARCAS_NAO_VERIFICADA = ("INDISPON", "ERRO", "FALHA", "TIMEOUT", "NAO_CONSULT", "NÃO CONSULT")

_LINK_CONSULTA_MANUAL = "https://certidoes-apf.apps.tcu.gov.br/"

_AVISO_PARCIAL = (
    "CONSULTA PARCIAL: {fontes} não respondeu(ram). Para essas bases não há "
    "resultado — isso NÃO equivale a 'nada consta'. Repita a consulta mais "
    "tarde ou confira no link_consulta_manual de cada uma antes de decidir."
)

_AVISO_ESCOPO = (
    "Cobertura desta consulta (bases federais consolidadas pelo TCU numa "
    "única chamada): TCU Licitantes Inidôneos, CNJ CNIA (improbidade), e "
    "CEIS/CNEP do Portal da Transparência. NÃO cobre: cadastros estaduais/"
    "municipais de inidôneos, suspensões pontuais de um órgão específico, "
    "nem a habilitação no SICAF (para isso use consultar_situacao_fornecedor). "
    "'Nada consta' aqui significa apenas ausência de registro nessas quatro "
    "bases federais no momento da consulta — não é atestado de idoneidade "
    "plena. Cada fonte traz um linkConsultaManual para conferência oficial."
)

_AVISO_APONTAMENTO = (
    "ATENÇÃO: há apontamento em pelo menos uma base. Isto NÃO decide "
    "automaticamente a inabilitação do fornecedor — confirme na fonte "
    "oficial (linkConsultaManual de cada certidão), verifique a vigência da "
    "sanção e o alcance (a que esfera/órgão se aplica) antes de qualquer "
    "decisão de contratação."
)


def _classificar(situacao: Any, observacao: Any) -> str:
    """``nada_consta``, ``apontamento`` ou ``nao_verificada`` (a base não respondeu).

    Antes, tudo que não fosse ``NADA_CONSTA`` contava como apontamento — e uma
    base fora do ar aparecia como sanção encontrada.
    """
    if situacao == _NADA_CONSTA:
        return "nada_consta"
    texto = f"{situacao or ''} {observacao or ''}".upper()
    if not situacao or any(marca in texto for marca in _MARCAS_NAO_VERIFICADA):
        return "nao_verificada"
    return "apontamento"


def _normalizar_certidoes(certidoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Achata cada certidão do TCU nos campos que interessam à decisão."""
    itens: list[dict[str, Any]] = []
    for c in certidoes or []:
        if not isinstance(c, dict):
            continue
        situacao = c.get("situacao")
        resultado = _classificar(situacao, c.get("observacao"))
        itens.append(
            {
                "fonte": c.get("tipo"),
                "descricao": c.get("descricao"),
                "orgao_emissor": c.get("emissor"),
                "situacao": situacao,
                "resultado": resultado,
                "tem_apontamento": resultado == "apontamento",
                "observacao": c.get("observacao"),
                "data_hora_emissao": c.get("dataHoraEmissao"),
                "link_consulta_manual": c.get("linkConsultaManual"),
            }
        )
    return itens


async def consultar_sancoes_fornecedor(cnpj: str) -> dict[str, Any]:
    """Consulta sanções/idoneidade de um fornecedor (PJ) em bases federais consolidadas pelo TCU.

    Terceira e última peça de due diligence de fornecedor deste projeto,
    complementar às outras duas: ``consultar_cnpj`` traz o cadastro na
    Receita Federal (situação cadastral, sócios) e
    ``consultar_situacao_fornecedor`` traz a habilitação no SICAF; **esta**
    responde a pergunta que faltava — *o fornecedor está impedido de
    contratar por alguma sanção/idoneidade?* O guia de pesquisa de preços
    (IN SEGES/ME 65/2021) e a boa prática de contratação recomendam essa
    checagem antes de formalizar uma cotação direta ou adjudicar.

    O grande diferencial da fonte: **uma única chamada agrega quatro bases
    de três órgãos** — TCU (Licitantes Inidôneos), CNJ (CNIA — improbidade
    administrativa e inelegibilidade) e Portal da Transparência (CEIS e
    CNEP). Em particular, **CEIS e CNEP são consultados sem exigir a chave
    de API do Portal da Transparência** — o TCU faz essa ponte
    internamente.

    Fonte: `Consulta consolidada de PJ do TCU
    <https://certidoes-apf.apps.tcu.gov.br/>`_ (dados abertos, pública, sem
    credencial — mesmo perfil somente-leitura das demais fontes do projeto).
    Cada chamada dispara consultas ao vivo às quatro bases; o resultado é
    cacheado por 30 minutos.

    **Escopo — leia o campo ``aviso``:** cobre só as quatro bases *federais*
    listadas. Não cobre cadastros estaduais/municipais nem suspensões
    pontuais de um órgão. "Nada consta" é ausência de registro nessas bases
    no momento, não um atestado de idoneidade plena — sempre confira no
    ``link_consulta_manual`` de cada fonte antes de decidir.

    Args:
        cnpj: CNPJ do fornecedor em qualquer formato (pontuação é removida
            automaticamente). Deve ter 14 posições após a limpeza; aceita o
            formato alfanumérico vigente desde julho/2026. A consulta
            consolidada do TCU é para pessoa jurídica — para pessoa física,
            não há equivalente aqui.

    Returns:
        Dicionário com ``cnpj`` (limpo), ``razao_social``, ``nome_fantasia``,
        ``uf``, ``encontrado_na_base_tcu`` (bool), ``tem_apontamento`` (bool —
        ``True`` se QUALQUER das quatro fontes tiver situação diferente de
        "NADA_CONSTA" e não for falha da base), ``consulta_realizada``,
        ``consulta_completa`` (``False`` se alguma base não respondeu),
        ``resumo`` (contagens por resultado e as listas
        ``fontes_com_apontamento`` e ``fontes_nao_verificadas``), ``fontes``
        (uma entrada por base com ``fonte``, ``orgao_emissor``, ``situacao``,
        ``resultado`` — ``nada_consta``, ``apontamento`` ou
        ``nao_verificada`` —, ``tem_apontamento``, ``observacao`` e
        ``link_consulta_manual``), ``data_hora_consulta`` e ``aviso``.

        **Base que não respondeu** (ex.: "Sistema indisponível" no CNJ) tem
        ``resultado="nao_verificada"``: não é apontamento nem "nada consta", e
        o ``aviso`` diz que a consulta é parcial.

        **Consulta que não aconteceu** (firewall do TCU, timeout, erro da
        fonte): ``consulta_realizada=False``, ``tem_apontamento=None``,
        ``motivo``, ``bloqueio_firewall`` e ``link_consulta_manual`` — nunca
        leia isso como "nada consta".

    Raises:
        ValueError: se ``cnpj`` não tiver 14 posições após remover pontuação.
    """
    cnpj_limpo = validar_cnpj(cnpj, campo="cnpj")
    aviso_alfanumerico = aviso_cnpj_alfanumerico(cnpj_limpo)

    logger.info("consultar_sancoes_fornecedor cnpj=%s", cnpj_limpo)

    try:
        dados = await tcu_client.consultar_certidoes_pj(cnpj_limpo)
    except UpstreamError as erro:
        return _nao_verificado(cnpj_limpo, erro, aviso_alfanumerico)

    fontes = _normalizar_certidoes(dados.get("certidoes") or [])
    com_apontamento = [f for f in fontes if f["tem_apontamento"]]
    nao_verificadas = [f for f in fontes if f["resultado"] == "nao_verificada"]
    tem_apontamento = bool(com_apontamento)

    # A ordem importa: o aviso de apontamento vem primeiro porque é o que
    # muda a decisão. O de CNPJ alfanumérico vai por último, e é acrescentado
    # em vez de substituir — a versão anterior deste trecho reatribuía
    # ``aviso`` no ramo de apontamento, o que apagaria qualquer aviso já
    # acumulado.
    partes = [_AVISO_APONTAMENTO] if tem_apontamento else []
    if nao_verificadas:
        nomes = ", ".join(str(f["fonte"] or f["orgao_emissor"]) for f in nao_verificadas)
        partes.append(_AVISO_PARCIAL.format(fontes=nomes))
    partes.append(_AVISO_ESCOPO)
    if aviso_alfanumerico:
        partes.append(aviso_alfanumerico)
    aviso = " ".join(partes)

    return {
        "cnpj": dados.get("cnpj") or cnpj_limpo,
        "razao_social": dados.get("razaoSocial"),
        "nome_fantasia": dados.get("nomeFantasia"),
        "uf": dados.get("uf"),
        "encontrado_na_base_tcu": dados.get("seCnpjEncontradoNaBaseTcu"),
        "consulta_realizada": True,
        "consulta_completa": bool(fontes) and not nao_verificadas,
        "tem_apontamento": tem_apontamento,
        "resumo": {
            "total_fontes": len(fontes),
            "com_apontamento": len(com_apontamento),
            "nada_consta": sum(1 for f in fontes if f["resultado"] == "nada_consta"),
            "nao_verificadas": len(nao_verificadas),
            # Mantido por compatibilidade: fontes que responderam sem apontamento.
            "sem_apontamento": sum(1 for f in fontes if f["resultado"] == "nada_consta"),
            "fontes_com_apontamento": [f["fonte"] for f in com_apontamento],
            "fontes_nao_verificadas": [f["fonte"] for f in nao_verificadas],
        },
        "fontes": fontes,
        "data_hora_consulta": (
            fontes[0]["data_hora_emissao"] if fontes else None
        ),
        "aviso": aviso,
    }


def _nao_verificado(cnpj: str, erro: UpstreamError, aviso_alfanumerico: str | None) -> dict[str, Any]:
    """Resultado quando a consulta ao TCU não foi feita: nada foi verificado.

    Devolvido como resultado, e não como erro da tool, para que o motivo e o
    caminho manual cheguem ao usuário — e para que ninguém leia a falha como
    "nada consta".
    """
    bloqueio = isinstance(erro, BloqueioFirewallError)
    motivo = (
        "O firewall de aplicações do TCU recusou a consulta automatizada "
        "('Requisição rejeitada'). Não é instabilidade passageira: repetir não resolve."
        if bloqueio
        else f"A consulta ao TCU falhou: {erro}"
    )
    partes = [
        "NÃO VERIFICADO: nenhuma das quatro bases (TCU Inidôneos, CNJ CNIA, CEIS, "
        "CNEP) foi consultada. Isso não equivale a 'nada consta'. Emita a consulta "
        f"consolidada manualmente em {_LINK_CONSULTA_MANUAL} e anexe o PDF ao processo.",
        _AVISO_ESCOPO,
    ]
    if aviso_alfanumerico:
        partes.append(aviso_alfanumerico)
    return {
        "cnpj": cnpj,
        "consulta_realizada": False,
        "consulta_completa": False,
        "tem_apontamento": None,
        "motivo": motivo,
        "bloqueio_firewall": bloqueio,
        "link_consulta_manual": _LINK_CONSULTA_MANUAL,
        "fontes": [],
        "aviso": " ".join(partes),
    }
