"""Tool MCP: enriquece um CNPJ com dados de cadastro da Receita Federal."""
from __future__ import annotations

from typing import Any

from ..clients import cnpj_client
from ..logging_utils import get_logger
from ..utils.documentos import aviso_cnpj_alfanumerico, validar_cnpj

logger = get_logger(__name__)

_AVISO_QSA_VAZIO = (
    "Quadro societário (socios) veio vazio na resposta do provedor — pode "
    "significar que a empresa realmente não tem sócios cadastrados nessa "
    "base (comum em órgãos públicos e algumas entidades) ou que o provedor "
    "gratuito usado não populou esse campo para este CNPJ. Não interprete "
    "lista vazia como 'sem sócios' sem checar outra fonte se isso for "
    "crítico para a decisão."
)


def _montar_endereco(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "logradouro": dados.get("logradouro"),
        "numero": dados.get("numero"),
        "complemento": dados.get("complemento"),
        "bairro": dados.get("bairro"),
        "municipio": dados.get("municipio"),
        "uf": dados.get("uf"),
        "cep": dados.get("cep"),
    }


def _montar_socios(dados: dict[str, Any]) -> list[dict[str, Any]]:
    """Normaliza o QSA (quadro de sócios) de forma defensiva.

    Os nomes de campo de cada sócio variam entre BrasilAPI e MinhaReceita
    (ex.: ``nome_socio`` vs. ``nome``, ``qualificacao_socio`` vs.
    ``qual``) — usa múltiplas chaves alternativas por campo para tolerar
    as duas formas sem quebrar caso um provedor mude o schema.
    """
    socios_brutos = dados.get("qsa") or []
    socios: list[dict[str, Any]] = []
    for socio in socios_brutos:
        if not isinstance(socio, dict):
            continue
        socios.append(
            {
                "nome": socio.get("nome_socio") or socio.get("nome"),
                "qualificacao": socio.get("qualificacao_socio") or socio.get("qual"),
                "data_entrada_sociedade": socio.get("data_entrada_sociedade"),
                "cnpj_cpf": socio.get("cnpj_cpf_do_socio") or socio.get("cnpj_cpf"),
            }
        )
    return socios


async def consultar_cnpj(cnpj: str) -> dict[str, Any]:
    """Consulta o cadastro de um CNPJ na Receita Federal (situação, sócios, endereço).

    Útil para checar antes de formalizar uma cotação direta com um
    fornecedor — o guia de pesquisa de preços (IN SEGES/ME 65/2021) recomenda
    confirmar que o CNPJ está com situação cadastral ATIVA e, se relevante,
    olhar o quadro societário (QSA) — checagem que nenhuma outra tool deste
    projeto cobre hoje.

    **Não é uma fonte de preço de referência**: só traz dados cadastrais
    (nome, situação, endereço, sócios, CNAE), nada relacionado a valores
    de contratações — para preços, use ``buscar_precos_praticados_compras``
    ou ``calcular_preco_referencia``.

    Fonte: `BrasilAPI <https://brasilapi.com.br/api/cnpj/v1/{cnpj}>`_
    (tentada primeiro), com fallback automático para
    `MinhaReceita <https://minhareceita.org/{cnpj}>`_ se a BrasilAPI falhar.
    As duas são agregadoras gratuitas sobre o Cadastro Nacional da Pessoa
    Jurídica (dados abertos da Receita Federal), sem garantia de SLA — o
    campo ``fonte`` no retorno indica qual das duas respondeu. Nomes de
    campo podem variar sutilmente entre provedores em casos de borda; os
    campos abaixo são uma normalização best-effort.

    Args:
        cnpj: CNPJ em qualquer formato (com ou sem pontuação) — pontuação é
            removida automaticamente. Deve ter 14 posições após a limpeza.
            Aceita o formato alfanumérico vigente desde julho/2026 (letras
            nas 12 primeiras posições); nesse caso o retorno traz um
            ``aviso_cnpj`` sobre comportamento não verificado da fonte.

    Returns:
        Dicionário com ``cnpj``, ``razao_social``, ``nome_fantasia``,
        ``situacao_cadastral`` (descrição, ex. "ATIVA"),
        ``codigo_situacao_cadastral``, ``data_situacao_cadastral``,
        ``motivo_situacao_cadastral``, ``natureza_juridica``, ``porte``,
        ``capital_social``, ``data_inicio_atividade``, ``cnae_principal``
        (``codigo``/``descricao``), ``cnaes_secundarios``, ``endereco``,
        ``telefone``, ``email``, ``optante_simples``, ``optante_mei``,
        ``socios`` (QSA normalizado), ``fonte`` (``"brasilapi"`` ou
        ``"minhareceita"``) e, se o QSA vier vazio, um ``aviso`` explicando
        que isso não deve ser lido automaticamente como "sem sócios".

    Raises:
        ValueError: se ``cnpj`` não tiver 14 posições após remover pontuação.
    """
    cnpj_limpo = validar_cnpj(cnpj, campo="cnpj")
    aviso_alfanumerico = aviso_cnpj_alfanumerico(cnpj_limpo)

    logger.info("consultar_cnpj cnpj=%s", cnpj_limpo)

    dados = await cnpj_client.consultar_cnpj(cnpj_limpo)

    cnae_principal = {
        "codigo": dados.get("cnae_fiscal"),
        "descricao": dados.get("cnae_fiscal_descricao"),
    }
    telefone_ddd = dados.get("ddd_telefone_1") or None
    socios = _montar_socios(dados)

    resultado: dict[str, Any] = {
        "cnpj": dados.get("cnpj") or cnpj_limpo,
        "razao_social": dados.get("razao_social"),
        "nome_fantasia": dados.get("nome_fantasia") or None,
        "situacao_cadastral": dados.get("descricao_situacao_cadastral"),
        "codigo_situacao_cadastral": dados.get("situacao_cadastral"),
        "data_situacao_cadastral": dados.get("data_situacao_cadastral"),
        "motivo_situacao_cadastral": dados.get("descricao_motivo_situacao_cadastral"),
        "natureza_juridica": dados.get("natureza_juridica"),
        "porte": dados.get("porte"),
        "capital_social": dados.get("capital_social"),
        "data_inicio_atividade": dados.get("data_inicio_atividade"),
        "cnae_principal": cnae_principal,
        "cnaes_secundarios": dados.get("cnaes_secundarios") or [],
        "endereco": _montar_endereco(dados),
        "telefone": telefone_ddd,
        "email": dados.get("email") or None,
        "optante_simples": dados.get("opcao_pelo_simples"),
        "optante_mei": dados.get("opcao_pelo_mei"),
        "socios": socios,
        "fonte": dados.get("_provider"),
    }
    if not socios:
        resultado["aviso"] = _AVISO_QSA_VAZIO
    if aviso_alfanumerico:
        resultado["aviso_cnpj"] = aviso_alfanumerico
    return resultado
