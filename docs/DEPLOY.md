# Hospedagem e conexão com clientes

Sem argumentos, o servidor roda em `stdio`, o modo usado por clientes
locais como o Claude Desktop. Este guia cobre os transportes HTTP, o
container e a conexão com cada cliente.

## Uso local (stdio)

```json
{
  "mcpServers": {
    "mcp-radardeprecos": { "command": "mcp-radardeprecos" }
  }
}
```

## Transportes HTTP

```bash
mcp-radardeprecos --transport streamable-http --host 0.0.0.0 --port 8000
```

| Rota | Função |
|---|---|
| `POST /mcp` | Protocolo MCP (`streamable-http`). Com `--transport sse`, o endpoint é `/sse`. |
| `GET /` | Health check: versão, catálogo de tools (com digest) e contadores de uso em memória. |
| `GET /.well-known/oauth-protected-resource` | Só com Entra ID habilitado. |

A URL configurada no cliente termina em `/mcp`. Um `POST` na raiz recebe
`405` com o endereço correto no corpo.

### Comportamento em HTTP

- **Rate limit por origem** (padrão 60 req/min, janela deslizante em
  memória). A origem vem de `Fly-Client-IP`, do último IP de
  `X-Forwarded-For` ou do IP da conexão. Com várias réplicas, o limite vale
  por processo.
- **`caminho_saida` recusado.** Relatórios e exportações voltam em
  `conteudo_base64` com um `nome_arquivo` único; o cliente salva do lado do
  usuário. Se o servidor HTTP roda na sua própria máquina (ex.: túnel para o
  ChatGPT), libere com `RADARDEPRECOS_PERMITIR_CAMINHO_SAIDA=1`. Nunca faça
  isso num servidor compartilhado.
- **Sem autenticação por padrão.** Os dados são públicos e as tools só
  leem; o que precisa ser isolado num servidor compartilhado é a carga, coberta
  pelo rate limit. Para exigir login corporativo, veja
  [Microsoft Entra ID](INTEGRACAO_M365_COPILOT.md).
- **Proteção contra DNS rebinding do SDK desligada.** Ela só aceita `Host` de
  localhost e rejeitaria (421) qualquer domínio público. O ataque que ela
  previne mira servidores locais acessados por navegador.

## Docker

```bash
docker build -t mcp-radardeprecos .
docker run -d --name radar -p 8080:8080 mcp-radardeprecos
curl http://localhost:8080/
```

Ou `docker compose up -d`. A imagem roda como usuário sem privilégios e tem
`HEALTHCHECK` em `/`.

Para usar a imagem em `stdio` no Claude Desktop:

```json
{
  "mcpServers": {
    "mcp-radardeprecos": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp-radardeprecos",
               "mcp-radardeprecos", "--transport", "stdio"]
    }
  }
}
```

## Hospedagem na nuvem

Qualquer provedor que rode containers serve. Recomendações:

- Exponha atrás de HTTPS público.
- Prefira uma região no Brasil, para reduzir a latência até as fontes.
- Configure as variáveis do [README](../README.md#configuração) como
  variáveis de ambiente ou segredos do provedor.
- Se a plataforma suspende máquinas ociosas, espere alguns segundos de
  partida a frio na primeira chamada.

## Conectando clientes

### Claude (conector personalizado)

Em **Configurações → Conectores → Adicionar conector personalizado**,
informe `https://<seu-host>/mcp`. A conexão parte da infraestrutura da
Anthropic, então o servidor precisa estar acessível publicamente. Veja a
[documentação de conectores remotos](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

### ChatGPT (modo desenvolvedor)

1. Rode o servidor em `streamable-http` (local ou hospedado).
2. Se for local, exponha-o com um túnel HTTPS (ngrok, Cloudflare Tunnel ou o
   túnel do próprio ChatGPT).
3. Em **Configurações → Apps e conectores → Modo desenvolvedor → Criar**,
   informe a URL terminada em `/mcp`, sem autenticação.

### Gemini

O servidor precisa estar acessível publicamente por HTTPS, como para o Claude.

1. Em [gemini.google.com](https://gemini.google.com), **no navegador** (o app de
   celular não permite adicionar conectores), abra o ícone **Personalizar** da
   barra lateral → **[Conectores](https://gemini.google.com/customize/connectors)**.
   Em algumas contas o caminho é **Configurações → Apps conectados**.
2. Em **Apps personalizados**, adicione o link do conector: a URL terminada em
   `/mcp`. Não há credencial a informar.
3. Siga as instruções da tela para concluir.
4. No chat, digite `@` e escolha o conector.

Depois de adicionado, o conector também fica disponível no app de celular.
Segundo a [ajuda do Google](https://support.google.com/gemini/answer/17209137),
o recurso exige conta Google pessoal (não funciona com contas de trabalho ou
escola) e a **Atividade nos apps do Gemini** ligada; a disponibilidade varia por
país e idioma. O Gemini pede confirmação antes de ações que gravam algo — as
tools deste servidor declaram quais são de leitura e quais geram arquivo.

### Microsoft 365 Copilot

Exige autenticação Entra ID. Veja
[INTEGRACAO_M365_COPILOT.md](INTEGRACAO_M365_COPILOT.md).

## Observabilidade

Com o extra `metrics` instalado (a imagem Docker já o inclui) e
`RADARDEPRECOS_METRICS_PORT` definida, o servidor publica métricas no formato
Prometheus em `http://<host>:<porta>/metrics`, numa porta **separada** da do
MCP. Assim elas podem ficar fora da internet: só quem está na rede interna lê.

| Métrica | Tipo | O que mede |
|---|---|---|
| `radardeprecos_tool_chamadas_total{tool}` | contador | Chamadas por tool |
| `radardeprecos_tool_erros_total{tool}` | contador | Chamadas com erro por tool |
| `radardeprecos_tool_duracao_segundos{tool,quantil}` | gauge | p50 e p95 da duração, por tool |
| `radardeprecos_fonte_chamadas_total{fonte}` | contador | Chamadas a cada fonte (PNCP, Compras.gov.br, BPS, BCB, TCU, CNPJ) |
| `radardeprecos_fonte_erros_total{fonte}` | contador | Chamadas a cada fonte que falharam |
| `radardeprecos_fonte_tentativas_total{fonte}` | contador | Requisições HTTP, contando repetições — acima de 1 por chamada, a fonte está instável |
| `radardeprecos_fonte_duracao_segundos{fonte,quantil}` | gauge | p50 e p95 da duração, por fonte |
| `radardeprecos_cliente_sessoes_total{cliente}` | contador | Sessões por cliente MCP |
| `radardeprecos_cliente_chamadas_total{cliente}` | contador | Chamadas por cliente MCP |
| `radardeprecos_sessoes_total` | contador | Sessões (conversas) MCP distintas |
| `radardeprecos_protocolo_chamadas_total{versao}` | contador | Chamadas por versão do protocolo MCP |
| `radardeprecos_info{versao}` | gauge | Versão em execução |

O **cliente** é o nome que o próprio software informa no handshake (Claude,
ChatGPT, Gemini…), limitado a 30 nomes distintos. Não há IP nem dado pessoal, e
uma sessão é uma conversa, não uma pessoa. Os contadores vivem em memória e
zeram quando o processo reinicia; o Prometheus trata isso em `rate()` e
`increase()`.

### No Fly.io

O `fly.toml` do repositório já liga as métricas na porta interna 9091 (seção
`[metrics]`) — ela não está no `http_service`, então não fica exposta na
internet. O Fly coleta automaticamente; para ver:

1. Abra o Grafana gerenciado do Fly: no painel do app, **Metrics** → *Learn how
   to access Prometheus or set up Grafana*, ou direto em
   [fly-metrics.net](https://fly-metrics.net).
2. **Dashboards → New → Import** e envie
   [`docs/grafana/painel-radardeprecos.json`](grafana/painel-radardeprecos.json).
3. Escolha a fonte de dados Prometheus da sua organização e o app
   `mcp-radardeprecos`.

O painel mostra chamadas e erros por tool, as tools mais usadas, latência,
sessões por cliente MCP e a saúde de cada fonte de dados.

## Verificação

`scripts/smoke_mcp.py` faz um teste de ponta a ponta contra um servidor em
execução, usando só a biblioteca padrão:

```bash
python scripts/smoke_mcp.py https://<seu-host>
```

Ele faz o handshake MCP, lista as tools e chama uma tool
sem rede e outra que consulta o PNCP. Se a tool sem rede passa e a de rede
falha, o problema está na saída de rede do ambiente, não no servidor.
