"""Utilitários de data compartilhados pelas tools de agregação.

Extraído de ``tools/buscar_contratacoes_pncp.py`` e
``tools/buscar_contratos_compras.py``, onde a mesma função existia duplicada
(copy-paste) — ambas as tools filtram resultados do índice do PNCP por uma
janela de meses a partir de hoje, então a lógica foi centralizada aqui.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone


def anterior_a_janela(data_iso: str | None, janelas_meses: int) -> bool:
    """A data é VÁLIDA e mais antiga que a janela?

    Serve para a varredura do índice parar cedo quando os resultados vêm
    ordenados do mais recente para o mais antigo (``ordenacao="-data"``): ao
    cruzar o limite inferior da janela, tudo que vem depois também está fora,
    e continuar varrendo só gasta orçamento.

    **Não é a negação de :func:`dentro_da_janela`, e a diferença é o ponto
    desta função.** ``dentro_da_janela`` devolve ``False`` também para data
    ausente ou mal formatada, porque na dúvida não coleta. Aqui a dúvida tem o
    efeito oposto — parar a varredura por engano esconderia todo o resto do
    índice, um falso negativo muito mais caro que um item a menos. Por isso
    data ausente ou inválida devolve ``False``: não autoriza parar.

    Args:
        data_iso: Data em formato ISO 8601 (aceita sufixo ``Z``).
        janelas_meses: Tamanho da janela, em meses, a partir de agora (UTC).

    Returns:
        ``True`` somente quando a data é parseável e anterior ao início da
        janela. ``False`` para data ausente, inválida ou dentro da janela.
    """
    if not data_iso:
        return False
    try:
        data = datetime.fromisoformat(data_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    limite = datetime.now(timezone.utc) - timedelta(days=30 * janelas_meses)
    return data < limite


def dentro_da_janela(data_iso: str | None, janelas_meses: int) -> bool:
    """Verifica se uma data ISO 8601 está dentro dos últimos ``janelas_meses`` meses.

    Usada para filtrar resultados da busca indexada do PNCP (que não aceita
    filtro de período nativo) por uma janela relativa a "agora". Meses são
    aproximados como 30 dias, o que é suficiente para a finalidade de
    pesquisa de preços (não exige precisão de calendário).

    Args:
        data_iso: Data em formato ISO 8601 (aceita sufixo ``Z``). ``None`` ou
            string vazia é tratado como "fora da janela".
        janelas_meses: Tamanho da janela, em meses, a partir de agora (UTC).

    Returns:
        ``True`` se ``data_iso`` for uma data válida dentro da janela;
        ``False`` caso contrário (data ausente, mal formatada ou fora da
        janela).
    """
    if not data_iso:
        return False
    try:
        data = datetime.fromisoformat(data_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    limite = datetime.now(timezone.utc) - timedelta(days=30 * janelas_meses)
    return data >= limite


def aviso_indice_parcial(
    total_indice: int, quantidade_retornada: int, motivos: list[str]
) -> str | None:
    """Gera um aviso explicando por que ``total_indice`` supera ``quantidade_retornada``.

    As tools de busca por texto no PNCP aplicam filtros no **cliente**
    (janela de meses via ``dentro_da_janela``, CNPJ do órgão, homologação,
    deduplicação, limite de resultados) depois de já terem lido o total do
    índice do servidor. Sem esse aviso, a diferença entre os dois números
    aparenta ser um bug de paginação — já foi de fato confundida dessa forma
    na prática — quando na verdade é o resultado esperado desses filtros.

    Args:
        total_indice: Total reportado pelo índice do PNCP para a busca,
            antes de qualquer filtro aplicado no cliente.
        quantidade_retornada: Quantidade de itens efetivamente devolvida
            depois dos filtros do cliente.
        motivos: Lista de descrições curtas dos filtros que podem explicar a
            diferença (ex.: janela de meses, CNPJ do órgão, limite).

    Returns:
        Uma mensagem de aviso, ou ``None`` se não houver diferença a explicar
        (``quantidade_retornada >= total_indice``).
    """
    if quantidade_retornada >= total_indice:
        return None
    motivos_txt = "; ".join(motivos)
    return (
        f"O índice do PNCP encontrou {total_indice} registro(s) para esta busca, mas "
        f"apenas {quantidade_retornada} foram retornados após os filtros aplicados no "
        f"cliente ({motivos_txt}). Ajuste esses parâmetros se esperava mais resultados."
    )


def janela_dias_atras(dias: int) -> tuple[str, str]:
    """Devolve ``(data_inicial, data_final)`` em formato ``AAAAMMDD`` (API de
    Consulta oficial do PNCP), cobrindo os últimos ``dias`` dias a partir de
    hoje (UTC), inclusive.

    Usada por tools que consultam a API de Consulta oficial (diferente da
    busca textual/``buscar_texto``, que não aceita esse formato de data) —
    ver ``pncp_client.consultar_contratos``/``consultar_contratacoes_publicacao``.
    """
    hoje = datetime.now(timezone.utc)
    inicio = hoje - timedelta(days=dias)
    return inicio.strftime("%Y%m%d"), hoje.strftime("%Y%m%d")


def janela_dias_atras_iso(dias: int) -> tuple[str, str]:
    """Devolve ``(data_inicial, data_final)`` em formato ``AAAA-MM-DD`` (com
    hífens), cobrindo os últimos ``dias`` dias a partir de hoje (UTC),
    inclusive.

    Usada pelos endpoints do módulo Compras.gov.br que exigem data com
    hífens (ex.: ``compras_client.consultar_arp``/``consultar_arp_itens`` —
    diferente de :func:`janela_dias_atras`, que devolve ``AAAAMMDD`` sem
    hífens para a API de Consulta oficial do PNCP).
    """
    hoje = datetime.now(timezone.utc)
    inicio = hoje - timedelta(days=dias)
    return inicio.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d")


def janela_dias_a_frente(dias: int) -> tuple[str, str]:
    """Devolve ``(data_inicio, data_fim)`` em formato ``AAAAMMDD``, cobrindo
    de hoje (UTC) até ``dias`` dias À FRENTE — o inverso de
    :func:`janela_dias_atras` (que olha para trás).

    Usada por tools de "radar" que buscam o que VAI vencer/abrir num
    horizonte futuro (ex.: ``radar_vencimentos`` sobre
    ``pncp_client.consultar_atas_periodo``, ``buscar_propostas_abertas``
    sobre ``pncp_client.consultar_contratacoes_proposta_aberta``) — nos dois
    casos a API de Consulta oficial do PNCP espera ``AAAAMMDD`` sem hífens.
    """
    hoje = datetime.now(timezone.utc)
    fim = hoje + timedelta(days=dias)
    return hoje.strftime("%Y%m%d"), fim.strftime("%Y%m%d")


def janela_dias_a_frente_iso(dias: int) -> tuple[str, str]:
    """Devolve ``(data_inicio, data_fim)`` em formato ``AAAA-MM-DD`` (com
    hífens), cobrindo de hoje (UTC) até ``dias`` dias À FRENTE.

    Usada por ``radar_vencimentos`` sobre os endpoints ``_FimVigencia`` do
    Compras.gov.br (``compras_client.consultar_contratos_fim_vigencia``/
    ``consultar_arp_fim_vigencia``), que exigem data com hífens — mesmo
    padrão de :func:`janela_dias_atras_iso`, mas olhando para a frente.
    """
    hoje = datetime.now(timezone.utc)
    fim = hoje + timedelta(days=dias)
    return hoje.strftime("%Y-%m-%d"), fim.strftime("%Y-%m-%d")


def hoje_iso() -> str:
    """Devolve a data de hoje (UTC) em formato ``AAAA-MM-DD``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def somar_meses(data_iso: str, meses: int) -> str:
    """Soma (ou subtrai, se ``meses`` for negativo) meses a uma data ``AAAA-MM-DD``.

    Aritmética de calendário simples (ano/mês), sem dependências externas —
    usada por ``radar_vencimentos`` para calcular o teto legal de vigência de ARP (24 meses, Lei
    14.133/2021) a partir de uma data de referência. Quando o dia original
    não existe no mês de destino (ex.: 31/01 + 1 mês), é ajustado para o
    último dia desse mês (28 ou 29/02).

    Args:
        data_iso: Data de referência em ``AAAA-MM-DD``.
        meses: Quantidade de meses a somar (negativo para subtrair).

    Returns:
        Nova data em ``AAAA-MM-DD``.

    Raises:
        ValueError: se ``data_iso`` não estiver em formato ``AAAA-MM-DD`` válido.
    """
    data = datetime.strptime(data_iso, "%Y-%m-%d")
    total_meses = (data.month - 1) + meses
    novo_ano = data.year + total_meses // 12
    novo_mes = total_meses % 12 + 1
    ultimo_dia_mes = calendar.monthrange(novo_ano, novo_mes)[1]
    novo_dia = min(data.day, ultimo_dia_mes)
    return f"{novo_ano:04d}-{novo_mes:02d}-{novo_dia:02d}"
