"""Cliente da API de dados abertos do Banco Central (SGS) — séries de índices mensais.

Endpoint público, sem credencial (mesmo perfil das demais fontes do projeto):
``GET https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_serie}/dados`` com
``formato=json`` e período em ``dataInicial``/``dataFinal`` (``dd/MM/aaaa``).
Cada registro é ``{"data": "01/MM/aaaa", "valor": "<variação % no mês>"}`` —
mesmo formato para qualquer série do SGS, não só a 433 (IPCA).

Generalizado na v0.2.4 de "só IPCA" para
qualquer série SGS de variação mensal — hoje usado pelos três índices de
``domain.dominios.INDICES_CORRECAO_MONETARIA`` (IPCA, IGP-M, IPC-Fipe), todos
consumidos por ``tools/atualizar_precos_indice.py``. Valores publicados não
mudam (revisões são raríssimas), então a resposta é cacheada por 1 dia.
"""
from __future__ import annotations

from datetime import date

from ..config import settings
from ..utils.cache import TTL_1_DIA
from .base import get_json

_SERIE_IPCA = 433


async def obter_indice_mensal(codigo_serie: int, data_inicial: date, data_final: date) -> list[dict]:
    """Variação mensal de uma série do SGS/Banco Central no período, em ordem cronológica.

    Args:
        codigo_serie: Código da série SGS (ex.: 433 = IPCA, 189 = IGP-M,
            193 = IPC-Fipe — ver ``domain.dominios.INDICES_CORRECAO_MONETARIA``
            para a lista suportada pelas tools deste servidor; qualquer outro
            código de série de variação mensal do SGS também funciona aqui).
        data_inicial: Início do período.
        data_final: Fim do período.

    Returns:
        Lista de ``{"competencia": "AAAA-MM", "variacao_percentual": float}``.
        Meses ainda não publicados pelo SGS simplesmente não aparecem.
    """
    bruto = await get_json(
        settings.bcb_sgs_base_url,
        f"/dados/serie/bcdata.sgs.{codigo_serie}/dados",
        {
            "formato": "json",
            "dataInicial": data_inicial.strftime("%d/%m/%Y"),
            "dataFinal": data_final.strftime("%d/%m/%Y"),
        },
        source="BCB/SGS",
        cache_key=f"bcb:serie{codigo_serie}:{data_inicial.isoformat()}:{data_final.isoformat()}",
        cache_ttl_seconds=TTL_1_DIA,
    )
    serie: list[dict] = []
    for registro in bruto or []:
        data_str = registro.get("data", "")  # "01/MM/aaaa"
        valor_str = str(registro.get("valor", "")).replace(",", ".")
        try:
            dia, mes, ano = data_str.split("/")
            serie.append(
                {
                    "competencia": f"{ano}-{mes}",
                    "variacao_percentual": float(valor_str),
                }
            )
        except (ValueError, AttributeError):
            continue  # registro malformado não derruba a série inteira
    serie.sort(key=lambda r: r["competencia"])
    return serie


async def obter_ipca_mensal(data_inicial: date, data_final: date) -> list[dict]:
    """Variação mensal do IPCA no período — atalho para ``obter_indice_mensal(433, ...)``."""
    return await obter_indice_mensal(_SERIE_IPCA, data_inicial, data_final)
