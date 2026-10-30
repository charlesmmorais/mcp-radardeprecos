"""Teste único parametrizado de paginação.

Garante presença/coerência dos campos de paginação padronizados
(``total_registros``, ``total_paginas``, ``numero_pagina``,
``paginas_restantes``) nas 9 tools listadas no plano, quando a fonte
mockada devolve o envelope completo (``totalRegistros``/``totalPaginas``/
``numeroPagina``/``paginasRestantes``). Cobertura complementar à de
``tests/test_utils_paginacao.py`` (que testa ``extrair_paginacao`` isolada);
aqui o alvo é a integração ponta a ponta em cada tool.

``consultar_contratos_orgao_pncp`` é a exceção documentada (ver docstring do
módulo e comentários no código): por ser um agregador multi-fatia/
multi-página, não expõe ``numero_pagina``/``paginas_restantes`` (sem
significado de página única) — só ``total_registros`` quando a soma por
fatia é confiável.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.buscar_arp_compras import buscar_arp_compras
from mcp_radardeprecos.tools.buscar_homologados_14133 import buscar_homologados_14133
from mcp_radardeprecos.tools.buscar_precos_praticados_compras import (
    buscar_precos_praticados_compras,
)
from mcp_radardeprecos.tools.buscar_propostas_abertas import buscar_propostas_abertas
from mcp_radardeprecos.tools.consultar_contratos_compras import consultar_contratos_compras
from mcp_radardeprecos.tools.consultar_contratos_orgao_pncp import (
    consultar_contratos_orgao_pncp,
)
from mcp_radardeprecos.tools.consultar_itens_contrato_compras import (
    consultar_itens_contrato_compras,
)
from mcp_radardeprecos.tools.listar_itens_catalogo import listar_itens_catalogo
from mcp_radardeprecos.tools.radar_vencimentos import radar_vencimentos

_ENVELOPE_COMPRAS = {
    "resultado": [],
    "totalRegistros": 40,
    "totalPaginas": 4,
    "numeroPagina": 1,
    "paginasRestantes": 3,
}
_ENVELOPE_PNCP = {
    "data": [],
    "totalRegistros": 40,
    "totalPaginas": 4,
    "numeroPagina": 1,
    "paginasRestantes": 3,
}


async def _caso_buscar_precos_praticados_compras():
    with patch(
        "mcp_radardeprecos.clients.compras_client.consultar_precos_material",
        new=AsyncMock(return_value=_ENVELOPE_COMPRAS),
    ):
        return await buscar_precos_praticados_compras(codigo_item_catalogo=1, tipo_item="material")


async def _caso_buscar_homologados_14133():
    with patch(
        "mcp_radardeprecos.clients.compras_client.consultar_itens_14133",
        new=AsyncMock(return_value=_ENVELOPE_COMPRAS),
    ):
        return await buscar_homologados_14133("2026-01-01", "2026-01-31", codigo_item_catalogo=1)


async def _caso_listar_itens_catalogo():
    with patch(
        "mcp_radardeprecos.clients.compras_client.listar_itens_material_por_pdm",
        new=AsyncMock(return_value=_ENVELOPE_COMPRAS),
    ):
        return await listar_itens_catalogo("material", 1)


async def _caso_consultar_contratos_orgao_pncp():
    with patch(
        "mcp_radardeprecos.clients.pncp_client.consultar_contratos",
        new=AsyncMock(return_value=_ENVELOPE_PNCP),
    ):
        return await consultar_contratos_orgao_pncp(
            "00394460000141", data_inicial="20260101", data_final="20260105",
        )


async def _caso_radar_vencimentos():
    with patch(
        "mcp_radardeprecos.clients.compras_client.consultar_contratos_fim_vigencia",
        new=AsyncMock(return_value=_ENVELOPE_COMPRAS),
    ):
        return await radar_vencimentos(
            "contratos",
            data_fim_vigencia_inicio="2026-01-01",
            data_fim_vigencia_fim="2026-01-31",
            codigo_orgao="26443",
        )


async def _caso_buscar_propostas_abertas():
    with patch(
        "mcp_radardeprecos.clients.pncp_client.consultar_contratacoes_proposta_aberta",
        new=AsyncMock(return_value=_ENVELOPE_PNCP),
    ):
        return await buscar_propostas_abertas()


async def _caso_buscar_arp_compras():
    with patch(
        "mcp_radardeprecos.clients.compras_client.consultar_arp",
        new=AsyncMock(return_value=_ENVELOPE_COMPRAS),
    ):
        return await buscar_arp_compras(
            data_vigencia_inicial_min="2025-01-01", data_vigencia_inicial_max="2025-06-30",
        )


async def _caso_consultar_itens_contrato_compras():
    with patch(
        "mcp_radardeprecos.clients.compras_client.consultar_contratos_itens",
        new=AsyncMock(return_value=_ENVELOPE_COMPRAS),
    ):
        return await consultar_itens_contrato_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-01-01",
            data_vigencia_inicial_max="2025-06-30",
        )


async def _caso_consultar_contratos_compras():
    with patch(
        "mcp_radardeprecos.clients.compras_client.consultar_contratos",
        new=AsyncMock(return_value=_ENVELOPE_COMPRAS),
    ):
        return await consultar_contratos_compras(
            codigo_orgao=25201,
            data_vigencia_inicial_min="2025-01-01",
            data_vigencia_inicial_max="2025-06-30",
        )


_CASOS = [
    pytest.param(_caso_buscar_precos_praticados_compras, id="buscar_precos_praticados_compras"),
    pytest.param(_caso_buscar_homologados_14133, id="buscar_homologados_14133"),
    pytest.param(_caso_listar_itens_catalogo, id="listar_itens_catalogo"),
    pytest.param(_caso_consultar_contratos_orgao_pncp, id="consultar_contratos_orgao_pncp"),
    pytest.param(_caso_radar_vencimentos, id="radar_vencimentos"),
    pytest.param(_caso_buscar_propostas_abertas, id="buscar_propostas_abertas"),
    pytest.param(_caso_buscar_arp_compras, id="buscar_arp_compras"),
    pytest.param(_caso_consultar_itens_contrato_compras, id="consultar_itens_contrato_compras"),
    pytest.param(_caso_consultar_contratos_compras, id="consultar_contratos_compras"),
]


@pytest.mark.parametrize("caso", _CASOS)
async def test_paginacao_padronizada_presente_e_coerente(caso):
    resultado = await caso()

    if "total_registros" in resultado:
        assert isinstance(resultado["total_registros"], int)
        assert resultado["total_registros"] >= 0
    if "total_paginas" in resultado:
        assert isinstance(resultado["total_paginas"], int)
        assert resultado["total_paginas"] >= 1
    if "numero_pagina" in resultado:
        assert isinstance(resultado["numero_pagina"], int)
        assert resultado["numero_pagina"] >= 1
    if "paginas_restantes" in resultado:
        assert isinstance(resultado["paginas_restantes"], int)
        assert resultado["paginas_restantes"] >= 0
    # A invariante central pedida pelo plano: total_paginas >= numero_pagina.
    if "total_paginas" in resultado and "numero_pagina" in resultado:
        assert resultado["total_paginas"] >= resultado["numero_pagina"]


async def test_consultar_contratos_orgao_pncp_nunca_expoe_numero_pagina_ou_paginas_restantes():
    # Documentado no próprio código: agregador multi-fatia/multi-página não
    # tem UM envelope — expor numero_pagina/paginas_restantes seria enganoso.
    resultado = await _caso_consultar_contratos_orgao_pncp()
    assert "numero_pagina" not in resultado
    assert "paginas_restantes" not in resultado
