"""Testes de gerar_pdf_avaliacao_pesquisa_mercado."""
from __future__ import annotations

import base64

import pytest
from reportlab import rl_config

from mcp_radardeprecos.tools import gerar_pdf_avaliacao_pesquisa_mercado as modulo
from mcp_radardeprecos.tools.gerar_pdf_avaliacao_pesquisa_mercado import (
    _moeda,
    gerar_pdf_avaliacao_pesquisa_mercado,
)


def _preco(valor, tipo="FORNECEDOR", fonte="Fonte", localizador="fl. 1"):
    return {"fonte": fonte, "tipo": tipo, "localizador": localizador, "valor": valor}


ITENS = [
    {"descricao": "Licença de uso", "metrica": "usuário/ano", "quantidade": 30, "precos": [
        _preco(5300), _preco(5100), _preco(4980, "ATA"), _preco(4900, "PNCP"), _preco(4950, "PNCP")]},
    {"descricao": "Suporte <24x7> & atualização", "metrica": "mês", "quantidade": 12,
     "precos": [_preco(1000, "ATA"), _preco(2000)]},
    {"descricao": "Consultoria", "metrica": "serviço", "quantidade": 1, "precos": []},
]


@pytest.fixture
def sem_compressao(monkeypatch):
    """PDF sem compressão, para procurar o texto nos bytes."""
    monkeypatch.setattr(rl_config, "pageCompression", 0)


async def _pdf(**kw) -> tuple[dict, bytes]:
    r = await gerar_pdf_avaliacao_pesquisa_mercado(itens=ITENS, **kw)
    return r, base64.b64decode(r["conteudo_base64"])


async def test_gera_pdf_em_base64_com_o_resumo_da_avaliacao():
    r, pdf = await _pdf(processo="00000.000123/2026-45", versao=4)
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    assert r["formato"] == "pdf"
    assert r["nome_arquivo"].endswith(".pdf")
    assert r["tamanho_bytes"] == len(pdf)
    assert r["versao"] == 4  # imprime a versão informada, não a seguinte
    assert r["resumo"] == {"total_itens": 3, "itens_prontos": 1, "valor_total_estimado": 151380.0}


async def test_pdf_traz_os_numeros_calculados_e_o_credito(sem_compressao):
    _, pdf = await _pdf(processo="00000.000123/2026-45", responsavel="Equipe de compras", versao=2)
    texto = pdf.decode("latin-1")
    for trecho in ("R$ 5.046,00", "R$ 151.380,00", "00000.000123/2026-45", "Equipe de compras",
                   "de 3", "Baseado na planilha de Avalia"):
        assert trecho in texto, trecho
    assert "STJ" in texto


async def test_texto_do_usuario_nao_vira_marcacao(sem_compressao):
    """"<24x7>" e "&" na descrição: sem escape, o ReportLab falharia ou sumiria com o texto."""
    _, pdf = await _pdf()
    texto = pdf.decode("latin-1")
    # O ReportLab desenha palavra a palavra; basta o trecho estar lá, sem escape duplo.
    assert "24x7" in texto and "(Suporte" in texto
    assert "&lt;" not in texto and "&amp;" not in texto


async def test_parametro_alterado_aparece_para_justificar(sem_compressao):
    r, pdf = await _pdf(cv_maximo=0.30)
    assert any("justificada" in a for a in r["avisos"])
    assert "padr" in pdf.decode("latin-1") and "justificar" in pdf.decode("latin-1")


async def test_grava_em_disco_no_modo_stdio(tmp_path):
    destino = tmp_path / "estudo.pdf"
    r = await gerar_pdf_avaliacao_pesquisa_mercado(itens=ITENS, caminho_saida=str(destino))
    assert destino.read_bytes().startswith(b"%PDF-")
    assert r["tamanho_bytes"] == destino.stat().st_size


async def test_estudo_invalido_e_recusado_antes_de_gerar():
    with pytest.raises(ValueError, match="pelo menos um item"):
        await gerar_pdf_avaliacao_pesquisa_mercado(itens=[])


@pytest.mark.parametrize("valor, esperado", [
    (5046, "R$ 5.046,00"), (151380.0, "R$ 151.380,00"), (91.666, "R$ 91,67"), (None, "—"),
])
def test_moeda_no_formato_brasileiro(valor, esperado):
    assert _moeda(valor) == esperado


def test_sem_logotipo():
    """Nada de imagem no relatório: o módulo não usa Image nem drawImage."""
    fonte = open(modulo.__file__, encoding="utf-8").read()
    assert "Image" not in fonte and "drawImage" not in fonte
