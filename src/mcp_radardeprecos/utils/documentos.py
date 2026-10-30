"""Normalização e validação de CNPJ e CPF, com suporte a CNPJ alfanumérico.

Centraliza o que estava espalhado por cinco pontos do código, cada um com uma
regra própria e todos assumindo que **CNPJ é numérico**. Deixou de ser: a
Receita Federal passou a emitir CNPJ com letras para inscrições novas, por
esgotamento da faixa numérica, com atribuição iniciada em julho de 2026
(Manual de Integração do PNCP, versão 2.5, de 11/06/2026). Os CNPJ já
existentes permanecem numéricos; os novos, não.

Formato do CNPJ alfanumérico
----------------------------
Quatorze posições, das quais as **doze primeiras** (oito de raiz e quatro de
ordem) admitem dígitos e letras maiúsculas, e as **duas últimas** — os
dígitos verificadores — continuam exclusivamente numéricas.

O que este módulo faz, e o que deliberadamente não faz
------------------------------------------------------
Faz: remove máscara, normaliza caixa e confere o formato acima.

**Não confere dígito verificador.** O cálculo do DV mudou junto com o formato
(cada caractere passa a valer o seu código ASCII menos 48), e nós não o
verificamos hoje nem para o CNPJ numérico. Introduzir a checagem agora, junto
com a ampliação do formato, misturaria duas mudanças de comportamento numa
só: se a implementação do DV tivesse qualquer erro, ele apareceria como
"CNPJ inválido" para dados corretos. Um validador que rejeita dado bom é pior
que validador nenhum — foi exatamente esse o defeito da primeira versão do
leitor de NFS-e, que só aceitava chave de 44 posições e recusava as de 50.

O aviso de comportamento não verificado
---------------------------------------
Aceitar CNPJ alfanumérico na nossa fronteira **não significa** que as fontes
consultadas o aceitem. Isso não foi verificado — o PNCP esteve indisponível
durante a investigação (ver ``docs/ACHADOS_DAS_FONTES.md``, seção 1). Por
isso :func:`aviso_cnpj_alfanumerico` existe: quando a entrada é alfanumérica,
as tools anexam à resposta um aviso dizendo que o comportamento da fonte é
desconhecido. Sem ele, um resultado vazio por rejeição da fonte seria
indistinguível de um resultado vazio por ausência de dados — o falso negativo
que este projeto persegue.
"""
from __future__ import annotations

import re

#: Caracteres mantidos na limpeza. Tudo o mais (``.``, ``/``, ``-``, espaço,
#: e qualquer outro) é máscara e sai. Note que a classe é ASCII estrita, e não
#: ``str.isalnum()``: este último aceita ``ç``, ``á`` e até ``²``, que não são
#: CNPJ e passariam adiante silenciosamente.
_NAO_ALFANUMERICO_ASCII = re.compile(r"[^0-9A-Za-z]+")

#: Doze posições alfanuméricas seguidas de dois dígitos verificadores.
_CNPJ_FORMATO = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")

#: CNPJ inteiramente numérico — o formato clássico, ainda majoritário.
_CNPJ_NUMERICO = re.compile(r"^[0-9]{14}$")

_CPF_FORMATO = re.compile(r"^[0-9]{11}$")

TAMANHO_CNPJ = 14
TAMANHO_CPF = 11

#: Anexado por quem chama quando a entrada é alfanumérica. Ver o cabeçalho.
AVISO_CNPJ_ALFANUMERICO = (
    "CNPJ alfanumérico (formato novo da Receita Federal, vigente para "
    "inscrições a partir de julho/2026). Este servidor aceita e repassa o "
    "identificador como informado, mas o comportamento das fontes externas "
    "com CNPJ alfanumérico AINDA NÃO FOI VERIFICADO. Resultado vazio aqui "
    "não deve ser lido como ausência de contratações: pode ser recusa da "
    "fonte. Confirme no portal oficial antes de concluir."
)


def limpar_cnpj(valor: str) -> str:
    """Remove a máscara de um CNPJ, **preservando letras**, e normaliza a caixa.

    Difere da versão anterior num ponto que era um defeito: aquela mantinha
    apenas dígitos, de modo que ``12ABC4000195`` virava ``1240000195`` e
    seguia para a fonte como um número plausível — porém de outra empresa, ou
    de nenhuma. A consulta respondia normalmente, sem qualquer sinal de que a
    entrada havia sido mutilada.

    Args:
        valor: CNPJ em qualquer formato, com ou sem pontuação.

    Returns:
        Somente os caracteres alfanuméricos ASCII, em maiúsculas. Não valida
        tamanho nem formato — para isso use :func:`validar_cnpj`.
    """
    return _NAO_ALFANUMERICO_ASCII.sub("", str(valor)).upper()


def limpar_cpf(valor: str) -> str:
    """Remove a máscara de um CPF, mantendo só dígitos.

    CPF **não** mudou de formato: continua com onze dígitos numéricos. A
    função existe separada de :func:`limpar_cnpj` justamente para que essa
    diferença fique explícita no código, em vez de as duas compartilharem uma
    limpeza que só serve para uma delas.
    """
    return re.sub(r"\D+", "", str(valor))


def cnpj_alfanumerico(cnpj_limpo: str) -> bool:
    """O CNPJ **já limpo** contém letras?

    Args:
        cnpj_limpo: Saída de :func:`limpar_cnpj`.

    Returns:
        ``True`` se houver ao menos uma letra. Não valida o resto — quem
        chama já validou, ou não se importa.
    """
    return not _CNPJ_NUMERICO.match(cnpj_limpo)


def validar_cnpj(valor: str, *, campo: str = "cnpj") -> str:
    """Limpa e valida o formato de um CNPJ, aceitando numérico e alfanumérico.

    Args:
        valor: CNPJ em qualquer formato.
        campo: Nome do parâmetro, usado só na mensagem de erro, para que ela
            aponte o argumento que o usuário informou (``cnpj_orgao``,
            ``cnpj``…) e não um nome genérico.

    Returns:
        O CNPJ limpo, em maiúsculas, com quatorze posições.

    Raises:
        ValueError: se, após remover a máscara, o resultado não tiver
            quatorze posições, ou tiver caractere fora de ``0-9A-Z`` nas doze
            primeiras, ou letra nas duas últimas.
    """
    limpo = limpar_cnpj(valor)
    if _CNPJ_FORMATO.match(limpo):
        return limpo
    raise ValueError(
        f"{campo} inválido: '{valor}' — esperado CNPJ com 14 posições após "
        "remover a pontuação. Desde julho/2026 as 12 primeiras posições "
        "aceitam letras (CNPJ alfanumérico); os 2 dígitos verificadores "
        f"finais continuam numéricos. Recebido: '{limpo}' "
        f"({len(limpo)} posições)."
    )


def validar_cpf(valor: str, *, campo: str = "cpf") -> str:
    """Limpa e valida o formato de um CPF (onze dígitos numéricos).

    Raises:
        ValueError: se não sobrarem exatamente onze dígitos.
    """
    limpo = limpar_cpf(valor)
    if _CPF_FORMATO.match(limpo):
        return limpo
    raise ValueError(
        f"{campo} inválido: '{valor}' — esperado 11 dígitos numéricos após "
        f"remover a pontuação. Recebido: '{limpo}' ({len(limpo)} dígitos)."
    )


def aviso_cnpj_alfanumerico(cnpj_limpo: str) -> str | None:
    """Devolve o aviso de comportamento não verificado, ou ``None``.

    Pensado para ser combinado com outros avisos da tool::

        aviso = aviso_cnpj_alfanumerico(cnpj_limpo)
        if aviso:
            resultado["avisos"].append(aviso)
    """
    return AVISO_CNPJ_ALFANUMERICO if cnpj_alfanumerico(cnpj_limpo) else None


# ===========================================================================
# Mascaramento na SAÍDA
# ===========================================================================
#
# As funções acima tratam a ENTRADA — limpar e validar o que o usuário pediu.
# Esta trata a saída, e o problema é outro: o campo de documento do fornecedor
# é o mesmo para pessoa jurídica e física em todas as fontes deste servidor
# (``niFornecedor`` no PNCP e no Compras.gov.br, ``ni`` na NF-e). A origem não
# separa; quem separa somos nós, pelo comprimento.
#
# Medido em 09/09/2026 no CATMAT 267203: 1.000 documentos de fornecedor, todos
# de 14 dígitos. CPF de fornecedor é evento raro em material — mais provável em
# serviço, onde há prestador pessoa física. Isto é controle contra evento raro,
# e a razão de existir é que o payload vai para um modelo de linguagem.
#
# CNPJ NÃO é mascarado, e a assimetria é deliberada: identifica pessoa
# jurídica, é público por natureza, e ocultá-lo quebraria o cruzamento com
# sanções, situação cadastral e contratos — que é metade do valor do servidor.


def mascarar_documento(valor: str | None) -> str | None:
    """Mascara CPF, preserva CNPJ, oculta o que não reconhece.

    Args:
        valor: Documento como veio da fonte, com ou sem pontuação.

    Returns:
        - CNPJ (14 numérico ou 12 alfanuméricos + 2 DV): **inalterado**;
        - CPF (11 dígitos): ``123.***.***-01`` — os três primeiros e os dois
          últimos bastam para conferir contra um documento em mãos e não
          bastam para reconstruir;
        - qualquer outro comprimento: ``"***"``. Na dúvida entre expor e
          ocultar, oculta: um identificador que não reconhecemos pode ser dado
          sujo da origem, e pode ser documento de pessoa física em outro
          formato. Expor seria decidir pelo lado que não dá para desfazer;
        - ``None``/vazio: ``None``. Ausência continua ausência.

    Com ``RADARDEPRECOS_INCLUIR_CPF_COMPLETO``, devolve o documento inteiro.
    """
    from ..config import settings

    if valor is None:
        return None
    limpo = _NAO_ALFANUMERICO_ASCII.sub("", str(valor)).upper()
    if not limpo:
        return None
    if _CNPJ_NUMERICO.match(limpo) or _CNPJ_FORMATO.match(limpo):
        return limpo
    if settings.incluir_cpf_completo:
        return limpo
    if _CPF_FORMATO.match(limpo):
        return f"{limpo[:3]}.***.***-{limpo[-2:]}"
    return "***"


#: Anexado por quem chama quando algum documento saiu mascarado, para que a
#: ausência do número não seja lida como ausência do fornecedor.
AVISO_CPF_MASCARADO = (
    "Documento(s) de fornecedor pessoa física saíram MASCARADOS "
    "(formato 123.***.***-01). O identificador existe na fonte; foi ocultado "
    "aqui por minimização de dado pessoal. Para conferir um fornecedor PF "
    "específico, consulte o portal oficial ou defina "
    "RADARDEPRECOS_INCLUIR_CPF_COMPLETO=true no servidor."
)
