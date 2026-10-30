"""Extração aditiva de metadados de paginação.

Tanto a API de Consulta do PNCP quanto o Compras.gov.br Dados Abertos podem
devolver, no envelope bruto da resposta, os campos ``totalRegistros``,
``totalPaginas``, ``numeroPagina`` e ``paginasRestantes`` (ver
a análise das specs oficiais seção 3.5) — mas nem toda fonte/endpoint
devolve os 4 (confirmado ao vivo consistentemente só para a família
``/api/consulta`` do PNCP; para o Compras.gov.br, ``totalRegistros`` é
universal neste projeto, mas ``totalPaginas``/``numeroPagina``/
``paginasRestantes`` só foram vistos em alguns módulos). Esta função é
deliberadamente DEFENSIVA: só inclui, na tradução snake_case padronizada, as
chaves que a fonte realmente devolveu no envelope bruto desta chamada
específica — nunca inventa/calcula um valor ausente (ex.: não deriva
``paginas_restantes`` de ``total_paginas - numero_pagina`` quando
``paginasRestantes`` não veio na resposta, nem ecoa o parâmetro ``pagina``
enviado como se fosse ``numeroPagina`` confirmado pela fonte). Chamar como
``{**resultado_da_tool, **extrair_paginacao(bruto)}`` para acrescentar os
campos sem remover nem sobrescrever nenhuma chave já existente no retorno da
tool (ex.: ``total_encontrado``/``total_no_periodo``, mantidos por
compatibilidade — ver CHANGELOG v0.2.4 item 3).
"""
from __future__ import annotations

from typing import Any

_CAMPOS: dict[str, str] = {
    "totalRegistros": "total_registros",
    "totalPaginas": "total_paginas",
    "numeroPagina": "numero_pagina",
    "paginasRestantes": "paginas_restantes",
}


def extrair_paginacao(bruto: dict[str, Any] | None) -> dict[str, int]:
    """Extrai metadados de paginação de um envelope bruto — só os campos presentes.

    Args:
        bruto: Dict cru devolvido por ``clients.base.get_json`` (envelope da
            API de Consulta do PNCP ou do Compras.gov.br Dados Abertos) —
            lida direto os 4 nomes de campo oficiais (camelCase), sem
            nenhuma tradução/normalização prévia necessária.

    Returns:
        Dict com 0 a 4 chaves entre ``total_registros``, ``total_paginas``,
        ``numero_pagina``, ``paginas_restantes`` — só as que vieram como
        inteiro no envelope bruto desta chamada. Nunca inclui uma chave
        ausente, ``None`` ou de tipo não numérico.
    """
    if not bruto:
        return {}
    extraido: dict[str, int] = {}
    for chave_origem, chave_destino in _CAMPOS.items():
        valor = bruto.get(chave_origem)
        if isinstance(valor, int) and not isinstance(valor, bool):
            extraido[chave_destino] = valor
    return extraido
