"""Testes de avaliar_pesquisa_mercado.

O primeiro caso é o gabarito: os valores que o Excel calculou na planilha
"Avaliação de Pesquisa de Mercado" v5.3, com estes 5 preços (salvo em
26/11/2026). Os demais casos exercitam uma regra por vez.
"""
from __future__ import annotations

import pytest

from mcp_radardeprecos.tools.avaliar_pesquisa_mercado import (
    CREDITO,
    EXCESSIVO,
    INEXEQUIVEL,
    MEDIA,
    MEDIANA,
    PRECO_MINIMO,
    PRECO_UNICO,
    VALIDO,
    VALIDO_IGUAL,
    VALIDO_MAIOR,
    VALIDO_PUBLICO,
    avaliar_pesquisa_mercado,
)


def _preco(valor, tipo="FORNECEDOR", fonte="Fonte", localizador="1"):
    return {"fonte": fonte, "tipo": tipo, "localizador": localizador, "valor": valor}


def _item(*precos, **extra):
    return {"descricao": "Item de teste", "metrica": "unidade", "quantidade": 1, "precos": list(precos), **extra}


async def _avaliar(*precos, **opcoes):
    r = await avaliar_pesquisa_mercado(itens=[_item(*precos)], **opcoes)
    return r, r["itens"][0]


# --- Gabarito da planilha ---------------------------------------------------------


async def test_gabarito_da_planilha_cinco_precos_validos():
    r, item = await _avaliar(
        _preco(5300, "FORNECEDOR", "adsad", "1"),
        _preco(5100, "FORNECEDOR", "fsafsfgs", "2"),
        _preco(4980, "ATA", "saf", "3"),
        _preco(4900, "COMPRASNET", "sfasfs", "4"),
        _preco(4950, "COMPRASNET", "fs", "5"),
    )
    assert [p["avaliacao"] for p in item["precos"]] == [VALIDO] * 5
    assert [p["observacao"] for p in item["precos"]] == [""] * 5
    # EXORB.!H / INEXEQ.!E: preço / média dos demais
    assert [p["percentual_em_relacao_aos_demais"] for p in item["precos"]] == [106.37, 101.34, 98.37, 96.41, 97.63]
    assert [p["media_dos_demais"] for p in item["precos"]] == [4982.5, 5032.5, 5062.5, 5082.5, 5070.0]
    res = item["resultado"]
    assert res["metodo_aplicado"] == MEDIA                      # MET!G5
    assert res["preco_mercado"] == 5046                         # RELATÓRIO!G24
    assert res["media"] == 5046                                 # MET!G3
    assert res["desvio_padrao"] == pytest.approx(159.93748778819804, abs=1e-4)  # MET!G2
    assert res["coeficiente_variacao_percentual"] == 3.17       # MET!G4 = 0,0317
    assert res["mediana"] == 4980                               # MET!G8
    assert res["preco_minimo"] == 4900                          # MET!G11
    assert res["precos_validos"] == 5                           # RELATÓRIO!J36
    assert item["problemas"] == []                              # K32 e K36 "ok"
    assert item["status"] == "pronto"
    assert [p["tipo"] for p in item["precos"]][3:] == ["PNCP", "PNCP"]  # Comprasnet = PNCP
    assert r["credito"] == CREDITO


# --- Uma regra por vez ----------------------------------------------------------


async def test_excessivamente_elevado_sai_do_calculo():
    _, item = await _avaliar(_preco(100, "ATA"), _preco(100, "ATA"), _preco(100, "PNCP"), _preco(200))
    assert item["precos"][3]["avaliacao"] == EXCESSIVO
    assert item["precos"][3]["usado_no_calculo"] is False
    assert item["precos"][3]["observacao"] == "O valor é 100,00% superior à média dos demais preços."
    assert item["resultado"]["preco_mercado"] == 100


async def test_inexequivel_de_fornecedor_sai_do_calculo():
    _, item = await _avaliar(_preco(100, "ATA"), _preco(100, "ATA"), _preco(100, "PNCP"), _preco(60))
    assert item["precos"][3]["avaliacao"] == INEXEQUIVEL
    assert item["precos"][3]["observacao"] == "O valor é 60,00% da média dos demais preços."
    assert item["resultado"]["precos_validos"] == 3


async def test_inexequivel_publico_e_preservado_e_pode_levar_a_mediana():
    _, item = await _avaliar(_preco(100, "ATA"), _preco(100, "PNCP"), _preco(100, "CONTRATO"), _preco(40, "ATA"))
    p = item["precos"][3]
    assert p["avaliacao"] == VALIDO_PUBLICO and p["usado_no_calculo"] is True
    assert p["observacao"].startswith("O valor é inexequível (40,00% da média dos demais preços). Todavia")
    # 100, 100, 100, 40: CV de 35% > 25% -> mediana
    assert item["resultado"]["coeficiente_variacao_percentual"] == 35.29
    assert item["resultado"]["metodo_aplicado"] == MEDIANA
    assert item["resultado"]["preco_mercado"] == 100


async def test_inexequivel_igual_a_preco_publico_e_preservado():
    # Cinco preços de 100 seguram a média: 60 fica inexequível (60%), sem tornar os 100 excessivos.
    cem = [_preco(100, "PNCP")] * 3 + [_preco(100)] * 2
    _, item = await _avaliar(*cem, _preco(60, "ATA"), _preco(60))
    assert item["precos"][5]["avaliacao"] == VALIDO_PUBLICO
    assert item["precos"][6]["avaliacao"] == VALIDO_IGUAL
    assert item["precos"][6]["usado_no_calculo"] is True


async def test_maior_que_preco_publico_aparece_valido_mas_fica_fora_da_conta():
    """Comportamento da planilha: a estatística usa a "Parte 2" da avaliação 3."""
    cem = [_preco(100, "PNCP")] * 3 + [_preco(100)] * 2
    _, item = await _avaliar(*cem, _preco(50, "ATA"), _preco(65))
    p = item["precos"][6]
    assert p["avaliacao"] == VALIDO_MAIOR
    assert p["usado_no_calculo"] is False


async def test_sem_preservar_publicos_o_inexequivel_publico_sai():
    r, item = await _avaliar(_preco(100, "ATA"), _preco(100, "PNCP"), _preco(100, "CONTRATO"), _preco(40, "ATA"),
                             preservar_publicos_inexequiveis=False)
    assert item["precos"][3]["avaliacao"] == INEXEQUIVEL
    assert any("não foram preservados" in a for a in r["avisos"])


async def test_preco_minimo_por_opcao():
    _, item = await _avaliar(_preco(100, "ATA"), _preco(110, "PNCP"), _preco(105, "ATA"), usar_preco_minimo=True)
    assert item["resultado"]["metodo_aplicado"] == PRECO_MINIMO
    assert item["resultado"]["preco_mercado"] == 100


async def test_um_unico_preco_nao_tem_preco_de_mercado():
    _, item = await _avaliar(_preco(100, "ATA"))
    assert item["resultado"]["metodo_aplicado"] == PRECO_UNICO
    assert item["resultado"]["preco_mercado"] is None
    assert item["status"] == "poucos_precos"
    assert any("poucas fontes válidas" in x for x in item["problemas"])


async def test_fontes_publicas_precisam_ser_maioria():
    _, item = await _avaliar(_preco(100, "ATA"), _preco(101), _preco(102), _preco(103, "PNCP"))
    assert any("não são a maioria" in x and "(2 de 4)" in x for x in item["problemas"])


async def test_limite_de_cv_alterado_gera_aviso_e_muda_o_metodo():
    r, item = await _avaliar(_preco(100, "ATA"), _preco(100, "PNCP"), _preco(100, "CONTRATO"), _preco(40, "ATA"),
                             cv_maximo=0.40)
    assert item["resultado"]["metodo_aplicado"] == MEDIA
    assert any("coeficiente de variação máximo (40,00%)" in a and "justificada" in a for a in r["avisos"])


async def test_prorrogacao_com_preco_contratado_acima_do_mercado():
    r = await avaliar_pesquisa_mercado(
        itens=[_item(_preco(100, "ATA"), _preco(100, "PNCP"), _preco(100, "ATA"), preco_contratado=120)],
        prorrogacao=True,
    )
    assert r["itens"][0]["prorrogacao"] == {
        "preco_contratado": 120.0, "desvantajoso": True, "mensagem": "Preço contratado é desvantajoso. Negociar preços."
    }


async def test_varios_itens_somam_o_valor_total_e_versao_avanca():
    r = await avaliar_pesquisa_mercado(
        itens=[
            {"descricao": "Licença", "metrica": "usuário/ano", "quantidade": 30,
             "precos": [_preco(5300), _preco(5100), _preco(4980, "ATA"), _preco(4900, "PNCP"), _preco(4950, "PNCP")]},
            {"descricao": "Suporte", "metrica": "mês", "quantidade": 12, "precos": [_preco(1000, "ATA"), _preco(1100, "PNCP")]},
            {"descricao": "Treinamento", "metrica": "hora", "quantidade": 40, "precos": []},
        ],
        versao=3,
    )
    assert r["versao"] == 4
    assert r["itens"][0]["resultado"]["valor_total"] == 151380.0  # 5.046 x 30
    assert [i["status"] for i in r["itens"]] == ["pronto", "poucos_precos", "sem_precos"]
    assert r["resumo"] == {"total_itens": 3, "itens_prontos": 1, "valor_total_estimado": 151380.0 + 1050.0 * 12}


async def test_preco_sem_fonte_ou_tipo_fica_fora_com_aviso():
    r, item = await _avaliar(_preco(100, "ATA"), _preco(100, "PNCP"), _preco(100, "ATA"), _preco(90, "DESCONHECIDO"))
    assert item["precos"][3]["avaliacao"] == "INCOMPLETO"
    assert item["resultado"]["precos_validos"] == 3
    assert any("falta a fonte ou o tipo" in a for a in r["avisos"])


async def test_valor_em_texto_no_formato_brasileiro():
    _, item = await _avaliar(_preco("R$ 4.900,00", "ATA"), _preco("4900.50", "PNCP"), _preco(4901, "ATA"))
    assert [p["valor"] for p in item["precos"]] == [4900.0, 4900.5, 4901.0]


@pytest.mark.parametrize("kwargs, trecho", [
    ({"itens": []}, "pelo menos um item"),
    ({"itens": [_item(_preco(0))]}, "valor ausente ou inválido"),
    ({"itens": [_item(_preco(10))], "percentual_inexequivel": 1.2}, "percentual_inexequivel"),
    ({"itens": [_item(_preco(10))], "cv_maximo": 0}, "cv_maximo"),
])
async def test_entradas_invalidas_sao_recusadas(kwargs, trecho):
    with pytest.raises(ValueError, match=trecho):
        await avaliar_pesquisa_mercado(**kwargs)


@pytest.mark.parametrize("processo", ["00000.000123/2026-45", "SEI 123456", "123", "Proc. 7/2026 - lote A"])
async def test_processo_volta_sem_formatacao(processo):
    """O número do processo é texto livre: volta exatamente como foi informado."""
    r = await avaliar_pesquisa_mercado(itens=[_item(_preco(100, "ATA"))], processo=processo)
    assert r["processo"] == processo
