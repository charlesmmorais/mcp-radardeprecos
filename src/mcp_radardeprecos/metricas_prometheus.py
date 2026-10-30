"""Exportação das métricas de uso no formato Prometheus.

Opcional: só funciona com o extra ``metrics`` (``prometheus-client``) e só é
ligada nos transportes HTTP quando ``RADARDEPRECOS_METRICS_PORT`` está
definida. As métricas saem numa porta própria, separada da porta do protocolo
MCP, para que possam ficar fora da internet — no Fly.io, só o coletor da
plataforma lê essa porta (seção ``[metrics]`` do ``fly.toml``).

Os valores vêm de :func:`observability.instantaneo_prometheus` no momento da
coleta; nada é instrumentado no caminho das tools. Os contadores zeram quando
o processo reinicia, e o Prometheus trata isso nativamente em ``rate()`` e
``increase()``.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from . import observability
from .logging_utils import get_logger

logger = get_logger(__name__)

PREFIXO = "radardeprecos"


def _familias() -> Iterator[Any]:
    from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

    dados = observability.instantaneo_prometheus()

    info = GaugeMetricFamily(f"{PREFIXO}_info", "Versão do servidor em execução.", labels=["versao"])
    info.add_metric([dados["versao"]], 1)
    yield info

    inicio = GaugeMetricFamily(
        f"{PREFIXO}_processo_inicio_timestamp_seconds", "Início do processo (epoch)."
    )
    inicio.add_metric([], dados["inicio_processo"])
    yield inicio

    chamadas = CounterMetricFamily(f"{PREFIXO}_tool_chamadas", "Chamadas por tool.", labels=["tool"])
    erros = CounterMetricFamily(f"{PREFIXO}_tool_erros", "Chamadas com erro por tool.", labels=["tool"])
    duracao = GaugeMetricFamily(
        f"{PREFIXO}_tool_duracao_segundos",
        "Duração das chamadas por tool (percentis das últimas amostras).",
        labels=["tool", "quantil"],
    )
    for nome, reg in sorted(dados["tools"].items()):
        chamadas.add_metric([nome], reg["chamadas"])
        erros.add_metric([nome], reg["erros"])
        for quantil in ("p50", "p95"):
            if reg[quantil] is not None:
                duracao.add_metric([nome, quantil], reg[quantil])
    yield chamadas
    yield erros
    yield duracao

    f_chamadas = CounterMetricFamily(
        f"{PREFIXO}_fonte_chamadas", "Chamadas lógicas por fonte externa.", labels=["fonte"]
    )
    f_erros = CounterMetricFamily(
        f"{PREFIXO}_fonte_erros", "Chamadas com erro por fonte externa.", labels=["fonte"]
    )
    f_tentativas = CounterMetricFamily(
        f"{PREFIXO}_fonte_tentativas",
        "Requisições HTTP por fonte externa, contando as repetições.",
        labels=["fonte"],
    )
    f_duracao = GaugeMetricFamily(
        f"{PREFIXO}_fonte_duracao_segundos",
        "Duração das chamadas por fonte externa (percentis das últimas amostras).",
        labels=["fonte", "quantil"],
    )
    for fonte, reg in sorted(dados["fontes"].items()):
        f_chamadas.add_metric([fonte], reg["chamadas"])
        f_erros.add_metric([fonte], reg["erros"])
        f_tentativas.add_metric([fonte], reg["tentativas"])
        for quantil in ("p50", "p95"):
            if reg[quantil] is not None:
                f_duracao.add_metric([fonte, quantil], reg[quantil])
    yield f_chamadas
    yield f_erros
    yield f_tentativas
    yield f_duracao

    c_chamadas = CounterMetricFamily(
        f"{PREFIXO}_cliente_chamadas", "Chamadas de tool por cliente MCP.", labels=["cliente"]
    )
    c_sessoes = CounterMetricFamily(
        f"{PREFIXO}_cliente_sessoes", "Sessões MCP abertas por cliente.", labels=["cliente"]
    )
    for nome, reg in sorted(dados["clientes"].items()):
        c_chamadas.add_metric([nome], reg["chamadas"])
        c_sessoes.add_metric([nome], reg["sessoes"])
    yield c_chamadas
    yield c_sessoes

    sessoes = CounterMetricFamily(f"{PREFIXO}_sessoes", "Sessões MCP distintas desde o início.")
    sessoes.add_metric([], dados["sessoes_vistas"])
    yield sessoes

    protocolos = CounterMetricFamily(
        f"{PREFIXO}_protocolo_chamadas",
        "Chamadas por versão do protocolo MCP negociada.",
        labels=["versao"],
    )
    for versao, total in sorted(dados["protocolos"].items()):
        protocolos.add_metric([versao], total)
    yield protocolos


class ColetorRadar:
    """Coletor que lê os contadores da observabilidade a cada coleta."""

    def collect(self) -> Iterator[Any]:
        yield from _familias()


def criar_registro() -> Any:
    from prometheus_client import CollectorRegistry

    registro = CollectorRegistry()
    registro.register(ColetorRadar())
    return registro


def iniciar_servidor(porta: int, endereco: str = "::") -> bool:
    """Sobe o endpoint ``/metrics`` numa porta própria. ``False`` se não for possível.

    ``::`` aceita IPv6 e IPv4 no Linux; a rede privada do Fly.io é IPv6.
    """
    try:
        from prometheus_client import start_http_server
    except ImportError:
        logger.warning(
            "RADARDEPRECOS_METRICS_PORT definida, mas prometheus-client não está "
            "instalado (extra 'metrics'); métricas Prometheus desligadas"
        )
        return False
    registro = criar_registro()
    for addr in dict.fromkeys((endereco, "0.0.0.0")):
        try:
            start_http_server(porta, addr=addr, registry=registro)
        except OSError as erro:
            logger.warning("não foi possível abrir a porta de métricas %s em %s: %s", porta, addr, erro)
            continue
        logger.info("métricas Prometheus em %s:%s/metrics", addr, porta)
        return True
    return False
