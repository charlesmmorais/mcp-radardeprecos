<p align="center">
  <img src="assets/mcp_radardeprecos_icon.png" alt="mcp-radardeprecos" width="96">
</p>

<h1 align="center">mcp-radardeprecos</h1>

<p align="center">
  Servidor <a href="https://modelcontextprotocol.io">MCP</a> para pesquisa de preços e contratações públicas brasileiras.
</p>

<p align="center">
  <a href="https://github.com/charlesmmorais/mcp-radardeprecos/actions/workflows/ci.yml"><img src="https://github.com/charlesmmorais/mcp-radardeprecos/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%E2%80%933.13-blue" alt="Python 3.10–3.13">
  <img src="https://img.shields.io/badge/MCP-servidor-6f42c1" alt="MCP">
  <a href="LICENSE"><img src="https://img.shields.io/badge/licen%C3%A7a-Apache--2.0-green" alt="Apache-2.0"></a>
</p>

---

O **mcp-radardeprecos** dá a assistentes de IA (Claude, ChatGPT, Gemini,
Microsoft 365 Copilot e outros clientes MCP) acesso às fontes oficiais de compras
públicas e às rotinas de uma pesquisa de preços conforme a
**IN SEGES/ME nº 65/2021**: da busca de referências ao cálculo do preço
estimado e à formalização em Excel e Word.

Fontes consultadas, todas públicas e de somente leitura, sem credencial:

- **PNCP** — Portal Nacional de Contratações Públicas
- **Compras.gov.br** — Dados Abertos (preços praticados, catálogos, atas, contratos, SICAF)
- **Banco de Preços em Saúde** — Ministério da Saúde
- **Banco Central** — séries do SGS para correção monetária (IPCA, IGP-M, IPC-Fipe)
- **Receita Federal** — cadastro de CNPJ (via BrasilAPI / MinhaReceita)
- **TCU** — consulta consolidada de sanções (TCU, CNJ, CEIS, CNEP)

## Teste rápido — servidor público

Para experimentar sem instalar nada, use a instância pública:

```
https://mcp-radardeprecos.fly.dev/mcp
```

Não precisa de login nem de chave. A URL termina sempre em `/mcp`.

### Configurando o cliente

| Cliente | Como configurar |
|---|---|
| **Claude** (web, desktop e celular) | **Configurações → Conectores → Adicionar conector personalizado**. Nome: `Radar de Preços`; URL: a acima. Disponível nos planos Pro, Max, Team e Enterprise. |
| **Claude Code** | `claude mcp add --transport http radardeprecos https://mcp-radardeprecos.fly.dev/mcp` |
| **ChatGPT** | **Configurações → Apps e conectores → Avançado → Modo desenvolvedor**; depois **Criar**, informe a URL e escolha **Sem autenticação**. |
| **Gemini** | Em [gemini.google.com](https://gemini.google.com), na web: ícone **Personalizar** da barra lateral → **[Conectores](https://gemini.google.com/customize/connectors)** → adicione um conector personalizado com a URL. No chat, chame-o digitando `@`. Depois de adicionado, funciona também no app de celular. |
| **VS Code** (GitHub Copilot) | Crie `.vscode/mcp.json` com o bloco abaixo. |
| **Cursor** | Em `~/.cursor/mcp.json`, use o bloco abaixo trocando `servers` por `mcpServers` e removendo `"type"`. |
| **Clientes só com `stdio`** | Use a ponte `mcp-remote` (requer Node.js), como no bloco abaixo. |

VS Code (`.vscode/mcp.json`):

```json
{
  "servers": {
    "radardeprecos": {
      "type": "http",
      "url": "https://mcp-radardeprecos.fly.dev/mcp"
    }
  }
}
```

Clientes que só aceitam `stdio` (ex.: versões antigas do Claude Desktop, em
`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "radardeprecos": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp-radardeprecos.fly.dev/mcp"]
    }
  }
}
```

### Primeiras perguntas

> Faça uma pesquisa de preços para "papel A4 75g/m², resma com 500 folhas",
> com contratações homologadas dos últimos 12 meses, e gere o relatório em Word.

> Quem forneceu "serviço de limpeza predial" para órgãos federais em 2026?

> Consulte a situação e as sanções do CNPJ 00.000.000/0001-91.

O prompt `conduzir_pesquisa_precos` traz o roteiro completo de uma pesquisa,
orquestrando as tools na ordem recomendada.

### Verificando sem cliente

```bash
curl https://mcp-radardeprecos.fly.dev/
```

Responde com a versão, a lista de tools e contadores de uso. Para chamar as
tools manualmente, use o [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
(`npx @modelcontextprotocol/inspector`), com transporte **Streamable HTTP** e a
URL acima.

> **Sobre a instância pública:** é um ambiente de demonstração, sem garantia de
> disponibilidade. Tem limite de 60 requisições por minuto por origem e pode
> levar alguns segundos para responder na primeira chamada depois de ociosa.
> Relatórios e exportações voltam como arquivo para o cliente; nada é gravado no
> servidor. Para uso contínuo ou institucional, hospede a sua própria instância
> ([docs/DEPLOY.md](docs/DEPLOY.md)).

## Instalação local

Requer Python 3.10 ou superior.

```bash
pip install git+https://github.com/charlesmmorais/mcp-radardeprecos
```

Registre o servidor no seu cliente MCP. No Claude Desktop
(`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mcp-radardeprecos": { "command": "mcp-radardeprecos" }
  }
}
```

No modo local (`stdio`), os relatórios também podem ser gravados direto numa
pasta do seu computador.

Para hospedar via HTTP (Docker, nuvem, Microsoft 365 Copilot), veja
**[docs/DEPLOY.md](docs/DEPLOY.md)**.

## O que ele faz

| Etapa | Recursos |
|---|---|
| **Busca** | Busca textual e booleana no PNCP com todos os filtros do site; licitações com valor **homologado** por item; contratos, atas de registro de preço com saldo de adesão; preços praticados por item CATMAT/CATSER; arquivos (edital, TR, contrato) com link direto. |
| **Análise** | Preço de referência por escore Z iterativo (padrão), média saneada, mediana ou mínimo, com CV antes e depois e histórico de cada exclusão; detecção de mistura de objetos; normalização de unidades; matriz de comparabilidade; Curva ABC; correção monetária. |
| **Apoio** | Descoberta de códigos CATMAT/CATSER e UASG a partir de texto livre; due diligence de fornecedor (CNPJ, SICAF, sanções); tabelas de domínio do PNCP; radar de vencimento de contratos e atas. |
| **Formalização** | Memória de pesquisa e relatórios em Excel (4 abas) e Word (elementos I a VIII do Art. 3º da IN 65/2021), como rascunho com pendências marcadas para revisão; trilha de auditoria com hash de cada resposta. |

### Princípios

- **Ausência de informação nunca é apresentada como fato.** Toda tool que
  varre uma fonte devolve `cobertura` (`exaustiva`, `parcial`,
  `indeterminada` ou `vazia`) e diz se pode afirmar inexistência.
  "Não achei" é diferente de "não existe".
- **Só valores homologados ou contratados valem como referência**
  (Acórdãos TCU 6.405/2017-1C e 2.062/2016-1C). Valores estimados aparecem,
  mas identificados como tal.
- **Reduções de resultado são declaradas.** Janela temporal, filtros, tetos
  de paginação e orçamento de tempo aparecem em `avisos`.
- **O cálculo se explica.** `status_resultado` (`apto`, `requer_revisao`,
  `nao_apto`), motivo de parada do saneamento e cada exclusão com o CV que a
  motivou.
- **Dados pessoais protegidos.** CPF de fornecedor pessoa física sai
  mascarado; liberar exige configuração do servidor, nunca parâmetro de
  chamada.

## Tools

A descrição completa de cada tool — o que faz, como funciona e qual fonte
consulta — está em **[docs/FERRAMENTAS.md](docs/FERRAMENTAS.md)**.

<details>
<summary><b>48 tools</b> — clique para expandir</summary>

**Busca no PNCP**

| Tool | Descrição |
|---|---|
| `buscar_pncp_texto` | Busca textual no PNCP (editais, atas, contratos) com os filtros do site e janela temporal opcional. |
| `buscar_pncp_texto_booleano` | Busca com operadores E/OU/NÃO sobre a busca textual. |
| `contar_pncp` | Conta registros no índice do PNCP sem exigir termo de busca. |
| `listar_filtros_pncp` | Facetas válidas (modalidade, UF, órgão, município…), com contagens. |
| `listar_arquivos_pncp` | Arquivos de um edital, ata ou contrato, com link de download. |
| `buscar_contratacoes_pncp` | Licitações pelo objeto, com itens e valor unitário homologado. |
| `buscar_propostas_abertas` | Contratações com recebimento de propostas aberto agora. |
| `consultar_contratacao_pncp` | Detalhe completo de uma contratação, com links para o PNCP e o sistema de origem. |
| `consultar_ata_registro_preco` | Detalhe de uma ata, com itens, saldo e arquivos. |
| `consultar_familia_contratacao_pncp` | Edital, arquivos, ata e contratos derivados (com aditivos e empenhos) numa chamada. |
| `consultar_contratos_orgao_pncp` | Listagem exaustiva de contratos e empenhos de um CNPJ num período. |
| `consultar_notas_fiscais` | Instrumentos de cobrança e NF-e de um contrato — o preço efetivamente faturado. |
| `consultar_pca` | Itens do Plano de Contratação Anual (sinal de planejamento, não referência de preço). |
| `consultar_tabelas_dominio_pncp` | As tabelas de domínio do PNCP (amparo legal, tipo de contrato etc.). |

**Compras.gov.br e outras fontes de preço**

| Tool | Descrição |
|---|---|
| `buscar_precos_praticados_compras` | Preços praticados por item CATMAT/CATSER — fonte prioritária da IN 65/2021. |
| `buscar_homologados_14133` | Itens homologados da Lei 14.133 em massa, por catálogo, fornecedor ou órgão. |
| `buscar_precos_saude_bps` | Preços de medicamentos e dispositivos médicos no Banco de Preços em Saúde. |
| `buscar_contratos_compras` | Contratos pelo objeto, com valor global e link. |
| `buscar_arp_compras` | Atas de registro de preço com saldo de adesão, filtráveis por item no servidor. |
| `consultar_arp_detalhe_compras` | Itens, adesões, unidades e empenhos de uma ata. |
| `consultar_contratos_compras` | Contratos de um órgão por vigência. |
| `consultar_itens_contrato_compras` | Itens de contratos, com preço unitário. |
| `radar_vencimentos` | Contratos ou atas com fim de vigência num horizonte de dias. |
| `mapear_fornecedores_mercado` | Quem venceu contratações de um objeto, agregado por fornecedor. |

**Catálogo e órgãos**

| Tool | Descrição |
|---|---|
| `descobrir_codigo_catalogo` | Código CATMAT/CATSER a partir de texto livre, com ranking por qualidade. |
| `listar_itens_catalogo` | Itens de um PDM ou classe, com filtro textual. |
| `navegar_catalogo_servico` | Navegação hierárquica do catálogo de serviços (seção → subclasse). |
| `converter_para_unidade_base` | Converte preços para a unidade base, pela tabela do catálogo. |
| `descobrir_uasg` | Código de UASG/órgão a partir do nome. |

**Fornecedor**

| Tool | Descrição |
|---|---|
| `consultar_cnpj` | Cadastro do CNPJ na Receita Federal. |
| `consultar_situacao_fornecedor` | Situação no SICAF por CNPJ ou CPF. |
| `consultar_sancoes_fornecedor` | Sanções e idoneidade (TCU, CNJ, CEIS, CNEP) numa consulta. |

**Análise e cálculo**

| Tool | Descrição |
|---|---|
| `montar_cesta_precos` | Extrai a série de preços unitários dos registros de uma busca. |
| `normalizar_precos_unidade` | Converte preços para uma unidade comum, com fórmula e premissas por linha. |
| `agrupar_por_comparabilidade` | Agrupa preços por unidade, quantidade e período, com grau A–D de comparabilidade. |
| `detectar_inconsistencias` | Sinaliza armadilhas nos registros (unitário que parece global, homologado > estimado…). |
| `atualizar_precos_indice` | Corrige preços históricos por IPCA, IGP-M ou IPC-Fipe. |
| `calcular_preco_referencia` | Escore Z iterativo, média saneada, mediana ou mínimo, com CV e avisos. |
| `pesquisar_cesta_precos` | Preço de referência de vários itens de uma vez, com total consolidado. |
| `classificar_curva_abc` | Classes A/B/C por valor acumulado, para dosar o esforço de pesquisa. |
| `classificar_objeto_tic` | Classificação heurística TIC/SaaS por palavra-chave. |
| `gerar_estudo_mercado_tic` | Matriz de comparabilidade de soluções de TIC (Estudo Técnico Preliminar). |
| `obter_diretrizes_pesquisa_precos` | Premissas metodológicas da pesquisa de preços, em JSON. |

**Formalização e exportação**

| Tool | Descrição |
|---|---|
| `gerar_memoria_pesquisa` | Consolida objeto, fontes, buscas frustradas e cálculo num documento (JSON/Markdown). |
| `gerar_relatorio_excel` | Planilha da pesquisa em 4 abas. |
| `gerar_relatorio_word` | Documento conforme o Art. 3º, I a VIII, da IN 65/2021. |
| `exportar_resultados` | Exporta qualquer lista de registros para CSV ou XLSX. |
| `exportar_trilha_auditoria` | Dossiê de proveniência: URL, parâmetros, horário e hash SHA-256 de cada consulta. |

</details>

Também disponíveis: o resource `docs://boas-praticas-pesquisa-precos`
(diretrizes em Markdown) e o prompt `conduzir_pesquisa_precos`.

## Metodologia

O fluxo e o cálculo seguem a IN SEGES/ME nº 65/2021 e a jurisprudência do TCU
consolidada em *Pesquisa de preços — um guia prático de sobrevivência*
(Franklin Brasil): hierarquia de fontes, mínimo de referências, janela
temporal, média saneada (Acórdão 355/2019-P) e escore Z (preferencial para
TIC — IPPC-TIC/AGU).

O saneamento é governado pelo coeficiente de variação: com CV inicial de até
25%, nada é removido; acima disso, o escore Z remove um valor por vez — o de
maior |Z| — até atingir a meta, chegar ao piso de 3 referências ou ao limite
de iterações. Detalhes em
[docs/BOAS_PRATICAS_PESQUISA_PRECOS.md](docs/BOAS_PRATICAS_PESQUISA_PRECOS.md).

### Modelos de relatório

| `modelo` | Status |
|---|---|
| `in65` (padrão) | Formalização conforme o Art. 3º, I a VIII, da IN 65/2021. |
| `tic_licitacao` | Reservado (TIC via licitação, Art. 8º) — ainda não implementado. |
| `tic_inexigibilidade` | Reservado (TIC via inexigibilidade/dispensa, Art. 7º) — ainda não implementado. |

## Configuração

Nenhuma variável é obrigatória. Veja [`.env.example`](.env.example).

| Variável | Padrão | Descrição |
|---|---|---|
| `RADARDEPRECOS_TRANSPORT` | `stdio` | `stdio`, `sse` ou `streamable-http`. |
| `RADARDEPRECOS_RATE_LIMIT_PER_MINUTE` | `60` | Requisições por minuto por origem, nos transportes HTTP. |
| `RADARDEPRECOS_HTTP_TIMEOUT` | `30` | Timeout (s) por chamada às fontes. |
| `RADARDEPRECOS_HTTP_MAX_RETRIES` | `4` | Tentativas em falha de rede, 429 e 5xx (backoff exponencial com jitter). |
| `RADARDEPRECOS_TOOL_BUDGET_SECONDS` | `120` | Orçamento de tempo das varreduras amplas; ao estourar, devolve o parcial com aviso. `0` desativa. |
| `RADARDEPRECOS_LOG_LEVEL` | `INFO` | Nível de log (estruturado, com `request_id` por chamada). |
| `RADARDEPRECOS_PERMITIR_CAMINHO_SAIDA` | — | Libera `caminho_saida` nos transportes HTTP. Use só quando o servidor roda na sua máquina. |
| `RADARDEPRECOS_INCLUIR_CPF_COMPLETO` | — | Desliga o mascaramento de CPF de fornecedor pessoa física. |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_REQUIRED_SCOPE` | — | Autenticação Microsoft Entra ID nos transportes HTTP (opcional). |

Nos transportes HTTP, `GET /` responde com versão, catálogo de tools e
contadores de uso em memória. O endpoint MCP é `/mcp`.

## Desenvolvimento

```bash
git clone https://github.com/charlesmmorais/mcp-radardeprecos
cd mcp-radardeprecos
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check src tests
pytest                 # suíte offline (APIs simuladas com respx)
pytest -m live         # testes contra as APIs reais
```

A suíte tem mais de mil testes, incluindo exemplos de cálculo reproduzidos do
guia do TCU, geração real dos arquivos Excel/Word e detectores que reprovam o
build se um defeito já corrigido reaparecer. Os testes `live` rodam
semanalmente no CI para detectar mudanças nas APIs.

Documentação técnica:

- [Ferramentas](docs/FERRAMENTAS.md) — o que cada tool faz e de onde vêm os dados
- [Arquitetura](docs/ARQUITETURA.md) — camadas, responsabilidades e decisões
- [Fontes de dados](docs/FONTES_DE_DADOS.md) — endpoints usados e limitações de cada API
- [Comportamento das fontes](docs/ACHADOS_DAS_FONTES.md) — o que foi medido nas APIs reais
- [Hospedagem](docs/DEPLOY.md) — Docker, HTTP e conexão com clientes
- [Microsoft 365 Copilot](docs/INTEGRACAO_M365_COPILOT.md) — autenticação Entra ID

## Contribuindo

Contribuições são bem-vindas — veja o [guia de contribuição](CONTRIBUTING.md) e
o [código de conduta](CODE_OF_CONDUCT.md). Para relatar uma vulnerabilidade,
siga a [política de segurança](SECURITY.md).

## Aviso

Este é um projeto independente, sem vínculo com o governo federal ou com os
órgãos responsáveis pelas fontes consultadas. Os resultados apoiam a pesquisa
de preços, mas não substituem a análise e a responsabilidade do agente
público.

## Licença

Distribuído sob a licença [Apache-2.0](LICENSE). Para citar este software, veja
[CITATION.cff](CITATION.cff).
