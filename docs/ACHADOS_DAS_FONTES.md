# Achados das fontes oficiais

Registro do que se sabe sobre o comportamento real das APIs consumidas por
este servidor, separando **o que foi medido** do **que foi lido em
documentação e ainda não confirmado**. A distinção é o ponto do documento:
este projeto já reverteu três otimizações construídas sobre suposições
plausíveis e não verificadas.

As seções trazem, quando é o caso, um bloco **Status** dizendo se o achado já
virou correção no código. Achado registrado não é achado resolvido, e o
documento perde a serventia se confundir os dois.

Última revisão: **2026-09-07**.

---

## Como ler este documento

| Marca | Significado |
| --- | --- |
| **MEDIDO** | Verificado por chamada real, com data. É fato. |
| **DOCUMENTADO** | Lido em manual ou especificação oficial. Ainda não exercitado. |
| **PENDENTE** | Precisa de teste ao vivo para decidir. |

---

## 1. CNPJ alfanumérico — CORRIGIDO (06/09/2026)

> **Status.** A correção está feita: regra única em
> `utils/documentos.py`, o BPS não mutila mais letras, as três tools que
> rejeitavam passaram a aceitar, e há aviso explícito quando a entrada é
> alfanumérica. O que **continua pendente** é a verificação de como as
> **fontes** se comportam com o formato novo — daí o aviso. O diagnóstico
> abaixo fica como registro do defeito.

**DOCUMENTADO** — Manual de Integração do PNCP, versão 2.5 (11/06/2026).

A Receita Federal passou a emitir **CNPJ com letras** para inscrições novas,
por esgotamento da faixa numérica. A atribuição começou em **julho de 2026** e
vale apenas para inscrições novas; os CNPJ existentes permanecem numéricos.

Estamos em setembro. CNPJ alfanuméricos já circulam.

### O que quebra no nosso código

Cinco pontos assumem que CNPJ é numérico, com comportamentos diferentes:

| Onde | Comportamento | Gravidade |
| --- | --- | --- |
| `clients/bps_client.py` (`_limpar`) | Remove as letras e consulta o número mutilado | **Falha silenciosa** |
| `tools/consultar_cnpj.py` | `raise ValueError` se não forem 14 dígitos | Erro explícito |
| `tools/consultar_contratos_orgao_pncp.py` | `raise ValueError` idem | Erro explícito |
| `tools/consultar_situacao_fornecedor.py` | `raise ValueError` idem | Erro explícito |
| `clients/tcu_client.py`, `clients/cnpj_client.py` | Docstrings dizem "14 dígitos" | Documentação |

O caso do BPS é o pior: `12AB34...` vira `1234...`, e a consulta retorna
resultado **de outro CNPJ ou vazio**, sem qualquer indicação de que a entrada
foi alterada. É a mesma família dos defeitos que este projeto vem encontrando
— a suposição de formato que só falha em parte dos dados.

### PENDENTE

- Alguma das APIs já devolve CNPJ alfanumérico em resposta? (Não verificável
  em 05/09: PNCP em indisponibilidade prolongada.)
- As APIs aceitam CNPJ alfanumérico como parâmetro de consulta?
- Qual o formato exato — quais posições admitem letra, como fica o dígito
  verificador.

---

## 2. Afirmação incorreta no nosso código: tabelas de domínio

> **Status.** A afirmação foi corrigida, sem mudança de
> comportamento: a tool continua pura. Trocou-se uma certeza falsa por uma
> dúvida honesta — os endpoints existem no manual, mas **não foi verificado**
> se respondem sem autenticação. As pendências abaixo seguem de pé.

**DOCUMENTADO** — Manual do PNCP, seção 7, versão 2.6.

A docstring de `consultar_tabelas_dominio_pncp` afirmava que as tabelas são
*"constantes internas transcritas do Manual do PNCP (não há endpoint REST para
elas)"*.

O manual documenta endpoints REST para praticamente todas:

```
GET /v1/modalidades                    GET /v1/modalidades?statusAtivo=true
GET /v1/instrumentos-convocatorios
GET /v1/modos-disputa
GET /v1/criterios-julgamento
GET /v1/tipos-contrato
GET /v1/tipos-documento
GET /v1/amparos-legais
GET /v1/categorias-item
GET /v1/portes-empresa                 (novo na versão 2.5)
```

Cada um tem também a variante "por código". Os exemplos em cURL não mostram
cabeçalho de autenticação, apenas `accept: */*`.

O parâmetro `statusAtivo` indica que **há itens desativados ao longo do
tempo** — algo que uma transcrição congelada não acompanha. As constantes
internas podem estar divergindo da fonte sem que ninguém perceba.

### PENDENTE

- O `BASE_URL` do manual é o público (`/api/pncp`) ou o da API autenticada de
  integração? O manual é de *integração*, o que torna a dúvida legítima.
- Se público: corrigir a docstring e avaliar substituir as constantes por
  consulta com cache longo, mantendo as internas como fallback.

---

## 3. Tabelas de conformidade normativa

**DOCUMENTADO** — Manual do PNCP, seções 7.35 a 7.39.

Duas famílias que o projeto não usa, e que respondem a uma pergunta hoje
resolvida por consulta jurídica: *quais combinações são válidas?*

```
GET /v1/instrumento-convocatorio-modalidade-amparo-legal
GET /v1/tipo-instrumento-convocatorio-modo-disputa
GET /v1/tipo-instrumento-convocatorio-modo-disputa?tipoInstrumentoConvocatorioId=1
GET /v1/tipo-instrumento-convocatorio-modo-disputa?tipoInstrumentoConvocatorioId=1&modoDisputaId=1
```

O filtro encadeado permite três perguntas: todas as combinações válidas, as
válidas para um instrumento, e a verificação de um par específico.

É validação normativa servida pela própria fonte oficial — não tabela
estática.

---

## 4. Intenção de Registro de Preços (IRP)

**DOCUMENTADO** — Manual do PNCP, versão 2.6 (31/08/2026). Família nova.

A IRP é a etapa **anterior ao edital**: o órgão gerenciador divulga
formalmente suas demandas e coleta manifestações de interesse de órgãos
participantes, consolidando quantitativos e especificações antes de licitar.

Sete endpoints de consulta (os demais são de escrita, fora do escopo deste
servidor):

- Consultar Intenção de Registro de Preço
- Consultar Todos os Itens da IRP
- Consultar Item da IRP
- Consultar Quantidade de Itens da IRP
- Consultar Histórico da IRP
- Consultar Dados de Todos os Documentos de uma IRP
- Baixar Arquivo/Documento de IRP

### Por que interessa

Para Estudo Técnico Preliminar, é informação que **nenhuma fonte atual do
projeto oferece**: o que outros órgãos estão prestes a comprar, com
quantitativos e especificações declarados. Antecede até o PCA em
especificidade, porque já traz item e quantidade consolidados.

### MEDIDO — o índice de busca já carrega campos de IRP

Em consulta de 04/09/2026 (`buscar_pncp_texto`, termo "material de limpeza"),
os registros vieram com:

```json
"tipo_item_irp": null, "prazo_manifestacao_interesse": null
```

Os campos existem no índice e **o nosso mapeamento os ignora**. Não sabemos
ainda se vêm preenchidos em documentos de IRP.

### PENDENTE

- Ler os endpoints de consulta na versão multipágina do manual
  (`https://pncp.gov.br/manual/pt-br/latest/irp/`) — o `singlehtml` trunca
  antes da seção 10.
- Verificar se o índice de busca indexa documentos de IRP e, em caso
  positivo, se `tipo_item_irp` vem preenchido.

---

## 5. ALICE — analisador de licitações na API aberta

**DOCUMENTADO** — OpenAPI viva do Compras.gov.br (`/v3/api-docs`, lida em
05/09/2026).

```
"98 - ALICE": "Serviços de integração Analisador de Licitações,
               Contratos e Editais (Alice) e Compras.gov."
```

Três endpoints, nenhum consumido pelo projeto:

```
GET /alice/compras
GET /alice/tickets
GET /alice/avisos-restritos
```

O ALICE analisa editais e sinaliza irregularidades. A existência desses
endpoints na API aberta significa que **análise automatizada de licitações já
é consultável programaticamente**.

### PENDENTE

- Exigem autenticação? O nome `avisos-restritos` sugere acesso controlado.
- Que dados retornam — o resultado da análise, ou apenas metadados do ticket?
- Qual a cobertura: todas as compras, ou um recorte?

---

## 6. Indicadores do Compras.gov.br

**DOCUMENTADO** — mesma especificação.

```
GET /modulo-indicadores/1_consultarIndicadoresConsolidados
GET /modulo-indicadores/2_consultarIndicadoresPorPeriodo
```

Não consumidos. Sem ler os parâmetros, não se sabe se são indicadores de
desempenho, de economicidade ou de outra natureza.

---

## 7. Outras novidades do PNCP, por versão

| Versão | Data | O que trouxe |
| --- | --- | --- |
| 2.6 | 31/08/2026 | IRP (família completa); correções de obrigatoriedade em `sequencialAta` e `percentualDesconto` |
| 2.5 | 11/06/2026 | CNPJ alfanumérico; campos novos de fornecedor (localidade, Cadastro de Reserva/Remanescente); tabela de Porte de Empresa |
| 2.4 | 09/04/2026 | Emendas parlamentares em empenho; **empenho como entidade própria**, com endpoints separados dos de contrato; tabelas de Tipo de Contrato e Tipo de Documento |
| 2.3.11 | 18/03/2026 | Identificação de contratos oriundos de ata de registro de preços, com as partes envolvidas |

Dois pontos merecem atenção além do já tratado:

**Empenho como entidade própria** (2.4) — hoje o projeto trata empenho como um
`tipo_contrato` dentro de contratos. Funciona, mas ignora `Consultar
Empenhos` e `Consultar Empenho pelo Número Sequencial`.

**Contratos oriundos de ARP identificáveis** (2.3.11) — para rastrear adesões
e carona, é dado que hoje precisamos inferir.

---

## 8. Achados de disponibilidade

**MEDIDO** — 04 e 05/09/2026.

O PNCP apresentou indisponibilidade intermitente e prolongada, com `503
Service Unavailable` do balanceador. Confirmado por **quatro caminhos de rede
independentes**: dois servidores em provedores diferentes, requisição direta
e navegador do usuário. A indisponibilidade atingiu também o site do manual.

Somado à recusa por User-Agent medida em 21/08 (cerca de 70% das requisições
legítimas rejeitadas antes de alcançar o índice), o quadro sobre a fonte
oficial não é de incidente isolado.

**Consequência para pesquisa de preços:** uma varredura iniciada durante uma
queda parcial devolve amostra incompleta. É por isso que as ferramentas deste
projeto declaram cobertura em vez de afirmar completude — mas quem consulta o
portal pela tela não tem esse aviso.

---

## 9. Catálogo oficial de endpoints — e o que ele não diz

**MEDIDO** — 05/09/2026.

A página *Documentação Interativa da API de Dados Abertos* do Portal de
Compras publica um **catálogo curado** de 11 módulos e **67 endpoints**, com
descrição, formato e **critérios de aceite por endpoint**. Publicada em
28/05/2026, atualizada em 08/07/2026.

O critério de aceite repetido em praticamente todos os endpoints é:

> Tempo de resposta inferior a 3 segundos em condições normais de operação.

É a primeira expectativa de desempenho **declarada pela própria fonte** que
este projeto encontra. Vale citar na resposta ao TCU: nossas medições de
latência passam a ter um parâmetro oficial de comparação, em vez de serem
apenas números nossos.

### O catálogo é servido de um ambiente de desenvolvimento

A página em `gov.br` não tem conteúdo próprio: é um *iframe* para

```
https://portaldadosabertos-dev.gestao.gov.br/catalogo-embed.html
https://portaldadosabertos-dev.gestao.gov.br/notificacoes-embed.html   (Central de Notificações)
```

O host termina em **`-dev`**. A documentação oficial de produção depende de um
host nomeado como ambiente de desenvolvimento. Não é conclusão sobre a
qualidade do serviço — é uma dependência frágil de um endereço que ninguém
prometeu manter.

Consequência prática: o conteúdo do catálogo **não é obtido por `fetch`
simples**; a página é renderizada por JavaScript e os dados vivem no bundle
`assets/documentacao-page-*.js`, cujo nome tem *hash*. Qualquer automação em
cima dele quebra no próximo build.

### Catálogo e especificação divergem

| | Endpoints |
| --- | --- |
| Catálogo curado (`catalogo-embed`) | 67 |
| OpenAPI viva (`/v3/api-docs`) | 77 |

**Só na especificação, ausentes do catálogo:**

```
97 - INDICADORES   /modulo-indicadores/1_consultarIndicadoresConsolidados
                   /modulo-indicadores/2_consultarIndicadoresPorPeriodo
98 - ALICE         /alice/compras   /alice/tickets   /alice/avisos-restritos
99 - USUARIOS      /usuarios/criar  /usuarios/consultar
                   /usuarios/atualizar/{id}  /usuarios/resetSenha/{id}
AUTENTICACAO       POST /autenticacao/login
```

As duas primeiras famílias já constam das seções 5 e 6 deste documento. As
duas últimas são novas aqui e merecem registro pelo que são: **endpoints de
criação de usuário, consulta de usuários, atualização, redefinição de senha e
login, declarados na especificação pública de uma API de dados abertos.**

Este projeto **não os exercitou e não pretende exercitar** — são de escrita e
de autenticação, fora do escopo de um servidor de consulta, e sondá-los seria
indistinguível de tentativa de acesso indevido. O achado é a *declaração* na
spec pública, não o comportamento. Se houver interlocução com a equipe do
Compras.gov.br, é um ponto a levantar por escrito.

**Só no catálogo, ausente da especificação:**

```
/modulo-pgc/3_consultarPgcAgregacao_CSV      →  404 Resource not found   (MEDIDO 05/09)
```

O catálogo publica um endpoint que não existe. Provável erro de nomenclatura
— os demais pares CSV usam sufixo `N.1`, este usa `3`. É o mesmo padrão de
falso negativo que o projeto persegue: quem seguir o catálogo recebe 404 e não
tem como saber se o dado não existe ou se o caminho está errado.

---

## 10. Exportação em CSV — oito endpoints que não usamos

**MEDIDO** — 05/09/2026, chamada real bem-sucedida.

O catálogo revelou variantes `_CSV` dos endpoints de maior volume:

```
/modulo-pesquisa-preco/1.1_consultarMaterial_CSV
/modulo-pesquisa-preco/2.1_consultarMaterialDetalhe_CSV
/modulo-pesquisa-preco/3.1_consultarServico_CSV
/modulo-pesquisa-preco/4.1_consultarServicoDetalhe_CSV
/modulo-pgc/1.1_consultarPgcDetalhe_CSV
/modulo-pgc/2.1_consultarPgcDetalheCatalogo_CSV
/modulo-uasg/1.1_consultarUasg_CSV
/modulo-uasg/2.1_consultarOrgao_CSV
```

Nenhuma é consumida pelo projeto (`grep _CSV` no `src/` não retorna nada fora
dos `_FimVigencia`, que já usamos). O critério de aceite declarado é
*"preservação dos filtros e parâmetros equivalentes ao endpoint principal"* —
ou seja, não é um recorte reduzido.

### Chamada verificada

```
GET /modulo-pesquisa-preco/1.1_consultarMaterial_CSV
    ?pagina=1&tamanhoPagina=10&tipo=codigoItemCatalogo&codigo=267203
→ 200, text/csv, 37 colunas
```

O parâmetro `tipo` **não é `M`/`S`** como nos endpoints JSON irmãos: é um enum
`["codigoItemCatalogo", "codigoPdm"]`. Passar `M` devolve **HTTP 500** com
stack trace de conversão de enum do Spring — não 400. Erro de cliente
reportado como erro de servidor.

### Armadilhas de formato do CSV (MEDIDO na mesma resposta)

| O que | Valor observado | Risco |
| --- | --- | --- |
| Separador | `;` | não é vírgula |
| Decimal | vírgula — `0,11` | parser ingênuo lê errado |
| Milhar | ponto — `273.000,00` | idem |
| Ausência | string literal `null` | vira o texto `"null"`, não vazio |
| `capacidadeUnidadeFornecimento` | `0,00` | **exatamente o campo de um defeito jÃ¡ corrigido** |

O último merece atenção: a correção `_capacidade_texto` trata `0` numérico
vindo do JSON. No CSV o mesmo campo chega como `"0,00"` — *truthy*, string,
e passaria direto por aquela guarda, produzindo rótulos como
`"COMPRIMIDO 0,00"`. Se o CSV for adotado, a correção precisa ser estendida,
não reaproveitada.

### Por que interessa

Para varredura ampla — estudos de mercado, auditorias — o
CSV elimina o custo de paginar JSON e desserializar. Mas troca um problema
conhecido por um novo: perde-se a tipagem, e todo o cuidado que o projeto tem
com "campo ausente ≠ campo zero" precisa ser refeito sobre texto.

**Recomendação:** não migrar. Avaliar o CSV apenas como caminho alternativo
para as varreduras grandes, mantendo o JSON como fonte da verdade — e só
depois de escrever o parser com as cinco armadilhas acima cobertas por teste.

---

## 11. Outras portas do Portal de Dados Abertos ainda não estudadas

**DOCUMENTADO** — menu do Portal, lido em 05/09/2026.

Itens que existem e que o projeto nunca examinou:

| Item | Endereço |
| --- | --- |
| Explorador de Dados | `gov.br/compras/.../explorador-de-dados` |
| Repositório CSV (dumps completos) | `repositorio.dados.gov.br/seges/comprasgov/` |
| Pesquisa de Preços em Dados Abertos | `suportedadoslivres.streamlit.app` |
| IA em Compras Públicas | `gov.br/compras/.../inteligencia-artificial-em-compras-publicas` |
| Central de Notificações | `portaldadosabertos-dev.gestao.gov.br/notificacoes-embed.html` |

Dois pesam mais:

- **Repositório CSV** — se houver dumps periódicos completos, muda a
  estratégia de varredura: baixa-se o conjunto e consulta-se localmente, sem
  depender da disponibilidade da API (seção 8).
- **IA em Compras Públicas** — página institucional do órgão sobre o uso de
  inteligência artificial nas compras públicas.

---

## 12. Manual do Usuário da API do Compras.gov.br, versão 2.0

**DOCUMENTADO + MEDIDO** — manual de 135 páginas, versão 2.0 (fev/2026,
arquivo modificado em 23/07/2026), Coordenação de Transparência e Informações
Gerenciais (Cotin/CGGES/Delog/Seges/MGI). Tudo abaixo com verificação ao vivo
em 05/09/2026.

O histórico de versões do próprio manual aponta o que mudou desde a 1.0
(04/2025): ARP com intervalos `Min`/`Max` de vigência e três endpoints novos
(unidades, empenhos, adesões) — **já consumidos pelo projeto** desde
2026-07-09; `orgaoEntidadeCnpj` em Contratações — **já consumido**; e
`pertence14133` no Legado, que **não usamos**.

O que segue são os achados que o manual expôs e que a leitura anterior da
especificação não tinha revelado.

### 12.1 `contratacaoExcluida` — contratações desconsideradas entram na conta

**MEDIDO.** Mesma janela (`codigoModalidade=6`, publicação de 01 a
05/08/2026), variando só o filtro:

| Consulta | `totalRegistros` |
| --- | --- |
| sem o parâmetro | **980** |
| `contratacaoExcluida=false` | 978 |
| `contratacaoExcluida=true` | 2 |

980 = 978 + 2. **Sem o filtro, a API devolve também as contratações
desconsideradas/excluídas.**

São 0,2% da amostra nesta janela, e é justamente isso que torna o problema
sério: pequeno demais para saltar aos olhos numa conferência manual, e
suficiente para contaminar uma média. Um preço vindo de contratação anulada
não deveria compor referência.

### Correção de escopo (06/09/2026) — o problema é pior e fica noutro lugar

A primeira redação desta seção dizia que "não enviamos o parâmetro e não
projetamos o campo", sugerindo que bastava passar a enviá-lo para limpar a
pesquisa de preço. **Está errado.** Verificação endpoint por endpoint na
especificação viva:

| Endpoint | Filtro `contratacaoExcluida`? | Campo na resposta? |
| --- | --- | --- |
| `1_consultarContratacoes` (cabeçalho) | **Sim** | **Sim** |
| `2_consultarItensContratacoes` | Não | Não |
| `3_consultarResultadoItens` | Não | Não |

Os endpoints que alimentam a pesquisa de preço são o **2** e o **3**. Neles
não há como excluir os itens de uma contratação desconsiderada **nem como
identificá-los**. O endpoint 1, o único que oferece o filtro, era consumido
por `consultar_contratacoes_lei14133`, função de cliente reservada para uso
futuro e não ligada a nenhuma tool.

Ou seja: não era um parâmetro esquecido, era um **buraco estrutural na
API**. A correção faz o que é possível — envia `false`
por padrão no endpoint 1 (preventivo) e faz `buscar_homologados_14133`
declarar o limite num aviso, apontando `situacaoCompraItem` e
`motivoCancelamento` como os sinais de nível de ITEM disponíveis, próximos
mas não equivalentes à exclusão da contratação inteira.

Fica registrada também a correção de rota deste documento: a primeira leitura
generalizou de um endpoint para a família inteira, que é o mesmo erro
cometido na seção 2 a respeito das tabelas de domínio. Ler a especificação
endpoint por endpoint não é preciosismo.

### 12.2 `dataAualizacaoPncp` — o parâmetro documentado não funciona, e o que funciona não existe

**MEDIDO.** A especificação declara, em
`/modulo-contratacoes/1_consultarContratacoes_PNCP_14133`:

```json
{"name":"dataAualizacaoPncp","in":"query","description":"YYYY-MM-DD"}
```

`Aualizacao`, sem o "t". O manual reproduz a mesma grafia — em parâmetro e no
exemplo de retorno. Testando na mesma janela das 980:

| O que foi enviado | Resultado |
| --- | --- |
| `parametroQueNaoExiste=abc` (controle) | 980 — ignorado |
| `dataAualizacaoPncp=2026-08-03` (**o documentado**) | **980 — idêntico ao controle** |
| `dataAtualizacaoPncp=2026-08-03` (grafia correta, **não documentada**) | **0** |
| idem, para 01/08, 04/08, 15/08 e 01/09 | 0 em todas |

Leitura honesta dos números: o parâmetro **documentado é inerte** — comporta-se
exatamente como um nome inventado. A grafia correta **é processada** (não seria
0 se fosse ignorada, seria 980), mas devolveu vazio para todas as datas
tentadas, inclusive dentro da janela.

Conclusão: **nenhuma das duas grafias filtra de forma utilizável.** Uma não
faz nada e devolve tudo; a outra faz alguma coisa e devolve nada. Para quem
chama, as duas são indistinguíveis de uma resposta legítima — a primeira
parece um filtro largo, a segunda parece ausência de dados.

O endpoint irmão `2_consultarItensContratacoes_PNCP_14133` usa
`dataAtualizacaoPncp`, com o "t". **Os dois vizinhos grafam o mesmo conceito
de formas diferentes.** Quem normalizar os nomes entre eles quebra um dos
dois, sem erro.

Não usamos nenhum dos dois hoje. **Recomendação: não adotar** até que o
comportamento seja esclarecido com a equipe do Compras.gov.br.

### 12.3 `bps` — a ponte entre o CATMAT e o Banco de Preços em Saúde

**MEDIDO.** Parâmetro booleano que o projeto desconhecia, presente em **três**
endpoints:

```
/modulo-material/3_consultarPdmMaterial              bps=true → 7.549 PDMs
                                                     bps=false → 20.430 PDMs
/modulo-material/4_consultarItemMaterial
/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133
```

Descrição oficial: *"Indica se o PDM está relacionado ao Banco de Preços em
Saúde (BPS)"*.

Isto resolve um problema concreto da tool `buscar_precos_saude_bps`.
Hoje, ao consultar um CATMAT que o BPS não cobre, ela devolve vazio — e
vazio é ambíguo: pode ser "não há compras registradas" ou "este item nunca
esteve no escopo do BPS". Com `bps`, a resposta passa a poder dizer **qual das
duas** — que é exatamente a distinção que este projeto persegue desde o
início.

O terceiro endpoint vai além: permite recortar os itens de contratações da
14.133 para os de saúde cobertos pelo BPS, viabilizando comparação direta
federal × BPS sobre o mesmo universo.

**É o achado de maior valor agregado desta leitura.** Ao contrário do 12.1,
não corrige um erro — remove uma ambiguidade.

### 12.4 `codigo_ncm` — e a inconsistência de nomenclatura da própria API

**MEDIDO.** `GET /modulo-material/4_consultarItemMaterial?codigo_ncm=30049099`
→ **1.312 itens CATMAT**, HTTP 200.

O parâmetro é **`codigo_ncm`, em snake_case** — único caso assim numa API que
é camelCase em todo o resto. O endpoint
`2_consultarItensContratacoes_PNCP_14133` chama o mesmo conceito de
**`codigoNCM`**. E o manual documenta apenas a segunda grafia.

Na mesma família há ainda `codFornecedor` e `codItemCatalogo` — abreviados,
enquanto os vizinhos usam `codigo...` por extenso.

Utilidade: a NCM é a chave que liga o item de catálogo público a preços de
mercado, notas fiscais e dados tributários. É o gancho mais direto que existe
para confrontar preço público com preço privado.

### 12.5 Filtros de comparabilidade que não usamos

Em `/modulo-contratacoes/3_consultarResultadoItensContratacoes_PNCP_14133`:

```
aplicacaoMargemPreferencia
aplicacaoBeneficioMeepp
aplicacaoCriterioDesempate
situacaoCompraItemResultadoId
porteFornecedorId   naturezaJuridicaId   codigoPais
```

Os três `aplicacao*` importam por um motivo metodológico: **um preço obtido
com margem de preferência aplicada, ou sob benefício de ME/EPP, não é
diretamente comparável a um preço de disputa aberta.** Hoje misturamos os dois
sem sinalizar. Os filtros de faixa de valor
(`valorUnitarioHomologadoInicial`/`Final`) desta mesma família **já são
usados**.

### 12.6 Defeito de redação no manual

Página 97, tabela de parâmetros de `2_consultarItensContratacoes`:

> `situacaoCompraItem` — *"Número do CNPJ da entidade do órgão"*

A descrição é a do `orgaoEntidadeCnpj`, logo acima. Erro de cópia. Registrado
porque este documento existe para separar o que foi lido do que foi medido: o
manual é fonte oficial, não é fonte confiável campo a campo.

### 12.7 Resumo do que fazer

| Achado | Natureza | Situação |
| --- | --- | --- |
| `contratacaoExcluida` (12.1) | Buraco na API | **FEITO** — `false` por padrão no cabeçalho e aviso de limite no caminho de preço |
| `bps` (12.3) | Ambiguidade removível | Pendente — usar para distinguir "sem compras" de "fora do escopo" |
| `codigo_ncm` (12.4) | Recurso novo | Pendente — avaliar; atenção às duas grafias |
| `pertence14133` (histórico) | Recurso novo | Pendente — avaliar no módulo Legado |
| `aplicacao*` (12.5) | Comparabilidade | Pendente — ao menos projetar, para o usuário ver |
| `dataA(t)ualizacaoPncp` (12.2) | Armadilha | **Não adotar**; levar à fonte |

---

## 13. Pendências de verificação

Ordem sugerida, quando o PNCP voltar:

1. **`GET /v1/modalidades`** — decide o item 2. Se responder sem
   autenticação, a docstring está errada e as constantes podem estar
   desatualizadas.
2. **CNPJ alfanumérico** — a correção do item 1 não depende do PNCP e pode
   ser feita antes; a verificação de como as APIs se comportam, sim.
3. **`possui_emenda_parlamentar`** — comparar a contagem com `true`, com
   `false` e sem o parâmetro. Se os três derem o mesmo total, o filtro é
   decorativo. Solicitado em 05/09 e não executado por indisponibilidade.
4. **IRP** — ler os endpoints na versão multipágina do manual.
5. **ALICE** — testar `/alice/compras` e verificar exigência de
   autenticação.
6. **Repositório CSV** (`repositorio.dados.gov.br/seges/comprasgov/`) —
   verificar se há dumps completos e com que periodicidade. É a única
   pendência que pode reduzir a dependência de disponibilidade da API.
7. **Página "IA em Compras Públicas"** — ler e avaliar o que se aplica a
   este projeto.

8. **`dataAtualizacaoPncp`** (seção 12.2) — esclarecer com a equipe do
   Compras.gov.br por que a grafia documentada é inerte e a correta devolve
   vazio. É a única pendência que não se resolve por teste — já foi testada.

Fora da lista, deliberadamente: os endpoints `99 - USUARIOS` e
`AUTENTICACAO` da seção 9. Não serão sondados.

### Correções já feitas (06/09/2026)

Com testes de regressão:

1. **CNPJ alfanumérico** (seção 1) — regra única em `utils/documentos.py`;
   o BPS deixou de mutilar letras; as três tools que rejeitavam passaram a
   aceitar; aviso de comportamento não verificado da fonte quando a entrada
   é alfanumérica. **Dígito verificador não é conferido**, de propósito.
2. **`contratacaoExcluida=false`** (seção 12.1) — no endpoint de cabeçalho,
   com a ressalva de escopo registrada acima.
3. **Afirmação incorreta sobre as tabelas de domínio** (seções 2 e 12.7) —
   corrigida em `consultar_tabelas_dominio_pncp` e em `domain/dominios.py`,
   sem mudar comportamento.

A pendência nº 1 da lista acima (`GET /v1/modalidades`) continua de pé: a
correção trocou uma certeza falsa por uma dúvida honesta, não por uma
verificação.

---

## 14. Booleanos do índice do PNCP são de TRÊS estados

**MEDIDO** — 07/09/2026, com o PNCP de volta ao ar.

Achado que começou como uma pergunta simples ("quantas contratações de 2026
têm emenda parlamentar?") e revelou duas coisas: uma limitação nossa e uma
armadilha da fonte.

### `/api/search` não exige termo de busca

`buscar_pncp_texto` exige `termo_busca`. O endpoint **não**. Omitindo `q`
(ou enviando-o vazio) o índice devolve o universo filtrado:

```
tipos_documento=edital&anos=2026&status=todos   → 951.350
```

Isso importa porque a alternativa — escolher um termo genérico só para
"destravar" a consulta — **não dá erro, dá número errado**: o total passa a
ser o do termo, não o do país. Foi assim que uma apuração sobre emenda
parlamentar chegou a `total = 0`, valor incompatível com casos já
identificados na mão.

### O terceiro estado

```
tipos_documento=edital&anos=2026&status=todos
  + possui_emenda_parlamentar=true    →     107
  + possui_emenda_parlamentar=false   →   7.224
```

`107 + 7.224 = 7.331`, contra um universo de 951.350. Os outros **944.019
registros têm o campo `null`** — confirmado lendo os registros: na população
geral o campo vem `null`; no recorte com `=true` vem `true`.

**`false` não é o complemento de `true`.** É "marcado explicitamente como
não". Quem subtrai `true` do total para obter "sem emenda" erra por duas
ordens de grandeza.

A proporção de nulos varia de forma extrema, sem regra que dispense medir
(ano 2026, `status=todos`):

| Campo / tipo | true | false | null |
| --- | ---: | ---: | ---: |
| edital / `possui_emenda_parlamentar` | 107 | 7.224 | 944.019 |
| contrato / `possui_emenda_parlamentar` | 157 | 14.579 | 1.230.337 |
| ata / `possui_emenda_parlamentar` | 0 | 1 | 280.484 |
| edital / `exigencia_conteudo_nacional` | 389 | 943.193 | 7.768 |
| contrato / `exigencia_conteudo_nacional` | 0 | 0 | 1.245.073 |
| ata / `permite_adesao` | 90.378 | 108.731 | 81.376 |
| edital / `permite_adesao` | 0 | 19 | 951.331 |

Duas linhas merecem leitura atenta. Em **edital / `exigencia_conteudo_nacional`**
o predominante é `false`, não o nulo — inverso do caso da emenda, o que
mostra que a intuição de "campo novo, pouco preenchido" não se generaliza.
E em **contrato / `exigencia_conteudo_nacional`** o filtro é aceito mas
**não há dado algum**: `=true` devolve zero, e esse zero não diz nada sobre
a realidade, só sobre o preenchimento do índice.

### Duas armadilhas do endpoint

- **Nome de parâmetro errado é ignorado em silêncio.** `emenda_parlamentar`
  (sem `possui_`) devolve 951.350 — idêntico ao controle com um parâmetro
  inventado. Nenhum erro. Já registrado no topo de `pncp_client.py`;
  reconfirmado agora.
- **Valor não booleano devolve HTTP 204.** `possui_emenda_parlamentar=talvez`
  responde 204 No Content, não 400.

### O que foi feito

A tool `contar_pncp` conta sem exigir termo, e com
`detalhar_campo` devolve a decomposição `true`/`false`/`ausente` com o
percentual preenchido. O percentual de `true` é calculado **sobre os
preenchidos**, não sobre o total — sobre o total ele misturaria "não tem"
com "não se sabe". Avisos automáticos quando a cobertura é menor que 10% e
quando não há dado algum.

Não devolve registros, só contagens; para ver os documentos, `buscar_pncp_texto`
com os mesmos filtros.

### Confirmado ao vivo em 07/09/2026

Contagens medidas diretamente no índice do PNCP. Tudo se sustentou:

| tipo / campo | total | true | false | null |
| --- | ---: | ---: | ---: | ---: |
| edital / `possui_emenda_parlamentar` | 951.362 | 107 | 7.224 | 944.031 |
| contrato / `possui_emenda_parlamentar` | 1.245.584 | 157 | 14.580 | 1.230.847 |
| ata / `possui_emenda_parlamentar` | 280.486 | 0 | 1 | 280.485 |
| edital / `exigencia_conteudo_nacional` | 951.361 | 389 | 943.203 | 7.769 |
| contrato / `exigencia_conteudo_nacional` | 1.245.584 | 0 | 0 | 1.245.584 |
| ata / `permite_adesao` | 280.486 | 90.378 | 108.732 | 81.376 |
| edital / `permite_adesao` | 951.362 | 0 | 19 | 951.343 |

Detalhe que vale registrar: os totais cresceram algumas centenas em relação à
medição pelo navegador, **mas as contagens de `true` não se moveram uma
unidade** — 107, 157, 0, 389, 0, 90.378, 0. O `false` andou 1 em dois casos.
Ou seja, o índice recebeu centenas de registros novos e praticamente nenhum
deles trouxe o campo preenchido. Reforça a leitura de que o preenchimento
depende de quem publica, e não do volume.

**O índice é escrito ao vivo.** Na mesma execução do script, o total de
editais oscilou entre 951.361 e 951.362 — segundos de intervalo. Isso obrigou
a corrigir o próprio verificador, que comparava a leitura com `q` vazio e a
leitura sem `q` exigindo igualdade exata e acusava a deriva como se fosse
mudança de comportamento. Falso positivo num verificador custa caro: quem é
avisado à toa para de olhar. Passou a fazer duas leituras sem `q`, uma antes
e outra depois, e só acusa se a leitura com `q` vazio cair fora do intervalo.

### PENDENTE

- Por que o preenchimento é tão desigual? Depende do sistema de origem que
  publica no PNCP, da versão do manual vigente quando o registro foi criado,
  ou de ambos? Sem isso, não dá para dizer se 107 editais com emenda em 2026
  é um número real ou um artefato de quem preenche.
- Os campos `tipo_item_irp`, `prazo_manifestacao_interesse` e
  `aplicabilidade_margem_preferencia` estão no payload do índice (seção 4) e
  seguem ignorados pelo nosso mapeamento.

---

## Fontes

- Manual de Integração do PNCP, versão 2.6 —
  <https://pncp.gov.br/manual/pt-br/latest/>
- OpenAPI do Compras.gov.br Dados Abertos, v2.0.0 —
  <https://dadosabertos.compras.gov.br/v3/api-docs>
- Manual do Usuário — API do Compras.gov.br, versão 2.0 (fev/2026), 135 p.,
  Cotin/CGGES/Delog/Seges/MGI — `manual-api-compras.pdf`
- Catálogo de Módulos e Endpoints (Documentação Interativa) —
  <https://www.gov.br/compras/pt-br/cidadao/portal-de-dados-abertos/documentacao-interativa-da-api-de-dados-abertos>
  (conteúdo servido de `portaldadosabertos-dev.gestao.gov.br`)
- Medições próprias, registradas nas docstrings dos módulos correspondentes e
  nos testes ao vivo (`tests/test_live_smoke.py`).
