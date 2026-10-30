"""Cliente do Banco de Preços em Saúde (BPS) — API de Dados Abertos do Ministério da Saúde.

O BPS registra compras de **medicamentos e dispositivos médicos** por estados,
municípios e consórcios intermunicipais. É referência nacional para cotação em
saúde (Resolução de Consolidação CIT nº 1/2021) e cobre um universo que as
demais fontes deste servidor não alcançam: aquisições municipais e de
consórcios, que raramente aparecem com itemização no PNCP.

O catálogo é o **CATMAT**, o mesmo do Compras.gov.br — de modo que
``descobrir_codigo_catalogo`` resolve o código sem nenhuma máquina adicional.

Endpoint: ``GET /economia-da-saude/bps``

**A URL não tem ``/v1``.** O Swagger UI fica em ``/v1/``, mas a especificação
(``/static/swagger.json``) não declara ``basePath``, então os caminhos são
relativos à raiz. Montar a URL a partir do endereço da página de documentação
devolve 404 — foi o primeiro erro cometido aqui, em 2026-08-27.

Três achados da verificação ao vivo daquela data, todos com consequência
direta sobre como este cliente funciona:

1. **A ordem padrão é ``dataCompra`` decrescente e é confiável.** Cinquenta
   registros consecutivos de um mesmo CATMAT vieram monotonicamente
   decrescentes, sem uma quebra em 49 transições — enquanto ``dataInsercao``
   quebrava 24 vezes nas mesmas transições, o que descarta ordem de inserção.

   Isso importa mais do que parece. No PNCP, a parada antecipada da varredura
   foi tentada e revertida três vezes, sempre pelo mesmo motivo estrutural: o
   índice ordenava por ``data_atualizacao_pncp`` e o filtro era sobre
   ``data_publicacao_pncp`` — campos diferentes, então parar pela data da
   página omitia registros válidos. Aqui o campo da ordem e o do filtro são o
   MESMO (``dataCompra`` / ``dataCompraInicio``+``dataCompraFim``), e a parada
   por data é correta por construção.

2. **O parâmetro ``ordenacao`` é uma armadilha — ver ``_ORDENACAO_NAO_USAR``.**

3. **A resposta não traz total.** Vem ``{"bps": [...]}`` e nada mais: não há
   contagem nem indicação de haver próxima página. A varredura pagina até vir
   página vazia, e a cobertura NUNCA pode ser afirmada como completa.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..logging_utils import get_logger
from ..utils.documentos import limpar_cnpj
from .base import get_json

logger = get_logger(__name__)

SOURCE = "bps/saude.gov.br"

#: Teto declarado na especificação e respeitado pela origem.
_MAX_TAMANHO_PAGINA = 500

#: Cache de 1 hora. O painel oficial declara atualização diária, então uma
#: janela curta não perde nada e evita repetir a mesma varredura numa sessão.
_TTL_1_HORA = 3600.0

#: **Não envie ``ordenacao``.** A especificação documenta
#: ``precoUnitario+asc|desc``, ``dataCompra+asc|desc`` e ``anoCompra+asc|desc``.
#: Medição de 2026-08-27, mesmo CATMAT (268252), três valores distintos:
#:
#:   ordenacao=precoUnitario+asc   -> 3,00 / 1,98 / 2,45
#:   ordenacao=precoUnitario+desc  -> 3,00 / 1,98 / 2,45  (idêntico)
#:   ordenacao=dataCompra+desc     -> 3,00 / 1,98 / 2,45  (idêntico)
#:
#: Nenhuma das três está ordenada pelo campo que nomeia. E o parâmetro não é
#: ignorado: sem ele a mesma consulta devolvia registros de 2026; com ele,
#: registros de 2022 e 2020. Ou seja, informar ``ordenacao`` troca o conjunto
#: de resultados E destrói a ordem padrão, sem produzir erro.
#:
#: A explicação provável é que a API monta um ``ORDER BY`` padrão e, ao tentar
#: substituí-lo pelo valor recebido, o mapeamento falha em silêncio e a
#: cláusula cai inteira — devolvendo as linhas na ordem física de carga, que
#: começa pelos dados mais antigos.
#:
#: O risco concreto: quem pede ``precoUnitario+asc`` esperando o menor preço
#: recebe um registro arbitrário. No caso medido, leria R$ 3,00 como mínimo,
#: quando a consulta sem ordenação já mostrava R$ 0,549 — erro de mais de
#: cinco vezes, em silêncio. Ordenação, se necessária, faz-se no cliente.
_ORDENACAO_NAO_USAR = True


def _limpar(valor: str | None) -> str | None:
    """Remove máscara de CNPJ, preservando ``None`` e string vazia como ``None``.

    Até a v0.5.0 esta função mantinha **apenas dígitos**, e era o pior dos
    cinco pontos do projeto que assumiam CNPJ numérico: um CNPJ alfanumérico
    como ``12ABC4000195`` virava ``1240000195`` e seguia para a API do BPS
    como um número plausível — de outra empresa, ou de nenhuma. A resposta
    voltava normal, vazia ou com os dados errados, sem nada indicando que a
    entrada havia sido alterada. Falha silenciosa, a categoria que este
    projeto trata como a mais cara.

    Delega para :func:`~mcp_radardeprecos.utils.documentos.limpar_cnpj`,
    que preserva letras.
    """
    if valor is None:
        return None
    return limpar_cnpj(valor) or None


async def consultar_bps(
    *,
    codigo_catmat: str | None = None,
    cnpj_instituicao: str | None = None,
    estado: str | None = None,
    cnpj_fornecedor: str | None = None,
    cnpj_fabricante: str | None = None,
    modalidade: str | None = None,
    tipo_compra: str | None = None,
    generico: bool | None = None,
    registro_anvisa: str | None = None,
    data_compra_inicio: str | None = None,
    data_compra_fim: str | None = None,
    ano_compra: int | None = None,
    valor_unitario_minimo: float | None = None,
    valor_unitario_maximo: float | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 100,
) -> list[dict[str, Any]]:
    """Uma página de registros do BPS.

    ``codigo_catmat`` ou ``cnpj_instituicao`` é obrigatório pela API — sem um
    dos dois a origem recusa. A validação fica na tool, que tem como explicar
    o porquê a quem chamou.

    Datas em ``AAAA-MM-DD`` (formato da origem, diferente do ``AAAAMMDD`` do
    PNCP — a conversão fica na tool, para que o usuário informe um formato só).

    Devolve a lista de registros, já extraída da chave ``bps`` do envelope.
    Lista vazia significa "esta página não tem registros", o que na varredura
    é o único sinal de fim disponível.
    """
    params = {
        "codigoCatmat": codigo_catmat,
        "cnpjInstituicao": _limpar(cnpj_instituicao),
        "estado": estado.upper() if estado else None,
        "cnpjFornecedor": _limpar(cnpj_fornecedor),
        "cnpjFabricante": _limpar(cnpj_fabricante),
        "modalidade": modalidade,
        "tipoCompra": tipo_compra,
        "generico": generico,
        "registroAnvisa": registro_anvisa,
        "dataCompraInicio": data_compra_inicio,
        "dataCompraFim": data_compra_fim,
        "anoCompra": ano_compra,
        "valorUnitarioMinimo": valor_unitario_minimo,
        "valorUnitarioMaximo": valor_unitario_maximo,
        "pagina": max(1, pagina),
        "tamanhoPagina": max(1, min(tamanho_pagina, _MAX_TAMANHO_PAGINA)),
        # `ordenacao` deliberadamente ausente — ver _ORDENACAO_NAO_USAR.
    }
    chave = ":".join(
        f"{k}={v}" for k, v in sorted(params.items()) if v is not None
    )
    resultado = await get_json(
        settings.saude_dadosabertos_base_url,
        "/economia-da-saude/bps",
        params,
        source=SOURCE,
        cache_key=f"bps:{chave}",
        cache_ttl_seconds=_TTL_1_HORA,
    )
    if isinstance(resultado, dict):
        registros = resultado.get("bps")
        return registros if isinstance(registros, list) else []
    # Envelope inesperado: a origem mudou de forma. Devolver [] esconderia a
    # mudança atrás de "nenhum resultado" — registra-se para aparecer no log.
    logger.warning(
        "BPS devolveu envelope inesperado (%s) — esperado dict com chave 'bps'",
        type(resultado).__name__,
    )
    return []
