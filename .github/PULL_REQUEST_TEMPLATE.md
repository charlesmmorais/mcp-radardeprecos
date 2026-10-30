## O que muda

<!-- Descreva a mudança e o motivo. Referencie a issue, se houver: "Resolve #123". -->

## Como foi verificado

- [ ] `ruff check src tests`
- [ ] `pytest`
- [ ] Testado contra a API real (`pytest -m live` ou chamada manual), quando muda a integração com uma fonte

## Checklist

- [ ] A docstring da tool descreve parâmetros e retorno (é o que o cliente MCP vê)
- [ ] Reduções de resultado aparecem em `avisos`
- [ ] `CHANGELOG.md` atualizado na seção "Não publicado"
