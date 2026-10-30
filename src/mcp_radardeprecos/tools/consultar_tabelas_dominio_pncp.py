"""Tool MCP: consulta as tabelas de domínio oficiais do PNCP.

Assim como ``obter_diretrizes_pesquisa_precos``, esta tool é **pura** — não
acessa nenhuma API. Os valores vêm do Manual/documentação do PNCP,
hardcoded em ``domain.dominios.TABELAS_DOMINIO_PNCP``, no mesmo espírito de
``MODALIDADES_PNCP``.

Correção de uma afirmação nossa que estava errada
----------------------------------------------------------
Até a v0.5.0 este cabeçalho afirmava, sem ressalva, que *"não existe nenhum
endpoint REST de tabelas de domínio"*. A afirmação era boa para a API de
**Consulta** (``/api/consulta/v3/api-docs``), cujo spec foi de fato lido por
inteiro — e indevidamente generalizada para o PNCP como um todo.

O **Manual de Integração do PNCP, versão 2.6**, documenta endpoints REST
para praticamente todas estas tabelas: ``/v1/modalidades`` (com
``?statusAtivo=true``), ``/v1/instrumentos-convocatorios``,
``/v1/modos-disputa``, ``/v1/criterios-julgamento``, ``/v1/tipos-contrato``,
``/v1/tipos-documento``, ``/v1/amparos-legais``, ``/v1/categorias-item`` e
``/v1/portes-empresa``, cada um com variante "por código".

O que **não** foi verificado: se esses caminhos respondem sem autenticação.
O manual é de *integração*, o que torna a dúvida legítima, e o PNCP esteve
indisponível durante a apuração (04–05/09/2026). Portanto nada mudou no
comportamento desta tool — apenas deixou de haver aqui uma certeza falsa.

A existência do parâmetro ``statusAtivo`` nesses endpoints indica que **há
itens desativados ao longo do tempo**, algo que uma transcrição congelada não
acompanha. Ver ``docs/ACHADOS_DAS_FONTES.md``, seção 2.

Expõe ~15 tabelas oficiais (amparo legal, tipo de contrato, critério de
julgamento, modo de disputa etc.) — útil como referência ao interpretar códigos
encontrados em editais, atas ou outros sistemas que usem a mesma
codificação do PNCP, e para uso futuro por tools que venham a consumir os
endpoints de contratos/contratações já reservados em ``pncp_client.py``.
"""
from __future__ import annotations

from typing import Any

from ..domain.dominios import TABELAS_DOMINIO_PNCP
from ..logging_utils import get_logger

logger = get_logger(__name__)


async def consultar_tabelas_dominio_pncp(tabela: str | None = None) -> dict[str, Any]:
    """Devolve uma ou todas as tabelas de domínio oficiais do PNCP.

    Cobre 15 tabelas: ``instrumento_convocatorio``, ``modalidade_contratacao``
    (mesmos códigos de ``codigo_modalidade`` em ``buscar_pncp_texto``/
    ``buscar_contratacoes_pncp``), ``modo_disputa``, ``criterio_julgamento``,
    ``situacao_contratacao``, ``situacao_item_contratacao``,
    ``tipo_beneficio``, ``situacao_resultado_item_contratacao``,
    ``tipo_contrato``, ``tipo_termo_contrato``, ``categoria_processo``,
    ``tipo_documento`` (tipos de anexo do PNCP — Edital, Termo de
    Referência, Ata, Termo Aditivo etc.; **não** confundir com o parâmetro
    ``tipo_documento`` de ``buscar_pncp_texto``/``listar_arquivos_pncp``, que
    usa só ``"edital"``/``"ata"``/``"contrato"`` — categorias de busca do
    backend ``/api/search``, um domínio diferente), ``porte_empresa``,
    ``categoria_item_pca`` e ``amparo_legal`` (80 códigos, ex.: os já usados
    no campo ``amparo_legal`` devolvido por ``consultar_contratacao_pncp``).

    Esta tool é **pura** — não acessa nenhuma API, apenas devolve uma
    estrutura de dados fixa (ver módulo ``domain/dominios.py`` para a nota
    sobre a origem dos valores e o risco de desatualização).

    Args:
        tabela: Nome de uma tabela específica (ver lista acima). Se
            ``None`` (padrão), devolve todas as tabelas.

    Returns:
        Dicionário ``{"tabelas": {...}}`` — se ``tabela`` for informado,
        contém só essa chave; caso contrário, todas as 15. Cada tabela é uma
        lista de dicionários com, no mínimo, ``codigo`` e ``nome`` (alguns
        registros também têm ``descricao`` e/ou ``categoria``).

    Raises:
        ValueError: se ``tabela`` for informado e não for uma chave válida
            de ``domain.dominios.TABELAS_DOMINIO_PNCP``.
    """
    if tabela is not None and tabela not in TABELAS_DOMINIO_PNCP:
        raise ValueError(
            f"tabela deve ser um de {tuple(TABELAS_DOMINIO_PNCP)} ou None (todas)"
        )

    logger.info("consultar_tabelas_dominio_pncp tabela=%s", tabela)

    if tabela is not None:
        dados = {tabela: TABELAS_DOMINIO_PNCP[tabela]}
    else:
        dados = dict(TABELAS_DOMINIO_PNCP)

    return {"tabelas": dados}
