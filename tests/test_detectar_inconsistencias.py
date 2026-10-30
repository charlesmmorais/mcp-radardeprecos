"""Testes da tool detectar_inconsistencias (pura)."""
from __future__ import annotations

from mcp_radardeprecos.tools.detectar_inconsistencias import detectar_inconsistencias


def _tipos(resultado, registro_idx=0):
    return {i["tipo"] for i in resultado["alertas"][registro_idx]["inconsistencias"]}


async def test_sem_registros_nao_quebra():
    r = await detectar_inconsistencias([])
    assert r["total"] == 0
    assert r["alertas"] == []


async def test_valor_ausente():
    r = await detectar_inconsistencias([{"descricao": "x", "valor_unitario": 0}])
    assert r["com_inconsistencia"] == 1
    assert "valor_ausente" in _tipos(r)


async def test_quantidade_suspeita_unitaria_com_total_maior():
    r = await detectar_inconsistencias(
        [{"quantidade": 1, "valor_unitario": 100, "valor_total": 40000}]
    )
    assert "quantidade_suspeita" in _tipos(r)


async def test_homologado_acima_do_estimado():
    r = await detectar_inconsistencias(
        [{"valor_unitario": 10, "valor_homologado": 5000, "valor_estimado": 3000}]
    )
    tipos = _tipos(r)
    assert "homologado_acima_estimado" in tipos
    # gravidade alta neste caso
    alta = [i for i in r["alertas"][0]["inconsistencias"]
            if i["tipo"] == "homologado_acima_estimado"][0]
    assert alta["gravidade"] == "alta"


async def test_quantidade_divergente():
    r = await detectar_inconsistencias(
        [{"valor_unitario": 10, "quantidade": 100, "quantidade_estimada": 400}]
    )
    assert "quantidade_divergente" in _tipos(r)


async def test_preco_aparenta_global_outlier_alto():
    # 4 registros: um muito acima da mediana (> 20×).
    regs = [{"valor_unitario": v} for v in (100, 110, 120, 5000)]
    r = await detectar_inconsistencias(regs)
    # o de 5000 deve ter o alerta
    outlier = next(a for a in r["alertas"] if a.get("valor_unitario") == 5000)
    assert any(i["tipo"] == "preco_aparenta_global" for i in outlier["inconsistencias"])


async def test_preco_muito_abaixo_outlier_baixo():
    regs = [{"valor_unitario": v} for v in (1000, 1100, 1200, 1)]
    r = await detectar_inconsistencias(regs)
    baixo = next(a for a in r["alertas"] if a.get("valor_unitario") == 1)
    assert any(i["tipo"] == "preco_muito_abaixo" for i in baixo["inconsistencias"])


async def test_objeto_composto_licenca_mais_agregado():
    r = await detectar_inconsistencias(
        [{"valor_unitario": 10, "descricao": "Licença Microsoft 365 com implantação e suporte"}]
    )
    assert "objeto_composto" in _tipos(r)


async def test_descricoes_divergentes():
    r = await detectar_inconsistencias(
        [{"valor_unitario": 10,
          "objeto": "aquisição de licenças de software de escritório",
          "descricao_item": "cadeira giratória ergonômica presidente"}]
    )
    assert "descricoes_divergentes" in _tipos(r)


async def test_registro_limpo_nao_gera_alerta():
    regs = [{"valor_unitario": v, "descricao": "notebook corporativo i7 16gb ssd"}
            for v in (100, 105, 110)]
    r = await detectar_inconsistencias(regs)
    assert r["com_inconsistencia"] == 0
    assert r["alertas"] == []


async def test_outlier_nao_avaliado_com_menos_de_3_precos():
    r = await detectar_inconsistencias([{"valor_unitario": 100}, {"valor_unitario": 999999}])
    # sem mediana (n<3) → nenhum alerta de outlier
    tipos_todos = {i["tipo"] for a in r["alertas"] for i in a["inconsistencias"]}
    assert "preco_aparenta_global" not in tipos_todos
    assert any("menos de 3" in a.lower() for a in r["avisos"])


async def test_alertas_sao_informativos_nunca_excluem():
    r = await detectar_inconsistencias([{"valor_unitario": 0}])
    assert any("nenhum registro foi excluído" in a.lower() for a in r["avisos"])


async def test_mapeamento_de_campos():
    r = await detectar_inconsistencias(
        [{"preco": 0}], campos={"valor_unitario": "preco"}
    )
    assert "valor_ausente" in _tipos(r)
