"""Tool MCP: navegação hierárquica completa do catálogo de serviços (CATSER)."""
from __future__ import annotations

from typing import Any

from ..clients import compras_client
from ..logging_utils import get_logger

logger = get_logger(__name__)

# Ordem oficial da hierarquia do CATSER:
# seção → divisão → grupo → classe → subclasse, sobre os endpoints
# /modulo-servico/1..5 (o nível "item", endpoint 6, já é coberto pela tool
# listar_itens_catalogo — fora do escopo desta navegação hierárquica).
_NIVEIS = ("secao", "divisao", "grupo", "classe", "subclasse")

# Campo do PRÓPRIO registro, em cada nível, que serve de codigo_pai para
# descer um nível (ex.: um registro de "secao" traz "codigoSecao" — é esse
# valor que se passa como codigo_pai para nivel="divisao").
_CAMPO_CODIGO = {
    "secao": "codigoSecao",
    "divisao": "codigoDivisao",
    "grupo": "codigoGrupo",
    "classe": "codigoClasse",
    "subclasse": "codigoSubclasse",
}

_PROXIMO_NIVEL = {
    "secao": "divisao",
    "divisao": "grupo",
    "grupo": "classe",
    "classe": "subclasse",
    "subclasse": None,
}


async def navegar_catalogo_servico(
    nivel: str | None = None,
    codigo_pai: int | None = None,
) -> dict[str, Any]:
    """Navega a hierarquia completa do catálogo de serviços (CATSER).

    Percorre seção → divisão → grupo → classe → subclasse
    (``/modulo-servico/1..5`` do Compras.gov.br), fechando a lacuna que
    ``descobrir_codigo_catalogo``/``listar_itens_catalogo`` deixavam: essas
    duas tools só cobrem classe (busca textual) e itens de uma classe —
    não davam como explorar a árvore completa a partir do topo (ex.:
    "quais são as seções?", "quais divisões tem a seção de TIC?").

    Chame sem argumentos para começar pelo topo (``nivel=None`` equivale a
    ``nivel="secao"``), depois use o campo indicado em
    ``campo_codigo_para_proximo_nivel`` de um dos ``registros`` retornados
    como ``codigo_pai`` da próxima chamada, com ``nivel=proximo_nivel``.
    Exemplo de navegação completa (TIC): ``navegar_catalogo_servico()`` →
    acha ``codigoSecao=1`` → ``navegar_catalogo_servico("divisao", 1)`` →
    acha ``codigoDivisao=11`` → ``navegar_catalogo_servico("grupo", 11)`` →
    acha ``codigoGrupo=111`` → ``navegar_catalogo_servico("classe", 111)`` →
    acha ``codigoClasse=1111`` → ``navegar_catalogo_servico("subclasse", 1111)``.

    Para o nível de ITEM (código CATSER real, usado em
    ``buscar_precos_praticados_compras``), use ``listar_itens_catalogo``
    (``tipo_item="servico"``) com o ``codigo_classe`` encontrado aqui — o
    endpoint de item filtra por classe, não por subclasse (confirmado ao
    vivo em ``listar_itens_servico_por_classe``).

    Args:
        nivel: Um de ``"secao"``, ``"divisao"``, ``"grupo"``, ``"classe"``,
            ``"subclasse"``. ``None`` (padrão) equivale a ``"secao"`` —
            ponto de partida da navegação.
        codigo_pai: Código do nível IMEDIATAMENTE ACIMA para filtrar os
            registros deste nível (ex.: ``codigoSecao`` ao pedir
            ``nivel="divisao"``). Opcional para ``"secao"``, ``"divisao"``,
            ``"grupo"`` e ``"classe"`` (omitido, lista o nível inteiro, sem
            filtro de pai) — **obrigatório** para ``"subclasse"`` (a API não
            oferece uma forma prática de listar todas as subclasses do
            catálogo de uma vez; ver ``clients.compras_client.listar_subclasses_servico``).

    Returns:
        Dicionário com ``nivel`` (efetivo), ``codigo_pai``,
        ``proximo_nivel`` (``None`` quando ``nivel="subclasse"`` — fim da
        hierarquia), ``campo_codigo_para_proximo_nivel`` (nome do campo, em
        cada registro deste nível, a usar como ``codigo_pai`` da próxima
        chamada), ``quantidade``, ``registros`` (formato bruto da API,
        preservando todos os campos originais) e ``avisos``.

    Raises:
        ValueError: se ``nivel`` não for um dos válidos, ou se
            ``nivel="subclasse"`` for pedido sem ``codigo_pai``.
    """
    nivel_efetivo = nivel or "secao"
    if nivel_efetivo not in _NIVEIS:
        raise ValueError(f"nivel deve ser um de {_NIVEIS} (ou None, equivalente a 'secao')")
    if nivel_efetivo == "subclasse" and codigo_pai is None:
        raise ValueError(
            "codigo_pai (codigoClasse) é obrigatório para nivel='subclasse' — a API não "
            "permite listar todas as subclasses do catálogo de uma vez de forma prática "
            "(ver clients.compras_client.listar_subclasses_servico)."
        )

    logger.info("navegar_catalogo_servico nivel=%s codigo_pai=%s", nivel_efetivo, codigo_pai)

    if nivel_efetivo == "secao":
        registros = await compras_client.listar_secoes_servico()
    elif nivel_efetivo == "divisao":
        registros = await compras_client.listar_divisoes_servico(codigo_pai)
    elif nivel_efetivo == "grupo":
        registros = await compras_client.listar_grupos_servico(codigo_pai)
    elif nivel_efetivo == "classe":
        todas_classes = await compras_client.listar_classes_servico()
        if codigo_pai is not None:
            registros = [c for c in todas_classes if c.get("codigoGrupo") == codigo_pai]
        else:
            registros = todas_classes
    else:  # subclasse
        registros = await compras_client.listar_subclasses_servico(codigo_pai)  # type: ignore[arg-type]

    avisos: list[str] = []
    if not registros:
        contexto_pai = f" com codigo_pai={codigo_pai}" if codigo_pai is not None else ""
        avisos.append(
            f"Nenhum registro encontrado para nivel='{nivel_efetivo}'{contexto_pai}. Pode "
            "ser um código inexistente, ou um nó sem filhos cadastrados (comum em "
            "'subclasse' — nem toda classe do CATSER tem subclasses)."
        )

    proximo_nivel = _PROXIMO_NIVEL[nivel_efetivo]
    return {
        "nivel": nivel_efetivo,
        "codigo_pai": codigo_pai,
        "proximo_nivel": proximo_nivel,
        "campo_codigo_para_proximo_nivel": _CAMPO_CODIGO[nivel_efetivo] if proximo_nivel else None,
        "quantidade": len(registros),
        "registros": registros,
        "avisos": avisos,
    }
