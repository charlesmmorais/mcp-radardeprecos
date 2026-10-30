"""Testes da observabilidade: fontes externas, sessões e visão consolidada.

Também travam o formato de ``obter_metricas()``, lido pelo health check.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from mcp_radardeprecos import observability as obs
from mcp_radardeprecos.clients import base

_URL = "https://exemplo-upstream.test"


@pytest.fixture(autouse=True)
def _zerar():
    obs.resetar()
    yield
    obs.resetar()


# ---------------------------------------------------------------------------
# O contrato que não pode quebrar
# ---------------------------------------------------------------------------


def test_formato_antigo_de_obter_metricas_preservado():
    """O health check expõe este dicionário achatado por ferramenta; a forma é contrato."""
    obs.registrar_chamada("buscar_pncp_texto", 0.2, True)
    m = obs.obter_metricas()

    assert set(m) == {"buscar_pncp_texto"}
    assert set(m["buscar_pncp_texto"]) == {
        "chamadas",
        "erros",
        "duracao_media_ms",
        "duracao_p95_ms",
    }
    assert isinstance(m["buscar_pncp_texto"]["duracao_p95_ms"], float)


def test_percentil_antigo_continua_devolvendo_zero_sem_amostra():
    """O formato antigo multiplica o percentil por 1000 — `None` estouraria."""
    assert obs._percentil([], 0.95) == 0.0


# ---------------------------------------------------------------------------
# Fontes externas
# ---------------------------------------------------------------------------


def test_tentativas_media_revela_origem_instavel_mesmo_sem_erro():
    """O sinal que faltava em 2026-08-21.

    Uma chamada que falha duas vezes e acerta na terceira conta como UM
    sucesso — do ponto de vista da ferramenta, funcionou. A instabilidade da
    origem fica invisível justamente quando o retry está fazendo seu
    trabalho. Naquele dia, ~70% das chamadas ao PNCP eram recusadas e o
    problema só aparecia quando as três tentativas falhavam juntas.
    """
    obs.registrar_upstream("pncp", 0.9, True, tentativas=3)
    obs.registrar_upstream("pncp", 0.2, True, tentativas=1)

    m = obs.obter_metricas_completas()["por_fonte_externa"]["pncp"]
    assert m["erros"] == 0
    assert m["taxa_erro"] == 0.0
    assert m["tentativas_media"] == 2.0, "sem isso, a instabilidade fica escondida"


def test_percentil_novo_sem_amostra_e_none_e_nao_zero():
    """Zero se leria como "respondeu instantaneamente" — afirmação falsa.

    Devolver None deixa explícito que não há dado, em vez de inventar um
    número que parece medição. É a mesma disciplina das tools de pesquisa:
    ausência de dado não pode se parecer com dado.
    """
    assert obs._percentil_ou_none([], 0.5) is None
    assert obs._percentil_ou_none([1.5], 0.95) == 1.5


# ---------------------------------------------------------------------------
# Sessões
# ---------------------------------------------------------------------------


def test_sessao_separa_alcance_de_volume():
    """Uma sessão com 10 chamadas != 10 sessões com 1 chamada.

    Confundir os dois faria um cliente com nove chamadas parecer nove pessoas.
    """
    for _ in range(10):
        obs.registrar_sessao("sessao-unica", "buscar_pncp_texto")

    s = obs.obter_metricas_completas()["sessoes"]
    assert s["distintas_em_memoria"] == 1
    assert s["chamadas_por_sessao"]["maximo"] == 10


def test_sessao_none_nao_cria_registro():
    """Transporte stdio não tem sessão HTTP — não inventar uma."""
    obs.registrar_sessao(None, "buscar_pncp_texto")
    assert obs.obter_metricas_completas()["sessoes"]["distintas_em_memoria"] == 0


def test_limite_de_sessoes_descarta_a_mais_antiga_e_avisa(monkeypatch):
    """Servidor de vida longa não pode acumular sessões sem teto.

    E quando descarta, o aviso precisa dizer — senão as médias por sessão
    passam a refletir só as recentes sem ninguém saber.
    """
    import dataclasses

    monkeypatch.setattr(
        obs, "settings", dataclasses.replace(obs.settings, observabilidade_max_sessoes=3)
    )
    for i in range(5):
        obs.registrar_sessao(f"s{i}", "x")

    m = obs.obter_metricas_completas()
    assert m["sessoes"]["distintas_em_memoria"] == 3
    assert m["sessoes"]["descartadas_por_limite"] == 2
    assert any("saíram da memória por limite" in a for a in m["avisos"])


def test_avisos_impedem_ler_sessao_como_pessoa():
    obs.registrar_sessao("s1", "t")
    avisos = obs.obter_metricas_completas()["avisos"]
    assert any("NÃO pessoas" in a for a in avisos)
    assert any("MEMÓRIA" in a for a in avisos)


def test_sem_chamada_avisa_que_vazio_nao_e_defeito():
    """Zero chamadas se lê como "está quebrado" — e normalmente não está."""
    avisos = obs.obter_metricas_completas()["avisos"]
    assert any("Nenhuma chamada registrada" in a for a in avisos)


# ---------------------------------------------------------------------------
# Instrumentação no ponto único
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_json_registra_fonte_e_tentativas(monkeypatch):
    """A instrumentação vive no get_json, não em cada cliente.

    Um lugar só: um cliente novo (uma fonte nova) passa a ser medido sem
    ninguém lembrar de instrumentar.
    """
    monkeypatch.setattr(base, "_espera_retry", lambda *a, **k: 0.0)
    respx.get(f"{_URL}/r").mock(
        side_effect=[
            httpx.RemoteProtocolError("caiu"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    assert await base.get_json(_URL, "/r", {}, source="pncp") == {"ok": True}

    m = obs.obter_metricas_completas()["por_fonte_externa"]["pncp"]
    assert m["chamadas"] == 1, "chamada LOGICA, não por tentativa"
    assert m["erros"] == 0
    assert m["tentativas_media"] == 2.0


@respx.mock
async def test_get_json_conta_erro_quando_esgota_tentativas(monkeypatch):
    monkeypatch.setattr(base, "_espera_retry", lambda *a, **k: 0.0)
    respx.get(f"{_URL}/r").mock(side_effect=httpx.RemoteProtocolError("caiu"))
    with pytest.raises(base.UpstreamError):
        await base.get_json(_URL, "/r", {}, source="pncp")

    m = obs.obter_metricas_completas()["por_fonte_externa"]["pncp"]
    assert m["chamadas"] == 1
    assert m["erros"] == 1
    assert m["taxa_erro"] == 1.0


# ---------------------------------------------------------------------------
# Privacidade
# ---------------------------------------------------------------------------


def test_metricas_completas_nao_guardam_ip_nem_pseudonimo():
    """Contrato de privacidade, travado por teste.

    A visão consolidada mede o que a gestão precisa — o que é chamado, o que
    falha, quanto demora, quantas conversas distintas — sem guardar endereço
    de origem nem pseudônimo derivado dele.
    """
    obs.registrar_chamada("t", 0.1, True)
    obs.registrar_sessao("sessao-abc", "t")
    texto = repr(obs.obter_metricas_completas()).lower()

    for proibido in ("ip", "pseudon", "acessor", "salt", "geoip", "cidade"):
        assert f'"{proibido}"' not in texto
        assert f"'{proibido}'" not in texto
