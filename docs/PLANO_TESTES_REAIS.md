# Plano de testes com dados reais

Plano para exercitar as 48 tools contra as fontes reais, medir a
disponibilidade e a latência de cada endpoint — com atenção especial ao PNCP —
e classificar as falhas encontradas. Complementa a suíte offline (`pytest`,
APIs simuladas) e os testes `live` semanais, que cobrem só o caminho feliz.

## 1. Objetivos

1. **Funcional:** cada tool devolve resultado correto para uma pesquisa real,
   com `avisos` e `cobertura` coerentes.
2. **Fontes:** medir, por endpoint, taxa de sucesso, latência (p50/p95) e
   repetições necessárias, separando falha da fonte de defeito do servidor.
3. **Contrato:** detectar mudanças silenciosas nas APIs (campo que sumiu,
   parâmetro ignorado, filtro que deixou de valer).
4. **Ponta a ponta:** executar pesquisas de preços completas, da descoberta do
   código de catálogo ao relatório Word.

## 2. Medições iniciais (30/10/2026)

Feitas ao montar este plano; servem de linha de base.

| Endpoint | Origem | Resultado |
|---|---|---|
| `GET /api/consulta/v1/orgaos/{cnpj}/compras/{ano}/{seq}` | rede residencial (SP) | 200 em **9,6 s** |
| `GET /api/consulta/v1/contratos` (TCU, out/2026) | rede residencial (SP) | 200 em **6,5 s** |
| `GET /api/search/` | rede residencial (SP) | **conexão derrubada** em 0,1 s, 3 de 3 tentativas |
| `/api/search` via `contar_pncp` | servidor no Fly (gru) | 200 em 0,25 s, 19.592 editais |

Duas consequências para o plano:

- **A falha depende da origem.** A mesma busca que o Fly obtém é recusada a
  partir de outra rede. Toda medição registra a origem, e a sondagem roda de
  pelo menos dois lugares (seção 4).
- **A API de Consulta está acima do compromisso publicado.** O catálogo oficial
  declara resposta em menos de 3 s (ver `ACHADOS_DAS_FONTES.md`, seção 9); as
  duas chamadas levaram 2 a 3 vezes isso.

Regra permanente: as requisições se identificam com o User-Agent do projeto.
Não se troca o User-Agent nem se usa outro artifício para contornar bloqueio — o
bloqueio é um resultado a medir, não um obstáculo a driblar.

## 3. Duas camadas de medição

Comparar as duas camadas é o que separa "a fonte falhou" de "o servidor tem
defeito".

| Camada | O que chama | Mede |
|---|---|---|
| **A — sondagem direta** | Cada endpoint externo, sem passar pelo servidor | Disponibilidade e latência da fonte |
| **B — tools via MCP** | As 48 tools, pelo protocolo MCP | Resultado entregue ao usuário: correção, avisos, cobertura, tempo total |

Leitura cruzada:

| A | B | Diagnóstico |
|---|---|---|
| ok | ok | Normal |
| falha | erro claro na tool | Fonte fora; servidor reportou bem |
| falha | resultado vazio sem aviso | **Defeito:** ausência apresentada como fato |
| ok | erro | **Defeito do servidor** |
| lento | `cobertura` parcial com aviso | Comportamento esperado do orçamento de tempo |

## 4. Ambiente e ritmo

- **Servidor:** instância local em HTTP
  (`mcp-radardeprecos --transport streamable-http`), para ler as métricas sem
  depender da instância pública; e a instância pública
  (`https://mcp-radardeprecos.fly.dev/mcp`) para o fluxo ponta a ponta.
- **Origens da camada A:** a máquina local e uma máquina no Fly (`gru`).
- **Janelas:** 9h, 14h e 20h (Brasília), em 5 dias úteis — a disponibilidade
  das fontes varia ao longo do dia.
- **Repetições:** 5 chamadas por endpoint em cada janela.
- **Ritmo:** no máximo 1 requisição por segundo por fonte. As fontes são
  públicas e compartilhadas; o teste não pode virar carga.
- **Configuração:** a padrão do servidor (timeout 30 s, até 4 tentativas,
  orçamento de 120 s por tool), registrada no relatório.

## 5. Dados de referência

Fixos, para que as rodadas sejam comparáveis. Conferidos em 30/10/2026.

| Dado | Valor | Uso |
|---|---|---|
| Material (CATMAT) | `267203` — dipirona sódica 500 mg | preços praticados, BPS, ARP, unidades |
| Serviço | obtido de `descobrir_codigo_catalogo("limpeza predial")` | preços de serviço, CATSER |
| Objeto de TIC | "notebook" e "licença de software de escritório em nuvem" | buscas, TIC, estudo de mercado |
| Contratação PNCP | `16854531000181-1-000066/2023` (seguros, SRP) | detalhe, itens, arquivos, família |
| Órgão | TCU, CNPJ `00414607000118` | contratos por órgão, PCA, UASG |
| Contrato PNCP | `00414607000118-2-000333/2026` | termos, empenhos, notas fiscais |
| Fornecedor | CNPJ `00000000000191` (Banco do Brasil) | CNPJ, SICAF, sanções |
| Período | 2025-10-30 a 2026-10-30 | recortes de data |

Dados encadeados (UASG, número de ata, item de ARP) são obtidos na própria
rodada, como num uso real, e registrados no relatório.

## 6. Classificação de falhas

| Código | Falha | Como detectar |
|---|---|---|
| F1 | Timeout | sem resposta no prazo |
| F2 | Conexão derrubada | reset ou erro de transporte |
| F3 | Erro 5xx da fonte | status 500–599 |
| F4 | Limite de requisições | status 429 |
| F5 | 4xx inesperado | parâmetro ou rota que deixou de existir |
| F6 | Vazio inesperado | 204 ou lista vazia onde havia dado |
| F7 | Contrato alterado | campo esperado ausente ou com outro tipo |
| F8 | Dado incoerente | ex.: data fora do filtro, resultado anterior à compra, homologado acima do estimado |
| F9 | Erro na tool | `isError: true` ou exceção |
| F10 | Cobertura reduzida | `cobertura` parcial ou indeterminada |
| F11 | Lentidão | acima do limite da seção 7 |

F5, F7 e F9 com a fonte disponível indicam **defeito ou mudança a corrigir**;
viram issue no repositório.

## 7. Critérios de aceite

| Métrica | Verde | Amarelo | Vermelho |
|---|---|---|---|
| Sucesso final por endpoint (após repetições) | ≥ 98% | 90–98% | < 90% |
| Sucesso na 1ª tentativa | ≥ 90% | 70–90% | < 70% |
| Tentativas médias por chamada | ≤ 1,1 | 1,1–1,5 | > 1,5 |
| Latência p95 — API de Consulta do PNCP | ≤ 3 s (compromisso oficial) | 3–10 s | > 10 s |
| Latência p95 — demais endpoints | ≤ 5 s | 5–15 s | > 15 s |
| Tools com `isError` indevido | 0 | — | ≥ 1 |
| Vazio sem aviso (ausência como fato) | 0 | — | ≥ 1 |

## 8. Camada A — endpoints a sondar

Cada sondagem é a chamada mais simples que exercita o endpoint com os dados da
seção 5.

**PNCP — busca indexada (`/api/search`)**

| # | Endpoint | Tools que dependem |
|---|---|---|
| A1 | `GET /api/search/` | `buscar_pncp_texto`, `_booleano`, `contar_pncp`, `buscar_contratacoes_pncp`, `buscar_contratos_compras`, `mapear_fornecedores_mercado` |
| A2 | `GET /api/search/filters` | `listar_filtros_pncp` |

**PNCP — API de Consulta (`/api/consulta`)**

| # | Endpoint | Tools |
|---|---|---|
| A3 | `/v1/orgaos/{cnpj}/compras/{ano}/{seq}` | `consultar_contratacao_pncp` |
| A4 | `/v1/contratos` | `consultar_contratos_orgao_pncp`, `consultar_familia_contratacao_pncp` |
| A5 | `/v1/contratacoes/proposta` | `buscar_propostas_abertas` |
| A6 | `/v1/contratacoes/publicacao` | apoio às buscas por período |
| A7 | `/v1/atas` | `radar_vencimentos` (complemento) |
| A8 | `/v1/pca/` e `/v1/pca/atualizacao` | `consultar_pca` |
| A9 | `/v1/instrumentoscobranca/inclusao` | `consultar_notas_fiscais` (por período) |

**PNCP — API PNCP (`/api/pncp`)**

| # | Endpoint | Tools |
|---|---|---|
| A10 | `/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens` | `buscar_contratacoes_pncp`, `consultar_contratacao_pncp` |
| A11 | `…/itens/{n}/resultados` | `buscar_contratacoes_pncp` (valor homologado) |
| A12 | `/v1/orgaos/{cnpj}/{recurso}/{ano}/{seq}/arquivos` | `listar_arquivos_pncp` |
| A13 | `…/compras/{ano}/{seq}/atas/{ata}` (e itens, arquivos) | `consultar_ata_registro_preco` |
| A14 | `/v1/orgaos/{cnpj}/contratos/{ano}/{seq}/termos` | `consultar_familia_contratacao_pncp` |
| A15 | `…/contratos/{ano}/{seq}/empenhos` | `consultar_familia_contratacao_pncp` |
| A16 | `…/contratos/{ano}/{seq}/instrumentocobranca` | `consultar_notas_fiscais` |

**Demais fontes**

| # | Endpoint | Tools |
|---|---|---|
| A17 | Compras.gov.br `/modulo-pesquisa-preco/1_consultarMaterial` e `3_consultarServico` | `buscar_precos_praticados_compras`, `pesquisar_cesta_precos` |
| A18 | Compras.gov.br `/modulo-contratacoes/*_PNCP_14133` | `buscar_homologados_14133` |
| A19 | Compras.gov.br `/modulo-arp/*` | `buscar_arp_compras`, `consultar_arp_detalhe_compras`, `radar_vencimentos` |
| A20 | Compras.gov.br `/modulo-contratos/*` | `consultar_contratos_compras`, `consultar_itens_contrato_compras`, `radar_vencimentos` |
| A21 | Compras.gov.br `/modulo-material/*`, `/modulo-servico/*` | catálogo, `converter_para_unidade_base` |
| A22 | Compras.gov.br `/modulo-uasg/*` | `descobrir_uasg` |
| A23 | Compras.gov.br `/modulo-fornecedor/1_consultarFornecedor` | `consultar_situacao_fornecedor` |
| A24 | BPS `/economia-da-saude/bps` | `buscar_precos_saude_bps` |
| A25 | BCB SGS `/dados/serie/bcdata.sgs.{433,189,193}/dados` | `atualizar_precos_indice` |
| A26 | TCU `/api/rest/publico/certidoes/{cnpj}` | `consultar_sancoes_fornecedor` |
| A27 | BrasilAPI `/cnpj/v1/{cnpj}` e MinhaReceita `/{cnpj}` | `consultar_cnpj` |

Para cada sondagem, registrar: origem, horário, status HTTP, latência, bytes,
classificação (seção 6) e se o campo-chave esperado veio.

## 9. Camada B — casos por tool

Cada caso lista a chamada e o que verificar, além do comum a todas: sem
`isError` indevido, avisos coerentes e tempo registrado.

### Busca de contratações e contratos

| Tool | Caso | Verificar |
|---|---|---|
| `buscar_pncp_texto` | "dipirona", edital, janela de 12 meses | resultados dentro da janela; `cobertura` coerente |
| `buscar_pncp_texto_booleano` | "notebook" E "i7" NÃO "locação" | nenhum resultado com o termo excluído |
| `contar_pncp` | edital, "dipirona" | total > 0; bate em ordem de grandeza com a busca |
| `listar_filtros_pncp` | edital | facetas de UF e modalidade presentes |
| `listar_arquivos_pncp` | contratação de referência | ao menos um arquivo com URL que responde |
| `buscar_contratacoes_pncp` | "notebook", 6 meses | itens com estimado **e** homologado, rotulados |
| `buscar_contratos_compras` | "limpeza predial" | valor global e link |
| `buscar_homologados_14133` | CATMAT 267203, período de referência | itens homologados com preço |
| `consultar_contratacao_pncp` | `16854531000181-1-000066/2023` | `srp: true`, links de PNCP e origem |
| `consultar_contratos_orgao_pncp` | TCU, out/2026 | inclui `00414607000118-2-000333/2026`; cobertura exaustiva |
| `consultar_familia_contratacao_pncp` | contratação de referência | edital, arquivos, ata e contratos; termos e empenhos quando houver |
| `buscar_propostas_abertas` | 15 dias à frente | só propostas abertas; aviso de "valores estimados" |
| `consultar_notas_fiscais` | contrato de referência | NF-e com itens, ou vazio declarado |
| `consultar_contratos_compras` | órgão do TCU, vigência atual | contratos com fundamento legal |
| `consultar_itens_contrato_compras` | idem | itens com preço unitário |
| `radar_vencimentos` | atas, 90 dias, órgão do TCU | datas de fim dentro do horizonte |

### Atas de registro de preço

| Tool | Caso | Verificar |
|---|---|---|
| `buscar_arp_compras` | CATMAT 267203, vigência de 12 meses | atas que registram o item; saldo |
| `consultar_ata_registro_preco` | ata obtida acima, no PNCP | itens e arquivos |
| `consultar_arp_detalhe_compras` | ata e item obtidos acima | unidades, adesões e empenhos |

### Catálogos e órgãos

| Tool | Caso | Verificar |
|---|---|---|
| `descobrir_codigo_catalogo` | "dipirona 500 mg" e "limpeza predial" | 267203 entre os primeiros; CATSER de limpeza |
| `listar_itens_catalogo` | PDM da dipirona | itens com código real |
| `navegar_catalogo_servico` | da seção à subclasse | hierarquia completa |
| `descobrir_uasg` | "Tribunal de Contas da União" | UASG do TCU |
| `consultar_tabelas_dominio_pncp` | todas | 15 tabelas (sem rede) |
| `consultar_pca` | TCU, 2026 | itens planejados; aviso de que não é referência de preço |

### Preços e cesta

| Tool | Caso | Verificar |
|---|---|---|
| `buscar_precos_praticados_compras` | 267203, as duas datas, todas as páginas | `periodo` sem registros fora da janela; `data_compra` presente; unidades |
| idem — negativo | só `data_compra_inicio` | erro "juntas" sem chamar a fonte |
| `buscar_precos_saude_bps` | 267203, 12 meses | registros de estados e municípios; cobertura nunca exaustiva |
| `pesquisar_cesta_precos` | 267203 + CATSER de limpeza, com correção por IPCA | preço por item e total |
| `montar_cesta_precos` | registros da busca de preços | série sem transcrição manual |
| `converter_para_unidade_base` | preços do 267203 | comprimido, ampola e frasco separados; `nao_convertidos` com motivo |
| `normalizar_precos_unidade` | licenças anuais → usuário/mês | fórmula por linha |
| `agrupar_por_comparabilidade` | série do 267203 | graus A–D; grupo não comparável |
| `detectar_inconsistencias` | série do 267203 | o preço de R$ 26.054 sinalizado |

### Cálculo e correção monetária

| Tool | Caso | Verificar |
|---|---|---|
| `calcular_preco_referencia` | comprimidos do 267203 (378 preços) | meta atingida com 49 exclusões; `status_resultado` |
| idem — negativo | `[1, 100, 100, 200]` | piso; amostra de menor CV mantida |
| `atualizar_precos_indice` | preços de 2025, IPCA e IGP-M | fator por competência; data-base |

### Estudo de mercado e classificação

| Tool | Caso | Verificar |
|---|---|---|
| `mapear_fornecedores_mercado` | "limpeza predial" | fornecedores vencedores; avisos de limite |
| `classificar_curva_abc` | cesta com 10 itens | classes A/B/C |
| `classificar_objeto_tic` | "licença de software em nuvem" | TIC e SaaS |
| `gerar_estudo_mercado_tic` | três soluções de escritório em nuvem | matriz completa |

### Fornecedor

| Tool | Caso | Verificar |
|---|---|---|
| `consultar_cnpj` | `00000000000191` | razão social; fonte (BrasilAPI ou MinhaReceita) |
| `consultar_situacao_fornecedor` | idem | situação no SICAF |
| `consultar_sancoes_fornecedor` | idem | resultado das quatro bases |

### Diretrizes, formalização e exportação

| Tool | Caso | Verificar |
|---|---|---|
| `obter_diretrizes_pesquisa_precos` | — | escore Z como padrão |
| `gerar_memoria_pesquisa` | resultado do fluxo da seção 10 | Markdown com fontes e buscas frustradas |
| `gerar_relatorio_excel` | idem | arquivo em base64 que abre; 4 abas |
| `gerar_relatorio_word` | idem | arquivo que abre; elementos I a VIII |
| `exportar_resultados` | registros da busca de preços | CSV e XLSX válidos |
| `exportar_trilha_auditoria` | após o fluxo | uma entrada por consulta, com hash |

## 10. Fluxos ponta a ponta

Cada fluxo é uma pesquisa real completa, encadeando as tools como um
assistente faria. Registra-se o tempo total e cada etapa.

1. **Material comum:** `descobrir_codigo_catalogo` → `buscar_precos_praticados_compras`
   (12 meses) → `converter_para_unidade_base` → `agrupar_por_comparabilidade` →
   `detectar_inconsistencias` → `calcular_preco_referencia` →
   `atualizar_precos_indice` → `gerar_memoria_pesquisa` → `gerar_relatorio_word`
   → `exportar_trilha_auditoria`.
2. **Serviço:** o mesmo fluxo para limpeza predial, com
   `mapear_fornecedores_mercado` antes do preço.
3. **TIC:** `classificar_objeto_tic` → `gerar_estudo_mercado_tic` →
   `buscar_contratacoes_pncp` → `normalizar_precos_unidade` →
   `calcular_preco_referencia`.
4. **Saúde:** `buscar_precos_saude_bps` e `buscar_precos_praticados_compras`
   para o mesmo CATMAT, comparando as duas fontes.
5. **Contrato vigente:** `consultar_contratos_orgao_pncp` →
   `consultar_familia_contratacao_pncp` → `consultar_notas_fiscais` →
   `radar_vencimentos`.
6. **Fornecedor:** `consultar_cnpj` → `consultar_situacao_fornecedor` →
   `consultar_sancoes_fornecedor`.

Um fluxo só passa se todas as etapas passarem ou se cada falha estiver
declarada em `avisos`/`cobertura` com a fonte identificada.

## 11. Resiliência

Situações provocadas na instância local, para confirmar o comportamento
documentado:

| Situação | Como provocar | Esperado |
|---|---|---|
| Fonte lenta | `RADARDEPRECOS_HTTP_TIMEOUT=2` | repetições; erro claro se esgotar |
| Orçamento de tempo curto | `RADARDEPRECOS_TOOL_BUDGET_SECONDS=10` em busca ampla | parcial com aviso e `cobertura` parcial |
| Sem repetição | `RADARDEPRECOS_HTTP_MAX_RETRIES=1` | taxa de sucesso na 1ª tentativa, isolada |
| Rate limit do servidor | 70 chamadas em 1 min | 429 após 60, com `Retry-After` |
| Entrada inválida | datas isoladas, CNPJ errado, CATMAT inexistente | erro de validação sem chamar a fonte, ou vazio declarado |

## 12. Registro e relatório

- **Bruto:** um arquivo JSON Lines por rodada, uma linha por chamada (camada,
  origem, horário, alvo, parâmetros, status, latência, tentativas,
  classificação, trecho do erro).
- **Métricas do servidor:** nas rodadas pela instância pública, os contadores
  `radardeprecos_fonte_*` no Grafana confirmam erros e repetições por fonte.
- **Relatório por rodada:**
  - disponibilidade e latência por endpoint, com a cor da seção 7;
  - resultado por tool (passou, falhou, motivo);
  - comparação entre origens;
  - falhas F5, F7 e F9 com reprodução.
- **Consolidado da semana:** tendência por endpoint e janela de horário, e
  atualização de `ACHADOS_DAS_FONTES.md` com o que for medido.

## 13. Execução

Os casos das seções 8 a 11 devem virar um executor (`scripts/teste_real.py`)
que lê os dados da seção 5, faz as chamadas no ritmo da seção 4, grava o
registro bruto e gera o relatório. As sondagens da camada A podem entrar no
workflow semanal `live-smoke`, que hoje roda só o caminho feliz.
