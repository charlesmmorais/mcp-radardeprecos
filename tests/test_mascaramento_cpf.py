"""Mascaramento de CPF nas saídas das tools.

O campo de documento do fornecedor é o MESMO para pessoa jurídica e física
nas três fontes que este servidor consulta — ``niFornecedor`` no PNCP e no
Compras.gov.br, ``ni`` na NF-e. A origem não separa; quem separa somos nós,
pelo comprimento.

Medido em 09/09/2026 no CATMAT 267203: 1.000 documentos de fornecedor, todos
de 14 dígitos. Ou seja, CPF de fornecedor é evento **raro** em material. Este
módulo é controle contra evento raro, não resposta a incêndio — e a razão de
existir é que o payload vai para um modelo de linguagem, onde um CPF que
aparece uma vez em mil já é uma vez a mais do que o necessário.
"""
from __future__ import annotations

import ast
import pathlib

from mcp_radardeprecos.config import settings
from mcp_radardeprecos.utils.documentos import mascarar_documento


def test_cpf_e_mascarado_preservando_o_suficiente_para_conferencia():
    """Primeiros 3 e últimos 2 — o bastante para bater com um documento em
    mãos, insuficiente para reconstruir."""
    assert mascarar_documento("12345678901") == "123.***.***-01"


def test_cpf_com_mascara_de_entrada_tambem_e_tratado():
    assert mascarar_documento("123.456.789-01") == "123.***.***-01"


def test_cnpj_nao_e_mascarado():
    """CNPJ identifica pessoa jurídica: é público por natureza, e mascará-lo
    quebraria o cruzamento com sanções, situação cadastral e contratos — que é
    metade do valor deste servidor."""
    assert mascarar_documento("05607657000801") == "05607657000801"


def test_cnpj_alfanumerico_passa_intacto():
    """Formato vigente desde julho/2026 — 12 posições alfanuméricas + 2 DV."""
    assert mascarar_documento("12ABC34501DE35") == "12ABC34501DE35"


def test_ausencia_continua_ausencia():
    assert mascarar_documento(None) is None
    assert mascarar_documento("") is None


def test_documento_de_tamanho_desconhecido_e_mascarado_por_precaucao():
    """Não sabemos o que é; na dúvida entre expor e ocultar, oculta.

    Um identificador de 9 ou 12 dígitos não é CNPJ nem CPF conhecido — pode
    ser dado sujo da origem, e pode ser documento de pessoa física de outro
    formato. Deixar passar seria decidir pelo lado que não dá para desfazer.
    """
    assert mascarar_documento("123456789") == "***"


def test_opt_in_devolve_o_documento_inteiro():
    """A saída existe porque há uso legítimo: conferir um fornecedor PF
    específico num processo. É explícita e fica no ambiente, não na chamada —
    para que apareça na configuração do servidor, e não escondida num
    parâmetro que alguém passa sem registrar."""
    original = settings.incluir_cpf_completo
    try:
        object.__setattr__(settings, "incluir_cpf_completo", True)
        assert mascarar_documento("12345678901") == "12345678901"
    finally:
        object.__setattr__(settings, "incluir_cpf_completo", original)


# ===========================================================================
# Detector: nenhum ponto de saída pode nascer sem máscara
# ===========================================================================
#
# Aplicar a função nos 12 pontos de hoje resolve hoje. O que impede a tool
# nº 54 de sair com o documento cru é este teste, que varre a árvore inteira
# em vez de confiar numa lista mantida à mão.
#
# O detector foi escrito errado na primeira tentativa: procurava `"ni"` por
# SUBSTRING e casou dentro de "u**ni**dade" e "mu**ni**cipio", devolvendo 131
# achados dos quais ~110 eram falsos. Casamento exato da chave do `.get()`
# reduziu para 20 reais. Fica registrado porque um detector que grita demais
# é abandonado, e um que grita de menos não protege.

#: Campos das origens que carregam documento de fornecedor. `niFornecedor` e
#: `ni` são o MESMO campo para PJ e PF — é essa ambiguidade da fonte que torna
#: o mascaramento necessário.
_CAMPOS_DE_DOCUMENTO = {
    "niFornecedor",
    "ni",
    "CnpjCpf",
    "cpfCnpj",
    "cnpjFornecedor",
    "cnpjFabricante",
    "cnpjInstituicao",
    "cpf",
}

_RAIZ = pathlib.Path(__file__).resolve().parents[1] / "src" / "mcp_radardeprecos" / "tools"


def _chave_do_get(no: ast.AST) -> str | None:
    """Nome da chave em ``x.get("chave")`` — casamento EXATO, não substring."""
    if (
        isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr == "get"
        and no.args
        and isinstance(no.args[0], ast.Constant)
        and isinstance(no.args[0].value, str)
    ):
        return no.args[0].value
    return None


def _pontos_sem_mascara() -> list[str]:
    fora = []
    for arquivo in sorted(_RAIZ.rglob("*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Dict):
                continue
            for chave, valor in zip(no.keys, no.values, strict=False):
                if not isinstance(chave, ast.Constant):
                    continue
                usados = {_chave_do_get(x) for x in ast.walk(valor)} - {None}
                if not (usados & _CAMPOS_DE_DOCUMENTO):
                    continue
                # Só o nó FOLHA importa: o dicionário-pai que contém o campo
                # aparece na varredura, mas quem precisa da máscara é a
                # atribuição direta.
                if any(isinstance(v, ast.Dict) for v in ast.walk(valor)):
                    continue
                if "mascarar_documento" not in ast.unparse(valor):
                    fora.append(f"{arquivo.name}:{valor.lineno} \"{chave.value}\"")
    return fora


def test_nenhum_documento_de_fornecedor_sai_sem_mascara():
    fora = _pontos_sem_mascara()
    assert not fora, (
        "documento de fornecedor saindo cru em:\n  " + "\n  ".join(fora)
        + "\nEnvolva com mascarar_documento(): o campo é o mesmo para PJ e PF."
    )


def test_o_detector_acusa_quando_o_defeito_e_reintroduzido():
    """Controle. Sem ele, um detector quebrado passaria por 'está tudo limpo'.

    É o mesmo cuidado do controle que a auditoria de 204 exigiu: um detector
    que nunca dispara é indistinguível de um código sem defeito.
    """
    codigo = 'x = {"cnpj": registro.get("niFornecedor")}'
    no = next(n for n in ast.walk(ast.parse(codigo)) if isinstance(n, ast.Dict))
    usados = {_chave_do_get(x) for x in ast.walk(no.values[0])} - {None}
    assert usados & _CAMPOS_DE_DOCUMENTO
    assert "mascarar_documento" not in ast.unparse(no.values[0])


def test_o_detector_nao_confunde_unidade_e_municipio_com_ni():
    """A primeira versão casava `ni` por substring e acusava 131 pontos."""
    for codigo in ('x = {"municipio": r.get("municipio")}',
                   'x = {"unidade": r.get("unidadeMedida")}',
                   'x = {"data": r.get("data_inicio")}'):
        no = next(n for n in ast.walk(ast.parse(codigo)) if isinstance(n, ast.Dict))
        usados = {_chave_do_get(x) for x in ast.walk(no.values[0])} - {None}
        assert not (usados & _CAMPOS_DE_DOCUMENTO), codigo
