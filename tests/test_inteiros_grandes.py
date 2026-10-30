"""Identificadores longos não podem sair como número.

O defeito, relatado em 02/10/2026 e medido no mesmo dia
-------------------------------------------------------
``id_compra`` tem 17 dígitos: ``15502005000242026``. O limite de inteiro
exatamente representável num ``double`` IEEE-754 é ``2^53 - 1`` =
``9.007.199.254.740.991`` — dezesseis dígitos. Acima disso o valor é
aproximado, e a camada de transporte do MCP é TypeScript, onde todo número é
``double``.

**O que a 0.6.3 afirmou e a medição desmentiu:** que o identificador "chega ao
cliente arredondado". Não chega. ``JSON.stringify`` imprime a menor
representação decimal que volta ao mesmo ``double``, e ela recupera os dígitos
originais — dos **1.349 ``id_compra`` reais** das respostas salvas (637 acima
de ``2^53-1``), todos atravessam ``JSON.parse``/``JSON.stringify`` com texto
idêntico e nenhum par distinto colide. Os "43% que perdem precisão" eram
valores **não representáveis em double**: propriedade dos números, não
corrupção do transporte.

**O dano real** é que o valor em memória é um ``double`` inexato:
``98367705000032030 === 98367705000032031`` devolve ``true``, e ``n % 10``
devolve 2 onde o último dígito é 0. Quem compara, deduplica ou faz aritmética
com o identificador erra — sem erro e sem aviso, com o número parecendo certo.

Terceira vez que esta camada engana, e sempre na mesma direção: uma vez li um
artefato do transporte como propriedade da origem (capacidade ``int``/
``float``), outra li uma propriedade dos números como artefato do transporte
(este caso). O que se repete é **em que camada se mede**.

Por que dois conjertos, e não um
---------------------------------
1. **Conversão explícita nos campos conhecidos.** Dá contrato estável: o campo
   é sempre texto.
2. **Rede de segurança genérica no wrapper de tool**, que converte qualquer
   inteiro acima do limite e avisa.

Só a rede de segurança não bastaria, e esta é a parte não óbvia: ela agiria
apenas sobre os valores grandes, então o MESMO campo sairia ``int`` quando o
valor fosse pequeno e ``str`` quando fosse grande. Tipo que depende da
magnitude do valor é pior que qualquer um dos dois fixos — quem consome não tem
como escrever código correto.

Só a conversão explícita também não bastaria: ela cobre os campos que alguém
lembrou de enumerar. A rede pega o próximo que ninguém viu, e avisa, que é como
a gente descobre que ele existe.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from mcp_radardeprecos.utils.numeros import (
    MAX_INTEIRO_SEGURO,
    identificador,
    proteger_inteiros_grandes,
)

#: Dois `id_compra` reais. O primeiro é exatamente representável num `double`;
#: o segundo não é. Ter os dois é o ponto: metade dos valores reais cai em cada
#: caso, e uma amostra de um só valor esconde isso.
#:
#: Os nomes vêm da v0.6.3 e estão imprecisos de propósito preservado — ambos
#: *imprimem* de volta igual. O que o segundo perde é a identidade: ele passa a
#: ser igual a `98367705000032031`. Ver o docstring do módulo.
_ID_QUE_SOBREVIVE = 15502005000242026
_ID_QUE_CORROMPE = 98367705000032030


def test_o_limite_e_o_do_double_e_nao_um_numero_escolhido():
    assert MAX_INTEIRO_SEGURO == 2**53 - 1 == 9007199254740991


def test_o_id_que_corrompe_realmente_corrompe():
    """Premissa do resto. Sem isto, o teste poderia passar por engano."""
    assert int(float(_ID_QUE_CORROMPE)) != _ID_QUE_CORROMPE
    assert int(float(_ID_QUE_SOBREVIVE)) == _ID_QUE_SOBREVIVE


# --- Conversão explícita ----------------------------------------------------


def test_identificador_devolve_texto_qualquer_que_seja_a_magnitude():
    """Contrato estável: não é "texto quando grande", é texto sempre."""
    assert identificador(_ID_QUE_CORROMPE) == "98367705000032030"
    assert identificador(7) == "7"
    assert identificador("já era texto") == "já era texto"


def test_identificador_preserva_ausencia():
    assert identificador(None) is None


def test_identificador_nao_estraga_zero():
    """`0` é um identificador possível; `or` o transformaria em ausência."""
    assert identificador(0) == "0"


# --- Rede de segurança ------------------------------------------------------


def test_a_rede_converte_inteiro_grande_em_qualquer_profundidade():
    payload = {
        "a": [{"b": {"c": _ID_QUE_CORROMPE}}],
        "seguro": 42,
        "quase": MAX_INTEIRO_SEGURO,
    }
    protegido, convertidos = proteger_inteiros_grandes(payload)
    assert protegido["a"][0]["b"]["c"] == "98367705000032030"
    assert protegido["seguro"] == 42, "número seguro não é mexido"
    assert protegido["quase"] == MAX_INTEIRO_SEGURO, "o limite ainda é seguro"
    assert convertidos == ["a[].b.c"]


def test_a_rede_relata_o_caminho_para_que_o_campo_seja_corrigido_na_origem():
    """O caminho é o conteúdo acionável: diz qual campo virar texto explícito.

    Sem ele, saberíamos que algo foi convertido e não onde — e o campo
    continuaria com tipo dependente da magnitude.
    """
    _, convertidos = proteger_inteiros_grandes(
        {"precos": [{"id_compra": _ID_QUE_CORROMPE}, {"id_compra": 1}]}
    )
    assert convertidos == ["precos[].id_compra"]


def test_a_rede_nao_mexe_em_float_nem_em_bool():
    """`float` já é double na origem — converter mentiria sobre o tipo. E
    `bool` é subclasse de `int` em Python, o que já causou defeito aqui antes.
    """
    protegido, convertidos = proteger_inteiros_grandes(
        {"preco": 1.5e20, "ativo": True}
    )
    assert protegido["preco"] == 1.5e20
    assert protegido["ativo"] is True
    assert convertidos == []


def test_negativo_grande_tambem_e_protegido():
    protegido, _ = proteger_inteiros_grandes({"x": -(2**60)})
    assert protegido["x"] == str(-(2**60))


# --- Integração: o campo que motivou o relato -------------------------------


async def test_id_compra_sai_como_texto_nos_precos_praticados():
    from mcp_radardeprecos.tools.buscar_precos_praticados_compras import (
        buscar_precos_praticados_compras,
    )

    registro = {
        "precoUnitario": 1.5,
        "quantidade": 10,
        "niFornecedor": "11222333000144",
        "dataResultado": "2026-01-10",
        "nomeUnidadeFornecimento": "UNIDADE",
        "capacidadeUnidadeFornecimento": 0,
        "idCompra": _ID_QUE_CORROMPE,
    }
    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(return_value={"resultado": [registro], "totalRegistros": 1}),
    ):
        r = await buscar_precos_praticados_compras(267203, "material", limite=20)

    id_saida = r["precos"][0]["id_compra"]
    assert isinstance(id_saida, str), "identificador é texto, não quantidade"
    assert id_saida == "98367705000032030"
    # O teste que importa: o valor sobrevive a uma ida e volta por JSON com
    # números em double, que é o que a camada de transporte faz.
    via_js = json.loads(json.dumps(r["precos"][0]), parse_int=float)
    assert via_js["id_compra"] == "98367705000032030"


async def test_id_compra_pequeno_tambem_sai_como_texto():
    """Controle do tipo estável: não muda de str para int conforme o valor."""
    from mcp_radardeprecos.tools.buscar_precos_praticados_compras import (
        buscar_precos_praticados_compras,
    )

    with patch(
        "mcp_radardeprecos.tools.buscar_precos_praticados_compras."
        "compras_client.consultar_precos_material",
        new=AsyncMock(
            return_value={"resultado": [{"precoUnitario": 1.0, "idCompra": 7}],
                          "totalRegistros": 1}
        ),
    ):
        r = await buscar_precos_praticados_compras(267203, "material", limite=20)
    assert r["precos"][0]["id_compra"] == "7"


# ---------------------------------------------------------------------------
# O modo de falha de verdade, medido em 02/10/2026
# ---------------------------------------------------------------------------
# Estes dois testes existem para impedir uma "simplificação" futura do tipo
# "os dígitos chegam certos, então pode voltar a sair como número". Chegam
# certos mesmo — e é exatamente por isso que o defeito é difícil de ver.


def test_o_texto_do_identificador_sobrevive_ao_double_e_isso_nao_e_consolo():
    """Imprimir de volta não prova que o valor está intacto.

    ``JSON.stringify`` em JavaScript imprime a MENOR representação decimal que
    volta ao mesmo ``double`` — não os dígitos exatos do valor armazenado. Para
    os 1.349 ``id_compra`` reais medidos, essa regra recupera os dígitos
    originais. O teste fixa isso para que ninguém use "os dígitos chegam
    certos" como argumento para remover a conversão.

    O equivalente em Python é ``repr`` do float (mesma regra, notação
    científica); ``f"{d:.0f}"`` NÃO serve, porque imprime o valor exato do
    ``double`` — foi assim que este teste falhou na primeira escrita, e a
    diferença é justamente o que torna o defeito invisível em JavaScript.
    """
    from decimal import Decimal

    original = 98367705000032030
    assert original > MAX_INTEIRO_SEGURO
    como_double = float(original)

    # o valor ARMAZENADO não é o original: os dígitos exatos terminam em 032
    assert int(como_double) == 98367705000032032
    assert f"{como_double:.0f}" == "98367705000032032"

    # mas o que o JavaScript IMPRIME é a menor representação que round-trips,
    # e ela recupera o original — é o que chega a quem lê a resposta.
    assert str(Decimal(repr(como_double))) == "9.836770500003203E+16"
    assert int(Decimal(repr(como_double))) == original


def test_o_dano_aparece_na_comparacao_e_na_aritmetica_nao_na_impressao():
    """Duas compras distintas passam a ser o mesmo valor.

    É o motivo pelo qual o identificador sai como texto. Não é o
    arredondamento visível que a v0.6.3 descreveu — é a igualdade falsa, que
    sobrevive a qualquer conferência a olho.
    """
    a, b = 98367705000032030, 98367705000032031
    assert a != b                      # em Python, dois inteiros distintos
    assert float(a) == float(b)        # em double, o MESMO valor
    # e o último dígito deixa de ser recuperável por aritmética
    assert a % 10 == 0
    assert int(float(a)) % 10 == 2
    # texto não tem esse problema: é o contrato que identificador() dá
    assert identificador(a) != identificador(b)
