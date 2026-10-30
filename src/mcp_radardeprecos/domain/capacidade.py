"""Interpretação da capacidade de uma unidade de fornecimento (texto livre).

O catálogo do Compras.gov.br informa a capacidade de cada unidade de
fornecimento como texto: ``"50 UN"``, ``"45 PACOTES"``, ``"4000 FOLHAS"``,
``"1,5 L"``, ``"CAIXA COM 100 UNIDADES"``. Esse texto é o que permite trazer
um preço "por pacote" para a base unitária — mas é texto livre, digitado por
pessoas ao longo de décadas, sem gramática garantida.

Princípio deste módulo (o mesmo de ``normalizar_precos_unidade``): **nunca
chutar**. Quando o texto não é reconhecido com segurança, o parser devolve
``None`` e quem chama trata o registro como não convertível, com o motivo
explícito. Uma conversão errada é pior que nenhuma: ela não aparece como erro,
aparece como um número com cara de rigor — precisão aparente, que é
exatamente o que a normalização deveria eliminar.

Casos deliberadamente NÃO interpretados (devolvem ``None``):

- múltiplos números sem estrutura clara (``"CAIXA 10 X 20"``) — poderia ser
  10×20=200 ou dimensões 10 cm × 20 cm; ambíguo, então não se decide;
- faixas (``"DE 50 A 100"``);
- texto sem número (``"UNIDADE"``, ``"GLOBAL"``) — não é erro, apenas não há
  fator a extrair (unidade simples, fator 1, tratado por quem chama).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: Palavras que indicam a unidade base contida na embalagem. Mapeiam para um
#: rótulo canônico, usado só para descrever a base do fator na saída.
_BASES = {
    "un": "unidade",
    "uni": "unidade",
    "und": "unidade",
    "unid": "unidade",
    "unidade": "unidade",
    "unidades": "unidade",
    "pc": "unidade",
    "peca": "unidade",
    "pecas": "unidade",
    "folha": "folha",
    "folhas": "folha",
    "pacote": "pacote",
    "pacotes": "pacote",
    "pct": "pacote",
    "caixa": "caixa",
    "caixas": "caixa",
    "ampola": "ampola",
    "ampolas": "ampola",
    "comprimido": "comprimido",
    "comprimidos": "comprimido",
    "capsula": "capsula",
    "capsulas": "capsula",
    "envelope": "envelope",
    "envelopes": "envelope",
    "rolo": "rolo",
    "rolos": "rolo",
    "metro": "metro",
    "metros": "metro",
    "m": "metro",
    "litro": "litro",
    "litros": "litro",
    "l": "litro",
    "ml": "mililitro",
    "kg": "quilograma",
    "g": "grama",
    "grama": "grama",
    "gramas": "grama",
}


@dataclass(frozen=True)
class Capacidade:
    """Capacidade interpretada: ``fator`` unidades-base por embalagem."""

    fator: Decimal
    base: str
    texto_original: str


def _sem_acento(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _para_decimal(bruto: str) -> Decimal | None:
    """Converte um número em texto, tolerando o formato brasileiro."""
    s = bruto.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return valor if valor > 0 else None


def interpretar_capacidade(texto: str | None) -> Capacidade | None:
    """Extrai o fator de conversão de uma capacidade em texto livre.

    Args:
        texto: o campo ``capacidadeUnidadeFornecimento`` do catálogo, como
            veio da API (pode ser ``None`` ou vazio).

    Returns:
        :class:`Capacidade` quando o texto tem exatamente um número seguido
        (ou precedido) de uma unidade reconhecida — ex.: ``"50 UN"`` →
        fator 50, base "unidade". ``None`` quando não há número, quando há
        mais de um número (ambíguo), quando o texto descreve uma faixa, ou
        quando a unidade não é reconhecida. Devolver ``None`` é um
        resultado legítimo, não uma falha: significa "não converta".
    """
    if not texto:
        return None
    limpo = _sem_acento(str(texto)).lower().strip()
    if not limpo:
        return None

    # Faixas e intervalos: nunca se escolhe um extremo.
    if re.search(r"\b(a|ate|entre|ou)\b.*\d", limpo) and len(
        re.findall(r"\d+(?:[.,]\d+)?", limpo)
    ) > 1:
        return None

    numeros = re.findall(r"\d+(?:[.,]\d+)?", limpo)
    if len(numeros) != 1:
        # Zero números: unidade simples, nada a converter.
        # Dois ou mais: "10 X 20" é ambíguo (produto? dimensões?).
        return None

    fator = _para_decimal(numeros[0])
    if fator is None:
        return None

    # A base é a primeira palavra reconhecida DEPOIS do número; se não houver,
    # tenta a palavra imediatamente ANTES (ex.: "FOLHAS 4000").
    posicao = limpo.find(numeros[0])
    depois = re.findall(r"[a-z]+", limpo[posicao + len(numeros[0]) :])
    antes = re.findall(r"[a-z]+", limpo[:posicao])
    for palavra in [*depois, *reversed(antes)]:
        base = _BASES.get(palavra)
        if base:
            return Capacidade(fator=fator, base=base, texto_original=str(texto))
    return None
