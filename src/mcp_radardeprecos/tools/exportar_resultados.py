"""Tool MCP: exporta uma lista de registros (de qualquer tool de busca) para CSV/XLSX.

As tools de busca deste servidor sempre
devolveram JSON — útil para o modelo consumir, mas o usuário final muitas
vezes só quer "me dá isso numa planilha". Esta tool recebe a MESMA lista de
registros que qualquer tool de busca já devolve (ex.: o campo ``atas`` de
``buscar_arp_compras``, ``contratos`` de ``buscar_contratos_compras`` etc.)
e grava uma tabela plana em CSV ou XLSX.

Reaproveita ``utils/arquivo_saida.gravar_documento`` (padrão v0.1.43, já
usado por ``gerar_relatorio_word``/``gerar_relatorio_excel``): com
``caminho_saida`` grava no disco de onde o servidor roda; sem ele, serializa
em memória e devolve ``conteudo_base64`` — nunca toca um filesystem
compartilhado entre usuários num servidor remoto.

Dicts aninhados (ex.: ``{"fornecedor": {"cnpj": "..."}}``) são achatados com
notação de ponto (``fornecedor.cnpj``) antes de virar coluna — uma tabela não
tem como representar aninhamento. Listas viram uma única célula de texto
(itens unidos por ``"; "``), preservando a informação sem multiplicar linhas.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Literal

from openpyxl import Workbook

from ..logging_utils import get_logger
from ..utils.arquivo_saida import gravar_documento

logger = get_logger(__name__)

FormatoExportacao = Literal["csv", "xlsx"]

_FORMATOS_VALIDOS = ("csv", "xlsx")
_LIMITE_REGISTROS = 5000


def _achatar(registro: dict[str, Any], prefixo: str = "") -> dict[str, Any]:
    """Achata um dict aninhado com notação de ponto (``fornecedor.cnpj``)."""
    achatado: dict[str, Any] = {}
    for chave, valor in registro.items():
        chave_completa = f"{prefixo}.{chave}" if prefixo else str(chave)
        if isinstance(valor, dict):
            achatado.update(_achatar(valor, chave_completa))
        elif isinstance(valor, list):
            achatado[chave_completa] = "; ".join(str(item) for item in valor) if valor else ""
        else:
            achatado[chave_completa] = valor
    return achatado


def _montar_colunas(
    registros_achatados: list[dict[str, Any]], nome_colunas: list[str] | None
) -> list[str]:
    if nome_colunas:
        return list(nome_colunas)
    colunas: list[str] = []
    vistas: set[str] = set()
    for registro in registros_achatados:
        for chave in registro:
            if chave not in vistas:
                vistas.add(chave)
                colunas.append(chave)
    return colunas


class _DocumentoCsv:
    """Wrapper mínimo com ``.save(destino)`` — mesmo protocolo esperado por
    ``utils.arquivo_saida.gravar_documento`` (visto em ``python-docx``/
    ``openpyxl``), para reaproveitar a mesma função com CSV via stdlib."""

    def __init__(self, colunas: list[str], linhas: list[dict[str, Any]]) -> None:
        self._colunas = colunas
        self._linhas = linhas

    def save(self, destino: Any) -> None:
        texto = io.StringIO()
        escritor = csv.DictWriter(texto, fieldnames=self._colunas, extrasaction="ignore")
        escritor.writeheader()
        for linha in self._linhas:
            escritor.writerow(linha)
        # BOM UTF-8: abre corretamente acentuação no Excel (padrão pt-BR).
        conteudo = texto.getvalue().encode("utf-8-sig")
        if isinstance(destino, str):
            with open(destino, "wb") as arquivo:
                arquivo.write(conteudo)
        else:
            destino.write(conteudo)


def _montar_xlsx(colunas: list[str], linhas: list[dict[str, Any]]) -> Workbook:
    pasta = Workbook()
    aba = pasta.active
    aba.title = "Resultados"
    aba.append(colunas)
    for linha in linhas:
        aba.append([linha.get(coluna, "") for coluna in colunas])
    return pasta


async def exportar_resultados(
    registros: list[dict[str, Any]],
    formato: FormatoExportacao = "csv",
    caminho_saida: str | None = None,
    nome_colunas: list[str] | None = None,
) -> dict[str, Any]:
    """Exporta uma lista de registros (de qualquer tool de busca) para CSV ou XLSX.

    Args:
        registros: Lista de dicionários a exportar — tipicamente o campo de
            resultados já devolvido por outra tool de busca deste servidor
            (ex.: ``atas`` de ``buscar_arp_compras``, ``contratos`` de
            ``buscar_contratos_compras``, ``itens`` de ``consultar_pca``).
            Dicts aninhados são achatados com notação de ponto
            (``fornecedor.cnpj``); listas viram uma célula de texto (itens
            unidos por ``"; "``).
        formato: ``"csv"`` (padrão, via biblioteca padrão do Python) ou
            ``"xlsx"`` (via ``openpyxl``).
        caminho_saida: Caminho de destino no disco de onde o servidor roda.
            Se omitido, o arquivo é serializado inteiramente em memória e
            devolvido em ``conteudo_base64`` (nunca toca o disco do
            servidor) — necessário quando o servidor roda remotamente (ex.:
            hospedagem compartilhada), onde ``caminho_saida`` não é aceito pelo
            usuário. Mesmo padrão de ``gerar_relatorio_word``/
            ``gerar_relatorio_excel``.
        nome_colunas: Lista explícita de nomes de coluna (já no formato
            achatado, ex.: ``["numero_ata_registro_preco",
            "fornecedor.cnpj"]``) e sua ORDEM na tabela. Se omitido, usa
            todas as chaves encontradas nos registros, na ordem de primeira
            aparição (união de todas as chaves — registros que não têm uma
            coluna específica ficam com célula vazia nela).

    Returns:
        Se ``caminho_saida`` foi informado: ``{"caminho_saida": ...,
        "tamanho_bytes": ...}``. Se omitido: ``{"nome_arquivo": ...,
        "conteudo_base64": ..., "tamanho_bytes": ...}``. Em ambos os casos,
        acrescido de ``formato``, ``total_registros_exportados``,
        ``colunas`` (lista efetivamente usada) e ``avisos``.

    Raises:
        ValueError: ``formato`` inválido; ``registros`` vazio; ou nenhuma
            coluna encontrada (registros vazios de conteúdo e
            ``nome_colunas`` não informado).
    """
    if formato not in _FORMATOS_VALIDOS:
        raise ValueError(f"formato deve ser um de {_FORMATOS_VALIDOS}, recebido: {formato!r}")
    if not registros:
        raise ValueError("registros não pode ser vazio — nada para exportar.")

    avisos: list[str] = []
    if len(registros) > _LIMITE_REGISTROS:
        avisos.append(
            f"registros tinha {len(registros)} item(ns) — truncado para os primeiros "
            f"{_LIMITE_REGISTROS} (limite de exportação por chamada)."
        )
        registros = registros[:_LIMITE_REGISTROS]

    registros_validos = [r for r in registros if isinstance(r, dict)]
    if len(registros_validos) < len(registros):
        avisos.append(
            f"{len(registros) - len(registros_validos)} item(ns) ignorado(s): não eram "
            "dicionários (registros deve ser uma lista de objetos/dicts)."
        )
    registros_achatados = [_achatar(r) for r in registros_validos]

    colunas = _montar_colunas(registros_achatados, nome_colunas)
    if not colunas:
        raise ValueError(
            "Nenhuma coluna encontrada — registros ficaram vazios após validação e "
            "nome_colunas não foi informado."
        )

    logger.info(
        "exportar_resultados formato=%s total_registros=%s colunas=%s caminho_saida=%s",
        formato, len(registros_achatados), len(colunas), bool(caminho_saida),
    )

    if formato == "csv":
        documento: Any = _DocumentoCsv(colunas, registros_achatados)
        extensao = "csv"
    else:
        documento = _montar_xlsx(colunas, registros_achatados)
        extensao = "xlsx"

    resultado = gravar_documento(
        documento,
        caminho_saida=caminho_saida,
        extensao=extensao,
        prefixo_nome="exportacao_resultados",
    )
    resultado["formato"] = formato
    resultado["total_registros_exportados"] = len(registros_achatados)
    resultado["colunas"] = colunas
    resultado["avisos"] = avisos
    return resultado
