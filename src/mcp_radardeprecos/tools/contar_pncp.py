"""Tool MCP: contagem agregada no índice do PNCP, sem exigir termo de busca.

Por que esta tool existe
------------------------
``buscar_pncp_texto`` exige ``termo_busca``. Para *contar* — "quantas
contratações de 2026 têm emenda parlamentar?" — isso é um obstáculo, e um
obstáculo que produz resposta errada em vez de erro: escolhe-se um termo
genérico só para "destravar" a consulta, o termo restringe o conjunto, e o
total resultante é o do termo, não o do país. Foi assim que uma apuração
sobre ``possui_emenda_parlamentar`` chegou a ``total = 0`` em 2026, número
incompatível com casos já identificados na mão.

**MEDIDO em 2026-09-07:** ``/api/search`` **não exige** ``q``. Omitindo o
parâmetro (ou enviando-o vazio) o índice devolve o universo filtrado:

```
tipos_documento=edital&anos=2026&status=todos            → 951.350
  + possui_emenda_parlamentar=true                       →     107
  + possui_emenda_parlamentar=false                      →   7.224
```

O booleano é, na prática, de três estados
------------------------------------------
Note que ``107 + 7.224 = 7.331``, muito longe de 951.350. Os outros
**944.019 registros têm o campo ``null``** — confirmado lendo os registros:
na população geral ``possui_emenda_parlamentar`` vem ``null``; no recorte
com ``=true`` vem ``true``.

Isto é a coisa mais importante desta tool, e a razão de ela nunca devolver
um número sozinho. ``false`` **não** significa "todos os que não têm emenda":
significa "os que foram explicitamente marcados como sem emenda". Quem
subtrai ``true`` do total para obter "sem emenda" erra por dois ordens de
grandeza, e quem lê ``false`` como complemento de ``true`` erra também.

A proporção de nulos varia de forma extrema por campo e por tipo de
documento — não há uma regra que dispense medir (MEDIDO 2026-09-07, ano 2026,
``status=todos``):

======================================  ========  =======  ==========
Campo / tipo                            true      false    null
======================================  ========  =======  ==========
edital / possui_emenda_parlamentar           107    7.224     944.019
contrato / possui_emenda_parlamentar         157   14.579   1.230.337
ata / possui_emenda_parlamentar                0        1     280.484
edital / exigencia_conteudo_nacional         389  943.193       7.768
contrato / exigencia_conteudo_nacional         0        0   1.245.073
ata / permite_adesao                      90.378  108.731      81.376
edital / permite_adesao                        0       19     951.331
======================================  ========  =======  ==========

Repare em ``edital / exigencia_conteudo_nacional``: ali o predominante é
``false``, e não o nulo — o inverso do caso da emenda. E em
``contrato / exigencia_conteudo_nacional``, onde o filtro é aceito mas
**não há dado algum**: uma consulta com ``=true`` devolve zero, e esse zero
não diz nada sobre a realidade, só sobre o preenchimento do índice.

Duas armadilhas do endpoint, também medidas
--------------------------------------------
- **Nome de parâmetro errado é ignorado em silêncio.** ``emenda_parlamentar``
  (sem ``possui_``) devolve o total não filtrado — 951.350, idêntico ao
  controle com um parâmetro inventado. Nenhum erro.
- **Valor não booleano devolve HTTP 204.** ``possui_emenda_parlamentar=talvez``
  responde 204 No Content, não 400. Por isso esta tool aceita apenas ``bool``
  do lado Python e nunca repassa texto livre.
"""
from __future__ import annotations

from typing import Any

from ..clients import pncp_client
from ..domain.dominios import MODALIDADES_PNCP, TIPOS_DOCUMENTO_BUSCA_PNCP
from ..logging_utils import get_logger

logger = get_logger(__name__)

#: Os três filtros booleanos do índice. Não aparecem em ``/api/search/filters``
#: (que só lista campos categóricos), então não há como descobri-los por
#: introspecção — daí estarem enumerados aqui.
CAMPOS_BOOLEANOS: tuple[str, ...] = (
    "possui_emenda_parlamentar",
    "exigencia_conteudo_nacional",
    "permite_adesao",
)

_AVISO_TRIESTADO = (
    "IMPORTANTE — este campo tem TRÊS estados no índice: true, false e "
    "AUSENTE (null). 'false' significa 'marcado explicitamente como não', "
    "NÃO 'todo o resto'. Não subtraia true do total para obter os demais: o "
    "resultado seria o número de registros sem informação, não o de "
    "registros sem a característica."
)

_AVISO_COBERTURA_BAIXA = (
    "COBERTURA BAIXA: menos de 10% dos registros deste recorte têm o campo "
    "preenchido. Qualquer proporção calculada sobre true/false descreve a "
    "minoria preenchida, não o universo. Um total baixo aqui pode significar "
    "'poucos casos' ou 'campo pouco preenchido' — são coisas diferentes e "
    "esta contagem não distingue as duas."
)

_AVISO_SEM_DADO = (
    "SEM DADO: nenhum registro deste recorte tem o campo preenchido (nem "
    "true nem false). O filtro é aceito pelo endpoint, mas não há o que "
    "filtrar. Zero aqui não é uma afirmação sobre a realidade — é ausência "
    "de preenchimento no índice."
)

_AVISO_CONTAGEM = (
    "Contagem obtida do índice de busca do PNCP (o mesmo que alimenta o site), "
    "não da API de consulta oficial. Reflete o que está indexado no momento da "
    "chamada."
)


async def contar_pncp(
    tipo_documento: str,
    termo_busca: str | None = None,
    detalhar_campo: str | None = None,
    uf: str | None = None,
    municipio: str | None = None,
    modalidade: int | None = None,
    ano: int | str | None = None,
    tipo_instrumento: int | None = None,
    tipo_contrato: int | None = None,
    orgao: str | None = None,
    unidade: str | None = None,
    esfera: str | None = None,
    poder: str | None = None,
    fonte_orcamentaria: str | None = None,
    tipo_margem_preferencia: str | None = None,
    exigencia_conteudo_nacional: bool | None = None,
    possui_emenda_parlamentar: bool | None = None,
    permite_adesao: bool | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Conta registros no índice do PNCP sem precisar de termo de busca.

    Responde a perguntas de volume — "quantos editais de 2026 no Paraná?",
    "quantas contratações com emenda parlamentar?" — que ``buscar_pncp_texto``
    não responde bem, porque lá o termo é obrigatório e todo termo restringe.

    **Não devolve registros**, só contagens. Para ver os documentos, use
    ``buscar_pncp_texto`` com os mesmos filtros.

    Args:
        tipo_documento: "edital", "ata" ou "contrato".
        termo_busca: Opcional. Omita para contar o universo filtrado. Informe
            apenas se quiser a contagem *dentro* de um termo — e lembre que
            o casamento textual do índice é por prefixo e não se limita à
            descrição exibida (ver ``buscar_pncp_texto``).
        detalhar_campo: Um de ``possui_emenda_parlamentar``,
            ``exigencia_conteudo_nacional`` ou ``permite_adesao``. Quando
            informado, devolve a decomposição em ``true``/``false``/``ausente``
            para o recorte, em vez de um total único. É o caminho correto
            para perguntas do tipo "quantos têm emenda parlamentar?", porque
            expõe quantos registros simplesmente não têm a informação.
        uf, municipio, modalidade, ano, tipo_instrumento, tipo_contrato,
        orgao, unidade, esfera, poder, fonte_orcamentaria,
        tipo_margem_preferencia, status: Mesmos filtros de
            ``buscar_pncp_texto``, um valor por chamada (o índice não combina
            múltiplos valores do mesmo filtro como OR).
        exigencia_conteudo_nacional, possui_emenda_parlamentar,
        permite_adesao: Filtros booleanos aplicados ao recorte. Se você quer
            a *decomposição* de um deles, use ``detalhar_campo`` em vez de
            fixar o valor aqui.

    Returns:
        Sem ``detalhar_campo``: ``{"total": int, "filtros": {...},
        "avisos": [...]}``.

        Com ``detalhar_campo``: acrescenta ``detalhe`` com ``campo``,
        ``true``, ``false``, ``ausente``, ``total``,
        ``percentual_preenchido`` e ``percentual_true_entre_preenchidos`` —
        este último calculado sobre os preenchidos, e não sobre o total,
        porque a proporção sobre o total misturaria "não tem" com "não se
        sabe".

    Raises:
        ValueError: tipo de documento, modalidade ou ``detalhar_campo``
            inválidos.
    """
    if tipo_documento not in TIPOS_DOCUMENTO_BUSCA_PNCP:
        raise ValueError(f"tipo_documento deve ser um de {TIPOS_DOCUMENTO_BUSCA_PNCP}")
    if modalidade is not None and modalidade not in MODALIDADES_PNCP:
        raise ValueError(
            f"modalidade {modalidade} desconhecida. Códigos válidos: "
            f"{sorted(MODALIDADES_PNCP)} (ver listar_filtros_pncp para nomes)."
        )
    if detalhar_campo is not None and detalhar_campo not in CAMPOS_BOOLEANOS:
        raise ValueError(
            f"detalhar_campo deve ser um de {list(CAMPOS_BOOLEANOS)} — são os "
            "únicos filtros booleanos do índice. Note que eles NÃO aparecem "
            "em listar_filtros_pncp, que só lista campos categóricos."
        )

    logger.info(
        "contar_pncp tipo=%s termo=%r detalhar=%s ano=%s uf=%s status=%s",
        tipo_documento, termo_busca, detalhar_campo, ano, uf, status,
    )

    comuns: dict[str, Any] = {
        "tipo_documento": tipo_documento,
        "uf": uf,
        "municipio": municipio,
        "modalidade": modalidade,
        "ano": int(ano) if ano is not None else None,
        "tipo_instrumento": tipo_instrumento,
        "tipo_contrato": tipo_contrato,
        "orgao": orgao,
        "unidade": unidade,
        "esfera": esfera,
        "poder": poder,
        "fonte_orcamentaria": fonte_orcamentaria,
        "tipo_margem_preferencia": tipo_margem_preferencia,
        "status": status,
        "exigencia_conteudo_nacional": exigencia_conteudo_nacional,
        "possui_emenda_parlamentar": possui_emenda_parlamentar,
        "permite_adesao": permite_adesao,
    }
    # O termo entra como string vazia quando ausente: medido em 2026-09-07,
    # `q=` e a omissão de `q` devolvem o mesmo total (951.350 para editais de
    # 2026), então não é preciso um caminho separado no cliente.
    base_termo = termo_busca or ""

    async def total_com(**overrides: Any) -> int:
        """Uma chamada ao índice pedindo só o total.

        ``tam_pagina=1`` porque o endpoint não tem modo "somente contagem" —
        e ``tam_pagina=0`` não foi testado, então não se usa.
        """
        resposta = await pncp_client.buscar_texto(
            base_termo, pagina=1, tamanho_pagina=1, **{**comuns, **overrides}
        )
        return int((resposta or {}).get("total") or 0)

    filtros_ecoados = {k: v for k, v in comuns.items() if v is not None}
    if termo_busca:
        filtros_ecoados["termo_busca"] = termo_busca

    resultado: dict[str, Any] = {
        "filtros": filtros_ecoados,
        "avisos": [_AVISO_CONTAGEM],
    }

    if detalhar_campo is None:
        resultado["total"] = await total_com()
        return resultado

    # Decomposição: o total do recorte SEM o booleano fixado, mais os dois
    # valores. O `ausente` é derivado por subtração, e não consultado, porque
    # o endpoint não oferece um "is null".
    sem_o_campo = {detalhar_campo: None}
    total = await total_com(**sem_o_campo)
    n_true = await total_com(**{detalhar_campo: True})
    n_false = await total_com(**{detalhar_campo: False})
    preenchidos = n_true + n_false
    ausente = total - preenchidos

    detalhe: dict[str, Any] = {
        "campo": detalhar_campo,
        "total": total,
        "true": n_true,
        "false": n_false,
        "ausente": ausente,
        "percentual_preenchido": round(100 * preenchidos / total, 2) if total else None,
        "percentual_true_entre_preenchidos": (
            round(100 * n_true / preenchidos, 2) if preenchidos else None
        ),
    }
    resultado["detalhe"] = detalhe
    resultado["total"] = total
    resultado["avisos"].append(_AVISO_TRIESTADO)
    if preenchidos == 0:
        resultado["avisos"].append(_AVISO_SEM_DADO)
    elif total and preenchidos / total < 0.10:
        resultado["avisos"].append(_AVISO_COBERTURA_BAIXA)
    if ausente < 0:
        # Nunca observado, mas se acontecer é sinal de que o índice mudou
        # entre as três chamadas (elas não são atômicas) — melhor dizer do
        # que devolver um negativo sem explicação.
        resultado["avisos"].append(
            "INCONSISTÊNCIA: true + false excedeu o total. As três contagens "
            "são chamadas separadas e o índice pode ter mudado entre elas. "
            "Repita a consulta."
        )
    return resultado
