"""Cliente de enriquecimento de CNPJ (cadastro na Receita Federal).

Primeiro cliente deste projeto que consulta uma API **fora** de PNCP/
Compras.gov.br — a Receita Federal não tem uma API pública própria e gratuita
para consulta de CNPJ, então dependemos de agregadores de terceiros sobre a
mesma base de dados aberta (Cadastro Nacional da Pessoa Jurídica, publicado
periodicamente pela Receita Federal).

Estratégia confirmada ao vivo nesta sessão: tentar primeiro a `BrasilAPI
<https://brasilapi.com.br/api/cnpj/v1/{cnpj}>`_ e, **somente se ela falhar**
(qualquer :class:`~mcp_radardeprecos.clients.base.UpstreamError` — timeout,
5xx, ou 404), cair para a `MinhaReceita <https://minhareceita.org/{cnpj}>`_
como fallback. As duas expõem essencialmente o mesmo cadastro (confirmado ao
vivo: para o CNPJ de teste usado, os dois provedores devolveram os mesmos
campos com os mesmos valores), mas **não há garantia de que os nomes de
campos sejam idênticos em todo CNPJ** — provedores de terceiros sobre dados
abertos podem divergir em casos de borda (CNPJ inativo há muito tempo, MEI,
etc.). Por isso o resultado inclui ``_provider`` indicando qual API
respondeu, para que quem consome saiba a proveniência do dado.

Uso pretendido: checar
situação cadastral (deve ser ATIVA) e sócios (QSA) na formalização de uma
cotação direta com fornecedor — o guia de pesquisa de preços já recomenda
essa checagem, mas nenhuma tool deste projeto cobria isso até agora.

Nenhuma das duas APIs exige autenticação — ambas são gratuitas e somente-
leitura sobre dados públicos, consistente com a política de segurança deste
projeto (ver ``clients/base.py``).
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..utils import cache
from ..utils.cache import TTL_1_DIA
from ..utils.documentos import limpar_cnpj as _limpar_cnpj
from .base import UpstreamError, get_json

SOURCE_BRASILAPI = "brasilapi"
SOURCE_MINHARECEITA = "minhareceita"


def limpar_cnpj(cnpj: str) -> str:
    """Remove pontuação de um CNPJ (``.``, ``/``, ``-``, espaços).

    Reexportado de :mod:`~mcp_radardeprecos.utils.documentos`, onde a regra
    passou a viver. Mantido aqui como alias porque várias tools já importavam
    deste módulo; a implementação é uma só.

    **Preserva letras.** Até a v0.5.0 esta função mantinha apenas dígitos, o
    que mutilava CNPJ alfanumérico em silêncio — ver o cabeçalho de
    ``utils/documentos.py``.

    Não valida dígitos verificadores nem tamanho: para isso use
    :func:`~mcp_radardeprecos.utils.documentos.validar_cnpj`, que produz
    mensagem de erro específica ao parâmetro informado.
    """
    return _limpar_cnpj(cnpj)


async def consultar_cnpj(cnpj: str) -> dict[str, Any]:
    """Consulta o cadastro de um CNPJ na Receita Federal (via BrasilAPI, fallback MinhaReceita).

    ``cnpj`` deve vir já limpo (14 posições, sem pontuação; podem incluir
    letras, no formato alfanumérico vigente desde julho/2026) — use
    :func:`limpar_cnpj` antes de chamar, se necessário.

    Tenta a BrasilAPI primeiro; se ela falhar (:class:`UpstreamError` — rede,
    timeout, 5xx, ou 404 de CNPJ inexistente/inválido), tenta a MinhaReceita.
    Se as duas falharem, propaga um :class:`UpstreamError` combinado com as
    duas mensagens. Resultado cacheado por :data:`TTL_1_DIA` (cadastro na
    Receita Federal muda raramente) — cache mantido aqui, não em
    :func:`~mcp_radardeprecos.clients.base.get_json`, porque a chave de
    cache é por CNPJ e independe de qual provedor respondeu.
    """
    cache_key = f"cnpj:{cnpj}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    erro_brasilapi: UpstreamError | None = None
    dados: dict[str, Any] | None = None
    provider = SOURCE_BRASILAPI
    try:
        dados = await get_json(
            settings.brasilapi_base_url, f"/cnpj/v1/{cnpj}", {}, source=SOURCE_BRASILAPI
        )
    except UpstreamError as exc:
        erro_brasilapi = exc

    if dados is None:
        provider = SOURCE_MINHARECEITA
        try:
            dados = await get_json(
                settings.minhareceita_base_url, f"/{cnpj}", {}, source=SOURCE_MINHARECEITA
            )
        except UpstreamError as exc_minhareceita:
            raise UpstreamError(
                "cnpj",
                None,
                f"BrasilAPI e MinhaReceita falharam para CNPJ {cnpj} — "
                f"BrasilAPI: {erro_brasilapi}; MinhaReceita: {exc_minhareceita}",
            ) from exc_minhareceita

    if dados is None:
        raise UpstreamError(
            "cnpj", None, f"CNPJ {cnpj} não encontrado em nenhum provedor (resposta vazia)"
        )

    resultado = {**dados, "_provider": provider}
    cache.set(cache_key, resultado, TTL_1_DIA)
    return resultado
