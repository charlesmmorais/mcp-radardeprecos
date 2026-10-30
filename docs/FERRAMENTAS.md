# Ferramentas

As 48 ferramentas do mcp-radardeprecos: o que cada uma faz, como funciona e de
onde vêm os dados.

Todas as consultas são anônimas e somente leitura, sobre fontes públicas
oficiais. As únicas operações de escrita são a geração de arquivos de saída
(Excel, Word, CSV, JSON), sempre a pedido do usuário e nunca em sistemas
externos. Nos transportes HTTP, esses arquivos voltam em base64 para o cliente
salvar do lado do usuário; gravar no disco do servidor só é possível no uso
local (`stdio`).

## Fontes consultadas

| Fonte | Endereço | O que oferece |
|---|---|---|
| **PNCP** — Portal Nacional de Contratações Públicas | `pncp.gov.br` | Busca indexada (`/api/search`), API de Consulta oficial (`/api/consulta`) e API PNCP (`/api/pncp`, para itens, resultados, atas e arquivos). |
| **Compras.gov.br** — Dados Abertos | `dadosabertos.compras.gov.br` | Preços praticados, catálogos CATMAT/CATSER, atas, contratos, UASG e SICAF. |
| **SGS / Banco Central** | `api.bcb.gov.br` | Séries de índices de preços (IPCA, IGP-M, IPC-Fipe). |
| **TCU** | `certidoes-apf.apps.tcu.gov.br` | Consulta consolidada de sanções. |
| **BPS / Ministério da Saúde** | `apidadosabertos.saude.gov.br` | Banco de Preços em Saúde: compras de medicamentos e dispositivos médicos por estados, municípios e consórcios. Usa o mesmo catálogo CATMAT do Compras.gov.br. |
| **Receita Federal** | via `brasilapi.com.br`, com fallback para `minhareceita.org` | Cadastro de CNPJ. |
| **Sem acesso externo** | — | Processamento local sobre os dados da própria chamada ou sobre constantes internas. |

**Distribuição por fonte:** PNCP (15), Compras.gov.br (12), sem acesso externo
(15), SGS/BCB (1), TCU (1), BPS/Ministério da Saúde (1), Receita Federal (1),
Compras.gov.br + PNCP (1), Compras.gov.br + SGS/BCB (1).

A contagem considera a fonte efetiva. Quatro ferramentas são **orquestradas** —
chamam outras ferramentas em vez de um cliente HTTP — e recebem a fonte das
ferramentas que consultam: `buscar_pncp_texto_booleano`,
`consultar_familia_contratacao_pncp`, `mapear_fornecedores_mercado` e
`pesquisar_cesta_precos`.

---

## Busca de contratações e contratos

**`buscar_pncp_texto`** — localiza editais, atas ou contratos por texto livre.
*Como:* envia o termo ao índice de busca do PNCP (o mesmo mecanismo do site
pncp.gov.br/app), com filtros opcionais (UF, órgão, modalidade, período,
situação etc.) e janela temporal, e devolve resultados paginados com
`cobertura`. *Fonte:* PNCP — busca indexada (`/api/search`).

**`buscar_pncp_texto_booleano`** — a mesma busca, com lógica E / OU / NÃO.
*Como:* combina termos obrigatórios, alternativos e excluídos sobre a busca
textual — útil para incluir sinônimos e afastar falsos positivos.
*Fonte:* PNCP — busca indexada (orquestrada via `buscar_pncp_texto`).

**`contar_pncp`** — conta registros no índice do PNCP sem exigir termo de
busca. *Como:* responde perguntas de volume ("quantos editais de 2026 no
Paraná?", "quantas contratações com emenda parlamentar?"), separando os valores
`true`, `false` e não informado dos campos booleanos. *Fonte:* PNCP — busca
indexada (`/api/search`).

**`listar_filtros_pncp`** — mostra os filtros (facetas) disponíveis para um tipo
de documento. *Como:* consulta os valores válidos de cada faceta (modalidade,
esfera, UF, órgão, município etc.), com contagens. *Fonte:* PNCP — busca
indexada (`/api/search/filters`).

**`listar_arquivos_pncp`** — lista os arquivos anexos de um processo, com link
de download. *Como:* consulta os documentos anexados a uma contratação, ata ou
contrato (edital, termo de referência, ata, contrato, retificações) e devolve a
URL de download de cada um. *Fonte:* PNCP — API PNCP (`/api/pncp/.../arquivos`).

**`buscar_contratacoes_pncp`** — busca licitações pelo objeto e traz os itens
com preços unitários. *Como:* faz a busca textual e, para cada contratação,
consulta os itens e os resultados, devolvendo o valor **estimado** e o valor
**homologado** por item, separados e rotulados. *Fonte:* PNCP — busca indexada
+ API PNCP (itens e resultados).

**`buscar_contratos_compras`** — busca contratos pelo objeto, com o valor
efetivamente contratado e link. *Como:* busca por texto no índice e, quando
pedido, lista os arquivos de cada contrato. Apesar do nome, a consulta é feita
no PNCP. *Fonte:* PNCP — busca indexada + API PNCP (arquivos).

**`buscar_homologados_14133`** — busca em massa itens homologados de
contratações da Lei 14.133/2021. *Como:* consulta itens e resultados por
catálogo, fornecedor ou órgão, sem precisar abrir contratação por contratação.
*Fonte:* Compras.gov.br — Dados Abertos.

**`consultar_contratacao_pncp`** — detalha uma contratação já conhecida, pelo
identificador. *Como:* dado o número de controle PNCP (ou CNPJ, ano e
sequencial), consulta o detalhe oficial (objeto, modalidade, amparo legal,
situação, valores) e os itens, com links prontos para o PNCP e o sistema de
origem. *Fonte:* PNCP — API de Consulta (detalhe) + API PNCP (itens).

**`consultar_contratos_orgao_pncp`** — listagem exaustiva dos contratos e
empenhos de um órgão. *Como:* dado o CNPJ do órgão e o período, percorre todos
os contratos, fatiando o período e paginando até o fim — não depende de uma
palavra aparecer no objeto. *Fonte:* PNCP — API de Consulta (`/v1/contratos`).

**`consultar_familia_contratacao_pncp`** — consolida a "família" de uma
contratação. *Como:* a partir de uma contratação, reúne edital, arquivos, ata
(se houver) e contratos derivados, cada contrato com seus termos aditivos e
empenhos. *Fonte:* PNCP — API de Consulta + API PNCP (orquestrada).

**`buscar_propostas_abertas`** — lista contratações recebendo propostas agora.
*Como:* consulta as contratações com prazo de propostas aberto até N dias à
frente. Os valores são **estimados** (ainda não há vencedor), e a resposta
avisa isso. *Fonte:* PNCP — API de Consulta (`/v1/contratacoes/proposta`).

**`consultar_notas_fiscais`** — notas fiscais eletrônicas itemizadas de um
contrato. *Como:* a partir dos instrumentos de cobrança de um contrato (ou de um
órgão num período), lista as NF-e e seus itens — o valor efetivamente
**faturado**, um degrau além do homologado. Uso de auditoria, não fonte
primária de pesquisa de preços. *Fonte:* PNCP — API PNCP (instrumentos de
cobrança).

**`consultar_contratos_compras`** — lista os contratos de um órgão, um por
linha, por vigência. *Fonte:* Compras.gov.br — Dados Abertos (módulo de
contratos).

**`consultar_itens_contrato_compras`** — lista os itens de contrato de um
órgão, com preço unitário, por vigência. *Fonte:* Compras.gov.br — Dados
Abertos (módulo de contratos).

**`radar_vencimentos`** — lista contratos ou atas com vigência próxima do fim.
*Como:* consulta as variantes de "fim de vigência" de contratos e atas para
identificar o que vence num horizonte de dias — útil para planejar renovação e
para aderir a atas antes que expirem. Aceita UASG ou órgão (com consulta por
todas as UASGs dele). *Fonte:* Compras.gov.br — Dados Abertos + PNCP (API de
Consulta, atas).

## Atas de registro de preço

**`buscar_arp_compras`** — busca atas de registro de preço por vigência
inicial, com saldo de adesão. *Como:* aceita filtro por item de catálogo, PDM ou
fornecedor aplicado no próprio servidor da fonte. *Fonte:* Compras.gov.br —
Dados Abertos (módulo ARP).

**`consultar_ata_registro_preco`** — detalha uma ata: itens, preços
registrados, fornecedores e arquivos. *Fonte:* PNCP — API PNCP.

**`consultar_arp_detalhe_compras`** — consolida, para um item de ata, as
unidades participantes, adesões (caronas) e empenhos. *Fonte:* Compras.gov.br —
Dados Abertos (módulo ARP).

## Catálogos e órgãos

**`descobrir_codigo_catalogo`** — encontra o código CATMAT/CATSER a partir de
uma descrição em texto livre. *Como:* a API não oferece busca livre, então o
servidor monta um índice a partir dos nomes do catálogo e compara localmente,
com ranking por qualidade (palavra inteira antes de trecho). *Fonte:*
Compras.gov.br — Dados Abertos (catálogo).

**`listar_itens_catalogo`** — lista os itens (com código real) de um PDM ou
classe, com filtro textual. *Fonte:* Compras.gov.br — Dados Abertos (catálogo).

**`navegar_catalogo_servico`** — navega a hierarquia do catálogo de serviços:
seção → divisão → grupo → classe → subclasse. *Fonte:* Compras.gov.br — Dados
Abertos (catálogo de serviços).

**`descobrir_uasg`** — encontra o código de uma UASG ou órgão a partir do nome.
*Como:* a API só filtra por código exato; o servidor lista as UASGs e órgãos
ativos e busca pelo nome localmente. *Fonte:* Compras.gov.br — Dados Abertos.

**`consultar_tabelas_dominio_pncp`** — devolve as tabelas de domínio oficiais
do PNCP (modalidades, amparo legal, tipo de contrato, critério de julgamento,
modo de disputa etc.). *Como:* constantes internas transcritas do Manual do
PNCP. *Fonte:* sem acesso externo.

**`consultar_pca`** — consulta itens planejados no Plano de Contratação Anual.
Sinal de planejamento, **não** referência de preço. *Fonte:* PNCP — API de
Consulta (`/v1/pca`).

## Preços praticados e formação da cesta

**`buscar_precos_praticados_compras`** — busca preços praticados no setor
público para um item de catálogo. *Como:* consulta os valores de compras
públicas concluídas por código CATMAT/CATSER (ou PDM), com filtros de data,
poder e esfera aplicados na fonte e opção de varrer todas as páginas. É a fonte
de maior prioridade da IN 65/2021. *Fonte:* Compras.gov.br — Dados Abertos
(módulo de pesquisa de preço).

**`buscar_precos_saude_bps`** — preços praticados de medicamentos e
dispositivos médicos. *Como:* consulta o Banco de Preços em Saúde por código
CATMAT ou por CNPJ da instituição compradora, com filtros de período, UF,
fornecedor, fabricante, modalidade, genérico e registro Anvisa. Cobre compras de
estados, municípios e consórcios intermunicipais — universo que as fontes
federais alcançam mal e onde está o volume das compras do SUS. É referência
nacional para cotação em saúde (Resolução de Consolidação CIT nº 1/2021) e
complementa, sem substituir, as fontes gerais. A origem não informa o total de
registros, então a cobertura nunca é declarada completa. *Fonte:* BPS /
Ministério da Saúde.

**`pesquisar_cesta_precos`** — pesquisa preços de vários itens de uma vez, com
total da cesta. *Como:* para cada item, busca preços praticados, opcionalmente
corrige por índice para uma data-base única e calcula o preço de referência;
depois soma o total. *Fonte:* Compras.gov.br + SGS/BCB (orquestrada).

**`montar_cesta_precos`** — monta a série de preços a partir dos registros de
uma busca. *Como:* recebe os registros que uma busca já devolveu e extrai a
série de preços unitários, preservando o contexto e separando o que não tem
preço válido — sem transcrição manual. *Fonte:* sem acesso externo.

**`converter_para_unidade_base`** — converte preços praticados para a unidade
base do catálogo. *Como:* o mesmo código de catálogo reúne preços em unidades
de fornecimento diferentes (a unidade avulsa, o pacote com 50, a caixa com 45
pacotes). O fator vem da capacidade registrada no próprio catálogo, não de
heurística sobre a descrição; quando ela não é interpretável com segurança, o
preço vai para `nao_convertidos` com o motivo, em vez de assumir fator 1.
*Fonte:* Compras.gov.br — Dados Abertos (unidades de fornecimento e de medida).

**`normalizar_precos_unidade`** — converte uma lista de preços para uma unidade
comum (ex.: usuário/mês, licença/ano). *Como:* aplica os fatores informados,
registrando fórmula, premissas e confiança de cada conversão; não assume fator
ausente. *Fonte:* sem acesso externo.

**`agrupar_por_comparabilidade`** — agrupa os preços por unidade, quantidade e
período e classifica cada um na escala A–D em relação ao objeto pesquisado,
com estatística por grupo e um grupo de não comparáveis. Passo recomendado antes
do cálculo. *Fonte:* sem acesso externo.

**`detectar_inconsistencias`** — sinaliza armadilhas nos registros (quantidade 1
num lote, homologado acima do estimado, unitário que parece global, objeto
composto etc.). Informativa: nunca descarta nada. *Fonte:* sem acesso externo.

## Cálculo e correção monetária

**`calcular_preco_referencia`** — calcula o preço de referência a partir da
cesta. *Como:* o padrão é o **escore Z iterativo**, governado pelo coeficiente
de variação: com CV inicial de até 25% nada é removido (série homogênea não tem
outlier a tratar); acima disso, remove um valor por iteração — o de maior |Z| —
e recalcula o CV até atingir a meta, o piso de 3 referências ou o limite de
iterações. Toda execução informa `motivo_parada_saneamento`, o CV antes e
depois, o `percentual_excluido` e o `historico_saneamento`, com uma linha por
exclusão. Quando a série parece misturar dois objetos sob o mesmo código de
catálogo, o resultado sai com `status_resultado: "nao_apto"` e
`apto_para_preco_referencia: false`: o preço fica preservado para auditoria,
mas marcado, porque remover outlier ali não limpa ruído, escolhe um dos grupos
em silêncio. Média saneada (Acórdão TCU 355/2019-P, em passe único), mediana e
mínimo continuam disponíveis. *Fonte:* sem acesso externo.

**`atualizar_precos_indice`** — atualiza preços históricos por um índice.
*Como:* busca a série do índice escolhido (IPCA, IGP-M ou IPC-Fipe) no SGS do
Banco Central e aplica o fator acumulado até a data-base. *Fonte:* SGS / Banco
Central.

## Estudo de mercado e classificação

**`mapear_fornecedores_mercado`** — mostra quem vem fornecendo determinado
objeto ao setor público, a partir de texto livre. *Como:* busca contratações no
PNCP e consolida os fornecedores dos resultados adjudicados. É a pergunta que
antecede o preço, típica do Estudo Técnico Preliminar: antes de estimar quanto
custa, saber se há mercado. Lista quem **venceu**, não quem participou —
propostas perdedoras não são publicadas, e ausência na lista não significa
incapacidade de fornecer. Os dois limites acompanham o resultado em `avisos`.
*Fonte:* PNCP (orquestrada via `buscar_contratacoes_pncp`).

**`classificar_curva_abc`** — classifica os itens de uma compra em grupos A, B e
C por valor acumulado (Pareto 80/95), para dosar o esforço de pesquisa.
*Fonte:* sem acesso externo.

**`classificar_objeto_tic`** — indica, por palavra-chave, se um objeto é de TIC
e se aparenta ser SaaS, com aviso de precisão limitada. *Fonte:* sem acesso
externo.

**`gerar_estudo_mercado_tic`** — monta a matriz de comparabilidade de soluções
de TIC candidatas (Estudo de Mercado do ETP, Art. 11, VI, da IN SGD/ME nº
94/2022). *Fonte:* sem acesso externo.

## Due diligence de fornecedor

**`consultar_cnpj`** — consulta o cadastro de um CNPJ na Receita Federal:
situação, atividade, endereço e quadro societário. *Como:* tenta a BrasilAPI e,
se ela falhar, a MinhaReceita; o resultado fica em cache por um dia. *Fonte:*
Receita Federal (via BrasilAPI / MinhaReceita).

**`consultar_situacao_fornecedor`** — consulta a situação de um fornecedor no
SICAF. *Como:* verifica se o cadastro está ativo e se consta habilitado a
licitar — dado que só existe no SICAF, não no cadastro da Receita. *Fonte:*
Compras.gov.br — Dados Abertos (SICAF).

**`consultar_sancoes_fornecedor`** — consulta sanções e idoneidade de uma pessoa
jurídica. *Como:* numa única consulta consolidada do TCU, verifica quatro bases
federais: Licitantes Inidôneos (TCU), CNIA (CNJ), CEIS e CNEP (Portal da
Transparência) — este último sem exigir chave de API, porque o próprio TCU faz a
ponte. *Fonte:* TCU.

## Diretrizes, formalização e exportação

**`obter_diretrizes_pesquisa_precos`** — devolve as premissas metodológicas de
uma pesquisa de preços: fases, fontes prioritárias, regras de amostra, métodos
de cálculo e checklist de formalização, com base na IN SEGES/ME 65/2021 e na
jurisprudência do TCU. *Fonte:* sem acesso externo.

**`gerar_memoria_pesquisa`** — consolida a pesquisa num documento único de
formalização. *Como:* reúne objeto, responsável, fontes, buscas frustradas,
cálculo e correção monetária (fornecidos) num documento em JSON ou Markdown.
*Fonte:* sem acesso externo.

**`gerar_relatorio_excel`** — gera a planilha (.xlsx) da pesquisa, em quatro
abas, a partir da memória e do cálculo. Pendências ficam marcadas na célula.
*Fonte:* sem acesso externo.

**`gerar_relatorio_word`** — gera o documento (.docx) de formalização conforme
os elementos I a VIII do Art. 3º da IN 65/2021, como rascunho com pendências
marcadas para revisão. *Fonte:* sem acesso externo.

**`exportar_resultados`** — exporta os registros de qualquer busca para CSV ou
XLSX, achatando campos aninhados. *Fonte:* sem acesso externo.

**`exportar_trilha_auditoria`** — gera o dossiê de proveniência da pesquisa.
*Como:* reúne, para cada consulta feita às fontes nesta sessão do servidor, a
URL, os parâmetros, o horário, o status e o hash SHA-256 da resposta, mais um
hash de reprodutibilidade do conjunto. A trilha fica em memória e zera quando o
servidor reinicia. *Fonte:* sem acesso externo.

---

## Recurso e prompt

**Recurso `docs://boas-praticas-pesquisa-precos`** — as premissas
metodológicas da pesquisa de preços em Markdown, para leitura corrida. Mesmo
conteúdo de `obter_diretrizes_pesquisa_precos`. Sem acesso externo.

**Prompt `conduzir_pesquisa_precos`** — roteiro que orquestra as ferramentas na
ordem recomendada, do objeto até a formalização. Sem acesso externo.
