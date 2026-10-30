"""Testes de `consultar_contratos_orgao_pncp` (fatiamento, paginação, dedup e resiliência)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.consultar_contratos_orgao_pncp import (
    _compra_origem,
    _fatiar_periodo,
    consultar_contratos_orgao_pncp,
)

_PATCH_ALVO = (
    "mcp_radardeprecos.tools.consultar_contratos_orgao_pncp.pncp_client.consultar_contratos"
)


def test_fatiar_periodo_gera_janelas_de_ate_30_dias():
    fatias, truncado = _fatiar_periodo("20260101", "20260228")
    assert fatias == [("20260101", "20260130"), ("20260131", "20260228")]
    assert truncado is False


def test_fatiar_periodo_periodo_curto_gera_uma_so_fatia():
    fatias, truncado = _fatiar_periodo("20260101", "20260105")
    assert fatias == [("20260101", "20260105")]
    assert truncado is False


def test_fatiar_periodo_inverte_datas_fora_de_ordem():
    fatias, _ = _fatiar_periodo("20260105", "20260101")
    assert fatias == [("20260101", "20260105")]


def test_fatiar_periodo_trunca_periodo_absurdamente_longo():
    # 40 fatias de 30 dias = 1200 dias (~3,3 anos) é o teto; um período de 10
    # anos deve ser truncado, não gerar centenas de fatias numa só chamada.
    fatias, truncado = _fatiar_periodo("20160101", "20260101")
    assert truncado is True
    assert len(fatias) == 40


async def test_rejeita_cnpj_orgao_vazio():
    with pytest.raises(ValueError, match="cnpj_orgao"):
        await consultar_contratos_orgao_pncp("")


async def test_rejeita_cnpj_orgao_com_tamanho_invalido():
    with pytest.raises(ValueError, match="14 posições"):
        await consultar_contratos_orgao_pncp("123")


async def test_aceita_cnpj_orgao_alfanumerico_e_avisa():
    """CNPJ alfanumérico passa — e a resposta diz que a fonte é incógnita.

    O aviso é o ponto: se o PNCP recusar o formato novo, esta tool devolve
    zero contratos, e zero contratos é resposta legítima para um órgão que
    não contratou no período. Sem o aviso, os dois casos são iguais.
    """
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = {"data": [], "totalPaginas": 0, "totalRegistros": 0}
        resultado = await consultar_contratos_orgao_pncp(
            "12.ABC.345/01DE-35", data_inicial="20260101", data_final="20260105"
        )
    assert resultado["cnpj_orgao"] == "12ABC34501DE35"
    assert any("alfanumérico" in a for a in resultado["avisos"])


async def test_aceita_cnpj_orgao_com_mascara_e_limpa_para_so_digitos():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = {"data": [], "totalPaginas": 0, "totalRegistros": 0}
        resultado = await consultar_contratos_orgao_pncp(
            "00.414.607/0001-18", data_inicial="20260101", data_final="20260105"
        )
    assert resultado["cnpj_orgao"] == "00414607000118"
    kwargs = mock.call_args.kwargs
    assert kwargs["cnpj_orgao"] == "00414607000118"


async def test_rejeita_data_inicial_sem_data_final():
    with pytest.raises(ValueError, match="data_inicial E data_final"):
        await consultar_contratos_orgao_pncp("00414607000118", data_inicial="20260101")


async def test_sem_datas_usa_janela_padrao_de_meses():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = {"data": [], "totalPaginas": 0, "totalRegistros": 0}
        resultado = await consultar_contratos_orgao_pncp("00414607000118", janelas_meses=1)
    # Só verifica que um período foi calculado automaticamente (não vazio) —
    # a lógica de cálculo já é testada em test_utils_datas.py.
    assert resultado["periodo"]["data_inicial"]
    assert resultado["periodo"]["data_final"]


async def test_pagina_ate_esgotar_totalPaginas():
    pagina_1 = {
        "data": [{"numeroControlePNCP": f"X-{i}"} for i in range(50)],
        "totalPaginas": 2,
        "totalRegistros": 53,
    }
    pagina_2 = {
        "data": [{"numeroControlePNCP": f"X-{i}"} for i in range(50, 53)],
        "totalPaginas": 2,
        "totalRegistros": 53,
    }
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.side_effect = [pagina_1, pagina_2]
        resultado = await consultar_contratos_orgao_pncp(
            "00414607000118", data_inicial="20260101", data_final="20260105"
        )
    assert resultado["quantidade_retornada"] == 53
    assert mock.await_count == 2


async def test_deduplica_registros_repetidos_entre_chamadas():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = {
            "data": [{"numeroControlePNCP": "SAME-ID"}],
            "totalPaginas": 1,
            "totalRegistros": 1,
        }
        # Período de 2 meses -> 2 fatias -> 2 chamadas -> mesmo registro nas duas.
        resultado = await consultar_contratos_orgao_pncp(
            "00414607000118", data_inicial="20260101", data_final="20260228"
        )
    assert resultado["quantidade_retornada"] == 1


async def test_deduplica_por_hash_quando_sem_campo_identificador_conhecido():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = {
            "data": [{"objeto": "Igual nos dois", "valor": 10}],
            "totalPaginas": 1,
            "totalRegistros": 1,
        }
        resultado = await consultar_contratos_orgao_pncp(
            "00414607000118", data_inicial="20260101", data_final="20260228"
        )
    assert resultado["quantidade_retornada"] == 1


async def test_falha_isolada_em_uma_fatia_nao_derruba_as_demais():
    fatia_1 = {
        "data": [{"numeroControlePNCP": "OK-1"}],
        "totalPaginas": 1,
        "totalRegistros": 1,
    }
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.side_effect = [fatia_1, RuntimeError("PNCP instável (simulado)")]
        resultado = await consultar_contratos_orgao_pncp(
            "00414607000118", data_inicial="20260101", data_final="20260228"
        )
    assert resultado["quantidade_retornada"] == 1
    assert any("falha" in a.lower() for a in resultado["avisos"])
    assert any("20260131" in a for a in resultado["avisos"])


async def test_avisa_quando_limite_e_atingido():
    pagina_cheia = {
        "data": [{"numeroControlePNCP": f"X-{i}"} for i in range(50)],
        "totalPaginas": 3,
        "totalRegistros": 150,
    }
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = pagina_cheia
        resultado = await consultar_contratos_orgao_pncp(
            "00414607000118", data_inicial="20260101", data_final="20260105", limite=10,
        )
    assert resultado["quantidade_retornada"] == 10
    assert any("truncado" in a.lower() for a in resultado["avisos"])


async def test_avisa_quando_nenhum_resultado():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = {"data": [], "totalPaginas": 0, "totalRegistros": 0}
        resultado = await consultar_contratos_orgao_pncp(
            "00414607000118", data_inicial="20260101", data_final="20260105"
        )
    assert resultado["quantidade_retornada"] == 0
    assert any("nenhum" in a.lower() for a in resultado["avisos"])


_REGISTRO_CRU_TRADUCAO = {
    "numeroControlePNCP": "00414607000118-2-000417/2025",
    "objetoContrato": "Objeto de teste",
    "niFornecedor": "12345678000199",
    "nomeRazaoSocialFornecedor": "Fornecedor Teste LTDA",
    "tipoContrato": {"id": 1, "nome": "Contrato"},
    "valorInicial": 1000.0,
    "valorGlobal": 1200.0,
    "valorAcumulado": 500.0,
    "valorParcela": 100.0,
    "dataAssinatura": "2025-01-10",
    "dataVigenciaInicio": "2025-01-15",
    "dataVigenciaFim": "2026-01-15",
    "frutoAdesao": False,
    "temRemanejamento": False,
    "receita": False,
    "emendaParlamentar": None,
    "numeroParcelas": 12,
    "numeroRetificacao": 0,
    "categoriaProcesso": {"id": 1, "nome": "Compras"},
    "orgaoEntidade": {"cnpj": "00414607000118", "razaoSocial": "Órgão Teste"},
    "unidadeOrgao": {
        "codigoUnidade": "123",
        "nomeUnidade": "Unidade Teste",
        "ufSigla": "DF",
        "municipioNome": "Brasília",
    },
}


async def test_registros_sao_traduzidos_para_snake_case():
    # A partir da v0.2.2, os campos são traduzidos para snake_case com base
    # no schema oficial (RecuperarContratoDTO) — ver docstring do módulo.
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = {
            "data": [_REGISTRO_CRU_TRADUCAO], "totalPaginas": 1, "totalRegistros": 1,
        }
        resultado = await consultar_contratos_orgao_pncp(
            "00414607000118", data_inicial="20260101", data_final="20260105"
        )
    contrato = resultado["contratos"][0]
    assert contrato["numero_controle_pncp"] == "00414607000118-2-000417/2025"
    assert contrato["objeto"] == "Objeto de teste"
    assert contrato["fornecedor"] == {"cnpj": "12345678000199", "nome": "Fornecedor Teste LTDA"}
    assert contrato["tipo_contrato"] == {"id": 1, "nome": "Contrato"}
    assert contrato["valores"] == {
        "valor_inicial": 1000.0, "valor_global": 1200.0,
        "valor_acumulado": 500.0, "valor_parcela": 100.0,
    }
    assert contrato["datas"] == {
        "data_assinatura": "2025-01-10",
        "data_vigencia_inicio": "2025-01-15",
        "data_vigencia_fim": "2026-01-15",
    }
    assert contrato["orgao"] == {"cnpj": "00414607000118", "razao_social": "Órgão Teste"}
    assert contrato["unidade"] == {
        "codigo": "123", "nome": "Unidade Teste", "uf": "DF", "municipio": "Brasília",
    }
    assert contrato["compra_origem"] is None  # sem numeroControlePncpCompra
    assert "dados_originais" not in contrato  # incluir_bruto=False por padrão


async def test_incluir_bruto_adiciona_dados_originais():
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = {
            "data": [_REGISTRO_CRU_TRADUCAO], "totalPaginas": 1, "totalRegistros": 1,
        }
        resultado = await consultar_contratos_orgao_pncp(
            "00414607000118", data_inicial="20260101", data_final="20260105",
            incluir_bruto=True,
        )
    contrato = resultado["contratos"][0]
    assert contrato["dados_originais"] == _REGISTRO_CRU_TRADUCAO


def test_compra_origem_extrai_cnpj_ano_sequencial_e_monta_link():
    # Exemplo real, confirmado ao vivo em 2026-07-08 (contrato do TCU).
    registro = {"numeroControlePncpCompra": "00414607000118-1-000334/2025"}
    origem = _compra_origem(registro)
    assert origem == {
        "cnpj": "00414607000118",
        "ano": 2025,
        "sequencial": 334,
        "numero_controle_pncp_compra": "00414607000118-1-000334/2025",
        "link_pagina_pncp": "https://pncp.gov.br/app/editais/00414607000118/2025/334",
    }


def test_compra_origem_none_quando_campo_ausente():
    assert _compra_origem({}) is None


def test_compra_origem_none_quando_formato_inesperado():
    assert _compra_origem({"numeroControlePncpCompra": "formato-invalido"}) is None


async def test_compra_origem_presente_mesmo_em_registro_de_empenho():
    # Confirmado ao vivo: numeroControlePncpCompra vem preenchido mesmo
    # quando tipoContrato é "Empenho", não só em contratos formais.
    registro_empenho = {
        "numeroControlePNCP": "00414607000118-2-000417/2025",
        "numeroControlePncpCompra": "00414607000118-1-000001/2027",
        "tipoContrato": {"id": 7, "nome": "Empenho"},
    }
    with patch(_PATCH_ALVO, new_callable=AsyncMock) as mock:
        mock.return_value = {"data": [registro_empenho], "totalPaginas": 1, "totalRegistros": 1}
        resultado = await consultar_contratos_orgao_pncp(
            "00414607000118", data_inicial="20260101", data_final="20260105"
        )
    origem = resultado["contratos"][0]["compra_origem"]
    assert origem["cnpj"] == "00414607000118"
    assert origem["ano"] == 2027
    assert origem["sequencial"] == 1
