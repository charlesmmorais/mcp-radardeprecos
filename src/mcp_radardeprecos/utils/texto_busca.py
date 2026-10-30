"""Normalização e classificação de texto para busca tolerante a maiúsculas/acentos.

Motivação: nenhuma API usada neste projeto (PNCP ou Compras.gov.br) oferece
busca textual por substring sobre nomes/descrições de catálogo — confirmado
ao vivo para o parâmetro ``descricaoItem`` de
``/modulo-material/4_consultarItemMaterial`` (exige igualdade exata com o
campo completo, não um "contém") e pela ausência de qualquer parâmetro de
texto em ``consultarItemServico`` (ver docstring de
``tools/descobrir_codigo_catalogo.py``). Por isso a busca por palavra-chave
precisa ser feita no lado do cliente, comparando o termo do usuário (que
pode vir em minúsculas, sem acento, etc.) contra os nomes reais do catálogo
(em maiúsculas, com acento) — daí a necessidade de normalizar os dois lados
antes de comparar.
"""
from __future__ import annotations

import re
import unicodedata


def normalizar_para_busca(texto: str) -> str:
    """Maiúsculas e sem acentos/diacríticos, para comparação "contém" tolerante.

    Ex.: ``normalizar_para_busca("notebook")`` e
    ``normalizar_para_busca("NOTEBOOK")`` e
    ``normalizar_para_busca("Notébook")`` devolvem todos ``"NOTEBOOK"``.
    """
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.upper().strip()


# Níveis de qualidade de correspondência — do melhor para o pior.
# Motivado por achado real de uso: buscar "TIC" retornava "GUIA TURISTICO",
# "DADOS ESTATISTICOS" e "PRODUTOS PLASTICOS" (a substring casa DENTRO de
# outras palavras). Ver classificar_correspondencia.
QUALIDADE_EXATA = "exata"
QUALIDADE_PALAVRA_INTEIRA = "palavra_inteira"
QUALIDADE_PARCIAL = "parcial"

_ORDEM_QUALIDADE = {QUALIDADE_EXATA: 0, QUALIDADE_PALAVRA_INTEIRA: 1, QUALIDADE_PARCIAL: 2}


def ordem_qualidade(qualidade: str) -> int:
    """Ordem de prioridade de um nível (0 = melhor), para ordenação."""
    return _ORDEM_QUALIDADE.get(qualidade, 99)


def classificar_correspondencia(termo_norm: str, nome_norm: str) -> str | None:
    """Classifica a qualidade da correspondência de ``termo_norm`` em ``nome_norm``.

    Ambos já normalizados por :func:`normalizar_para_busca`. Retorna:

    - ``"exata"``: o nome É o termo;
    - ``"palavra_inteira"``: toda palavra do termo aparece como palavra
      inteira no nome (``TIC`` casa em "... COMUNICACAO (TIC)", não em
      "PLASTICO");
    - ``"parcial"``: toda palavra do termo aparece, mas ao menos uma só
      como pedaço de outra palavra (``TIC`` dentro de "TURISTICO");
    - ``None``: alguma palavra do termo não aparece no nome.
    """
    if not termo_norm or not nome_norm:
        return None
    if termo_norm == nome_norm:
        return QUALIDADE_EXATA
    palavras = termo_norm.split()
    if not palavras or any(p not in nome_norm for p in palavras):
        return None
    inteiras = all(
        re.search(rf"(?<![A-Z0-9]){re.escape(p)}(?![A-Z0-9])", nome_norm)
        for p in palavras
    )
    return QUALIDADE_PALAVRA_INTEIRA if inteiras else QUALIDADE_PARCIAL
