"""Tool MCP: busca preços praticados no setor público (Compras.gov.br)."""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any

from ..clients import compras_client
from ..config import settings
from ..domain import cobertura as cobertura_mod
from ..domain.cobertura import MotivoInterrupcao, StatusCobertura
from ..domain.dominios import TIPOS_ITEM_CATALOGO_COMPRAS
from ..logging_utils import get_logger
from ..utils.documentos import mascarar_documento
from ..utils.numeros import identificador
from ..utils.paginacao import extrair_paginacao

logger = get_logger(__name__)

#: Menor tamanho de página aceito pelo Compras.gov.br — o mesmo piso que
#: `compras_client` aplica (`max(10, ...)`). Fica explícito aqui para que a
#: tool e o cliente não voltem a discordar sobre a faixa válida de `limite`.
_LIMITE_MINIMO_DA_FONTE = 10


def _formatar_preco(r: dict[str, Any], incluir_bruto: bool = False) -> dict[str, Any]:
    """Formata um registro de preço praticado do Compras.gov.br.

    **Unidade de fornecimento:** o endpoint devolve, por registro,
    a unidade em que o preço foi praticado — ``siglaUnidadeFornecimento``,
    ``nomeUnidadeFornecimento`` (ex.: "PACOTE", "UNIDADE", "CAIXA") e
    ``capacidadeUnidadeFornecimento`` (ex.: "50 UN"), além da unidade de
    medida de base. Estes campos eram DESCARTADOS até a v0.4.6, o que
    tornava invisível a diferença entre "R$ 0,60 a unidade" e "R$ 0,60 o
    pacote com 50" — preços que o mesmo código de catálogo mistura sem
    qualquer sinalização. Sem eles, qualquer estatística sobre a série
    agrega grandezas incomensuráveis e produz precisão aparente: o preço
    de referência converge com desvio baixo justamente porque descarta os
    valores discrepantes que denunciariam a mistura.

    ``pdm`` (família de produto) e ``classe`` são os eixos de agrupamento
    do catálogo, e ``criterio_julgamento`` distingue preço por valor de
    preço por desconto (nesse caso ``percentualMaiorDesconto`` é o que
    define o resultado, e o unitário isolado engana).
    """
    formatado = {
        "preco_unitario": r.get("precoUnitario"),
        "quantidade": r.get("quantidade"),
        "unidade_fornecimento": {
            "sigla": r.get("siglaUnidadeFornecimento"),
            "nome": r.get("nomeUnidadeFornecimento"),
            "capacidade": r.get("capacidadeUnidadeFornecimento"),
        },
        "unidade_medida": {
            "sigla": r.get("siglaUnidadeMedida"),
            "nome": r.get("nomeUnidadeMedida"),
        },
        "fornecedor": {
            "cnpj": mascarar_documento(r.get("niFornecedor")),
            "nome": r.get("nomeFornecedor"),
        },
        "marca": r.get("marca"),
        "orgao": r.get("nomeOrgao"),
        "uasg": {
            "codigo": r.get("codigoUasg"),
            "nome": r.get("nomeUasg"),
        },
        "uf": r.get("estado"),
        "municipio": r.get("municipio"),
        "data_resultado": r.get("dataResultado"),
        "descricao_item": r.get("descricaoDetalhadaItem") or r.get("descricaoItem"),
        "pdm": {
            "codigo": r.get("codigoPdm"),
            "nome": r.get("nomePdm"),
        },
        "classe": {
            "codigo": r.get("codigoClasse"),
            "nome": r.get("nomeClasse"),
        },
        "criterio_julgamento": r.get("criterioJulgamento"),
        "percentual_maior_desconto": r.get("percentualMaiorDesconto"),
        "id_compra": identificador(r.get("idCompra")),
    }
    if incluir_bruto:
        formatado["dados_originais"] = r
    return formatado


def _texto(valor: Any) -> str:
    """Converte para texto sem presumir o tipo que a origem devolveu.

    A API do Compras.gov.br não é consistente quanto ao tipo dos campos de
    unidade de fornecimento: ``capacidade`` chega como texto na maioria dos
    itens e como NÚMERO em outros — medido em 2026-09-04 nos CATMAT 267203 e
    268252 (dipirona sódica), que derrubavam a ferramenta inteira com
    ``'float' object has no attribute 'strip'``.

    O erro era pior do que uma exceção comum: a ferramenta falhava por
    completo para o item, e a mensagem não dizia qual campo tinha o tipo
    inesperado — só o tipo. Converter aqui, num lugar só, evita que a mesma
    suposição seja refeita a cada campo novo.
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, float) and valor.is_integer():
        # 200.0 vira "200", não "200.0" — o rótulo é lido por pessoas, e a
        # casa decimal vazia sugere precisão que a origem não declarou.
        return str(int(valor))
    return str(valor).strip()


def _capacidade_texto(valor: Any) -> str:
    """Capacidade como texto, tratando ZERO como ausência.

    A origem usa ``capacidade: 0`` para unidades que não têm capacidade —
    "UNIDADE", "SERVIÇO" e afins. O rótulo dessas precisa ser "UNIDADE", e
    não "UNIDADE 0": o zero não distingue nada e, incluído, criaria um balde
    de agrupamento diferente para a mesma unidade.

    Até 2026-09-04 esse comportamento vinha por acidente — ``0 or ""``
    devolve ``""`` porque zero é falso em Python. O acidente também
    mascarava o defeito de tipo: itens com capacidade real (ampola de 200,
    caixa com 45) chegavam como número e derrubavam a ferramenta, enquanto
    os de capacidade zero passavam. Ou seja, o erro se escondia justamente
    onde o campo é irrelevante e disparava justamente onde ele é essencial
    para julgar comparabilidade.
    """
    if isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor == 0:
        return ""
    return _texto(valor)


def _rotulo_unidade(preco: dict[str, Any]) -> str | None:
    """Rótulo curto da unidade de fornecimento, para agrupar a série.

    Combina nome/sigla com a capacidade porque "PACOTE" sozinho não
    distingue pacote com 50 de pacote com 100 — a capacidade é parte da
    identidade da unidade, não um detalhe.

    Devolve ``None`` quando a unidade é **desconhecida**, e não uma string
    como "(unidade não informada)". A diferença decide o resultado: enquanto
    o desconhecido era um rótulo, uma série inteira sem unidade produzia UM
    rótulo repetido, portanto ``unidades_distintas: 1`` e
    ``serie_homogenea: true`` — ausência total de informação apresentada como
    uniformidade. Ver :func:`resumir_unidades`.

    Em SERVIÇOS (CATSER) ``unidade_fornecimento`` vem nulo e a unidade real
    está em ``unidade_medida``: medido em 07/09/2026 no CATSER 26077 (SaaS),
    cuja série trazia ``UN``, ``UST`` e ``USN`` e era declarada homogênea.
    """
    for campo in ("unidade_fornecimento", "unidade_medida"):
        rotulo = _rotulo_de_campo(preco.get(campo))
        if rotulo:
            return rotulo
    return None


def _rotulo_de_campo(unidade: Any) -> str | None:
    """Rótulo de um campo de unidade, ou ``None`` se não houver informação."""
    if unidade is None:
        return None
    if not isinstance(unidade, dict):
        # A origem já devolveu a unidade como texto puro em alguns itens.
        return _texto(unidade) or None
    nome = _texto(unidade.get("nome") or unidade.get("sigla"))
    capacidade = _capacidade_texto(unidade.get("capacidade"))
    if not nome and not capacidade:
        return None
    return " ".join(parte for parte in (nome, capacidade) if parte)


def resumir_unidades(precos: list[dict[str, Any]]) -> dict[str, Any]:
    """Conta os preços por unidade de fornecimento e sinaliza mistura.

    Serve de trava metodológica ANTES do cálculo: se a série tem mais de
    uma unidade, ela não é uma amostra de um preço só, e média/mediana
    sobre ela não têm significado — é preciso separar por unidade (ou
    normalizar para uma base comum) antes de estimar.
    """
    contagem: dict[str, int] = {}
    sem_unidade = 0
    for preco in precos:
        rotulo = _rotulo_unidade(preco)
        if rotulo is None:
            sem_unidade += 1
            continue
        contagem[rotulo] = contagem.get(rotulo, 0) + 1
    ordenado = dict(sorted(contagem.items(), key=lambda par: (-par[1], par[0])))

    # `serie_homogenea` tem TRÊS estados, e o terceiro é o que importa:
    #
    #   True   — exatamente uma unidade conhecida, e nenhum registro sem
    #            unidade. Só aqui se pode calcular média/mediana direto.
    #   False  — mais de uma unidade conhecida. Mistura comprovada.
    #   None   — há registros sem unidade informada. NÃO se sabe se a série é
    #            homogênea, e afirmar que é seria inventar.
    #
    # Até a v0.5.4 o desconhecido virava o rótulo "(unidade não informada)" e
    # entrava na contagem, de modo que uma série inteiramente sem unidade
    # saía com `unidades_distintas: 1` e `serie_homogenea: true`.
    if sem_unidade:
        homogenea: bool | None = None
    else:
        homogenea = len(ordenado) <= 1

    resultado: dict[str, Any] = {
        "unidades_distintas": len(ordenado),
        "contagem_por_unidade": ordenado,
        "serie_homogenea": homogenea,
    }
    if sem_unidade:
        resultado["registros_sem_unidade"] = sem_unidade
    return resultado


async def buscar_precos_praticados_compras(
    codigo_item_catalogo: int,
    tipo_item: str,
    tipo_codigo: str = "codigoItemCatalogo",
    uf: str | None = None,
    codigo_municipio: int | None = None,
    codigo_uasg: str | None = None,
    apenas_com_resultado: bool = True,
    limite: int = 20,
    pagina: int = 1,
    data_compra_inicio: str | None = None,
    data_compra_fim: str | None = None,
    poder: str | None = None,
    esfera: str | None = None,
    buscar_todas_paginas: bool = False,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Busca preços praticados no setor público para um item de catálogo (CATMAT/CATSER).

    Consulta o módulo "Pesquisa de Preço" do Compras.gov.br — a fonte que a
    IN SEGES/ME 65/2021 prioriza **acima de qualquer outra** na pesquisa de
    preços (preços efetivamente praticados em compras públicas já
    realizadas). Os resultados já vêm prontos
    para alimentar ``calcular_preco_referencia``.

    **Pré-requisito:** ``codigo_item_catalogo`` é o código do item no
    catálogo CATMAT (materiais) ou CATSER (serviços) do Compras.gov.br —
    não é o número de item de uma contratação específica do PNCP. Para
    descobrir esse código a partir de uma descrição em texto livre (ex.:
    "notebook"), use a tool ``descobrir_codigo_catalogo`` deste servidor.

    **Achado real (2026-07-10): a API NÃO garante ordenação por data** —
    confirmado ao vivo pelo usuário (``codigo_item_catalogo=27332``,
    859 registros no total): a primeira página trouxe uma mistura de datas,
    incluindo registros de dezembro/2025 misturados com julho/2026, então
    filtrar por período olhando só a página 1 pode perder registros dentro
    da janela desejada que caíram em páginas posteriores. Para uma pesquisa
    exaustiva (ex.: "todos os preços praticados nos últimos 6 meses"),
    itere ``pagina`` (1, 2, 3, ...) até ``pagina * limite >= total_encontrado``
    (ou até ``precos`` vir vazio), consolide os resultados de todas as
    páginas e só então filtre por data no lado do cliente — não confie na
    ordem retornada pela API.

    Args:
        codigo_item_catalogo: Código do item no catálogo CATMAT ou CATSER.
        tipo_item: "material" (CATMAT) ou "servico" (CATSER) — determina
            qual endpoint é consultado.
        tipo_codigo: SÓ para material — diz se ``codigo_item_catalogo`` é um
            código de ITEM (``"codigoItemCatalogo"``, padrão) ou de PDM
            (``"codigoPdm"``, a "família de produto"). A API de material passou
            a exigir esse discriminador (mudança de 2026-07). Serviço não tem
            PDM, então só aceita ``"codigoItemCatalogo"`` — passar
            ``"codigoPdm"`` com serviço é erro de validação. Observação: passar
            um código de PDM no modo ITEM (ou vice-versa) devolve zero
            registros, sem erro.
        uf: Sigla da UF para filtrar (ex: SP, DF).
        codigo_municipio: Código IBGE do município para filtrar.
        codigo_uasg: Código da UASG (unidade administrativa) para filtrar.
        apenas_com_resultado: Se True (padrão), retorna somente registros
            com data de resultado preenchida — ou seja, compras já
            concluídas, com preço efetivamente pago (não estimativas em
            andamento). Corresponde ao parâmetro ``dataResultado`` da API.
        limite: Número de registros por página (padrão 20, máximo 100 —
            teto do lado da tool para manter a resposta pequena; a API em si
            aceita até 500, confirmado ao vivo). Ajusta o tamanho de página
            da API diretamente, tanto para "material" quanto para "servico"
            (achado real de 2026-07-10, corrige suposição anterior de que
            "servico" não aceitava tamanho de página customizado).
        pagina: Número da página a buscar, 1-indexado (padrão 1). Ignorado
            (com aviso) quando ``buscar_todas_paginas=True``.
        data_compra_inicio: Recorte por data da compra (YYYY-MM-DD), aplicado
            NO SERVIDOR (v0.2.1, conforme spec oficial) — mitiga a
            não-ordenação por data do achado v0.1.49 na origem.
        data_compra_fim: Fim do recorte (YYYY-MM-DD).
        poder: "E" (Executivo), "L" (Legislativo) ou "J" (Judiciário) —
            filtro no servidor.
        esfera: "F" (Federal), "E" (Estadual), "M" (Municipal) — filtro no
            servidor.
        buscar_todas_paginas: Se True, varre TODAS as páginas do
            resultado e consolida numa resposta só (necessário para
            pesquisa exaustiva, já que a API não ordena por data): página 1
            sequencial, seguintes em lotes de 5 concorrentes, com teto de
            segurança de 50 páginas e o mesmo orçamento de tempo das
            varreduras do PNCP (RADARDEPRECOS_TOOL_BUDGET_SECONDS) — ao
            estourar qualquer um dos dois, devolve o parcial com aviso.
        incluir_bruto: Se True, cada preço também traz ``dados_originais``
            com os campos exatos e completos da API, sem tradução (padrão
            False — não incluído por padrão para não duplicar o payload à
            toa).

    Returns:
        Dicionário com ``tipo_item``, ``codigo_item_catalogo``, ``pagina``,
        ``total_encontrado`` e ``precos`` — lista de preços praticados, cada
        um com ``preco_unitario``, ``quantidade``, ``unidade_fornecimento``
        (sigla/nome/capacidade), ``unidade_medida`` (sigla/nome),
        ``fornecedor`` (CNPJ/nome), ``marca`` (só para material), ``orgao``,
        ``uasg`` (código/nome), ``uf``, ``municipio``, ``data_resultado``,
        ``descricao_item``, ``pdm`` (código/nome da família de produto),
        ``classe`` (código/nome), ``criterio_julgamento``,
        ``percentual_maior_desconto`` e ``id_compra``.

        Traz também ``unidades`` — ``unidades_distintas``,
        ``contagem_por_unidade`` e ``serie_homogenea``. Quando
        ``serie_homogenea`` é ``False``, a série mistura preços praticados
        em unidades diferentes (ex.: unidade × pacote com 50 × caixa) sob o
        mesmo código de catálogo, e um aviso é emitido: nesse caso média e
        mediana agregam grandezas incomensuráveis, e o preço de referência
        parecerá preciso apenas porque o saneamento descartou a mistura.
        Separe por unidade ou use ``normalizar_precos_unidade`` antes de
        estimar.
    """
    if tipo_item not in TIPOS_ITEM_CATALOGO_COMPRAS:
        raise ValueError(f"tipo_item deve ser um de {TIPOS_ITEM_CATALOGO_COMPRAS}")
    if tipo_codigo not in ("codigoItemCatalogo", "codigoPdm"):
        raise ValueError("tipo_codigo deve ser 'codigoItemCatalogo' ou 'codigoPdm'")
    if tipo_codigo == "codigoPdm" and tipo_item != "material":
        raise ValueError(
            "tipo_codigo='codigoPdm' só se aplica a tipo_item='material' "
            "(serviço não tem PDM)."
        )

    # v0.5.14: o piso é o da FONTE, não uma escolha nossa. O cliente faz
    # `tamanho_pagina = max(10, ...)`, então pedir menos que 10 buscava 10
    # registros e descartava a diferença em silêncio — lidos, pagos e jogados
    # fora. Dois clamps na mesma pilha discordando sobre a faixa válida.
    #
    # A consequência menos óbvia era aritmética: a varredura calcula
    # `ceil(total / limite)` e anuncia "50 páginas (50 × limite registros)".
    # Com `limite` abaixo do piso, esse anúncio descrevia um resultado parcial
    # com um número menor que o real.
    limite_pedido = limite
    limite = max(_LIMITE_MINIMO_DA_FONTE, min(limite, 100))
    # Declarado aqui, e não dentro do ramo de varredura, para que o bloco de
    # cobertura no fim da função possa lê-lo sem `locals()` — busca por nome
    # em tempo de execução falha em silêncio se a variável for renomeada.
    motivo_parada: MotivoInterrupcao | None = None
    pagina = max(1, pagina)
    avisos: list[str] = []
    if limite_pedido < _LIMITE_MINIMO_DA_FONTE:
        avisos.append(
            f"limite={limite_pedido} elevado para {_LIMITE_MINIMO_DA_FONTE}: é o "
            "menor tamanho de página que o Compras.gov.br aceita. Devolver menos "
            "esconderia registros já lidos da fonte."
        )
    if buscar_todas_paginas and pagina != 1:
        avisos.append("pagina é ignorado quando buscar_todas_paginas=True (varredura começa da página 1)")
        pagina = 1
    logger.info(
        "buscar_precos_praticados_compras codigo_item_catalogo=%s tipo_item=%s uf=%s "
        "apenas_com_resultado=%s limite=%s pagina=%s",
        codigo_item_catalogo, tipo_item, uf, apenas_com_resultado, limite, pagina,
    )

    data_resultado = True if apenas_com_resultado else None

    def _consultar(p: int):
        kwargs: dict[str, Any] = dict(
            codigo_uasg=codigo_uasg,
            estado=uf,
            codigo_municipio=codigo_municipio,
            data_resultado=data_resultado,
            data_compra_inicio=data_compra_inicio,
            data_compra_fim=data_compra_fim,
            poder=poder,
            esfera=esfera,
            tamanho_pagina=limite,
            pagina=p,
        )
        if tipo_item == "material":
            # tipo_codigo (Item ou PDM) só existe no endpoint de material.
            return compras_client.consultar_precos_material(
                codigo_item_catalogo, tipo_codigo=tipo_codigo, **kwargs
            )
        return compras_client.consultar_precos_servico(codigo_item_catalogo, **kwargs)

    resposta = await _consultar(pagina)
    registros = (resposta or {}).get("resultado", []) or []
    total_encontrado = (resposta or {}).get("totalRegistros", len(registros))

    if buscar_todas_paginas and total_encontrado > len(registros):
        # Varredura consolidada: a API não ordena por data (achado
        # v0.1.49), então filtrar por período com segurança exige reunir
        # todas as páginas primeiro. Teto de segurança + orçamento de
        # tempo, ambos sinalizados em avisos quando atingidos.
        max_paginas = 50
        lote = 5
        inicio_orc = time.monotonic()
        orcamento = settings.tool_budget_seconds
        ultima = min(max_paginas, math.ceil(total_encontrado / limite))
        proxima = 2
        while proxima <= ultima:
            if orcamento and orcamento > 0 and (time.monotonic() - inicio_orc) >= orcamento:
                avisos.append(
                    f"varredura parou ao atingir o orçamento de tempo de {orcamento:.0f}s "
                    "(RADARDEPRECOS_TOOL_BUDGET_SECONDS) — resultado parcial"
                )
                motivo_parada = MotivoInterrupcao.ORCAMENTO_EXECUCAO
                break
            fim_lote = min(proxima + lote - 1, ultima)
            respostas = await asyncio.gather(
                *(_consultar(pg) for pg in range(proxima, fim_lote + 1))
            )
            for r in respostas:
                registros.extend((r or {}).get("resultado", []) or [])
            proxima = fim_lote + 1
        if ultima >= max_paginas and total_encontrado > max_paginas * limite:
            motivo_parada = MotivoInterrupcao.LIMITE_DE_VARREDURA
            avisos.append(
                f"varredura limitada às primeiras {max_paginas} páginas "
                f"({max_paginas * limite} registros de {total_encontrado}) — refine os "
                "filtros (uf, data_compra_inicio/fim, poder, esfera) para reduzir o universo"
            )

    precos = [
        _formatar_preco(r, incluir_bruto)
        for r in (registros if buscar_todas_paginas else registros[:limite])
    ]

    # campos de paginação padronizados (aditivo,
    # não substitui total_encontrado/pagina já existentes). Em
    # buscar_todas_paginas=True, o envelope de `resposta` reflete só a
    # página 1 original — total_registros/total_paginas continuam válidos
    # (são estatísticas do universo inteiro), mas numero_pagina/
    # paginas_restantes ficariam enganosos (já consolidamos tudo), então são
    # omitidos nesse modo.
    paginacao = extrair_paginacao(resposta)
    if buscar_todas_paginas:
        paginacao.pop("numero_pagina", None)
        paginacao.pop("paginas_restantes", None)

    # Trava metodológica: um mesmo código de catálogo mistura
    # preços praticados em unidades diferentes (unidade, pacote, caixa).
    # Avisar ANTES do cálculo evita a "precisão aparente" de uma média
    # saneada que converge só porque descartou a mistura.
    unidades = resumir_unidades(precos)
    rotulos = ", ".join(
        f"{rotulo} ({qtd})"
        for rotulo, qtd in list(unidades["contagem_por_unidade"].items())[:5]
    )
    if unidades["serie_homogenea"] is False:
        avisos.append(
            f"série NÃO homogênea: {unidades['unidades_distintas']} unidades de "
            f"fornecimento diferentes ({rotulos}) — separe por unidade ou "
            "normalize com normalizar_precos_unidade antes de calcular o preço "
            "de referência; média/mediana sobre unidades distintas não têm "
            "significado."
        )
    elif unidades["serie_homogenea"] is None:
        # Distinto do aviso acima: ali sabe-se que há mistura; aqui não se
        # sabe nada. As duas situações pedem a mesma cautela e por motivos
        # diferentes, e dizer "não homogênea" no segundo caso seria afirmar
        # uma mistura que não foi observada.
        sem = unidades.get("registros_sem_unidade", 0)
        conhecidas = (
            f"As conhecidas são: {rotulos}. " if unidades["unidades_distintas"] else ""
        )
        avisos.append(
            f"homogeneidade INDETERMINADA: {sem} de {len(precos)} preços vieram "
            f"sem unidade informada na fonte. {conhecidas}"
            "Não é possível afirmar que a série mistura unidades, nem que não "
            "mistura — média/mediana aqui carregam esse risco. Confira os "
            "registros sem unidade antes de calcular o preço de referência."
        )

    # `cobertura` estruturado. Duas leituras muito diferentes do
    # mesmo retorno, que só o bloco separa:
    #
    #  - `buscar_todas_paginas=False` devolve UMA página por desenho. Não é
    #    varredura interrompida, é paginação — mas também não autoriza
    #    afirmar inexistência sobre o universo.
    #  - `buscar_todas_paginas=True` percorre até o teto de 50 páginas ou o
    #    orçamento de tempo, e aí sim há um motivo de parada a declarar.
    motivo_cob = motivo_parada if buscar_todas_paginas else None
    if not total_encontrado:
        status_cob = StatusCobertura.VAZIA
    elif motivo_cob is not None:
        status_cob = StatusCobertura.PARCIAL
    elif buscar_todas_paginas or len(precos) >= total_encontrado:
        status_cob = StatusCobertura.EXAUSTIVA
    else:
        status_cob = StatusCobertura.PARCIAL
        motivo_cob = MotivoInterrupcao.LIMITE_DE_VARREDURA

    bloco = cobertura_mod.montar(
        fonte="Compras.gov.br",
        status=status_cob,
        registros_retornados=len(precos),
        registros_examinados=len(registros),
        total_no_universo=total_encontrado,
        motivo=motivo_cob,
    )
    texto_cob = cobertura_mod.aviso(bloco)
    if texto_cob:
        avisos.insert(0, texto_cob)

    return {
        "tipo_item": tipo_item,
        "codigo_item_catalogo": codigo_item_catalogo,
        "tipo_codigo": tipo_codigo,
        "pagina": pagina,
        "total_encontrado": total_encontrado,
        "quantidade_retornada": len(precos),
        "precos": precos,
        "unidades": unidades,
        "cobertura": bloco,
        "avisos": avisos,
        **paginacao,
    }
