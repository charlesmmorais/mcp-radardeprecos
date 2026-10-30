"""Testes de `utils/arquivo_saida.py` — grava em disco ou serializa em base64."""
from __future__ import annotations

import base64

from mcp_radardeprecos.utils.arquivo_saida import gravar_documento


class _DocumentoFalso:
    """Simula a interface `.save(destino)` do python-docx/openpyxl."""

    def __init__(self, conteudo: bytes) -> None:
        self._conteudo = conteudo

    def save(self, destino) -> None:
        if isinstance(destino, (str,)):
            with open(destino, "wb") as f:
                f.write(self._conteudo)
        else:
            destino.write(self._conteudo)


def test_com_caminho_saida_grava_em_disco(tmp_path):
    doc = _DocumentoFalso(b"conteudo-teste")
    caminho = tmp_path / "saida.docx"

    resultado = gravar_documento(
        doc, caminho_saida=str(caminho), extensao="docx", prefixo_nome="relatorio"
    )

    assert resultado["caminho_saida"] == str(caminho.resolve()) or resultado["caminho_saida"].endswith("saida.docx")
    assert caminho.read_bytes() == b"conteudo-teste"
    assert resultado["tamanho_bytes"] == len(b"conteudo-teste")
    assert "nome_arquivo" not in resultado
    assert "conteudo_base64" not in resultado


def test_com_caminho_saida_cria_diretorios_intermediarios(tmp_path):
    doc = _DocumentoFalso(b"x")
    caminho = tmp_path / "sub1" / "sub2" / "saida.xlsx"

    gravar_documento(doc, caminho_saida=str(caminho), extensao="xlsx", prefixo_nome="relatorio")

    assert caminho.exists()


def test_sem_caminho_saida_devolve_base64_e_nome_unico(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    doc = _DocumentoFalso(b"conteudo-em-memoria")

    resultado = gravar_documento(doc, caminho_saida=None, extensao="docx", prefixo_nome="relatorio")

    assert "caminho_saida" not in resultado
    assert resultado["nome_arquivo"].startswith("relatorio_")
    assert resultado["nome_arquivo"].endswith(".docx")
    assert base64.b64decode(resultado["conteudo_base64"]) == b"conteudo-em-memoria"
    assert resultado["tamanho_bytes"] == len(b"conteudo-em-memoria")
    # nunca deve tocar o disco quando caminho_saida é omitido
    assert list(tmp_path.iterdir()) == []


def test_sem_caminho_saida_nomes_sao_unicos_entre_chamadas():
    doc = _DocumentoFalso(b"x")

    r1 = gravar_documento(doc, caminho_saida=None, extensao="docx", prefixo_nome="relatorio")
    r2 = gravar_documento(doc, caminho_saida=None, extensao="docx", prefixo_nome="relatorio")

    assert r1["nome_arquivo"] != r2["nome_arquivo"]


# --- Servidor hospedado (HTTP): caminho_saida recusado ---


def test_caminho_saida_recusado_quando_gravacao_desligada(tmp_path):
    import pytest

    from mcp_radardeprecos.utils import arquivo_saida

    arquivo_saida.permitir_gravacao_em_disco(False)
    caminho = tmp_path / "invasao.docx"

    with pytest.raises(ValueError, match="caminho_saida"):
        gravar_documento(
            _DocumentoFalso(b"x"), caminho_saida=str(caminho), extensao="docx", prefixo_nome="r"
        )
    assert not caminho.exists()


def test_base64_continua_funcionando_com_gravacao_desligada():
    from mcp_radardeprecos.utils import arquivo_saida

    arquivo_saida.permitir_gravacao_em_disco(False)
    resultado = gravar_documento(
        _DocumentoFalso(b"abc"), caminho_saida=None, extensao="xlsx", prefixo_nome="r"
    )
    assert base64.b64decode(resultado["conteudo_base64"]) == b"abc"


async def test_trilha_auditoria_recusa_caminho_saida_quando_desligada(tmp_path):
    import pytest

    from mcp_radardeprecos.tools.exportar_trilha_auditoria import exportar_trilha_auditoria
    from mcp_radardeprecos.utils import arquivo_saida

    arquivo_saida.permitir_gravacao_em_disco(False)
    caminho = tmp_path / "trilha.json"

    with pytest.raises(ValueError, match="caminho_saida"):
        await exportar_trilha_auditoria(caminho_saida=str(caminho))
    assert not caminho.exists()


def _rodar_http_mockado():
    from unittest.mock import patch

    from mcp_radardeprecos import server

    with (
        patch("mcp_radardeprecos.server.uvicorn"),
        patch("mcp_radardeprecos.server.anyio"),
    ):
        server._run_http("streamable-http", 60)


def test_run_http_desliga_gravacao_em_disco(monkeypatch):
    from mcp_radardeprecos.utils import arquivo_saida

    monkeypatch.delenv(arquivo_saida.ENV_PERMITIR_CAMINHO_SAIDA, raising=False)
    _rodar_http_mockado()
    assert arquivo_saida.gravacao_em_disco_permitida() is False


def test_run_http_respeita_opt_in_por_ambiente(monkeypatch):
    from mcp_radardeprecos.utils import arquivo_saida

    monkeypatch.setenv(arquivo_saida.ENV_PERMITIR_CAMINHO_SAIDA, "1")
    _rodar_http_mockado()
    assert arquivo_saida.gravacao_em_disco_permitida() is True
