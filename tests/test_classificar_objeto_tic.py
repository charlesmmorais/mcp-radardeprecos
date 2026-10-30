"""Testes de `classificar_objeto_tic` (tool pura, sem chamada de rede)."""
from __future__ import annotations

import pytest

from mcp_radardeprecos.tools.classificar_objeto_tic import classificar_objeto_tic


async def test_rejeita_texto_vazio():
    with pytest.raises(ValueError, match="vazio"):
        await classificar_objeto_tic("")
    with pytest.raises(ValueError, match="vazio"):
        await classificar_objeto_tic("   ")


async def test_reconhece_objeto_de_tic():
    resultado = await classificar_objeto_tic(
        "Contratação de licenciamento de software de gestão empresarial"
    )
    assert resultado["e_tic"] is True
    assert "licenciamento de software" in resultado["termos_tic_encontrados"]


async def test_reconhece_objeto_de_saas():
    resultado = await classificar_objeto_tic(
        "Contratação de solução SaaS de gestão de processos, modelo de assinatura em nuvem"
    )
    assert resultado["e_tic"] is True
    assert resultado["e_saas"] is True
    assert "saas" in resultado["termos_saas_encontrados"]


async def test_nao_reconhece_objeto_sem_relacao_com_tic():
    resultado = await classificar_objeto_tic(
        "Aquisição de gêneros alimentícios para merenda escolar"
    )
    assert resultado["e_tic"] is False
    assert resultado["e_saas"] is False
    assert resultado["termos_tic_encontrados"] == []
    assert resultado["termos_saas_encontrados"] == []


async def test_tic_sem_saas_nao_marca_e_saas():
    resultado = await classificar_objeto_tic(
        "Aquisição de notebooks e impressoras para o setor administrativo"
    )
    assert resultado["e_tic"] is True
    assert resultado["e_saas"] is False
    assert resultado["termos_saas_encontrados"] == []


async def test_tolerante_a_maiusculas_e_acentuacao():
    resultado = await classificar_objeto_tic(
        "CONTRATAÇÃO DE SOLUÇÃO TECNOLÓGICA PARA SEGURANÇA DA INFORMAÇÃO"
    )
    assert resultado["e_tic"] is True
    assert "solução tecnológica" in resultado["termos_tic_encontrados"]
    assert "segurança da informação" in resultado["termos_tic_encontrados"]


async def test_aviso_de_teto_de_precisao_sempre_presente():
    resultado_tic = await classificar_objeto_tic("Licenciamento de software")
    resultado_nao_tic = await classificar_objeto_tic("Aquisição de material de limpeza")
    assert any("HEURÍSTICA" in a for a in resultado_tic["avisos"])
    assert any("HEURÍSTICA" in a for a in resultado_nao_tic["avisos"])


async def test_termos_encontrados_nao_tem_duplicatas_para_termo_unico():
    resultado = await classificar_objeto_tic("Contratação de firewall para a rede corporativa")
    assert resultado["termos_tic_encontrados"].count("firewall") == 1


# v0.2.6, item 11: regressão do bug confirmado ao vivo
# em 2026-07-12 — e_tic=False + e_saas=True era logicamente inconsistente
# (SaaS é subconjunto de TIC).


async def test_frase_do_avaliador_e_tic_e_saas_via_taxonomia_nova():
    # Frase exata do bug relatado. Com a taxonomia nova ("microsoft 365"
    # em PALAVRAS_TIC), casa diretamente — origem_tic="palavra_tic".
    resultado = await classificar_objeto_tic(
        "Contratação de licenças Microsoft 365 em modelo SaaS, com suporte "
        "técnico e serviços de implantação"
    )
    assert resultado["e_tic"] is True
    assert resultado["e_saas"] is True
    assert resultado["origem_tic"] == "palavra_tic"
    assert "microsoft 365" in resultado["termos_tic_encontrados"]


async def test_saas_sem_nenhum_termo_tic_direto_deriva_e_tic():
    # Nenhuma palavra de PALAVRAS_TIC aparece aqui — só "saas" (PALAVRAS_SAAS)
    # — cobre o caminho origem_tic="derivada_de_saas" da correção do bug.
    resultado = await classificar_objeto_tic(
        "Aquisição de solução em modelo SaaS para gestão de estoque, com suporte remoto"
    )
    assert resultado["termos_tic_encontrados"] == []
    assert resultado["e_saas"] is True
    assert resultado["e_tic"] is True
    assert resultado["origem_tic"] == "derivada_de_saas"


async def test_objeto_sem_tic_nem_saas_tem_origem_tic_none():
    resultado = await classificar_objeto_tic("Aquisição de gêneros alimentícios para merenda escolar")
    assert resultado["e_tic"] is False
    assert resultado["origem_tic"] is None


async def test_licenca_ambiental_nao_e_classificada_como_tic():
    resultado = await classificar_objeto_tic(
        "Licença ambiental para obra de pavimentação de vias públicas"
    )
    assert resultado["e_tic"] is False
    assert resultado["e_saas"] is False
    assert resultado["termos_tic_encontrados"] == []


async def test_licenca_de_uso_de_imagem_nao_e_classificada_como_tic():
    # Caso negativo explícito do item 11 — motivou trocar o bigrama
    # pré-existente "licença de uso" por "licença de uso de software"
    # (o antigo colidia com esta frase).
    resultado = await classificar_objeto_tic(
        "Licença de uso de imagem de atleta para campanha publicitária"
    )
    assert resultado["e_tic"] is False
    assert resultado["termos_tic_encontrados"] == []
