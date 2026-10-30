"""Tool MCP: contratações do PNCP com propostas ABERTAS agora.

``/api/consulta/v1/contratacoes/proposta``
responde "o que está aberto para propor até uma data", complementando as
demais tools deste servidor (que buscam o que **já foi** publicado/
homologado) com o que ainda está em fase de recebimento de propostas —
oportunidades correntes, não histórico.

**Os valores devolvidos são ESTIMADOS, não referência de preço válida** —
mesma distinção já documentada em ``clients/pncp_client.py`` (nota crítica
"estimado vs. homologado"): uma contratação com proposta aberta ainda não
tem vencedor, então só existe o valor estimado pelo órgão antes da disputa.
Um aviso fixo lembra disso em toda chamada.
"""
from __future__ import annotations

from typing import Any

from ..clients import pncp_client
from ..logging_utils import get_logger
from ..utils.datas import janela_dias_a_frente
from ..utils.paginacao import extrair_paginacao

logger = get_logger(__name__)

_LIMITE_MAXIMO = 50  # teto real da API (ver clients.pncp_client.consultar_contratacoes_proposta_aberta)

_AVISO_VALOR_ESTIMADO = (
    "Os valores retornados (valor_total_estimado) são ESTIMADOS pelo órgão antes da "
    "disputa — a contratação ainda está com propostas abertas, não tem vencedor. NÃO "
    "use esses valores como referência de pesquisa de preços (só valores homologados "
    "valem como referência — ver buscar_contratacoes_pncp)."
)


def _formatar_proposta(bruto: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    orgao_entidade = bruto.get("orgaoEntidade") or {}
    unidade_orgao = bruto.get("unidadeOrgao") or {}
    numero_controle = bruto.get("numeroControlePNCP")
    link_pagina_pncp = None
    parsed = pncp_client.parse_numero_controle_pncp(numero_controle or "")
    if parsed:
        cnpj, ano, sequencial = parsed
        link_pagina_pncp = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"
    formatado = {
        "numero_controle_pncp": numero_controle,
        "objeto": bruto.get("objetoCompra"),
        "orgao": orgao_entidade.get("razaoSocial"),
        "cnpj_orgao": orgao_entidade.get("cnpj"),
        "unidade": unidade_orgao.get("nomeUnidade"),
        "uf": unidade_orgao.get("ufSigla"),
        "municipio": unidade_orgao.get("municipioNome"),
        "modalidade": bruto.get("modalidadeNome"),
        "data_abertura_proposta": bruto.get("dataAberturaProposta"),
        "data_encerramento_proposta": bruto.get("dataEncerramentoProposta"),
        "valor_total_estimado": bruto.get("valorTotalEstimado"),
        "link_pagina_pncp": link_pagina_pncp,
    }
    if incluir_bruto:
        formatado["dados_originais"] = bruto
    return formatado


async def buscar_propostas_abertas(
    dias_a_frente: int = 30,
    uf: str | None = None,
    modalidade: int | None = None,
    cnpj_orgao: str | None = None,
    pagina: int = 1,
    limite: int = 50,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Busca contratações do PNCP com propostas ABERTAS agora, até `dias_a_frente` dias à frente.

    Fonte: API de Consulta oficial do PNCP (``/v1/contratacoes/proposta``; ver
    ``clients.pncp_client.consultar_contratacoes_proposta_aberta``). Ao
    contrário de ``buscar_pncp_texto``/``buscar_contratacoes_pncp`` (que
    encontram o que já foi publicado ou já tem resultado), esta tool foca no
    que ainda está recebendo propostas — útil para monitorar oportunidades
    correntes, não para pesquisa de preços histórica.

    Args:
        dias_a_frente: Horizonte em dias, a partir de hoje, até quando a
            proposta deve estar aberta (``dataFinal`` do filtro — padrão 30).
        uf: Sigla da UF (ex.: "SP"), opcional.
        modalidade: Código de modalidade de contratação do PNCP (ver
            ``consultar_tabelas_dominio_pncp("modalidade_contratacao")``),
            opcional.
        cnpj_orgao: CNPJ do órgão (14 posições), opcional.
        pagina: Página dos resultados (padrão 1).
        limite: Número máximo de propostas a devolver nesta página (padrão
            50, **máximo 50** — teto real da API, menor que os 500 de outros
            endpoints da API de Consulta).
        incluir_bruto: Se True, cada proposta também traz ``dados_originais``
            com os campos exatos e completos da API, sem tradução (padrão
            False — não incluído por padrão para não duplicar o payload à
            toa).

    Returns:
        Dicionário com ``periodo`` (``dias_a_frente``/``data_final`` em
        ``AAAAMMDD``), ``quantidade_retornada``, ``total_no_periodo``,
        ``propostas`` (cada uma com ``link_pagina_pncp`` já montado a partir
        de ``numero_controle_pncp``) e ``avisos`` — sempre incluindo o aviso
        fixo de que os valores são estimados (ver docstring do módulo).
    """
    dias_a_frente = max(1, dias_a_frente)
    limite = max(1, min(limite, _LIMITE_MAXIMO))
    pagina = max(1, pagina)

    _, data_final = janela_dias_a_frente(dias_a_frente)

    logger.info(
        "buscar_propostas_abertas dias_a_frente=%s data_final=%s uf=%s modalidade=%s "
        "cnpj_orgao=%s pagina=%s limite=%s",
        dias_a_frente, data_final, uf, modalidade, cnpj_orgao, pagina, limite,
    )

    resposta = await pncp_client.consultar_contratacoes_proposta_aberta(
        data_final=data_final,
        codigo_modalidade_contratacao=modalidade,
        uf=uf,
        cnpj=cnpj_orgao,
        pagina=pagina,
        tamanho_pagina=limite,
    )
    brutos = (resposta or {}).get("data", []) or []
    total_no_periodo = (resposta or {}).get("totalRegistros", 0) or 0

    propostas = [_formatar_proposta(p, incluir_bruto) for p in brutos[:limite]]

    avisos: list[str] = [_AVISO_VALOR_ESTIMADO]
    if total_no_periodo > len(propostas):
        avisos.append(
            f"O PNCP encontrou {total_no_periodo} contratação(ões) com proposta aberta no "
            f"período/filtros informados, mas só {len(propostas)} foram retornadas nesta "
            f"página (limite={limite}). Use pagina para avançar, ou restrinja por "
            "uf/modalidade/cnpj_orgao."
        )
    if not propostas:
        avisos.append(
            f"Nenhuma contratação com proposta aberta até {data_final} encontrada com os "
            "filtros informados."
        )

    # campos padronizados, aditivos —
    # total_no_periodo acima é mantido (nome antigo).
    return {
        "periodo": {"dias_a_frente": dias_a_frente, "data_final": data_final},
        "quantidade_retornada": len(propostas),
        "total_no_periodo": total_no_periodo,
        "propostas": propostas,
        "avisos": avisos,
        **extrair_paginacao(resposta),
    }
