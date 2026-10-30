"""Cliente HTTP compartilhado: timeout, retries com backoff e tratamento de erros.

Uso restrito a chamadas GET somente-leitura, sem credenciais hardcoded —
todas as APIs consultadas são públicas.

Suporta cache opcional em memória (``cache_key``/``cache_ttl_seconds``), para
evitar refazer a mesma chamada de rede repetidamente na mesma pesquisa, com
TTL curto por tipo de recurso. Centralizado aqui (em vez de em
cada função de cliente) para manter a mesma política de cache/TTL em um só
lugar — nenhuma função de ``pncp_client.py``/``compras_client.py`` precisa
reimplementar lógica de cache, só decidir se/por quanto tempo cachear.

Duas mudanças de desempenho/resiliência (ver CHANGELOG):

1. **Cliente compartilhado com pool de conexões.** Até a v0.1.51, cada
   chamada criava um ``httpx.AsyncClient`` novo — pagando handshake TCP+TLS
   do zero a cada requisição. Isso era tolerável com o teto antigo de 5
   páginas por varredura, mas a própria v0.1.51 elevou esse teto para 100
   páginas por chamada de tool (mais o fan-out de itens/resultados/arquivos),
   ou seja, potencialmente centenas de handshakes numa única pesquisa.
   Agora um único cliente por processo é criado sob demanda e reutilizado
   (keep-alive), com limites explícitos de pool. Se o event loop corrente
   mudar (só acontece em testes — em produção, stdio e HTTP rodam num único
   loop), o cliente é recriado, pois conexões de um loop encerrado não podem
   ser reusadas em outro.

2. **Retry para erros transitórios de servidor (429/502/503/504), com
   backoff exponencial e jitter.** Até a v0.1.51, qualquer status >= 400 —
   inclusive um 503 momentâneo do PNCP, que tem instabilidade intermitente
   conhecida — virava ``UpstreamError`` na primeira ocorrência, e o retry
   (que só cobria timeout/erro de transporte) usava backoff linear fixo, sem
   jitter. Agora 429/502/503/504 também são retryados (respeitando o header
   ``Retry-After``, quando presente e razoável); os demais 4xx continuam
   falhando imediatamente — são erros de validação, repetir não ajuda. O
   jitter evita que várias corrotinas de um mesmo fan-out (ex.:
   ``incluir_arquivos``) re-tentem todas no mesmo instante.
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Mapping
from typing import Any

import httpx

from .. import auditoria, observability
from ..config import settings
from ..logging_utils import get_logger
from ..utils import cache

logger = get_logger(__name__)


class UpstreamError(RuntimeError):
    """Erro ao consultar uma API pública upstream (PNCP ou Compras.gov.br)."""

    def __init__(self, source: str, status_code: int | None, message: str) -> None:
        super().__init__(f"[{source}] {message} (status={status_code})")
        self.source = source
        self.status_code = status_code


#: Status HTTP tratados como transitórios (vale a pena re-tentar).
#: 429 = rate limit upstream; 502/503/504 = indisponibilidade momentânea.
#: Demais 4xx (400, 404, 422...) são erros de validação — nunca retryados.
STATUS_RETRYAVEIS = frozenset({429, 502, 503, 504})

#: Teto (segundos) aceito de um header ``Retry-After`` — valores acima disso
#: (ou inválidos) caem no backoff exponencial normal, para uma tool nunca
#: ficar bloqueada por um Retry-After absurdo vindo do upstream.
_RETRY_AFTER_MAX_SEGUNDOS = 30.0

# Cliente HTTP compartilhado do processo (pool de conexões/keep-alive), criado
# sob demanda por _get_client(). Guardado junto com o event loop que o criou:
# conexões abertas num loop não são válidas em outro, então se o loop mudou
# (caso dos testes, um loop novo por teste), um cliente novo é criado. Em
# produção há um único loop pela vida do processo, então o cliente é criado
# uma vez e reutilizado para sempre — que é o objetivo.
_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


def _get_client() -> httpx.AsyncClient:
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        _client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            # O User-Agent é FUNCIONAL, não cosmético — ver a nota longa em
            # config.py. Sem ele, o httpx se anuncia como "python-httpx/x.y.z"
            # e o /api/search do PNCP derruba a conexão em ~70% das chamadas
            # (medido em 10 rodadas intercaladas, 2026-08-21). Era a causa das
            # "falhas intermitentes da origem" que tratamos com backoff.
            headers={"User-Agent": settings.http_user_agent},
        )
        _client_loop = loop
    return _client


async def aclose() -> None:
    """Fecha o cliente compartilhado (shutdown gracioso; opcional em stdio)."""
    global _client, _client_loop
    if _client is not None:
        await _client.aclose()
        _client = None
        _client_loop = None


#: Falhas que significam "o servidor ATENDEU e desistiu no meio", em oposição
#: a "o servidor não atendeu". As três descrevem o mesmo fenômeno em momentos
#: diferentes da mesma requisição:
#:
#: - ``ReadTimeout``  — aceitou, começou a responder, parou de enviar
#: - ``ReadError``    — aceitou, a conexão morreu durante a leitura
#:
#: ``RemoteProtocolError`` esteve nesta tupla entre a v0.4.15 e a v0.4.19, e
#: SAIU — ver :data:`_ERROS_CONEXAO_DERRUBADA`. A hipótese de que ela também
#: significava "servidor lento" não sobreviveu à medição.
#:
#: Retentar é seguro: todas as chamadas deste cliente são GET, idempotentes.
_ERROS_SERVIDOR_DESISTIU = (
    httpx.ReadError,
    httpx.ReadTimeout,
)

#: Falhas em que a CONEXÃO caiu sem o servidor responder nada — categoria
#: separada porque pede a reação OPOSTA à de :data:`_ERROS_SERVIDOR_DESISTIU`.
#:
#: Medido no ``/api/search`` do PNCP em 2026-08-21, direto da máquina do
#: usuário, sem proxy no caminho: 1 falha em 5 chamadas
#: idênticas. As 4 que passaram responderam em 219–489ms; a que falhou levou
#: 1066ms e não trouxe byte nenhum. Meia hora antes, a MESMA chamada pelo
#: ambiente de produção falhara 3 vezes seguidas; depois passou em 0,7s.
#:
#: Isso não é lentidão — é a conexão sendo derrubada. E contra conexão
#: derrubada, ESPERAR é a reação errada: o que cura é uma conexão nova. Com
#: a classificação anterior (base 2s) as 3 tentativas gastavam ~6s de espera
#: para tratar algo que se resolve em milissegundos, e ainda por cima davam
#: mais tempo para as conexões ociosas do pool serem fechadas pela origem —
#: aumentando a chance de a tentativa seguinte pegar outra conexão morta.
_ERROS_CONEXAO_DERRUBADA = (httpx.RemoteProtocolError,)

#: Base do backoff para :data:`_ERROS_SERVIDOR_DESISTIU` — v0.4.14.
#:
#: Com a base normal de 0.5s, as 3 tentativas cabem em ~1,5s. Contra um
#: endpoint que está lento (não fora do ar), isso é tempo curto demais para
#: ele se recuperar: as três tentativas caem na mesma janela ruim e a tool
#: falha. Medido no ``/api/search`` do PNCP em 2026-08-12. Com base 2s, as
#: tentativas se espalham por ~6s, que é a ordem de grandeza da lentidão
#: observada. Erros de conexão (``ConnectError``) seguem no backoff curto:
#: ali o servidor nem atendeu, e esperar mais raramente ajuda.
_BACKOFF_BASE_LEITURA = 2.0

#: Base e fator do backoff para :data:`_ERROS_CONEXAO_DERRUBADA` — v0.4.19.
#:
#: A base é deliberadamente MENOR que a normal de 0.5s, e o fator é MAIOR que
#: o 2 usado nas outras famílias. Os dois ajustes atacam causas diferentes que
#: produzem a mesma exceção, e é por isso que não bastava mexer na base:
#:
#: - **Conexão morta no pool.** A origem fechou uma conexão ociosa, nós
#:   escrevemos nela e recebemos EOF. Não há o que esperar: a tentativa
#:   seguinte abre outra conexão e passa. Quer a 1ª repetição QUASE IMEDIATA,
#:   e é o que a base de 0.2s dá.
#: - **Janela ruim na origem.** O serviço está derrubando conexões por alguns
#:   segundos. Aqui repetir rápido é inútil: as tentativas caem todas dentro
#:   da mesma janela. Foi o que se viu em produção em 2026-08-21, com 3 falhas
#:   seguidas numa origem que, medida direto, falha só 1 vez em 5.
#:
#: Com base 0.2 e fator 4 as esperas ficam 0.2 / 0.8 / 3.2s: a primeira
#: repetição cobre a conexão morta, e a última já está longe o bastante para
#: cair fora de uma janela curta. Um fator 2 daria 0.2 / 0.4 / 0.8 — tudo
#: dentro de um segundo, resolvendo só metade do problema.
_BACKOFF_BASE_CONEXAO = 0.2
_BACKOFF_FATOR_CONEXAO = 4.0

#: Teto de UMA espera de backoff, em segundos — v0.4.19.
#:
#: Existe porque crescimento exponencial e número de tentativas se multiplicam:
#: com o fator 4 da família de conexão, a 4ª espera seria 12,8s e a 5ª, 51s.
#: Sem teto, aumentar ``http_max_retries`` para absorver uma origem instável
#: trocaria a falha rápida por um travamento longo — pior para quem chamou,
#: porque o cliente MCP desiste no meio e o usuário não recebe nem erro nem
#: resposta. Com o teto, as esperas da família de conexão ficam
#: 0.2 / 0.8 / 3.2 / 6 / 6 e as de leitura 2 / 4 / 6 / 6 / 6.
_ESPERA_MAX_SEGUNDOS = 6.0


def _espera_retry(
    attempt: int, retry_after_header: str | None, *, erro: BaseException | None = None
) -> float:
    """Quanto esperar antes da tentativa seguinte (segundos).

    Prioriza um ``Retry-After`` numérico do upstream (se razoável); senão,
    backoff exponencial com jitter de até 25%. A base depende do que falhou,
    porque cada família pede uma reação diferente:

    - :data:`_ERROS_CONEXAO_DERRUBADA` → 0.2 / 0.8 / 3.2s: primeira repetição
      quase imediata (conexão morta) e última bem espaçada (janela ruim).
    - :data:`_ERROS_SERVIDOR_DESISTIU` → :data:`_BACKOFF_BASE_LEITURA`
      (2, 4, 8, ...): o servidor está lento, precisa de tempo.
    - demais (``ConnectError`` etc.) → 0.5s (0.5, 1, 2, ...).

    A ordem dos testes importa: ``RemoteProtocolError`` é subclasse de
    ``httpx.ProtocolError``, não das de leitura, mas manter o teste de conexão
    primeiro deixa a precedência explícita para quem mexer nas tuplas depois.
    """
    if retry_after_header is not None:
        try:
            valor = float(retry_after_header)
            if 0 <= valor <= _RETRY_AFTER_MAX_SEGUNDOS:
                return valor
        except ValueError:
            pass  # formato de data HTTP ou lixo — ignora, usa backoff normal
    if isinstance(erro, _ERROS_CONEXAO_DERRUBADA):
        base_inicial, fator = _BACKOFF_BASE_CONEXAO, _BACKOFF_FATOR_CONEXAO
    elif isinstance(erro, _ERROS_SERVIDOR_DESISTIU):
        base_inicial, fator = _BACKOFF_BASE_LEITURA, 2.0
    else:
        base_inicial, fator = 0.5, 2.0
    base = min(base_inicial * (fator ** (attempt - 1)), _ESPERA_MAX_SEGUNDOS)
    return base * (1 + random.uniform(0, 0.25))


def descrever_excecao(exc: BaseException) -> str:
    """Descrição legível de uma exceção, SEMPRE com o tipo.

    Motivação: o log de retry saía
    truncado — ``tentativa 1/3 falhou para https://pncp.gov.br/api/search:``
    e nada depois. Causa: várias exceções de rede do httpx
    (``ReadError``, ``ConnectError``, ``RemoteProtocolError``) têm
    ``str(exc)`` VAZIO, então o ``%s`` do log não imprimia nada e ficava
    impossível distinguir timeout de reset de conexão ou falha de DNS —
    exatamente a informação necessária para saber se o problema é do
    upstream (PNCP) ou nosso.

    Devolve ``"TipoDaExcecao: mensagem"`` ou, quando não há mensagem,
    apenas ``"TipoDaExcecao"``.
    """
    tipo = type(exc).__name__
    mensagem = str(exc).strip()
    return f"{tipo}: {mensagem}" if mensagem else tipo


async def get_json(
    base_url: str,
    path: str,
    params: Mapping[str, Any],
    *,
    source: str,
    cache_key: str | None = None,
    cache_ttl_seconds: float | None = None,
    timeout_seconds: float | None = None,
) -> Any:
    """``_executar`` com métrica por FONTE EXTERNA.

    O ponto de medição fica aqui, e não em cada cliente (``pncp_client``,
    ``compras_client``, ``tcu_client``, ``bps_client``), pelo mesmo motivo do
    wrapper de registro de ferramentas no ``server.py``: um lugar só,
    impossível esquecer numa das fontes. Um cliente novo passa a ser medido
    sem ninguém lembrar de instrumentá-lo.

    O que se mede é a chamada **lógica** — uma por invocação —, com o número
    de tentativas HTTP que ela consumiu. Contar por tentativa inflaria o
    volume e esconderia justamente o sinal que interessa: uma chamada que
    precisou de três tentativas conta como UMA chamada com
    ``tentativas=3``, e é isso que faz ``tentativas_media`` denunciar uma
    origem instável antes que ela vire erro visível.
    """
    tentativas: list[int] = [1]
    inicio = time.monotonic()
    sucesso = False
    try:
        resultado = await _executar(
            base_url,
            path,
            params,
            source=source,
            cache_key=cache_key,
            cache_ttl_seconds=cache_ttl_seconds,
            timeout_seconds=timeout_seconds,
            _tentativas=tentativas,
        )
        sucesso = True
        return resultado
    finally:
        observability.registrar_upstream(
            source, time.monotonic() - inicio, sucesso, tentativas[0]
        )


async def _executar(
    base_url: str,
    path: str,
    params: Mapping[str, Any],
    *,
    source: str,
    cache_key: str | None = None,
    cache_ttl_seconds: float | None = None,
    timeout_seconds: float | None = None,
    _tentativas: list[int] | None = None,
) -> Any:
    """Executa um GET somente-leitura e retorna o corpo JSON, com retries.

    Se ``cache_key`` e ``cache_ttl_seconds`` forem informados, tenta servir a
    resposta do cache em memória antes de fazer a chamada de rede, e grava o
    resultado no cache (por ``cache_ttl_seconds`` segundos) após uma resposta
    bem-sucedida. Erros (``UpstreamError``) nunca são cacheados. Chamadores
    que não passam ``cache_key`` mantêm o comportamento anterior (sempre
    chamada de rede) — em particular, buscas textuais (``buscar_texto``)
    nunca devem ser cacheadas, já que seu resultado muda a qualquer momento
    com novos editais publicados.

    Retries: timeouts/erros de transporte e status 429/502/503/504 (ver
    ``STATUS_RETRYAVEIS``) são re-tentados até ``http_max_retries`` vezes,
    com backoff exponencial + jitter (``Retry-After`` do upstream é
    respeitado quando presente e <= 30s). Demais status >= 400 falham
    imediatamente com ``UpstreamError``.

    ``timeout_seconds`` sobrescreve, só para esta chamada, o timeout padrão do
    cliente compartilhado — sem afetar as demais fontes. Usado por fontes
    reconhecidamente lentas (ex.: consulta consolidada de PJ do TCU, que faz
    busca ao vivo em quatro bases). ``None`` mantém o timeout padrão.
    """
    if cache_key is not None and cache_ttl_seconds is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    clean_params = {k: v for k, v in params.items() if v is not None}
    url = f"{base_url}{path}"
    last_error: Exception | None = None
    ultimo_status: int | None = None

    client = _get_client()
    timeout = timeout_seconds if timeout_seconds is not None else httpx.USE_CLIENT_DEFAULT
    for attempt in range(1, settings.http_max_retries + 1):
        if _tentativas is not None:
            _tentativas[0] = attempt
        try:
            response = await client.get(url, params=clean_params, timeout=timeout)
            # Trilha de auditoria: registra CADA acesso upstream com
            # URL, params, status e hash da resposta bruta. Best-effort — não
            # interfere no fluxo (a função nunca levanta).
            auditoria.registrar_upstream(
                source=source,
                url=url,
                params=clean_params,
                status=response.status_code,
                corpo=response.content,
            )
            if response.status_code == 204:
                return None
            if response.status_code in STATUS_RETRYAVEIS:
                ultimo_status = response.status_code
                last_error = UpstreamError(
                    source, response.status_code, response.text[:300]
                )
                if attempt < settings.http_max_retries:
                    espera = _espera_retry(
                        attempt, response.headers.get("Retry-After")
                    )
                    logger.warning(
                        "status transitório %s de %s (tentativa %s/%s) — nova tentativa em %.1fs",
                        response.status_code,
                        url,
                        attempt,
                        settings.http_max_retries,
                        espera,
                    )
                    await asyncio.sleep(espera)
                continue
            if response.status_code >= 400:
                raise UpstreamError(source, response.status_code, response.text[:300])
            # Corpo vazio num 2xx (ex.: a consulta consolidada de PJ do TCU
            # devolve 200 com corpo vazio para CNPJ inexistente/inválido) —
            # response.json() estouraria JSONDecodeError cru. Tratamos como
            # None, deixando o chamador decidir (mesma semântica do 204).
            if not response.content:
                return None
            resultado = response.json()
            if cache_key is not None and cache_ttl_seconds is not None:
                cache.set(cache_key, resultado, cache_ttl_seconds)
            return resultado
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            ultimo_status = None
            logger.warning(
                "tentativa %s/%s falhou para %s: %s",
                attempt,
                settings.http_max_retries,
                url,
                descrever_excecao(exc),
            )
            if attempt < settings.http_max_retries:
                await asyncio.sleep(_espera_retry(attempt, None, erro=exc))
        except UpstreamError:
            raise

    if isinstance(last_error, UpstreamError):
        raise last_error

    # A mensagem diz de QUEM é a falha e o que fazer. Sem isso, o texto que
    # chega ao cliente MCP é indistinguível de um defeito nosso — e foi
    # exatamente assim que foi lido em 2026-08-21, quando um relatório
    # concluiu "as ferramentas de pesquisa no PNCP estão indisponíveis" a
    # partir de uma falha intermitente da origem, medida em 1 de cada 5
    # chamadas diretas, sem nada nosso no caminho.
    detalhe = (
        descrever_excecao(last_error) if last_error is not None else "causa desconhecida"
    )
    if isinstance(last_error, _ERROS_CONEXAO_DERRUBADA):
        detalhe += (
            f". A origem ({source}) aceitou a conexão e a fechou sem responder,"
            f" nas {settings.http_max_retries} tentativas. É instabilidade"
            " conhecida e INTERMITENTE do"
            " lado do provedor, não um erro de parâmetros nem indisponibilidade"
            " da ferramenta: repetir a mesma chamada costuma funcionar."
        )
    raise UpstreamError(
        source,
        ultimo_status,
        f"falha de rede após {settings.http_max_retries} tentativas: {detalhe}",
    )
