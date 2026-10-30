"""MCP Prompt: orquestra a metodologia do guia de pesquisa de preços sobre as tools existentes.

Complementa ``obter_diretrizes_pesquisa_precos`` (que devolve as premissas em
JSON/Markdown, mas não diz em que ordem usá-las) com um roteiro de
**execução**: em que sequência chamar as tools deste servidor para conduzir
uma pesquisa de preços completa, do objeto até a formalização, conforme
"Pesquisa de preços — um guia prático de sobrevivência" — ver
o guia de boas práticas de pesquisa de preços. Item pendente desde a v0.1.8
(ver CHANGELOG).

Diferença para uma tool: um MCP Prompt não executa nada nem devolve dados —
ele devolve um TEXTO (mensagem de usuário) que orienta o cliente/agente sobre
os próximos passos, citando as tools pelo nome na ordem recomendada. Em
clientes MCP, prompts aparecem como um "comando" que o usuário seleciona
explicitamente (ex.: slash command no Claude Desktop) — diferente de tools,
que o modelo decide chamar sozinho, e de resources, que são conteúdo estático
para leitura.

Esta é uma função **pura**: não consulta nenhuma API nem chama nenhuma outra
tool deste servidor — apenas monta o texto do roteiro a partir dos
argumentos recebidos.
"""
from __future__ import annotations


def conduzir_pesquisa_precos(objeto: str, agente_responsavel: str | None = None) -> str:
    """Gera o roteiro passo a passo para conduzir uma pesquisa de preços completa.

    Args:
        objeto: Descrição do item ou serviço a ser pesquisado (ex.: "notebook
            i5 8GB RAM").
        agente_responsavel: Nome/cargo de quem conduz a pesquisa, se já
            conhecido no momento de invocar o prompt. Usado para preencher o
            passo final de formalização (``gerar_memoria_pesquisa``); se
            omitido, o roteiro orienta perguntar ao usuário antes desse passo.

    Returns:
        Texto (mensagem de usuário) com o roteiro de execução, orquestrando
        as tools deste servidor na ordem recomendada pelo guia: diretrizes ->
        Curva ABC -> descoberta de catálogo -> coleta por prioridade de fonte
        -> tratamento (normalização de unidade, comparabilidade, correção
        monetária) -> cálculo -> formalização.
    """
    linha_responsavel = (
        f"Agente responsável informado: {agente_responsavel}.\n\n"
        if agente_responsavel and agente_responsavel.strip()
        else "Agente responsável: ainda não informado — pergunte ao usuário "
        "antes do passo 7 (formalização).\n\n"
    )

    return (
        f'Conduza uma pesquisa de preços completa para o objeto: "{objeto}", '
        "seguindo a metodologia de \"Pesquisa de preços — um guia prático de "
        "sobrevivência\" (jurisprudência do TCU), implementada pelas tools "
        "deste servidor. Siga esta sequência:\n\n"
        f"{linha_responsavel}"
        "1. Revise as premissas — chame `obter_diretrizes_pesquisa_precos` "
        "(ou leia o resource `docs://boas-praticas-pesquisa-precos`) antes de "
        "iniciar, para relembrar fontes prioritárias, regras de amostra e "
        "janela temporal.\n\n"
        "2. Se o objeto fizer parte de uma lista de itens (ex.: vários itens "
        "de uma mesma contratação), classifique-os primeiro com "
        "`classificar_curva_abc` — isso define o rigor da pesquisa por item: "
        "Classe A exige pesquisa exaustiva (mais fontes), Classe B pesquisa "
        "moderada, Classe C admite pesquisa simplificada.\n\n"
        "3. Se o objeto for um material ou serviço padronizado, use "
        "`descobrir_codigo_catalogo` para achar o código CATMAT/CATSER — é "
        "pré-requisito de `buscar_precos_praticados_compras`.\n\n"
        "4. Colete referências de preço NESTA ORDEM DE PRIORIDADE (não pule "
        "direto para cotação de fornecedores):\n"
        "   a. `buscar_precos_praticados_compras` — preços praticados no "
        "setor público (Painel de Preços/CATMAT-CATSER), prioridade "
        "normativa máxima (IN SEGES/ME 65/2021).\n"
        "   b. `buscar_contratacoes_pncp` (valor homologado/vencedor) e "
        "`buscar_contratos_compras` — contratações e contratos públicos "
        "vigentes/recentes no PNCP.\n"
        "   c. `consultar_ata_registro_preco` — atas de registro de preço "
        "vigentes de outros órgãos, quando aplicável.\n"
        "   d. Cotação direta de fornecedores — ÚLTIMO recurso, não o ponto "
        "de partida; evite concentrar em um único fornecedor ou em empresas "
        "vinculadas entre si.\n"
        "   Em todas: use o parâmetro `janelas_meses` para respeitar a "
        "janela temporal (6 meses por exigência legal, até 12 para itens "
        "estáveis), reúna no mínimo 3 referências válidas (efetivamente "
        "vencedoras/homologadas/contratadas — nunca valores estimados em "
        "edital) e anote toda busca que não retornar resultado (vai para "
        "`buscas_frustradas` no passo 7).\n\n"
        "5. TRATE as referências antes de calcular — não jogue os preços "
        "coletados direto numa média (é o erro nº 1 da pesquisa de preços):\n"
        "   a. `montar_cesta_precos` — passe os REGISTROS que as buscas do "
        "passo 4 devolveram (ex.: o campo `precos`/`registros`/`itens`) para "
        "extrair a série de preços de uma vez. NÃO transcreva preço a preço à "
        "mão: isso gera amostra artificialmente pequena. A cesta já sai com "
        "contexto (descrição/unidade/quantidade) para os passos seguintes.\n"
        "   b. `detectar_inconsistencias` — checagem de sanidade: aponta "
        "quantidade 1 em lote, homologado acima do estimado, unitário que "
        "aparenta global, objeto composto etc. Os alertas são informativos "
        "(nada é excluído) — investigue antes de seguir.\n"
        "   c. `normalizar_precos_unidade` — traga tudo para uma unidade "
        "comum (ex.: preço por usuário/mês, por licença/ano) antes de "
        "comparar; a tool devolve a fórmula e a confiança de cada conversão e "
        "separa o que não pôde ser normalizado (não estima em silêncio).\n"
        "   d. `agrupar_por_comparabilidade` — agrupe por unidade, faixa de "
        "quantidade e período e classifique cada preço na escala A–D relativa "
        "ao objeto (A idêntico, B diferença menor, C substituto próximo, D não "
        "comparável). Só os graus A–C entram no cálculo; os D ficam de fora. "
        "Informe o `alvo` (termos_nucleo/variacao/substituto, métrica, "
        "modalidade e, principalmente, `unidade`) — é onde entra o seu "
        "julgamento técnico. Atenção: o grau A–D é correspondência TEXTUAL, "
        "não atestado de preço; para calcular, use só grupos com "
        "`confiavel_para_calculo=True` (homogêneos, CV baixo) — um grau A com "
        "CV alto sinaliza mistura de escala/unidade (ex.: contrato global com "
        "preço unitário) e deve ser revisado, não somado.\n"
        "   e. Se os preços forem de datas diferentes, traga-os à mesma "
        "data-base com `atualizar_precos_indice` (IPCA por padrão; IGP-M ou "
        "IPC-Fipe quando justificado — para licenciamento de software, note "
        "que reajuste do fabricante/câmbio pode pesar mais que a inflação "
        "geral).\n\n"
        "6. Calcule o preço de referência com `calcular_preco_referencia` "
        "sobre UM grupo comparável do passo 5 (não misture grupos). Método "
        "padrão: média saneada; para TIC, o escore Z é o saneamento "
        "preferencial; use mediana ou mínimo apenas nos casos de baixo risco "
        "previstos no guia.\n\n"
        "7. Formalize com `gerar_memoria_pesquisa`, passando: objeto, agente "
        "responsável, cada fonte do passo 4 (com informante, meio de "
        "consulta, data e valor e, quando houver, CNPJ/quantidade/URL/"
        "especificação/condições), as buscas frustradas registradas e o "
        "resultado de `calcular_preco_referencia`. Use `formato=\"markdown\"` "
        "se o documento for anexado diretamente ao processo.\n\n"
        "Ao final, revise os `avisos` devolvidos por cada tool chamada "
        "(amostra pequena, CV alto, fontes divergentes da amostra etc.) "
        "antes de considerar a pesquisa concluída."
    )
