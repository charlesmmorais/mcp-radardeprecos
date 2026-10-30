"""Testes das projeções padrão.

O default de uma tool é o contrato de fato: o modelo só enxerga o que volta.
Campos que mudam a INTERPRETAÇÃO do número — unidade, situação do registro,
data de exclusão — precisam vir sempre, não atrás de uma flag que ninguém liga.
"""
from __future__ import annotations

from mcp_radardeprecos.tools.consultar_contratos_compras import _formatar_contrato
from mcp_radardeprecos.tools.consultar_itens_contrato_compras import _formatar_item
from mcp_radardeprecos.tools.consultar_notas_fiscais import (
    _esta_cancelada,
    _formatar_instrumento,
)
from mcp_radardeprecos.tools.radar_vencimentos import (
    _formatar_contrato as _formatar_contrato_radar,
)


def test_radar_expoe_situacao_do_contrato():
    """Um contrato excluído não é um vencimento a acompanhar."""
    r = _formatar_contrato_radar(
        {"numeroContrato": "1/2026", "contratoExcluido": True,
         "dataHoraExclusao": "2026-03-01T10:00:00"}
    )
    assert r["contrato_excluido"] is True
    assert r["data_hora_exclusao"] == "2026-03-01T10:00:00"


def test_radar_contrato_vigente_nao_marcado():
    r = _formatar_contrato_radar({"numeroContrato": "2/2026", "contratoExcluido": False})
    assert r["contrato_excluido"] is False


def test_contrato_expoe_quando_foi_excluido():
    """'excluído' sem data não diz se esteve vigente no período analisado."""
    r = _formatar_contrato(
        {"contratoExcluido": True, "dataHoraExclusao": "2026-02-10T08:00:00",
         "unidadesRequisitantes": "UASG 111", "idCompra": 99}
    )
    assert r["data_hora_exclusao"] == "2026-02-10T08:00:00"
    assert r["unidades_requisitantes"] == "UASG 111"
    # v0.6.3: identificador passou a sair como TEXTO. Um `id_compra` de 17
    # dígitos não sobrevive à camada de transporte do MCP, que trata todo
    # número como double — 37 de 86 valores reais perdiam precisão. O tipo
    # é texto SEMPRE, e não só quando o valor é grande: tipo que depende da
    # magnitude impede quem consome de escrever código correto.
    assert r["id_compra"] == "99"


def test_item_de_contrato_tem_escape_hatch():
    r = _formatar_item({"numeroItem": 1, "campoNovoDaApi": "x"}, incluir_bruto=True)
    assert r["dados_originais"]["campoNovoDaApi"] == "x"


def test_item_de_contrato_sem_bruto_por_padrao():
    r = _formatar_item({"numeroItem": 1})
    assert "dados_originais" not in r


def test_nota_fiscal_cancelada_e_sinalizada():
    """NF cancelada continua na resposta e seu valor não é despesa realizada."""
    instrumento = {
        "notaFiscalEletronica": {
            "numero": "123",
            "eventos": [{"tipoEvento": "Cancelamento de NF-e"}],
        }
    }
    r = _formatar_instrumento(instrumento)
    assert r["nota_fiscal"]["cancelada"] is True


def test_nota_fiscal_normal_nao_e_marcada():
    instrumento = {
        "notaFiscalEletronica": {"numero": "124", "eventos": [{"tipoEvento": "Autorizada"}]}
    }
    assert _formatar_instrumento(instrumento)["nota_fiscal"]["cancelada"] is False


def test_deteccao_de_cancelamento_e_conservadora():
    """Na dúvida, False: falso positivo esconderia despesa real."""
    assert _esta_cancelada([]) is False
    assert _esta_cancelada([{"tipo": None}]) is False
    assert _esta_cancelada([{"tipo": "Carta de Correcao"}]) is False
    assert _esta_cancelada([{"tipo": "CANCELAMENTO"}]) is True


def test_nota_fiscal_tem_escape_hatch():
    r = _formatar_instrumento({"numero": "1", "campoNovo": "y"}, incluir_bruto=True)
    assert r["dados_originais"]["campoNovo"] == "y"
