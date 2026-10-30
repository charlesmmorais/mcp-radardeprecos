"""Testes da contagem agregada no índice do PNCP.

O que estes testes protegem: a distinção entre "não tem a característica" e
"não se sabe se tem". O campo `possui_emenda_parlamentar` é booleano no nome
e de três estados no índice — `true`, `false` e ausente — e o ausente é a
maioria esmagadora nos editais (944.019 de 951.350 em 2026).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from mcp_radardeprecos.config import settings
from mcp_radardeprecos.tools.contar_pncp import contar_pncp

_PATCH = "mcp_radardeprecos.tools.contar_pncp.pncp_client.buscar_texto"


async def test_conta_sem_exigir_termo_de_busca():
    """O motivo de a tool existir: `/api/search` não exige `q`.

    Forçar um termo genérico só para destravar a consulta devolve o total do
    termo, não o do universo — foi assim que uma apuração sobre emenda
    parlamentar chegou a zero.
    """
    with patch(_PATCH, new_callable=AsyncMock) as mock:
        mock.return_value = {"total": 951350, "items": []}
        r = await contar_pncp(tipo_documento="edital", ano=2026, status="todos")
    assert r["total"] == 951350
    assert mock.call_args.args[0] == ""
    assert "termo_busca" not in r["filtros"]


async def test_pede_pagina_minima_por_ser_contagem():
    with patch(_PATCH, new_callable=AsyncMock) as mock:
        mock.return_value = {"total": 10, "items": []}
        await contar_pncp(tipo_documento="edital")
    assert mock.call_args.kwargs["tamanho_pagina"] == 1


async def test_detalhe_decompoe_em_tres_estados():
    """Números reais medidos em 2026-09-07 (editais de 2026, status=todos)."""
    with patch(_PATCH, new_callable=AsyncMock) as mock:
        mock.side_effect = [
            {"total": 951350},  # sem o booleano
            {"total": 107},  # true
            {"total": 7224},  # false
        ]
        r = await contar_pncp(
            tipo_documento="edital",
            ano=2026,
            status="todos",
            detalhar_campo="possui_emenda_parlamentar",
        )
    d = r["detalhe"]
    assert (d["true"], d["false"]) == (107, 7224)
    assert d["ausente"] == 951350 - 7331
    # A proporção é sobre os PREENCHIDOS, não sobre o total: sobre o total ela
    # misturaria "não tem" com "não se sabe".
    assert d["percentual_true_entre_preenchidos"] == round(100 * 107 / 7331, 2)
    assert d["percentual_preenchido"] == round(100 * 7331 / 951350, 2)


async def test_detalhe_sempre_avisa_do_terceiro_estado():
    with patch(_PATCH, new_callable=AsyncMock) as mock:
        mock.side_effect = [{"total": 100}, {"total": 40}, {"total": 60}]
        r = await contar_pncp(
            tipo_documento="ata", detalhar_campo="permite_adesao"
        )
    assert any("TRÊS estados" in a for a in r["avisos"])
    # Cobertura de 100% não dispara o aviso de cobertura baixa.
    assert not any("COBERTURA BAIXA" in a for a in r["avisos"])


async def test_avisa_quando_a_cobertura_e_baixa():
    """O caso da emenda parlamentar: 0,77% preenchido."""
    with patch(_PATCH, new_callable=AsyncMock) as mock:
        mock.side_effect = [{"total": 951350}, {"total": 107}, {"total": 7224}]
        r = await contar_pncp(
            tipo_documento="edital", detalhar_campo="possui_emenda_parlamentar"
        )
    assert any("COBERTURA BAIXA" in a for a in r["avisos"])


async def test_zero_por_campo_vazio_nao_e_zero_por_ausencia_do_fenomeno():
    """`contrato / exigencia_conteudo_nacional`: filtro aceito, nenhum dado.

    Sem este aviso, o zero seria lido como "nenhum contrato exige conteúdo
    nacional", quando o que há é ausência de preenchimento no índice.
    """
    with patch(_PATCH, new_callable=AsyncMock) as mock:
        mock.side_effect = [{"total": 1245073}, {"total": 0}, {"total": 0}]
        r = await contar_pncp(
            tipo_documento="contrato",
            detalhar_campo="exigencia_conteudo_nacional",
        )
    assert r["detalhe"]["ausente"] == 1245073
    assert r["detalhe"]["percentual_true_entre_preenchidos"] is None
    assert any("SEM DADO" in a for a in r["avisos"])


async def test_detalhe_nao_fixa_o_booleano_na_chamada_de_total():
    """A primeira das três chamadas tem de vir SEM o filtro.

    Se o total fosse colhido já com o booleano fixado, `ausente` sairia
    sempre zero e a tool esconderia exatamente o que veio expor.
    """
    with patch(_PATCH, new_callable=AsyncMock) as mock:
        mock.side_effect = [{"total": 100}, {"total": 1}, {"total": 2}]
        await contar_pncp(
            tipo_documento="edital", detalhar_campo="possui_emenda_parlamentar"
        )
    chamadas = [c.kwargs["possui_emenda_parlamentar"] for c in mock.call_args_list]
    assert chamadas == [None, True, False]


async def test_recusa_campo_que_nao_e_booleano_do_indice():
    with pytest.raises(ValueError, match="detalhar_campo"):
        await contar_pncp(tipo_documento="edital", detalhar_campo="modalidade")


async def test_recusa_tipo_documento_invalido():
    with pytest.raises(ValueError, match="tipo_documento"):
        await contar_pncp(tipo_documento="empenho")


async def test_termo_opcional_e_ecoado_quando_informado():
    with patch(_PATCH, new_callable=AsyncMock) as mock:
        mock.return_value = {"total": 5}
        r = await contar_pncp(tipo_documento="edital", termo_busca="ambulância")
    assert mock.call_args.args[0] == "ambulância"
    assert r["filtros"]["termo_busca"] == "ambulância"


@respx.mock
async def test_query_string_bate_com_a_medida_ao_vivo():
    """Trava a tradução dos argumentos para a query string real.

    Os números dos testes acima vieram de chamadas ao vivo feitas com esta
    query, em 2026-09-07:

        /api/search/?tipos_documento=edital&anos=2026&status=todos
                     &possui_emenda_parlamentar=true&tam_pagina=1

    Se a montagem dos parâmetros mudar (nome, caixa do booleano, `q`
    ausente), os totais deixam de corresponder ao que foi medido — e o erro
    seria silencioso, porque o endpoint IGNORA parâmetro desconhecido e
    devolve o total não filtrado, sem status de erro.
    """
    rota = respx.get(settings.pncp_search_base_url).mock(
        return_value=httpx.Response(200, json={"total": 107, "items": []})
    )
    await contar_pncp(
        tipo_documento="edital",
        ano=2026,
        status="todos",
        possui_emenda_parlamentar=True,
    )
    p = rota.calls.last.request.url.params
    assert p["tipos_documento"] == "edital"
    assert p["anos"] == "2026"
    assert p["status"] == "todos"
    # minúsculo: o servidor devolve 204 No Content para valor não booleano,
    # e "True" com maiúscula não é booleano para ele.
    assert p["possui_emenda_parlamentar"] == "true"
    assert p["tam_pagina"] == "1"
    assert p.get("q", "") == ""
