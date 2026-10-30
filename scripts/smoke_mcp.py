"""Teste de fumaça de um servidor MCP publicado, pelo protocolo real.

Por que existe: um ``curl`` na raiz (``/``) responde 200 mesmo quando o MCP
está quebrado — foi assim que uma imagem com ``ModuleNotFoundError`` passou
por saudável durante dois dias, com o pod novo em CrashLoop e o antigo
servindo. O health check diz que o processo subiu; ele não diz que o
protocolo funciona, que as tools estão registradas nem que as chamadas
chegam às APIs externas.

Este script faz o caminho completo que um cliente MCP faria:

1. ``initialize``      — devolve ``serverInfo.version`` e o ``Mcp-Session-Id``
2. ``notifications/initialized`` — sem isso o servidor recusa o resto
3. ``tools/list``      — quantas tools o servidor realmente expõe
4. uma tool PURA       — exercita o servidor sem depender de rede externa
5. uma tool de REDE    — exercita a saída para o PNCP (proxy, allowlist, DNS)

O passo 4 separa dois problemas que se confundem: se ele passa e o 5 falha,
o servidor está bem e o que está quebrado é a saída de rede do ambiente.

Só usa a biblioteca padrão — roda em qualquer Python 3.10+ sem instalar nada.

Uso:
    python scripts/smoke_mcp.py https://seu-servidor.exemplo.gov.br
    python scripts/smoke_mcp.py <url> --insecure    # CA corporativa não confiável
"""
from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.error
import urllib.request

TIMEOUT = 120  # varreduras no PNCP podem passar de 60s


class Cliente:
    def __init__(self, base: str, inseguro: bool = False) -> None:
        self.url = base.rstrip("/") + "/mcp"
        self.sessao: str | None = None
        self.ctx = ssl._create_unverified_context() if inseguro else None
        self._id = 0

    def _chamar(self, metodo: str, params: dict | None = None, notificacao: bool = False):
        corpo: dict = {"jsonrpc": "2.0", "method": metodo}
        if params is not None:
            corpo["params"] = params
        if not notificacao:
            self._id += 1
            corpo["id"] = self._id

        req = urllib.request.Request(
            self.url,
            data=json.dumps(corpo).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                # Os DOIS tipos: sem text/event-stream o servidor devolve 406.
                "Accept": "application/json, text/event-stream",
                **({"Mcp-Session-Id": self.sessao} if self.sessao else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=self.ctx) as r:
            if self.sessao is None:
                self.sessao = r.headers.get("mcp-session-id")
            bruto = r.read().decode("utf-8", "replace")

        if notificacao:
            return None
        # A resposta vem como SSE: linhas "event:" e "data:".
        for linha in bruto.splitlines():
            if linha.startswith("data:"):
                return json.loads(linha[len("data:"):].strip())
        raise RuntimeError(f"resposta sem frame SSE: {bruto[:300]!r}")


def _ok(rotulo: str, detalhe: str = "", segundos: float | None = None) -> None:
    tempo = f"  ({segundos:.1f}s)" if segundos is not None else ""
    print(f"  OK   {rotulo}{': ' + detalhe if detalhe else ''}{tempo}")


def _falha(rotulo: str, erro: object, segundos: float | None = None) -> None:
    # O tempo importa tanto quanto a mensagem: uma falha em menos de 2s é
    # recusa (proxy fechou o túnel, DNS, allowlist); uma falha perto do
    # timeout é lentidão da origem. A mesma RemoteProtocolError aparece nos
    # dois casos, e sem o relógio não dá para distinguir.
    tempo = f"  ({segundos:.1f}s)" if segundos is not None else ""
    print(f"  FALHA {rotulo}{tempo}: {erro}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url", help="base do servidor, sem /mcp")
    p.add_argument("--insecure", action="store_true", help="ignora validação de certificado")
    p.add_argument(
        "--tentativas",
        type=int,
        default=3,
        help="quantas vezes repetir a tool de rede antes de desistir (padrão 3); "
             "existe porque o /api/search do PNCP falha de forma intermitente",
    )
    args = p.parse_args(argv)
    args.tentativas = max(1, args.tentativas)

    print(f"\nTestando {args.url}\n")
    c = Cliente(args.url, args.insecure)
    problemas = 0

    # 1. handshake
    try:
        t = time.monotonic()
        r = c._chamar("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke_mcp", "version": "1"},
        })
        info = r["result"]["serverInfo"]
        _ok("initialize", f"{info['name']} {info['version']}", time.monotonic() - t)
        if not c.sessao:
            print("  AVISO: servidor não devolveu Mcp-Session-Id")
        # A versão do SDK aparecendo aqui significa que o servidor não passou
        # a própria versão ao FastMCP (corrigido na v0.4.14/0.5.4).
        if info["version"].startswith("1."):
            print(f"  AVISO: versão {info['version']} parece ser a do SDK, não a do projeto")
    except Exception as exc:  # noqa: BLE001
        _falha("initialize", exc)
        return 1

    c._chamar("notifications/initialized", notificacao=True)

    # 2. inventário de tools
    try:
        t = time.monotonic()
        r = c._chamar("tools/list")
        tools = [x["name"] for x in r["result"]["tools"]]
        _ok("tools/list", f"{len(tools)} tools", time.monotonic() - t)
    except Exception as exc:  # noqa: BLE001
        _falha("tools/list", exc)
        return 1

    # 3. tool PURA — não sai para a rede; isola servidor de conectividade
    if "consultar_tabelas_dominio_pncp" in tools:
        try:
            t = time.monotonic()
            r = c._chamar("tools/call", {
                "name": "consultar_tabelas_dominio_pncp",
                "arguments": {"tabela": "modalidade_contratacao"},
            })
            decorrido = time.monotonic() - t
            erro = r.get("result", {}).get("isError")
            if erro:
                _falha("tool pura", r["result"], decorrido)
            else:
                _ok("tool pura", "sem rede externa", decorrido)
            problemas += bool(erro)
        except Exception as exc:  # noqa: BLE001
            _falha("tool pura", exc, time.monotonic() - t)
            problemas += 1

    # 4. tool de REDE — valida saída para o PNCP (proxy/allowlist/DNS)
    #
    # Repete até `args.tentativas` vezes porque o /api/search do PNCP falha de
    # forma INTERMITENTE: em 2026-08-21 a mesma chamada passou em 2,9s e, meia
    # hora depois, falhou com RemoteProtocolError. Uma execução única não
    # distingue "quebrado" de "instável", e as duas conclusões levam a
    # correções opostas — mexer no ambiente ou aceitar e tolerar a falha.
    # Para na primeira que passar: basta uma para provar que o caminho existe.
    if "buscar_pncp_texto" in tools:
        sucessos = 0
        for tentativa in range(1, args.tentativas + 1):
            rotulo = "tool de rede (PNCP)" + (
                f" tentativa {tentativa}/{args.tentativas}" if args.tentativas > 1 else ""
            )
            try:
                t = time.monotonic()
                r = c._chamar("tools/call", {
                    "name": "buscar_pncp_texto",
                    "arguments": {
                        "termo_busca": "notebook",
                        "tipo_documento": "edital",
                        "tamanho_pagina": 5,
                    },
                })
                decorrido = time.monotonic() - t
                res = r.get("result", {})
                if res.get("isError"):
                    _falha(rotulo, res.get("content"), decorrido)
                else:
                    _ok(rotulo, "consulta externa respondeu", decorrido)
                    sucessos += 1
                    break
            except Exception as exc:  # noqa: BLE001
                _falha(rotulo, exc, time.monotonic() - t)
        if not sucessos:
            problemas += 1
        elif tentativa > 1:
            print(
                f"  AVISO: passou só na tentativa {tentativa} — a saída de rede "
                "funciona, mas o /api/search do PNCP está INTERMITENTE."
            )

    print(f"\n{'tudo certo' if not problemas else f'{problemas} problema(s)'}\n")
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
