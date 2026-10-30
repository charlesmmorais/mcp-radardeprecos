"""Testes da tool consultar_sancoes_fornecedor e do tcu_client (respx).

Cobre a consulta consolidada de PJ do TCU: agregação de quatro
bases federais (TCU Inidôneos, CNJ CNIA, CEIS e CNEP) numa única chamada,
sem exigir a chave de API do Portal da Transparência.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from mcp_radardeprecos.clients import base as base_mod
from mcp_radardeprecos.clients import tcu_client
from mcp_radardeprecos.clients.base import UpstreamError
from mcp_radardeprecos.config import settings
from mcp_radardeprecos.tools.consultar_sancoes_fornecedor import (
    consultar_sancoes_fornecedor,
)
from mcp_radardeprecos.utils import cache

CNPJ_LIMPO = "33683111000107"
_URL = f"{settings.tcu_certidoes_base_url}/api/rest/publico/certidoes/{CNPJ_LIMPO}"


def _certidao(tipo, descricao, emissor, situacao):
    return {
        "tipo": tipo,
        "descricao": descricao,
        "emissor": emissor,
        "situacao": situacao,
        "observacao": None,
        "dataHoraEmissao": "25/07/2026 21:22",
        "linkConsultaManual": f"https://exemplo.test/{tipo}",
        "tempoGeracao": 20,
    }


def _resposta(situacoes, *, encontrado_tcu=True):
    """Monta uma resposta consolidada com as 4 fontes nas situações dadas."""
    return {
        "cnpj": "33.683.111/0001-07",
        "razaoSocial": "Serviço Federal de Processamento de Dados",
        "nomeFantasia": "Empresa Exemplo",
        "uf": None,
        "seCnpjEncontradoNaBaseTcu": encontrado_tcu,
        "dataHoraGeracaoInMillis": 1785025358845,
        "certidaoPDF": None,
        "certidoes": [
            _certidao("Inidôneos", "Licitantes Inidôneos", "TCU", situacoes[0]),
            _certidao("CNIA", "CNIA - Improbidade", "CNJ", situacoes[1]),
            _certidao("CEIS", "CEIS", "Portal da Transparência", situacoes[2]),
            _certidao("CNEP", "CNEP", "Portal da Transparência", situacoes[3]),
        ],
    }


@pytest.fixture(autouse=True)
def _limpa_cache_e_backoff(monkeypatch):
    cache.clear()
    # tcu_client cacheia por 30 min; sem limpar, um teste contamina o outro.
    monkeypatch.setattr(base_mod, "_espera_retry", lambda attempt, retry_after: 0.0)
    yield
    cache.clear()


# --- validação de entrada (não chega a bater na rede) -----------------------


async def test_rejeita_cnpj_com_tamanho_invalido():
    with pytest.raises(ValueError):
        await consultar_sancoes_fornecedor(cnpj="123")


# --- caso feliz: nada consta em nenhuma das quatro fontes --------------------


@respx.mock
async def test_nada_consta_em_todas_as_fontes():
    respx.get(_URL).mock(
        return_value=httpx.Response(
            200, json=_resposta(["NADA_CONSTA"] * 4)
        )
    )
    r = await consultar_sancoes_fornecedor(cnpj="33.683.111/0001-07")

    assert r["cnpj"] == "33.683.111/0001-07"
    assert r["razao_social"] == "Serviço Federal de Processamento de Dados"
    assert r["nome_fantasia"] == "Empresa Exemplo"
    assert r["encontrado_na_base_tcu"] is True
    assert r["tem_apontamento"] is False
    assert r["resumo"]["total_fontes"] == 4
    assert r["resumo"]["com_apontamento"] == 0
    assert r["resumo"]["fontes_com_apontamento"] == []
    assert len(r["fontes"]) == 4
    assert all(f["tem_apontamento"] is False for f in r["fontes"])
    assert "aviso" in r


# --- apontamento em uma das fontes ------------------------------------------


@respx.mock
async def test_apontamento_em_uma_fonte_marca_tem_apontamento():
    respx.get(_URL).mock(
        return_value=httpx.Response(
            200,
            json=_resposta(["NADA_CONSTA", "NADA_CONSTA", "CONSTA", "NADA_CONSTA"]),
        )
    )
    r = await consultar_sancoes_fornecedor(cnpj=CNPJ_LIMPO)

    assert r["tem_apontamento"] is True
    assert r["resumo"]["com_apontamento"] == 1
    assert r["resumo"]["fontes_com_apontamento"] == ["CEIS"]
    ceis = next(f for f in r["fontes"] if f["fonte"] == "CEIS")
    assert ceis["tem_apontamento"] is True
    assert ceis["situacao"] == "CONSTA"
    # O aviso reforçado deve aparecer quando há apontamento.
    assert "ATENÇÃO" in r["aviso"]


# --- CNPJ inexistente/inválido: endpoint devolve corpo vazio ----------------


@respx.mock
async def test_resposta_vazia_vira_upstream_error():
    respx.get(_URL).mock(return_value=httpx.Response(200, text=""))
    with pytest.raises(UpstreamError):
        await consultar_sancoes_fornecedor(cnpj=CNPJ_LIMPO)


# --- cliente: monta a URL certa e passa seEmitirPDF=false -------------------


@respx.mock
async def test_client_usa_seemitirpdf_false():
    rota = respx.get(_URL).mock(
        return_value=httpx.Response(200, json=_resposta(["NADA_CONSTA"] * 4))
    )
    await tcu_client.consultar_certidoes_pj(CNPJ_LIMPO)
    assert rota.called
    assert rota.calls.last.request.url.params["seEmitirPDF"] == "false"


async def test_client_usa_timeout_dedicado_do_tcu(monkeypatch):
    # v0.3.7: a consulta ao TCU é lenta p/ CNPJ com registro —
    # deve usar settings.tcu_timeout_seconds, não o timeout global.
    from unittest.mock import AsyncMock

    from mcp_radardeprecos.config import settings

    fake = AsyncMock(return_value=_resposta(["NADA_CONSTA"] * 4))
    monkeypatch.setattr(tcu_client, "get_json", fake)
    await tcu_client.consultar_certidoes_pj(CNPJ_LIMPO)
    assert fake.await_args.kwargs["timeout_seconds"] == settings.tcu_timeout_seconds
