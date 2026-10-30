"""Tool MCP: preços praticados de medicamentos e dispositivos médicos (BPS).

Fonte: **Banco de Preços em Saúde (BPS)** do Ministério da Saúde, via API de
Dados Abertos do DEMAS. Registra compras de estados, municípios e consórcios
intermunicipais — universo que as demais fontes deste servidor cobrem mal, e
que para objetos de saúde é justamente onde está o volume.

**Por que existe, se já há ``buscar_precos_praticados_compras``.** Aquela
consulta o Compras.gov.br, cujo alcance é a Administração federal. Uma
pesquisa de preço de medicamento feita só ali ignora a maior parte das
aquisições do SUS. E a Resolução de Consolidação CIT nº 1/2021 estabelece o
BPS como referência nacional para cotação em saúde: omiti-lo não é uma escolha
de conveniência, é deixar de consultar a fonte setorial devida.

**Catálogo comum.** O BPS usa CATMAT, o mesmo do Compras.gov.br, então
``descobrir_codigo_catalogo`` resolve o código a partir de descrição livre e o
resultado entra direto aqui. Atenção a um detalhe que já custou uma consulta
vazia na verificação: um mesmo nome pode existir em classes diferentes —
"DIPIRONA SÓDICA" aparece na classe 6810 (produtos químicos, padrão analítico
de laboratório), na 6509 (uso veterinário) e na 6505 (drogas e medicamentos).
Para pesquisa de preço em saúde humana, a classe que interessa é a **6505**.

**Cobertura nunca é afirmada.** A origem não devolve total de registros: vem
``{"bps": [...]}`` e nada mais. Não há como saber se a varredura esgotou o
universo, e o resultado declara isso em ``avisos`` — em vez de deixar que uma
lista curta seja lida como "é só isso que existe".
"""
from __future__ import annotations

import time
from typing import Any

from ..clients import bps_client
from ..config import settings
from ..logging_utils import get_logger
from ..utils.documentos import mascarar_documento

logger = get_logger(__name__)

#: Aviso fixo, presente em toda resposta. O BPS é execução de compras já
#: realizadas por entes federativos — é fonte legítima e prevista de pesquisa
#: de preços (diferente da NF-e de execução contratual, ver
#: ``consultar_notas_fiscais``), mas restrita a medicamentos e dispositivos
#: médicos. Usá-la para outros objetos não faz sentido, e o aviso evita que
#: alguém tente.
_AVISO_ESCOPO = (
    "O BPS cobre MEDICAMENTOS e DISPOSITIVOS MÉDICOS adquiridos por estados, "
    "municípios e consórcios. É referência nacional para cotação em saúde "
    "(Resolução de Consolidação CIT nº 1/2021) e complementa — não substitui — "
    "as fontes gerais (buscar_precos_praticados_compras, buscar_contratacoes_pncp), "
    "cujo alcance é a Administração federal."
)


def _iso(data: str | None) -> str | None:
    """Aceita ``AAAAMMDD`` (formato das demais tools) ou ``AAAA-MM-DD``.

    A origem exige ``AAAA-MM-DD``. As outras ferramentas deste servidor usam
    ``AAAAMMDD``. Converter aqui, num lugar só, evita que o usuário precise
    lembrar de qual formato vale para qual fonte.
    """
    if not data:
        return None
    texto = str(data).strip()
    if len(texto) == 8 and texto.isdigit():
        return f"{texto[:4]}-{texto[4:6]}-{texto[6:]}"
    return texto


def _formatar(bruto: dict[str, Any]) -> dict[str, Any]:
    return {
        "data_compra": bruto.get("dataCompra"),
        "ano_compra": bruto.get("anoCompra"),
        "codigo_catmat": bruto.get("codigoCatmat"),
        "descricao_item": bruto.get("descricaoItem"),
        "preco_unitario": bruto.get("precoUnitario"),
        "quantidade": bruto.get("quantidade"),
        "preco_total": bruto.get("precoTotal"),
        # Trio que decide comparabilidade. `unidadeFornecimento` sozinha é
        # ambígua ("AMPOLA" não diz de quantos ml), e é a `capacidade` com a
        # `unidadeMedidaCapacidade` que permite trazer preços de embalagens
        # diferentes a uma base comum — mesmo problema já tratado em
        # converter_para_unidade_base para o Compras.gov.br.
        "unidade_fornecimento": bruto.get("unidadeFornecimento"),
        "capacidade": bruto.get("capacidade"),
        "unidade_medida_capacidade": bruto.get("unidadeMedidaCapacidade"),
        "sigla_unidade_medida": bruto.get("siglaUnidadeMedida"),
        "comprador": {
            "nome": bruto.get("nomeInstituicao"),
            "cnpj": mascarar_documento(bruto.get("cnpjInstituicao")),
            "municipio": bruto.get("municipio"),
            "uf": bruto.get("estado"),
            "esfera": bruto.get("esfera"),
        },
        # Fornecedor e fabricante vêm SEPARADOS, o que o Compras.gov.br não
        # oferece. Quando diferem, há revenda no meio — informação que muda a
        # leitura do preço.
        "fornecedor": {
            "nome": bruto.get("nomeFornecedor"),
            "cnpj": mascarar_documento(bruto.get("cnpjFornecedor")),
        },
        "fabricante": {
            "nome": bruto.get("nomeFabricante"),
            "cnpj": mascarar_documento(bruto.get("cnpjFabricante")),
        },
        "modalidade": bruto.get("modalidade"),
        "tipo_compra": bruto.get("tipoCompra"),
        "generico": bruto.get("generico"),
        # Permite cruzar com o teto de preço da CMED.
        "registro_anvisa": bruto.get("registroAnvisa"),
        "numero_processo_compra": bruto.get("numeroProcessoCompra"),
        "numero_ata": bruto.get("numeroAta"),
        "validade_compra_meses": bruto.get("validadeCompra"),
        "codigo_pdm": bruto.get("codigoPdm"),
        "nome_pdm": bruto.get("nomePdm"),
        "codigo_classe": bruto.get("codigoClasse"),
        "nome_classe": bruto.get("nomeClasse"),
        "data_insercao": bruto.get("dataInsercao"),
        "observacoes": bruto.get("observacoes"),
    }


async def buscar_precos_saude_bps(
    codigo_catmat: str | None = None,
    cnpj_instituicao: str | None = None,
    uf: str | None = None,
    cnpj_fornecedor: str | None = None,
    cnpj_fabricante: str | None = None,
    modalidade: str | None = None,
    generico: bool | None = None,
    registro_anvisa: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    ano_compra: int | None = None,
    valor_unitario_minimo: float | None = None,
    valor_unitario_maximo: float | None = None,
    limite: int = 100,
    incluir_bruto: bool = False,
) -> dict[str, Any]:
    """Preços praticados de medicamentos e dispositivos médicos no BPS.

    Informe ``codigo_catmat`` **ou** ``cnpj_instituicao`` — a origem exige um
    dos dois. Use ``descobrir_codigo_catalogo`` para obter o CATMAT a partir de
    uma descrição livre; para saúde humana, prefira a classe 6505.

    Args:
        codigo_catmat: Código CATMAT do item.
        cnpj_instituicao: CNPJ da instituição compradora (com ou sem máscara).
        uf: Sigla da UF da instituição compradora.
        cnpj_fornecedor: CNPJ do fornecedor.
        cnpj_fabricante: CNPJ do fabricante.
        modalidade: Modalidade da compra (ex.: "Pregão", "Registro de Preços").
        generico: ``True`` para só medicamentos genéricos, ``False`` para só
            não genéricos, ``None`` para ambos.
        registro_anvisa: Código de registro CMED/Anvisa.
        data_inicio: Início do período da compra (``AAAAMMDD`` ou ``AAAA-MM-DD``).
        data_fim: Fim do período da compra.
        ano_compra: Ano da compra, alternativa mais simples ao par de datas.
        valor_unitario_minimo: Piso do preço unitário.
        valor_unitario_maximo: Teto do preço unitário.
        limite: Máximo de registros a devolver (padrão 100, teto 2000).
        incluir_bruto: Se ``True``, cada registro traz ``dados_originais``.

    Returns:
        Dicionário com ``filtros``, ``quantidade_retornada``, ``registros``,
        ``cobertura`` e ``avisos``.

        ``cobertura`` nunca afirma completude: a origem não devolve total, de
        modo que não há como distinguir "acabaram os registros" de "a varredura
        parou antes". O campo declara quantas páginas foram lidas e por que a
        varredura terminou.

    Raises:
        ValueError: nem ``codigo_catmat`` nem ``cnpj_instituicao`` informados.
    """
    if not codigo_catmat and not cnpj_instituicao:
        raise ValueError(
            "Informe codigo_catmat ou cnpj_instituicao — a API do BPS exige um "
            "dos dois. Sem filtro, a consulta abrangeria todas as compras de "
            "saúde do país. Use descobrir_codigo_catalogo(termo, 'material') "
            "para achar o CATMAT a partir de uma descrição."
        )

    limite = max(1, min(limite, 2000))
    tamanho_pagina = min(500, max(limite, 100))

    registros: list[dict[str, Any]] = []
    avisos: list[str] = [_AVISO_ESCOPO]
    inicio = time.monotonic()
    orcamento = settings.tool_budget_seconds
    pagina = 1
    paginas_lidas = 0
    motivo_fim = "página vazia (fim da listagem)"

    while len(registros) < limite:
        pagina_bruta = await bps_client.consultar_bps(
            codigo_catmat=codigo_catmat,
            cnpj_instituicao=cnpj_instituicao,
            estado=uf,
            cnpj_fornecedor=cnpj_fornecedor,
            cnpj_fabricante=cnpj_fabricante,
            modalidade=modalidade,
            generico=generico,
            registro_anvisa=registro_anvisa,
            data_compra_inicio=_iso(data_inicio),
            data_compra_fim=_iso(data_fim),
            ano_compra=ano_compra,
            valor_unitario_minimo=valor_unitario_minimo,
            valor_unitario_maximo=valor_unitario_maximo,
            pagina=pagina,
            tamanho_pagina=tamanho_pagina,
        )
        paginas_lidas += 1

        # Página vazia é o ÚNICO sinal de fim que esta origem oferece. Página
        # menor que a pedida NÃO é fim: tratá-la assim já encerrou varreduras
        # cedo demais duas vezes neste projeto (no PNCP e nas atas do
        # Compras.gov.br), omitindo registros em silêncio.
        if not pagina_bruta:
            break

        for bruto in pagina_bruta:
            if len(registros) >= limite:
                motivo_fim = f"limite de {limite} registros atingido"
                break
            item = _formatar(bruto)
            if incluir_bruto:
                item["dados_originais"] = bruto
            registros.append(item)

        if len(registros) >= limite:
            motivo_fim = f"limite de {limite} registros atingido"
            break

        if orcamento and orcamento > 0 and (time.monotonic() - inicio) >= orcamento:
            motivo_fim = f"orçamento de tempo esgotado ({orcamento:.0f}s)"
            avisos.append(
                f"A varredura parou por tempo após {paginas_lidas} página(s). "
                "O resultado é PARCIAL: pode haver mais registros no período."
            )
            break

        pagina += 1

    avisos.append(
        "A origem não informa o total de registros existentes, apenas a página "
        "solicitada. Portanto NÃO é possível afirmar que esta lista esgota o "
        "universo — ausência de um preço aqui não autoriza concluir que ele não "
        "existe. Amplie o período ou refine os filtros para conferir."
    )
    if not registros:
        avisos.append(
            "Nenhum registro para os filtros informados. Antes de concluir que "
            "não há compras, confira se o CATMAT é o da classe correta: o mesmo "
            "nome existe em classes distintas (ex.: 6505 drogas e medicamentos, "
            "6810 produtos químicos de laboratório, 6509 uso veterinário), e "
            "apenas a de saúde humana tem compras registradas no BPS."
        )

    return {
        "filtros": {
            "codigo_catmat": codigo_catmat,
            "cnpj_instituicao": cnpj_instituicao,
            "uf": uf,
            "data_inicio": _iso(data_inicio),
            "data_fim": _iso(data_fim),
            "ano_compra": ano_compra,
            "generico": generico,
        },
        "quantidade_retornada": len(registros),
        "registros": registros,
        "cobertura": {
            "paginas_lidas": paginas_lidas,
            "motivo_fim": motivo_fim,
            "total_no_universo": None,
            "completude_verificavel": False,
        },
        "avisos": avisos,
    }
