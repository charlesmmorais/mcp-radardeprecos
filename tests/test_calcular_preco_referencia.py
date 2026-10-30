"""Testes de `calcular_preco_referencia` (tool pura, sem chamada de rede)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos.tools.calcular_preco_referencia import (
    MotivoParadaSaneamento,
    calcular_preco_referencia,
)


def _avisos_de_calculo(resultado: dict) -> list[str]:
    """Avisos referentes ao CÁLCULO, ignorando o de homogeneidade de unidade.

    A partir da v0.5.6 toda chamada sem `serie_homogenea` recebe um aviso
    sobre unidade — informação de PROVENIÊNCIA, não de estatística. Os testes
    deste módulo verificam o cálculo, e por isso filtram esse aviso em vez de
    exigir lista vazia, o que os faria falhar todos por um motivo alheio ao
    que cada um verifica.
    """
    return [
        a for a in resultado["avisos"] if "Homogeneidade de unidade NÃO informada" not in a
    ]


async def test_rejeita_lista_vazia():
    with pytest.raises(ValueError):
        await calcular_preco_referencia([])


async def test_rejeita_precos_nao_positivos():
    with pytest.raises(ValueError):
        await calcular_preco_referencia([10.0, 0, 5.0])
    with pytest.raises(ValueError):
        await calcular_preco_referencia([10.0, -5.0])


async def test_rejeita_metodo_desconhecido():
    with pytest.raises(ValueError):
        await calcular_preco_referencia([10.0, 11.0, 9.0], metodo="media")


async def test_media_saneada_sem_outliers_nao_exclui_nada():
    # Distribuição simétrica (+-0.1 em torno de 10.0): todos os pontos ficam
    # exatamente nos limites [media - dp, media + dp], nenhum é expurgado.
    precos = [9.9, 10.1, 9.9, 10.1]
    # v0.5.17: `metodo` explícito — o padrão passou a ser o escore Z.
    resultado = await calcular_preco_referencia(precos, metodo="media_saneada")

    assert resultado["metodo_utilizado"] == "media_saneada"
    assert resultado["valores_excluidos"] == []
    assert resultado["iteracoes_saneamento"] == 0
    assert resultado["amostra_saneada"] == precos
    assert resultado["preco_referencia"] == pytest.approx(sum(precos) / len(precos), abs=1e-4)
    # v0.5.6: quem não informa `serie_homogenea` está SUPONDO que os preços
    # estão na mesma unidade. A tool recebe uma lista de números e não tem como
    # verificar — o silêncio anterior fazia a suposição passar por verificação.
    # Asserção pela PROPRIEDADE (nenhum aviso de cálculo), não por igualdade de
    # texto, que quebraria a cada ajuste de redação.
    assert _avisos_de_calculo(resultado) == []


async def test_media_saneada_remove_outlier_evidente():
    # 50.0 está muito acima do restante (~10) e deve ser expurgado pela
    # faixa média ± desvio-padrão.
    precos = [10.0, 10.5, 9.8, 10.2, 50.0]
    resultado = await calcular_preco_referencia(precos)

    assert 50.0 in resultado["valores_excluidos"]
    assert 50.0 not in resultado["amostra_saneada"]
    assert resultado["iteracoes_saneamento"] >= 1
    # Após remover o outlier, a referência deve ficar próxima da faixa dos
    # valores homogêneos (~10), bem longe do valor expurgado.
    assert resultado["preco_referencia"] < 15.0


async def test_saneamento_nao_reduz_abaixo_de_tres_media_saneada():
    # v0.4.1: piso de 3. [1, 2, 3, 100] — a média saneada removeria o 100
    # (fora de média±dp); depois, com [1,2,3] e CV ainda alto, PARA (não
    # reduz abaixo de 3), mantendo 3 valores e sinalizando o CV alto.
    resultado = await calcular_preco_referencia([1.0, 2.0, 3.0, 100.0])
    assert len(resultado["amostra_saneada"]) >= 3
    assert any("mínimo de 3" in a for a in resultado["avisos"])


async def test_media_saneada_aviso_amostra_pequena():
    resultado = await calcular_preco_referencia([10.0, 12.0])
    assert any("abaixo do mínimo de 3" in a for a in resultado["avisos"])
    # v0.4.1: o aviso empurra para ampliar/normalizar/agrupar, não para "trocar o método".
    assert any("NÃO resolve amostra pequena" in a for a in resultado["avisos"])


async def test_media_saneada_aviso_cv_alto_quando_amostra_nao_pode_ser_saneada():
    # Só 3 valores muito dispersos (10, 20, 30): o algoritmo detecta que
    # sanear deixaria apenas 1 elemento (degenerado) e preserva a amostra
    # original — o CV final (40.8%) fica acima do limite de 25% e gera aviso.
    resultado = await calcular_preco_referencia([10.0, 20.0, 30.0])
    assert resultado["iteracoes_saneamento"] == 0
    assert resultado["valores_excluidos"] == []
    # v0.5.15: era 40,82 (desvio populacional). Com a convenção amostral
    # unificada, pstdev([10,20,30])=8,165 vira stdev=10,0 e o CV vai a 50,0%.
    # O número mudou; a propriedade que o teste protege — CV acima do limite
    # gera aviso — é a mesma.
    assert resultado["estatisticas"]["coeficiente_variacao_percentual"] == pytest.approx(50.0, abs=0.01)
    assert any("Coeficiente de Variação" in a for a in resultado["avisos"])


async def test_mediana_reproduz_exemplo_do_guia():
    # Exemplo literal do guia "Pesquisa de preços — um guia prático de
    # sobrevivência": preços (1.50, 2.20, 3.50, 4.00, 10.00) -> mediana 3.50
    # (a média simples seria 4.24).
    resultado = await calcular_preco_referencia(
        [1.50, 2.20, 3.50, 4.00, 10.00], metodo="mediana"
    )
    assert resultado["metodo_utilizado"] == "mediana"
    assert resultado["preco_referencia"] == pytest.approx(3.50)
    assert resultado["estatisticas"]["media"] == pytest.approx(4.24)
    # Mediana não aplica saneamento: amostra final == amostra original.
    assert resultado["amostra_saneada"] == [1.50, 2.20, 3.50, 4.00, 10.00]
    assert resultado["valores_excluidos"] == []
    assert resultado["iteracoes_saneamento"] == 0


async def test_minimo_retorna_menor_valor_e_avisa():
    resultado = await calcular_preco_referencia([12.0, 9.5, 15.0], metodo="minimo")
    assert resultado["metodo_utilizado"] == "minimo"
    assert resultado["preco_referencia"] == 9.5
    assert any("mercados com poucos fornecedores" in a for a in resultado["avisos"])


async def test_amostra_original_preserva_valores_informados():
    precos = [20.0, 22.0, 19.5]
    resultado = await calcular_preco_referencia(precos)
    assert resultado["amostra_original"]["quantidade"] == 3
    assert resultado["amostra_original"]["valores"] == precos


async def test_escore_z_reproduz_exemplo_oficial_do_ippc_tic():
    # Exemplo literal do IPPC-TIC (AGU/MGI, 2024, p. 71 — "Item 02"): CV
    # inicial 40,12%, 4 iterações removendo 1 valor por vez pelo maior
    # |Escore Z| (18.14, depois 4.20, depois 6.24), até CV 14,48%.
    precos = [10.18, 9.92, 12.50, 12.11, 6.24, 14.00, 4.20, 18.14]
    resultado = await calcular_preco_referencia(precos, metodo="escore_z")

    assert resultado["metodo_utilizado"] == "escore_z"
    assert resultado["iteracoes_saneamento"] == 3
    # Remoção de 1 valor por iteração — nunca em lote.
    assert resultado["valores_excluidos"] == [18.14, 4.20, 6.24]
    assert resultado["amostra_saneada"] == [10.18, 9.92, 12.50, 12.11, 14.00]
    assert resultado["estatisticas"]["coeficiente_variacao_percentual"] == pytest.approx(
        14.48, abs=0.01
    )
    assert resultado["preco_referencia"] == pytest.approx(11.742, abs=1e-3)
    # v0.5.6: quem não informa `serie_homogenea` está SUPONDO que os preços
    # estão na mesma unidade. A tool recebe uma lista de números e não tem como
    # verificar — o silêncio anterior fazia a suposição passar por verificação.
    # Asserção pela PROPRIEDADE (nenhum aviso de cálculo), não por igualdade de
    # texto, que quebraria a cada ajuste de redação.
    assert _avisos_de_calculo(resultado) == []


async def test_escore_z_sem_outliers_nao_exclui_nada():
    precos = [9.9, 10.1, 9.9, 10.1]
    resultado = await calcular_preco_referencia(precos, metodo="escore_z")

    assert resultado["metodo_utilizado"] == "escore_z"
    assert resultado["valores_excluidos"] == []
    assert resultado["iteracoes_saneamento"] == 0
    assert resultado["amostra_saneada"] == precos
    assert resultado["preco_referencia"] == pytest.approx(sum(precos) / len(precos), abs=1e-4)


async def test_escore_z_remove_um_por_vez_nao_em_lote():
    # Dois outliers de magnitude parecida (2.0 e 50.0) ao lado de uma amostra
    # homogênea (~10): a Média Saneada (lote) removeria os dois na mesma
    # iteração; o Escore Z deve remover só o de maior |Z| por vez.
    precos = [10.0, 10.5, 9.8, 10.2, 2.0, 50.0]
    resultado = await calcular_preco_referencia(precos, metodo="escore_z")

    assert resultado["metodo_utilizado"] == "escore_z"
    assert resultado["iteracoes_saneamento"] >= 2
    assert 50.0 not in resultado["amostra_saneada"]
    assert 2.0 not in resultado["amostra_saneada"]
    # Confirma remoção individual: a primeira iteração descarta só 1 valor.
    assert len(resultado["valores_excluidos"]) == resultado["iteracoes_saneamento"]


async def test_escore_z_aviso_amostra_pequena():
    resultado = await calcular_preco_referencia([10.0, 12.0], metodo="escore_z")
    assert any("abaixo do mínimo de 3" in a for a in resultado["avisos"])


async def test_escore_z_nao_reduz_abaixo_de_tres():
    # v0.4.1: o Escore Z NÃO reduz a amostra abaixo do mínimo de 3, mesmo com
    # CV alto. Antes, [10,20,30] virava [20,30] (2 valores) para tentar baixar
    # o CV; agora para em 3, mantém a amostra e sinaliza o CV alto (a amostra
    # é heterogênea — o certo é separar/normalizar, não degenerar a amostra).
    resultado = await calcular_preco_referencia([10.0, 20.0, 30.0], metodo="escore_z")
    assert resultado["iteracoes_saneamento"] == 0
    assert resultado["valores_excluidos"] == []
    assert resultado["amostra_saneada"] == [10.0, 20.0, 30.0]
    # v0.5.19: o texto passou a ser um aviso único, com o motivo real da
    # parada. A propriedade protegida — CV alto é sinalizado — é a mesma.
    assert any("não deve ser considerada homogênea" in a.lower() for a in resultado["avisos"])


# ===========================================================================
# v0.5.12 — o saneamento parava por guarda de segurança, não por critério
# ===========================================================================
#
# Reportado após comparação com um cálculo independente: a exclusão era
# sistematicamente muito maior que a de um corte em bloco em média ± 1 dp.
#
# Medido em 08/09/2026, amostra lognormal de 200 preços, CV inicial 37,1%:
# o corte em bloco de um passe retinha 150 valores (75%) com CV 21,0%; o
# `_sanear_amostra` de então retinha 4 (2%) com CV 0,1%.
#
# A causa é que a parada documentada — "repete até não haver mais exclusões"
# — é inalcançável. Cortar em média ± 1 dp remove ~32% de qualquer amostra
# contínua; o que sobra é truncado, o dp encolhe, e a faixa seguinte é mais
# estreita: de novo ~30-44% cai fora. O laço só terminava ao bater no teto de
# 10 iterações ou no piso de 3 valores — dois LIMITES DE SEGURANÇA decidindo
# o resultado da ferramenta.
#
# O agravante não é o corte, é o relato: o CV final baixíssimo era exibido
# como indicador de qualidade quando é o sintoma. Quanto menor o CV devolvido,
# mais da amostra havia sido consumida.


def _lognormal(n: int, semente: int = 42) -> list[float]:
    import random

    rnd = random.Random(semente)
    return [round(rnd.lognormvariate(3, 0.35), 2) for _ in range(n)]


async def test_media_saneada_e_passe_unico_e_nao_devora_a_amostra():
    """A regressão central: 200 preços não podem virar 4.

    O número exigido aqui não é arbitrário — é o do corte em bloco de um
    passe, que é o que a ferramenta anuncia e o que o cálculo comparativo
    independente produz.
    """
    precos = _lognormal(200)
    r = await calcular_preco_referencia(precos, metodo="media_saneada")

    assert r["iteracoes_saneamento"] == 1, "média saneada é UM passe, não um laço"
    assert len(r["amostra_saneada"]) >= 0.60 * len(precos), (
        "o corte em bloco em média ± 1 dp retém ~70-75% de uma amostra contínua; "
        "reter muito menos significa que o corte foi reaplicado sobre a amostra "
        "já truncada"
    )
    assert r["motivo_parada_saneamento"] in ("passe_unico_concluido", "meta_nao_atingida"), (
        "um passe pode ou não alcançar a meta; o que não pode é reaplicar o corte"
    )


async def test_cv_baixo_demais_denuncia_amostra_consumida():
    """Guarda contra o exagero oposto ao ruído: CV como sintoma, não prêmio.

    Este teste falharia no comportamento antigo, que devolvia CV 0,1% — e é
    justamente o valor que passava por excelente. Um CV próximo de zero numa
    amostra grande de preços públicos não é homogeneidade: é o que sobra
    depois de remover quase tudo.
    """
    r = await calcular_preco_referencia(_lognormal(200))
    assert r["estatisticas"]["coeficiente_variacao_percentual"] > 5.0


async def test_escore_z_nao_para_na_decima_exclusao():
    """Regressão: um teto fixo de 10 iterações interrompia amostras grandes.

    Esta série de 200 preços precisa de 38 exclusões (19%) para chegar à meta;
    com o teto, parava na 10ª com o CV ainda acima de 25%.
    """
    r = await calcular_preco_referencia(_lognormal(200), metodo="escore_z")
    assert r["motivo_parada_saneamento"] == "meta_cv_atingida"
    assert r["iteracoes_saneamento"] == 38
    assert r["cv_final_percentual"] <= 25.0
    assert not any("acima de 20%" in a for a in r["avisos"]), "19% fica abaixo do alerta"


async def test_catmat_267203_chega_a_meta_sem_teto():
    """Caso real que expôs o teto: 378 preços de comprimido de dipirona 500 mg.

    Dados gravados da fonte em 30/10/2026 (tests/dados). São necessárias 49
    exclusões (13%) para o CV cair abaixo de 25%.
    """
    import json
    from pathlib import Path

    dados = json.loads(
        (Path(__file__).parent / "dados" / "catmat_267203_comprimidos.json").read_text(
            encoding="utf-8"
        )
    )
    r = await calcular_preco_referencia(dados["precos"], metodo="escore_z")
    assert r["amostra_original"]["quantidade"] == 378
    assert r["motivo_parada_saneamento"] == "meta_cv_atingida"
    assert r["iteracoes_saneamento"] == 49
    assert r["cv_final_percentual"] <= 25.0
    assert r["percentual_excluido"] == pytest.approx(12.96, abs=0.01)


async def test_exclusao_acima_de_20_por_cento_gera_aviso():
    """Série que só fica homogênea descartando muito: o número sai, com aviso."""
    serie = [100.0 + i for i in range(20)] + [
        150.0, 190.0, 240.0, 300.0, 380.0, 470.0, 600.0, 800.0,
    ]
    r = await calcular_preco_referencia(serie, metodo="escore_z", serie_homogenea=True)
    assert r["motivo_parada_saneamento"] == "meta_cv_atingida"
    assert r["iteracoes_saneamento"] == 6
    assert r["percentual_excluido"] > 20.0
    assert any("acima de 20%" in a for a in r["avisos"])


async def test_parada_por_guarda_aparece_nos_avisos():
    """Um limite de segurança que age precisa dizer que agiu — não só num campo."""
    r = await calcular_preco_referencia(
        [10.0, 20.0, 30.0, 40.0, 5000.0], metodo="escore_z", serie_homogenea=True
    )
    assert r["motivo_parada_saneamento"] == "piso_minimo_amostra"
    assert any("limite" in a.lower() for a in r["avisos"])


async def test_escore_z_que_alcanca_a_meta_declara_a_meta():
    """O controle do teste anterior: quando converge, tem de dizer que converteu."""
    r = await calcular_preco_referencia(
        [10.18, 9.92, 12.50, 12.11, 6.24, 14.00, 4.20, 18.14], metodo="escore_z"
    )
    assert r["motivo_parada_saneamento"] == "meta_cv_atingida"
    assert not any("limite de segurança" in a for a in r["avisos"])


async def test_percentual_excluido_e_declarado():
    """O número que teria tornado o defeito visível sem precisar depurar."""
    r = await calcular_preco_referencia(_lognormal(50))
    assert 0 < r["percentual_excluido"] < 45


async def test_metodos_sem_saneamento_nao_inventam_motivo_de_parada():
    """Não houve saneamento; um motivo aqui seria contradição no dado."""
    for metodo in ("mediana", "minimo"):
        r = await calcular_preco_referencia([10.0, 12.0, 11.0], metodo=metodo)
        assert r["motivo_parada_saneamento"] is None
        assert r["percentual_excluido"] == 0.0


# ===========================================================================
# v0.5.15 — os dois métodos usavam convenções diferentes de desvio-padrão
# ===========================================================================
#
# Encontrado por verificação independente do usuário, 08/09/2026: o
# `media_saneada` usava desvio POPULACIONAL (`pstdev`, ddof=0) e o `escore_z`
# usava AMOSTRAL (`stdev`, ddof=1). Consequências medidas:
#
#   - o "CV final" não era comparável entre os métodos — na amostra de piso,
#     33,33% num e 27,22% no outro, 6 pontos de diferença só pela convenção;
#   - a meta de CV <= 25% ficava mais rígida sob a convenção amostral, então o
#     `escore_z` podia remover um valor a mais nos casos de fronteira, efeito
#     que cresce conforme a amostra encolhe — onde ela é mais frágil;
#   - a banda populacional é mais estreita, e o `media_saneada` excluía
#     marginalmente mais (29 contra 28 numa normal de n=100).
#
# A convenção escolhida é a AMOSTRAL, e não por gosto: era a única com âncora
# verificada. O ddof=1 do `escore_z` é o que reproduz os CV do exemplo oficial
# do IPPC-TIC (40,12%/35,65%/25,06%/14,48%); o ddof=0 do `media_saneada` se
# justificava por uma alegação sobre "as planilhas mais comuns no setor
# público" que nunca foi verificada contra fonte alguma. Também é o
# `DESVPAD.A` do Excel, o padrão de `statistics.stdev`, e o que
# `agrupar_por_comparabilidade` já usava neste mesmo projeto.


def _cv(valores: list[float]) -> float:
    import statistics

    return statistics.stdev(valores) / statistics.mean(valores) * 100


async def test_os_dois_metodos_reportam_o_cv_na_mesma_convencao():
    """Sem isto, o mesmo número significava coisas diferentes por método."""
    precos = [10.18, 9.92, 12.50, 12.11, 6.24, 14.00, 4.20, 18.14]
    for metodo in ("media_saneada", "escore_z"):
        r = await calcular_preco_referencia(precos, metodo=metodo)
        esperado = _cv(r["amostra_saneada"])
        assert r["estatisticas"]["coeficiente_variacao_percentual"] == pytest.approx(
            esperado, abs=0.01
        ), f"{metodo} não usa a convenção amostral"


async def test_desvio_padrao_reportado_e_amostral():
    """O campo `desvio_padrao` é lido direto por quem monta a planilha."""
    import statistics

    r = await calcular_preco_referencia([10.0, 12.0, 11.0, 13.0], metodo="mediana")
    assert r["estatisticas"]["desvio_padrao"] == pytest.approx(
        statistics.stdev([10.0, 12.0, 11.0, 13.0]), abs=1e-4
    )


async def test_exemplo_oficial_do_ippc_tic_continua_reproduzindo():
    """A âncora que decidiu a convenção não pode quebrar ao unificá-la."""
    r = await calcular_preco_referencia(
        [10.18, 9.92, 12.50, 12.11, 6.24, 14.00, 4.20, 18.14], metodo="escore_z"
    )
    assert r["valores_excluidos"] == [18.14, 4.20, 6.24]
    assert r["estatisticas"]["coeficiente_variacao_percentual"] == pytest.approx(14.48, abs=0.01)


async def test_media_saneada_nao_poda_serie_ja_homogenea():
    """v0.5.16 SUPERA a v0.5.15 aqui, e a mudança é de comportamento.

    A v0.5.15 mantinha a poda e apenas AVISAVA que ela era ruído — o que
    preservava a letra do método (o corte em bloco não tem parada por CV) ao
    custo de remover ~30% de uma série boa. A v0.5.16 deixa de podar: se o CV
    já está na meta, não há outlier a remover, e "apliquei a média saneada e
    nada estava fora do critério de aceitação" é mais defensável no processo
    do que descartar preços válidos e explicar depois.
    """
    precos = [100.0, 101.0, 99.0, 102.0, 98.0, 100.5, 99.5]
    assert _cv(precos) < 25.0, "a premissa do teste é uma série já homogênea"
    r = await calcular_preco_referencia(precos, metodo="media_saneada")
    assert r["valores_excluidos"] == []
    assert r["motivo_parada_saneamento"] == "cv_inicial_ja_aceitavel"
    assert not any("já era homogênea" in a for a in r["avisos"]), (
        "o aviso da v0.5.15 perdeu o objeto: não há mais poda a explicar"
    )


# ===========================================================================
# v0.5.16 — o que o corte de outliers NÃO resolve
# ===========================================================================
#
# Duas lacunas apontadas pelo usuário, e um caso real que mostra por que a
# segunda é a menos importante das três.
#
# 1. O passe único não garante CV <= 25%. Verdade, e não há conserto pela via
#    da iteração: iterar foi exatamente o defeito da v0.5.11. A resposta certa
#    é DECLARAR que a meta não foi atingida, não perseguir o número.
#
# 2. Ele cortava mesmo com a série já dentro da meta. Corrigido: quando o CV
#    inicial já está em 25% ou menos, não há saneamento a fazer, e o motivo da
#    parada diz isso.
#
# 3. CATMAT 434228 (esfigmomanômetro de pedestal), 19 preços, cobertura
#    exaustiva, todos com a MESMA descrição, o mesmo PDM e a mesma unidade:
#
#      33,75  58,00  64,06  66,00  74,90  83,00  92,16  99,90  129,99
#      ----------------------- lacuna de 2,27x -----------------------
#      294,90  347,00  348,99  349,99  357,50  360,00  369,00  390,00
#      466,66  544,05
#
#    Não é ruído: o código é do produto COM pedestal, e é usado também para
#    comprar o modelo comum e peças avulsas. São dois objetos diferentes sob
#    um código só, e nenhum metadado os separa — só o preço.
#
#    O que os métodos fazem com isso, medido:
#      media_saneada  R$ 253,64  (exclui 6, CV final 52,0%)
#      escore_z       R$  77,97  (exclui 10, CV final 35,4%)
#      mediana        R$ 294,90
#
#    O escore_z removeu exatamente os 10 preços do grupo caro e devolveu a
#    média do grupo barato. Ele não removeu outliers: ESCOLHEU UM CLUSTER — e
#    escolheu o que não corresponde ao objeto do código, produzindo uma
#    estimativa 4,9x menor. Nenhuma regra de parada conserta isso, porque não
#    há um centro a encontrar.

_CATMAT_434228 = [
    369.0, 129.99, 349.99, 294.90, 347.0, 360.0, 74.90, 83.0, 58.0, 357.50,
    64.06, 348.99, 544.05, 466.66, 92.1553, 33.75, 390.0, 66.0, 99.90,
]


async def test_serie_ja_homogenea_nao_e_podada():
    """O corte em bloco removia ~30% de qualquer série, inclusive das boas."""
    precos = [100.0, 101.0, 99.0, 102.0, 98.0, 100.5, 99.5]
    for metodo in ("escore_z", "media_saneada"):
        r = await calcular_preco_referencia(precos, metodo=metodo, serie_homogenea=True)
        assert r["valores_excluidos"] == [], metodo
        assert r["percentual_excluido"] == 0.0, metodo
        assert r["iteracoes_saneamento"] == 0, metodo
        assert r["motivo_parada_saneamento"] == "cv_inicial_ja_aceitavel", metodo
        assert r["amostra_saneada"] == precos, metodo


async def test_passe_unico_que_nao_alcanca_a_meta_declara_isso():
    """A lacuna 1: um passe não garante CV <= 25%, e fingir que garante seria
    pior que não garantir. O motivo da parada passa a dizer."""
    r = await calcular_preco_referencia(
        _CATMAT_434228, metodo="media_saneada", serie_homogenea=True
    )
    assert r["estatisticas"]["coeficiente_variacao_percentual"] > 25.0
    assert r["motivo_parada_saneamento"] == "meta_nao_atingida"
    assert any("único passe" in a for a in r["avisos"]), (
        "v0.5.19: o aviso agora nomeia o motivo real em vez de dizer só "
        "'não atingiu a meta'"
    )


# --- Detecção de mistura de objetos ----------------------------------------


async def test_bimodalidade_do_434228_e_detectada_e_declarada():
    """O achado principal: a série tem dois objetos, não outliers."""
    r = await calcular_preco_referencia(_CATMAT_434228, serie_homogenea=True)
    d = r["diagnostico_distribuicao"]
    assert d["possivel_mistura_de_objetos"] is True
    assert d["metodo"] == "heuristica_de_lacuna", "inferência declarada como inferência"
    assert d["corte_sugerido"] == pytest.approx(129.99), "a maior lacuna da série"
    assert d["grupos"][0]["quantidade"] == 9
    assert d["grupos"][1]["quantidade"] == 10
    assert d["grupos"][1]["coeficiente_variacao_percentual"] < 25.0, (
        "o grupo caro sozinho É homogêneo — é a mistura que produz o CV de 69%"
    )
    assert any("MISTURA" in a.upper() for a in r["avisos"])


async def test_o_aviso_de_mistura_desaconselha_o_saneamento():
    """Remover outliers numa série bimodal escolhe um cluster, não limpa ruído.

    Medido no 434228: o escore_z removeu os 10 preços do grupo caro e devolveu
    R$ 77,97 — a média do grupo barato, 4,9x abaixo. Sem este aviso, o número
    sai com aparência de saneado.
    """
    r = await calcular_preco_referencia(_CATMAT_434228, metodo="escore_z", serie_homogenea=True)
    assert r["preco_referencia"] == pytest.approx(77.97, abs=0.01)
    assert r["diagnostico_distribuicao"]["possivel_mistura_de_objetos"] is True
    assert any("agrupar_por_comparabilidade" in a for a in r["avisos"])


async def test_serie_unimodal_nao_dispara_o_alarme():
    """Controle: falso positivo aqui faria o aviso virar ruído a ser ignorado.

    Os 13 preços do Adobe CC, série real e homogênea (CV 11,6%).
    """
    precos = [12750.0, 14188.50, 14762.0, 15303.58, 15500.16, 16281.0, 17040.0,
              17290.0, 18208.18, 18300.0, 18484.0, 18486.0, 18666.45]
    r = await calcular_preco_referencia(precos, serie_homogenea=True)
    assert r["diagnostico_distribuicao"]["possivel_mistura_de_objetos"] is False
    assert not any("MISTURA" in a.upper() for a in r["avisos"])


async def test_um_outlier_isolado_nao_e_confundido_com_mistura():
    """Um valor absurdo é outlier; dois grupos são objetos diferentes.

    Confundir os dois faria a tool desaconselhar o saneamento exatamente onde
    ele é o tratamento certo.
    """
    precos = [100.0, 102.0, 98.0, 101.0, 99.0, 103.0, 97.0, 100.0, 102.0,
              99.0, 101.0, 98.0, 100.0, 900.0]
    r = await calcular_preco_referencia(precos, serie_homogenea=True)
    assert r["diagnostico_distribuicao"]["possivel_mistura_de_objetos"] is False


async def test_amostra_pequena_nao_recebe_diagnostico_de_distribuicao():
    """Com poucos valores não há como distinguir lacuna de acaso."""
    r = await calcular_preco_referencia([10.0, 12.0, 11.0, 50.0], serie_homogenea=True)
    d = r["diagnostico_distribuicao"]
    assert d["possivel_mistura_de_objetos"] is None, "None é 'não sei', não 'não há'"
    assert d["motivo"] == "amostra_pequena"


# ===========================================================================
# v0.5.17 — o escore Z iterativo vira o saneamento padrão
# ===========================================================================
#
# Especificação recebida em 09/09/2026, e a regra central dela:
#
#   Nunca remover outlier quando o CV inicial for <= 25%. Se for > 25%,
#   remover iterativamente apenas o maior outlier e recalcular o CV após cada
#   remoção, até atingir CV <= 25% ou o piso de 3 referências.
#
# A média saneada continua disponível, mas deixa de ser o padrão: ela remove
# vários preços de uma vez e, sendo de passe único, não garante a meta. O
# escore Z remove um por vez e para no critério — mais controlável, e
# auditável exclusão a exclusão.


async def test_exemplo_de_aceitacao_dos_seis_precos_do_434228():
    """O caso de aceitação da especificação, número a número.

    Seis preços do grupo caro do CATMAT 434228: CV inicial 29,56% (acima da
    meta, então há saneamento a fazer), sai o 129,99 — que é o único do grupo
    barato que sobrou na seleção — e o CV cai para 8,39% numa iteração só.
    """
    precos = [369.00, 129.99, 349.99, 294.90, 347.00, 360.00]
    r = await calcular_preco_referencia(precos, serie_homogenea=True)

    assert r["metodo_utilizado"] == "escore_z", "o padrão passou a ser o escore Z"
    assert r["cv_inicial_percentual"] == pytest.approx(29.56, abs=0.01)
    assert r["valores_excluidos"] == [129.99]
    assert r["iteracoes_saneamento"] == 1
    assert r["cv_final_percentual"] == pytest.approx(8.39, abs=0.01)
    assert r["motivo_parada_saneamento"] == "meta_cv_atingida"
    assert r["meta_cv_percentual"] == 25.0


async def test_para_na_primeira_iteracao_que_alcanca_a_meta():
    """Não continua removendo depois de atingido o critério.

    O CV é recalculado ANTES de cada remoção, não depois de um lote — é o que
    impede o algoritmo de passar do ponto e ir comendo a amostra.
    """
    precos = [369.00, 129.99, 349.99, 294.90, 347.00, 360.00]
    r = await calcular_preco_referencia(precos)
    assert len(r["amostra_saneada"]) == 5, "removeu um, e parou"


async def test_cv_inicial_aceitavel_zera_exclusoes_e_iteracoes():
    """A regra central da especificação, na sua forma mais direta."""
    precos = [100.0, 102.0, 98.0, 101.0, 99.0]
    r = await calcular_preco_referencia(precos, serie_homogenea=True)
    assert r["cv_inicial_percentual"] <= 25.0
    assert r["valores_excluidos"] == []
    assert r["iteracoes_saneamento"] == 0
    assert r["motivo_parada_saneamento"] == "cv_inicial_ja_aceitavel"
    assert r["cv_final_percentual"] == r["cv_inicial_percentual"]


async def test_piso_de_tres_para_mesmo_com_cv_acima_da_meta():
    """Reduzir a 2 para "forçar" o CV não torna a amostra representativa."""
    r = await calcular_preco_referencia([10.0, 20.0, 30.0, 40.0, 5000.0])
    assert len(r["amostra_saneada"]) == 3
    assert r["motivo_parada_saneamento"] == "piso_minimo_amostra"
    assert r["cv_final_percentual"] > 25.0
    assert any("LIMITE de segurança" in a for a in r["avisos"])


async def test_valores_todos_iguais_nao_dividem_por_zero():
    """Escore Z é (x - média)/dp; com dp zero seria NaN silencioso."""
    r = await calcular_preco_referencia([50.0, 50.0, 50.0, 50.0])
    assert r["motivo_parada_saneamento"] == "desvio_padrao_zero"
    assert r["valores_excluidos"] == []
    assert r["cv_final_percentual"] == 0.0


async def test_exemplo_do_ippc_tic_continua_valendo_como_padrao():
    """A âncora oficial não pode quebrar ao promover o método a padrão."""
    r = await calcular_preco_referencia(
        [10.18, 9.92, 12.50, 12.11, 6.24, 14.00, 4.20, 18.14]
    )
    assert r["metodo_utilizado"] == "escore_z"
    assert r["valores_excluidos"] == [18.14, 4.20, 6.24]
    assert r["cv_inicial_percentual"] == pytest.approx(40.12, abs=0.01)
    assert r["cv_final_percentual"] == pytest.approx(14.48, abs=0.01)


# ===========================================================================
# v0.5.18 — o docstring continuou anunciando o padrão antigo
# ===========================================================================
#
# A v0.5.17 trocou o método padrão para `escore_z` no CÓDIGO e esqueceu o
# docstring, que seguiu dizendo `Se omitido, usa "media_saneada"`.
#
# O detalhe que torna isso mais que um deslize de texto: o digest do catálogo
# NÃO mudou (`9faab8a866e8`, o mesmo da v0.5.14), porque o digest cobre a
# descrição da tool — e a descrição não mudou. O mecanismo funcionou como
# projetado e disse a verdade: o contrato anunciado continuava o mesmo. Era o
# comportamento que tinha saído de baixo dele.
#
# Para um cliente MCP, o docstring É o contrato: é por ele que o modelo decide
# quando e como chamar. Anunciar um padrão e executar outro é a mesma família
# de defeito que este projeto persegue desde o começo — a diferença entre o
# que se afirma e o que se faz.


def test_o_padrao_documentado_e_o_padrao_executado():
    """Guarda contra divergência entre docstring e comportamento.

    Extrai do docstring o método anunciado como padrão e compara com o que a
    função realmente usa quando `metodo` é omitido. Um teste de texto, porque
    é o texto que o cliente MCP lê.
    """
    import inspect
    import re

    doc = inspect.getdoc(calcular_preco_referencia) or ""
    m = re.search(r"Se omitido, usa [\"“]?(\w+)", doc)
    assert m, "o docstring precisa dizer qual é o método padrão"
    documentado = m.group(1)

    fonte = inspect.getsource(calcular_preco_referencia)
    e = re.search(r'metodo_utilizado = metodo or "(\w+)"', fonte)
    assert e, "o padrão precisa ser legível no código"
    executado = e.group(1)

    assert documentado == executado, (
        f"o docstring anuncia {documentado!r} e o código usa {executado!r}. "
        "Para um cliente MCP o docstring É o contrato."
    )


async def test_os_campos_novos_estao_documentados():
    """Campo que existe no retorno e não no docstring é campo que ninguém usa."""
    import inspect

    doc = inspect.getdoc(calcular_preco_referencia) or ""
    r = await calcular_preco_referencia([10.0, 12.0, 11.0])
    for campo in (
        "cv_inicial_percentual",
        "cv_final_percentual",
        "meta_cv_percentual",
        "motivo_parada_saneamento",
        "diagnostico_distribuicao",
    ):
        assert campo in r, f"{campo} deveria estar no retorno"
        assert campo in doc, f"{campo} está no retorno mas não no docstring"


# ===========================================================================
# v0.5.19 — bateria de 13 cenários: dois motivos errados e um portão que
#           faltava
# ===========================================================================
#
# Relatados em 09/09/2026 depois de uma bateria independente. Os dois
# primeiros são o mesmo defeito de sempre: o rótulo não descrevia o fato.


async def test_nada_fora_da_faixa_com_cv_acima_da_meta_nao_e_cv_aceitavel():
    """Bug 1: [74, 100, 126] tem CV 26% e devolvia `cv_inicial_ja_aceitavel`.

    Logicamente impossível: 26% > 25%. O que acontece é outra coisa — média
    100, dp 26, faixa [74, 126] com limites inclusivos, e os três valores caem
    DENTRO dela. O corte em bloco não encontrou outlier pelo seu critério, e
    isso não é o mesmo fato que "o CV já estava na meta". Vale também para
    amostras maiores que 3, por isso o motivo é próprio.
    """
    r = await calcular_preco_referencia([74.0, 100.0, 126.0], metodo="media_saneada")
    assert r["cv_inicial_percentual"] == pytest.approx(26.0, abs=0.01)
    assert r["cv_inicial_percentual"] > r["meta_cv_percentual"]
    assert r["motivo_parada_saneamento"] == "sem_outlier_pelo_criterio"
    assert r["valores_excluidos"] == []
    assert r["status_resultado"] == "nao_apto", "CV acima da meta não é resultado apto"


async def test_o_limite_exato_de_25_por_cento_e_aceito():
    """Controle do anterior: 25,00% é aceitável, não 'acima'."""
    for metodo in ("media_saneada", "escore_z"):
        r = await calcular_preco_referencia([75.0, 100.0, 125.0], metodo=metodo)
        assert r["cv_inicial_percentual"] == pytest.approx(25.0, abs=0.01), metodo
        assert r["motivo_parada_saneamento"] == "cv_inicial_ja_aceitavel", metodo
        assert r["valores_excluidos"] == [], metodo


async def test_aviso_de_cv_alto_diz_o_motivo_certo_da_parada():
    """Bug 2: o aviso citava o piso de 3 mesmo quando sobravam 5 valores.

    Em [10, 95, 100, 105, 110, 500] a média saneada remove o 500 e para —
    porque é de passe único, não porque tenha esbarrado no piso. O texto era
    fixo, independente de `motivo_parada`.
    """
    r = await calcular_preco_referencia(
        [10.0, 95.0, 100.0, 105.0, 110.0, 500.0], metodo="media_saneada"
    )
    assert len(r["amostra_saneada"]) == 5
    cv_alto = [a for a in r["avisos"] if "Coeficiente de Variação" in a]
    assert len(cv_alto) == 1, "um aviso só de CV alto — sem duplicar com o de meta"
    assert "mínimo de 3" not in cv_alto[0], "o piso não foi o motivo — sobravam 5"
    assert "único passe" in cv_alto[0]


async def test_aviso_cita_o_piso_quando_o_piso_foi_mesmo_o_motivo():
    """Controle: quando a parada É pelo piso, o aviso tem de dizer isso."""
    r = await calcular_preco_referencia([10.0, 20.0, 30.0, 40.0, 5000.0])
    assert r["motivo_parada_saneamento"] == "piso_minimo_amostra"
    cv_alto = [a for a in r["avisos"] if "Coeficiente de Variação" in a]
    assert cv_alto and "piso mínimo" in cv_alto[0]


# --- Item 3: status legível por máquina, sem apagar o número ----------------

_BIMODAL = [95.0, 100.0, 105.0, 110.0, 115.0, 480.0, 500.0, 520.0, 540.0, 560.0]


async def test_serie_misturada_e_marcada_como_nao_apta_sem_perder_o_numero():
    """O ponto mais importante da bateria.

    O escore Z remove os 5 caros e devolve R$ 105,00 com CV 7,53% e
    `meta_cv_atingida` — bonito e economicamente errado, porque a metade
    removida era outro produto, não ruído.

    O `preco_referencia` é preservado: serve à auditoria, e é o que permite
    ver o que o algoritmo teria feito. O que muda é que existe um campo
    LEGÍVEL POR MÁQUINA dizendo que ele não serve — em vez de depender de um
    agente ler o texto de `avisos`.
    """
    r = await calcular_preco_referencia(_BIMODAL, serie_homogenea=True)
    assert r["preco_referencia"] == pytest.approx(105.0), "preservado para auditoria"
    assert r["apto_para_preco_referencia"] is False
    assert r["status_resultado"] == "nao_apto"
    assert r["diagnostico_distribuicao"]["possivel_mistura_de_objetos"] is True
    assert any("MISTURA" in a.upper() for a in r["avisos"])


async def test_mistura_derruba_o_status_em_todos_os_metodos():
    """A mediana de duas populações também não descreve nenhuma delas."""
    for metodo in ("escore_z", "media_saneada", "mediana", "minimo"):
        r = await calcular_preco_referencia(_BIMODAL, metodo=metodo, serie_homogenea=True)
        assert r["status_resultado"] == "nao_apto", metodo
        assert r["apto_para_preco_referencia"] is False, metodo


async def test_status_apto_exige_homogeneidade_declarada():
    """`serie_homogenea=None` é suposição, não verificação — requer revisão."""
    precos = [100.0, 102.0, 98.0, 101.0, 99.0]
    assert (await calcular_preco_referencia(precos))["status_resultado"] == "requer_revisao"
    r = await calcular_preco_referencia(precos, serie_homogenea=True)
    assert r["status_resultado"] == "apto"
    assert r["apto_para_preco_referencia"] is True
    r = await calcular_preco_referencia(precos, serie_homogenea=False)
    assert r["status_resultado"] == "nao_apto"


async def test_parada_por_guarda_nunca_e_apta():
    """Piso e meta não atingida invalidam o número."""
    r = await calcular_preco_referencia(
        [10.0, 20.0, 30.0, 40.0, 5000.0], serie_homogenea=True
    )
    assert r["motivo_parada_saneamento"] == "piso_minimo_amostra"
    assert r["status_resultado"] == "nao_apto"


# --- Item 5: histórico auditável por iteração -------------------------------


async def test_historico_registra_o_cv_que_motivou_cada_exclusao():
    """A docstring prometia "cada exclusão com o CV que a motivou" e o retorno
    não trazia isso — só o CV inicial e o final."""
    r = await calcular_preco_referencia(
        [100.0, 105.0, 110.0, 115.0, 500.0, 1000.0], serie_homogenea=True
    )
    h = r["historico_saneamento"]
    assert len(h) == r["iteracoes_saneamento"] == 2
    assert [p["valor_excluido"] for p in h] == [1000.0, 500.0]
    assert h[0]["iteracao"] == 1 and h[1]["iteracao"] == 2
    assert h[0]["quantidade_antes"] == 6 and h[1]["quantidade_antes"] == 5
    assert h[0]["cv_antes_percentual"] > h[0]["cv_depois_percentual"]
    assert h[1]["cv_depois_percentual"] == pytest.approx(r["cv_final_percentual"], abs=0.01)
    assert abs(h[0]["escore_z"]) > 1.0, "o removido é o de maior |Z|"


async def test_sem_exclusao_o_historico_vem_vazio():
    r = await calcular_preco_referencia([100.0, 102.0, 98.0], serie_homogenea=True)
    assert r["historico_saneamento"] == []


async def test_media_saneada_registra_o_passe_unico_no_historico():
    """O corte em bloco remove vários de uma vez — a entrada reflete isso."""
    r = await calcular_preco_referencia(
        [10.0, 95.0, 100.0, 105.0, 110.0, 500.0], metodo="media_saneada"
    )
    h = r["historico_saneamento"]
    assert len(h) == 1, "passe único gera uma entrada só"
    assert h[0]["valores_excluidos"] == [500.0]
    assert "escore_z" not in h[0], "o critério do bloco não é escore Z"


# --- Item 6: o docstring lista os motivos que existem -----------------------


def test_o_docstring_lista_exatamente_os_motivos_do_enum():
    """O catálogo MCP expõe este texto: motivo inventado ali vira contrato falso."""
    import inspect

    doc = inspect.getdoc(calcular_preco_referencia) or ""
    reais = {m.value for m in MotivoParadaSaneamento}
    for valor in reais:
        assert f"``{valor}``" in doc, f"{valor} existe no enum e não no docstring"
    for obsoleto in ("sem_exclusoes", "limite_de_iteracoes", "limite_iteracoes", "piso_da_amostra"):
        assert obsoleto not in doc, f"{obsoleto} não existe mais e ainda é citado"
