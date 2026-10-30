"""Trilha de auditoria reprodutível: proveniência das chamadas upstream.

Objetivo: tornar uma pesquisa de
preços DEFENSÁVEL e RECONSTRUÍVEL — para cada acesso a uma fonte pública
(PNCP, Compras.gov.br, Banco Central, Receita, TCU) registra-se, em memória:
qual tool disparou, a URL e os parâmetros exatos, o timestamp UTC, o status e
um **hash SHA-256 da resposta bruta** (prova de integridade: "foi ISTO que a
fonte devolveu naquele instante").

**Zero dependência nova** e mesmo espírito de ``observability.py`` (contadores
em memória, sem persistência): a captura acontece nos dois pontos que já veem
tudo — o cliente HTTP (:func:`clients.base.get_json`, que faz a requisição) e
o wrapper único de tools (``server._registrar_tool``, que sabe qual tool está
executando). A ligação entre os dois é um :class:`contextvars.ContextVar`:
o wrapper marca a "tool atual" e o ``get_json`` a lê ao registrar. ContextVars
são isolados por *task* async, então isto é seguro sob atendimento
concorrente (transportes HTTP), sem misturar chamadas de usuários diferentes
numa mesma requisição.

Limitações honestas (iguais às de ``observability.py``): é memória de processo
— reinicia zerado a cada deploy/hibernação; num servidor HTTP compartilhado, a
trilha global intercala chamadas de várias sessões (por isso o dossiê traz
timestamps e o filtro por janela, e o uso ideal é stdio/local ou exportar ao
fim de cada pesquisa). Para retenção de verdade, ver os logs estruturados com
``request_id`` (``logging_utils.py``).
"""
from __future__ import annotations

import hashlib
import threading
from collections import deque
from collections.abc import Mapping
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any

# Tool MCP atualmente em execução — setada pelo wrapper server._registrar_tool
# e lida por get_json ao registrar a proveniência. ContextVar é isolado por
# task async: uma requisição concorrente não vê a "tool atual" de outra.
_tool_atual: ContextVar[str | None] = ContextVar("mcp_radardeprecos_tool_atual", default=None)

#: Teto de registros mantidos em memória (descarta os mais antigos). Igual em
#: espírito ao teto do cache: um processo HTTP de longa duração não pode
#: crescer sem limite. Uma varredura ampla (ex.: descobrir material ~79
#: chamadas) cabe com folga; pesquisas muito longas perdem os registros
#: iniciais — exporte o dossiê ao final de cada pesquisa.
_MAX_REGISTROS = 5000

_lock = threading.Lock()
_registros: deque[dict[str, Any]] = deque(maxlen=_MAX_REGISTROS)


def definir_tool_atual(nome: str | None) -> Token:
    """Marca a tool em execução no contexto async atual. Devolve o token p/ reset."""
    return _tool_atual.set(nome)


def limpar_tool_atual(token: Token) -> None:
    """Restaura a tool anterior (chamado no finally do wrapper de tools)."""
    _tool_atual.reset(token)


def registrar_upstream(
    *,
    source: str,
    url: str,
    params: Mapping[str, Any] | None = None,
    status: int | None,
    corpo: bytes | None,
) -> None:
    """Registra UMA requisição a uma fonte upstream (chamado por get_json).

    Nunca levanta exceção (auditoria não pode derrubar uma consulta). O hash é
    SHA-256 do corpo bruto exatamente como recebido — é a prova de integridade.
    """
    try:
        registro = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "tool": _tool_atual.get(),
            "fonte": source,
            "url": url,
            "params": {k: v for k, v in dict(params or {}).items() if v is not None},
            "status": status,
            "resposta_hash_sha256": (
                hashlib.sha256(corpo).hexdigest() if corpo else None
            ),
            "resposta_bytes": len(corpo) if corpo else 0,
        }
        with _lock:
            _registros.append(registro)
    except Exception:  # pragma: no cover - auditoria é best-effort, nunca quebra a consulta
        pass


def obter_trilha(
    limite: int | None = None, desde_iso: str | None = None
) -> list[dict[str, Any]]:
    """Devolve os registros de proveniência (mais recentes por último).

    Args:
        limite: se informado, devolve só os ``limite`` registros mais recentes.
        desde_iso: se informado (timestamp ISO UTC), só registros a partir dele
            — útil para recortar a janela de UMA pesquisa num servidor
            compartilhado.
    """
    with _lock:
        registros = list(_registros)
    if desde_iso:
        registros = [r for r in registros if r["timestamp_utc"] >= desde_iso]
    if limite is not None and limite >= 0:
        registros = registros[-limite:]
    return registros


def hash_reprodutibilidade(registros: list[dict[str, Any]]) -> str:
    """Hash SHA-256 que identifica unicamente este conjunto de acessos.

    Combina, em ordem, ``fonte|url|params|status|resposta_hash`` de cada
    registro — dois dossiês com o mesmo hash consultaram exatamente as mesmas
    fontes e obtiveram exatamente as mesmas respostas.
    """
    h = hashlib.sha256()
    for r in registros:
        chave = (
            f"{r.get('fonte')}|{r.get('url')}|{sorted((r.get('params') or {}).items())}"
            f"|{r.get('status')}|{r.get('resposta_hash_sha256')}"
        )
        h.update(chave.encode("utf-8"))
    return h.hexdigest()


def resetar() -> None:
    """Zera a trilha em memória (usado em testes e entre pesquisas, se desejado)."""
    with _lock:
        _registros.clear()
