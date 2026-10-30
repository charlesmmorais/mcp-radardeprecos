"""Testes do CNPJ alfanumérico (``utils/documentos.py``).

O defeito que estes testes travam: até a v0.5.0 o projeto assumia, em cinco
pontos, que CNPJ é numérico. O pior deles era a limpeza do cliente do BPS, que
**removia as letras em silêncio** e consultava um número mutilado — resposta
normal, dado errado, nenhum sinal.
"""
from __future__ import annotations

import pytest

from mcp_radardeprecos.utils.documentos import (
    AVISO_CNPJ_ALFANUMERICO,
    aviso_cnpj_alfanumerico,
    cnpj_alfanumerico,
    limpar_cnpj,
    limpar_cpf,
    validar_cnpj,
    validar_cpf,
)

#: Numérico clássico, com e sem máscara.
CNPJ_NUMERICO = "11222333000181"
#: Alfanumérico: 12 posições alfanuméricas + 2 dígitos verificadores.
CNPJ_ALFA = "12ABC34501DE35"


def test_limpar_cnpj_preserva_letras():
    """O coração da correção: letras entram e letras saem."""
    assert limpar_cnpj("12.ABC.345/01DE-35") == CNPJ_ALFA


def test_limpar_cnpj_normaliza_caixa():
    assert limpar_cnpj("12abc34501de35") == CNPJ_ALFA


def test_limpar_cnpj_nao_mutila_silenciosamente():
    """Regressão direta do defeito: a versão antiga devolvia 10 dígitos.

    ``12ABC34501DE35`` virava ``1234501 35`` — um número plausível, de outra
    empresa ou de nenhuma, sem qualquer indicação de que a entrada mudou.
    """
    limpo = limpar_cnpj(CNPJ_ALFA)
    assert len(limpo) == 14
    assert limpo == CNPJ_ALFA


def test_limpar_cnpj_descarta_nao_ascii():
    """``str.isalnum()`` aceitaria ``ç`` e ``²``; a nossa classe não."""
    assert limpar_cnpj("11²22ç2333000181") == "11222333000181"


def test_validar_cnpj_aceita_numerico_e_alfanumerico():
    assert validar_cnpj("11.222.333/0001-81") == CNPJ_NUMERICO
    assert validar_cnpj("12.ABC.345/01DE-35") == CNPJ_ALFA


def test_validar_cnpj_recusa_letra_no_digito_verificador():
    """As duas últimas posições continuam numéricas."""
    with pytest.raises(ValueError):
        validar_cnpj("12ABC34501DEAB")


def test_validar_cnpj_recusa_tamanho_errado():
    with pytest.raises(ValueError) as exc:
        validar_cnpj("123")
    # A mensagem tem de dizer o que veio, não só o que se esperava.
    assert "3 posições" in str(exc.value)


def test_validar_cnpj_usa_o_nome_do_campo_na_mensagem():
    with pytest.raises(ValueError) as exc:
        validar_cnpj("123", campo="cnpj_orgao")
    assert "cnpj_orgao" in str(exc.value)


def test_validar_cnpj_nao_confere_digito_verificador():
    """Decisão deliberada, documentada no módulo.

    Um CNPJ com DV aritmeticamente errado passa. Introduzir a checagem junto
    com a ampliação do formato misturaria duas mudanças de comportamento: um
    erro na implementação do DV apareceria como "CNPJ inválido" para dado
    correto.
    """
    assert validar_cnpj("11222333000100") == "11222333000100"


def test_cnpj_alfanumerico_distingue_os_dois_formatos():
    assert cnpj_alfanumerico(CNPJ_ALFA) is True
    assert cnpj_alfanumerico(CNPJ_NUMERICO) is False


def test_aviso_so_aparece_no_formato_novo():
    assert aviso_cnpj_alfanumerico(CNPJ_ALFA) == AVISO_CNPJ_ALFANUMERICO
    assert aviso_cnpj_alfanumerico(CNPJ_NUMERICO) is None


def test_aviso_diz_que_vazio_pode_ser_recusa_da_fonte():
    """O aviso existe para separar 'não há dado' de 'a fonte recusou'."""
    assert "NÃO FOI VERIFICADO" in AVISO_CNPJ_ALFANUMERICO
    assert "ausência" in AVISO_CNPJ_ALFANUMERICO


def test_cpf_continua_numerico():
    assert limpar_cpf("123.456.789-09") == "12345678909"
    assert validar_cpf("123.456.789-09") == "12345678909"
    with pytest.raises(ValueError):
        validar_cpf("12A45678909")
