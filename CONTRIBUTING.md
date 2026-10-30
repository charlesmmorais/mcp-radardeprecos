# Como contribuir

Obrigado pelo interesse em melhorar o mcp-radardeprecos. Relatos de defeito,
sugestões e pull requests são bem-vindos.

## Antes de começar

- Para mudanças maiores (nova tool, nova fonte, mudança de comportamento),
  abra uma issue primeiro para alinhar a abordagem.
- Vulnerabilidades de segurança seguem a [política de segurança](SECURITY.md),
  nunca uma issue pública.

## Ambiente

```bash
git clone https://github.com/charlesmmorais/mcp-radardeprecos
cd mcp-radardeprecos
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Verificação

```bash
ruff check src tests
pytest                 # offline, APIs simuladas com respx
pytest -m live         # contra as APIs reais, quando mexer em integração
```

O CI roda lint e testes em Python 3.10 a 3.13, além do build do pacote e da
imagem Docker.

## Convenções

- **Uma tool por arquivo** em `src/mcp_radardeprecos/tools/`. A assinatura e a
  docstring são a única fonte do schema que o cliente MCP vê: descreva cada
  parâmetro e o retorno.
- **Detalhes das APIs ficam em `clients/`**: nomes reais de parâmetros,
  paginação e comportamentos inesperados. A tool não deveria precisar saber
  disso.
- **Nunca reduza resultados em silêncio.** Filtros no cliente, tetos de
  paginação e orçamentos de tempo devem aparecer em `avisos`; tools que varrem
  uma fonte devolvem `cobertura`.
- **Só valores homologados ou contratados são referência de preço.** Valores
  estimados podem aparecer, mas rotulados como tal.
- **Teste sem rede.** Use `respx` para simular as APIs; testes contra a fonte
  real levam o marcador `live`.
- Registre a nova tool em `server.py` e atualize a tabela do `README.md`.
- Descreva a mudança em `CHANGELOG.md`, na seção "Não publicado".

Veja [docs/ARQUITETURA.md](docs/ARQUITETURA.md) para o desenho completo.

## Pull requests

- Um assunto por pull request.
- Mensagens de commit no imperativo, em português (ex.: "Adiciona filtro por
  UF em buscar_arp_compras").
- O CI precisa passar.

Ao contribuir, você concorda que sua contribuição será licenciada sob a
[Apache-2.0](LICENSE) e se compromete a seguir o
[código de conduta](CODE_OF_CONDUCT.md).
