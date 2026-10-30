"""Regressão: a sessão MCP tem de ser lida onde a ferramenta roda.

Até a v0.5.10 o servidor reportava ``sessoes.distintas_em_memoria = 0`` depois
de baterias inteiras de chamadas reais. A leitura fácil — e errada — era que o
cliente fosse *sessionless* (protocolo 2026-07-28, sem ``Mcp-Session-Id``).

**Medido em 2026-09-07, com servidor streamable-http de verdade:** o servidor
emitiu o ``Mcp-Session-Id``, o cliente o devolveu no ``tools/call``, e
``sessao_atual()`` dentro do handler leu ``None``. O protocolo negociado era
``2025-06-18`` — cliente COM sessão. Portanto o zero não provava nada sobre o
cliente; apareceria igual em qualquer cenário.

A causa está na arquitetura do transporte: na primeira requisição — o
``initialize``, quando o cliente ainda não tem session id — o gerenciador cria
o transporte e dispara ``run_server`` numa task própria. É essa task que
processa todas as mensagens seguintes, inclusive as chamadas de ferramenta. O
``ContextVar`` do middleware ASGI era definido na task da requisição HTTP e
nunca chegava lá.

Estes testes usam o servidor real, por HTTP, porque um mock do contexto MCP
reproduziria a suposição em vez de testá-la — foi exatamente a suposição que
manteve o defeito invisível.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request

import pytest
import uvicorn

from mcp_radardeprecos import observability, server

_PORTA = 8207
_BASE = f"http://127.0.0.1:{_PORTA}/mcp"
_CABECALHOS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


@pytest.fixture(scope="module")
def servidor():
    """Servidor streamable-http real, em thread, para o módulo inteiro."""
    app = server.mcp.streamable_http_app()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=_PORTA, log_level="critical")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(60):  # espera subir, sem sleep fixo generoso
        time.sleep(0.1)
        if getattr(srv, "started", False):
            break
    yield
    srv.should_exit = True
    t.join(timeout=5)


def _post(payload: dict, sessao: str | None = None) -> str | None:
    cab = dict(_CABECALHOS)
    if sessao:
        cab["Mcp-Session-Id"] = sessao
    req = urllib.request.Request(_BASE, json.dumps(payload).encode(), cab)
    with urllib.request.urlopen(req, timeout=25) as r:
        r.read()
        return r.headers.get("Mcp-Session-Id")


def _abrir_sessao(nome: str, protocolo: str = "2025-06-18") -> str | None:
    sessao = _post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": protocolo,
                "capabilities": {},
                "clientInfo": {"name": nome, "version": "1"},
            },
        }
    )
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sessao)
    return sessao


def _chamar(sessao: str | None) -> None:
    _post(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "consultar_tabelas_dominio_pncp",
                "arguments": {"tabela": "modalidade_contratacao"},
            },
        },
        sessao,
    )


def test_o_servidor_emite_session_id_para_cliente_legado(servidor):
    """Premissa do resto: há sessão de verdade para ser lida."""
    sessao = _abrir_sessao("premissa")
    assert sessao, "o transporte deveria emitir Mcp-Session-Id no initialize"


def test_chamadas_de_ferramenta_contam_na_sessao(servidor):
    """O defeito: contava zero mesmo com sessão real.

    Duas sessões distintas, três chamadas cada — números escolhidos para que
    um resultado errado não possa coincidir com o certo por acaso.
    """
    antes = observability.obter_metricas_completas()["sessoes"]["distintas_em_memoria"]
    for n in range(2):
        sessao = _abrir_sessao(f"cliente-{n}")
        for _ in range(3):
            _chamar(sessao)
    depois = observability.obter_metricas_completas()["sessoes"]
    assert depois["distintas_em_memoria"] >= antes + 2, (
        "cada initialize abre uma sessão MCP distinta e ela precisa ser contada"
    )
    assert depois["chamadas_por_sessao"]["media"] is not None


def test_versao_de_protocolo_negociada_e_registrada(servidor):
    """Sem isto, "zero sessões" admitia duas leituras e nenhuma verificável.

    O campo separa cliente sessionless de leitura quebrada do nosso lado — a
    ambiguidade que fez o defeito passar por comportamento esperado.
    """
    sessao = _abrir_sessao("com-protocolo", protocolo="2025-06-18")
    _chamar(sessao)
    protocolos = observability.obter_metricas_completas()["por_protocolo"]
    assert protocolos.get("2025-06-18", 0) >= 1


def test_sessoes_distintas_nao_sao_fundidas(servidor):
    """Guarda contra o exagero oposto: contar tudo como uma sessão só.

    Um identificador constante faria `distintas_em_memoria` valer 1 para
    sempre — tão inútil quanto o zero, e mais difícil de perceber.
    """
    a = _abrir_sessao("distinta-A")
    b = _abrir_sessao("distinta-B")
    antes = observability.obter_metricas_completas()["sessoes"]["distintas_em_memoria"]
    _chamar(a)
    _chamar(b)
    depois = observability.obter_metricas_completas()["sessoes"]["distintas_em_memoria"]
    assert depois == antes + 2
