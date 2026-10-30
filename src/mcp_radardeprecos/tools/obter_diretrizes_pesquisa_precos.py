"""Tool MCP: devolve as premissas/diretrizes de uma pesquisa de preços.

Assim como ``calcular_preco_referencia``, esta tool é **pura** — não acessa
nenhuma API. Ela expõe, em formato estruturado (JSON), as premissas
metodológicas descritas em "Pesquisa de preços — um guia prático de
sobrevivência" (Franklin Brasil) — ver
o guia de boas práticas de pesquisa de preços para o texto completo com toda a
jurisprudência do TCU citada.

O objetivo é permitir que qualquer agente/cliente MCP que já use este
servidor consiga consultar as premissas de uma pesquisa de preços
corretamente conduzida (fontes prioritárias, mínimo de referências, janela
temporal, métodos de cálculo etc.) sem depender de acesso ao repositório de
código — o mesmo conteúdo também é exposto como MCP Resource
(``docs://boas-praticas-pesquisa-precos``, ver ``server.py``) para quem
preferir o texto em Markdown.
"""
from __future__ import annotations

from typing import Any

from ..domain.diretrizes_pesquisa_precos import DIRETRIZES_PESQUISA_PRECOS
from ..logging_utils import get_logger

logger = get_logger(__name__)


async def obter_diretrizes_pesquisa_precos() -> dict[str, Any]:
    """Devolve as premissas de uma pesquisa de preços conduzida corretamente.

    Consolida, em formato estruturado, a metodologia de "Pesquisa de preços
    — um guia prático de sobrevivência" (Franklin Brasil), que por sua vez
    consolida jurisprudência do TCU sobre o tema. Use esta tool **antes** de
    iniciar uma pesquisa (para saber quais fontes priorizar, o mínimo de
    referências e a janela temporal aceitável) e antes de aplicar
    ``calcular_preco_referencia`` (para saber qual método de cálculo é
    apropriado ao risco da compra).

    Esta tool é **pura** — não acessa nenhuma API, apenas devolve uma
    estrutura de dados fixa.

    Returns:
        Dicionário com:
        - ``fonte``: título, autor, data e normas do guia de referência.
        - ``conceito_central``: a ideia-chave (cesta de preços aceitáveis,
          não "3 orçamentos").
        - ``fases``: as 5 fases da pesquisa (objeto, planejamento, coleta,
          tratamento, formalização), cada uma com seus pontos-chave.
        - ``fontes_prioritarias``: lista ordenada de fontes de referência,
          da mais para a menos prioritária, com observações de uso.
        - ``regras_amostra``: mínimo de referências e regras de validade dos
          preços (só vencedores/homologados/contratados).
        - ``janela_temporal``: prazo máximo das referências coletadas,
          detalhado por fonte (``por_fonte``) — a IN SEGES/ME 65/2021 varia
          o prazo conforme a origem (6 meses para mídia/cotação direta,
          1 ano para contratações públicas similares e notas fiscais, sem
          prazo fixo para sistemas oficiais como o Painel de Preços) — mais
          a orientação geral do guia para itens estáveis.
        - ``metodos_calculo``: resumo dos 3 métodos disponíveis na tool
          ``calcular_preco_referencia`` e quando usar cada um.
        - ``curva_abc``: critério de priorização do rigor da pesquisa por
          grupo de relevância econômica do item.
        - ``checklist_formalizacao``: itens que a documentação da pesquisa
          deve conter para ser rastreável.
    """
    logger.info("obter_diretrizes_pesquisa_precos")
    return DIRETRIZES_PESQUISA_PRECOS
