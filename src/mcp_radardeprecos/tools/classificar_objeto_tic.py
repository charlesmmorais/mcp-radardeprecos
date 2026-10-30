"""Tool MCP: classifica heuristicamente se um objeto de contratação é de TIC e, se for, se parece SaaS.

**Por que heurístico, e não um campo estruturado do PNCP.** O PNCP tem um
campo de categoria estruturado equivalente só para itens de PCA
(``categoria_item_pca``, código 5 = "Soluções de TIC" — ver tool
``consultar_pca``), mas **nenhuma** das tools de busca de editais/
contratações já implementadas aqui (``buscar_pncp_texto``,
``buscar_contratacoes_pncp``, ``buscar_contratos_compras``) extrai um campo
de categoria confiável equivalente — e não existe, em nenhuma API do PNCP,
um campo estruturado para "SaaS" (é um conceito de modelo de licenciamento,
não uma categoria oficial do portal). Por isso esta tool usa correspondência
de palavras-chave (substring, case-insensitive, sem NLP/embeddings) contra
o texto do objeto/descrição — um **teto de precisão conhecido e aceito**:
vai perder contratações de TIC descritas com terminologia fora da lista
(falso negativo) e pode acertar por acaso em objetos que mencionam um termo
da lista fora de contexto de TIC (falso positivo, mais raro na prática).
**Nunca deve ser tratada como classificação definitiva** — sempre inclui um
aviso fixo lembrando disso, e o resultado deve ser conferido por quem conduz
a pesquisa antes de decisões baseadas nele (ex.: qual método de saneamento
usar, se aplicar a estrutura de relatório de TIC).

Esta tool é **pura**: não consulta nenhuma API, apenas casa palavras-chave
(``domain.dominios.PALAVRAS_TIC``/``PALAVRAS_SAAS``) contra um texto já
fornecido pelo chamador (ex.: o campo ``objeto``/``description`` de
``buscar_pncp_texto``, ``buscar_contratacoes_pncp`` ou
``consultar_contratacao_pncp``).
"""
from __future__ import annotations

import unicodedata
from typing import Any

from ..domain.dominios import PALAVRAS_SAAS, PALAVRAS_TIC
from ..logging_utils import get_logger

logger = get_logger(__name__)

_AVISO_TETO_PRECISAO = (
    "Classificação HEURÍSTICA por palavra-chave (não é um campo estruturado "
    "do PNCP) — tem um teto de precisão conhecido: pode não reconhecer "
    "contratações de TIC descritas com terminologia fora da lista de "
    "palavras-chave (falso negativo), e pode eventualmente casar um termo "
    "fora de contexto (falso positivo). Nunca trate como classificação "
    "definitiva — confirme manualmente antes de decisões baseadas nela."
)


def _normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparação tolerante a variação de
    grafia (ex.: "tecnologia da informação" casa com ou sem acento)."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acento.lower()


def _termos_encontrados(texto_normalizado: str, palavras: tuple[str, ...]) -> list[str]:
    encontrados = []
    for palavra in palavras:
        if _normalizar(palavra) in texto_normalizado:
            encontrados.append(palavra)
    return encontrados


async def classificar_objeto_tic(texto: str) -> dict[str, Any]:
    """Classifica heuristicamente (por palavra-chave) se um objeto de contratação é de TIC e, se for, se parece SaaS.

    Casa o texto informado contra duas listas de palavras-chave
    (``domain.dominios.PALAVRAS_TIC`` e ``PALAVRAS_SAAS`` — SaaS é tratado
    como um subconjunto temático de TIC, não uma categoria independente),
    de forma tolerante a maiúsculas/minúsculas e acentuação. Ver docstring
    do módulo para por que isso é heurístico (não um campo estruturado do
    PNCP) e o teto de precisão conhecido que isso implica — **sempre**
    verifique o resultado antes de decisões automatizadas.

    **Correção v0.2.6 — bug confirmado ao
    vivo em 2026-07-12**: com o objeto "Contratação de licenças Microsoft
    365 em modelo SaaS, com suporte técnico e serviços de implantação", a
    versão anterior devolvia ``e_tic=False, e_saas=True`` — logicamente
    inconsistente, já que o próprio docstring desta tool sempre afirmou que
    SaaS é subconjunto de TIC, mas o código não garantia isso (``e_tic``
    dependia só de ``PALAVRAS_TIC``, casadas independentemente de
    ``PALAVRAS_SAAS``). Agora ``e_tic`` é ``True`` sempre que ``e_saas`` for
    ``True``, mesmo sem nenhum termo de ``PALAVRAS_TIC`` casando — ver
    campo novo ``origem_tic`` para saber qual dos dois motivos classificou
    o objeto como TIC.

    Esta tool é **pura** — não acessa nenhuma API. Alimente-a com o campo
    ``objeto``/``description`` já obtido de qualquer tool de busca deste
    servidor (ex.: ``buscar_pncp_texto``, ``buscar_contratacoes_pncp``,
    ``consultar_contratacao_pncp``).

    Args:
        texto: Objeto/descrição da contratação, item ou processo (texto
            livre). Obrigatório e não pode ser vazio.

    Returns:
        Dicionário com:
        - ``e_tic``: ``True`` se ao menos uma palavra-chave de
          ``PALAVRAS_TIC`` foi encontrada no texto, OU se ``e_saas`` for
          ``True`` (SaaS é sempre TIC, mesmo quando nenhum termo de
          ``PALAVRAS_TIC`` casa isoladamente).
        - ``e_saas``: ``True`` se ao menos uma palavra-chave de
          ``PALAVRAS_SAAS`` foi encontrada.
        - ``origem_tic``: por que ``e_tic`` é ``True`` —
          ``"palavra_tic"`` (achou termo de ``PALAVRAS_TIC`` diretamente),
          ``"derivada_de_saas"`` (só achou termo de ``PALAVRAS_SAAS``, TIC
          inferido) ou ``None`` (``e_tic`` é ``False``) — para auditoria de
          qual regra classificou o objeto.
        - ``termos_tic_encontrados`` / ``termos_saas_encontrados``: as
          palavras-chave específicas que casaram (para auditoria — permite
          conferir manualmente se o casamento faz sentido no contexto).
        - ``avisos``: sempre inclui o aviso de teto de precisão conhecido
          desta classificação heurística.
    """
    if not texto or not texto.strip():
        raise ValueError("texto não pode ser vazio")

    texto_normalizado = _normalizar(texto)

    termos_tic = _termos_encontrados(texto_normalizado, PALAVRAS_TIC)
    termos_saas = _termos_encontrados(texto_normalizado, PALAVRAS_SAAS)

    e_saas = bool(termos_saas)
    e_tic = bool(termos_tic) or e_saas
    if termos_tic:
        origem_tic = "palavra_tic"
    elif e_saas:
        origem_tic = "derivada_de_saas"
    else:
        origem_tic = None

    logger.info(
        "classificar_objeto_tic e_tic=%s e_saas=%s origem_tic=%s qtd_termos_tic=%d qtd_termos_saas=%d",
        e_tic, e_saas, origem_tic, len(termos_tic), len(termos_saas),
    )

    return {
        "e_tic": e_tic,
        "e_saas": e_saas,
        "origem_tic": origem_tic,
        "termos_tic_encontrados": termos_tic,
        "termos_saas_encontrados": termos_saas,
        "avisos": [_AVISO_TETO_PRECISAO],
    }
