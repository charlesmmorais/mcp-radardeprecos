"""Testes de ``clients/base.py``: retry 429/5xx com backoff e cliente compartilhado.

Cobertura das duas mudanças da v0.1.52:

1. Cliente ``httpx.AsyncClient`` compartilhado (pool de conexões) — a mesma
   instância é reutilizada entre chamadas no mesmo event loop.
2. Retry para status transitórios (429/502/503/504) com backoff exponencial
   + jitter e respeito ao header ``Retry-After``; demais 4xx continuam
   falhando na primeira tentativa (erro de validação — repetir não ajuda).
"""
from __future__ import annotations

import logging

import httpx
import pytest
import respx

from mcp_radardeprecos.clients import base
from mcp_radardeprecos.clients.base import UpstreamError, _espera_retry
from mcp_radardeprecos.config import settings

_URL_BASE = "https://exemplo-upstream.test"


@pytest.fixture(autouse=True)
def _retry_sem_espera(monkeypatch):
    """Zera o tempo de backoff nos retries, para os testes não dormirem de verdade.

    Só afeta o quanto ``get_json`` espera entre tentativas — a função real
    ``_espera_retry`` continua testada diretamente (é pura), sem patch.
    """
    monkeypatch.setattr(base, "_espera_retry", lambda attempt, retry_after, **kw: 0.0)


@respx.mock
async def test_503_transitorio_e_retryado_ate_sucesso():
    route = respx.get(f"{_URL_BASE}/recurso").mock(
        side_effect=[
            httpx.Response(503, text="indisponível"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    resultado = await base.get_json(_URL_BASE, "/recurso", {}, source="teste")
    assert resultado == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_conexao_caida_e_retryada_e_a_seguinte_passa():
    """O caso comum: a conexao cai, a proxima abre outra e funciona.

    E a forma mais frequente da instabilidade do /api/search do PNCP medida em
    2026-08-21 (1 falha em 5). Antes da v0.4.19 isso tambem funcionava, mas
    custava 2s de espera inutil no meio.
    """
    route = respx.get(f"{_URL_BASE}/recurso").mock(
        side_effect=[
            httpx.RemoteProtocolError("Server disconnected without sending a response"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    resultado = await base.get_json(_URL_BASE, "/recurso", {}, source="teste")
    assert resultado == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_conexao_caida_persistente_atribui_a_falha_a_origem():
    """Esgotadas as tentativas, a mensagem tem que dizer de quem e a culpa.

    Sem isso o texto que chega ao cliente MCP e indistinguivel de um defeito
    nosso — e foi assim que foi lido em 2026-08-21, quando um relatorio
    concluiu que "as ferramentas de pesquisa no PNCP estao indisponiveis" a
    partir de uma falha intermitente da origem. A tool nao esta indisponivel;
    a chamada daquele instante falhou.

    O que NAO se faz aqui: devolver lista vazia. Um resultado vazio se le como
    "nao existe nada", quando o que houve foi "nao consegui perguntar" — o
    falso negativo mais caro que este projeto pode produzir.
    """
    respx.get(f"{_URL_BASE}/recurso").mock(
        side_effect=httpx.RemoteProtocolError("Server disconnected")
    )
    with pytest.raises(UpstreamError) as exc:
        await base.get_json(_URL_BASE, "/recurso", {}, source="pncp")

    mensagem = str(exc.value)
    assert "pncp" in mensagem
    assert "INTERMITENTE" in mensagem
    assert "repetir" in mensagem.lower()


@respx.mock
async def test_429_e_retryado_ate_sucesso():
    route = respx.get(f"{_URL_BASE}/recurso").mock(
        side_effect=[
            httpx.Response(429, text="rate limited", headers={"Retry-After": "1"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    resultado = await base.get_json(_URL_BASE, "/recurso", {}, source="teste")
    assert resultado == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_5xx_persistente_estoura_upstream_error_apos_max_retries():
    route = respx.get(f"{_URL_BASE}/recurso").mock(
        return_value=httpx.Response(503, text="fora do ar")
    )
    with pytest.raises(UpstreamError) as excinfo:
        await base.get_json(_URL_BASE, "/recurso", {}, source="teste")
    assert excinfo.value.status_code == 503
    assert route.call_count == settings.http_max_retries


@respx.mock
async def test_4xx_de_validacao_nao_e_retryado():
    route = respx.get(f"{_URL_BASE}/recurso").mock(
        return_value=httpx.Response(400, text="parâmetro inválido")
    )
    with pytest.raises(UpstreamError) as excinfo:
        await base.get_json(_URL_BASE, "/recurso", {}, source="teste")
    assert excinfo.value.status_code == 400
    assert route.call_count == 1  # nenhuma re-tentativa


@respx.mock
async def test_corpo_vazio_em_200_vira_none_sem_json_decode_error():
    # A consulta consolidada de PJ do TCU devolve 200 com corpo VAZIO para
    # CNPJ inexistente/inválido — response.json() estouraria JSONDecodeError
    # cru. get_json trata isso como None (mesma semântica do 204), deixando
    # o chamador (ex.: tcu_client) converter em UpstreamError com mensagem clara.
    respx.get(f"{_URL_BASE}/vazio").mock(return_value=httpx.Response(200, text=""))
    resultado = await base.get_json(_URL_BASE, "/vazio", {}, source="teste")
    assert resultado is None


# --- timeout por-fonte -------------


async def test_timeout_por_chamada_e_encaminhado_ao_client(monkeypatch):
    """``timeout_seconds`` sobrescreve o timeout só desta chamada."""
    capturado = {}

    class _ClientStub:
        async def get(self, url, params=None, timeout=None):
            capturado["timeout"] = timeout
            return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(base, "_get_client", lambda: _ClientStub())

    # Com timeout explícito → repassado tal qual.
    r = await base.get_json(_URL_BASE, "/x", {}, source="teste", timeout_seconds=45.0)
    assert r == {"ok": True}
    assert capturado["timeout"] == 45.0

    # Sem timeout → usa o default do cliente (sentinela do httpx).
    await base.get_json(_URL_BASE, "/x", {}, source="teste")
    assert capturado["timeout"] is httpx.USE_CLIENT_DEFAULT


@respx.mock
async def test_cliente_compartilhado_e_reutilizado_no_mesmo_loop():
    respx.get(f"{_URL_BASE}/a").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{_URL_BASE}/b").mock(return_value=httpx.Response(200, json={}))
    await base.get_json(_URL_BASE, "/a", {}, source="teste")
    cliente_1 = base._get_client()
    await base.get_json(_URL_BASE, "/b", {}, source="teste")
    cliente_2 = base._get_client()
    assert cliente_1 is cliente_2


# --- _espera_retry (função pura, testada sem o patch do fixture) -----------


def test_espera_retry_respeita_retry_after_numerico_razoavel():
    # Usa o nome importado no topo do arquivo — o fixture autouse só troca o
    # atributo ``base._espera_retry`` (usado por get_json), não este binding.
    assert _espera_retry(1, "2") == 2.0
    assert _espera_retry(3, "0") == 0.0


def test_espera_retry_ignora_retry_after_excessivo_ou_invalido():
    # Acima do teto (30s) → backoff exponencial normal da 1ª tentativa.
    assert 0.5 <= _espera_retry(1, "9999") <= 0.5 * 1.25
    # Formato de data HTTP (não numérico) → backoff normal.
    assert 0.5 <= _espera_retry(1, "Wed, 21 Oct 2026 07:28:00 GMT") <= 0.5 * 1.25


def test_espera_retry_backoff_exponencial_com_jitter():
    assert 0.5 <= _espera_retry(1, None) <= 0.5 * 1.25
    assert 1.0 <= _espera_retry(2, None) <= 1.0 * 1.25
    assert 2.0 <= _espera_retry(3, None) <= 2.0 * 1.25


# --- Log com tipo da exceção ---------------------------------------
#
# Regressão: o warning de retry saía
# truncado ("...falhou para https://pncp.gov.br/api/search:" e nada depois)
# porque várias exceções de rede do httpx têm str() VAZIO. Sem o tipo, era
# impossível distinguir timeout de reset de conexão nos logs.


def test_descrever_excecao_inclui_tipo_quando_mensagem_vazia():
    from mcp_radardeprecos.clients.base import descrever_excecao

    # httpx.ReadError("") é o caso REAL que gerou o log truncado.
    assert descrever_excecao(httpx.ReadError("")) == "ReadError"
    assert descrever_excecao(httpx.ConnectError("")) == "ConnectError"


def test_descrever_excecao_inclui_tipo_e_mensagem_quando_ha_texto():
    from mcp_radardeprecos.clients.base import descrever_excecao

    assert descrever_excecao(httpx.ReadTimeout("timed out")) == "ReadTimeout: timed out"


@respx.mock
async def test_log_de_retry_mostra_tipo_da_excecao_sem_mensagem(caplog):
    """Regressão direta do log truncado visto em produção."""
    respx.get(f"{_URL_BASE}/recurso").mock(side_effect=httpx.ReadError(""))

    with caplog.at_level(logging.WARNING, logger="mcp_radardeprecos.clients.base"):
        with pytest.raises(UpstreamError) as excinfo:
            await base.get_json(_URL_BASE, "/recurso", {}, source="teste")

    # O warning de cada tentativa agora identifica o tipo:
    mensagens = [r.getMessage() for r in caplog.records]
    assert any("ReadError" in m for m in mensagens), mensagens
    # E não termina mais em ":" seguido de nada:
    assert not any(m.rstrip().endswith(":") for m in mensagens), mensagens
    # A exceção final propagada também carrega o tipo:
    assert "ReadError" in str(excinfo.value)


def test_espera_retry_usa_backoff_mais_longo_para_falha_de_leitura():
    """ReadError/ReadTimeout = servidor lento, não indisponível.

    Com a base curta as 3 tentativas cabiam em ~1,5s e caíam todas na mesma
    janela ruim — foi o que fez o /api/search do PNCP falhar de vez em quando.
    """
    curto = _espera_retry(1, None, erro=httpx.ConnectError("recusou"))
    longo = _espera_retry(1, None, erro=httpx.ReadError("interrompeu"))

    assert 0.5 <= curto <= 0.5 * 1.25
    assert 2.0 <= longo <= 2.0 * 1.25
    assert longo > curto

    # Cresce exponencialmente a partir da base maior — 2, 4, e a 3a seria 8s,
    # mas a v0.4.19 passou a limitar cada espera a _ESPERA_MAX_SEGUNDOS.
    assert 4.0 <= _espera_retry(2, None, erro=httpx.ReadTimeout("demorou")) <= 4.0 * 1.25
    assert 6.0 <= _espera_retry(3, None, erro=httpx.ReadTimeout("demorou")) <= 6.0 * 1.25


def test_espera_retry_sem_erro_mantem_o_backoff_curto():
    # Chamada legada (status transitório 429/503): base 0.5s, como antes.
    assert 0.5 <= _espera_retry(1, None) <= 0.5 * 1.25


def test_retry_after_tem_prioridade_mesmo_em_falha_de_leitura():
    assert _espera_retry(1, "3", erro=httpx.ReadError("x")) == 3.0


def test_espera_retry_repete_rapido_quando_a_conexao_caiu():
    """RemoteProtocolError pede conexao NOVA, nao espera.

    Este teste substitui um que afirmava o contrario. Da v0.4.15 a v0.4.18 a
    excecao era classificada como "servidor lento" e recebia backoff de 2s,
    por analogia com ReadError/ReadTimeout. A analogia era so plausivel, nunca
    medida.

    A medicao veio em 2026-08-21, direto da maquina do usuario, sem proxy
    no caminho: 5 chamadas identicas ao /api/search do PNCP, 1
    falhou. As 4 boas responderam em 219-489ms; a ruim levou 1066ms e nao
    trouxe nada. Servidor lento devolve devagar — este nao devolveu. O que
    cai aqui e a conexao, e conexao morta nao melhora com espera.

    Primeira repeticao curta, portanto. E o exponencial fica mais agressivo
    (fator 4) para que a ULTIMA tentativa ainda escape de uma janela ruim de
    poucos segundos na origem — que foi o que produziu 3 falhas seguidas em
    producao numa origem que, medida isoladamente, falha 1 em 5.
    """
    caiu = _espera_retry(1, None, erro=httpx.RemoteProtocolError("disconnected"))
    recusou = _espera_retry(1, None, erro=httpx.ConnectError("recusou"))
    lento = _espera_retry(1, None, erro=httpx.ReadError("interrompeu"))

    assert 0.2 <= caiu <= 0.2 * 1.25
    assert caiu < recusou < lento


def test_espera_retry_espalha_as_tentativas_de_conexao_caida():
    """O fator 4 existe para a 3a tentativa cair FORA de uma janela ruim.

    Com o fator 2 das outras familias as tres esperas somariam menos de 1,5s
    e cairiam todas dentro da mesma janela de instabilidade — retentar rapido
    resolve conexao morta e nao resolve origem indisponivel por alguns
    segundos. As duas causas produzem a mesma excecao, e o backoff precisa
    cobrir as duas.
    """
    erro = httpx.RemoteProtocolError("disconnected")
    esperas = [_espera_retry(n, None, erro=erro) for n in (1, 2, 3)]

    assert 0.2 <= esperas[0] <= 0.2 * 1.25
    assert 0.8 <= esperas[1] <= 0.8 * 1.25
    assert 3.2 <= esperas[2] <= 3.2 * 1.25
    # A ultima sozinha ja supera a soma das anteriores: e o que tira a
    # tentativa final da janela onde as primeiras falharam.
    assert esperas[2] > esperas[0] + esperas[1]


def test_espera_retry_tem_teto_por_tentativa():
    """Sem teto, aumentar as tentativas trocaria falha rapida por travamento.

    Com fator 4, a 4a espera da familia de conexao seria 12,8s e a 5a, 51s —
    o cliente MCP desistiria no meio e o usuario nao receberia nem erro nem
    resposta. O teto e o que torna seguro subir http_max_retries para
    absorver uma origem que falha entre 1 em 5 e 3 em 8 das chamadas.
    """
    from mcp_radardeprecos.clients.base import _ESPERA_MAX_SEGUNDOS

    for erro in (
        httpx.RemoteProtocolError("caiu"),
        httpx.ReadError("interrompeu"),
        httpx.ConnectError("recusou"),
    ):
        for n in (4, 5, 8):
            assert _espera_retry(n, None, erro=erro) <= _ESPERA_MAX_SEGUNDOS * 1.25


@respx.mock
async def test_cliente_envia_user_agent_configurado():
    """O User-Agent e FUNCIONAL, nao cosmetico.

    Medido em 2026-08-21, 10 rodadas INTERCALADAS contra o /api/search do
    PNCP — mesma URL, mesma maquina, mesmo instante:

        Mozilla/5.0 (navegador) .... 10/10 ok
        python-urllib/3.x ..........  3/10 ok  (ConnectionResetError)
        python-httpx/0.27.0 ........  3/10 ok  (ConnectionResetError)

    Uma protecao anti-bot derrubava a conexao pelo header. Era a causa real
    das "falhas de rede intermitentes do PNCP" que passamos o dia tratando
    com backoff: 70% das nossas chamadas eram recusadas antes de chegar ao
    indice.

    Este teste existe para que ninguem remova o header achando que e enfeite.
    """
    route = respx.get(f"{_URL_BASE}/recurso").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    await base.get_json(_URL_BASE, "/recurso", {}, source="teste")

    enviado = route.calls[0].request.headers["user-agent"]
    assert enviado == settings.http_user_agent
    # Prefixo Mozilla: e o que a verificacao anti-bot procura.
    assert enviado.startswith("Mozilla/5.0")
    # ...mas sem mentir: o nome do projeto tem que estar la, para quem opera
    # o PNCP saber quem esta chamando.
    assert "mcp-radardeprecos" in enviado


def test_user_agent_padrao_identifica_o_projeto_e_a_versao():
    """O UA precisa ter FORMA de navegador E dizer quem esta chamando.

    As duas exigencias vem de medicao, nao de gosto (2026-08-21, 3 rodadas
    intercaladas, 10 chamadas cada):

        navegador puro .................. 10/10, 10/10, 10/10
        navegador + identificacao ....... 10/10
        '(compatible; projeto/versao)' ..  1/10,  4/10
        python-httpx/0.27.0 .............  3/10,  3/10, 4/10
        Python-urllib/3.x ...............  3/10,  1/10, 8/10

    Formas com aparencia de navegador: 40/40. Todas as demais: 27/80. O filtro
    do PNCP nao faz checagem de prefixo — '(compatible;' e justamente o que
    anuncia bot, e por isso a primeira tentativa de correcao ficou PIOR que o
    problema que tentava resolver.

    A identificacao anexada ao final e o que impede que a requisicao se passe
    silenciosamente por uma pessoa num navegador: quem administra o PNCP ve no
    log o nome do projeto e onde reclamar.
    """
    from mcp_radardeprecos import __version__

    ua = settings.http_user_agent
    assert ua.startswith("Mozilla/5.0 (Windows NT")  # forma de navegador
    assert "mcp-radardeprecos" in ua  # ...sem esconder quem chama
    assert __version__ in ua
    assert "+https://" in ua  # url de contato
