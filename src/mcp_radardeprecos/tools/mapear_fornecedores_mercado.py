"""Tool MCP: quem vem fornecendo determinado objeto ao setor público.

Responde a pergunta que vem ANTES do preço — "quem fornece isso?" — a partir
de texto livre ("microsoft", "switch SAN", "cabo de rede"), não de código de
catálogo. É a entrada natural de um Estudo Técnico Preliminar: antes de
estimar quanto custa, é preciso saber se há mercado e quantos players.

**O que a ferramenta NÃO responde, e é o ponto mais importante desta
docstring.** Ela lista quem **venceu**, não quem **participou**. O PNCP
publica o resultado adjudicado de cada item — verificado ao vivo em
2026-08-18 no endpoint de resultado: devolve o fornecedor homologado e, em
registro de preços, os classificados (``ordemClassificacaoSrp``). Propostas
perdedoras não são publicadas. Quem disputou e perdeu é invisível aqui.

Isso importa porque as duas perguntas levam a decisões diferentes: "quantos
venderam" mede concentração de mercado; "quantos disputaram" mede
competitividade do certame. Confundi-las subestima a competição.

**Segundo limite, da mesma família.** Ausência nesta lista não significa
incapacidade de fornecer. Um fornecedor novo, ou que nunca venceu naquele
objeto, não aparece. Usar o resultado para concluir "só existem N
fornecedores no mercado" — numa justificativa de inexigibilidade, por
exemplo — inverte o significado do dado.

Ambos os limites são declarados em ``avisos``, junto do resultado, e não só
aqui: quem lê a resposta raramente leu a documentação.
"""
from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger
from .buscar_contratacoes_pncp import buscar_contratacoes_pncp

logger = get_logger(__name__)

#: Teto de contratações varridas. Cada uma custa uma chamada de itens mais uma
#: de resultado POR ITEM, então o custo cresce rápido — 50 contratações de 10
#: itens já são ~550 requisições ao PNCP.
_MAX_CONTRATACOES = 100


def _faixa(valores: list[float]) -> dict[str, float | None]:
    limpos = [v for v in valores if isinstance(v, (int, float)) and v > 0]
    if not limpos:
        return {"minimo": None, "maximo": None, "mediano": None}
    ordenados = sorted(limpos)
    meio = len(ordenados) // 2
    mediano = (
        ordenados[meio]
        if len(ordenados) % 2
        else (ordenados[meio - 1] + ordenados[meio]) / 2
    )
    return {"minimo": ordenados[0], "maximo": ordenados[-1], "mediano": mediano}


async def mapear_fornecedores_mercado(
    termo_busca: str,
    janelas_meses: int = 12,
    uf: str | None = None,
    limite_contratacoes: int = 30,
    incluir_contratacoes: bool = False,
) -> dict[str, Any]:
    """Mapeia quem VENCEU contratações de um objeto, agregando por fornecedor.

    Args:
        termo_busca: texto livre do objeto (ex.: ``"microsoft"``,
            ``"switch SAN"``). Vale a observação de ``buscar_pncp_texto``:
            múltiplas palavras casam como "E", sem ordem, e termos curtos
            casam por prefixo — prefira termos específicos.
        janelas_meses: janela de tempo, contada da data de publicação no PNCP.
            Padrão 12.
        uf: sigla da UF, para restringir geograficamente (ex.: ``"PR"``).
        limite_contratacoes: quantas contratações varrer antes de agregar
            (padrão 30, teto 100). Quanto maior, mais completo e mais lento —
            o custo cresce com o número de ITENS de cada contratação.
        incluir_contratacoes: se ``True``, inclui em cada fornecedor a lista
            dos números de controle PNCP em que ele venceu, para conferência.

    Returns:
        ``{fornecedores, total_fornecedores, contratacoes_analisadas,
        avisos}``. Cada fornecedor traz identificação, porte, tipo de pessoa,
        quantas contratações e itens venceu, faixa de preço unitário
        homologado, valor total, órgãos e UFs onde atuou, e o período.
        Ordenado por número de contratações vencidas (proxy de recorrência),
        não por preço.
    """
    limite_contratacoes = max(1, min(limite_contratacoes, _MAX_CONTRATACOES))
    logger.info(
        "mapear_fornecedores_mercado termo=%r janelas_meses=%s uf=%s limite=%s",
        termo_busca, janelas_meses, uf, limite_contratacoes,
    )

    base = await buscar_contratacoes_pncp(
        termo_busca=termo_busca,
        janelas_meses=janelas_meses,
        uf=uf,
        limite=limite_contratacoes,
        apenas_homologadas=True,
        incluir_valor_homologado=True,
    )

    por_fornecedor: dict[str, dict[str, Any]] = {}
    itens_sem_vencedor = 0

    for contratacao in base.get("resultados", []):
        numero = contratacao.get("numero_controle_pncp")
        orgao = contratacao.get("orgao")
        uf_c = contratacao.get("uf")
        data = contratacao.get("data_publicacao_pncp")

        for item in contratacao.get("itens", []):
            vencedor = item.get("fornecedor_vencedor")
            if not vencedor or not vencedor.get("cnpj"):
                itens_sem_vencedor += 1
                continue
            chave = vencedor["cnpj"]
            if chave not in por_fornecedor:
                por_fornecedor[chave] = {
                    "identificacao": chave,
                    "nome": vencedor.get("nome"),
                    "tipo_pessoa": vencedor.get("tipo_pessoa"),
                    "porte": vencedor.get("porte"),
                    "contratacoes": set(),
                    "itens_vencidos": 0,
                    "valor_total_homologado": 0.0,
                    "_precos": [],
                    "orgaos": set(),
                    "ufs": set(),
                    "primeira_vez": data,
                    "ultima_vez": data,
                }
            f = por_fornecedor[chave]
            f["contratacoes"].add(numero)
            f["itens_vencidos"] += 1
            if orgao:
                f["orgaos"].add(orgao)
            if uf_c:
                f["ufs"].add(uf_c)
            if data and (not f["primeira_vez"] or data < f["primeira_vez"]):
                f["primeira_vez"] = data
            if data and (not f["ultima_vez"] or data > f["ultima_vez"]):
                f["ultima_vez"] = data

            unitario = item.get("valor_unitario_homologado")
            quantidade = item.get("quantidade_homologada") or 0
            if isinstance(unitario, (int, float)) and unitario > 0:
                f["_precos"].append(float(unitario))
                if isinstance(quantidade, (int, float)):
                    f["valor_total_homologado"] += float(unitario) * float(quantidade)

    fornecedores = []
    for f in por_fornecedor.values():
        registro = {
            "identificacao": f["identificacao"],
            "nome": f["nome"],
            "tipo_pessoa": f["tipo_pessoa"],
            "porte": f["porte"],
            "contratacoes_vencidas": len(f["contratacoes"]),
            "itens_vencidos": f["itens_vencidos"],
            "valor_total_homologado": round(f["valor_total_homologado"], 2),
            "preco_unitario": _faixa(f["_precos"]),
            "orgaos": sorted(f["orgaos"]),
            "ufs": sorted(f["ufs"]),
            "primeira_vez": f["primeira_vez"],
            "ultima_vez": f["ultima_vez"],
        }
        if incluir_contratacoes:
            registro["numeros_controle_pncp"] = sorted(x for x in f["contratacoes"] if x)
        fornecedores.append(registro)

    # Recorrência primeiro: quem vence muitas vezes é o sinal que a pergunta
    # busca. Ordenar por valor destacaria um contrato grande e único, que diz
    # menos sobre capacidade de fornecimento.
    fornecedores.sort(
        key=lambda r: (r["contratacoes_vencidas"], r["itens_vencidos"]), reverse=True
    )

    contratacoes_analisadas = len(base.get("resultados", []))
    avisos: list[str] = [
        "Esta lista é de quem VENCEU, não de quem PARTICIPOU. O PNCP publica o "
        "resultado adjudicado de cada item; propostas perdedoras não são "
        "publicadas. Para medir competitividade de um certame (quantos "
        "disputaram), este dado não serve — ele mede concentração (quem levou).",
        "Ausência nesta lista NÃO significa incapacidade de fornecer: quem nunca "
        "venceu neste objeto, ou entrou no mercado depois, não aparece. Não use "
        "a contagem como número de fornecedores existentes — em especial para "
        "justificar inexigibilidade ou restringir competição.",
        f"Universo analisado: {contratacoes_analisadas} contratação(ões) "
        f"homologadas dos últimos {janelas_meses} mes(es)"
        + (f" na UF {uf}" if uf else "")
        + f", encontradas pelo termo {termo_busca!r}. Ampliar "
        "limite_contratacoes/janelas_meses muda o resultado.",
    ]
    if itens_sem_vencedor:
        avisos.append(
            f"{itens_sem_vencedor} item(ns) das contratações analisadas não "
            "tinham resultado com fornecedor identificado e ficaram de fora."
        )
    if any(f.get("tipo_pessoa") == "PF" for f in fornecedores):
        avisos.append(
            "Há fornecedor(es) PESSOA FÍSICA nesta lista (tipo_pessoa='PF'): o "
            "campo 'nome' é nome civil, e 'identificacao' é CPF. Trate como dado "
            "pessoal ao reutilizar ou publicar."
        )
    avisos.extend(base.get("avisos", []))

    return {
        "fornecedores": fornecedores,
        "total_fornecedores": len(fornecedores),
        "contratacoes_analisadas": contratacoes_analisadas,
        "avisos": avisos,
    }
