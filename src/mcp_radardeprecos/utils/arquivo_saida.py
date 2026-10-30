"""Grava um documento gerado em memória (``.docx``/``.xlsx``) em disco OU em base64.

Usado pelas tools de relatório e exportação.

- **Com** ``caminho_saida``: grava no caminho dado (criando diretórios) e
  devolve ``caminho_saida``/``tamanho_bytes``. Só faz sentido quando o disco
  do servidor é o do usuário (stdio, ou HTTP na própria máquina); nos
  transportes HTTP é recusado por padrão (ver
  :func:`exigir_gravacao_em_disco_permitida`).
- **Sem** ``caminho_saida``: serializa em memória e devolve
  ``conteudo_base64`` com um ``nome_arquivo`` único (UUID4). Nada toca o
  disco do servidor, então não há colisão nem leitura cruzada entre
  usuários.
"""
from __future__ import annotations

import base64
import io
import os
import uuid
from typing import Any, Protocol

#: Variável de ambiente que reabilita ``caminho_saida`` nos transportes HTTP.
#: Só faz sentido quando o processo HTTP roda na máquina do próprio usuário
#: (ex.: túnel do modo desenvolvedor do ChatGPT).
ENV_PERMITIR_CAMINHO_SAIDA = "RADARDEPRECOS_PERMITIR_CAMINHO_SAIDA"

# Ligado por padrão (stdio: o disco é o do usuário). O servidor desliga ao
# subir em HTTP — ver ``server._run_http``.
_gravacao_em_disco_permitida = True


def permitir_gravacao_em_disco(permitir: bool) -> None:
    """Liga ou desliga a gravação em ``caminho_saida`` para todo o processo."""
    global _gravacao_em_disco_permitida
    _gravacao_em_disco_permitida = permitir


def gravacao_em_disco_permitida() -> bool:
    return _gravacao_em_disco_permitida


def exigir_gravacao_em_disco_permitida() -> None:
    """Recusa ``caminho_saida`` quando o servidor está hospedado.

    Num servidor HTTP compartilhado, aceitar um caminho do chamador deixaria
    qualquer cliente gravar em qualquer lugar do servidor.
    """
    if not _gravacao_em_disco_permitida:
        raise ValueError(
            "caminho_saida não é aceito neste servidor (transporte HTTP): o disco "
            "é o da VM do servidor, não o seu. Omita caminho_saida para receber o "
            "arquivo em base64 (conteudo_base64) e salvá-lo do seu lado."
        )


class _Salvavel(Protocol):
    def save(self, destino: Any) -> None: ...


def gravar_documento(
    documento: _Salvavel,
    *,
    caminho_saida: str | None,
    extensao: str,
    prefixo_nome: str,
) -> dict[str, Any]:
    """Grava ``documento`` (algo com ``.save(destino)``, ex.: ``docx.Document``/``openpyxl.Workbook``).

    Args:
        documento: Objeto com método ``save()`` aceitando um caminho
            (``str``) ou um objeto binário tipo arquivo (``io.BytesIO``) —
            ambos ``python-docx`` e ``openpyxl`` seguem essa interface.
        caminho_saida: Caminho de destino, ou ``None`` para gerar em
            memória e devolver em base64.
        extensao: Extensão do arquivo, sem ponto (ex.: ``"docx"``,
            ``"xlsx"``) — usada tanto para validar ``caminho_saida`` quanto
            para compor ``nome_arquivo`` quando ele é omitido.
        prefixo_nome: Prefixo usado para compor ``nome_arquivo`` quando
            ``caminho_saida`` é omitido (ex.: ``"relatorio_pesquisa_precos"``).

    Returns:
        Se ``caminho_saida`` foi informado: ``{"caminho_saida": <caminho
        absoluto>, "tamanho_bytes": <int>}``. Se omitido: ``{"nome_arquivo":
        <nome único com UUID>, "conteudo_base64": <str>, "tamanho_bytes":
        <int>}``.
    """
    if caminho_saida:
        exigir_gravacao_em_disco_permitida()
        diretorio = os.path.dirname(os.path.abspath(caminho_saida))
        if diretorio:
            os.makedirs(diretorio, exist_ok=True)
        try:
            documento.save(caminho_saida)
        except OSError as erro:
            raise RuntimeError(
                f"Não foi possível gravar o arquivo em {caminho_saida!r}: {erro}"
            ) from erro
        caminho_absoluto = os.path.abspath(caminho_saida)
        return {
            "caminho_saida": caminho_absoluto,
            "tamanho_bytes": os.path.getsize(caminho_absoluto),
        }

    buffer = io.BytesIO()
    documento.save(buffer)
    conteudo = buffer.getvalue()
    nome_arquivo = f"{prefixo_nome}_{uuid.uuid4().hex}.{extensao}"
    return {
        "nome_arquivo": nome_arquivo,
        "conteudo_base64": base64.b64encode(conteudo).decode("ascii"),
        "tamanho_bytes": len(conteudo),
    }
