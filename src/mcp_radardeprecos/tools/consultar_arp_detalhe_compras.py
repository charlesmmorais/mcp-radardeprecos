"""Tool MCP: consolida saldo, adesões (caronas) e empenhos de um item de ARP (Compras.gov.br).

Complementa ``consultar_ata_registro_preco`` (PNCP): o PNCP não expõe saldo
de adesão, teto de adesão nem empenhos por item de uma Ata de Registro de
Preço — só o módulo "ARP" do Compras.gov.br tem essa granularidade
(``/modulo-arp/3_consultarUnidadesItem``, ``4_consultarEmpenhosSaldoItem``,
``5_consultarAdesoesItem``), confirmada ao vivo em 2026-07-09.

**Sobre o campo ``adesoes`` — devolvido CRU, sem tradução de nomes.** Ao
desenvolver esta tool, testei ``5_consultarAdesoesItem`` contra vários itens
reais com alto teto de adesão (candidatos prováveis a ter uma "carona"
registrada) e todas as tentativas devolveram lista vazia — adesão real é
aparentemente incomum nos dados correntes. Sem um caso real para confirmar
o formato dos campos, não faço a mesma tradução snake_case aplicada aos
outros campos desta tool (não chuto nome de campo, mesmo princípio já usado
em outros clientes deste projeto) — se `adesoes` vier não-vazio, os nomes
são exatamente os da resposta original do Compras.gov.br.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..clients import compras_client
from ..logging_utils import get_logger

logger = get_logger(__name__)


async def consultar_arp_detalhe_compras(
    numero_ata: str,
    unidade_gerenciadora: str,
    numero_item: str,
) -> dict[str, Any]:
    """Consolida saldo de adesão/remanejamento, adesões e empenho de um item de ARP.

    Três chamadas de rede (paralelas) já existentes no Compras.gov.br: saldo
    da unidade gerenciadora sobre o item, adesões ("caronas") registradas, e
    empenhos do item (a API devolve os empenhos de TODOS os itens da ata
    numa única chamada — esta tool filtra pelo ``numero_item`` pedido).

    Args:
        numero_ata: Número da Ata de Registro de Preço (ex.: "00002/2025") —
            ver ``numero_ata_registro_preco`` no retorno de
            ``buscar_arp_compras``.
        unidade_gerenciadora: Código da UASG gerenciadora da ata — ver
            ``codigo_unidade_gerenciadora`` no retorno de
            ``buscar_arp_compras``.
        numero_item: Número do item dentro da ata (ex.: "00009") — ver
            ``numero_item`` no retorno de ``buscar_arp_compras`` com
            ``incluir_itens=True``.

    Returns:
        Dicionário com:
        - ``saldo_unidade``: ``quantidade_registrada``, ``saldo_adesoes``,
          ``saldo_remanejamento_empenho``, ``qtd_limite_adesao``,
          ``aceita_adesao``, ``fornecedor`` — ``None`` se não encontrado.
        - ``adesoes``: lista de adesões registradas para este item, **crua**
          (sem tradução de campo — ver docstring do módulo). Lista vazia é
          uma resposta normal (a maioria dos itens não tem adesão).
        - ``empenho``: ``quantidade_registrada``, ``quantidade_empenhada``,
          ``saldo_empenho`` deste item específico (filtrado da resposta que
          traz todos os itens da ata) — ``None`` se não encontrado.
        - ``avisos``: alerta se algum dos três não encontrou registro.

    Raises:
        ValueError: se algum dos três argumentos for vazio.
    """
    if not numero_ata or not numero_ata.strip():
        raise ValueError("numero_ata não pode ser vazio")
    if not unidade_gerenciadora or not unidade_gerenciadora.strip():
        raise ValueError("unidade_gerenciadora não pode ser vazio")
    if not numero_item or not numero_item.strip():
        raise ValueError("numero_item não pode ser vazio")

    logger.info(
        "consultar_arp_detalhe_compras numero_ata=%s unidade_gerenciadora=%s numero_item=%s",
        numero_ata, unidade_gerenciadora, numero_item,
    )

    resultado_unidades, resultado_adesoes, resultado_empenhos = await asyncio.gather(
        compras_client.consultar_arp_unidades_item(
            numero_ata=numero_ata,
            unidade_gerenciadora=unidade_gerenciadora,
            numero_item=numero_item,
        ),
        compras_client.consultar_arp_adesoes_item(
            numero_ata=numero_ata,
            unidade_gerenciadora=unidade_gerenciadora,
            numero_item=numero_item,
        ),
        compras_client.consultar_arp_empenhos_item(
            numero_ata=numero_ata,
            unidade_gerenciadora=unidade_gerenciadora,
        ),
    )

    unidades_brutas = (resultado_unidades or {}).get("resultado", []) or []
    adesoes_brutas = (resultado_adesoes or {}).get("resultado", []) or []
    empenhos_brutos = (resultado_empenhos or {}).get("resultado", []) or []

    avisos: list[str] = []

    saldo_unidade: dict[str, Any] | None = None
    if unidades_brutas:
        u = unidades_brutas[0]
        saldo_unidade = {
            "quantidade_registrada": u.get("quantidadeRegistrada"),
            "saldo_adesoes": u.get("saldoAdesoes"),
            "saldo_remanejamento_empenho": u.get("saldoRemanejamentoEmpenho"),
            "qtd_limite_adesao": u.get("qtdLimiteAdesao"),
            "aceita_adesao": u.get("aceitaAdesao"),
            "fornecedor": u.get("fornecedor"),
        }
    else:
        avisos.append(
            "Nenhum registro de saldo de unidade encontrado para este item — "
            "confira numero_ata/unidade_gerenciadora/numero_item."
        )

    empenho: dict[str, Any] | None = None
    empenho_bruto = next(
        (e for e in empenhos_brutos if e.get("numeroItem") == numero_item), None
    )
    if empenho_bruto:
        empenho = {
            "quantidade_registrada": empenho_bruto.get("quantidadeRegistrada"),
            "quantidade_empenhada": empenho_bruto.get("quantidadeEmpenhada"),
            "saldo_empenho": empenho_bruto.get("saldoEmpenho"),
        }
    else:
        avisos.append(
            "Nenhum registro de empenho encontrado para numero_item="
            f"{numero_item!r} dentro desta ata."
        )

    return {
        "saldo_unidade": saldo_unidade,
        "adesoes": adesoes_brutas,
        "empenho": empenho,
        "avisos": avisos,
    }
