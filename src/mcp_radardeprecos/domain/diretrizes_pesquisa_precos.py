"""Premissas de uma pesquisa de preços, estruturadas a partir do guia de referência.

Fonte: "Pesquisa de preços — um guia prático de sobrevivência" (Franklin
Brasil, Set/2020), que consolida jurisprudência do TCU sobre o tema — ver
o guia de boas práticas de pesquisa de preços para o texto completo e o
mapeamento com o roadmap deste projeto.

``DIRETRIZES_PESQUISA_PRECOS`` é a **única fonte de verdade** deste
conteúdo: a tool ``obter_diretrizes_pesquisa_precos`` devolve esta mesma
estrutura como JSON, e o MCP Resource (registrado em ``server.py``) renderiza
``renderizar_markdown()`` — construída a partir da mesma constante — para
quem preferir o texto corrido. Evita manter o mesmo conteúdo duplicado em
dois formatos.
"""
from __future__ import annotations

from typing import Any

DIRETRIZES_PESQUISA_PRECOS: dict[str, Any] = {
    "fonte": {
        "titulo": "Pesquisa de preços — um guia prático de sobrevivência",
        "autor": "Franklin Brasil",
        "data_publicacao": "Setembro/2020",
        "normas_referenciadas": [
            "Lei 14.133/2021 (Nova Lei de Licitações)",
            "IN SEGES/ME 65/2021",
            "Lei 13.303/2016 (Lei das Estatais)",
        ],
        "documento_completo": "o guia de boas práticas de pesquisa de preços",
    },
    "conceito_central": (
        "O preço de referência deve resultar de uma 'cesta de preços "
        "aceitáveis' (várias fontes), não do mito de que '3 orçamentos' de "
        "fornecedores sempre validam o preço de mercado (Acórdãos TCU "
        "2.170/2007-P e 819/2009-P)."
    ),
    "fases": [
        {
            "fase": "objeto",
            "nome": "Especificação do objeto",
            "pontos_chave": [
                "Definição técnica clara, suficiente e precisa, compatível "
                "com a necessidade efetiva a ser atendida (Súmula 177 TCU).",
                "Incluir marca/modelo representativos, unidade de "
                "comercialização, quantidades com memória de cálculo, "
                "prazos, condições de entrega, garantia, instalação e "
                "suporte.",
            ],
        },
        {
            "fase": "planejamento",
            "nome": "Planejamento (Curva ABC / risco da compra)",
            "pontos_chave": [
                "Classificar os itens pela Curva ABC (Pareto 80/20): grupo "
                "A (poucos itens, alta relevância) exige pesquisa "
                "exaustiva; grupo B, pesquisa moderada; grupo C (muitos "
                "itens, baixa relevância), pesquisa simplificada.",
                "Acórdão TCU 2.096/2013-Plenário recomenda esse critério "
                "explicitamente.",
            ],
        },
        {
            "fase": "coleta",
            "nome": "Coleta de referências",
            "pontos_chave": [
                "Priorizar fontes na ordem de 'fontes_prioritarias' desta "
                "estrutura — cotação de fornecedores é o último recurso, "
                "não o ponto de partida.",
                "Mínimo de 3 referências; menos exige justificativa "
                "comprovada de limitação de mercado ou manifesto "
                "desinteresse, testada contra todo o universo de "
                "fornecedores (Acórdão TCU 43/2002-1C).",
                "Só valem preços efetivamente vencedores/homologados/"
                "contratados — nunca preços estimados em editais nem "
                "propostas desclassificadas (Acórdãos TCU 6.405/2017-1C e "
                "2.062/2016-1C).",
                "Respeitar a janela temporal (ver 'janela_temporal').",
                "Evitar concentração num único fornecedor ou cotações de "
                "empresas vinculadas entre si (Acórdão TCU 3.195/2017-2C).",
                "Garantir homogeneidade entre as referências: "
                "especificação, contemporaneidade, quantidade (efeito de "
                "escala) e unidade de medida comparáveis.",
            ],
        },
        {
            "fase": "tratamento",
            "nome": "Tratamento estatístico",
            "pontos_chave": [
                "Ver 'metodos_calculo' e a tool calcular_preco_referencia, "
                "que implementa esta fase.",
            ],
        },
        {
            "fase": "formalizacao",
            "nome": "Formalização e rastreabilidade",
            "pontos_chave": [
                "Ver 'checklist_formalizacao' desta estrutura.",
                "Registrar também as buscas frustradas, não só as "
                "bem-sucedidas.",
            ],
        },
    ],
    "fontes_prioritarias": [
        {
            "posicao": 1,
            "fonte": "Preços praticados no setor público (Painel de Preços / CATMAT-CATSER)",
            "observacao": "Priorizada pela IN SEGES/ME 65/2021 — a fonte com "
            "maior chance de já trazer preço efetivamente pago (não "
            "estimado). Coberta pela tool `buscar_precos_praticados_compras` "
            "(Compras.gov.br), que por padrão (`apenas_com_resultado=True`) "
            "só devolve registros com compra já concluída.",
        },
        {
            "posicao": 2,
            "fonte": "Preços históricos do próprio órgão contratante",
            "observacao": "Cuidado com defasagem/atualização e com o risco "
            "de referência de fornecedor único.",
        },
        {
            "posicao": 3,
            "fonte": "Atas de Registro de Preços vigentes de outros órgãos",
            "observacao": "Risco de extrapolação de contexto ou "
            "especificação diferente.",
        },
        {
            "posicao": 4,
            "fonte": "Mídia especializada e sites de e-commerce/domínio amplo",
            "observacao": "Ex.: Tabela FIPE (veículos), Pesquisa ANP "
            "(combustíveis). Condições de varejo podem diferir das "
            "condições de venda ao setor público.",
        },
        {
            "posicao": 5,
            "fonte": "Cotação direta de fornecedores",
            "observacao": "Último recurso, não o ponto de partida. "
            "Verificar quadro societário e capacidade operacional dos "
            "fornecedores consultados; evitar empresas vinculadas entre si.",
        },
    ],
    "regras_amostra": {
        "minimo_referencias": 3,
        "excecao_minimo": "Menos de 3 exige justificativa de limitação de "
        "mercado ou manifesto desinteresse, comprovada contra todo o "
        "universo de fornecedores (Acórdão TCU 43/2002-1C).",
        "apenas_precos_validos": "Só preços efetivamente vencedores/"
        "homologados/contratados — nunca preços estimados em editais nem "
        "de propostas desclassificadas (Acórdãos TCU 6.405/2017-1C e "
        "2.062/2016-1C).",
    },
    "janela_temporal": {
        # v0.2.7: o prazo NÃO é uniforme entre fontes — a IN SEGES/ME
        # 65/2021 (art. 3º) fixa janelas diferentes conforme a origem da
        # referência (confirmado por pesquisa direta ao texto normativo).
        # `limite_legal_nll_meses` continua em 6 por compatibilidade — é o
        # prazo mais restritivo, válido para mídia/cotação direta — mas
        # generalizá-lo para TODA fonte (como esta estrutura fazia até a
        # v0.2.6) sub-utiliza contratações públicas similares e notas
        # fiscais, que a própria IN admite usar com até 1 ano. Ver
        # 'por_fonte' para o detalhamento correto.
        "limite_legal_nll_meses": 6,
        "orientacao_geral_meses": 12,
        "por_fonte": [
            {
                "fonte": "Sistemas oficiais de preços (Painel de Preços, "
                "banco de preços em saúde)",
                "prazo": "Sem prazo fixo na IN 65/2021 — observar o índice "
                "de atualização de preços correspondente em vez de "
                "descartar por idade (ver tool `atualizar_precos_indice`).",
            },
            {
                "fonte": "Contratações públicas similares da Administração "
                "(em execução ou concluídas) e notas fiscais eletrônicas",
                "prazo": "Até 1 (um) ano da data de divulgação do edital "
                "(IN SEGES/ME 65/2021, art. 3º).",
            },
            {
                "fonte": "Mídia especializada, tabelas de referência "
                "formalmente aprovadas e sítios eletrônicos",
                "prazo": "Até 6 (seis) meses da data de divulgação do "
                "edital (IN SEGES/ME 65/2021, art. 3º).",
            },
            {
                "fonte": "Cotação direta com fornecedores",
                "prazo": "Até 6 (seis) meses da data de divulgação do "
                "edital (IN SEGES/ME 65/2021, art. 3º) — último recurso, "
                "não o ponto de partida (ver 'fontes_prioritarias').",
            },
        ],
        "observacao": "O prazo varia por fonte (ver 'por_fonte') — usar 6 "
        "meses indistintamente para tudo, como um teto único, sub-utiliza "
        "contratações públicas similares e notas fiscais (que admitem até "
        "1 ano) e pode aceitar indevidamente cotações diretas/mídia mais "
        "antigas que 6 meses. O parâmetro `janelas_meses` de "
        "`buscar_pncp_texto`, `buscar_contratacoes_pncp` e "
        "`buscar_contratos_compras` filtra no cliente por "
        "`data_publicacao_pncp` — ajuste o valor conforme a fonte "
        "efetivamente buscada, em vez de aplicar um único padrão a todas "
        "as chamadas.",
    },
    "metodos_calculo": {
        "tool": "calcular_preco_referencia",
        "escore_z": "Método padrão. Se o Coeficiente de Variação (CV) passa "
        "de 25%, remove um valor por vez — o de maior |Escore Z| — até CV ≤ 25% "
        "ou o piso de 3 referências (IPPC-TIC, AGU/MGI 2024); no piso sem a meta, "
        "fica a amostra de menor CV encontrada. Com CV inicial "
        "de até 25%, nada é removido. Em amostras de 20 preços ou mais, excluir "
        "mais de 20% pede revisão.",
        "media_saneada": "Média ± desvio-padrão em passe único (Acórdão TCU "
        "355/2019-P): exclui de uma vez os valores fora da faixa; não garante "
        "CV ≤ 25%.",
        "mediana": "Mais robusta a valores discrepantes; indicada para "
        "pesquisas de baixo risco ou amostras heterogêneas (Acórdãos TCU "
        "631/2014-P e 3033/2013-P).",
        "minimo": "Uso excepcional, restrito a mercados com poucos "
        "fornecedores (Acórdão TCU 8.514/2017-2C).",
    },
    "curva_abc": {
        "grupo_a": "Poucos itens, alta relevância econômica — pesquisa de "
        "preços exaustiva, item a item.",
        "grupo_b": "Relevância intermediária — pesquisa moderada, com "
        "possível agrupamento em lotes.",
        "grupo_c": "Muitos itens, baixa relevância econômica — pesquisa "
        "simplificada (baixo custo-benefício de um tratamento rigoroso).",
        "referencia": "Acórdão TCU 2.096/2013-Plenário.",
    },
    "checklist_formalizacao": [
        "Identificação do agente responsável pela cotação/pesquisa.",
        "Empresas pesquisadas do ramo pertinente e não vinculadas entre si.",
        "Caracterização completa de cada fonte: informante, meio de "
        "consulta, data, URL, CNPJ, quantidade, valor, especificação, "
        "condições de pagamento e entrega.",
        "Metodologia utilizada (ex.: média saneada) e conclusões obtidas.",
        "Data e local de expedição da pesquisa.",
        "Registro das buscas frustradas, quando houver, não só das "
        "bem-sucedidas.",
    ],
}


def renderizar_markdown() -> str:
    """Renderiza :data:`DIRETRIZES_PESQUISA_PRECOS` como texto em Markdown.

    Usada pelo MCP Resource (``docs://boas-praticas-pesquisa-precos`` em
    ``server.py``) para expor o mesmo conteúdo da tool
    ``obter_diretrizes_pesquisa_precos`` em formato legível, sem duplicar o
    texto em dois lugares — ambos são gerados a partir da mesma estrutura.
    """
    d = DIRETRIZES_PESQUISA_PRECOS
    linhas: list[str] = []

    fonte = d["fonte"]
    linhas.append("# Diretrizes de pesquisa de preços\n")
    linhas.append(
        f"Fonte: *{fonte['titulo']}* ({fonte['autor']}, "
        f"{fonte['data_publicacao']}). Normas de referência: "
        f"{', '.join(fonte['normas_referenciadas'])}.\n"
    )
    linhas.append(f"> {d['conceito_central']}\n")

    linhas.append("## Fases da pesquisa de preços\n")
    for fase in d["fases"]:
        linhas.append(f"### {fase['nome']}\n")
        for ponto in fase["pontos_chave"]:
            linhas.append(f"- {ponto}")
        linhas.append("")

    linhas.append("## Fontes de referência, por prioridade\n")
    for item in d["fontes_prioritarias"]:
        linhas.append(f"{item['posicao']}. **{item['fonte']}** — {item['observacao']}")
    linhas.append("")

    regras = d["regras_amostra"]
    linhas.append("## Regras da amostra\n")
    linhas.append(f"- Mínimo de referências: {regras['minimo_referencias']}")
    linhas.append(f"- Exceção ao mínimo: {regras['excecao_minimo']}")
    linhas.append(f"- Preços válidos: {regras['apenas_precos_validos']}")
    linhas.append("")

    janela = d["janela_temporal"]
    linhas.append("## Janela temporal\n")
    linhas.append(
        f"- Limite legal mais restritivo (mídia/cotação direta): "
        f"{janela['limite_legal_nll_meses']} meses"
    )
    linhas.append(
        f"- Orientação geral do guia: até {janela['orientacao_geral_meses']} meses"
    )
    linhas.append("- Prazo por fonte (IN SEGES/ME 65/2021, art. 3º):")
    for item in janela["por_fonte"]:
        linhas.append(f"  - **{item['fonte']}**: {item['prazo']}")
    linhas.append(f"- {janela['observacao']}")
    linhas.append("")

    metodos = d["metodos_calculo"]
    linhas.append(f"## Métodos de cálculo (tool `{metodos['tool']}`)\n")
    linhas.append(f"- **Escore Z**: {metodos['escore_z']}")
    linhas.append(f"- **Média saneada**: {metodos['media_saneada']}")
    linhas.append(f"- **Mediana**: {metodos['mediana']}")
    linhas.append(f"- **Mínimo**: {metodos['minimo']}")
    linhas.append("")

    curva = d["curva_abc"]
    linhas.append(f"## Curva ABC ({curva['referencia']})\n")
    linhas.append(f"- **Grupo A**: {curva['grupo_a']}")
    linhas.append(f"- **Grupo B**: {curva['grupo_b']}")
    linhas.append(f"- **Grupo C**: {curva['grupo_c']}")
    linhas.append("")

    linhas.append("## Checklist de formalização\n")
    for item in d["checklist_formalizacao"]:
        linhas.append(f"- [ ] {item}")
    linhas.append("")

    linhas.append(
        f"Documento completo com jurisprudência detalhada: "
        f"`{fonte['documento_completo']}`."
    )

    return "\n".join(linhas)
