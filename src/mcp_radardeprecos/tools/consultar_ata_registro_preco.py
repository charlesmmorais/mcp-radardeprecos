"""Tool MCP: consulta detalhe, itens (com saldo) e arquivos de uma Ata de Registro de Preço."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ..clients import pncp_client
from ..clients.base import UpstreamError
from ..logging_utils import get_logger
from ..utils.documentos import mascarar_documento

logger = get_logger(__name__)


def _vigente(vigencia_fim: str | None, cancelada: bool | None) -> bool:
    """Regra de vigência: cancelada nunca é vigente;
    sem ``vigencia_fim`` é tratada como vigente; senão compara com agora (UTC)."""
    if cancelada:
        return False
    if not vigencia_fim:
        return True
    try:
        fim = datetime.fromisoformat(vigencia_fim.replace("Z", "+00:00"))
    except ValueError:
        return True
    if fim.tzinfo is None:
        fim = fim.replace(tzinfo=timezone.utc)
    return fim >= datetime.now(timezone.utc)


async def consultar_ata_registro_preco(
    numero_controle_pncp_ata: str | None = None,
    cnpj: str | None = None,
    ano_compra: int | None = None,
    sequencial_compra: int | None = None,
    sequencial_ata: int | None = None,
    incluir_arquivos: bool = False,
) -> dict[str, Any]:
    """Consulta o detalhe de uma Ata de Registro de Preço, com itens (preço e saldo) e arquivos.

    Fonte: índice de Atas do PNCP — o repositório de PUBLICIDADE da Lei
    14.133, onde todo ente é obrigado a publicar. É o conjunto mais amplo
    para saber SE existe ata: cobre também quem está fora do SIASG (outros
    Poderes, órgãos de controle, estados, municípios), que não aparece em
    ``buscar_arp_compras``. Confirmado ao vivo em 2026-08-17: atas vigentes
    do TCU aparecem aqui e não lá.

    A tool irmã ``buscar_arp_compras`` cobre só o subconjunto SIASG, mas para
    ESSE subconjunto traz o que o PNCP não tem — empenhos e adesões por item.
    Use esta para descobrir se a ata existe; aquela para aprofundar quando o
    órgão for do SIASG.

    Preenche a **3ª fonte prioritária** de pesquisa de preços do guia
: "atas de outros órgãos" —
    até esta versão, o projeto só permitia buscar atas por texto
    (``buscar_pncp_texto`` com ``tipo_documento="ata"``), sem acesso ao
    preço/saldo de seus itens. Endpoints da API de Consulta oficial,
    confirmados ao vivo.

    Identifique a ata de uma das duas formas:

    1. ``numero_controle_pncp_ata``: a string completa no formato
       ``CNPJ-1-SEQUENCIAL_COMPRA/ANO-SEQUENCIAL_ATA`` (ex.:
       ``18457226000181-1-000015/2023-000001``), como vem no campo
       ``numero_controle_pncp`` de uma ata retornada por
       ``buscar_pncp_texto``; **ou**
    2. os quatro parâmetros discretos ``cnpj``/``ano_compra``/
       ``sequencial_compra``/``sequencial_ata`` separadamente.

    Args:
        numero_controle_pncp_ata: Número de controle completo da ata (ver
            acima). Se informado, os 4 parâmetros discretos são ignorados.
        cnpj: CNPJ do órgão (14 posições), se não usar
            ``numero_controle_pncp_ata``.
        ano_compra: Ano da contratação que originou a ata.
        sequencial_compra: Sequencial da contratação que originou a ata.
        sequencial_ata: Sequencial da própria ata dentro da contratação.
        incluir_arquivos: Se True, busca também os arquivos anexados
            diretamente à ata (ex.: o PDF assinado). Padrão False (chamada
            de rede extra).

    Returns:
        Dicionário com os metadados da ata (``numero_ata``, ``objeto``,
        ``orgao``, ``uf``, ``municipio``, ``vigencia_inicio``,
        ``vigencia_fim``, ``vigente`` — calculado —, ``cancelada``), a lista
        ``itens`` (``preco_unitario``, ``quantidade_original``,
        ``saldo_quantidade``, ``fornecedor``, ``marca``/``modelo`` — pode vir
        vazia, ver ``avisos``), e, se ``incluir_arquivos``, a lista
        ``arquivos``. ``avisos`` alerta quando o PNCP não tem itens
        detalhados para esta ata (lacuna de dados conhecida, não um erro).
    """
    if numero_controle_pncp_ata:
        parsed = pncp_client.parse_numero_controle_pncp_ata(numero_controle_pncp_ata)
        if not parsed:
            raise ValueError(
                "numero_controle_pncp_ata em formato inválido — esperado "
                "CNPJ-1-SEQUENCIAL_COMPRA/ANO-SEQUENCIAL_ATA"
            )
        cnpj, ano_compra, sequencial_compra, sequencial_ata = parsed
    elif not all(
        v is not None for v in (cnpj, ano_compra, sequencial_compra, sequencial_ata)
    ):
        raise ValueError(
            "Informe numero_controle_pncp_ata OU os 4 parâmetros discretos "
            "(cnpj, ano_compra, sequencial_compra, sequencial_ata)."
        )

    logger.info(
        "consultar_ata_registro_preco cnpj=%s ano_compra=%s sequencial_compra=%s "
        "sequencial_ata=%s incluir_arquivos=%s",
        cnpj, ano_compra, sequencial_compra, sequencial_ata, incluir_arquivos,
    )

    # `return_exceptions=True` é o ponto desta função.
    #
    # As três chamadas são independentes e falham de forma independente: em
    # 07/09/2026 duas atas reais devolveram HTTP 404 em `/itens` enquanto o
    # DETALHE e os ARQUIVOS respondiam normalmente. Sem esta flag, o 404 de
    # uma derrubava as outras duas, e a tool devolvia erro tendo em mãos os
    # metadados da ata. Pior: o tratamento correto já existia logo abaixo
    # (`itens: []` mais um aviso explicando a lacuna) e era inalcançável.
    #
    # A separação que importa: 404 no DETALHE significa que a ata não existe
    # e tem de falhar; 404 nos ITENS ou ARQUIVOS é lacuna de preenchimento
    # pelo órgão, comum mesmo em atas vigentes, e vira aviso.
    coros = [
        pncp_client.consultar_ata(cnpj, ano_compra, sequencial_compra, sequencial_ata),
        pncp_client.consultar_itens_ata(cnpj, ano_compra, sequencial_compra, sequencial_ata),
    ]
    if incluir_arquivos:
        coros.append(
            pncp_client.consultar_arquivos_ata(
                cnpj, ano_compra, sequencial_compra, sequencial_ata
            )
        )
    respostas = await asyncio.gather(*coros, return_exceptions=True)
    ata, itens = respostas[0], respostas[1]
    arquivos_brutos = respostas[2] if incluir_arquivos else None

    # Falhas de coleta que viram aviso, não erro. Guardadas antes de tocar
    # em `ata`, porque a mensagem menciona o motivo original.
    falhas: list[str] = []
    if isinstance(itens, BaseException):
        falhas.append(f"itens da ata não puderam ser lidos no PNCP ({itens}).")
        itens = []
    if isinstance(arquivos_brutos, BaseException):
        falhas.append(f"arquivos da ata não puderam ser lidos no PNCP ({arquivos_brutos}).")
        arquivos_brutos = None

    # O detalhe, ao contrário, é indispensável: sem ele não há ata para
    # descrever, e devolver um envelope de campos nulos seria inventar um
    # registro que a fonte disse não ter. `None` (204/corpo vazio) recebe o
    # mesmo tratamento — foi o quinto ponto do defeito de 204 da v0.5.4, que
    # a auditoria por análise estática perdeu por não cobrir `asyncio.gather`.
    if isinstance(ata, BaseException):
        raise ata
    if ata is None:
        raise UpstreamError(
            "pncp",
            None,
            f"ata {cnpj}/{ano_compra}/{sequencial_compra}/{sequencial_ata} não "
            "encontrada no PNCP (a fonte respondeu sem conteúdo). Confira o "
            "número de controle — o sequencial da ata é por compra, não global.",
        )

    cancelada = ata.get("cancelado")
    if cancelada is None:
        cancelada = ata.get("cancelada")
    vigencia_fim = ata.get("vigenciaFim") or ata.get("dataVigenciaFim")

    itens_formatados = [
        {
            "descricao": it.get("descricao"),
            "quantidade_original": it.get("quantidadeOriginal") or it.get("quantidade"),
            "saldo_quantidade": it.get("saldoQuantidade"),
            "unidade_medida": it.get("unidadeMedida"),
            "preco_unitario": it.get("valorUnitario"),
            "valor_total": it.get("valorTotal"),
            "fornecedor": {
                "cnpj": mascarar_documento(it.get("niFornecedor")),
                "nome": it.get("nomeRazaoSocialFornecedor"),
            },
            "marca": it.get("marca"),
            "modelo": it.get("modelo"),
        }
        for it in itens
    ]

    avisos: list[str] = list(falhas)
    # Campos estruturados para a ausência de itens: obrigar quem
    # consome o MCP a interpretar texto livre de `avisos` para saber se a ata
    # tem itens é o mesmo problema que o contrato de cobertura resolve.
    itens_disponiveis = bool(itens_formatados)
    motivo_itens: str | None = None
    if not itens_disponiveis:
        motivo_itens = "PNCP_ERRO" if falhas else "PNCP_SEM_ITENS"
        if falhas and "404" in falhas[0]:
            motivo_itens = "PNCP_HTTP_404"
    if not itens_formatados:
        avisos.append(
            "PNCP não retornou itens detalhados para esta ata (com preço/saldo) — isso é "
            "comum mesmo em atas vigentes e sem cancelamento (lacuna de preenchimento pelo "
            "órgão, confirmada em amostras reais). Considere consultar os itens da "
            "contratação de origem via buscar_contratacoes_pncp/consultar_itens_contratacao "
            "(sem saldo, mas com o valor histórico do item), ou os arquivos da ata/compra "
            "para conferir manualmente."
        )

    resultado: dict[str, Any] = {
        "itens_disponiveis": itens_disponiveis,
        "motivo_itens_indisponiveis": motivo_itens,
        "numero_controle_pncp_ata": ata.get("numeroControlePNCPAta") or ata.get("numeroControlePNCP"),
        "numero_ata": ata.get("numeroAtaRegistroPreco"),
        "objeto": ata.get("objetoContratacao"),
        "orgao": (ata.get("orgaoEntidade") or {}).get("razaoSocial"),
        "cnpj_orgao": (ata.get("orgaoEntidade") or {}).get("cnpj"),
        "uf": (ata.get("unidadeOrgao") or {}).get("ufSigla"),
        "municipio": (ata.get("unidadeOrgao") or {}).get("municipioNome"),
        "data_assinatura": ata.get("dataAssinatura"),
        "vigencia_inicio": ata.get("vigenciaInicio") or ata.get("dataVigenciaInicio"),
        "vigencia_fim": vigencia_fim,
        "vigente": _vigente(vigencia_fim, cancelada),
        "cancelada": bool(cancelada),
        "itens": itens_formatados,
        "avisos": avisos,
    }
    if incluir_arquivos:
        resultado["arquivos"] = [
            {
                "titulo": a.get("titulo"),
                "tipo_documento": a.get("tipoDocumentoNome"),
                "data_publicacao_pncp": a.get("dataPublicacaoPncp"),
                "url_download": a.get("url") or a.get("uri"),
            }
            for a in (arquivos_brutos or [])
        ]
    return resultado
