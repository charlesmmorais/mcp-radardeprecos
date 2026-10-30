# Microsoft 365 Copilot e autenticação Entra ID

Agentes declarativos do Microsoft 365 Copilot consomem servidores MCP por
`streamable-http`, mas **exigem autenticação OAuth 2.0 via Microsoft Entra
ID**: não existe modo sem login. O mcp-radardeprecos traz essa camada como
opcional. Sem as variáveis abaixo, nada muda.

## Habilitando

```bash
ENTRA_TENANT_ID=<directory-tenant-id> \
ENTRA_CLIENT_ID=<application-client-id> \
mcp-radardeprecos --transport streamable-http --host 0.0.0.0 --port 8000
```

`ENTRA_REQUIRED_SCOPE` (opcional) exige esse scope (`scp`, tokens delegados)
ou role (`roles`, tokens de aplicação). Sem ela, qualquer token válido do
tenant e da audience configurados é aceito.

## Comportamento

- `/mcp` e `/sse` passam a exigir `Authorization: Bearer <token>`. O JWT é
  validado localmente: assinatura RS256 pelas chaves públicas (JWKS) do
  tenant, `aud`, `iss`, `exp`/`nbf` e scope, se configurado.
- `GET /` e `GET /.well-known/*` continuam abertos, para monitoramento e
  descoberta.
- `GET /.well-known/oauth-protected-resource` anuncia o Entra do tenant como
  authorization server (RFC 9728). É por ele que o Agents Toolkit descobre
  onde autenticar o usuário.
- Token inválido responde `401` com `WWW-Authenticate: Bearer
  error="invalid_token"`; a causa fica no log estruturado.
- Falha ao buscar as chaves do Entra responde `503`, não `401`:
  instabilidade do Entra não deve parecer token inválido.
- As chaves ficam em cache (`RADARDEPRECOS_JWKS_TTL`, padrão 3600 s) e são
  recarregadas na hora quando chega um token com `kid` desconhecido.
- O rate limit continua por fora da autenticação, barrando abuso antes de
  gastar CPU validando JWT.

## Passo a passo

Requer um tenant Microsoft 365 com licença para agentes Copilot
personalizados.

1. **Portal do Azure → Microsoft Entra ID → App registrations → New
   registration.** Anote o *Application (client) ID* (`ENTRA_CLIENT_ID`) e o
   *Directory (tenant) ID* (`ENTRA_TENANT_ID`).
2. **Expose an API:** defina um Application ID URI e ao menos um scope (ex.:
   `access_as_user`) — o valor de `ENTRA_REQUIRED_SCOPE`, se quiser exigi-lo.
3. **Redirect URIs:** adicione as URIs indicadas pelo Microsoft 365 Agents
   Toolkit ao configurar a autenticação do agente.
4. **Publique o servidor** com as variáveis como segredos do provedor.
5. **Microsoft 365 Agents Toolkit** (VS Code): crie um agente declarativo →
   *Add Action* → *Start with an MCP server* → `https://<seu-host>/mcp`. O
   Toolkit lê os metadados de recurso protegido e conduz o fluxo OAuth.
6. **Teste ponta a ponta** no Copilot e ajuste scope e audience conforme o
   erro retornado.

## Fora de escopo

- Autorização por tool ou por usuário: todas as tools leem dados públicos; o
  token serve para governança e registro de quem chamou, não para restringir
  conteúdo.
- Multi-tenant dinâmico: um tenant por instância.

## Referências

- [Configure authentication for MCP and API plugins in Microsoft 365 Copilot](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-authentication)
- [Build plugins from an MCP server for Microsoft 365 Copilot](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/build-mcp-plugins)
