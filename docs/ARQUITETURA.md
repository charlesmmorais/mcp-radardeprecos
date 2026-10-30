# Arquitetura

Este documento descreve as camadas do projeto, onde cada informação mora e
as decisões que orientam o código. Serve de referência para adicionar tools
ou filtros sem quebrar a consistência.

## Camadas

```
src/mcp_radardeprecos/
├── server.py            Registro MCP (camada fina) e seleção de transporte
├── config.py            Configuração por variáveis de ambiente
├── logging_utils.py     Logs estruturados com request_id
├── observability.py     Contadores em memória por tool, fonte e cliente MCP
├── metricas_prometheus.py  Exportação Prometheus (opcional, porta interna)
├── auditoria.py         Trilha de proveniência de cada consulta às fontes
├── catalogo.py          Digest do catálogo de tools, exposto no health check
├── rate_limit.py        Rate limit por origem (transportes HTTP)
├── auth/                Autenticação Microsoft Entra ID opcional
│   ├── entra.py           Validação de JWT e cache de JWKS
│   └── middleware.py      Middleware ASGI
├── clients/             Como cada API externa espera ser chamada
│   ├── base.py            HTTP compartilhado: timeout, retry, cache, erros
│   ├── pncp_client.py     PNCP: busca do site, API de Consulta, arquivos
│   ├── compras_client.py  Compras.gov.br: preços, catálogos, ARP, contratos, SICAF
│   ├── bps_client.py      Banco de Preços em Saúde
│   ├── bcb_client.py      Séries do SGS (IPCA, IGP-M, IPC-Fipe)
│   ├── cnpj_client.py     Cadastro de CNPJ (BrasilAPI, MinhaReceita)
│   └── tcu_client.py      Consulta consolidada de sanções
├── domain/              Regras e tabelas de domínio, sem I/O
│   ├── dominios.py        Tabelas de código, domínios do PNCP, modelos de relatório
│   ├── diretrizes_pesquisa_precos.py  Premissas metodológicas (tool e resource)
│   ├── cobertura.py       Contrato de cobertura de uma consulta
│   ├── distribuicao.py    Detecção de mistura de objetos numa série
│   └── capacidade.py      Interpretação da capacidade de unidades de fornecimento
├── tools/               Uma tool por arquivo — fonte única de assinatura e docstring
├── prompts/             Prompts MCP (roteiros que o usuário seleciona)
└── utils/               Lógica compartilhada entre tools
    ├── varredura.py       Varredura paginada e concorrente do índice do PNCP
    ├── paginacao.py       Metadados de paginação padronizados
    ├── cache.py           Cache em memória com TTL e teto de entradas
    ├── datas.py           Janelas temporais
    ├── documentos.py      CNPJ (inclusive alfanumérico) e CPF, com mascaramento
    ├── numeros.py         Identificadores como texto
    ├── texto_busca.py     Comparação tolerante a acento e caixa
    └── arquivo_saida.py   Saída em disco ou base64
```

## Cada informação tem um dono

| Informação | Onde vive | Por quê |
|---|---|---|
| Nome real dos parâmetros das APIs (`ufs`, `tipos_documento`…) | `clients/` | Detalhe de integração; a tool não precisa saber. |
| Comportamentos inesperados das APIs | `clients/` (docstrings) e [ACHADOS_DAS_FONTES.md](ACHADOS_DAS_FONTES.md) | Conhecimento sobre a fonte, não sobre o produto. |
| Assinatura e descrição de cada tool | `tools/` | É o que o cliente MCP vê; existe em um lugar só. |
| Códigos e tabelas de domínio | `domain/dominios.py` | Validação de entrada e tabelas expostas saem da mesma fonte. |
| Premissas metodológicas | `domain/diretrizes_pesquisa_precos.py` | Alimenta a tool (JSON) e o resource (Markdown). |
| Lógica usada por mais de uma tool | `utils/` | Se duas tools precisam dela, não pertence a nenhuma. |

## `server.py` é uma camada fina

O FastMCP gera o schema de cada tool por introspecção da assinatura, e essa
introspecção segue `__wrapped__`. Por isso o registro usa
`functools.wraps`: o wrapper herda nome, assinatura e docstring da
implementação em `tools/`, e nada é escrito duas vezes. O nome MCP é
passado explicitamente, porque `wraps` também sobrescreve `__name__`.

O wrapper é o único ponto por onde passa toda chamada de tool, e por isso
concentra o que vale para todas:

- **request_id** e **métricas** (chamadas, erros, latência) por tool;
- **trilha de auditoria**: a tool corrente fica num `ContextVar`, e
  `clients/base.get_json` registra URL, parâmetros, status e hash de cada
  resposta;
- **inteiros grandes**: qualquer inteiro acima de 2⁵³−1 vira texto e o
  caminho do campo vai para o log e para `avisos`. Isso é uma rede de
  segurança: campos conhecidos já saem como texto na própria tool, porque um
  tipo que muda conforme a magnitude do valor é pior que qualquer tipo fixo.

As anotações MCP (`readOnlyHint`, `openWorldHint`…) também são definidas
ali, por exceção: só as tools que geram arquivo deixam de ser somente
leitura, e só as que não acessam rede têm `openWorldHint=False`. Um teste
confere essa lista contra os imports reais de cada módulo.

### Rotas HTTP

| Rota | Função |
|---|---|
| `/mcp` (ou `/sse`) | Protocolo MCP. |
| `GET /` | Versão, catálogo (com digest) e métricas. O digest separa "cliente com cache velho" de "deploy que não aplicou". |
| `POST /` | `405` com corpo explicando que o endpoint é `/mcp`. |
| `GET /.well-known/oauth-protected-resource` | Só com Entra ID habilitado. |

A cadeia de middlewares é `RateLimitMiddleware → EntraAuthMiddleware
(opcional) → app do FastMCP`: o rate limit fica por fora para barrar abuso
antes de gastar CPU validando JWT.

## Clientes HTTP

`clients/base.py` concentra a política de rede:

- um `httpx.AsyncClient` reutilizado (sem novo handshake TLS por chamada);
- retry com backoff exponencial e jitter em timeout, erro de transporte e
  429/502/503/504, respeitando `Retry-After`. Conexão derrubada recebe
  repetição curta (o que cura é uma conexão nova); servidor lento recebe
  espera maior;
- erros 4xx de validação nunca são repetidos;
- `204` e corpo vazio devolvem `None`, e cada tool decide o que o vazio
  significa;
- cache opcional por chamada (`utils/cache.py`), com TTL e teto de entradas.

## Cobertura: "não achei" não é "não existe"

Toda tool que varre uma fonte devolve `cobertura` (`domain/cobertura.py`):
status (`exaustiva`, `parcial`, `indeterminada`, `vazia`), percentual
examinado, motivo de interrupção e `pode_afirmar_inexistencia`. A varredura
do índice do PNCP (`utils/varredura.py`) roda páginas em paralelo, tolera
página que falha e respeita um orçamento de tempo; quando estoura, devolve o
parcial com aviso em vez de deixar o cliente MCP descartar tudo por timeout.

## O cálculo do preço de referência

`tools/calcular_preco_referencia.py` é a única tool que decide algo além de
projetar dados. Três decisões:

1. **O saneamento é governado pelo CV.** O padrão é o escore Z iterativo:
   com CV inicial de até 25%, nada é removido; acima disso, sai um valor por
   vez, recalculando o CV. A média saneada (Acórdão TCU 355/2019-P) é de
   passe único — reaplicar o corte µ±1σ não converge e consome a amostra. Uma
   só convenção de desvio-padrão (amostral, n−1) vale para todos os métodos.
2. **Toda parada é nomeada.** `motivo_parada_saneamento` é um enum, e o
   texto do aviso é derivado dele, não escrito à mão em cada ramo.
3. **Resultado suspeito é marcado, não apagado.** Quando `domain/distribuicao.py`
   detecta mistura de objetos, o `preco_referencia` continua na resposta para
   auditoria, mas `status_resultado` e `apto_para_preco_referencia` dizem que
   ele não serve como referência. `historico_saneamento` traz uma linha por
   exclusão, para que cada corte possa ser contestado.

## Testes

```bash
pytest            # offline, com as APIs simuladas por respx
pytest -m live    # contra as APIs reais (semanal no CI)
```

A suíte cobre a montagem de cada chamada às APIs, filtros, paginação,
retry, cálculo estatístico (com exemplos reproduzidos do guia do TCU),
geração dos arquivos Excel e Word (reabertos e conferidos), autenticação
Entra (com chaves de teste) e o registro das tools no servidor.

Duas categorias protegem contra classes de defeito, não contra casos:

- **Detectores por AST** varrem todos os arquivos procurando um padrão já
  corrigido (ex.: documento de fornecedor devolvido sem mascaramento). Cada
  detector vem com um controle que reintroduz o defeito numa cópia e prova
  que ele dispara — detector que nunca acusa não protege nada.
- **Guardas de contrato anunciado** comparam o que a docstring promete com o
  que o código faz (ex.: o método padrão do cálculo).
