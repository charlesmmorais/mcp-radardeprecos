"""Tabelas de domínio e constantes de validação compartilhadas entre tools.

As tabelas de código do PNCP (``MODALIDADES_PNCP``, ``TIPOS_DOCUMENTO_BUSCA_PNCP``)
são reproduzidas a partir da API de Consulta do PNCP (manual e documentação oficial do PNCP). Mantidas como
constantes simples (sem chamada de rede) porque mudam raramente; revisar
periodicamente contra a fonte oficial:
https://pncp.gov.br/api/consulta/swagger-ui/index.html

Estas constantes são a fonte única de verdade para validação de entrada nas
tools (``TIPOS_DOCUMENTO_BUSCA_PNCP`` em ``buscar_pncp_texto``,
``listar_arquivos_pncp`` e ``listar_filtros_pncp``; ``MODALIDADES_PNCP`` em
``buscar_pncp_texto``; ``METODOS_CALCULO_PRECO`` em ``calcular_preco_referencia``;
``TIPOS_ITEM_CATALOGO_COMPRAS`` em ``buscar_precos_praticados_compras``;
``FORMATOS_MEMORIA_PESQUISA`` em ``gerar_memoria_pesquisa``) — evita repetir
a mesma tupla/validação em cada arquivo.
"""
from __future__ import annotations

from typing import Any

MODALIDADES_PNCP: dict[int, str] = {
    1: "Leilão - Eletrônico",
    2: "Diálogo Competitivo",
    3: "Concurso",
    4: "Concorrência - Eletrônica",
    5: "Concorrência - Presencial",
    6: "Pregão - Eletrônico",
    7: "Pregão - Presencial",
    8: "Dispensa de Licitação",
    9: "Inexigibilidade",
    10: "Manifestação de Interesse",
    11: "Pré-qualificação",
    12: "Credenciamento",
    13: "Leilão - Presencial",
}

TIPOS_DOCUMENTO_BUSCA_PNCP: tuple[str, ...] = ("edital", "ata", "contrato")

# Métodos de cálculo de preço de referência descritos em "Pesquisa de preços
# — um guia prático de sobrevivência" (Franklin Brasil): média saneada é o
# método padrão (Acórdão TCU 355/2019-P); mediana e mínimo são alternativas
# para casos de baixo risco (Acórdãos TCU 631/2014-P, 3033/2013-P e
# 8.514/2017-2C, respectivamente). "escore_z" é o método de
# saneamento preferencial para TIC segundo o IPPC-TIC (AGU/MGI, 2024, p.
# 70-72) e a orientação "Análise Crítica na Pesquisa de Preços" (SGD,
# 2026, item 1.4): mesmo critério de parada (CV <= 25%) de "media_saneada",
# mas remove só o valor de maior |Escore Z| por iteração, não o lote
# inteiro fora de média ± desvio-padrão de uma vez. Ver
# o guia de boas práticas de pesquisa de preços seção 6.
METODOS_CALCULO_PRECO: tuple[str, ...] = ("media_saneada", "mediana", "minimo", "escore_z")

# CATMAT (material) ou CATSER (serviço) — os dois catálogos do Compras.gov.br
# usados por buscar_precos_praticados_compras. Cada um mapeia para um
# endpoint diferente do módulo "Pesquisa de Preço" (ver compras_client.py).
TIPOS_ITEM_CATALOGO_COMPRAS: tuple[str, ...] = ("material", "servico")

# Palavras-chave para classificar_objeto_tic (item 4 da lista priorizada de
# melhorias, análise cruzada ChatGPT/Claude, 2026-07-08) — filtro HEURÍSTICO
# por palavra-chave no objeto/descrição de uma contratação, item ou processo.
# Deliberadamente simples (busca de substring, sem NLP/embeddings): o PNCP
# tem um campo estruturado equivalente só para itens de PCA
# (``categoria_item_pca`` código 5, "Soluções de TIC" — ver
# ``consultar_pca``), mas NÃO para editais/contratações em geral nas tools
# já implementadas aqui, e não tem NENHUM campo estruturado para "SaaS"
# (conceito de modelo de licenciamento, não uma categoria do PNCP). Por
# isso, esta lista é um teto de precisão CONHECIDO e aceito, não uma
# tentativa de classificação definitiva — ver aviso fixo em
# ``tools.classificar_objeto_tic``. Termos escolhidos a partir de
# terminologia comum em objetos de contratação de TIC (não de uma fonte
# normativa fechada) — revisar/ampliar conforme falsos negativos forem
# encontrados em uso real.
PALAVRAS_TIC: tuple[str, ...] = (
    "tecnologia da informação", "tecnologia da informacao", "solução de ti",
    "solucao de ti", "solução tecnológica", "solucao tecnologica", "software",
    "sistema informatizado", "licenciamento de software",
    "licença de uso de software", "licenca de uso de software",
    "computador", "notebook", "desktop", "servidor de rede",
    "data center", "datacenter", "storage", "armazenamento de dados",
    "banco de dados", "aplicativo", "plataforma digital",
    "infraestrutura de ti", "infraestrutura de tic", "rede de dados",
    "telecomunicações", "telecomunicacoes", "link de internet",
    "cabeamento estruturado", "firewall", "switch de rede", "roteador",
    "impressora", "scanner", "backup de dados", "cibersegurança",
    "ciberseguranca", "segurança da informação", "seguranca da informacao",
    "desenvolvimento de sistemas", "manutenção de sistemas",
    "manutencao de sistemas", "suporte técnico de ti", "suporte tecnico de ti",
    "outsourcing de impressão", "outsourcing de impressao", "virtualização",
    "virtualizacao", "nuvem", "cloud", "hospedagem de sítio",
    "hospedagem de site", "certificado digital", "assinatura digital",
    "central de atendimento ao usuário de ti", "service desk",
    "fábrica de software", "fabrica de software", "sistema operacional",
    # v0.2.6, item 11: termos de alta precisão
    # acrescentados após bug confirmado ao vivo em 2026-07-12 — "Contratação
    # de licenças Microsoft 365 em modelo SaaS..." não casava com NENHUM
    # termo de PALAVRAS_TIC (só com PALAVRAS_SAAS via "saas"), o que por si
    # só já foi corrigido em classificar_objeto_tic (e_tic passa a ser
    # também True quando e_saas é True), mas a taxonomia também estava
    # incompleta para o caso comum de contratação de licença de suíte de
    # produtividade. Bigramas deliberados — "licença"/"licenças" SOZINHO não
    # entra (colide com "licença ambiental"/"licença de operação"). Pelo
    # mesmo motivo, o termo pré-existente "licença de uso" foi trocado por
    # "licença de uso de software" acima — o bigrama antigo colidia com
    # "licença de uso de imagem" (caso negativo explícito do item 11).
    "microsoft 365", "office 365", "m365", "google workspace",
    "licença de software", "licenca de software",
    "subscrição de software", "subscricao de software",
    "sistema de informação", "sistema de informacao",
)

# Subconjunto de PALAVRAS_TIC específico do modelo de licenciamento SaaS
# (Software as a Service — assinatura/nuvem) — distinção relevante porque o
# IPPC-TIC trata licenciamento por assinatura de forma diferente de
# licenciamento perpétuo/hardware na análise de custo total de propriedade.
PALAVRAS_SAAS: tuple[str, ...] = (
    "saas", "software as a service", "assinatura de software",
    "licenciamento por assinatura", "licença por assinatura",
    "licenca por assinatura", "plataforma como serviço",
    "plataforma como servico", "paas", "platform as a service",
    "infraestrutura como serviço", "infraestrutura como servico", "iaas",
    "infrastructure as a service", "hospedagem em nuvem",
    "serviço de nuvem", "servico de nuvem", "cloud computing",
    "computação em nuvem", "computacao em nuvem", "software por demanda",
)

# Formato de saída de gerar_memoria_pesquisa: "json" (estrutura de dados,
# para consumo programático) ou "markdown" (documento pronto para leitura
# corrida/anexação ao processo) — mesmo padrão dual já usado por
# obter_diretrizes_pesquisa_precos + o MCP Resource equivalente.
FORMATOS_MEMORIA_PESQUISA: tuple[str, ...] = ("json", "markdown")

# Modelos de relatório suportados por gerar_relatorio_excel/gerar_relatorio_word
# (parâmetro `modelo`). Status de cada um:
# - "in65": único IMPLEMENTADO. Segue os 8 elementos mínimos exigidos pelo
#   Art. 3º da IN SEGES/ME nº 65/2021 (formalização da pesquisa de preços),
#   confirmados lendo o texto oficial em
#   https://www.gov.br/compras/pt-br/acesso-a-informacao/legislacao/instrucoes-normativas/instrucao-normativa-seges-me-no-65-de-7-de-julho-de-2021
#   — NÃO uma estrutura de "seções 7.1 a 7.9" (essa numeração, usada por
#   algumas ferramentas, não existe no texto real da IN, que tem só 11
#   artigos corridos).
# - "tic_licitacao": PREPARADO, não implementado — modelo específico
#   para contratação de itens de TIC via licitação (Art. 8º da IN 65/2021
#   trata de TIC de forma específica: preço do Catálogo de Soluções de TIC
#   com Condições Padronizadas deve ser usado como estimado, salvo pesquisa
#   resultando em valor menor). Selecionar levanta NotImplementedError.
# - "tic_inexigibilidade": PREPARADO, não implementado — mesmo caso, para
#   contratação de TIC por inexigibilidade/dispensa (Art. 7º da IN 65/2021).
#   Selecionar levanta NotImplementedError.
MODELOS_RELATORIO_PRECOS: tuple[str, ...] = ("in65", "tic_licitacao", "tic_inexigibilidade")
MODELOS_RELATORIO_PRECOS_IMPLEMENTADOS: tuple[str, ...] = ("in65",)

# Índices de correção monetária suportados por atualizar_precos_indice (item 2
# do plano v0.2.4) — os três disponíveis no SGS/Banco
# Central com o mesmo formato público, sem credencial, usado por
# clients/bcb_client.py. "ipca" é o padrão (IN SEGES/ME 65/2021); os demais
# atendem casos de uso específicos (ver "uso_tipico" de cada um). Fonte única
# de verdade — a tabela de outras séries SGS (INPC, SELIC etc.) do backlog
# condicionado do plano v0.2.4 seria uma simples adição aqui.
INDICES_CORRECAO_MONETARIA: dict[str, dict[str, Any]] = {
    "ipca": {
        "serie_sgs": 433,
        "nome": "IPCA",
        "fonte_oficial": "IBGE",
        "uso_tipico": (
            "Índice oficial de inflação — padrão para pesquisa de preços "
            "conforme a IN SEGES/ME 65/2021."
        ),
    },
    "igpm": {
        "serie_sgs": 189,
        "nome": "IGP-M",
        "fonte_oficial": "FGV",
        "uso_tipico": (
            "Contratos com cláusula de reajuste IGP-M (aluguéis, contratos "
            "administrativos antigos)."
        ),
    },
    "ipc_fipe": {
        "serie_sgs": 193,
        "nome": "IPC-Fipe",
        "fonte_oficial": "Fipe",
        "uso_tipico": "Cesta do município de São Paulo — comparações regionais SP.",
    },
}

# Tabelas de domínio oficiais do PNCP (códigos usados em vários campos das
# APIs de Consulta e de busca) — consumidas por `consultar_tabelas_dominio_pncp`
# (conferidas em 2026-07-05). IMPORTANTE — origem: estes valores vêm do
# Manual/documentação do PNCP, não de uma chamada de
# rede ao vivo — por isso são hardcoded aqui, no mesmo espírito de
# `MODALIDADES_PNCP` acima, com o mesmo risco de desatualização (revisar
# periodicamente contra o manual oficial do PNCP).
#
# CORREÇÃO: até a v0.5.0 este bloco afirmava que o PNCP "NÃO tem
# nenhum endpoint REST de tabelas de domínio". Isso vale para o spec da API de
# CONSULTA (`/api/consulta/v3/api-docs`), lido por inteiro — e foi
# indevidamente generalizado. O Manual de Integração do PNCP 2.6 documenta
# `/v1/modalidades`, `/v1/modos-disputa`, `/v1/criterios-julgamento`,
# `/v1/tipos-contrato`, `/v1/tipos-documento`, `/v1/amparos-legais`,
# `/v1/categorias-item`, `/v1/instrumentos-convocatorios` e
# `/v1/portes-empresa`. NÃO foi verificado se respondem sem autenticação (o
# manual é de integração, e o PNCP esteve fora do ar em 04-05/09/2026), então
# a transcrição permanece — mas o parâmetro `statusAtivo` desses endpoints
# revela que há itens DESATIVADOS ao longo do tempo, o que uma transcrição
# congelada não acompanha. Ver docs/ACHADOS_DAS_FONTES.md, seção 2.
# `modalidade_contratacao`
# é derivada de `MODALIDADES_PNCP` para não duplicar a fonte única de verdade
# desse domínio específico.
#
# Nota sobre nomes parecidos mas com significados DIFERENTES: `tipo_documento`
# aqui é a tabela oficial de tipos de documento/anexo do PNCP (Edital, Termo
# de Referência, Ata de Registro de Preço, Termo Aditivo etc., usada em
# `/arquivos`) — não confundir com `TIPOS_DOCUMENTO_BUSCA_PNCP` acima
# ("edital"/"ata"/"contrato"), que são as 3 categorias de busca do backend
# `/api/search` usadas por `buscar_pncp_texto`/`listar_arquivos_pncp`/
# `listar_filtros_pncp` — domínios distintos, de APIs distintas.
TABELAS_DOMINIO_PNCP: dict[str, tuple[dict[str, Any], ...]] = {
    "instrumento_convocatorio": (
        {
            "codigo": 1,
            "nome": "Edital",
            "descricao": "Diálogo competitivo, concurso, concorrência, pregão, manifestação de interesse, pré-qualificação e credenciamento",
        },
        {
            "codigo": 2,
            "nome": "Aviso de Contratação Direta",
            "descricao": "Dispensa com Disputa",
        },
        {
            "codigo": 3,
            "nome": "Ato que autoriza a Contratação Direta",
            "descricao": "Dispensa sem Disputa ou Inexigibilidade",
        },
    ),
    "modalidade_contratacao": tuple(
        {"codigo": codigo, "nome": nome} for codigo, nome in MODALIDADES_PNCP.items()
    ),
    "modo_disputa": (
        {"codigo": 1, "nome": "Aberto"},
        {"codigo": 2, "nome": "Fechado"},
        {"codigo": 3, "nome": "Aberto-Fechado"},
        {"codigo": 4, "nome": "Dispensa Com Disputa"},
        {"codigo": 5, "nome": "Não se aplica"},
        {"codigo": 6, "nome": "Fechado-Aberto"},
    ),
    "criterio_julgamento": (
        {"codigo": 1, "nome": "Menor preço"},
        {"codigo": 2, "nome": "Maior desconto"},
        {"codigo": 4, "nome": "Técnica e preço"},
        {"codigo": 5, "nome": "Maior lance"},
        {"codigo": 6, "nome": "Maior retorno econômico"},
        {"codigo": 7, "nome": "Não se aplica"},
        {"codigo": 8, "nome": "Melhor técnica"},
        {"codigo": 9, "nome": "Conteúdo artístico"},
    ),
    "situacao_contratacao": (
        {
            "codigo": 1,
            "nome": "Divulgada no PNCP",
            "descricao": "Situação atribuída na inclusão da contratação",
        },
        {"codigo": 2, "nome": "Revogada"},
        {"codigo": 3, "nome": "Anulada"},
        {"codigo": 4, "nome": "Suspensa"},
    ),
    "situacao_item_contratacao": (
        {
            "codigo": 1,
            "nome": "Em Andamento",
            "descricao": "Disputa/seleção do fornecedor não finalizada",
        },
        {
            "codigo": 2,
            "nome": "Homologado",
            "descricao": "Com resultado (fornecedor informado)",
        },
        {"codigo": 3, "nome": "Anulado/Revogado/Cancelado"},
        {"codigo": 4, "nome": "Deserto", "descricao": "Sem fornecedores interessados"},
        {
            "codigo": 5,
            "nome": "Fracassado",
            "descricao": "Fornecedores desclassificados ou inabilitados",
        },
    ),
    "tipo_beneficio": (
        {"codigo": 1, "nome": "Participação exclusiva para ME/EPP"},
        {"codigo": 2, "nome": "Subcontratação para ME/EPP"},
        {"codigo": 3, "nome": "Cota reservada para ME/EPP"},
        {"codigo": 4, "nome": "Sem benefício"},
        {"codigo": 5, "nome": "Não se aplica"},
    ),
    "situacao_resultado_item_contratacao": (
        {
            "codigo": 1,
            "nome": "Informado",
            "descricao": "Possui valor, fornecedor e marca oriundo do resultado",
        },
        {"codigo": 2, "nome": "Cancelado"},
    ),
    "tipo_contrato": (
        {
            "codigo": 1,
            "nome": "Contrato (termo inicial)",
            "descricao": "Acordo formal recíproco entre as partes",
        },
        {
            "codigo": 2,
            "nome": "Comodato",
            "descricao": "Concessão de uso gratuito de bem móvel ou imóvel",
        },
        {
            "codigo": 3,
            "nome": "Arrendamento",
            "descricao": "Cessão de bem por período mediante pagamento",
        },
        {
            "codigo": 4,
            "nome": "Concessão",
            "descricao": "Serviço público com remuneração por tarifa",
        },
        {"codigo": 5, "nome": "Termo de Adesão", "descricao": "Cláusulas não negociáveis"},
        {"codigo": 6, "nome": "Convênio", "descricao": "Objetivo em comum entre as partes"},
        {"codigo": 7, "nome": "Empenho", "descricao": "Promessa de pagamento pelo Estado"},
        {"codigo": 8, "nome": "Outros"},
        {
            "codigo": 9,
            "nome": "Termo de Execução Descentralizada (TED)",
            "descricao": "Descentralização de crédito entre órgãos",
        },
        {
            "codigo": 10,
            "nome": "Acordo de Cooperação Técnica (ACT)",
            "descricao": "Execução de programas de trabalho",
        },
        {"codigo": 11, "nome": "Termo de Compromisso"},
        {
            "codigo": 12,
            "nome": "Carta Contrato",
            "descricao": "Formaliza acordo em hipóteses que a lei dispensa contrato",
        },
    ),
    "tipo_termo_contrato": (
        {
            "codigo": 1,
            "nome": "Termo de Rescisão",
            "descricao": "Encerramento antes da data final",
        },
        {
            "codigo": 2,
            "nome": "Termo Aditivo",
            "descricao": "Atualiza o contrato (prorrogação, reajuste, acréscimo, supressão)",
        },
        {
            "codigo": 3,
            "nome": "Termo de Apostilamento",
            "descricao": "Atualiza o valor do contrato",
        },
    ),
    "categoria_processo": (
        {"codigo": 1, "nome": "Cessão"},
        {"codigo": 2, "nome": "Compras"},
        {"codigo": 3, "nome": "Informática (TIC)"},
        {"codigo": 4, "nome": "Internacional"},
        {"codigo": 5, "nome": "Locação Imóveis"},
        {"codigo": 6, "nome": "Mão de Obra"},
        {"codigo": 7, "nome": "Obras"},
        {"codigo": 8, "nome": "Serviços"},
        {"codigo": 9, "nome": "Serviços de Engenharia"},
        {"codigo": 10, "nome": "Serviços de Saúde"},
        {"codigo": 11, "nome": "Alienação de bens móveis/imóveis"},
    ),
    "tipo_documento": (
        {"codigo": 1, "nome": "Aviso de Contratação Direta", "categoria": "contratacao"},
        {"codigo": 2, "nome": "Edital", "categoria": "contratacao"},
        {"codigo": 3, "nome": "Minuta do Contrato", "categoria": "contratacao_anexo"},
        {"codigo": 4, "nome": "Termo de Referência", "categoria": "contratacao_anexo"},
        {"codigo": 5, "nome": "Anteprojeto", "categoria": "contratacao_anexo"},
        {"codigo": 6, "nome": "Projeto Básico", "categoria": "contratacao_anexo"},
        {"codigo": 7, "nome": "Estudo Técnico Preliminar", "categoria": "contratacao_anexo"},
        {"codigo": 8, "nome": "Projeto Executivo", "categoria": "contratacao_anexo"},
        {"codigo": 9, "nome": "Mapa de Riscos", "categoria": "contratacao_anexo"},
        {"codigo": 10, "nome": "DFD", "categoria": "contratacao_anexo"},
        {"codigo": 11, "nome": "Ata de Registro de Preço", "categoria": "ata"},
        {"codigo": 12, "nome": "Contrato", "categoria": "contrato"},
        {"codigo": 13, "nome": "Termo de Rescisão", "categoria": "contrato"},
        {"codigo": 14, "nome": "Termo Aditivo", "categoria": "contrato"},
        {"codigo": 15, "nome": "Termo de Apostilamento", "categoria": "contrato"},
        {"codigo": 16, "nome": "Outros documentos do processo", "categoria": "geral"},
        {"codigo": 17, "nome": "Nota de Empenho", "categoria": "contrato"},
        {"codigo": 18, "nome": "Relatório Final de Contrato", "categoria": "contrato"},
    ),
    "porte_empresa": (
        {"codigo": 1, "nome": "ME", "descricao": "Microempresa"},
        {"codigo": 2, "nome": "EPP", "descricao": "Empresa de Pequeno Porte"},
        {"codigo": 3, "nome": "Demais", "descricao": "Demais empresas"},
        {"codigo": 4, "nome": "Não se aplica", "descricao": "Fornecedor pessoa física"},
        {"codigo": 5, "nome": "Não informado"},
    ),
    "categoria_item_pca": (
        {"codigo": 1, "nome": "Material"},
        {"codigo": 2, "nome": "Serviço"},
        {"codigo": 3, "nome": "Obras"},
        {"codigo": 4, "nome": "Serviços de Engenharia"},
        {"codigo": 5, "nome": "Soluções de TIC"},
        {"codigo": 6, "nome": "Locação de Imóveis"},
        {"codigo": 7, "nome": "Alienação/Concessão/Permissão"},
        {"codigo": 8, "nome": "Obras e Serviços de Engenharia"},
    ),
    "amparo_legal": (
        {"codigo": 1, "nome": "Lei 14.133/2021, Art. 28, I"},
        {"codigo": 2, "nome": "Lei 14.133/2021, Art. 28, II"},
        {"codigo": 3, "nome": "Lei 14.133/2021, Art. 28, III"},
        {"codigo": 4, "nome": "Lei 14.133/2021, Art. 28, IV"},
        {"codigo": 5, "nome": "Lei 14.133/2021, Art. 28, V"},
        {"codigo": 6, "nome": "Lei 14.133/2021, Art. 74, I"},
        {"codigo": 7, "nome": "Lei 14.133/2021, Art. 74, II"},
        {"codigo": 8, "nome": "Lei 14.133/2021, Art. 74, III, a"},
        {"codigo": 9, "nome": "Lei 14.133/2021, Art. 74, III, b"},
        {"codigo": 10, "nome": "Lei 14.133/2021, Art. 74, III, c"},
        {"codigo": 11, "nome": "Lei 14.133/2021, Art. 74, III, d"},
        {"codigo": 12, "nome": "Lei 14.133/2021, Art. 74, III, e"},
        {"codigo": 13, "nome": "Lei 14.133/2021, Art. 74, III, f"},
        {"codigo": 14, "nome": "Lei 14.133/2021, Art. 74, III, g"},
        {"codigo": 15, "nome": "Lei 14.133/2021, Art. 74, III, h"},
        {"codigo": 16, "nome": "Lei 14.133/2021, Art. 74, IV"},
        {"codigo": 17, "nome": "Lei 14.133/2021, Art. 74, V"},
        {"codigo": 18, "nome": "Lei 14.133/2021, Art. 75, I"},
        {"codigo": 19, "nome": "Lei 14.133/2021, Art. 75, II"},
        {"codigo": 20, "nome": "Lei 14.133/2021, Art. 75, III, a"},
        {"codigo": 21, "nome": "Lei 14.133/2021, Art. 75, III, b"},
        {"codigo": 22, "nome": "Lei 14.133/2021, Art. 75, IV, a"},
        {"codigo": 23, "nome": "Lei 14.133/2021, Art. 75, IV, b"},
        {"codigo": 24, "nome": "Lei 14.133/2021, Art. 75, IV, c"},
        {"codigo": 25, "nome": "Lei 14.133/2021, Art. 75, IV, d"},
        {"codigo": 26, "nome": "Lei 14.133/2021, Art. 75, IV, e"},
        {"codigo": 27, "nome": "Lei 14.133/2021, Art. 75, IV, f"},
        {"codigo": 28, "nome": "Lei 14.133/2021, Art. 75, IV, g"},
        {"codigo": 29, "nome": "Lei 14.133/2021, Art. 75, IV, h"},
        {"codigo": 30, "nome": "Lei 14.133/2021, Art. 75, IV, i"},
        {"codigo": 31, "nome": "Lei 14.133/2021, Art. 75, IV, j"},
        {"codigo": 32, "nome": "Lei 14.133/2021, Art. 75, IV, k"},
        {"codigo": 33, "nome": "Lei 14.133/2021, Art. 75, IV, l"},
        {"codigo": 34, "nome": "Lei 14.133/2021, Art. 75, IV, m"},
        {"codigo": 35, "nome": "Lei 14.133/2021, Art. 75, V"},
        {"codigo": 36, "nome": "Lei 14.133/2021, Art. 75, VI"},
        {"codigo": 37, "nome": "Lei 14.133/2021, Art. 75, VII"},
        {"codigo": 38, "nome": "Lei 14.133/2021, Art. 75, VIII"},
        {"codigo": 39, "nome": "Lei 14.133/2021, Art. 75, IX"},
        {"codigo": 40, "nome": "Lei 14.133/2021, Art. 75, X"},
        {"codigo": 41, "nome": "Lei 14.133/2021, Art. 75, XI"},
        {"codigo": 42, "nome": "Lei 14.133/2021, Art. 75, XII"},
        {"codigo": 43, "nome": "Lei 14.133/2021, Art. 75, XIII"},
        {"codigo": 44, "nome": "Lei 14.133/2021, Art. 75, XIV"},
        {"codigo": 45, "nome": "Lei 14.133/2021, Art. 75, XV"},
        {"codigo": 46, "nome": "Lei 14.133/2021, Art. 75, XVI"},
        {"codigo": 47, "nome": "Lei 14.133/2021, Art. 78, I"},
        {"codigo": 48, "nome": "Lei 14.133/2021, Art. 78, II"},
        {"codigo": 49, "nome": "Lei 14.133/2021, Art. 78, III"},
        {"codigo": 50, "nome": "Lei 14.133/2021, Art. 74, caput"},
        {"codigo": 51, "nome": "Lei 14.284/2021, Art. 29, caput"},
        {"codigo": 52, "nome": "Lei 14.284/2021, Art. 24 § 1º"},
        {"codigo": 53, "nome": "Lei 14.284/2021, Art. 25 § 1º"},
        {"codigo": 54, "nome": "Lei 14.284/2021, Art. 34"},
        {"codigo": 55, "nome": "Lei 9.636/1998, Art. 11-C, I"},
        {"codigo": 56, "nome": "Lei 9.636/1998, Art. 11-C, II"},
        {"codigo": 57, "nome": "Lei 9.636/1998, Art. 24-C, I"},
        {"codigo": 58, "nome": "Lei 9.636/1998, Art. 24-C, II"},
        {"codigo": 59, "nome": "Lei 9.636/1998, Art. 24-C, III"},
        {"codigo": 60, "nome": "Lei 14.133/2021, Art. 75, XVII"},
        {"codigo": 61, "nome": "Lei 14.133/2021, Art. 76, I, a"},
        {"codigo": 62, "nome": "Lei 14.133/2021, Art. 76, I, b"},
        {"codigo": 63, "nome": "Lei 14.133/2021, Art. 76, I, c"},
        {"codigo": 64, "nome": "Lei 14.133/2021, Art. 76, I, d"},
        {"codigo": 65, "nome": "Lei 14.133/2021, Art. 76, I, e"},
        {"codigo": 66, "nome": "Lei 14.133/2021, Art. 76, I, f"},
        {"codigo": 67, "nome": "Lei 14.133/2021, Art. 76, I, g"},
        {"codigo": 68, "nome": "Lei 14.133/2021, Art. 76, I, h"},
        {"codigo": 69, "nome": "Lei 14.133/2021, Art. 76, I, i"},
        {"codigo": 70, "nome": "Lei 14.133/2021, Art. 76, I, j"},
        {"codigo": 71, "nome": "Lei 14.133/2021, Art. 76, II, a"},
        {"codigo": 72, "nome": "Lei 14.133/2021, Art. 76, II, b"},
        {"codigo": 73, "nome": "Lei 14.133/2021, Art. 76, II, c"},
        {"codigo": 74, "nome": "Lei 14.133/2021, Art. 76, II, d"},
        {"codigo": 75, "nome": "Lei 14.133/2021, Art. 76, II, e"},
        {"codigo": 76, "nome": "Lei 14.133/2021, Art. 76, II, f"},
        {"codigo": 77, "nome": "Lei 14.133/2021, Art. 75, XVIII"},
        {"codigo": 78, "nome": "Lei 14.628/2023, Art. 4º"},
        {"codigo": 79, "nome": "Lei 14.628/2023, Art. 12"},
        {"codigo": 80, "nome": "Lei 14.133/2021, Art. 1º, § 2º"},
    ),
}
