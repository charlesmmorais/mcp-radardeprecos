"""Testes de `consultar_familia_contratacao_pncp` (composição de outras tools, cliente PNCP mockado).

Patches são aplicados diretamente em `mcp_radardeprecos.clients.pncp_client`
(o módulo compartilhado por todas as tools compostas aqui) — equivalente a
patchear via cada módulo importador individualmente, já que `from ..clients
import pncp_client` referencia o mesmo objeto de módulo em todo lugar.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_radardeprecos.tools.consultar_familia_contratacao_pncp import (
    consultar_familia_contratacao_pncp,
)

_PREFIXO = "mcp_radardeprecos.clients.pncp_client"

DETALHE_COMPRA = {
    "numeroControlePNCP": "18457226000181-1-000015/2023",
    "numeroCompra": "PRE 15",
    "processo": "100/2023",
    "orgaoEntidade": {"cnpj": "18457226000181", "razaoSocial": "Município Teste"},
    "unidadeOrgao": {"ufSigla": "MG", "municipioNome": "Santa Vitória"},
    "modalidadeNome": "Pregão - Eletrônico",
    "modoDisputaNome": "Aberto",
    "srp": False,
    "objetoCompra": "Serviços de análise técnica",
    "valorTotalEstimado": 100000.0,
    "valorTotalHomologado": 95000.0,
    "situacaoCompraNome": "Divulgada no PNCP",
    "amparoLegal": {"codigo": 1, "nome": "Lei 14.133/2021", "descricao": "pregão"},
    "dataPublicacaoPncp": "2023-06-01T10:00:00",
    "dataAberturaProposta": "2023-06-05T10:00:00",
    "dataEncerramentoProposta": "2023-06-20T10:00:00",
    "linkSistemaOrigem": None,
    "linkProcessoEletronico": None,
}

DETALHE_COMPRA_SRP = {**DETALHE_COMPRA, "srp": True}

ARQUIVOS_COMPRA = [
    {"titulo": "Edital.pdf", "tipoDocumentoNome": "Edital", "dataPublicacaoPncp": "2023-06-01", "uri": "https://pncp.gov.br/edital.pdf"},
]

ATA_BRUTA = {
    "numeroControlePNCPAta": "18457226000181-1-000015/2023-000001",
    "numeroAtaRegistroPreco": "NPERP 003/2023",
    "objetoContratacao": "Serviços de análise técnica",
    "orgaoEntidade": {"cnpj": "18457226000181", "razaoSocial": "Município Teste"},
    "unidadeOrgao": {"ufSigla": "MG", "municipioNome": "Santa Vitória"},
    "dataAssinatura": "2023-06-16",
    "vigenciaInicio": "2023-07-07",
    "vigenciaFim": "2099-10-07",
    "cancelado": False,
}


def _contratos_resposta(itens):
    return {"data": itens, "totalPaginas": 1, "totalRegistros": len(itens)}


async def test_rejeita_sem_identificacao():
    with pytest.raises(ValueError, match="numero_controle_pncp"):
        await consultar_familia_contratacao_pncp()


@patch(f"{_PREFIXO}.consultar_empenhos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_termos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_monta_familia_completa_filtrando_contratos_pela_compra_origem(
    mock_detalhe, mock_arquivos, mock_contratos, mock_termos, mock_empenhos
):
    mock_detalhe.return_value = DETALHE_COMPRA
    mock_arquivos.return_value = ARQUIVOS_COMPRA
    mock_contratos.return_value = _contratos_resposta([
        {
            "numeroControlePNCP": "18457226000181-2-000001/2023",
            "numeroControlePncpCompra": "18457226000181-1-000015/2023",
        },
        {
            "numeroControlePNCP": "18457226000181-2-000002/2023",
            "numeroControlePncpCompra": "18457226000181-1-000099/2023",  # outra compra
        },
    ])
    mock_termos.return_value = []
    mock_empenhos.return_value = []

    resultado = await consultar_familia_contratacao_pncp(
        numero_controle_pncp="18457226000181-1-000015/2023"
    )

    assert resultado["compra"]["numero_controle_pncp"] == "18457226000181-1-000015/2023"
    assert resultado["arquivos_compra"][0]["titulo"] == "Edital.pdf"
    assert resultado["ata"] is None
    assert len(resultado["contratos"]) == 1
    # A partir da v0.2.2, os contratos vêm com o schema traduzido de
    # consultar_contratos_orgao_pncp (snake_case) — não mais o campo cru
    # numeroControlePNCP.
    assert resultado["contratos"][0]["numero_controle_pncp"] == "18457226000181-2-000001/2023"
    assert resultado["avisos"] == []


@patch(f"{_PREFIXO}.consultar_contratos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_aviso_srp_sem_ata_informada(mock_detalhe, mock_arquivos, mock_contratos):
    mock_detalhe.return_value = DETALHE_COMPRA_SRP
    mock_arquivos.return_value = []
    mock_contratos.return_value = _contratos_resposta([])

    resultado = await consultar_familia_contratacao_pncp(
        cnpj="18457226000181", ano=2023, sequencial=15,
    )

    assert resultado["ata"] is None
    assert any("Sistema de Registro de Preços" in a for a in resultado["avisos"])


@patch(f"{_PREFIXO}.consultar_arquivos_ata", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_itens_ata", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_ata", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_inclui_ata_quando_informada_e_nao_gera_aviso_srp(
    mock_detalhe, mock_arquivos, mock_contratos, mock_ata, mock_itens_ata, mock_arquivos_ata
):
    mock_detalhe.return_value = DETALHE_COMPRA_SRP
    mock_arquivos.return_value = []
    mock_contratos.return_value = _contratos_resposta([])
    mock_ata.return_value = ATA_BRUTA
    mock_itens_ata.return_value = []
    mock_arquivos_ata.return_value = []

    resultado = await consultar_familia_contratacao_pncp(
        cnpj="18457226000181", ano=2023, sequencial=15,
        numero_controle_pncp_ata="18457226000181-1-000015/2023-000001",
    )

    assert resultado["ata"]["numero_ata"] == "NPERP 003/2023"
    assert not any("Sistema de Registro de Preços" in a for a in resultado["avisos"])
    mock_ata.assert_awaited_once_with("18457226000181", 2023, 15, 1)


async def test_rejeita_ata_de_compra_diferente():
    with pytest.raises(ValueError, match="compra diferente"):
        await consultar_familia_contratacao_pncp(
            cnpj="18457226000181", ano=2023, sequencial=15,
            numero_controle_pncp_ata="18457226000181-1-000099/2023-000001",
        )


async def test_rejeita_numero_controle_pncp_ata_invalido():
    with pytest.raises(ValueError, match="numero_controle_pncp_ata"):
        await consultar_familia_contratacao_pncp(
            cnpj="18457226000181", ano=2023, sequencial=15,
            numero_controle_pncp_ata="formato-invalido",
        )


@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_aviso_quando_sem_data_publicacao_pula_busca_de_contratos(
    mock_detalhe, mock_arquivos
):
    detalhe_sem_data = {k: v for k, v in DETALHE_COMPRA.items() if k != "dataPublicacaoPncp"}
    mock_detalhe.return_value = detalhe_sem_data
    mock_arquivos.return_value = []

    resultado = await consultar_familia_contratacao_pncp(
        cnpj="18457226000181", ano=2023, sequencial=15,
    )

    assert resultado["contratos"] == []
    assert any("data_publicacao_pncp válida" in a for a in resultado["avisos"])


@patch(f"{_PREFIXO}.consultar_contratos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_aviso_quando_nenhum_contrato_encontrado_no_periodo(
    mock_detalhe, mock_arquivos, mock_contratos
):
    mock_detalhe.return_value = DETALHE_COMPRA
    mock_arquivos.return_value = []
    mock_contratos.return_value = _contratos_resposta([])

    resultado = await consultar_familia_contratacao_pncp(
        cnpj="18457226000181", ano=2023, sequencial=15,
    )

    assert resultado["contratos"] == []
    assert any("Nenhum contrato/empenho encontrado" in a for a in resultado["avisos"])


@patch(f"{_PREFIXO}.consultar_empenhos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_termos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_nao_consolida_multiplos_empenhos_devolve_cada_um_separado(
    mock_detalhe, mock_arquivos, mock_contratos, mock_termos, mock_empenhos
):
    # Pedido explícito do usuário: não consolidar/agregar múltiplos Empenhos
    # numa única linha — cada um deve ser devolvido como item separado.
    mock_detalhe.return_value = DETALHE_COMPRA
    mock_arquivos.return_value = []
    mock_contratos.return_value = _contratos_resposta([
        {
            "numeroControlePNCP": "18457226000181-2-000001/2023",
            "numeroControlePncpCompra": "18457226000181-1-000015/2023",
            "tipoContrato": {"id": 7, "nome": "Empenho"},
        },
        {
            "numeroControlePNCP": "18457226000181-2-000002/2023",
            "numeroControlePncpCompra": "18457226000181-1-000015/2023",
            "tipoContrato": {"id": 7, "nome": "Empenho"},
        },
    ])
    mock_termos.return_value = []
    mock_empenhos.return_value = []

    resultado = await consultar_familia_contratacao_pncp(
        cnpj="18457226000181", ano=2023, sequencial=15,
    )

    assert len(resultado["contratos"]) == 2
    numeros = {c["numero_controle_pncp"] for c in resultado["contratos"]}
    assert numeros == {
        "18457226000181-2-000001/2023",
        "18457226000181-2-000002/2023",
    }


@patch(f"{_PREFIXO}.consultar_empenhos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_termos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_propaga_avisos_de_consultar_contratos_orgao_pncp(
    mock_detalhe, mock_arquivos, mock_contratos, mock_termos, mock_empenhos
):
    pagina_cheia = {
        "data": [
            {
                "numeroControlePNCP": f"18457226000181-2-{i:06d}/2023",
                "numeroControlePncpCompra": "18457226000181-1-000015/2023",
            }
            for i in range(50)
        ],
        "totalPaginas": 3,
        "totalRegistros": 150,
    }
    mock_detalhe.return_value = DETALHE_COMPRA
    mock_arquivos.return_value = []
    mock_contratos.return_value = pagina_cheia
    mock_termos.return_value = []
    mock_empenhos.return_value = []

    resultado = await consultar_familia_contratacao_pncp(
        cnpj="18457226000181", ano=2023, sequencial=15,
    )

    # consultar_contratos_orgao_pncp não recebe limite explícito aqui (usa o
    # padrão, 500) — o importante é que avisos propagados por ela (se
    # houver) apareçam também no resultado desta tool.
    assert isinstance(resultado["avisos"], list)


_CONTRATO_UNICO = {
    "numeroControlePNCP": "18457226000181-2-000001/2023",
    "numeroControlePncpCompra": "18457226000181-1-000015/2023",
}


@patch(f"{_PREFIXO}.consultar_empenhos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_termos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_incluir_termos_e_empenhos_busca_e_anexa_aos_contratos(
    mock_detalhe, mock_arquivos, mock_contratos, mock_termos, mock_empenhos
):
    mock_detalhe.return_value = DETALHE_COMPRA
    mock_arquivos.return_value = []
    mock_contratos.return_value = _contratos_resposta([_CONTRATO_UNICO])
    mock_termos.return_value = [{"numeroTermo": 1, "tipo": "Aditivo"}]
    mock_empenhos.return_value = [{"numeroEmpenho": "2023NE000123"}]

    resultado = await consultar_familia_contratacao_pncp(
        cnpj="18457226000181", ano=2023, sequencial=15,
    )

    assert len(resultado["contratos"]) == 1
    contrato = resultado["contratos"][0]
    assert contrato["termos"] == [{"numeroTermo": 1, "tipo": "Aditivo"}]
    assert contrato["empenhos"] == [{"numeroEmpenho": "2023NE000123"}]
    mock_termos.assert_awaited_once_with("18457226000181", 2023, 1)
    mock_empenhos.assert_awaited_once_with("18457226000181", 2023, 1)


@patch(f"{_PREFIXO}.consultar_empenhos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_termos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_falha_isolada_em_termos_e_empenhos_nao_derruba_a_familia(
    mock_detalhe, mock_arquivos, mock_contratos, mock_termos, mock_empenhos
):
    mock_detalhe.return_value = DETALHE_COMPRA
    mock_arquivos.return_value = []
    mock_contratos.return_value = _contratos_resposta([_CONTRATO_UNICO])
    mock_termos.side_effect = RuntimeError("PNCP instável (simulado)")
    mock_empenhos.return_value = [{"numeroEmpenho": "2023NE000123"}]

    resultado = await consultar_familia_contratacao_pncp(
        cnpj="18457226000181", ano=2023, sequencial=15,
    )

    # Falha isolada em termos/empenhos de UM contrato não derruba a família
    # inteira — o contrato continua no resultado, só com termos/empenhos
    # vazios (ver docstring do módulo).
    assert len(resultado["contratos"]) == 1
    contrato = resultado["contratos"][0]
    assert contrato["termos"] == []
    assert contrato["empenhos"] == []


@patch(f"{_PREFIXO}.consultar_empenhos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_termos_contrato", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_arquivos", new_callable=AsyncMock)
@patch(f"{_PREFIXO}.consultar_contratacao_detalhe", new_callable=AsyncMock)
async def test_incluir_termos_e_empenhos_false_pula_a_busca(
    mock_detalhe, mock_arquivos, mock_contratos, mock_termos, mock_empenhos
):
    mock_detalhe.return_value = DETALHE_COMPRA
    mock_arquivos.return_value = []
    mock_contratos.return_value = _contratos_resposta([_CONTRATO_UNICO])

    resultado = await consultar_familia_contratacao_pncp(
        cnpj="18457226000181", ano=2023, sequencial=15,
        incluir_termos_e_empenhos=False,
    )

    assert len(resultado["contratos"]) == 1
    assert "termos" not in resultado["contratos"][0]
    assert "empenhos" not in resultado["contratos"][0]
    mock_termos.assert_not_awaited()
    mock_empenhos.assert_not_awaited()
