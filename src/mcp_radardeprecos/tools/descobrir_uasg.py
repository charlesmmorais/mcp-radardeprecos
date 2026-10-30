"""Tool MCP: descobre código de UASG/órgão a partir de texto livre (nome)."""
from __future__ import annotations

from typing import Any

from ..clients import compras_client
from ..logging_utils import get_logger
from ..utils.texto_busca import normalizar_para_busca

logger = get_logger(__name__)

_TIPOS_VALIDOS = ("uasg", "orgao")


async def descobrir_uasg(
    termo_busca: str,
    tipo: str = "uasg",
    uf: str | None = None,
    limite: int = 10,
) -> dict[str, Any]:
    """Descobre o código de uma UASG ou órgão a partir do nome (texto livre).

    Nasceu de um estudo completo do spec OpenAPI do Compras.gov.br (todas as
    15 tags, ~60 endpoints, lido direto do Swagger em
    https://dadosabertos.compras.gov.br/swagger-ui/index.html): nenhum
    endpoint de UASG/órgão aceita busca textual por nome — só filtros
    exatos (``codigoUasg``, ``codigoOrgao``, CNPJ, UF, status) — confirmado
    ao vivo, mesma limitação já vista no catálogo de materiais/serviços
    (ver ``descobrir_codigo_catalogo``). Útil como pré-requisito de
    ``buscar_precos_praticados_compras``, que aceita ``codigo_uasg`` como
    filtro opcional mas não tem como descobri-lo a partir do nome do órgão.

    Faz a busca no lado do cliente (case/acento-insensível), comparando o
    termo contra os nomes cadastrados:

    - ``tipo="uasg"`` (padrão): busca sobre o nome de TODAS as UASGs ativas
      (~21.941 no Brasil todo, sem filtro de UF — a primeira chamada de uma
      sessão sem ``uf`` pode levar vários segundos, 44 páginas). Informar
      ``uf`` filtra no SERVIDOR antes de paginar (ex.: SP sozinho tem
      ~3.123 UASGs, 7 páginas) — bem mais rápido, use sempre que souber o
      estado, mesmo que aproximado. Lista cacheada por até 1 dia (por
      valor de ``uf``).
    - ``tipo="orgao"``: busca sobre o nome (e mnemônico) de TODOS os
      órgãos ativos (~11.840, 24 páginas) — **não aceita** ``uf`` (órgãos
      são entidades nacionais, sem UF própria; a UF é atributo da UASG, não
      do órgão — informar ``uf`` aqui levanta erro em vez de ser
      silenciosamente ignorado, mesma cautela já adotada neste projeto
      para outras pegadinhas de API). Lista cacheada por até 1 dia.

    Args:
        termo_busca: Texto livre com o nome (ou parte do nome) da UASG/
            órgão (ex.: "hospital universitario", "tribunal de contas").
        tipo: ``"uasg"`` (padrão) ou ``"orgao"``.
        uf: Sigla da UF (ex.: "SP") para restringir a busca — só válido
            com ``tipo="uasg"``.
        limite: Número máximo de resultados (padrão 10, máximo 50).

    Returns:
        Dicionário com ``termo_busca``, ``tipo``, ``uf``,
        ``total_correspondencias`` e ``resultados`` — lista onde cada item
        traz, para UASG: ``codigo_uasg``, ``nome_uasg``, ``uf``,
        ``municipio``, ``codigo_orgao``, ``cnpj_orgao``, ``uso_sisg``; para
        órgão: ``codigo_orgao``, ``nome_orgao``, ``cnpj_orgao``, ``poder``,
        ``esfera``, ``nome_orgao_superior``. Inclui ``aviso`` só quando não
        encontrou nenhuma correspondência.

    Raises:
        ValueError: se ``tipo`` for inválido, ``termo_busca`` vazio, ou
            ``uf`` informado junto com ``tipo="orgao"``.
    """
    if tipo not in _TIPOS_VALIDOS:
        raise ValueError(f"tipo deve ser um de {_TIPOS_VALIDOS}")
    if not termo_busca or not termo_busca.strip():
        raise ValueError("termo_busca não pode ser vazio")
    if tipo == "orgao" and uf is not None:
        raise ValueError(
            "uf não se aplica a tipo='orgao' — órgãos são entidades "
            "nacionais, sem UF própria (a UF é atributo da UASG, não do "
            "órgão). Use tipo='uasg' para filtrar por UF, ou remova uf."
        )

    limite = max(1, min(limite, 50))
    termo_norm = normalizar_para_busca(termo_busca)
    logger.info(
        "descobrir_uasg termo_busca=%s tipo=%s uf=%s limite=%s",
        termo_busca, tipo, uf, limite,
    )

    if tipo == "uasg":
        return await _descobrir_uasg(termo_norm, termo_busca, uf, limite)
    return await _descobrir_orgao(termo_norm, termo_busca, limite)


async def _descobrir_uasg(
    termo_norm: str, termo_busca: str, uf: str | None, limite: int
) -> dict[str, Any]:
    uasgs = await compras_client.listar_uasgs_ativas(sigla_uf=uf)
    correspondentes = [
        u for u in uasgs if termo_norm in normalizar_para_busca(u.get("nomeUasg", ""))
    ]
    # Nomes mais curtos tendem a ser correspondências mais específicas
    # (mesmo critério já usado em descobrir_codigo_catalogo).
    correspondentes.sort(key=lambda u: len(u.get("nomeUasg") or ""))

    resultados: list[dict[str, Any]] = [
        {
            "codigo_uasg": u.get("codigoUasg"),
            "nome_uasg": u.get("nomeUasg"),
            "uf": u.get("siglaUf"),
            "municipio": u.get("nomeMunicipioIbge"),
            "codigo_orgao": u.get("codigoOrgao"),
            "cnpj_orgao": u.get("cnpjCpfOrgao"),
            "uso_sisg": u.get("usoSisg"),
        }
        for u in correspondentes[:limite]
    ]

    resposta: dict[str, Any] = {
        "termo_busca": termo_busca,
        "tipo": "uasg",
        "uf": uf,
        "total_correspondencias": len(correspondentes),
        "resultados": resultados,
    }
    if not correspondentes:
        resposta["aviso"] = (
            "Nenhuma UASG ativa contém esse termo no nome"
            + (f" no estado {uf}" if uf else "")
            + ". Tente um termo mais genérico, sem sigla/abreviação, ou "
            "remova o filtro de uf se usado."
        )
    return resposta


async def _descobrir_orgao(termo_norm: str, termo_busca: str, limite: int) -> dict[str, Any]:
    orgaos = await compras_client.listar_orgaos_ativos()
    correspondentes = [
        o
        for o in orgaos
        if termo_norm in normalizar_para_busca(o.get("nomeOrgao", ""))
        or termo_norm in normalizar_para_busca(o.get("nomeMnemonicoOrgao", ""))
    ]
    correspondentes.sort(key=lambda o: len(o.get("nomeOrgao") or ""))

    resultados: list[dict[str, Any]] = [
        {
            "codigo_orgao": o.get("codigoOrgao"),
            "nome_orgao": o.get("nomeOrgao"),
            "cnpj_orgao": o.get("cnpjCpfOrgao"),
            "poder": o.get("poder"),
            "esfera": o.get("esfera"),
            "nome_orgao_superior": o.get("nomeOrgaoSuperior"),
        }
        for o in correspondentes[:limite]
    ]

    resposta: dict[str, Any] = {
        "termo_busca": termo_busca,
        "tipo": "orgao",
        "uf": None,
        "total_correspondencias": len(correspondentes),
        "resultados": resultados,
    }
    if not correspondentes:
        resposta["aviso"] = (
            "Nenhum órgão ativo contém esse termo no nome (ou mnemônico). "
            "Tente um termo mais genérico ou o nome oficial completo."
        )
    return resposta
