"""Testes de `radar_vencimentos` (clientes Compras.gov.br e PNCP mockados).

Patches aplicados diretamente nos módulos `compras_client`/`pncp_client`
(mesmo padrão de `test_consultar_familia_contratacao_pncp.py`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.radar_vencimentos import radar_vencimentos

_PATCH_CONTRATOS = "mcp_radardeprecos.clients.compras_client.consultar_contratos_fim_vigencia"
_PATCH_ARP = "mcp_radardeprecos.clients.compras_client.consultar_arp_fim_vigencia"
_PATCH_ATAS_PNCP = "mcp_radardeprecos.clients.pncp_client.consultar_atas_periodo"
_PATCH_CONSULTAR_ORGAO = "mcp_radardeprecos.clients.compras_client.consultar_orgao"
_PATCH_CONSULTAR_UASG = "mcp_radardeprecos.clients.compras_client.consultar_uasg"

_CNPJ_ORGAO = "15126437000143"

_CONTRATO_BRUTO = {
    "numeroContrato": "001/2026",
    "objeto": "Serviços de manutenção",
    "nomeTipo": "Contrato",
    "nomeModalidadeCompra": "Pregão - Eletrônico",
    "niFornecedor": "12345678000199",
    "nomeRazaoSocialFornecedor": "Fornecedor Teste LTDA",
    "codigoOrgao": "25201",
    "nomeOrgao": "Órgão Teste",
    "codigoUnidadeGestora": "179087",
    "nomeUnidadeGestora": "Unidade Teste",
    "dataVigenciaInicial": "2025-08-01",
    "dataVigenciaFinal": "2026-08-01",
    "valorGlobal": 50000.0,
    "numeroControlePncpContrato": "25201-2-000010/2025",
    "numeroControlePncpCompra": "25201-1-000005/2025",
}

_ATA_BRUTA = {
    "numeroAtaRegistroPreco": "001/2026",
    "codigoUnidadeGerenciadora": "179087",
    "nomeUnidadeGerenciadora": "Unidade Teste",
    "codigoOrgao": "25201",
    "nomeOrgao": "Órgão Teste",
    "objeto": "Registro de preços de notebooks",
    "nomeModalidadeCompra": "Pregão - Eletrônico",
    "dataVigenciaInicial": "2025-08-01",
    "dataVigenciaFinal": "2026-08-01",
    "valorTotal": 1000000.0,
    "statusAta": "Vigente",
    "numeroControlePncpAta": "25201-1-000005/2025-000001",
    "numeroControlePncpCompra": "25201-1-000005/2025",
    "linkAtaPNCP": "https://pncp.gov.br/app/atas/25201/2025/5/1",
}

# nomes reais do AtaRegistroPrecoPeriodoDTO
# (confirmados ao vivo) — fixture de regressão para o mapeamento correto.
_ATA_PNCP_BRUTA = {
    "numeroControlePNCPAta": "25201-1-000005/2025-000001",
    "numeroControlePNCPCompra": "25201-1-000005/2025",
    "objetoContratacao": "Registro de preços de notebooks",
    "vigenciaInicio": "2025-08-01",
    "vigenciaFim": "2026-08-01",
    "possibilidadeAdesao": True,
    "cancelado": False,
    "dataCancelamento": None,
    "cnpjOrgao": _CNPJ_ORGAO,
    "nomeOrgao": "Órgão Teste",
}

_ORGAO_BRUTO = {
    "codigoOrgao": 25201,
    "nomeOrgao": "Órgão Teste",
    "cnpjCpfOrgao": _CNPJ_ORGAO,
}

_UASG_BRUTA = {
    "codigoUasg": "179087",
    "nomeUasg": "Unidade Teste",
    "siglaUf": "DF",
    "codigoOrgao": 25201,
    "cnpjCpfOrgao": _CNPJ_ORGAO,
}


def _resposta_compras(itens, total=None):
    return {"resultado": itens, "totalRegistros": total if total is not None else len(itens)}


async def test_rejeita_tipo_invalido():
    with pytest.raises(ValueError, match="tipo"):
        await radar_vencimentos("outro")


async def test_rejeita_falta_de_codigo_orgao_para_tipo_contratos():
    with pytest.raises(ValueError, match="codigo_orgao"):
        await radar_vencimentos("contratos")


async def test_rejeita_apenas_uma_data_informada():
    with pytest.raises(ValueError, match="data_fim_vigencia_inicio E data_fim_vigencia_fim"):
        await radar_vencimentos(
            "atas", data_fim_vigencia_inicio="2026-07-01",
        )


async def test_rejeita_janela_invertida():
    with pytest.raises(ValueError, match="posterior"):
        await radar_vencimentos(
            "atas",
            data_fim_vigencia_inicio="2026-08-01",
            data_fim_vigencia_fim="2026-07-01",
        )


async def test_rejeita_vigentes_em_para_tipo_contratos():
    with pytest.raises(ValueError, match="vigentes_em"):
        await radar_vencimentos("contratos", codigo_orgao="25201", vigentes_em="2026-07-01")


async def test_rejeita_vigentes_em_combinado_com_datas_explicitas():
    with pytest.raises(ValueError, match="vigentes_em"):
        await radar_vencimentos(
            "atas",
            vigentes_em="2026-07-01",
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )


async def test_sem_datas_usa_dias_a_frente_padrao():
    with patch(_PATCH_ARP, new_callable=AsyncMock) as mock_arp, \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp:
        mock_arp.return_value = _resposta_compras([])
        mock_pncp.return_value = {"data": []}
        resultado = await radar_vencimentos("atas", cnpj_orgao=_CNPJ_ORGAO)
    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert resultado["periodo"]["data_fim_vigencia_inicio"] == hoje
    assert resultado["periodo"]["data_fim_vigencia_fim"] > hoje


async def test_tipo_contratos_chama_compras_client_com_codigo_orgao_e_formata_registros():
    with patch(_PATCH_CONTRATOS, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta_compras([_CONTRATO_BRUTO])
        resultado = await radar_vencimentos(
            "contratos",
            codigo_orgao="25201",
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )
    assert mock.call_args.kwargs["codigo_orgao"] == "25201"
    assert mock.call_args.kwargs["data_vigencia_final_min"] == "2026-07-01"
    assert mock.call_args.kwargs["data_vigencia_final_max"] == "2026-09-30"
    contrato = resultado["contratos"][0]
    assert contrato["numero_contrato"] == "001/2026"
    assert contrato["objeto"] == "Serviços de manutenção"
    assert contrato["ni_fornecedor"] == "12345678000199"
    assert contrato["data_vigencia_final"] == "2026-08-01"
    assert contrato["valor_global"] == 50000.0
    assert "atas" not in resultado
    assert "atas_pncp_complemento" not in resultado


async def test_tipo_atas_com_cnpj_explicito_agrega_complemento_pncp_com_nomes_reais():
    with patch(_PATCH_ARP, new_callable=AsyncMock) as mock_arp, \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp:
        mock_arp.return_value = _resposta_compras([_ATA_BRUTA])
        mock_pncp.return_value = {"data": [_ATA_PNCP_BRUTA]}
        resultado = await radar_vencimentos(
            "atas",
            cnpj_orgao=_CNPJ_ORGAO,
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )
    assert mock_arp.call_args.kwargs["data_vigencia_final_min"] == "2026-07-01"
    assert mock_arp.call_args.kwargs["data_vigencia_final_max"] == "2026-09-30"
    # Datas repassadas ao complemento PNCP devem estar em AAAAMMDD (sem hífens).
    assert mock_pncp.call_args.kwargs["data_inicial"] == "20260701"
    assert mock_pncp.call_args.kwargs["data_final"] == "20260930"
    # Bug A: o cnpj do órgão precisa ser repassado ao endpoint /v1/atas.
    assert mock_pncp.call_args.kwargs["cnpj"] == _CNPJ_ORGAO

    ata = resultado["atas"][0]
    assert ata["numero_ata_registro_preco"] == "001/2026"
    assert ata["codigo_unidade_gerenciadora"] == "179087"
    assert ata["valor_total"] == 1000000.0

    # Bug B: campos do complemento devem vir preenchidos com os nomes reais
    # do DTO, não mais null.
    complemento = resultado["atas_pncp_complemento"][0]
    assert complemento["numero_controle_pncp_ata"] == "25201-1-000005/2025-000001"
    assert complemento["numero_controle_pncp_compra"] == "25201-1-000005/2025"
    assert complemento["objeto"] == "Registro de preços de notebooks"
    assert complemento["data_vigencia_inicio"] == "2025-08-01"
    assert complemento["data_vigencia_fim"] == "2026-08-01"
    assert complemento["possibilidade_adesao"] is True
    assert complemento["cancelado"] is False
    assert complemento["cnpj_orgao"] == _CNPJ_ORGAO
    assert complemento["nome_orgao"] == "Órgão Teste"
    assert resultado["avisos"] == []


async def test_sem_cnpj_resolvivel_suprime_complemento_pncp_com_aviso():
    with patch(_PATCH_ARP, new_callable=AsyncMock) as mock_arp, \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp:
        mock_arp.return_value = _resposta_compras([_ATA_BRUTA])
        resultado = await radar_vencimentos(
            "atas",
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )
    # Bug A: sem CNPJ resolvível (nenhum cnpj_orgao/codigo_orgao/
    # codigo_unidade_gerenciadora informado), o complemento nacional do PNCP
    # nunca deve ser chamado — só suprimido com aviso.
    mock_pncp.assert_not_called()
    assert resultado["atas_pncp_complemento"] == []
    assert any("suprimido" in a for a in resultado["avisos"])


async def test_codigo_unidade_gerenciadora_resolve_cnpj_automaticamente():
    with patch(_PATCH_ARP, new_callable=AsyncMock) as mock_arp, \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp, \
         patch(_PATCH_CONSULTAR_UASG, new_callable=AsyncMock) as mock_uasg:
        mock_arp.return_value = _resposta_compras([_ATA_BRUTA])
        mock_pncp.return_value = {"data": []}
        mock_uasg.return_value = _resposta_compras([_UASG_BRUTA])
        resultado = await radar_vencimentos(
            "atas",
            codigo_unidade_gerenciadora="179087",
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )
    mock_uasg.assert_called_once()
    assert mock_uasg.call_args.kwargs["codigo_uasg"] == "179087"
    assert mock_pncp.call_args.kwargs["cnpj"] == _CNPJ_ORGAO
    assert resultado["atas_pncp_complemento"] == []


async def test_falha_isolada_no_complemento_pncp_nao_derruba_o_radar():
    with patch(_PATCH_ARP, new_callable=AsyncMock) as mock_arp, \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp:
        mock_arp.return_value = _resposta_compras([_ATA_BRUTA])
        mock_pncp.side_effect = RuntimeError("PNCP instável (simulado)")
        resultado = await radar_vencimentos(
            "atas",
            cnpj_orgao=_CNPJ_ORGAO,
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )
    # Resultado principal (Compras.gov.br) preservado mesmo com falha do complemento.
    assert len(resultado["atas"]) == 1
    assert resultado["atas_pncp_complemento"] == []
    assert any("Complemento de atas do PNCP" in a for a in resultado["avisos"])


async def test_avisa_quando_total_no_periodo_excede_retornado():
    with patch(_PATCH_CONTRATOS, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta_compras([_CONTRATO_BRUTO], total=42)
        resultado = await radar_vencimentos(
            "contratos",
            codigo_orgao="25201",
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )
    assert resultado["total_no_periodo"] == 42
    assert resultado["quantidade_retornada"] == 1
    assert any("42 registro" in a for a in resultado["avisos"])


async def test_avisa_quando_nenhum_registro_encontrado():
    with patch(_PATCH_CONTRATOS, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta_compras([])
        resultado = await radar_vencimentos(
            "contratos",
            codigo_orgao="25201",
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )
    assert resultado["quantidade_retornada"] == 0
    assert any("Nenhum(a) contrato(s)" in a for a in resultado["avisos"])


# --- Item 6, Melhoria C: codigo_orgao com fan-out por UASG ---


async def test_codigo_orgao_para_atas_resolve_uasgs_e_faz_fanout():
    ata_uasg_1 = dict(_ATA_BRUTA)
    ata_uasg_2 = dict(_ATA_BRUTA, numeroAtaRegistroPreco="002/2026", codigoUnidadeGerenciadora="179088")

    async def _consultar_uasg(**kwargs):
        if kwargs.get("cnpj_cpf_orgao") == _CNPJ_ORGAO:
            return _resposta_compras(
                [_UASG_BRUTA, dict(_UASG_BRUTA, codigoUasg="179088")]
            )
        return _resposta_compras([])

    async def _consultar_arp_fim_vigencia(**kwargs):
        if kwargs.get("codigo_unidade_gerenciadora") == "179087":
            return _resposta_compras([ata_uasg_1])
        if kwargs.get("codigo_unidade_gerenciadora") == "179088":
            return _resposta_compras([ata_uasg_2])
        return _resposta_compras([])

    with patch(_PATCH_CONSULTAR_ORGAO, new_callable=AsyncMock) as mock_orgao, \
         patch(_PATCH_CONSULTAR_UASG, new=AsyncMock(side_effect=_consultar_uasg)), \
         patch(_PATCH_ARP, new=AsyncMock(side_effect=_consultar_arp_fim_vigencia)), \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp:
        mock_orgao.return_value = _resposta_compras([_ORGAO_BRUTO])
        mock_pncp.return_value = {"data": []}
        resultado = await radar_vencimentos(
            "atas",
            codigo_orgao="25201",
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )
    mock_orgao.assert_called_once()
    assert mock_orgao.call_args.kwargs["codigo_orgao"] == 25201
    numeros = {a["numero_ata_registro_preco"] for a in resultado["atas"]}
    assert numeros == {"001/2026", "002/2026"}
    assert resultado["total_no_periodo"] == 2
    # O CNPJ resolvido do órgão deve ser repassado ao complemento do PNCP.
    assert mock_pncp.call_args.kwargs["cnpj"] == _CNPJ_ORGAO


async def test_codigo_orgao_sem_cnpj_resolvivel_avisa_e_nao_derruba():
    with patch(_PATCH_CONSULTAR_ORGAO, new_callable=AsyncMock) as mock_orgao:
        mock_orgao.return_value = _resposta_compras([])
        resultado = await radar_vencimentos(
            "atas",
            codigo_orgao="999999",
            data_fim_vigencia_inicio="2026-07-01",
            data_fim_vigencia_fim="2026-09-30",
        )
    assert resultado["atas"] == []
    assert any("CNPJ do órgão" in a for a in resultado["avisos"])


# --- Item 6, Melhoria D: atalho vigentes_em ---


async def test_vigentes_em_define_janela_de_24_meses_e_filtra_vigencia_inicial():
    ata_ja_vigente = dict(_ATA_BRUTA, dataVigenciaInicial="2026-01-01")
    ata_ainda_nao_iniciada = dict(
        _ATA_BRUTA, numeroAtaRegistroPreco="003/2026", dataVigenciaInicial="2026-08-01",
    )
    with patch(_PATCH_ARP, new_callable=AsyncMock) as mock_arp, \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp:
        mock_arp.return_value = _resposta_compras([ata_ja_vigente, ata_ainda_nao_iniciada])
        mock_pncp.return_value = {"data": []}
        resultado = await radar_vencimentos(
            "atas", cnpj_orgao=_CNPJ_ORGAO, vigentes_em="2026-07-12",
        )
    assert resultado["periodo"]["data_fim_vigencia_inicio"] == "2026-07-12"
    assert resultado["periodo"]["data_fim_vigencia_fim"] == "2028-07-12"
    assert mock_arp.call_args.kwargs["data_vigencia_final_min"] == "2026-07-12"
    assert mock_arp.call_args.kwargs["data_vigencia_final_max"] == "2028-07-12"
    numeros = {a["numero_ata_registro_preco"] for a in resultado["atas"]}
    assert numeros == {"001/2026"}
    assert any("removida" in a for a in resultado["avisos"])


async def test_vigentes_em_aceita_hoje_como_atalho():
    with patch(_PATCH_ARP, new_callable=AsyncMock) as mock_arp, \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp:
        mock_arp.return_value = _resposta_compras([])
        mock_pncp.return_value = {"data": []}
        resultado = await radar_vencimentos("atas", cnpj_orgao=_CNPJ_ORGAO, vigentes_em="hoje")
    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert resultado["periodo"]["data_fim_vigencia_inicio"] == hoje


# --- incluir_bruto opt-in ---


async def test_incluir_bruto_false_por_padrao_nao_inclui_dados_originais():
    with patch(_PATCH_ARP, new_callable=AsyncMock) as mock_arp, \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp:
        mock_arp.return_value = _resposta_compras([_ATA_BRUTA])
        mock_pncp.return_value = {"data": [_ATA_PNCP_BRUTA]}
        resultado = await radar_vencimentos("atas", cnpj_orgao=_CNPJ_ORGAO)
    assert "dados_originais" not in resultado["atas"][0]
    assert "dados_originais" not in resultado["atas_pncp_complemento"][0]


async def test_incluir_bruto_true_adiciona_dados_originais_em_todas_as_listas():
    with patch(_PATCH_ARP, new_callable=AsyncMock) as mock_arp, \
         patch(_PATCH_ATAS_PNCP, new_callable=AsyncMock) as mock_pncp:
        mock_arp.return_value = _resposta_compras([_ATA_BRUTA])
        mock_pncp.return_value = {"data": [_ATA_PNCP_BRUTA]}
        resultado = await radar_vencimentos("atas", cnpj_orgao=_CNPJ_ORGAO, incluir_bruto=True)
    assert resultado["atas"][0]["dados_originais"] == _ATA_BRUTA
    assert resultado["atas_pncp_complemento"][0]["dados_originais"] == _ATA_PNCP_BRUTA


async def test_incluir_bruto_true_para_contratos():
    with patch(_PATCH_CONTRATOS, new_callable=AsyncMock) as mock:
        mock.return_value = _resposta_compras([_CONTRATO_BRUTO])
        resultado = await radar_vencimentos(
            "contratos", codigo_orgao="25201", incluir_bruto=True,
        )
    assert resultado["contratos"][0]["dados_originais"] == _CONTRATO_BRUTO
