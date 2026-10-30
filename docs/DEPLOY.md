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

### Microsoft 365 Copilot

Exige autenticação Entra ID. Veja
[INTEGRACAO_M365_COPILOT.md](INTEGRACAO_M365_COPILOT.md).

## Verificação

`scripts/smoke_mcp.py` faz um teste de ponta a ponta contra um servidor em
execução, usando só a biblioteca padrão:

```bash
python scripts/smoke_mcp.py https://<seu-host>
```

Ele faz o handshake MCP, lista as tools e chama uma tool
sem rede e outra que consulta o PNCP. Se a tool sem rede passa e a de rede
falha, o problema está na saída de rede do ambiente, não no servidor.
