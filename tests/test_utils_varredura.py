"""Testes de utils/varredura.py: lotes concorrentes, dedup, teto e orçamento."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from mcp_radardeprecos.utils.varredura import (
    aviso_orcamento,
    aviso_paginas_com_falha,
    varrer_indice,
)


def _pagina(inicio: int, quantidade: int, total: int, tamanho: int = 100):
    """Página sintética com `quantidade` itens numerados a partir de `inicio`."""
    return {
        "items": [
            {"numero_controle_pncp": f"nc-{inicio + i:05d}", "n": inicio + i}
            for i in range(quantidade)
        ],
        "total": total,
    }


def _fabrica(paginas: dict[int, dict], chamadas: list[int]):
    async def buscar(p: int):
        chamadas.append(p)
        return paginas.get(p, {"items": [], "total": 0})

    return buscar


async def test_pagina_unica_suficiente_nao_dispara_lotes():
    chamadas: list[int] = []
    buscar = _fabrica({1: _pagina(0, 100, 500)}, chamadas)

    r = await varrer_indice(
        buscar, lambda i: True, limite=10, tamanho_pagina=100
    )

    assert chamadas == [1]  # caso comum: nenhuma página extra
    assert len(r.coletados) == 10
    assert r.total_indice == 500
    assert not r.orcamento_estourado


async def test_lotes_concorrentes_preservam_ordem_e_dedup():
    chamadas: list[int] = []
    paginas = {
        1: _pagina(0, 100, 350),
        2: _pagina(100, 100, 350),
        3: _pagina(100, 100, 350),  # página 3 duplica a 2 (mesmos numero_controle)
        4: _pagina(300, 50, 350),
    }
    buscar = _fabrica(paginas, chamadas)

    r = await varrer_indice(
        buscar, lambda i: True, limite=1000, tamanho_pagina=100
    )

    # total=350 → última página real = 4; páginas 2..4 num único lote de até 5.
    assert sorted(chamadas) == [1, 2, 3, 4]
    # 100 + 100 + 0 (duplicadas) + 50 = 250, em ordem de página.
    assert len(r.coletados) == 250
    ns = [c["n"] for c in r.coletados]
    assert ns == sorted(ns)  # ordem de página preservada apesar do gather
    assert r.indice_esgotado  # página 4 veio curta (50 < 100)


async def test_respeita_max_paginas_e_sinaliza():
    chamadas: list[int] = []
    # Índice "infinito": toda página vem cheia e nada passa no filtro.
    paginas = {p: _pagina(p * 100, 100, 10_000) for p in range(1, 101)}
    buscar = _fabrica(paginas, chamadas)

    r = await varrer_indice(
        buscar, lambda i: False, limite=20, tamanho_pagina=100, max_paginas=100
    )

    assert len(chamadas) == 100
    assert r.coletados == []
    assert r.atingiu_max_paginas
    assert not r.indice_esgotado


async def test_orcamento_estourado_devolve_parcial():
    chamadas: list[int] = []
    paginas = {p: _pagina(p * 100, 100, 10_000) for p in range(1, 101)}
    buscar = _fabrica(paginas, chamadas)

    # Relógio congelado que "anda" 999s já na primeira checagem entre lotes.
    tempos = iter([0.0] + [999.0] * 50)
    with patch("mcp_radardeprecos.utils.varredura.time.monotonic", lambda: next(tempos)):
        r = await varrer_indice(
            buscar,
            lambda i: i["n"] % 100 == 0,  # 1 aceito por página — nunca atinge limite
            limite=50,
            tamanho_pagina=100,
            orcamento_segundos=120.0,
        )

    assert chamadas == [1]  # parou antes do primeiro lote
    assert r.orcamento_estourado
    assert len(r.coletados) == 1  # parcial da página 1 preservado
    assert not r.atingiu_max_paginas  # motivo correto, não confundir com o teto


async def test_orcamento_desativado_com_zero():
    chamadas: list[int] = []
    paginas = {1: _pagina(0, 100, 200), 2: _pagina(100, 100, 200)}
    buscar = _fabrica(paginas, chamadas)

    r = await varrer_indice(
        buscar, lambda i: True, limite=1000, tamanho_pagina=100, orcamento_segundos=0
    )

    assert sorted(chamadas) == [1, 2]
    assert not r.orcamento_estourado
    assert len(r.coletados) == 200


def test_aviso_orcamento_menciona_variavel_e_parcial():
    texto = aviso_orcamento(120.0)
    assert "RADARDEPRECOS_TOOL_BUDGET_SECONDS" in texto
    assert "120s" in texto
    assert "parciais" in texto


# --- tolerância a página que falha -------------------------------
#
# Regressão da falha relatada como "muitas falhas de rede no PNCP": uma página
# que não responde derrubava o gather, a varredura e a tool inteira, jogando
# fora tudo que já tinha sido coletado.


def _fabrica_com_falhas(paginas: dict[int, dict], falham: set[int], chamadas: list[int]):
    async def buscar(p: int):
        chamadas.append(p)
        if p in falham:
            raise httpx.ReadError("conexão interrompida na leitura")
        return paginas.get(p, {"items": [], "total": 0})

    return buscar


async def test_pagina_que_falha_e_pulada_e_a_varredura_continua():
    chamadas: list[int] = []
    paginas = {n: _pagina(n * 100, 100, 1000) for n in range(1, 7)}
    buscar = _fabrica_com_falhas(paginas, {3}, chamadas)

    r = await varrer_indice(buscar, lambda i: True, limite=400, tamanho_pagina=100)

    # A página 3 falhou, mas 1, 2, 4, 5 responderam: 400 itens coletados.
    assert len(r.coletados) == 400
    assert [p for p, _ in r.paginas_com_falha] == [3]
    assert "ReadError" in r.paginas_com_falha[0][1]
    # E o buraco NÃO foi confundido com fim de índice.
    assert not r.indice_esgotado


async def test_lote_inteiro_falhando_devolve_parcial_em_vez_de_estourar():
    chamadas: list[int] = []
    paginas = {1: _pagina(0, 100, 10000)}
    buscar = _fabrica_com_falhas(paginas, {2, 3, 4, 5, 6}, chamadas)

    r = await varrer_indice(
        buscar, lambda i: True, limite=300, tamanho_pagina=100, max_paginas=6
    )

    # Só a página 1 vingou — mas os 100 itens dela sobreviveram.
    assert len(r.coletados) == 100
    assert [p for p, _ in r.paginas_com_falha] == [2, 3, 4, 5, 6]


async def test_falha_na_primeira_pagina_ainda_propaga():
    # Sem a página 1 não há nem itens nem `total`: não há parcial a devolver,
    # então o erro deve chegar a quem chamou em vez de virar "zero resultados",
    # que seria indistinguível de uma busca legítima sem resultados.
    chamadas: list[int] = []
    buscar = _fabrica_com_falhas({}, {1}, chamadas)

    with pytest.raises(httpx.ReadError):
        await varrer_indice(buscar, lambda i: True, limite=10, tamanho_pagina=100)


def test_aviso_paginas_com_falha_nomeia_paginas_e_erro():
    texto = aviso_paginas_com_falha([(3, "ReadError('x')"), (7, "ReadError('y')")])

    assert "2 página(s)" in texto
    assert "3, 7" in texto
    assert "ReadError" in texto
    assert "PARCIAL" in texto


# --- parada por janela temporal ----------------------------------


def _pagina_datada(inicio: int, quantidade: int, total: int, data: str):
    """Página sintética cujos itens carregam uma data de publicação."""
    return {
        "items": [
            {
                "numero_controle_pncp": f"nc-{inicio + i:05d}",
                "data_publicacao_pncp": data,
            }
            for i in range(quantidade)
        ],
        "total": total,
    }


async def test_para_ao_cruzar_o_fim_da_janela():
    """A varredura para na primeira pagina fora da janela, sem varrer o resto.

    Este e o ganho central da v0.4.20. Antes, ``aceitar_item`` apenas deixava
    de COLETAR os itens fora da janela e a varredura seguia ate esgotar o
    indice, o teto de paginas ou os 120s de orcamento — gastando dezenas de
    requisicoes para descobrir o que a segunda pagina ja provava.
    """
    chamadas: list[int] = []
    paginas = {
        1: _pagina_datada(0, 100, 10_000, "2026-08-01T00:00:00"),
        2: _pagina_datada(100, 100, 10_000, "2026-08-01T00:00:00"),
        3: _pagina_datada(200, 100, 10_000, "2019-01-01T00:00:00"),  # fora
        4: _pagina_datada(300, 100, 10_000, "2018-01-01T00:00:00"),
    }
    buscar = _fabrica(paginas, chamadas)

    r = await varrer_indice(
        buscar,
        lambda i: i.get("data_publicacao_pncp", "") >= "2026-01-01",
        limite=1000,
        tamanho_pagina=100,
        max_paginas=100,
        passou_da_janela=lambda i: i.get("data_publicacao_pncp", "") < "2026-01-01",
    )

    assert r.parou_por_janela
    assert len(r.coletados) == 200  # so as paginas 1 e 2
    # Parou por janela nao e resultado parcial: o que restava estava fora.
    assert not r.atingiu_max_paginas
    assert not r.orcamento_estourado
    # Sem a parada, o teto de 100 paginas teria sido perseguido ate o fim.
    assert max(chamadas) <= 6


async def test_sem_predicado_a_varredura_nao_para_por_data():
    """Comportamento anterior preservado quando ``passou_da_janela`` e None.

    E o que deve acontecer com ordenacao crescente: nada se pode concluir
    sobre as paginas seguintes, entao parar seria errado.
    """
    chamadas: list[int] = []
    paginas = {
        p: _pagina_datada((p - 1) * 100, 100, 1000, "2019-01-01T00:00:00")
        for p in range(1, 11)
    }
    buscar = _fabrica(paginas, chamadas)

    r = await varrer_indice(
        buscar,
        lambda i: False,
        limite=1000,
        tamanho_pagina=100,
        max_paginas=10,
    )

    assert not r.parou_por_janela
    assert r.coletados == []
    assert max(chamadas) == 10  # varreu tudo, como antes


async def test_data_invalida_nao_autoriza_parar():
    """Uma data ausente ou lixo NAO pode encerrar a varredura.

    Parar por engano esconde todo o resto do indice — falso negativo muito
    mais caro que um item a menos. Por isso ``anterior_a_janela`` devolve
    False para data invalida, e este teste trava esse contrato usando o
    predicado real.
    """
    from mcp_radardeprecos.utils.datas import anterior_a_janela

    assert anterior_a_janela(None, 12) is False
    assert anterior_a_janela("", 12) is False
    assert anterior_a_janela("data-invalida", 12) is False
    assert anterior_a_janela("0001-01-01", 12) is True  # valida e antiga

    chamadas: list[int] = []
    paginas = {
        1: {
            "items": [{"numero_controle_pncp": "nc-1", "data_publicacao_pncp": None}]
            * 1
            + [{"numero_controle_pncp": "nc-2"}],
            "total": 300,
        },
        2: _pagina_datada(100, 100, 300, "2026-08-01T00:00:00"),
    }
    paginas[1]["items"] += [
        {"numero_controle_pncp": f"nc-{i}", "data_publicacao_pncp": "2026-08-01T00:00:00"}
        for i in range(3, 101)
    ]
    buscar = _fabrica(paginas, chamadas)

    r = await varrer_indice(
        buscar,
        lambda i: True,
        limite=1000,
        tamanho_pagina=100,
        max_paginas=5,
        passou_da_janela=lambda i: anterior_a_janela(
            i.get("data_publicacao_pncp"), 12
        ),
    )

    # As datas ausentes da pagina 1 nao interromperam a varredura.
    assert not r.parou_por_janela
    assert 2 in chamadas
