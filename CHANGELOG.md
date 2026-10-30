# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto adota o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não publicado]

### Adicionado

- Seção de teste rápido no README com a instância pública e a configuração
  de cada cliente MCP.
- `docs/FERRAMENTAS.md`, com a descrição e a fonte de cada tool.
- Ícone do navegador em `/favicon.ico`, liberado também quando a autenticação
  Entra ID está ativa.

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

[Não publicado]: https://github.com/charlesmmorais/mcp-radardeprecos/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/charlesmmorais/mcp-radardeprecos/releases/tag/v1.0.0
