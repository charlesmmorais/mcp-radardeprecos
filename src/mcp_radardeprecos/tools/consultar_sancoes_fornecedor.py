"""Tool MCP: due diligence de fornecedor — sanções/idoneidade (consulta consolidada do TCU)."""
from __future__ import annotations

from typing import Any

from ..clients import tcu_client
from ..logging_utils import get_logger
from ..utils.documentos import aviso_cnpj_alfanumerico, validar_cnpj

logger = get_logger(__name__)

#: Valor de ``situacao`` (por fonte) que significa "sem apontamento".
_NADA_CONSTA = "NADA_CONSTA"

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


def _normalizar_certidoes(certidoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Achata cada certidão do TCU nos campos que interessam à decisão."""
    itens: list[dict[str, Any]] = []
    for c in certidoes or []:
        if not isinstance(c, dict):
            continue
        situacao = c.get("situacao")
        itens.append(
            {
                "fonte": c.get("tipo"),
                "descricao": c.get("descricao"),
                "orgao_emissor": c.get("emissor"),
                "situacao": situacao,
                "tem_apontamento": situacao is not None and situacao != _NADA_CONSTA,
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
        "NADA_CONSTA"), ``resumo`` (contagem de fontes com/sem apontamento),
        ``fontes`` (lista normalizada, uma entrada por base com ``fonte``,
        ``orgao_emissor``, ``situacao``, ``tem_apontamento``, ``observacao``,
        ``link_consulta_manual``), ``data_hora_consulta`` e ``aviso``
        (escopo — sempre presente; reforçado quando há apontamento).

    Raises:
        ValueError: se ``cnpj`` não tiver 14 posições após remover pontuação.
        UpstreamError: se a consulta ao TCU falhar ou o CNPJ não retornar
            dados (inexistente/inválido, ou serviço indisponível).
    """
    cnpj_limpo = validar_cnpj(cnpj, campo="cnpj")
    aviso_alfanumerico = aviso_cnpj_alfanumerico(cnpj_limpo)

    logger.info("consultar_sancoes_fornecedor cnpj=%s", cnpj_limpo)

    dados = await tcu_client.consultar_certidoes_pj(cnpj_limpo)

    fontes = _normalizar_certidoes(dados.get("certidoes") or [])
    com_apontamento = [f for f in fontes if f["tem_apontamento"]]
    tem_apontamento = bool(com_apontamento)

    # A ordem importa: o aviso de apontamento vem primeiro porque é o que
    # muda a decisão. O de CNPJ alfanumérico vai por último, e é acrescentado
    # em vez de substituir — a versão anterior deste trecho reatribuía
    # ``aviso`` no ramo de apontamento, o que apagaria qualquer aviso já
    # acumulado.
    partes = [_AVISO_APONTAMENTO] if tem_apontamento else []
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
        "tem_apontamento": tem_apontamento,
        "resumo": {
            "total_fontes": len(fontes),
            "com_apontamento": len(com_apontamento),
            "sem_apontamento": len(fontes) - len(com_apontamento),
            "fontes_com_apontamento": [f["fonte"] for f in com_apontamento],
        },
        "fontes": fontes,
        "data_hora_consulta": (
            fontes[0]["data_hora_emissao"] if fontes else None
        ),
        "aviso": aviso,
    }
