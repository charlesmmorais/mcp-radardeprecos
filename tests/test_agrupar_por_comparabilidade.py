"""Testes da tool agrupar_por_comparabilidade (pura)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos.tools.agrupar_por_comparabilidade import (
    agrupar_por_comparabilidade,
)

ALVO_M365 = {
    "termos_nucleo": ["microsoft 365", "e3"],
    "termos_variacao": ["sem teams", "without teams"],
    "termos_substituto": ["office 365 e3"],
    "metrica": "usuário",
    "modalidade": "subscrição",
}


async def test_dimensoes_invalidas_erro():
    with pytest.raises(ValueError):
        await agrupar_por_comparabilidade([{"descricao": "x"}], dimensoes=["cor"])


async def test_grau_A_identico_ao_alvo():
    regs = [{"descricao": "Microsoft 365 E3 subscrição por usuário",
             "unidade": "usuário", "quantidade": 50, "valor": 100}]
    r = await agrupar_por_comparabilidade(regs, alvo=ALVO_M365)
    assert r["resumo"]["A"] == 1
    assert r["grupos"][0]["grau"] == "A"
    assert r["grupos"][0]["registros"][0]["grau"] == "A"


async def test_grau_B_mesmo_produto_difere_em_variacao():
    regs = [{"descricao": "Microsoft 365 E3 sem Teams por usuário subscrição",
             "unidade": "usuário", "quantidade": 50, "valor": 90}]
    r = await agrupar_por_comparabilidade(regs, alvo=ALVO_M365)
    assert r["resumo"]["B"] == 1
    assert "variação" in r["grupos"][0]["registros"][0]["motivo_grau"]


async def test_grau_C_substituto():
    regs = [{"descricao": "Office 365 E3 por usuário subscrição mensal",
             "unidade": "usuário", "quantidade": 50, "valor": 80}]
    r = await agrupar_por_comparabilidade(regs, alvo=ALVO_M365)
    assert r["resumo"]["C"] == 1
    assert r["grupos"][0]["grau"] == "C"


async def test_grau_D_desqualificador_vai_para_nao_comparaveis():
    regs = [{"descricao": "Notebook com Microsoft 365 E3 incluído",
             "unidade": "unidade", "quantidade": 10, "valor": 5000}]
    r = await agrupar_por_comparabilidade(regs, alvo=ALVO_M365)
    assert r["resumo"]["D"] == 1
    assert r["grupos"] == []
    assert r["nao_comparaveis"][0]["grau"] == "D"
    assert "desqualificador" in r["nao_comparaveis"][0]["motivo"]


async def test_grau_D_nao_corresponde_ao_alvo():
    regs = [{"descricao": "Serviço de limpeza predial mensal continuado",
             "unidade": "mês", "quantidade": 12, "valor": 3000}]
    r = await agrupar_por_comparabilidade(regs, alvo=ALVO_M365)
    assert r["resumo"]["D"] == 1
    assert "não corresponde ao alvo" in r["nao_comparaveis"][0]["motivo"]


async def test_descricao_insuficiente_vira_D():
    r = await agrupar_por_comparabilidade([{"descricao": "M365", "valor": 100}], alvo=ALVO_M365)
    assert r["nao_comparaveis"][0]["grau"] == "D"
    assert "insuficiente" in r["nao_comparaveis"][0]["motivo"]


async def test_sem_alvo_agrupa_mas_nao_da_ABC():
    regs = [
        {"descricao": "Item qualquer bem descrito aqui", "unidade": "usuário",
         "quantidade": 5, "valor": 10},
        {"descricao": "Outro item também bem descrito", "unidade": "usuário",
         "quantidade": 8, "valor": 12},
    ]
    r = await agrupar_por_comparabilidade(regs)
    assert r["resumo"]["sem_classificacao"] == 2
    # mesma unidade + mesma faixa (1-9) → um único grupo
    assert len(r["grupos"]) == 1
    assert r["grupos"][0]["grau"] is None
    assert any("Sem 'alvo'" in a for a in r["avisos"])


async def test_faixa_de_quantidade_separa_grupos():
    regs = [
        {"descricao": "Microsoft 365 E3 subscrição usuário", "unidade": "usuário",
         "quantidade": 5, "valor": 100},
        {"descricao": "Microsoft 365 E3 subscrição usuário", "unidade": "usuário",
         "quantidade": 500, "valor": 80},
    ]
    r = await agrupar_por_comparabilidade(regs, alvo=ALVO_M365)
    # mesmo grau A, mas faixas 1-9 e 100-999 → dois grupos
    assert len(r["grupos"]) == 2
    faixas = {g["chave"]["faixa_quantidade"] for g in r["grupos"]}
    assert faixas == {"1-9", "100-999"}


async def test_estatistica_e_aviso_cv_alto():
    regs = [
        {"descricao": "Microsoft 365 E3 subscrição usuário", "unidade": "usuário",
         "quantidade": 50, "valor": v}
        for v in (100, 105, 900)  # dispersão alta → CV > 25%
    ]
    r = await agrupar_por_comparabilidade(regs, alvo=ALVO_M365)
    grupo = r["grupos"][0]
    assert grupo["estatistica"]["n"] == 3
    assert grupo["estatistica"]["cv_percent"] > 25
    assert any("CV" in a for a in r["avisos"])


async def test_aviso_amostra_pequena():
    regs = [{"descricao": "Microsoft 365 E3 subscrição usuário", "unidade": "usuário",
             "quantidade": 50, "valor": 100}]
    r = await agrupar_por_comparabilidade(regs, alvo=ALVO_M365)
    # amostra pequena agora é alerta POR GRUPO; o grupo também não é
    # confiável para cálculo (n < 3).
    grupo = r["grupos"][0]
    assert grupo["confiavel_para_calculo"] is False
    assert any("amostra pequena" in a for a in grupo["alertas"])


async def test_unidade_divergente_do_alvo_rebaixa_de_A_para_C():
    # Regressão: num teste de "limpeza predial", um
    # INSUMO (sabonete, unidade "frasco") entrava como grau A junto do SERVIÇO
    # (unidade "posto"), só por citar o termo do objeto. Com alvo declarando a
    # unidade, o insumo cai para C.
    alvo = {"termos_nucleo": ["limpeza predial"], "unidade": "posto"}
    regs = [
        {"descricao": "Serviço de limpeza predial continuada", "unidade": "posto",
         "quantidade": 10, "valor": 8000},
        {"descricao": "Sabonete líquido para limpeza predial", "unidade": "frasco",
         "quantidade": 200, "valor": 5},
    ]
    r = await agrupar_por_comparabilidade(regs, alvo=alvo)
    graus = {reg["descricao"].split()[0].lower(): g["grau"]
             for g in r["grupos"] for reg in g["registros"]}
    assert graus["serviço"] == "A"
    assert graus["sabonete"] == "C"  # unidade divergente → rebaixado


async def test_grupo_A_com_cv_alto_nao_e_confiavel():
    # Regressão: contrato global anual entrava como "A idêntico"
    # com CV de 180%+, sem sinalizar. Agora o grupo é marcado não-confiável.
    alvo = {"termos_nucleo": ["limpeza predial"], "unidade": "posto"}
    regs = [
        {"descricao": "Limpeza predial posto", "unidade": "posto", "quantidade": 5, "valor": v}
        for v in (8000, 8200, 250000)  # o global anual dispara CV altíssimo
    ]
    r = await agrupar_por_comparabilidade(regs, alvo=alvo)
    grupo = r["grupos"][0]
    assert grupo["grau"] == "A"  # o grau textual continua A (descrição bate)
    assert grupo["estatistica"]["cv_percent"] > 25
    assert grupo["homogeneo"] is False
    assert grupo["confiavel_para_calculo"] is False
    assert any("CV" in a for a in grupo["alertas"])
    assert any("confiáveis" in a for a in r["avisos"])
    # v0.3.16: rótulo deixa explícito que grau A não é utilizável para cálculo.
    assert "NÃO utilizável para cálculo" in grupo["rotulo"]
    assert grupo["grau"] == "A" and "textual" in grupo["rotulo"]
    # v0.3.17: aptidão visível no resumo (nenhum grupo confiável neste caso).
    assert r["resumo"]["grupos_total"] == 1
    assert r["resumo"]["grupos_confiaveis_para_calculo"] == 0


async def test_grupo_homogeneo_e_confiavel_quando_precos_proximos():
    # (não uso "notebook" aqui porque está nos desqualificadores padrão →
    # cairia em D; uso M365, que classifica como A.)
    alvo = {"termos_nucleo": ["microsoft 365", "e3"], "unidade": "usuario"}
    regs = [
        {"descricao": "Microsoft 365 E3 subscrição usuário", "unidade": "usuario",
         "quantidade": 50, "valor": v}
        for v in (100, 105, 110)
    ]
    r = await agrupar_por_comparabilidade(regs, alvo=alvo)
    grupo = r["grupos"][0]
    assert grupo["grau"] == "A"
    assert grupo["homogeneo"] is True
    assert grupo["confiavel_para_calculo"] is True
    assert grupo["alertas"] == []


async def test_mapeamento_de_campos_e_valor_normalizado():
    regs = [{"objeto": "Microsoft 365 E3 subscrição usuário", "unid": "usuário",
             "quantidade": 50, "valor_normalizado": 167.19}]
    r = await agrupar_por_comparabilidade(
        regs, alvo=ALVO_M365, campos={"descricao": "objeto", "unidade": "unid"}
    )
    assert r["grupos"][0]["estatistica"]["media"] == pytest.approx(167.19, abs=1e-2)
    assert r["grupos"][0]["chave"]["unidade"] == "usuario"
