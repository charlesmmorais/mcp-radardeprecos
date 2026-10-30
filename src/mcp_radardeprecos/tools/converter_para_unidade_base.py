"""Tool MCP: converte preços praticados para a unidade base do catálogo.

Complementa ``normalizar_precos_unidade`` (que é pura e trata de bases
contratuais — usuário/mês, licença/ano). Aqui o problema é outro e anterior:
o mesmo código de catálogo reúne preços praticados em **unidades de
fornecimento diferentes** — a unidade avulsa, o pacote com 50, a caixa com 45
pacotes. Comparados sem conversão, esses valores não formam uma amostra: são
grandezas incomensuráveis sob um rótulo comum.

A conversão usa a tabela OFICIAL do catálogo (``material/6`` para CATMAT,
``servico/7`` para CATSER), não uma heurística sobre a descrição. O fator sai
da ``capacidadeUnidadeFornecimento`` registrada pelo próprio Compras.gov.br.

Princípio anti-erro-silencioso: quando a capacidade não é interpretável com
segurança (texto ambíguo, faixa, unidade desconhecida), o preço vai para
``nao_convertidos`` com o motivo — nunca se assume fator 1 nem se adivinha.
Um fator errado produz um número que parece rigoroso e não é, que é
precisamente a falha que a normalização existe para evitar.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..clients import compras_client
from ..domain.capacidade import interpretar_capacidade
from ..logging_utils import get_logger

logger = get_logger(__name__)


def _chave_unidade(nome: str | None, sigla: str | None) -> str:
    return (nome or sigla or "").strip().upper()


def _tabela_de_fatores(unidades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Indexa a tabela oficial por nome/sigla da unidade, com o fator lido."""
    tabela: dict[str, dict[str, Any]] = {}
    for unidade in unidades:
        capacidade_txt = unidade.get("capacidadeUnidadeFornecimento")
        capacidade = interpretar_capacidade(capacidade_txt)
        entrada = {
            "sigla": unidade.get("siglaUnidadeFornecimento"),
            "nome": unidade.get("nomeUnidadeFornecimento"),
            "capacidade_texto": capacidade_txt,
            "fator": float(capacidade.fator) if capacidade else None,
            "base": capacidade.base if capacidade else None,
            "unidade_medida": unidade.get("siglaUnidadeMedida"),
        }
        for chave in (
            _chave_unidade(unidade.get("nomeUnidadeFornecimento"), None),
            _chave_unidade(None, unidade.get("siglaUnidadeFornecimento")),
        ):
            if chave:
                tabela.setdefault(chave, entrada)
    return tabela


async def converter_para_unidade_base(
    precos: list[dict[str, Any]],
    tipo_item: str = "material",
    codigo_pdm: int | None = None,
    codigo_servico: int | None = None,
) -> dict[str, Any]:
    """Converte preços praticados para a unidade base, pela tabela do catálogo.

    Consome a saída de ``buscar_precos_praticados_compras`` (cada preço traz
    ``preco_unitario`` e ``unidade_fornecimento``) e divide cada valor pela
    capacidade oficial da sua unidade, deixando todos na mesma base — o passo
    que falta entre coletar e calcular quando a série não é homogênea.

    A tabela de conversão vem do catálogo (cacheada por 1 dia), então o fator
    é rastreável até a fonte: cada linha convertida informa a capacidade
    textual usada e o fator dela extraído.

    **Não converte por adivinhação.** Preço sem unidade informada, unidade
    ausente da tabela oficial, ou capacidade em texto não interpretável
    (ambíguo, faixa, unidade desconhecida) vão para ``nao_convertidos`` com o
    motivo. Cabe a quem chama decidir — ampliar a busca, tratar caso a caso ou
    excluir de forma justificada.

    Args:
        precos: lista de preços de ``buscar_precos_praticados_compras``.
        tipo_item: ``"material"`` (CATMAT, usa ``codigo_pdm``) ou
            ``"servico"`` (CATSER, usa ``codigo_servico``).
        codigo_pdm: código do PDM (família de produto) — obrigatório para
            material. Vem no campo ``pdm.codigo`` dos próprios preços.
        codigo_servico: código CATSER — obrigatório para serviço.

    Returns:
        Dicionário com ``tabela_unidades`` (a tabela oficial usada, com os
        fatores lidos), ``convertidos`` (cada item preserva os campos
        originais e acrescenta ``preco_base``, ``fator_conversao``,
        ``unidade_base``, ``capacidade_usada`` e ``formula``),
        ``precos_base`` (lista de floats pronta para
        ``calcular_preco_referencia``), ``nao_convertidos`` (com ``motivo``)
        e ``avisos``.

    Raises:
        ValueError: se ``tipo_item`` for inválido ou se faltar o código
            correspondente.
    """
    if tipo_item not in ("material", "servico"):
        raise ValueError("tipo_item deve ser 'material' ou 'servico'")
    if tipo_item == "material" and codigo_pdm is None:
        raise ValueError(
            "codigo_pdm é obrigatório para tipo_item='material' — use o campo "
            "'pdm.codigo' devolvido por buscar_precos_praticados_compras."
        )
    if tipo_item == "servico" and codigo_servico is None:
        raise ValueError("codigo_servico é obrigatório para tipo_item='servico'")

    if tipo_item == "material":
        unidades = await compras_client.listar_unidades_fornecimento_material(
            int(codigo_pdm)  # type: ignore[arg-type]
        )
    else:
        unidades = await compras_client.listar_unidades_medida_servico(
            int(codigo_servico)  # type: ignore[arg-type]
        )

    tabela = _tabela_de_fatores(unidades)
    convertidos: list[dict[str, Any]] = []
    nao_convertidos: list[dict[str, Any]] = []

    for preco in precos:
        valor = preco.get("preco_unitario")
        if not isinstance(valor, (int, float)) or valor <= 0:
            nao_convertidos.append({**preco, "motivo": "preço unitário ausente ou não positivo"})
            continue

        unidade = preco.get("unidade_fornecimento") or {}
        chave = _chave_unidade(unidade.get("nome"), unidade.get("sigla"))
        if not chave:
            nao_convertidos.append(
                {**preco, "motivo": "unidade de fornecimento não informada no registro"}
            )
            continue

        entrada = tabela.get(chave)
        if entrada is None:
            nao_convertidos.append(
                {**preco, "motivo": f"unidade {chave!r} não consta na tabela oficial do catálogo"}
            )
            continue

        # Sem capacidade declarada: a própria unidade JÁ é a base (fator 1).
        capacidade_registro = interpretar_capacidade(unidade.get("capacidade"))
        fator_decimal: Decimal | None = None
        capacidade_usada = None
        if capacidade_registro is not None:
            fator_decimal = capacidade_registro.fator
            capacidade_usada = capacidade_registro.texto_original
            base = capacidade_registro.base
        elif entrada["fator"] is not None:
            fator_decimal = Decimal(str(entrada["fator"]))
            capacidade_usada = entrada["capacidade_texto"]
            base = entrada["base"]
        elif not (unidade.get("capacidade") or entrada["capacidade_texto"]):
            fator_decimal = Decimal(1)
            capacidade_usada = None
            base = "unidade"
        else:
            nao_convertidos.append(
                {
                    **preco,
                    "motivo": (
                        "capacidade "
                        f"{unidade.get('capacidade') or entrada['capacidade_texto']!r} "
                        "não pôde ser interpretada com segurança — converter exigiria "
                        "adivinhar o fator"
                    ),
                }
            )
            continue

        preco_base = Decimal(str(valor)) / fator_decimal
        convertidos.append(
            {
                **preco,
                "preco_base": float(round(preco_base, 6)),
                "fator_conversao": float(fator_decimal),
                "unidade_base": base,
                "capacidade_usada": capacidade_usada,
                "formula": f"{valor} / {fator_decimal} = {float(round(preco_base, 6))}",
            }
        )

    avisos: list[str] = []
    if nao_convertidos:
        avisos.append(
            f"{len(nao_convertidos)} de {len(precos)} preço(s) NÃO foram convertidos "
            "(ver 'nao_convertidos' e o motivo). Não foram estimados nem descartados "
            "— decida caso a caso."
        )
    bases = {c["unidade_base"] for c in convertidos}
    if len(bases) > 1:
        avisos.append(
            f"Os preços convertidos caíram em bases diferentes ({sorted(bases)}) — "
            "ainda não são comparáveis entre si. Separe por base antes de calcular."
        )
    if convertidos and not nao_convertidos and len(bases) <= 1:
        avisos.append(
            "Série na mesma base após a conversão — pronta para "
            "calcular_preco_referencia."
        )

    logger.info(
        "converter_para_unidade_base tipo=%s total=%d convertidos=%d nao=%d",
        tipo_item, len(precos), len(convertidos), len(nao_convertidos),
    )

    return {
        "tipo_item": tipo_item,
        "codigo_pdm": codigo_pdm,
        "codigo_servico": codigo_servico,
        "tabela_unidades": list(
            {id(v): v for v in tabela.values()}.values()
        ),
        "total": len(precos),
        "convertidos": convertidos,
        "precos_base": [c["preco_base"] for c in convertidos],
        "nao_convertidos": nao_convertidos,
        "avisos": avisos,
    }
