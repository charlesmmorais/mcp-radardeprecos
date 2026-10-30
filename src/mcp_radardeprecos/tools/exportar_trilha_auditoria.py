"""Tool MCP: exporta o dossiê de auditoria (proveniência) de uma pesquisa."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .. import __version__, auditoria
from ..logging_utils import get_logger
from ..utils.arquivo_saida import exigir_gravacao_em_disco_permitida

logger = get_logger(__name__)

_AVISO = (
    "A trilha é mantida EM MEMÓRIA (reinicia a cada deploy/reinício do "
    "servidor). Num servidor HTTP compartilhado, ela pode intercalar acessos "
    "de sessões diferentes — para um dossiê de UMA pesquisa, use o servidor "
    "local (stdio) ou exporte logo ao fim da pesquisa, e/ou recorte a janela "
    "com 'desde_iso'. Os hashes SHA-256 provam a integridade de cada resposta "
    "como foi recebida da fonte, mas NÃO atestam que a fonte estava correta."
)


async def exportar_trilha_auditoria(
    objeto: str | None = None,
    responsavel: str | None = None,
    decisoes: Any | None = None,
    desde_iso: str | None = None,
    limite: int = 1000,
    caminho_saida: str | None = None,
) -> dict[str, Any]:
    """Exporta o dossiê de AUDITORIA da pesquisa: proveniência + integridade.

    Torna uma pesquisa de preços **defensável e reconstruível**. Reúne a trilha
    capturada automaticamente a cada acesso às fontes públicas (qual tool
    disparou, URL, parâmetros, timestamp UTC, status e o **hash SHA-256 da
    resposta bruta**) num dossiê único, com um hash de reprodutibilidade que
    identifica exatamente aquele conjunto de acessos e respostas.

    Complementa ``gerar_memoria_pesquisa`` (que formaliza objeto, fontes,
    método e resultado no padrão da IN 65/2021): aqui entra a camada de
    PROVENIÊNCIA e INTEGRIDADE que permite provar, em auditoria, "consultei
    estas URLs, nesta data/hora, e recebi exatamente estas respostas".

    A proveniência é capturada sozinha (não precisa instrumentar nada): todo
    acesso upstream feito pelas tools deste servidor já entra na trilha. Chame
    esta tool ao FIM de uma pesquisa para consolidar o dossiê.

    Args:
        objeto: descrição do objeto pesquisado (para constar no dossiê).
        responsavel: agente responsável pela pesquisa.
        decisoes: decisões metodológicas a registrar (texto ou estrutura livre
            — ex.: unidade-alvo, grupos escolhidos, exclusões justificadas,
            método estatístico). O modelo/quem chama fornece.
        desde_iso: se informado (timestamp ISO UTC, ex.: ``"2026-07-29T18:00:00+00:00"``),
            inclui só acessos a partir desse instante — recorta a janela de UMA
            pesquisa num servidor compartilhado.
        limite: máximo de acessos incluídos (mais recentes; padrão 1000).
        caminho_saida: se informado, grava o dossiê como JSON nesse caminho (só
            faz sentido em uso local/stdio — o disco é o do servidor). Sem ele,
            o dossiê volta apenas no retorno.

    Returns:
        Dicionário com ``gerado_em`` (UTC), ``versao_servidor``, ``objeto``,
        ``responsavel``, ``decisoes``, ``resumo`` (total de acessos, fontes
        distintas, janela de tempo), ``hash_reprodutibilidade``,
        ``proveniencia`` (lista de acessos, cada um com tool/fonte/url/params/
        status/hash/bytes/timestamp), ``aviso`` e, se ``caminho_saida`` for
        usado, ``caminho_saida``/``tamanho_bytes``.
    """
    trilha = auditoria.obter_trilha(limite=limite, desde_iso=desde_iso)

    fontes = sorted({r.get("fonte") for r in trilha if r.get("fonte")})
    janela = None
    if trilha:
        janela = {
            "primeiro_acesso_utc": trilha[0]["timestamp_utc"],
            "ultimo_acesso_utc": trilha[-1]["timestamp_utc"],
        }

    logger.info(
        "exportar_trilha_auditoria acessos=%d fontes=%d objeto=%r",
        len(trilha), len(fontes), objeto,
    )

    dossie: dict[str, Any] = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "versao_servidor": __version__,
        "objeto": objeto,
        "responsavel": responsavel,
        "decisoes": decisoes,
        "resumo": {
            "total_acessos": len(trilha),
            "fontes_consultadas": fontes,
            "janela": janela,
        },
        "hash_reprodutibilidade": auditoria.hash_reprodutibilidade(trilha),
        "proveniencia": trilha,
        "aviso": _AVISO,
    }

    if caminho_saida:
        exigir_gravacao_em_disco_permitida()
        conteudo = json.dumps(dossie, ensure_ascii=False, indent=2)
        with open(caminho_saida, "w", encoding="utf-8") as fh:
            fh.write(conteudo)
        dossie["caminho_saida"] = caminho_saida
        dossie["tamanho_bytes"] = len(conteudo.encode("utf-8"))

    return dossie
