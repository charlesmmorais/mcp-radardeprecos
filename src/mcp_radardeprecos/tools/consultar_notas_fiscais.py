"""Tool MCP: notas fiscais eletrônicas (NF-e) itemizadas de contratos — o preço efetivamente FATURADO.

A referência de preço mais usada é o valor **homologado** (vencedor da
disputa, antes da execução do contrato). O PNCP também expõe, via os instrumentos de cobrança de um contrato, a NF-e
efetivamente emitida — com itens (``descricaoProdutoServico``, NCM,
quantidade, valor unitário/total) e eventos — ou seja, o preço realmente
**FATURADO** durante a execução, um degrau além do homologado.

**Uso pretendido: verificação pós-contratual / auditoria (faturado vs.
homologado), NÃO pesquisa de preços primária.** A IN SEGES/ME nº 65/2021
(Art. 3º, hierarquia de fontes no guia de boas práticas de pesquisa de preços)
não reconhece NF-e de execução contratual como fonte de pesquisa de preços —
o preço faturado de UM contrato já assinado não é uma amostra de mercado,
é a execução de um preço já negociado. Um aviso fixo lembra disso em toda
chamada. Uso real: cruzar o valor faturado com o homologado
(``buscar_contratacoes_pncp``) para identificar divergências (ex.: item
faturado acima do preço unitário homologado no edital).

**Schema confirmado ao vivo em 2026-08-27** (contratos
``00394544000185-2-002038/2024`` e ``32479123000143-2-000050/2024``). A
confirmação, que até então estava pendente, encontrou três defeitos — e o
principal é da origem, não nosso:

1. **Os itens da NF-e não são entregues.** O campo ``jsonResponseNFe`` traz
   ``{"notaFiscalDTO":null,"itensNotaFiscal":null,"eventosNotaFiscal":null}``
   em **8 de 8** notas medidas, ao lado de ``statusResponseNFe="200"``. Ou
   seja: a estrutura existe, o status declara sucesso, e o conteúdo é nulo.
   É o preço FATURADO — a razão de existir desta tool — que não chega.

   Consequência para quem consome: ``nota_fiscal: None`` sem qualificação se
   lê como "esta nota não tem itens", quando o correto é "a origem não
   entrega os itens". A diferença decide se alguém conclui que um contrato
   não foi faturado ou que o dado não está disponível. Por isso cada
   instrumento passa a trazer ``problemas`` quando o envelope vem vazio.

2. **``jsonResponseNFe`` é uma STRING contendo JSON**, não objeto aninhado.
   A normalização procurava ``itensNotaFiscal`` como chave do objeto externo,
   onde nunca esteve. Corrigido; se a origem passar a preencher o envelope,
   o dado será encontrado.

3. **Nomes de campo divergentes**: a API usa ``dataEmissaoDocumento`` e
   ``chaveNFe`` (NF maiúsculo). Líamos ``dataEmissao`` e ``chaveNfe``, e
   devolvíamos ``None`` ao lado de dados presentes.

Achado adicional sobre a qualidade do cadastro: em 6 das 8 notas, o campo
``chaveNFe`` continha cadeias de nove caracteres (``2WRK-X5JV``,
``BLYD-PKZ2``, ...), que não são chave de acesso de documento fiscal algum.
O PNCP aceita e devolve o conteúdo como está. A chave passa a vir acompanhada
do problema declarado, em vez de descartada ou repassada em silêncio.

Disponibilidade: o endpoint por CONTRATO responde normalmente. O endpoint por
PERÍODO (API de Consulta, ``/v1/instrumentoscobranca/inclusao``) estava
indisponível na data da medição, com timeout acima de 180s — condição que
afetava toda a API de Consulta, e não este endpoint em particular.
"""
from __future__ import annotations

import json
from typing import Any

from ..clients import pncp_client
from ..clients.pncp_client import parse_numero_controle_pncp
from ..logging_utils import get_logger
from ..utils.documentos import mascarar_documento

logger = get_logger(__name__)

_LIMITE_MAXIMO = 100

_AVISO_METODOLOGICO = (
    "NF-e é EXECUÇÃO contratual (preço efetivamente FATURADO) — serve à análise "
    "crítica/auditoria (faturado vs. homologado), NÃO como fonte primária de pesquisa "
    "de preços conforme a IN SEGES/ME 65/2021 (só valores homologados/contratados são "
    "referência válida — ver buscar_contratacoes_pncp)."
)


def _formatar_item_nfe(bruto: dict[str, Any]) -> dict[str, Any]:
    return {
        "numero_item": bruto.get("numeroItem"),
        "descricao_produto_servico": bruto.get("descricaoProdutoServico"),
        "codigo_ncm": bruto.get("codigoNCM"),
        "descricao_ncm": bruto.get("descricaoNCM"),
        "cfop": bruto.get("cfop"),
        "quantidade": bruto.get("quantidade"),
        "unidade": bruto.get("unidade"),
        "valor_unitario": bruto.get("valorUnitario"),
        "valor_total": bruto.get("valorTotal"),
    }


def _formatar_evento(bruto: dict[str, Any]) -> dict[str, Any]:
    return {
        "tipo": bruto.get("tipoEvento") or bruto.get("tipo"),
        "data": bruto.get("dataEvento") or bruto.get("data"),
    }


def _esta_cancelada(eventos: list[dict[str, Any]]) -> bool:
    """Detecta cancelamento a partir dos eventos da NF-e.

    Conservador: só marca ``True`` quando o tipo do evento menciona
    cancelamento. Na dúvida devolve ``False`` — a flag existe para alertar,
    não para excluir registros, e um falso positivo esconderia despesa real.
    """
    for evento in eventos or []:
        tipo = str(evento.get("tipoEvento") or evento.get("tipo") or "").lower()
        if "cancel" in tipo:
            return True
    return False


def _formatar_nota_fiscal(bruto: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bruto:
        return None
    emitente = bruto.get("emitente") or {}
    itens_brutos = bruto.get("itens") or bruto.get("itensNotaFiscal") or []
    eventos_brutos = bruto.get("eventos") or bruto.get("eventosNotaFiscal") or []
    return {
        "numero": bruto.get("numero"),
        "serie": bruto.get("serie"),
        "data_emissao": bruto.get("dataEmissao"),
        "emitente": {
            "ni": mascarar_documento(emitente.get("ni") or emitente.get("niFornecedor")),
            "nome": emitente.get("nome") or emitente.get("nomeRazaoSocial"),
        },
        "valor_nota": bruto.get("valorNota") or bruto.get("valorTotal"),
        "itens": [_formatar_item_nfe(i) for i in itens_brutos],
        "eventos": [_formatar_evento(e) for e in eventos_brutos],
        # v0.4.10: uma NF CANCELADA continua na resposta, e seu valor não
        # representa despesa realizada. O cancelamento só aparecia dentro da
        # lista de eventos (texto livre), fácil de ignorar — agora é uma flag
        # explícita no topo do registro.
        "cancelada": _esta_cancelada(eventos_brutos),
    }


#: Comprimentos válidos de chave de acesso, por modelo de documento:
#: 44 dígitos para NF-e (mercadoria) e 50 para NFS-e do padrão nacional
#: (serviço). O campo ``chaveNFe`` do PNCP recebe os dois, porque um contrato
#: de serviço é faturado por NFS-e.
#:
#: A primeira versão desta verificação aceitava só 44 e reprovava a chave de
#: 50 dígitos de um contrato de manutenção predial — um validador que acusa
#: dado correto é pior que validador nenhum, porque desloca a suspeita para o
#: lado errado.
_TAMANHOS_CHAVE = {44: "NF-e", 50: "NFS-e (padrão nacional)"}


def _classificar_chave(valor: Any) -> tuple[str | None, str | None]:
    """Devolve ``(chave, problema)``, sem descartar nem validar em silêncio.

    Medido em 2026-08-27, contrato ``32479123000143-2-000050/2024``: das oito
    notas registradas, SEIS traziam em ``chaveNFe`` cadeias de nove caracteres
    (``2WRK-X5JV``, ``BLYD-PKZ2``, ``NUTS-UTAS``, ...), que não são chave de
    acesso de documento fiscal algum. As duas de 2026 traziam chave de 50
    dígitos, válida para NFS-e.

    O PNCP aceita e devolve o conteúdo como está. Repassá-lo em ``chave_nfe``
    sem qualificação levaria quem consome a tratá-lo como chave e a falhar
    adiante, longe daqui. Devolver ``None`` seria pior: apagaria o fato de que
    HÁ conteúdo cadastrado, apenas inválido — que é justamente o achado.
    """
    if valor is None:
        return None, None
    texto = str(valor).strip()
    if not texto:
        return None, None
    if texto.isdigit() and len(texto) in _TAMANHOS_CHAVE:
        return texto, None
    esperados = ", ".join(f"{n} ({m})" for n, m in sorted(_TAMANHOS_CHAVE.items()))
    return texto, (
        f"valor cadastrado em chaveNFe não é chave de acesso válida "
        f"({len(texto)} caracteres; esperado {esperados})"
    )


def _extrair_nota_do_envelope(bruto: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Extrai a NF-e de ``jsonResponseNFe``, que é uma STRING contendo JSON.

    Não é objeto aninhado: o PNCP guarda a resposta da consulta à NF-e
    serializada como texto. Versões anteriores procuravam ``notaFiscal`` e
    ``itensNotaFiscal`` como chaves do objeto externo, onde nunca estiveram —
    e por isso devolviam ``None`` mesmo quando houvesse conteúdo.

    Devolve ``(nota, problema)``. O ``problema`` distingue os três casos que
    de outro modo se apresentam identicamente como "sem nota":
    ausência de envelope, envelope ilegível e envelope presente porém vazio.
    """
    envelope_texto = bruto.get("jsonResponseNFe")
    status = bruto.get("statusResponseNFe")

    if not envelope_texto:
        return None, None

    try:
        envelope = json.loads(envelope_texto)
    except (TypeError, ValueError):
        return None, "jsonResponseNFe presente, mas não é JSON legível"

    if not isinstance(envelope, dict):
        return None, "jsonResponseNFe não é um objeto"

    nota = envelope.get("notaFiscalDTO")
    itens = envelope.get("itensNotaFiscal")
    eventos = envelope.get("eventosNotaFiscal")

    if nota is None and not itens and not eventos:
        # O caso observado em 100% das medições de 2026-08-27. O status diz
        # 200 e o conteúdo é nulo: sucesso aparente sem dado. Precisa ser
        # dito, senão se lê como "esta nota não tem itens".
        return None, (
            f"o PNCP registrou a consulta à NF-e com statusResponseNFe={status!r}, "
            "mas devolveu notaFiscalDTO, itensNotaFiscal e eventosNotaFiscal nulos — "
            "os itens da nota NÃO estão disponíveis nesta origem"
        )

    if nota is None:
        nota = {}
    if itens:
        nota.setdefault("itensNotaFiscal", itens)
    if eventos:
        nota.setdefault("eventosNotaFiscal", eventos)
    return nota, None


def _formatar_instrumento(bruto: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    tipo = bruto.get("tipoInstrumentoCobranca") or bruto.get("tipoInstrumento") or {}
    # Nomes conferidos contra resposta real em 2026-08-27. Os anteriores
    # (`dataEmissao`, `chaveNfe`) não existem: a API usa
    # `dataEmissaoDocumento` e `chaveNFe` — esta com "NF" maiúsculo, e a
    # busca era sensível a caixa. O efeito era um campo nulo ao lado de um
    # dado presente, indistinguível de ausência real no cadastro.
    chave, problema_chave = _classificar_chave(
        bruto.get("chaveNFe") or bruto.get("chaveAcesso") or bruto.get("chaveNfe")
    )
    nota_bruta = bruto.get("notaFiscalEletronica") or bruto.get("notaFiscal")
    problema_nota = None
    if nota_bruta is None:
        nota_bruta, problema_nota = _extrair_nota_do_envelope(bruto)

    formatado = {
        "tipo_instrumento": {"id": tipo.get("id"), "nome": tipo.get("nome")},
        "numero": bruto.get("numeroInstrumentoCobranca") or bruto.get("numero"),
        "data_emissao": bruto.get("dataEmissaoDocumento") or bruto.get("dataEmissao"),
        "chave_nfe": chave,
        "nota_fiscal": _formatar_nota_fiscal(nota_bruta),
    }
    problemas = [p for p in (problema_chave, problema_nota) if p]
    if problemas:
        formatado["problemas"] = problemas
    if incluir_bruto:
        formatado["dados_originais"] = bruto
    return formatado


async def consultar_notas_fiscais(
    numero_controle_pncp_contrato: str | None = None,
    cnpj_orgao: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    pagina: int = 1,
    limite: int = 100,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Consulta notas fiscais eletrônicas (itemizadas) ligadas a instrumentos de cobrança do PNCP.

    Ver docstring do módulo para a fonte (instrumentos de cobrança do PNCP,
    achados 3.1/4.3), o uso pretendido (auditoria pós-contratual, não
    pesquisa de preços primária) e a ressalva sobre o schema não confirmado
    ao vivo nesta versão.

    Identifique a busca de uma das duas formas:

    1. ``numero_controle_pncp_contrato``: contrato já conhecido (formato
       ``CNPJ-2-SEQUENCIAL/ANO``, mesmo campo devolvido por
       ``consultar_contratos_orgao_pncp``/``consultar_familia_contratacao_pncp``)
       — consulta direta, sem varrer período; **ou**
    2. ``data_inicio``/``data_fim`` (``AAAAMMDD``, ambos obrigatórios juntos):
       varre um período, opcionalmente filtrado por ``cnpj_orgao``.

    Args:
        numero_controle_pncp_contrato: Número de controle completo do
            contrato (ver acima). Se informado, ``data_inicio``/``data_fim``/
            ``cnpj_orgao`` são ignorados.
        cnpj_orgao: CNPJ do órgão (14 dígitos), opcional — só usado no modo
            por período.
        data_inicio: Início do período de inclusão do instrumento de
            cobrança (``AAAAMMDD``) — obrigatório no modo por período.
        data_fim: Fim do período (``AAAAMMDD``) — obrigatório no modo por
            período.
        pagina: Página dos resultados (padrão 1).
        limite: Número máximo de instrumentos de cobrança a devolver nesta
            página (padrão 100, **máximo 100** — teto real da API).

    Returns:
        Dicionário com ``modo`` (``"por_contrato"`` ou ``"por_periodo"``),
        ``pagina``, ``quantidade_retornada``, ``total_no_periodo`` (só
        preenchido de fato no modo por período — a API de contrato não expõe
        um total agregado), ``instrumentos_cobranca`` (cada um com
        ``tipo_instrumento``, ``numero``, ``data_emissao``, ``chave_nfe`` e
        ``nota_fiscal`` — ``None`` quando o instrumento de cobrança não é uma
        NF-e ou não tem nota vinculada; quando presente, traz ``itens`` e
        ``eventos`` da nota) e ``avisos`` — sempre incluindo o aviso fixo
        metodológico (ver docstring do módulo).

    Raises:
        ValueError: nenhum dos dois modos foi informado corretamente
            (``numero_controle_pncp_contrato`` ausente E ``data_inicio``/
            ``data_fim`` ausentes), ou ``numero_controle_pncp_contrato`` em
            formato inválido.
    """
    limite = max(1, min(limite, _LIMITE_MAXIMO))
    pagina = max(1, pagina)
    avisos: list[str] = [_AVISO_METODOLOGICO]

    if numero_controle_pncp_contrato:
        parsed = parse_numero_controle_pncp(numero_controle_pncp_contrato)
        if not parsed:
            raise ValueError(
                "numero_controle_pncp_contrato em formato inválido — esperado "
                "CNPJ-2-SEQUENCIAL/ANO"
            )
        cnpj, ano, sequencial = parsed
        modo = "por_contrato"
        logger.info(
            "consultar_notas_fiscais modo=por_contrato cnpj=%s ano=%s sequencial=%s pagina=%s",
            cnpj, ano, sequencial, pagina,
        )
        brutos = await pncp_client.consultar_instrumentos_cobranca_contrato(
            cnpj, ano, sequencial, pagina=pagina, tamanho_pagina=limite,
        )
        total_no_periodo = len(brutos)
    else:
        if not data_inicio or not data_fim:
            raise ValueError(
                "informe numero_controle_pncp_contrato (busca por contrato conhecido) OU "
                "data_inicio E data_fim (AAAAMMDD, busca por período+órgão)"
            )
        modo = "por_periodo"
        logger.info(
            "consultar_notas_fiscais modo=por_periodo periodo=%s..%s cnpj_orgao=%s pagina=%s",
            data_inicio, data_fim, cnpj_orgao, pagina,
        )
        resposta = await pncp_client.consultar_instrumentos_cobranca_periodo(
            data_inicial=data_inicio, data_final=data_fim, cnpj_orgao=cnpj_orgao,
            pagina=pagina, tamanho_pagina=limite,
        )
        brutos = (resposta or {}).get("data", []) or []
        total_no_periodo = (resposta or {}).get("totalRegistros", len(brutos)) or 0

    instrumentos = [_formatar_instrumento(i, incluir_bruto) for i in brutos[:limite]]

    if total_no_periodo > len(instrumentos):
        avisos.append(
            f"O PNCP encontrou {total_no_periodo} instrumento(s) de cobrança com os "
            f"filtros informados, mas só {len(instrumentos)} foram retornados nesta "
            f"página (limite={limite}). Use pagina para avançar."
        )
    if not instrumentos:
        avisos.append("Nenhum instrumento de cobrança encontrado com os filtros informados.")

    return {
        "modo": modo,
        "pagina": pagina,
        "quantidade_retornada": len(instrumentos),
        "total_no_periodo": total_no_periodo,
        "instrumentos_cobranca": instrumentos,
        "avisos": avisos,
    }
