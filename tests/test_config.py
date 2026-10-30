"""Testes de config.py: warning (não silêncio) quando env var numérica é inválida."""
from __future__ import annotations

import logging

from mcp_radardeprecos import config


def test_get_float_valido_e_ausente(monkeypatch):
    monkeypatch.setenv("X_TIMEOUT", "12.5")
    assert config._get_float("X_TIMEOUT", 30.0) == 12.5
    monkeypatch.delenv("X_TIMEOUT", raising=False)
    assert config._get_float("X_TIMEOUT", 30.0) == 30.0


def test_get_float_invalido_usa_padrao_e_loga_warning(monkeypatch, caplog):
    # Regressão do achado da auditoria: "RADARDEPRECOS_HTTP_TIMEOUT=3O"
    # (letra O) caía no padrão sem nenhum aviso.
    monkeypatch.setenv("X_TIMEOUT", "3O")
    with caplog.at_level(logging.WARNING, logger="mcp_radardeprecos.config"):
        assert config._get_float("X_TIMEOUT", 30.0) == 30.0
    assert any("X_TIMEOUT" in r.message and "inválida" in r.message for r in caplog.records)


def test_get_int_invalido_usa_padrao_e_loga_warning(monkeypatch, caplog):
    monkeypatch.setenv("X_RETRIES", "muitas")
    with caplog.at_level(logging.WARNING, logger="mcp_radardeprecos.config"):
        assert config._get_int("X_RETRIES", 3) == 3
    assert any("X_RETRIES" in r.message for r in caplog.records)


def test_get_int_valido(monkeypatch):
    monkeypatch.setenv("X_RETRIES", "5")
    assert config._get_int("X_RETRIES", 3) == 5
