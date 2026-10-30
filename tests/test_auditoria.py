"""Testes da trilha de auditoria."""
from __future__ import annotations

import httpx
import pytest
import respx

from mcp_radardeprecos import auditoria
from mcp_radardeprecos.clients import base
from mcp_radardeprecos.tools.exportar_trilha_auditoria import (
    exportar_trilha_auditoria,
)

_URL = "https://exemplo-auditoria.test"


@pytest.fixture(autouse=True)
def _limpa():
    auditoria.resetar()
    yield
    auditoria.resetar()


def test_registrar_e_obter_trilha():
    auditoria.registrar_upstream(
        source="teste", url=f"{_URL}/x", params={"a": 1}, status=200, corpo=b"conteudo"
    )
    trilha = auditoria.obter_trilha()
    assert len(trilha) == 1
    r = trilha[0]
    assert r["fonte"] == "teste"
    assert r["status"] == 200
    assert r["params"] == {"a": 1}
    assert r["resposta_bytes"] == len(b"conteudo")
    # hash é o SHA-256 do corpo bruto
    import hashlib
    assert r["resposta_hash_sha256"] == hashlib.sha256(b"conteudo").hexdigest()
    assert r["timestamp_utc"].endswith("+00:00")  # UTC


def test_params_none_sao_omitidos():
    auditoria.registrar_upstream(
        source="t", url="u", params={"a": 1, "b": None}, status=200, corpo=b""
    )
    assert auditoria.obter_trilha()[0]["params"] == {"a": 1}


def test_hash_reprodutibilidade_estavel_e_sensivel():
    auditoria.registrar_upstream(source="t", url="u", params={}, status=200, corpo=b"a")
    h1 = auditoria.hash_reprodutibilidade(auditoria.obter_trilha())
    # mesmo conjunto -> mesmo hash
    assert h1 == auditoria.hash_reprodutibilidade(auditoria.obter_trilha())
    # um acesso a mais com resposta diferente -> hash muda
    auditoria.registrar_upstream(source="t", url="u", params={}, status=200, corpo=b"b")
    assert auditoria.hash_reprodutibilidade(auditoria.obter_trilha()) != h1


def test_filtro_por_limite_e_desde():
    for i in range(5):
        auditoria.registrar_upstream(source=f"f{i}", url="u", params={}, status=200, corpo=b"x")
    assert len(auditoria.obter_trilha(limite=2)) == 2
    todos = auditoria.obter_trilha()
    ts_meio = todos[2]["timestamp_utc"]
    recortada = auditoria.obter_trilha(desde_iso=ts_meio)
    assert all(r["timestamp_utc"] >= ts_meio for r in recortada)


def test_contextvar_marca_a_tool_atual():
    token = auditoria.definir_tool_atual("minha_tool")
    try:
        auditoria.registrar_upstream(source="t", url="u", params={}, status=200, corpo=b"x")
    finally:
        auditoria.limpar_tool_atual(token)
    assert auditoria.obter_trilha()[0]["tool"] == "minha_tool"
    # fora do contexto, volta a None
    auditoria.registrar_upstream(source="t", url="u", params={}, status=200, corpo=b"x")
    assert auditoria.obter_trilha()[-1]["tool"] is None


@respx.mock
async def test_get_json_alimenta_a_trilha():
    respx.get(f"{_URL}/rec").mock(return_value=httpx.Response(200, json={"ok": True}))
    await base.get_json(_URL, "/rec", {"q": "z"}, source="fonte-x")
    trilha = auditoria.obter_trilha()
    assert len(trilha) == 1
    assert trilha[0]["fonte"] == "fonte-x"
    assert trilha[0]["url"] == f"{_URL}/rec"
    assert trilha[0]["status"] == 200
    assert trilha[0]["resposta_hash_sha256"]  # hash presente


async def test_tool_exporta_dossie():
    auditoria.registrar_upstream(
        source="PNCP", url="https://pncp/x", params={"pagina": 1}, status=200, corpo=b"{}"
    )
    dossie = await exportar_trilha_auditoria(
        objeto="notebook", responsavel="Fulano", decisoes={"metodo": "media_saneada"}
    )
    assert dossie["objeto"] == "notebook"
    assert dossie["responsavel"] == "Fulano"
    assert dossie["resumo"]["total_acessos"] == 1
    assert dossie["resumo"]["fontes_consultadas"] == ["PNCP"]
    assert dossie["hash_reprodutibilidade"]
    assert len(dossie["proveniencia"]) == 1
    assert "aviso" in dossie


async def test_tool_salva_arquivo(tmp_path):
    auditoria.registrar_upstream(source="t", url="u", params={}, status=200, corpo=b"x")
    destino = tmp_path / "dossie.json"
    dossie = await exportar_trilha_auditoria(caminho_saida=str(destino))
    assert destino.exists()
    assert dossie["caminho_saida"] == str(destino)
    import json
    salvo = json.loads(destino.read_text(encoding="utf-8"))
    assert salvo["resumo"]["total_acessos"] == 1
