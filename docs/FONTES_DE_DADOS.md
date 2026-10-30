# Fontes de dados, endpoints e pegadinhas das APIs

Todas as APIs consultadas são **públicas e somente leitura** — nenhuma
credencial é necessária. Este documento é a referência técnica de cada
endpoint usado e, principalmente, das **pegadinhas confirmadas ao vivo**
contra cada API (comportamentos não documentados que causaram bugs reais;
detalhes em `ACHADOS_DAS_FONTES.md`).

## PNCP — busca indexada (`/api/search`)

A busca textual (`buscar_pncp_texto`) e as tools de agregação
(`buscar_contratacoes_pncp`, `buscar_contratos_compras`) não usam a API de
Consulta oficial para a busca em si — usam `/api/search`, a mesma API
interna que o site pncp.gov.br/app chama para popular resultados e filtros.
Não é documentada em Swagger, mas é pública e estável; foi validada por
engenharia reversa do bundle do site e inspeção das chamadas de rede reais.

Pegadinhas confirmadas ao vivo:

- **O parâmetro de UF é `ufs` (plural).** `uf` (singular) é **ignorado
  silenciosamente** — a busca roda sem filtro nenhum, sem erro (confirmado:
  `uf=SP` → 371 resultados; `ufs=SP` → 47). Um smoke test ao vivo
  (`pytest -m live`) vigia essa regressão permanentemente.
- **Seleção múltipla do mesmo filtro não funciona como OR** —
  `ufs=SP&ufs=RJ` usa só o último valor; `ufs=SP,RJ` vira valor inválido
  (zero resultados). Por isso as tools aceitam um valor por chamada.
- **Teto real do índice: `pagina × tamanhoPagina <= 10000`** (limite do
  Elasticsearch subjacente; HTTP 400 acima disso). As varreduras internas
  respeitam exatamente esse teto (100 páginas × 100 registros) e avisam
  quando param nele.
- **`tam_pagina` aceita até ~1000** (a UI do site usa 10) — as tools pedem
  100 por página para reduzir round-trips.
- **`municipios` espera o ID interno do PNCP** (São Paulo = `3830`), não o
  código IBGE (`3550308`). Use `listar_filtros_pncp` para descobrir IDs.
- **O filtro de emenda parlamentar é `possui_emenda_parlamentar`** —
  `emenda_parlamentar` (nome mais óbvio) é ignorado silenciosamente.
- **`termo_busca` não tem sintaxe de frase exata**: aspas em 1 palavra são
  ignoradas; em frases produzem resultado imprevisível. Múltiplas palavras
  casam como "E" (bag-of-words, independente de ordem); termos curtos casam
  por **prefixo** (`"note"` ≈ `"notebook"`). Prefira termos longos +
  filtros estruturados.
- **Não há filtro nativo de período relativo** ("últimos N meses") — só ano
  civil via `ano`. O parâmetro `janelas_meses` das tools filtra no cliente,
  varrendo o índice internamente; por isso `total` pode superar a
  quantidade retornada (sinalizado em `avisos`).
- **Suspeita não confirmada (relato de campo, 2026-07-16): `pagina` pode
  não avançar de forma confiável.** Um agente relatou que `pagina=1` e
  `pagina=2` devolveram exatamente o mesmo conjunto de IDs numa busca real
  contra `/api/search`. Não foi possível reproduzir neste projeto (ambiente
  de implementação sem acesso de rede) — pode ser um bug real de paginação
  no backend (ex.: falta de tie-break estável quando muitos documentos têm
  o mesmo `data_publicacao_pncp`, um problema clássico de paginação profunda
  em índices Elasticsearch sem ordenação determinística) ou uma
  particularidade pontual da consulta usada. Um teste ao vivo permanente
  (`test_live_pncp_paginacao_pagina_1_e_2_nao_repetem_os_mesmos_itens` em
  `tests/test_live_smoke.py`) foi adicionado para confirmar/vigiar isso na
  próxima rodada de CI com rede real — se ele falhar, trate como confirmação
  do bug, não como instabilidade passageira.

## PNCP — endpoints usados

| Endpoint | Uso |
|---|---|
| `GET pncp.gov.br/api/search/` | Busca textual indexada (editais, atas, contratos) — mesmo backend do site. |
| `GET .../api/search/filters` | Facetas de filtro (modalidade, UF, órgão, município etc.), com contagens. |
| `GET .../api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens` | Itens e preços unitários **estimados** de uma contratação. |
| `GET .../itens/{n}/resultados` | Valor **homologado** (vencedor) de um item — a referência válida para pesquisa de preços. |
| `GET .../api/pncp/v1/orgaos/{cnpj}/{compras\|contratos}/{ano}/{seq}/arquivos` | Arquivos anexados (edital, TR, contrato assinado), com link de download. |
| `GET .../compras/{ano}/{seq}/atas/{seqAta}` (+ `/itens`, `/arquivos`) | Detalhe de Ata de Registro de Preço, itens com saldo, arquivos. |
| `GET .../api/consulta/v1/orgaos/{cnpj}/compras/{ano}/{seq}` | Detalhe completo de uma contratação (srp, amparo legal, links). |
| `GET .../api/consulta/v1/contratos` | Contratos por publicação, filtro por CNPJ do **órgão** no servidor (não há filtro por fornecedor). |
| `GET .../api/consulta/v1/pca/` e `/pca/atualizacao` | Itens do Plano de Contratação Anual. |

Pegadinhas:

- O host do link de **download** (`pncp.gov.br/pncp-api/v1/...`) é diferente
  do host de **listagem** (`pncp.gov.br/api/pncp/v1/...`) — confirmado, não
  é erro.
- **Atas não têm arquivos próprios** (`/atas/.../arquivos` → 404): os
  documentos são os da compra de origem — use o sequencial da compra.
- **Links de página do site são construídos localmente** a partir de
  `cnpj/ano/sequencial` — o campo `item_url` da API de busca já embute o
  prefixo do recurso e gera URLs quebradas se concatenado (bug já
  corrigido).
- O detalhe de contratação inclui `linkSistemaOrigem` — o link pronto para a
  página do ComprasNet-web, cujas APIs próprias exigem captcha e não podem
  ser lidas programaticamente.

## Compras.gov.br — Dados Abertos (`dadosabertos.compras.gov.br`)

| Endpoint | Uso |
|---|---|
| `GET /modulo-pesquisa-preco/1_consultarMaterial` e `/3_consultarServico` | **Preços praticados** por item CATMAT/CATSER — a fonte de maior prioridade normativa (IN SEGES/ME 65/2021). |
| `GET /modulo-material/{1..4}_...` e `/modulo-servico/{4,6}_...` | Catálogos CATMAT/CATSER (grupos, classes, PDMs, itens) — cacheados. |
| `GET /modulo-arp/{1..5}_...` | Atas de Registro de Preço com saldo de adesão, caronas e empenhos por item. |
| `GET /modulo-contratos/1_consultarContratos` e `/2_consultarContratosItem` | Contratos por vigência (cabeçalho e itens com preço unitário). |
| `GET /modulo-uasg/1_consultarUasg` e `/2_consultarOrgao` | UASGs e órgãos (descoberta de código a partir do nome, no cliente). |
| `GET /modulo-fornecedor/1_consultarFornecedor` | Situação do fornecedor no SICAF (`habilitado_a_licitar`). |

Pegadinhas confirmadas ao vivo:

- **`descricaoItem` exige igualdade exata** com o campo completo — não é
  busca por substring, apesar do nome. `descobrir_codigo_catalogo` faz a
  busca textual no lado do cliente por causa disso.
- **Paginação exige `tamanhoPagina` entre 10 e 500** em vários módulos
  (HTTP 400 fora da faixa); `consultarUasg`/`consultarOrgao` **não aceitam**
  `tamanhoPagina` nem busca textual.
- **Preços praticados NÃO vêm ordenados por data** — pesquisas exaustivas
  devem iterar `pagina`, consolidar e só então filtrar por período.
- **`codigo_orgao` é obrigatório** nos módulos de contratos (sem ele a API
  devolve HTTP 404, não "sem resultados"); janelas de vigência limitadas a
  365 dias.

## Outras fontes

| Endpoint | Uso |
|---|---|
| BrasilAPI `GET /cnpj/v1/{cnpj}` | Cadastro do CNPJ na Receita Federal, com fallback automático para MinhaReceita (`minhareceita.org/{cnpj}`). |
| Banco Central `GET api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados` | Variação mensal do IPCA/IBGE (série 433 do SGS) — atualização monetária de preços históricos (`atualizar_precos_indice`). Cacheada por 1 dia. |
