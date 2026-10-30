"""Impressão digital do catálogo de ferramentas, para verificação externa.

Por que existe, e por que NÃO é uma notificação
-----------------------------------------------
A v0.5.8 tentou resolver o cache de catálogo dos clientes emitindo
``notifications/tools/list_changed`` no primeiro uso de cada sessão. Foi um
erro em dois níveis:

1. **Prático.** Em teste na instância publicada, o efeito foi o oposto do
   pretendido — logo após a descoberta, o cliente passou a responder
   ``Resource not found`` para tools que o próprio catálogo anunciava, até
   redescobrir. A leitura mais plausível é que a notificação invalidava, no
   cliente, a lista que ele acabara de montar.

2. **Normativo, e este é decisivo.** A especificação do MCP determina que o
   conjunto devolvido por ``tools/list`` **não varie como efeito colateral de
   outras requisições na conexão**. Um ``tools/call`` provocando alteração
   aparente do catálogo é comportamento incorreto, independentemente de o
   cliente lidar bem com isso ou não. ``listChanged`` significa "a lista
   mudou" — não "houve uma primeira chamada", "abriu sessão" ou "a tool foi
   usada".

Por que também não vale reimplementar com digest e notificar
-------------------------------------------------------------
O critério correto seria notificar apenas na transição real
``digest_anterior != digest_atual``. Só que **neste servidor o conjunto de
tools é fixo no import**: nunca há transição dentro de um processo. Entre
processos, a sessão do transporte morre de qualquer forma (``Mcp-Session-Id``
é por processo, e o streamable-http devolve 404 para um identificador que não
corresponde mais), e o cliente reinicializa e redescobre por conta própria.

Ou seja: uma implementação **correta** de ``listChanged`` aqui nunca
dispararia. O que sobra do esforço é a parte útil — o digest como
**impressão digital verificável de fora**, que não depende do protocolo nem
do cache do cliente:

- se ``GET /`` anuncia 53 tools com digest ``abc123`` e o cliente oferece 52,
  o cliente está desatualizado;
- se ``GET /`` também não traz a tool nova, quem está velho é o **deploy**.

Essa distinção importa porque as duas causas produzem o mesmo sintoma, e
atribuir tudo a cache de cliente é uma explicação confortável que já mascarou
falha de publicação real neste projeto.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _descrever(tool: Any) -> dict[str, Any]:
    """Extrai de uma tool do FastMCP o que define a sua identidade.

    Nome e schema de entrada mudam o **contrato**; a descrição muda a
    **decisão do modelo** de quando chamar. Uma alteração em qualquer um dos
    três precisa mudar o digest — senão um cliente com cache continuaria
    chamando com o schema antigo sem que nada acusasse.
    """
    return {
        "nome": getattr(tool, "name", None),
        "descricao": getattr(tool, "description", None),
        "parametros": getattr(tool, "parameters", None),
    }


def descrever_catalogo(tools: list[Any]) -> dict[str, Any]:
    """Nomes, contagem e digest determinístico do catálogo.

    Args:
        tools: Lista de tools do FastMCP (``await mcp.list_tools()``) ou
            qualquer objeto com ``name``/``description``/``parameters``.

    Returns:
        ``{"tools": [nomes...], "tools_count": int, "digest": "..."}``.

        O digest é o SHA-256 dos doze primeiros caracteres hexadecimais sobre
        a serialização JSON **ordenada** das descrições. Ordenar é o que torna
        o valor reproduzível: sem ``sort_keys`` e sem ordenar a lista, dois
        processos com o mesmo catálogo produziriam digests diferentes, e a
        comparação — que é toda a razão de existir do campo — acusaria
        divergência onde não há.
    """
    descricoes = sorted(
        (_descrever(t) for t in tools), key=lambda d: d["nome"] or ""
    )
    serializado = json.dumps(descricoes, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(serializado.encode("utf-8")).hexdigest()[:12]
    return {
        "tools": [d["nome"] for d in descricoes],
        "tools_count": len(descricoes),
        "digest": digest,
    }
