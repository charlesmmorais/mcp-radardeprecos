# Política de segurança

## Versões suportadas

| Versão | Suporte |
|---|---|
| 1.x | ✅ |

## Como relatar uma vulnerabilidade

**Não abra issue pública.** Use o
[relato privado de vulnerabilidades](https://github.com/charlesmmorais/mcp-radardeprecos/security/advisories/new)
do GitHub e inclua:

- descrição do problema e do impacto;
- passos para reproduzir;
- versão afetada e transporte usado (`stdio` ou HTTP).

Você receberá confirmação de recebimento em até 5 dias úteis. Depois da
correção, a vulnerabilidade é divulgada no advisory e no `CHANGELOG.md`,
com crédito a quem relatou, se desejar.

## Modelo de segurança

- **Somente leitura de dados públicos.** O servidor não guarda credenciais e
  não exige nenhuma para consultar as fontes.
- **Transportes HTTP** aplicam rate limit por origem e recusam `caminho_saida`
  (o disco é o do servidor). Autenticação é opcional, via Microsoft Entra ID.
- **Dados pessoais:** CPF de fornecedor pessoa física é mascarado por padrão.
- O servidor hospedado deve ficar atrás de HTTPS.

Ao hospedar uma instância própria, revise as variáveis descritas no
[README](README.md#configuração) e em [docs/DEPLOY.md](docs/DEPLOY.md).
