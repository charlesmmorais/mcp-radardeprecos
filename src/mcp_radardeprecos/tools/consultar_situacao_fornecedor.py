"""Tool MCP: due diligence de fornecedor — situação de habilitação no SICAF."""
from __future__ import annotations

from typing import Any

from ..clients import compras_client
from ..logging_utils import get_logger
from ..utils.documentos import (
    aviso_cnpj_alfanumerico,
    limpar_cnpj,
    validar_cnpj,
    validar_cpf,
)

logger = get_logger(__name__)

_AVISO_ESCOPO = (
    "Esta consulta reflete apenas o cadastro/habilitação no SICAF "
    "(Compras.gov.br) — se o fornecedor está apto a licitar/contratar. "
    "NÃO é uma consulta de sanções (CEIS/CNEP/CNIA) nem de idoneidade: um "
    "fornecedor pode aparecer habilitado aqui e ainda assim ter impedimento "
    "registrado em outra base. Para verificação de sanções/idoneidade, use "
    "consultar_sancoes_fornecedor (consulta consolidada do TCU: TCU "
    "Inidôneos, CNJ CNIA, CEIS e CNEP numa única chamada)."
)


def _limpar_documento(valor: str) -> str:
    """Remove pontuação de um CNPJ — preserva letras (CNPJ alfanumérico).

    Mantido como indireção fina para não espalhar o import pelo módulo. CPF
    tem limpeza própria (:func:`limpar_cpf`), porque continua numérico e
    tratá-los igual foi o que escondeu o defeito do CNPJ alfanumérico.
    """
    return limpar_cnpj(valor)


def _montar_resultado(
    *,
    documento_tipo: str,
    documento: str,
    registro: dict[str, Any] | None,
    situacao: str,
    aviso_extra: str | None = None,
) -> dict[str, Any]:
    """Monta o envelope de resposta.

    ``aviso_extra`` existe para o caso do CNPJ alfanumérico, e é anexado
    inclusive — sobretudo — quando ``situacao`` é ``NAO_ENCONTRADO``. É
    justamente aí que ele importa: sem o aviso, "não encontrado" por recusa
    da fonte ao formato novo seria indistinguível de "fornecedor não existe
    no SICAF".
    """
    aviso = f"{_AVISO_ESCOPO} {aviso_extra}" if aviso_extra else _AVISO_ESCOPO
    resultado: dict[str, Any] = {
        documento_tipo: documento,
        "situacao": situacao,
        "habilitado_a_licitar": None,
        "razao_social": None,
        "natureza_juridica": None,
        "porte_empresa": None,
        "cnae": None,
        "municipio": None,
        "uf": None,
        "aviso": aviso,
    }
    if registro:
        resultado["habilitado_a_licitar"] = registro.get("habilitadoLicitar")
        resultado["razao_social"] = registro.get("nomeRazaoSocialFornecedor")
        resultado["natureza_juridica"] = registro.get("naturezaJuridicaNome")
        resultado["porte_empresa"] = registro.get("porteEmpresaNome")
        resultado["cnae"] = {
            "codigo": registro.get("codigoCnae"),
            "descricao": registro.get("nomeCnae"),
        }
        resultado["municipio"] = registro.get("nomeMunicipio")
        resultado["uf"] = registro.get("ufSigla")
    return resultado


async def consultar_situacao_fornecedor(
    cnpj: str | None = None,
    cpf: str | None = None,
) -> dict[str, Any]:
    """Consulta a situação de um fornecedor no SICAF (Compras.gov.br) — due diligence.

    Complementa ``consultar_cnpj`` (cadastro na Receita Federal): traz o
    campo ``habilitado_a_licitar`` — que só existe no SICAF, não no cadastro
    da Receita Federal — útil para checar, antes de aceitar uma cotação
    direta ou formalizar uma contratação, se o fornecedor está apto a
    licitar/contratar com a administração pública.

    A API do SICAF exige informar se busca fornecedor **ativo** ou
    **inativo** (parâmetro obrigatório) — esta tool tenta primeiro
    ``ativo=True`` e, se não encontrar nada, tenta ``ativo=False``
    automaticamente, para diferenciar um cadastro **inativo** (existe, mas
    não está ativo no momento) de um CNPJ/CPF **nunca cadastrado** no
    SICAF (o que não significa necessariamente irregularidade — muitos
    fornecedores válidos nunca participaram de uma licitação federal).

    **Atenção — escopo limitado:** esta consulta reflete só a
    habilitação/cadastro no SICAF, **não** é uma consulta de sanções
    (CEIS/CNEP) — ver o aviso incluído em todo retorno.

    Args:
        cnpj: CNPJ do fornecedor pessoa jurídica, em qualquer formato
            (pontuação é removida automaticamente). Informe **um** de
            ``cnpj``/``cpf``.
        cpf: CPF do fornecedor pessoa física, em qualquer formato. Informe
            **um** de ``cnpj``/``cpf``.

    Returns:
        Dicionário com ``cnpj`` ou ``cpf`` (o documento informado, limpo),
        ``situacao`` (``"ATIVO"``, ``"INATIVO"`` ou ``"NAO_ENCONTRADO"``),
        ``habilitado_a_licitar`` (bool ou ``None`` se não encontrado),
        ``razao_social``, ``natureza_juridica``, ``porte_empresa``,
        ``cnae`` (``codigo``/``descricao``), ``municipio``, ``uf`` e
        ``aviso`` (escopo desta consulta — sempre presente).

    Raises:
        ValueError: se nenhum ou os dois (``cnpj`` e ``cpf``) forem
            informados, ou se o documento informado tiver tamanho inválido
            após a limpeza (14 posições para CNPJ — podendo conter letras,
            no formato alfanumérico vigente desde julho/2026 — e 11 dígitos
            numéricos para CPF).
    """
    if bool(cnpj) == bool(cpf):
        raise ValueError("Informe exatamente um de cnpj/cpf (não os dois, não nenhum).")

    if cnpj:
        documento_tipo = "cnpj"
        documento = validar_cnpj(cnpj, campo="cnpj")
        aviso_alfanumerico = aviso_cnpj_alfanumerico(documento)
        kwargs = {"cnpj": documento}
    else:
        documento_tipo = "cpf"
        documento = validar_cpf(cpf, campo="cpf")
        aviso_alfanumerico = None
        kwargs = {"cpf": documento}

    logger.info("consultar_situacao_fornecedor %s=%s", documento_tipo, documento)

    resposta_ativo = await compras_client.consultar_fornecedor(ativo=True, **kwargs)
    registros = (resposta_ativo or {}).get("resultado", []) or []
    if registros:
        return _montar_resultado(
            documento_tipo=documento_tipo,
            documento=documento,
            registro=registros[0],
            situacao="ATIVO",
            aviso_extra=aviso_alfanumerico,
        )

    resposta_inativo = await compras_client.consultar_fornecedor(ativo=False, **kwargs)
    registros_inativo = (resposta_inativo or {}).get("resultado", []) or []
    if registros_inativo:
        return _montar_resultado(
            documento_tipo=documento_tipo,
            documento=documento,
            registro=registros_inativo[0],
            situacao="INATIVO",
            aviso_extra=aviso_alfanumerico,
        )

    return _montar_resultado(
        documento_tipo=documento_tipo,
        documento=documento,
        registro=None,
        situacao="NAO_ENCONTRADO",
        aviso_extra=aviso_alfanumerico,
    )
