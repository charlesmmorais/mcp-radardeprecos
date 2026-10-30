"""Tool MCP: lista os arquivos (edital, TR, contrato assinado etc.) de uma compra/contrato do PNCP."""
from __future__ import annotations

from typing import Any, Literal

from ..clients import pncp_client
from ..domain.dominios import TIPOS_DOCUMENTO_BUSCA_PNCP
from ..logging_utils import get_logger

logger = get_logger(__name__)

TipoDocumentoArquivo = Literal["edital", "ata", "contrato"]


async def listar_arquivos_pncp(
    tipo_documento: TipoDocumentoArquivo,
    cnpj: str,
    ano: int,
    sequencial: int,
    pagina: int = 1,
    tamanho_pagina: int = 50,
) -> dict[str, Any]:
    """Lista os arquivos anexados a um edital, ata ou contrato do PNCP, com link de download.

    Essencial para pesquisa de preços: os documentos originais (edital, termo
    de referência, contrato assinado, termo de adesão etc.) costumam ser a
    fonte primária que comprova o preço praticado, exigida pela IN SEGES/ME
    65/2021.

    Args:
        tipo_documento: "edital", "ata" ou "contrato".
        cnpj: CNPJ do órgão (14 posições, sem máscara).
        ano: Ano da compra (edital/ata) ou do contrato.
        sequencial: Sequencial no PNCP. Para "edital", o sequencial da compra.
            Para "ata", **o sequencial da compra que originou a ata** — não o
            sequencial da própria ata (a ata não tem arquivos próprios; os
            documentos ficam na compra de origem). No retorno de
            ``buscar_pncp_texto``/busca de atas, esse valor vem no campo
            ``numero_sequencial_compra_ata``. Para "contrato", o sequencial
            do contrato (campo ``numero_controle_pncp``, formato
            ``CNPJ-2-SEQUENCIAL/ANO``).
        pagina: Página dos resultados (padrão 1).
        tamanho_pagina: Registros por página (padrão 50).

    Returns:
        Dicionário com ``quantidade`` e ``arquivos`` — cada um com ``titulo``
        (nome do arquivo), ``tipo_documento`` (categoria, ex.: "Termo de
        Referência"), ``data_publicacao_pncp`` e ``url_download`` (link
        direto, público, sem autenticação).
    """
    if tipo_documento not in TIPOS_DOCUMENTO_BUSCA_PNCP:
        raise ValueError(f"tipo_documento deve ser um de {TIPOS_DOCUMENTO_BUSCA_PNCP}")

    recurso = "contratos" if tipo_documento == "contrato" else "compras"
    logger.info(
        "listar_arquivos_pncp tipo=%s cnpj=%s ano=%s sequencial=%s recurso=%s",
        tipo_documento, cnpj, ano, sequencial, recurso,
    )
    arquivos = await pncp_client.consultar_arquivos(
        cnpj, ano, sequencial, recurso, pagina=pagina, tamanho_pagina=tamanho_pagina
    )
    resultados = [
        {
            "titulo": a.get("titulo"),
            "tipo_documento": a.get("tipoDocumentoNome"),
            "data_publicacao_pncp": a.get("dataPublicacaoPncp"),
            "sequencial_documento": a.get("sequencialDocumento"),
            "url_download": a.get("uri") or a.get("url"),
        }
        for a in arquivos
    ]
    return {"quantidade": len(resultados), "arquivos": resultados}
