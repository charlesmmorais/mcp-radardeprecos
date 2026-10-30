# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto adota o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não publicado]

## [1.0.1] — 2026-10-30

### Corrigido

- `calcular_preco_referencia`: o escore Z parava na 10ª exclusão, mesmo longe
  da meta de CV. Amostras grandes ficavam como `nao_apto` sem chegar ao preço
  (378 preços do CATMAT 267203 precisam de 49 exclusões). O teto de iterações
  foi removido: o saneamento busca CV ≤ 25% e, se chegar ao piso de 3
  referências antes, fica com a amostra de menor CV encontrada no caminho —
  remover o maior |Z| às vezes aumenta o CV. O motivo de parada
  `limite_iteracoes` deixa de existir.
- `buscar_precos_praticados_compras`: uma data de compra informada sozinha era
  aceita, mas o Compras.gov.br ignora o filtro nesse caso e devolve todos os
  períodos — a série inteira parecia filtrada. A tool agora exige as duas datas,
  no formato `AAAA-MM-DD`, com o início antes do fim.
- As diretrizes metodológicas (`obter_diretrizes_pesquisa_precos` e o resource)
  ainda apresentavam a média saneada iterativa como método padrão; passam a
  descrever o escore Z, que é o padrão, e a média saneada de passe único.

### Adicionado

- Aviso quando o escore Z exclui mais de 20% de uma amostra com 20 preços ou
  mais. É informativo e não muda `status_resultado`.
- `data_compra` em cada preço de `buscar_precos_praticados_compras`, ao lado de
  `data_resultado`, e o bloco `periodo`: critério, período pedido, período
  observado, registros fora do período e registros com resultado anterior à
  compra (erro de cadastro na fonte).
- Ícone do navegador em `/favicon.ico`, liberado também quando a autenticação
  Entra ID está ativa.
- Seção de teste rápido no README com a instância pública e a configuração de
  cada cliente MCP, inclusive Gemini.
- `docs/FERRAMENTAS.md`, com a descrição e a fonte de cada tool.

## [1.0.0] — 2026-10-30

Primeira versão pública.

### Adicionado

- 48 tools MCP sobre PNCP, Compras.gov.br, Banco de Preços em Saúde, Banco
  Central (SGS), Receita Federal (CNPJ) e TCU.
- Cálculo de preço de referência por escore Z iterativo, média saneada,
  mediana ou mínimo, com veredito legível por máquina (`status_resultado`),
  motivo de parada e histórico de cada exclusão.
- Detecção de mistura de objetos numa série de preços.
- Contrato único de `cobertura` em todas as tools que varrem fontes, separando
  "não encontrado" de "não existe".
- Normalização de unidades, matriz de comparabilidade e detecção de
  inconsistências nos registros coletados.
- Correção monetária por IPCA, IGP-M ou IPC-Fipe.
- Memória de pesquisa e relatórios em Excel e Word conforme o Art. 3º da
  IN SEGES/ME nº 65/2021.
- Trilha de auditoria com URL, parâmetros, horário e hash SHA-256 de cada
  consulta às fontes.
- Resource `docs://boas-praticas-pesquisa-precos` e prompt
  `conduzir_pesquisa_precos`.
- Transportes `stdio`, `sse` e `streamable-http`, com rate limit por origem e
  autenticação Microsoft Entra ID opcional.
- Imagem Docker com usuário sem privilégios e health check.

[Não publicado]: https://github.com/charlesmmorais/mcp-radardeprecos/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/charlesmmorais/mcp-radardeprecos/releases/tag/v1.0.1
[1.0.0]: https://github.com/charlesmmorais/mcp-radardeprecos/releases/tag/v1.0.0
