"""Testes de `gerar_relatorio_excel` (tool quase pura — só grava um arquivo)."""
from __future__ import annotations

import base64
import io

import pytest
from openpyxl import load_workbook

from mcp_radardeprecos.tools.gerar_relatorio_excel import gerar_relatorio_excel

_RESULTADO_CALCULO = {
    "metodo_utilizado": "media_saneada",
    "preco_referencia": 98.5,
    "amostra_original": {"quantidade": 6, "valores": [100.0, 95.0, 98.0, 102.0, 97.0, 350.0]},
    "amostra_saneada": [100.0, 95.0, 98.0, 102.0, 97.0],
    "valores_excluidos": [350.0],
    "iteracoes_saneamento": 1,
    "estatisticas": {
        "media": 98.4,
        "mediana": 98.0,
        "minimo": 95.0,
        "maximo": 102.0,
        "desvio_padrao": 2.42,
        "coeficiente_variacao_percentual": 2.46,
    },
    "avisos": [],
}

_MEMORIA = {
    "objeto": "Notebook corporativo",
    "agente_responsavel": "Fulano de Tal - Analista",
    "data_pesquisa": "2026-07-04",
    "metodologia": {
        "metodo_utilizado": "media_saneada",
        "preco_referencia": 98.5,
        "estatisticas": _RESULTADO_CALCULO["estatisticas"],
    },
    "fontes_consultadas": [
        {
            "informante": "Fornecedor A",
            "cnpj": "11111111000111",
            "meio_consulta": "PNCP - contratação",
            "valor_unitario": 100.0,
            "quantidade": 5,
            "data_referencia": "2026-05-01",
            "especificacao": "Notebook i7 16GB",
            "condicoes": "Entrega em 30 dias",
            "url": "https://pncp.gov.br/exemplo",
        },
        {
            "informante": "Fornecedor B",
            "meio_consulta": "Compras.gov.br",
            "valor_unitario": 95.0,
            "data_referencia": "2026-05-02",
        },
    ],
    "quantidade_fontes": 2,
    "buscas_frustradas": [
        {"meio_consulta": "Painel de Preços", "termo_busca": "notebook", "motivo": "sem resultado"}
    ],
    "avisos": ["Amostra pequena — considerar ampliar."],
}


async def test_rejeita_caminho_sem_extensao_xlsx(tmp_path):
    with pytest.raises(ValueError, match="xlsx"):
        await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO, str(tmp_path / "saida.txt"))


async def test_rejeita_caminho_vazio():
    with pytest.raises(ValueError):
        await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO, "")


async def test_rejeita_memoria_sem_campos_esperados(tmp_path):
    with pytest.raises(ValueError, match="gerar_memoria_pesquisa"):
        await gerar_relatorio_excel({"algo": 1}, _RESULTADO_CALCULO, str(tmp_path / "saida.xlsx"))


async def test_rejeita_resultado_calculo_sem_campos_esperados(tmp_path):
    with pytest.raises(ValueError, match="calcular_preco_referencia"):
        await gerar_relatorio_excel(_MEMORIA, {"algo": 1}, str(tmp_path / "saida.xlsx"))


async def test_rejeita_modelo_invalido(tmp_path):
    with pytest.raises(ValueError, match="modelo"):
        await gerar_relatorio_excel(
            _MEMORIA, _RESULTADO_CALCULO, str(tmp_path / "saida.xlsx"), modelo="xyz"
        )


@pytest.mark.parametrize("modelo", ["tic_licitacao", "tic_inexigibilidade"])
async def test_modelos_tic_preparados_mas_nao_implementados(tmp_path, modelo):
    with pytest.raises(NotImplementedError, match=modelo):
        await gerar_relatorio_excel(
            _MEMORIA, _RESULTADO_CALCULO, str(tmp_path / "saida.xlsx"), modelo=modelo
        )


async def test_gera_arquivo_com_4_abas_na_ordem_esperada(tmp_path):
    caminho = tmp_path / "relatorio.xlsx"
    resultado = await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO, str(caminho))

    assert caminho.exists()
    assert resultado["modelo"] == "in65"
    assert resultado["abas"] == [
        "Mapa de Pesquisa", "Fontes e Evidências", "Análise Estatística", "Avisos e Pendências",
    ]
    assert resultado["tamanho_bytes"] == caminho.stat().st_size


async def test_cria_diretorios_intermediarios(tmp_path):
    caminho = tmp_path / "sub1" / "sub2" / "relatorio.xlsx"
    resultado = await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO, str(caminho))
    assert caminho.exists()
    assert resultado["caminho_saida"] == str(caminho)


async def test_aba_mapa_pesquisa_contem_dados_principais(tmp_path):
    caminho = tmp_path / "relatorio.xlsx"
    await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO, str(caminho))

    wb = load_workbook(caminho)
    ws = wb["Mapa de Pesquisa"]
    valores = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    texto = " | ".join(valores)
    assert "Notebook corporativo" in texto
    assert "Fulano de Tal - Analista" in texto
    assert "media_saneada" in texto
    assert "98.5" in texto


async def test_aba_fontes_lista_fontes_e_buscas_frustradas(tmp_path):
    caminho = tmp_path / "relatorio.xlsx"
    await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO, str(caminho))

    wb = load_workbook(caminho)
    ws = wb["Fontes e Evidências"]
    valores = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    texto = " | ".join(valores)
    assert "Fornecedor A" in texto
    assert "Fornecedor B" in texto
    assert "Buscas sem resultado" in texto
    assert "sem resultado" in texto


async def test_aba_fontes_marca_pendencia_quando_fonte_sem_url_e_sem_evidencia(tmp_path):
    # "Fornecedor B" em _MEMORIA não tem "url" nem "evidencia_acesso".
    caminho = tmp_path / "relatorio.xlsx"
    await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO, str(caminho))

    wb = load_workbook(caminho)
    ws = wb["Fontes e Evidências"]
    cabecalho = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    assert "URL / Evidência de Acesso" in cabecalho
    col_evidencia = cabecalho.index("URL / Evidência de Acesso") + 1

    # Fornecedor A (linha 2) tem url; Fornecedor B (linha 3) não tem nada.
    celula_a = ws.cell(row=2, column=col_evidencia)
    celula_b = ws.cell(row=3, column=col_evidencia)
    assert celula_a.value == "https://pncp.gov.br/exemplo"
    assert celula_b.value == "[PENDÊNCIA: informar URL (PNCP/Compras.gov.br) ou evidência de acesso]"
    assert celula_b.fill.fgColor.rgb == "00FFC7CE"
    assert celula_a.fill.fgColor.rgb != "00FFC7CE"


async def test_aba_fontes_evidencia_acesso_aparece_quando_sem_url(tmp_path):
    memoria = {
        **_MEMORIA,
        "fontes_consultadas": [
            {
                "informante": "Fornecedor Direto",
                "meio_consulta": "Cotação direta",
                "valor_unitario": 97.0,
                "data_referencia": "2026-05-04",
                "evidencia_acesso": "E-mail de cotação anexado ao processo, fls. 20-22",
            }
        ],
        "quantidade_fontes": 1,
    }
    caminho = tmp_path / "relatorio.xlsx"
    await gerar_relatorio_excel(memoria, _RESULTADO_CALCULO, str(caminho))

    wb = load_workbook(caminho)
    ws = wb["Fontes e Evidências"]
    cabecalho = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    col_evidencia = cabecalho.index("URL / Evidência de Acesso") + 1
    celula = ws.cell(row=2, column=col_evidencia)
    assert celula.value == "E-mail de cotação anexado ao processo, fls. 20-22"
    assert celula.fill.fgColor.rgb != "00FFC7CE"


async def test_aba_analise_estatistica_marca_valor_excluido(tmp_path):
    caminho = tmp_path / "relatorio.xlsx"
    await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO, str(caminho))

    wb = load_workbook(caminho)
    ws = wb["Análise Estatística"]
    linhas_com_350 = [
        row for row in ws.iter_rows()
        if any(c.value == 350.0 for c in row)
    ]
    assert len(linhas_com_350) == 1
    linha = linhas_com_350[0]
    valores_da_linha = [c.value for c in linha]
    assert "Excluído no saneamento" in valores_da_linha


async def test_aba_avisos_inclui_avisos_e_pendencias_padrao(tmp_path):
    caminho = tmp_path / "relatorio.xlsx"
    await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO, str(caminho))

    wb = load_workbook(caminho)
    ws = wb["Avisos e Pendências"]
    valores = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    texto = " | ".join(valores)
    assert "Amostra pequena" in texto
    assert "Pendência de preenchimento humano" in texto


# --- Modo hospedado: caminho_saida omitido -> base64 em memória ---


async def test_sem_caminho_saida_devolve_base64_em_vez_de_gravar_no_disco(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    resultado = await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO)

    assert "caminho_saida" not in resultado
    assert "nome_arquivo" in resultado
    assert resultado["nome_arquivo"].startswith("relatorio_pesquisa_precos_")
    assert resultado["nome_arquivo"].endswith(".xlsx")
    assert resultado["tamanho_bytes"] > 0
    assert list(tmp_path.iterdir()) == []


async def test_sem_caminho_saida_base64_decodifica_para_xlsx_valido():
    resultado = await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO)

    conteudo = base64.b64decode(resultado["conteudo_base64"])
    assert len(conteudo) == resultado["tamanho_bytes"]

    wb = load_workbook(io.BytesIO(conteudo))
    assert wb["Mapa de Pesquisa"]["A1"].value == "Mapa de Pesquisa de Preços"


async def test_dois_arquivos_gerados_sem_caminho_saida_tem_nomes_diferentes():
    r1 = await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO)
    r2 = await gerar_relatorio_excel(_MEMORIA, _RESULTADO_CALCULO)

    assert r1["nome_arquivo"] != r2["nome_arquivo"]
