"""Tool ``gerar_pdf_avaliacao_pesquisa_mercado``: o estudo de avaliação em PDF.

Recebe o mesmo estudo de :func:`avaliar_pesquisa_mercado`, refaz a avaliação
no servidor (o PDF nunca mostra números que a tool não calculou) e monta um
relatório A4: dados do estudo, indicadores, resumo dos itens, a avaliação de
cada preço, parâmetros, método e campo de assinatura. Sem logotipo.

Não guarda nada: o PDF volta em base64, como os relatórios em Word e Excel.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..utils.arquivo_saida import gravar_documento
from .avaliar_pesquisa_mercado import (
    CREDITO,
    EXCESSIVO,
    INEXEQUIVEL,
    PADRAO_CV_MAXIMO,
    PADRAO_EXCESSIVO,
    PADRAO_INEXEQUIVEL,
    VALIDO,
    avaliar_pesquisa_mercado,
)

logger = logging.getLogger(__name__)

TITULO = "Avaliação de pesquisa de mercado"
SUBTITULO = "Método do Manual de Pesquisa de Preços"
_BRASILIA = timezone(timedelta(hours=-3))

# --- Paleta (a mesma da tela) ----------------------------------------------------
TINTA = colors.HexColor("#1b1f24")
SUAVE = colors.HexColor("#5b6470")
BORDA = colors.HexColor("#d9dde3")
FUNDO = colors.HexColor("#f3f5f8")
DESTAQUE = colors.HexColor("#1f5fbf")
DESTAQUE_CLARO = colors.HexColor("#e8f0fc")
OK, OK_FUNDO = colors.HexColor("#1d7a3e"), colors.HexColor("#e3f4e8")
ALERTA, ALERTA_FUNDO = colors.HexColor("#9a5b00"), colors.HexColor("#fdf0d8")
ERRO, ERRO_FUNDO = colors.HexColor("#b42318"), colors.HexColor("#fde7e5")
NEUTRO_FUNDO = colors.HexColor("#eceff3")

LARGURA_UTIL = A4[0] - 36 * mm


def _estilo(nome: str, **kw: Any) -> ParagraphStyle:
    base = {"fontName": "Helvetica", "fontSize": 9, "leading": 12, "textColor": TINTA}
    base.update(kw)
    return ParagraphStyle(nome, **base)


E_TITULO = _estilo("titulo", fontName="Helvetica-Bold", fontSize=20, leading=24)
E_SUBTITULO = _estilo("subtitulo", fontSize=10.5, leading=14, textColor=SUAVE)
E_META = _estilo("meta", fontSize=8, leading=11, textColor=SUAVE, alignment=TA_RIGHT)
E_SECAO = _estilo("secao", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=SUAVE,
                  spaceBefore=14, spaceAfter=6)
E_ITEM = _estilo("item", fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=4)
E_ITEM_SUB = _estilo("item_sub", fontSize=9, leading=12, textColor=SUAVE, spaceAfter=6)
E_TEXTO = _estilo("texto")
E_PEQUENO = _estilo("pequeno", fontSize=8, leading=10.5)
E_PEQUENO_SUAVE = _estilo("pequeno_suave", fontSize=8, leading=10.5, textColor=SUAVE)
E_CELULA = _estilo("celula", fontSize=8, leading=10)
E_CELULA_DIR = _estilo("celula_dir", fontSize=8, leading=10, alignment=TA_RIGHT)
E_CABECALHO = _estilo("cabecalho", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=SUAVE)
E_CABECALHO_DIR = _estilo("cabecalho_dir", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5,
                          textColor=SUAVE, alignment=TA_RIGHT)
E_ROTULO_CARTAO = _estilo("rotulo_cartao", fontName="Helvetica-Bold", fontSize=6.8, leading=9, textColor=SUAVE)
E_VALOR_CARTAO = _estilo("valor_cartao", fontName="Helvetica-Bold", fontSize=11.5, leading=14)
E_CREDITO = _estilo("credito", fontSize=8, leading=11, textColor=SUAVE, alignment=1, spaceBefore=18)


# --- Formatação --------------------------------------------------------------------
def _moeda(v: float | None) -> str:
    if v is None:
        return "—"
    inteiro, _, dec = f"{v:,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{dec}"


def _numero(v: float | None, casas: int = 2) -> str:
    if v is None:
        return "—"
    inteiro, _, dec = f"{v:,.{casas}f}".partition(".")
    inteiro = inteiro.replace(",", ".")
    return f"{inteiro},{dec}" if casas else inteiro


def _qtd(v: float | None) -> str:
    if v is None:
        return "—"
    return _numero(v, 0) if float(v).is_integer() else _numero(v, 2)


def _pct(f: float) -> str:
    return f"{_numero(f * 100, 2)}%"


def _t(texto: Any) -> str:
    """Texto do usuário para dentro de um Paragraph: sem marcação."""
    return escape("" if texto is None else str(texto))


def _p(texto: Any, estilo: ParagraphStyle = E_CELULA) -> Paragraph:
    return Paragraph(_t(texto), estilo)


_SITUACAO = {
    "pronto": ("Pronto", OK, OK_FUNDO),
    "poucos_precos": ("Poucos preços", ALERTA, ALERTA_FUNDO),
    "sem_precos": ("Sem preços", ERRO, ERRO_FUNDO),
}


def _cores_avaliacao(avaliacao: str) -> tuple[colors.Color, colors.Color]:
    if avaliacao == VALIDO:
        return OK, OK_FUNDO
    if avaliacao.startswith(VALIDO):
        return ALERTA, ALERTA_FUNDO
    if avaliacao in (EXCESSIVO, INEXEQUIVEL):
        return ERRO, ERRO_FUNDO
    return SUAVE, NEUTRO_FUNDO


def _selo(texto: str, cor: colors.Color, fundo: colors.Color, largura: float) -> Table:
    """Um rótulo colorido, como as pílulas da tela."""
    t = Table([[Paragraph(_t(texto), _estilo("selo", fontName="Helvetica-Bold", fontSize=6.8,
                                             leading=8.5, textColor=cor))]],
              colWidths=[largura])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fundo),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


# --- Blocos ------------------------------------------------------------------------
def _derivado(nome: str, pai: ParagraphStyle, **kw: Any) -> ParagraphStyle:
    return ParagraphStyle(nome, parent=pai, **kw)


def _cartoes(cartoes: list[tuple[str, str] | tuple[str, str, str]], principal: int | None = 0,
             tamanho_valor: float = 11.5) -> Table:
    """Linha de indicadores. O cartão ``principal`` fica em destaque; um 3º texto vira legenda."""
    n = len(cartoes)
    espaco = 2.5 * mm
    largura = (LARGURA_UTIL - espaco * (n - 1)) / n
    e_valor = _derivado("valor", E_VALOR_CARTAO, fontSize=tamanho_valor, leading=tamanho_valor + 3)
    linha: list[Any] = []
    larguras: list[float] = []
    for i, (rotulo, valor, *legenda) in enumerate(cartoes):
        destaque = i == principal
        conteudo = [
            Paragraph(_t(rotulo).upper(), _derivado("r", E_ROTULO_CARTAO,
                                                     textColor=colors.HexColor("#dce7fb") if destaque else SUAVE)),
            Paragraph(_t(valor), _derivado("v", e_valor, textColor=colors.white if destaque else TINTA)),
        ]
        if legenda:
            conteudo.append(Paragraph(_t(legenda[0]), _derivado(
                "l", E_ROTULO_CARTAO, fontName="Helvetica", textColor=colors.HexColor("#dce7fb") if destaque else SUAVE)))
        cartao = Table([[c] for c in conteudo], colWidths=[largura])
        cartao.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), DESTAQUE if destaque else FUNDO),
            ("ROUNDEDCORNERS", [5, 5, 5, 5]),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ]))
        linha.append(cartao)
        larguras.append(largura)
        if i < n - 1:
            linha.append("")
            larguras.append(espaco)
    t = Table([linha], colWidths=larguras)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _tabela(cabecalho: list[Paragraph], linhas: list[list[Any]], larguras: list[float],
            extras: list[tuple] | None = None) -> Table:
    t = Table([cabecalho, *linhas], colWidths=larguras, repeatRows=1)
    estilo = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, TINTA),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, BORDA),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    t.setStyle(TableStyle(estilo + (extras or [])))
    return t


def _caixa(conteudo: list[Any], cor: colors.Color, fundo: colors.Color) -> Table:
    t = Table([[conteudo]], colWidths=[LARGURA_UTIL])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fundo),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, cor),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _cabecalho_documento(r: dict, gerado_em: datetime) -> list[Any]:
    meta = Paragraph(
        f"Versão {r['versao']}<br/>Gerado em {gerado_em:%d/%m/%Y às %H:%M}", E_META)
    topo = Table([[[Paragraph(TITULO, E_TITULO), Paragraph(SUBTITULO, E_SUBTITULO)], meta]],
                 colWidths=[LARGURA_UTIL - 45 * mm, 45 * mm])
    topo.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, 0), 2, DESTAQUE),
    ]))
    return [topo, Spacer(1, 10)]


def _dados_do_estudo(r: dict) -> Table:
    pares = [
        ("Processo nº", r.get("processo") or "—"),
        ("Responsável", r.get("responsavel") or "—"),
        ("Objeto", r.get("objeto") or "—"),
        ("Prorrogação contratual", "Sim" if r.get("prorrogacao") else "Não"),
    ]
    celulas = [[Paragraph(_t(rot).upper(), E_ROTULO_CARTAO), Paragraph(_t(val), E_TEXTO)] for rot, val in pares]
    meia = LARGURA_UTIL / 2
    linhas = [[celulas[0], celulas[1]], [celulas[2], celulas[3]]]
    t = Table(linhas, colWidths=[meia, meia])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDA),
        ("ROUNDEDCORNERS", [5, 5, 5, 5]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, BORDA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _resumo_dos_itens(r: dict) -> Table:
    cab = [Paragraph(x, E_CABECALHO) for x in ("#", "DESCRIÇÃO", "MÉTRICA")] + [
        Paragraph(x, E_CABECALHO_DIR) for x in ("QTD.", "PREÇO DE MERCADO", "VALOR TOTAL")] + [
        Paragraph("SITUAÇÃO", E_CABECALHO)]
    larguras = [8 * mm, 52 * mm, 24 * mm, 14 * mm, 27 * mm, 27 * mm, 22 * mm]
    linhas = []
    for n, item in enumerate(r["itens"], start=1):
        res = item["resultado"]
        rotulo, cor, fundo = _SITUACAO.get(item["status"], (item["status"], SUAVE, NEUTRO_FUNDO))
        linhas.append([
            _p(n), _p(item["descricao"] or "Item sem descrição"), _p(item["metrica"]),
            _p(_qtd(item["quantidade"]), E_CELULA_DIR), _p(_moeda(res["preco_mercado"]), E_CELULA_DIR),
            _p(_moeda(res["valor_total"]), E_CELULA_DIR), _selo(rotulo, cor, fundo, 20 * mm),
        ])
    total = r["resumo"]["valor_total_estimado"]
    linhas.append(["", Paragraph("<b>Total estimado</b>", E_CELULA), "", "", "",
                   Paragraph(f"<b>{_t(_moeda(total))}</b>", E_CELULA_DIR), ""])
    return _tabela(cab, linhas, larguras, [
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, TINTA),
        ("LINEBELOW", (0, -1), (-1, -1), 0, colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), FUNDO),
    ])


def _bloco_item(n: int, item: dict) -> list[Any]:
    res = item["resultado"]
    sub = f"{item['metrica'] or 'sem métrica'}  ·  quantidade {_qtd(item['quantidade'])}"
    blocos: list[Any] = [
        Paragraph(f"{n}. {_t(item['descricao'] or 'Item sem descrição')}", E_ITEM),
        Paragraph(_t(sub), E_ITEM_SUB),
    ]
    resultado: list[Any] = []

    precos = item["precos"]
    if precos:
        cab = [Paragraph(x, E_CABECALHO) for x in ("#", "FONTE", "TIPO", "LOCALIZADOR")] + [
            Paragraph(x, E_CABECALHO_DIR) for x in ("VALOR", "% DOS DEMAIS")] + [
            Paragraph("AVALIAÇÃO", E_CABECALHO), Paragraph("CÁLCULO", E_CABECALHO)]
        larguras = [7 * mm, 33 * mm, 25 * mm, 24 * mm, 23 * mm, 16 * mm, 30 * mm, 16 * mm]
        linhas, notas = [], []
        for k, p in enumerate(precos, start=1):
            cor, fundo = _cores_avaliacao(p["avaliacao"])
            pct = p.get("percentual_em_relacao_aos_demais")
            linhas.append([
                _p(k), _p(p.get("fonte") or "—"), _p(p.get("tipo") or "—"), _p(p.get("localizador") or "—"),
                _p(_moeda(p.get("valor")), E_CELULA_DIR),
                _p("—" if pct is None else f"{_numero(pct)}%", E_CELULA_DIR),
                _selo(p["avaliacao"], cor, fundo, 28 * mm),
                _p("Sim" if p.get("usado_no_calculo") else "Não"),
            ])
            obs = p.get("observacao") or ""
            if not p.get("usado_no_calculo") and p["avaliacao"].startswith(VALIDO):
                obs = (obs + " " if obs else "") + "Fica fora do cálculo, como na planilha de referência."
            if obs:
                notas.append(f"<b>{k}.</b> {_t(obs)}")
        blocos.append(_tabela(cab, linhas, larguras))
        if notas:
            blocos.append(Spacer(1, 4))
            blocos.extend(Paragraph(x, E_PEQUENO_SUAVE) for x in notas)
    else:
        blocos.append(Paragraph("Nenhum preço informado para este item.", E_PEQUENO_SUAVE))

    cv = res.get("coeficiente_variacao_percentual")
    resultado.append(Spacer(1, 8))
    resultado.append(_cartoes([
        ("Preço de mercado", _moeda(res["preco_mercado"]),
         f"por {res['metodo_aplicado'].lower()}" if res["preco_mercado"] is not None else "não calculado"),
        ("Média", _moeda(res.get("media"))),
        ("Mediana", _moeda(res.get("mediana"))),
        ("Mínimo", _moeda(res.get("preco_minimo"))),
        ("Coef. variação", "—" if cv is None else f"{_numero(cv)}%"),
        ("Preços válidos", str(res.get("precos_validos", 0))),
    ], tamanho_valor=10.5))

    pror = item.get("prorrogacao")
    if pror and pror.get("mensagem"):
        cor, fundo = (ERRO, ERRO_FUNDO) if pror.get("desvantajoso") else (OK, OK_FUNDO)
        resultado += [Spacer(1, 6), _caixa([Paragraph(
            f"<b>Prorrogação.</b> Preço contratado {_t(_moeda(pror.get('preco_contratado')))}: "
            f"{_t(pror['mensagem'])}", E_PEQUENO)], cor, fundo)]
    if item.get("problemas"):
        resultado += [Spacer(1, 6), _caixa(
            [Paragraph("<b>Pendências do item</b>", E_PEQUENO)]
            + [Paragraph(f"• {_t(x)}", E_PEQUENO) for x in item["problemas"]], ALERTA, ALERTA_FUNDO)]
    # Item curto fica inteiro numa página; um longo mantém juntos o título com
    # a tabela e o resultado com as pendências.
    if len(precos) <= 8:
        return [KeepTogether(blocos + resultado), Spacer(1, 12)]
    return [KeepTogether(blocos), KeepTogether(resultado), Spacer(1, 12)]


def _parametros(r: dict) -> list[Any]:
    o = r["opcoes"]

    def linha(rotulo: str, valor: str, padrao: str | None = None) -> list[Paragraph]:
        alterado = padrao is not None and valor != padrao
        nota = f"  <font color='#9a5b00'>(padrão {padrao}; justificar)</font>" if alterado else ""
        return [_p(rotulo), Paragraph(_t(valor) + nota, E_CELULA)]

    linhas = [
        linha("Método", "Média dos demais preços"),
        linha("Excessivamente elevado acima de", _pct(1 + o["percentual_excessivo"]) + " da média dos demais",
              _pct(1 + PADRAO_EXCESSIVO) + " da média dos demais"),
        linha("Inexequível abaixo de", _pct(o["percentual_inexequivel"]) + " da média dos demais",
              _pct(PADRAO_INEXEQUIVEL) + " da média dos demais"),
        linha("Coeficiente de variação máximo para usar a média", _pct(o["cv_maximo"]), _pct(PADRAO_CV_MAXIMO)),
        linha("Preço de mercado pelo preço mínimo", "Sim" if o["usar_preco_minimo"] else "Não"),
        linha("Preços públicos inexequíveis preservados", "Sim" if o["preservar_publicos_inexequiveis"] else "Não"),
        linha("Mínimo de preços válidos por item", str(o["minimo_precos_validos"])),
    ]
    t = Table(linhas, colWidths=[78 * mm, LARGURA_UTIL - 78 * mm])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (0, 0), (0, -1), SUAVE),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    metodo = [
        "<b>1. Excessivamente elevado.</b> Cada preço é comparado à média dos demais preços do item; "
        "acima do limite, sai do cálculo.",
        "<b>2. Inexequível.</b> Entre os preços restantes, abaixo do limite em relação à média dos demais, "
        "o preço sai do cálculo.",
        "<b>3. Preços públicos.</b> PNCP, Painel de Preços, ata e contrato inexequíveis são preservados, "
        "assim como preços iguais a eles. Preço de outra fonte maior que um preço público preservado "
        "aparece como válido, mas fica fora do cálculo.",
        "<b>4. Preço de mercado.</b> Com coeficiente de variação até o limite, usa-se a média; acima dele, "
        "a mediana; por opção, o preço mínimo. Com menos de 2 preços válidos, não há preço de mercado.",
        "<b>5. Conferências.</b> As fontes públicas devem ser a maioria, e cada item deve ter o mínimo de "
        "preços válidos. Na prorrogação, o preço contratado é comparado ao preço de mercado.",
    ]
    return [t, Spacer(1, 8)] + [Paragraph(x, _derivado("m", E_PEQUENO, spaceAfter=3)) for x in metodo]


def _assinatura(r: dict) -> Table:
    linha = [Paragraph("Local e data", E_PEQUENO_SUAVE),
             "", Paragraph(_t(r.get("responsavel") or "Responsável pela pesquisa"), E_PEQUENO_SUAVE)]
    t = Table([["", "", ""], linha], colWidths=[70 * mm, LARGURA_UTIL - 140 * mm, 70 * mm],
              rowHeights=[16 * mm, None])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (0, 0), 0.6, TINTA), ("LINEBELOW", (2, 0), (2, 0), 0.6, TINTA),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return KeepTogether([Spacer(1, 6), t])


# --- Página -------------------------------------------------------------------------
class _CanvasNumerado(rl_canvas.Canvas):
    """Rodapé com "Página x de y": guarda as páginas e desenha no fim."""

    rodape_esquerda = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._paginas: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 (API do ReportLab)
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self._rodape(total)
            super().showPage()
        super().save()

    def _rodape(self, total: int) -> None:
        largura, _ = A4
        self.setStrokeColor(BORDA)
        self.setLineWidth(0.5)
        self.line(18 * mm, 13 * mm, largura - 18 * mm, 13 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(SUAVE)
        self.drawString(18 * mm, 9 * mm, self.rodape_esquerda)
        self.drawRightString(largura - 18 * mm, 9 * mm, f"Página {self._pageNumber} de {total}")


class _DocumentoPdf:
    """Interface ``save(destino)`` esperada por :func:`gravar_documento`."""

    def __init__(self, historia: list[Any], rodape: str, titulo: str) -> None:
        self.historia, self.rodape, self.titulo = historia, rodape, titulo

    def save(self, destino: Any) -> None:
        doc = SimpleDocTemplate(
            destino, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=16 * mm, bottomMargin=20 * mm, title=self.titulo, author="",
            subject=SUBTITULO, creator="mcp-radardeprecos",
        )
        rodape = self.rodape

        class _Canvas(_CanvasNumerado):
            rodape_esquerda = rodape

        doc.build(list(self.historia), canvasmaker=_Canvas)


def _montar(r: dict, gerado_em: datetime) -> _DocumentoPdf:
    resumo = r["resumo"]
    h: list[Any] = _cabecalho_documento(r, gerado_em)
    h.append(_dados_do_estudo(r))
    h.append(Spacer(1, 10))
    h.append(_cartoes([
        ("Valor total estimado", _moeda(resumo["valor_total_estimado"])),
        ("Itens", str(resumo["total_itens"])),
        ("Itens prontos", f"{resumo['itens_prontos']} de {resumo['total_itens']}"),
        ("Preços avaliados", str(sum(len(i["precos"]) for i in r["itens"]))),
    ]))
    h += [Paragraph("RESUMO DOS ITENS", E_SECAO), _resumo_dos_itens(r)]
    if r["avisos"]:
        h += [Spacer(1, 10), _caixa([Paragraph("<b>Avisos</b>", E_PEQUENO)]
                                     + [Paragraph(f"• {_t(a)}", E_PEQUENO) for a in r["avisos"]],
                                     ALERTA, ALERTA_FUNDO)]
    h.append(Paragraph("AVALIAÇÃO DOS PREÇOS POR ITEM", E_SECAO))
    for n, item in enumerate(r["itens"], start=1):
        h += _bloco_item(n, item)
    h += [KeepTogether([Paragraph("PARÂMETROS E MÉTODO", E_SECAO), *_parametros(r)])]
    h += [Paragraph("ASSINATURA", E_SECAO), _assinatura(r)]
    h.append(Paragraph(_t(CREDITO), E_CREDITO))

    processo = r.get("processo")
    rodape = f"{TITULO}{' · Processo nº ' + processo if processo else ''} · versão {r['versao']}"
    return _DocumentoPdf(h, rodape, TITULO + (f" — Processo nº {processo}" if processo else ""))


async def gerar_pdf_avaliacao_pesquisa_mercado(
    itens: list[dict[str, Any]],
    processo: str | None = None,
    objeto: str | None = None,
    responsavel: str | None = None,
    prorrogacao: bool = False,
    percentual_excessivo: float = PADRAO_EXCESSIVO,
    percentual_inexequivel: float = PADRAO_INEXEQUIVEL,
    cv_maximo: float = PADRAO_CV_MAXIMO,
    usar_preco_minimo: bool = False,
    preservar_publicos_inexequiveis: bool = True,
    minimo_precos_validos: int = 3,
    versao: int = 1,
    caminho_saida: str | None = None,
) -> dict[str, Any]:
    """Gera o PDF do estudo de avaliação de pesquisa de mercado.

    Recebe o MESMO estudo de ``avaliar_pesquisa_mercado`` (itens, dados e
    opções) e refaz a avaliação antes de montar o documento, para o PDF trazer
    exatamente os números da tool. O relatório A4 traz: dados do estudo,
    indicadores, resumo dos itens com o total estimado, a avaliação de cada
    preço com observações, resultado de cada item, pendências, parâmetros
    adotados, o método e campo de assinatura. Sem logotipo.

    Args:
        itens, processo, objeto, responsavel, prorrogacao, percentual_excessivo,
        percentual_inexequivel, cv_maximo, usar_preco_minimo,
        preservar_publicos_inexequiveis, minimo_precos_validos: os mesmos de
            ``avaliar_pesquisa_mercado``.
        versao: número da versão do estudo a imprimir (o ``versao`` devolvido
            pela última chamada de ``avaliar_pesquisa_mercado``).
        caminho_saida: caminho do .pdf no disco (só no modo stdio). Se omitido,
            o PDF volta em ``conteudo_base64``.

    Returns:
        ``{"nome_arquivo", "conteudo_base64", "tamanho_bytes"}`` (ou
        ``caminho_saida``), mais ``formato: "pdf"``, ``versao``, ``resumo`` e
        ``avisos`` da avaliação.
    """
    versao = max(int(versao or 1), 1)
    r = await avaliar_pesquisa_mercado(
        itens=itens, processo=processo, objeto=objeto, responsavel=responsavel,
        prorrogacao=prorrogacao, percentual_excessivo=percentual_excessivo,
        percentual_inexequivel=percentual_inexequivel, cv_maximo=cv_maximo,
        usar_preco_minimo=usar_preco_minimo,
        preservar_publicos_inexequiveis=preservar_publicos_inexequiveis,
        minimo_precos_validos=minimo_precos_validos, versao=versao - 1,
    )
    documento = _montar(r, datetime.now(_BRASILIA))
    resultado = gravar_documento(documento, caminho_saida=caminho_saida, extensao="pdf",
                                 prefixo_nome="avaliacao_pesquisa_mercado")
    logger.info("gerar_pdf_avaliacao_pesquisa_mercado: %d item(ns), versão %d, %d bytes",
                len(r["itens"]), r["versao"], resultado["tamanho_bytes"])
    resultado.update({"formato": "pdf", "versao": r["versao"], "resumo": r["resumo"], "avisos": r["avisos"]})
    return resultado
