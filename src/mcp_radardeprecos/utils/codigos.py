"""Códigos de órgão e de UASG do Compras.gov.br, sempre com zero à esquerda.

A fonte é inconsistente: devolve ``codigoOrgao`` como número (``3000``), mas os
filtros só reconhecem o código com o zero à esquerda. Medido em 30/10/2026,
mesmo período e mesmos demais filtros:

=====================================================  ==========  ==========
Filtro                                                 com zero    sem zero
=====================================================  ==========  ==========
``codigoOrgao`` em ``1_consultarContratos``            5 (03000)   0 (3000)
``codigoOrgao`` em ``1.2_consultarContratos_FimVig.``  3           0
``codigoUnidadeGestora`` em ``1_consultarContratos``   5 (030001)  0 (30001)
``codigoUnidadeGerenciadora`` em ``1_consultarARP``    6           0
``codigoUnidadeGerenciadora`` em ``1.2_..._FimVig.``   9           0
=====================================================  ==========  ==========

O resultado vazio não vem com erro: a consulta parece correta e afirma que o
órgão não tem contratos. Por isso todo código de órgão ou UASG que vai para a
fonte passa por aqui. Na listagem de órgãos ativos (12.126), o código tem até
5 dígitos; as UASGs têm sempre 6.
"""
from __future__ import annotations

LARGURA_ORGAO = 5
LARGURA_UASG = 6


def _normalizar(valor: object, largura: int, nome: str, exemplo: str) -> str | None:
    if isinstance(valor, bool):
        raise ValueError(f"{nome} deve ser um código numérico (ex.: {exemplo}); recebido {valor!r}")
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if not (texto.isascii() and texto.isdigit()):
        raise ValueError(
            f"{nome} deve conter só dígitos (ex.: {exemplo}); recebido {valor!r}"
        )
    texto = texto.lstrip("0") or "0"
    if len(texto) > largura:
        raise ValueError(
            f"{nome} tem no máximo {largura} dígitos (ex.: {exemplo}); recebido {valor!r}"
        )
    return texto.zfill(largura)


def normalizar_codigo_orgao(valor: object) -> str | None:
    """Código de órgão com 5 dígitos: ``3000`` e ``"03000"`` → ``"03000"``."""
    return _normalizar(valor, LARGURA_ORGAO, "codigo_orgao", "03000")


def normalizar_codigo_uasg(valor: object) -> str | None:
    """Código de UASG com 6 dígitos: ``30001`` e ``"030001"`` → ``"030001"``."""
    return _normalizar(valor, LARGURA_UASG, "codigo da UASG", "030001")
