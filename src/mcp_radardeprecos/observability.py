"""Observabilidade mínima: contadores em memória por tool, fonte e cliente.

Sem dependência externa. Alimentado pelo wrapper único
``server._registrar_tool``, exposto no health check (``GET /``) e, quando
configurado, no formato Prometheus (``metricas_prometheus.py``).

- Nada por usuário ou IP. O "cliente" é o nome do software MCP (Claude,
  ChatGPT…) que ele próprio informa no handshake.
- Sem persistência: zera a cada reinício. Para histórico, use os logs
  estruturados (``request_id``, ver ``logging_utils.py``).
- p95 sobre uma janela limitada de amostras (:data:`_MAX_AMOSTRAS_DURACAO`),
  para a memória não crescer num processo de longa duração.
"""
from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .config import settings

# Amostras de duração mantidas por tool, para o cálculo de p95 — limitado
# para não crescer sem limite num processo de longa duração (servidor
# HTTP). 500 amostras é suficiente para uma estimativa razoável de p95 sem
# custo de memória relevante.
_MAX_AMOSTRAS_DURACAO = 500

_lock = threading.Lock()
_chamadas: dict[str, int] = {}
_erros: dict[str, int] = {}
_duracoes: dict[str, deque[float]] = {}


def registrar_chamada(nome_tool: str, duracao_segundos: float, sucesso: bool) -> None:
    """Registra uma chamada concluída de ``nome_tool``.

    Chamado pelo wrapper único de registro de tools (``server._registrar_tool``)
    depois de cada chamada, com sucesso ou falha — thread-safe (``threading.Lock``),
    porque o transporte HTTP (``sse``/``streamable-http``) pode atender
    requisições concorrentes de clientes diferentes na mesma instância do
    processo.

    Args:
        nome_tool: Nome MCP da tool (``func.__name__``).
        duracao_segundos: Duração da chamada, em segundos.
        sucesso: ``False`` se a chamada terminou em exceção.
    """
    with _lock:
        _chamadas[nome_tool] = _chamadas.get(nome_tool, 0) + 1
        if not sucesso:
            _erros[nome_tool] = _erros.get(nome_tool, 0) + 1
        amostras = _duracoes.setdefault(nome_tool, deque(maxlen=_MAX_AMOSTRAS_DURACAO))
        amostras.append(duracao_segundos)


def obter_metricas() -> dict[str, dict[str, Any]]:
    """Devolve um resumo agregado por tool, para exposição no health check.

    Returns:
        Dicionário ``{nome_tool: {chamadas, erros, duracao_media_ms,
        duracao_p95_ms}}``, ordenado por nome de tool. Tools nunca chamadas
        desde o início do processo não aparecem (em vez de aparecer com
        contadores zerados) — mantém a resposta enxuta.
    """
    with _lock:
        resultado: dict[str, dict[str, Any]] = {}
        for nome, total in sorted(_chamadas.items()):
            amostras = list(_duracoes.get(nome, ()))
            duracao_media_ms = (sum(amostras) / len(amostras) * 1000) if amostras else 0.0
            duracao_p95_ms = _percentil(amostras, 0.95) * 1000
            resultado[nome] = {
                "chamadas": total,
                "erros": _erros.get(nome, 0),
                "duracao_media_ms": round(duracao_media_ms, 2),
                "duracao_p95_ms": round(duracao_p95_ms, 2),
            }
        return resultado


def _percentil(amostras: list[float], p: float) -> float:
    """Percentil ``p`` (0–1) de ``amostras`` por interpolação linear entre os
    dois índices mais próximos (mesmo método 'linear' do ``numpy.percentile``)
    — sem dependência externa (evita ``numpy`` só para isto).

    Arredondar para o índice mais próximo (em vez de interpolar) sub-representa
    a cauda em amostras pequenas: com 20 amostras e 1 outlier no topo,
    ``round(0.95 * 19) == 18`` aponta para o penúltimo valor, não o último —
    o outlier fica de fora do p95 mesmo sendo exatamente o top 5% da amostra.
    """
    if not amostras:
        return 0.0
    dados_ordenados = sorted(amostras)
    posicao = p * (len(dados_ordenados) - 1)
    indice_baixo = int(posicao)
    indice_alto = min(indice_baixo + 1, len(dados_ordenados) - 1)
    fracao = posicao - indice_baixo
    return dados_ordenados[indice_baixo] + fracao * (dados_ordenados[indice_alto] - dados_ordenados[indice_baixo])


def resetar() -> None:
    """Zera todos os contadores em memória.

    Usado apenas em testes, para isolar o estado global entre casos de
    teste (os contadores são deliberadamente um módulo-nível singleton, não
    uma instância injetável, porque o wrapper de registro em ``server.py``
    é criado uma única vez na importação do módulo).
    """
    with _lock:
        _chamadas.clear()
        _erros.clear()
        _duracoes.clear()
        _fontes.clear()
        _sessoes.clear()
        # Sem isto, um teste que reseta as métricas herdaria a contagem de
        # protocolo do caso anterior — dado velho apresentado como medição,
        # que é exatamente o que este módulo existe para evitar.
        _protocolos.clear()
        _clientes.clear()
    global _sessoes_descartadas, _sessoes_vistas
    _sessoes_descartadas = 0
    _sessoes_vistas = 0


# ===========================================================================
# Fontes externas, sessões e visão consolidada.
#
# `obter_metricas()` mantém o formato achatado por tool, lido pelo health
# check; a visão completa sai em `obter_metricas_completas()`.
# ===========================================================================

#: Métricas por fonte externa (PNCP, Compras.gov.br, TCU, BPS).
_fontes: dict[str, dict[str, Any]] = {}

#: Sessões MCP distintas, em ordem de chegada — a mais antiga sai primeiro
#: quando o teto é atingido.
_sessoes: OrderedDict[str, int] = OrderedDict()
_sessoes_descartadas = 0
#: Sessões distintas vistas desde o início do processo, inclusive as que já
#: saíram da memória — base do contador monotônico do Prometheus.
_sessoes_vistas = 0

#: Chamadas e sessões por cliente MCP (nome informado no handshake).
_clientes: dict[str, dict[str, int]] = {}
#: Teto de nomes distintos: um cliente com nome aleatório não pode inflar as
#: séries de métricas. Os excedentes entram em :data:`_CLIENTE_OUTROS`.
_MAX_CLIENTES = 30
_CLIENTE_OUTROS = "(outros)"
_CLIENTE_DESCONHECIDO = "(desconhecido)"
_CARACTERES_CLIENTE = re.compile(r"[^A-Za-z0-9 ._-]")

_inicio_processo = time.time()


class _AcessoAoContextoMCP:
    """Acesso tardio ao ``FastMCP`` do servidor, para não criar import circular.

    ``server.py`` importa este módulo; importá-lo de volta no topo fecharia o
    ciclo. A resolução acontece na primeira chamada e é memorizada.
    """

    _mcp: Any = None

    def get_context(self) -> Any:
        if self._mcp is None:
            from .server import mcp  # import tardio, deliberado

            self._mcp = mcp
        return self._mcp.get_context()


mcp_server_module = _AcessoAoContextoMCP()


def registrar_upstream(
    fonte: str,
    duracao_segundos: float,
    sucesso: bool,
    tentativas: int = 1,
) -> None:
    """Registra uma chamada LÓGICA a uma fonte externa.

    ``tentativas`` é o número de requisições HTTP que a chamada consumiu —
    e é o dado que faltava até aqui.

    Uma chamada que falha duas vezes e acerta na terceira conta como UM
    sucesso: do ponto de vista da ferramenta, funcionou. A instabilidade da
    origem fica invisível justamente quando a política de retry está fazendo
    seu trabalho. Foi o que aconteceu em 2026-08-21, quando cerca de 70% das
    chamadas ao PNCP eram recusadas e o problema só aparecia quando as três
    tentativas falhavam juntas.

    Com ``tentativas_media`` acima de 1,0, a origem se denuncia antes de
    virar erro visível ao usuário.
    """
    with _lock:
        reg = _fontes.setdefault(
            fonte,
            {"chamadas": 0, "erros": 0, "tentativas": 0, "duracoes": deque(maxlen=_MAX_AMOSTRAS_DURACAO)},
        )
        reg["chamadas"] += 1
        if not sucesso:
            reg["erros"] += 1
        reg["tentativas"] += max(1, tentativas)
        reg["duracoes"].append(duracao_segundos)


#: Versões de protocolo MCP negociadas, com a contagem de chamadas de cada uma.
_protocolos: dict[str, int] = {}


def sessao_atual() -> str | None:
    """Identificador da sessão MCP corrente, lido na camada MCP (não no ASGI).

    Ler o cabeçalho ``Mcp-Session-Id`` num middleware não funciona: o
    ``StreamableHTTPSessionManager`` processa as chamadas de tool numa task
    criada no ``initialize``, antes de existir sessão. Por isso o
    identificador deriva do objeto ``ServerSession`` — estável enquanto a
    sessão vive e disponível também em transportes sem esse cabeçalho. A
    métrica conta sessões distintas; o valor em si não importa.
    """
    try:
        sessao = mcp_server_module.get_context().request_context.session
    except Exception:  # noqa: BLE001 - fora de contexto MCP (stdio, testes)
        return None
    return f"s{id(sessao):x}"


def protocolo_atual() -> str | None:
    """Versão de protocolo MCP negociada no ``initialize`` desta sessão.

    Serve para separar clientes que usam sessão de clientes sessionless sem
    depender de inferência. Enquanto este campo não existia, "zero sessões"
    admitia duas leituras incompatíveis e nenhuma verificável.
    """
    try:
        sessao = mcp_server_module.get_context().request_context.session
        return getattr(getattr(sessao, "client_params", None), "protocolVersion", None)
    except Exception:  # noqa: BLE001
        return None


def registrar_protocolo(versao: str | None) -> None:
    """Conta uma chamada por versão de protocolo negociada."""
    chave = versao or "(sem initialize/stdio)"
    with _lock:
        _protocolos[chave] = _protocolos.get(chave, 0) + 1


def registrar_sessao(sessao: str | None, nome_tool: str) -> bool:
    """Conta uma chamada na sessão MCP informada; ``True`` se a sessão é nova.

    ``None`` não cria registro: o transporte ``stdio`` não tem sessão HTTP, e
    inventar uma produziria uma contagem que não corresponde a nada.
    """
    if not sessao:
        return False
    global _sessoes_descartadas, _sessoes_vistas
    with _lock:
        if sessao in _sessoes:
            _sessoes[sessao] += 1
            _sessoes.move_to_end(sessao)
            return False
        _sessoes[sessao] = 1
        _sessoes_vistas += 1
        while len(_sessoes) > settings.observabilidade_max_sessoes:
            _sessoes.popitem(last=False)
            _sessoes_descartadas += 1
        return True


def cliente_atual() -> str | None:
    """Nome do cliente MCP desta sessão, como ele mesmo informou no ``initialize``."""
    try:
        sessao = mcp_server_module.get_context().request_context.session
        info = getattr(getattr(sessao, "client_params", None), "clientInfo", None)
        return getattr(info, "name", None)
    except Exception:  # noqa: BLE001 - fora de contexto MCP (stdio, testes)
        return None


def normalizar_cliente(nome: str | None) -> str:
    """Nome de cliente seguro para rótulo: só caracteres comuns, até 40."""
    limpo = _CARACTERES_CLIENTE.sub("", str(nome or "")).strip()[:40]
    return limpo or _CLIENTE_DESCONHECIDO


def registrar_cliente(nome: str | None, nova_sessao: bool) -> None:
    """Conta uma chamada (e, se for o caso, uma sessão nova) para o cliente MCP."""
    chave = normalizar_cliente(nome)
    with _lock:
        if chave not in _clientes and len(_clientes) >= _MAX_CLIENTES:
            chave = _CLIENTE_OUTROS
        reg = _clientes.setdefault(chave, {"chamadas": 0, "sessoes": 0})
        reg["chamadas"] += 1
        if nova_sessao:
            reg["sessoes"] += 1


def instantaneo_prometheus() -> dict[str, Any]:
    """Contadores brutos para exportação: totais monotônicos e percentis.

    Separado de :func:`obter_metricas_completas`, que é contrato do health
    check e traz médias e taxas já calculadas — o Prometheus precisa dos
    totais para calcular taxas por conta própria.
    """
    with _lock:
        tools = {
            nome: {
                "chamadas": total,
                "erros": _erros.get(nome, 0),
                "p50": _percentil_ou_none(list(_duracoes.get(nome, ())), 0.5),
                "p95": _percentil_ou_none(list(_duracoes.get(nome, ())), 0.95),
            }
            for nome, total in _chamadas.items()
        }
        fontes = {
            fonte: {
                "chamadas": reg["chamadas"],
                "erros": reg["erros"],
                "tentativas": reg["tentativas"],
                "p50": _percentil_ou_none(list(reg["duracoes"]), 0.5),
                "p95": _percentil_ou_none(list(reg["duracoes"]), 0.95),
            }
            for fonte, reg in _fontes.items()
        }
        return {
            "versao": __version__,
            "inicio_processo": _inicio_processo,
            "tools": tools,
            "fontes": fontes,
            "clientes": {nome: dict(reg) for nome, reg in _clientes.items()},
            "protocolos": dict(_protocolos),
            "sessoes_em_memoria": len(_sessoes),
            "sessoes_vistas": _sessoes_vistas,
        }


def _percentil_ou_none(amostras: list[float], p: float) -> float | None:
    """Percentil que devolve ``None`` quando não há amostra.

    Diferente de ``_percentil``, que devolve ``0.0`` por compatibilidade com
    o formato antigo. Zero, num campo de latência, lê-se como "respondeu
    instantaneamente" — uma afirmação falsa. ``None`` deixa explícito que
    não há dado, em vez de inventar um número que parece medição.
    """
    if not amostras:
        return None
    return _percentil(amostras, p)


def obter_metricas_completas() -> dict[str, Any]:
    """Visão consolidada: processo, totais, ferramentas, fontes e sessões.

    Não substitui ``obter_metricas()`` — ver o comentário no início desta
    seção. Serve a quem precisa do quadro completo, incluindo a saúde das
    origens externas.
    """
    with _lock:
        por_ferramenta = {}
        for nome, total in sorted(_chamadas.items()):
            amostras = list(_duracoes.get(nome, ()))
            erros = _erros.get(nome, 0)
            por_ferramenta[nome] = {
                "chamadas": total,
                "erros": erros,
                "taxa_erro": round(erros / total, 4) if total else 0.0,
                "duracao_p50_s": _percentil_ou_none(amostras, 0.5),
                "duracao_p95_s": _percentil_ou_none(amostras, 0.95),
            }

        por_fonte = {}
        for fonte, reg in sorted(_fontes.items()):
            total = reg["chamadas"]
            amostras = list(reg["duracoes"])
            por_fonte[fonte] = {
                "chamadas": total,
                "erros": reg["erros"],
                "taxa_erro": round(reg["erros"] / total, 4) if total else 0.0,
                "tentativas_media": round(reg["tentativas"] / total, 2) if total else None,
                "duracao_p50_s": _percentil_ou_none(amostras, 0.5),
                "duracao_p95_s": _percentil_ou_none(amostras, 0.95),
            }

        chamadas_por_sessao = list(_sessoes.values())
        total_chamadas = sum(_chamadas.values())
        total_erros = sum(_erros.values())
        descartadas = _sessoes_descartadas
        protocolos = dict(_protocolos)
        clientes = {nome: dict(reg) for nome, reg in sorted(_clientes.items())}

    avisos = [
        "As sessões contam CONVERSAS MCP distintas, NÃO pessoas nem "
        "organizações: uma pessoa pode abrir várias sessões, e uma sessão pode "
        "ser compartilhada. Não é indicador de alcance.",
        "As métricas vivem em MEMÓRIA do processo e zeram a cada reinício ou "
        "implantação. Representam o estado da instância, não série histórica.",
    ]
    if not total_chamadas:
        avisos.append(
            "Nenhuma chamada registrada desde o início do processo — o conjunto "
            "vazio é o estado normal de uma instância recém-iniciada, não defeito."
        )
    if descartadas:
        avisos.append(
            f"{descartadas} sessão(ões) saíram da memória por limite "
            f"({settings.observabilidade_max_sessoes}); as médias por sessão "
            "refletem apenas as retidas."
        )

    return {
        "processo": {
            "versao": __version__,
            "inicio": datetime.fromtimestamp(_inicio_processo, tz=timezone.utc).isoformat(),
            "em_execucao_segundos": round(time.time() - _inicio_processo, 1),
        },
        "totais": {
            "chamadas": total_chamadas,
            "erros": total_erros,
            "taxa_erro": round(total_erros / total_chamadas, 4) if total_chamadas else 0.0,
        },
        "por_ferramenta": por_ferramenta,
        "por_fonte_externa": por_fonte,
        # Sem `por_protocolo`, "zero sessões" admitia duas leituras
        # incompatíveis — cliente sessionless, ou defeito nosso de leitura — e
        # nenhuma verificável. Era o caso até a v0.5.11, e a segunda leitura é
        # que estava certa.
        "por_protocolo": dict(protocolos),
        "por_cliente": clientes,
        "sessoes": {
            "distintas_em_memoria": len(chamadas_por_sessao),
            "descartadas_por_limite": descartadas,
            "chamadas_por_sessao": {
                "minimo": min(chamadas_por_sessao) if chamadas_por_sessao else None,
                "maximo": max(chamadas_por_sessao) if chamadas_por_sessao else None,
                "media": round(sum(chamadas_por_sessao) / len(chamadas_por_sessao), 2)
                if chamadas_por_sessao
                else None,
            },
        },
        "avisos": avisos,
    }

