# Boas práticas de pesquisa de preços

Este documento resume a metodologia que o mcp-radardeprecos segue e mapeia
cada etapa às tools que a apoiam. As referências principais são a
**IN SEGES/ME nº 65/2021**, o guia *Pesquisa de preços — um guia prático de
sobrevivência* (Franklin Brasil, 2020), que consolida a jurisprudência do
TCU, e, para TIC, o **IPPC-TIC** (AGU/MGI, 2024) e as orientações da
Secretaria de Governo Digital.

O guia organiza a pesquisa em cinco fases: **Objeto → Planejamento → Coleta →
Tratamento → Formalização**.

> **Reajuste não é pesquisa de preços.** Pesquisa de preços estima o valor de
> uma contratação **nova** a partir de uma cesta de referências; reajustar um
> contrato **vigente** é outro problema. Aqui, `atualizar_precos_indice` serve
> para trazer preços históricos a uma data-base comum antes do cálculo.

## 1. Fundamentos: cesta de preços e prioridade de fontes

O preço de referência resulta de uma **cesta de preços aceitáveis**, não de
"três orçamentos". Ordem de prioridade das fontes:

1. Preços praticados no setor público (CATMAT/CATSER) — priorizados pela IN 65/2021;
2. Contratações do próprio órgão;
3. Atas de registro de preços vigentes de outros órgãos;
4. Mídia especializada e comércio eletrônico;
5. Cotação direta com fornecedores — último recurso.

Mínimo de três referências; menos, só com justificativa de limitação de
mercado. **Só valem preços vencedores, homologados ou contratados** — nunca o
valor estimado de um edital nem proposta desclassificada (Acórdãos TCU
6.405/2017-1C e 2.062/2016-1C).

**No mcp-radardeprecos:**

| Fonte | Tools |
|---|---|
| 1. Preços praticados | `buscar_precos_praticados_compras` (por padrão, só compras concluídas), `buscar_homologados_14133`, `buscar_precos_saude_bps` |
| 2–3. Contratações e atas | `buscar_contratacoes_pncp`, `buscar_pncp_texto`, `buscar_contratos_compras`, `buscar_arp_compras`, `consultar_ata_registro_preco` |
| 4–5. Mídia e cotação | Fora de APIs estruturadas; registre manualmente em `gerar_memoria_pesquisa`. |

`buscar_contratacoes_pncp` devolve `valor_unitario_estimado` e
`valor_unitario_homologado` separados e rotulados, para que nunca se use um
pelo outro sem perceber.

## 2. Planejamento: Curva ABC

Classificar os itens pela Curva ABC (Pareto) dosa o esforço: grupo A pede
pesquisa exaustiva; B, moderada; C, simplificada (Acórdão TCU 2.096/2013-P).

**Tool:** `classificar_curva_abc`. O Plano de Contratação Anual
(`consultar_pca`) indica o que outros órgãos planejam comprar, mas não é
referência de preço.

## 3. Coleta: amplitude e homogeneidade

- **Janela temporal.** A Lei 14.133 limita a seis meses o uso de orçamentos
  coletados; o guia admite até doze meses para itens estáveis. As tools de
  busca aceitam janela em meses e declaram em `avisos` quando ela reduz o
  resultado.
- **Homogeneidade.** Especificação, quantidade (efeito de escala), unidade e
  data precisam ser comparáveis antes da agregação.
  `normalizar_precos_unidade` e `converter_para_unidade_base` levam os preços
  a uma unidade comum; `agrupar_por_comparabilidade` agrupa e gradua cada
  preço de A a D; `detectar_inconsistencias` sinaliza armadilhas como
  unitário que parece global ou homologado acima do estimado.
- **Concentração de fornecedor.** Preços de um único fornecedor, ou de
  empresas vinculadas, enfraquecem a cesta. `mapear_fornecedores_mercado`
  mostra quem venceu as contratações do objeto.
- **Documentos de suporte.** `listar_arquivos_pncp` e
  `consultar_familia_contratacao_pncp` trazem edital, termo de referência,
  ata e contratos com link.

## 4. Tratamento: métodos estatísticos

- **Coeficiente de variação:** CV = (DP / M) × 100. CV ≤ 25%, com pelo menos
  três elementos, indica amostra homogênea.
- **Escore Z iterativo (padrão).** Se o CV inicial passa de 25%, remove-se a
  cada iteração apenas o valor de maior |Z|, com Z = (V − M) / DP, e
  recalcula-se o CV, até atingir 25% ou chegar a três valores — nesse caso,
  fica a amostra de menor CV encontrada. É o método do IPPC-TIC. Em amostras de 20 preços ou mais, excluir mais de 20% gera um aviso
  para revisão: série que só fica homogênea descartando tanto costuma misturar
  objetos ou unidades.
- **Média saneada** (Acórdão TCU 355/2019-P): exclui de uma vez os valores
  fora de M ± DP. Aplicada em passe único — reaplicar o corte não converge e
  consome a amostra.
- **Mediana** (Acórdãos 631/2014-P e 3.033/2013-P), mais robusta a valores
  extremos, e **mínimo** (Acórdão 8.514/2017-2C), só em mercado restrito.

O desvio-padrão é sempre o **amostral** (n − 1): é o que reproduz os CV do
exemplo oficial do IPPC-TIC.

**Tool:** `calcular_preco_referencia`. Com CV inicial até 25%, nada é
removido. Toda execução informa o motivo de parada, o CV antes e depois, cada
exclusão com o CV que a motivou e um `status_resultado` (`apto`,
`requer_revisao`, `nao_apto`). Quando a série parece misturar objetos
diferentes, o preço é mantido para auditoria, mas marcado como inapto: trocar
de método não torna comparáveis preços de coisas diferentes.
`pesquisar_cesta_precos` aplica o cálculo a vários itens de uma vez.

### Exemplo oficial (IPPC-TIC, p. 71)

Amostra `[10,18; 9,92; 12,50; 12,11; 6,24; 14,00; 4,20; 18,14]`, CV inicial
40,12%. O escore Z remove 18,14, depois 4,20, depois 6,24 (CV de 35,65% →
25,06% → 14,48%). Amostra final `[10,18; 9,92; 12,50; 12,11; 14,00]`, média
R$ 11,74. O documento rotula o resultado como "mediana saneada", mas o valor
é a média da amostra final (a mediana seria 12,11). O exemplo é reproduzido
em `tests/test_calcular_preco_referencia.py`.

## 5. Formalização: rastreabilidade

A documentação da pesquisa deve trazer o agente responsável, a
identificação completa de cada fonte (meio, data, URL, CNPJ, quantidade,
valor, especificação), a metodologia, as conclusões e **as buscas
frustradas**, não só as bem-sucedidas.

**Tools:**

- `gerar_memoria_pesquisa` consolida fontes, buscas frustradas, cálculo e
  correção monetária (JSON ou Markdown);
- `gerar_relatorio_excel` e `gerar_relatorio_word` produzem os arquivos
  conforme os elementos I a VIII do Art. 3º da IN 65/2021, com o que falta
  marcado como `[PENDÊNCIA]`;
- `exportar_trilha_auditoria` reúne URL, parâmetros, horário e hash SHA-256
  de cada consulta às fontes.

Toda fonte precisa de um meio de verificação (link para o PNCP ou o
Compras.gov.br, ou evidência equivalente).

## 6. Particularidades de TIC

As [orientações da Secretaria de Governo Digital](https://www.gov.br/governodigital/pt-br/contratacoes-de-tic/legislacao/orientacoes-para-realizacao-de-analise-critica-na-pesquisa-de-precos)
remetem ao IPPC-TIC, à IN SGD/ME nº 94/2022 e à Nota Técnica AudTI/TCU
nº 08/2023.

- **Saneamento:** o escore Z iterativo, padrão deste servidor, é o do
  IPPC-TIC. A Nota Técnica do TCU descreve a remoção em lote (média
  saneada). As duas variantes têm lastro oficial.
- **Estudo de mercado do ETP** (Art. 11, VI, IN SGD/ME 94/2022): comparar
  soluções concorrentes antes de pesquisar o preço da escolhida.
  `gerar_estudo_mercado_tic` monta a matriz de comparabilidade, que
  `gerar_relatorio_word` pode incluir no relatório.
- **Uso de IA:** a orientação pede evitar vieses de ferramentas de
  inteligência artificial e garantir a rastreabilidade de todos os preços.
  Este servidor exige evidência por fonte e trilha de auditoria, mas a
  verificação final cabe a quem conduz a pesquisa.
- **Estrutura de relatório específica de TIC:** os modelos `tic_licitacao` e
  `tic_inexigibilidade` estão reservados e ainda não implementados.
- **Preços internacionais:** sem fonte estruturada; fora do escopo.
