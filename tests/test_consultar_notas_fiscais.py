"""Testes de `consultar_notas_fiscais` (composição sobre instrumentos de cobrança do PNCP, cliente mockado)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.consultar_notas_fiscais import (
    _formatar_instrumento,
    consultar_notas_fiscais,
)

# ---------------------------------------------------------------------------
# Achados de 2026-08-27 — primeira medição ao vivo deste endpoint.
#
# Até essa data a docstring declarava "schema não confirmado ao vivo". A
# confirmação encontrou três defeitos, dois nossos e um da origem. Os testes
# abaixo travam cada um deles contra o registro REAL devolvido pelo contrato
# 32479123000143-2-000050/2024 (UFES).
# ---------------------------------------------------------------------------

#: Registro real, copiado da resposta do PNCP sem edição além do recorte.
_REAL_UFES = {
    "numeroInstrumentoCobranca": "202500000000156",
    "dataEmissaoDocumento": "2025-05-07",
    "chaveNFe": "2WRK-X5JV",
    "statusResponseNFe": "200",
    "jsonResponseNFe": (
        '{"notaFiscalDTO":null,"itensNotaFiscal":null,"eventosNotaFiscal":null}'
    ),
    "tipoInstrumentoCobranca": {"id": 1, "nome": "Nota Fiscal Eletrônica (NF-e)"},
}


def test_le_data_de_emissao_do_campo_que_a_api_realmente_usa():
    """O campo é ``dataEmissaoDocumento``, não ``dataEmissao``.

    Líamos o nome errado e devolvíamos ``None`` ao lado de um dado presente —
    indistinguível, para quem consome, de nota sem data cadastrada.
    """
    assert _formatar_instrumento(_REAL_UFES)["data_emissao"] == "2025-05-07"


def test_le_chave_do_campo_chaveNFe_sensivel_a_caixa():
    """``chaveNFe``, com NF maiúsculo. Procurávamos ``chaveNfe``."""
    assert _formatar_instrumento(_REAL_UFES)["chave_nfe"] == "2WRK-X5JV"


def test_chave_invalida_e_devolvida_com_o_problema_declarado():
    """Nem descartar nem repassar em silêncio.

    Em 6 das 8 notas deste contrato, ``chaveNFe`` trazia cadeias de nove
    caracteres. Devolver ``None`` apagaria o fato de haver conteúdo cadastrado;
    repassar sem qualificação faria quem consome tratá-lo como chave válida.
    """
    r = _formatar_instrumento(_REAL_UFES)
    assert r["chave_nfe"] == "2WRK-X5JV"
    assert any("não é chave de acesso válida" in p for p in r["problemas"])


def test_chave_de_nfse_com_50_digitos_e_valida():
    """Contrato de SERVIÇO é faturado por NFS-e, cuja chave tem 50 posições.

    A primeira versão desta verificação aceitava apenas os 44 dígitos da NF-e
    e acusava a chave de 50 como inválida. Um validador que reprova dado
    correto desloca a suspeita para o lado errado.
    """
    registro = dict(_REAL_UFES, chaveNFe="1" * 50)
    r = _formatar_instrumento(registro)
    assert r["chave_nfe"] == "1" * 50
    assert "problemas" not in r or not any("chave" in p for p in r["problemas"])


def test_envelope_vazio_com_status_200_e_declarado():
    """O achado central: sucesso aparente sem conteúdo.

    O PNCP registra ``statusResponseNFe="200"`` e devolve ``notaFiscalDTO``,
    ``itensNotaFiscal`` e ``eventosNotaFiscal`` nulos — em 8 de 8 notas
    medidas. Sem esta declaração, ``nota_fiscal: null`` se lê como "esta nota
    não tem itens", quando o correto é "os itens não estão disponíveis nesta
    origem". A diferença decide se alguém conclui que o contrato não foi
    faturado ou que a fonte não entrega o dado.
    """
    r = _formatar_instrumento(_REAL_UFES)
    assert r["nota_fiscal"] is None
    assert any("NÃO estão disponíveis" in p for p in r["problemas"])
    assert any("statusResponseNFe" in p for p in r["problemas"])


def test_envelope_e_string_json_e_nao_objeto_aninhado():
    """``jsonResponseNFe`` é TEXTO contendo JSON, não objeto.

    Procurávamos ``itensNotaFiscal`` como chave do objeto externo, onde nunca
    esteve. Se a origem passar a preencher o envelope, o dado precisa ser
    encontrado — este teste garante que será.
    """
    registro = dict(
        _REAL_UFES,
        jsonResponseNFe=(
            '{"notaFiscalDTO":{"numero":"123","valorNota":1500.0},'
            '"itensNotaFiscal":[{"descricaoProdutoServico":"Manutenção","valorUnitario":750.0}],'
            '"eventosNotaFiscal":null}'
        ),
    )
    r = _formatar_instrumento(registro)
    assert r["nota_fiscal"] is not None
    assert r["nota_fiscal"]["numero"] == "123"
    assert len(r["nota_fiscal"]["itens"]) == 1


def test_envelope_ilegivel_nao_se_confunde_com_envelope_vazio():
    registro = dict(_REAL_UFES, jsonResponseNFe="{isto nao e json")
    r = _formatar_instrumento(registro)
    assert r["nota_fiscal"] is None
    assert any("não é JSON legível" in p for p in r["problemas"])


def test_sem_envelope_nao_gera_problema_de_nota():
    """Ausência do campo é diferente de campo presente e vazio."""
    registro = {k: v for k, v in _REAL_UFES.items() if k != "jsonResponseNFe"}
    registro["chaveNFe"] = "1" * 44
    r = _formatar_instrumento(registro)
    assert r["nota_fiscal"] is None
    assert "problemas" not in r

_PATCH_PERIODO = (
    "mcp_radardeprecos.tools.consultar_notas_fiscais.pncp_client."
    "consultar_instrumentos_cobranca_periodo"
)
_PATCH_CONTRATO = (
    "mcp_radardeprecos.tools.consultar_notas_fiscais.pncp_client."
    "consultar_instrumentos_cobranca_contrato"
)

_INSTRUMENTO_BRUTO = {
    "tipoInstrumentoCobranca": {"id": 1, "nome": "Nota Fiscal"},
    "numeroInstrumentoCobranca": "NFE-001",
    "dataEmissao": "2026-06-15",
    "chaveAcesso": "35260600000000000000550010000000011000000010",
    "notaFiscalEletronica": {
        "numero": "1",
        "serie": "1",
        "dataEmissao": "2026-06-15",
        "emitente": {"ni": "12345678000199", "nome": "Fornecedor Teste LTDA"},
        "valorNota": 1500.0,
        "itens": [
            {
                "numeroItem": 1,
                "descricaoProdutoServico": "Notebook",
                "codigoNCM": "84713012",
                "descricaoNCM": "Máquinas automáticas de processamento de dados",
                "cfop": "5102",
                "quantidade": 3,
                "unidade": "UN",
                "valorUnitario": 500.0,
                "valorTotal": 1500.0,
            }
        ],
        "eventos": [{"tipoEvento": "Autorização", "dataEvento": "2026-06-15"}],
    },
}


async def test_rejeita_sem_identificacao():
    with pytest.raises(ValueError, match="numero_controle_pncp_contrato"):
        await consultar_notas_fiscais()


async def test_rejeita_apenas_data_inicio_sem_data_fim():
    with pytest.raises(ValueError, match="numero_controle_pncp_contrato"):
        await consultar_notas_fiscais(data_inicio="20260101")


async def test_rejeita_numero_controle_pncp_contrato_invalido():
    with pytest.raises(ValueError, match="numero_controle_pncp_contrato"):
        await consultar_notas_fiscais(numero_controle_pncp_contrato="formato-invalido")


@patch(_PATCH_CONTRATO, new_callable=AsyncMock)
async def test_modo_por_contrato_normaliza_registro(mock_contrato):
    mock_contrato.return_value = [_INSTRUMENTO_BRUTO]

    resultado = await consultar_notas_fiscais(
        numero_controle_pncp_contrato="12345678000199-2-000010/2026"
    )

    assert resultado["modo"] == "por_contrato"
    mock_contrato.assert_awaited_once_with("12345678000199", 2026, 10, pagina=1, tamanho_pagina=100)
    instrumento = resultado["instrumentos_cobranca"][0]
    assert instrumento["tipo_instrumento"] == {"id": 1, "nome": "Nota Fiscal"}
    assert instrumento["numero"] == "NFE-001"
    assert instrumento["chave_nfe"] == "35260600000000000000550010000000011000000010"
    nota = instrumento["nota_fiscal"]
    assert nota["emitente"] == {"ni": "12345678000199", "nome": "Fornecedor Teste LTDA"}
    assert nota["valor_nota"] == 1500.0
    item = nota["itens"][0]
    assert item["descricao_produto_servico"] == "Notebook"
    assert item["codigo_ncm"] == "84713012"
    assert item["valor_unitario"] == 500.0
    assert nota["eventos"] == [{"tipo": "Autorização", "data": "2026-06-15"}]
    assert any("FATURADO" in a for a in resultado["avisos"])


@patch(_PATCH_PERIODO, new_callable=AsyncMock)
async def test_modo_por_periodo_repassa_filtros_e_pagina(mock_periodo):
    mock_periodo.return_value = {"data": [_INSTRUMENTO_BRUTO], "totalRegistros": 1}

    resultado = await consultar_notas_fiscais(
        cnpj_orgao="12345678000199", data_inicio="20260101", data_fim="20260107",
    )

    assert resultado["modo"] == "por_periodo"
    mock_periodo.assert_awaited_once_with(
        data_inicial="20260101", data_final="20260107", cnpj_orgao="12345678000199",
        pagina=1, tamanho_pagina=100,
    )
    assert resultado["quantidade_retornada"] == 1
    assert resultado["total_no_periodo"] == 1


@patch(_PATCH_PERIODO, new_callable=AsyncMock)
async def test_instrumento_sem_nota_fiscal_vinculada(mock_periodo):
    mock_periodo.return_value = {
        "data": [{"tipoInstrumentoCobranca": {"id": 2, "nome": "Fatura"}, "numeroInstrumentoCobranca": "F-1"}],
        "totalRegistros": 1,
    }
    resultado = await consultar_notas_fiscais(data_inicio="20260101", data_fim="20260107")
    assert resultado["instrumentos_cobranca"][0]["nota_fiscal"] is None


@patch(_PATCH_PERIODO, new_callable=AsyncMock)
async def test_avisa_quando_nenhum_resultado(mock_periodo):
    mock_periodo.return_value = {"data": [], "totalRegistros": 0}
    resultado = await consultar_notas_fiscais(data_inicio="20260101", data_fim="20260107")
    assert resultado["quantidade_retornada"] == 0
    assert any("Nenhum instrumento" in a for a in resultado["avisos"])


@patch(_PATCH_PERIODO, new_callable=AsyncMock)
async def test_avisa_quando_limite_e_atingido(mock_periodo):
    mock_periodo.return_value = {
        "data": [dict(_INSTRUMENTO_BRUTO) for _ in range(5)],
        "totalRegistros": 20,
    }
    resultado = await consultar_notas_fiscais(
        data_inicio="20260101", data_fim="20260107", limite=5,
    )
    assert resultado["quantidade_retornada"] == 5
    assert any("20 instrumento" in a for a in resultado["avisos"])


@patch(_PATCH_PERIODO, new_callable=AsyncMock)
async def test_limite_e_limitado_a_100(mock_periodo):
    mock_periodo.return_value = {"data": [], "totalRegistros": 0}
    await consultar_notas_fiscais(data_inicio="20260101", data_fim="20260107", limite=9999)
    assert mock_periodo.call_args.kwargs["tamanho_pagina"] == 100
