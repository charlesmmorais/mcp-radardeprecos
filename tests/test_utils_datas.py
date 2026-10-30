"""Testes do utilitário compartilhado de janela de datas (utils/datas.py).

Extraído de duas tools que tinham a mesma função duplicada — estes testes
cobrem os casos de borda que já eram implicitamente exercitados nos testes
de agregação das tools, agora isolados na unidade correta.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp_radardeprecos.utils.datas import (
    dentro_da_janela,
    janela_dias_a_frente,
    janela_dias_a_frente_iso,
    janela_dias_atras,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_dentro_da_janela_aceita_data_recente():
    recente = datetime.now(timezone.utc) - timedelta(days=10)
    assert dentro_da_janela(_iso(recente), janelas_meses=12) is True


def test_dentro_da_janela_rejeita_data_fora_da_janela():
    antiga = datetime.now(timezone.utc) - timedelta(days=400)
    assert dentro_da_janela(_iso(antiga), janelas_meses=12) is False


def test_dentro_da_janela_aceita_sufixo_z():
    recente = datetime.now(timezone.utc) - timedelta(days=1)
    data_com_z = recente.isoformat().replace("+00:00", "Z")
    assert dentro_da_janela(data_com_z, janelas_meses=1) is True


def test_dentro_da_janela_trata_data_naive_como_utc():
    recente_naive = (datetime.now(timezone.utc) - timedelta(days=5)).replace(tzinfo=None)
    assert dentro_da_janela(recente_naive.isoformat(), janelas_meses=1) is True


def test_dentro_da_janela_retorna_falso_para_none():
    assert dentro_da_janela(None, janelas_meses=12) is False


def test_dentro_da_janela_retorna_falso_para_string_vazia():
    assert dentro_da_janela("", janelas_meses=12) is False


def test_dentro_da_janela_retorna_falso_para_formato_invalido():
    assert dentro_da_janela("data-invalida", janelas_meses=12) is False


def test_janela_dias_atras_formato_aaaammdd():
    inicio, fim = janela_dias_atras(30)
    assert len(inicio) == 8 and inicio.isdigit()
    assert len(fim) == 8 and fim.isdigit()


def test_janela_dias_atras_inicio_antes_do_fim():
    inicio, fim = janela_dias_atras(30)
    assert inicio < fim


def test_janela_dias_atras_fim_e_hoje():
    _, fim = janela_dias_atras(30)
    assert fim == datetime.now(timezone.utc).strftime("%Y%m%d")


def test_janela_dias_a_frente_formato_aaaammdd():
    inicio, fim = janela_dias_a_frente(30)
    assert len(inicio) == 8 and inicio.isdigit()
    assert len(fim) == 8 and fim.isdigit()


def test_janela_dias_a_frente_inicio_e_hoje_e_fim_no_futuro():
    inicio, fim = janela_dias_a_frente(30)
    assert inicio == datetime.now(timezone.utc).strftime("%Y%m%d")
    assert fim > inicio


def test_janela_dias_a_frente_e_o_inverso_de_janela_dias_atras():
    # janela_dias_atras olha para trás (fim=hoje); janela_dias_a_frente olha
    # para a frente (início=hoje) — ver docstring de ambas.
    inicio_atras, fim_atras = janela_dias_atras(30)
    inicio_frente, fim_frente = janela_dias_a_frente(30)
    assert fim_atras == inicio_frente == datetime.now(timezone.utc).strftime("%Y%m%d")
    assert inicio_atras < fim_atras
    assert inicio_frente < fim_frente


def test_janela_dias_a_frente_iso_formato_com_hifens():
    inicio, fim = janela_dias_a_frente_iso(30)
    assert inicio.count("-") == 2 and fim.count("-") == 2
    assert inicio == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert fim > inicio


def test_janela_dias_a_frente_iso_cobre_o_numero_de_dias_pedido():
    inicio, fim = janela_dias_a_frente_iso(10)
    diferenca = datetime.strptime(fim, "%Y-%m-%d") - datetime.strptime(inicio, "%Y-%m-%d")
    assert diferenca == timedelta(days=10)
