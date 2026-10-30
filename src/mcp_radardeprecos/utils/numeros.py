"""Identificador grande como número vira ``double`` inexato no cliente.

O defeito, relatado em 02/10/2026 e **medido em 02/10/2026**
------------------------------------------------------------
``id_compra`` tem 17 dígitos: ``15502005000242026``. O maior inteiro
exatamente representável num ``double`` IEEE-754 é ``2^53 - 1`` =
``9.007.199.254.740.991``, com dezesseis dígitos. Acima disso o valor passa a
ser aproximado.

Python não aproxima, porque ``int`` tem precisão arbitrária. A camada de
transporte do MCP é TypeScript, onde **todo número é double** — e que o
round-trip acontece de fato está provado por outro campo: ``capacidade`` sai
daqui como ``0.0`` e chega gravado como ``0`` nas respostas salvas. Só
``JSON.parse``/``JSON.stringify`` faz isso.

**O que a medição desmentiu.** A versão 0.6.3 afirmou que o identificador
"chega ao cliente arredondado", com ``98367705000032030`` virando
``98367705000032032``. **Isso é falso**, e dizia mais do que havia sido
medido. ``JSON.stringify`` imprime a menor representação decimal que volta ao
mesmo ``double``, e essa representação recupera os dígitos originais: dos
**1.349 valores reais de id_compra** nas respostas salvas (637 deles acima de
``2^53-1``), **todos** atravessam ``JSON.parse`` → ``JSON.stringify`` com o
texto idêntico, e **nenhum par distinto colide** no mesmo ``double``. O que a
medição original mostrou foi que 43% dos valores não são representáveis em
``double`` — propriedade dos números, não corrupção do transporte. Apresentei
a primeira como evidência da segunda.

**Onde o dano é real, então.** O valor em memória *é* um ``double`` inexato, e
isso aparece em tudo que não seja imprimir::

    const n = 98367705000032030;
    Number.isSafeInteger(n)        // false
    n === 98367705000032031        // true   <- duas compras distintas iguais
    n % 10                         // 2      <- o último dígito real é 0

Ou seja: quem **compara** dois ``id_compra``, **deduplica** uma lista deles,
usa um como chave, ou extrai dígitos por aritmética, obtém a resposta errada —
sem erro, sem aviso, e com o número aparentando estar certo na tela. É um modo
de falha pior que o arredondamento que eu havia descrito, porque sobrevive à
conferência visual.

Terceira vez que esta camada engana, e as três do mesmo jeito: li um artefato
do transporte como propriedade da origem (capacidade ``int``/``float``), depois
uma propriedade dos números como artefato do transporte (este caso). A
conclusão que se repete é **em que camada se mede** — e que uma inferência
plausível não passa a ser medição por ser plausível.

A correção continua certa — pelo motivo corrigido
--------------------------------------------------
Texto nunca se torna ``double``: comparação e deduplicação voltam a ser
exatas, e o tipo deixa de depender da magnitude do valor. O que muda com a
medição é a **justificativa**, não a conduta: não se converte para impedir que
os dígitos cheguem errados (eles chegavam certos), mas para impedir que dois
identificadores distintos possam ser tratados como o mesmo.

Por que são dois mecanismos, e não um
--------------------------------------
:func:`identificador` converte nos campos conhecidos, dando **contrato
estável**: o campo é texto sempre, não "texto quando grande".

:func:`proteger_inteiros_grandes` é a rede de segurança, aplicada num ponto
único no ``server.py``, para os campos que ninguém enumerou.

A rede sozinha não bastaria, e esta é a parte não óbvia: ela agiria apenas
sobre os valores grandes, então o MESMO campo sairia ``int`` quando o valor
fosse pequeno e ``str`` quando fosse grande. **Tipo que depende da magnitude
do valor é pior que qualquer um dos dois fixos** — quem consome não tem como
escrever código correto, e o defeito só aparece em produção, com o registro
que por acaso tem um dígito a mais.

A conversão explícita sozinha também não bastaria: cobre o que alguém lembrou
de enumerar. A rede pega o próximo campo que ninguém viu, e **avisa com o
caminho**, que é como a gente descobre que ele existe e o promove a conversão
explícita.
"""
from __future__ import annotations

from typing import Any

#: Maior inteiro que um ``double`` IEEE-754 representa sem arredondar.
#: É ``Number.MAX_SAFE_INTEGER`` do JavaScript, e o limite é da aritmética de
#: ponto flutuante, não uma escolha nossa.
MAX_INTEIRO_SEGURO = 2**53 - 1


def identificador(valor: Any) -> str | None:
    """Identificador como texto, qualquer que seja a magnitude.

    Um identificador não é uma quantidade: não se soma, não se compara por
    ordem, não se interpola. O único uso é casar com outro identificador —
    e para isso texto serve, com a vantagem de atravessar qualquer camada de
    transporte sem perder dígito.

    Args:
        valor: O identificador como veio da fonte.

    Returns:
        O valor como ``str``, ou ``None`` se ausente. **``0`` devolve
        ``"0"``**, não ``None``: zero é um identificador possível, e tratá-lo
        como ausência é o defeito que a capacidade de unidade já produziu
        neste projeto.
    """
    if valor is None:
        return None
    return str(valor)


def proteger_inteiros_grandes(
    valor: Any, _caminho: str = ""
) -> tuple[Any, list[str]]:
    """Converte para texto todo inteiro que um ``double`` arredondaria.

    Percorre dicionários e listas em profundidade. Devolve uma estrutura nova
    — não altera a recebida — e a lista dos **caminhos** convertidos.

    O caminho é o conteúdo acionável: ele diz qual campo precisa de
    :func:`identificador` explícito na tool, para que o tipo pare de depender
    da magnitude do valor.

    ``float`` não é tocado: já é ``double`` na origem, e convertê-lo mentiria
    sobre o tipo do dado. ``bool`` também não, embora seja subclasse de ``int``
    em Python — confundir os dois já causou defeito aqui antes.
    """
    convertidos: list[str] = []

    if isinstance(valor, bool):
        return valor, convertidos
    if isinstance(valor, int):
        if abs(valor) > MAX_INTEIRO_SEGURO:
            return str(valor), [_caminho] if _caminho else [""]
        return valor, convertidos
    if isinstance(valor, dict):
        saida: dict[Any, Any] = {}
        for chave, item in valor.items():
            filho = f"{_caminho}.{chave}" if _caminho else str(chave)
            saida[chave], achados = proteger_inteiros_grandes(item, filho)
            convertidos.extend(achados)
        return saida, convertidos
    if isinstance(valor, list):
        # O caminho usa `[]` em vez do índice de propósito: o que interessa é
        # QUAL CAMPO precisa de conversão explícita, não em que posição da
        # lista ele apareceu desta vez. Mil preços produziriam mil caminhos
        # distintos para o mesmo defeito, e o aviso viraria ruído.
        lista = []
        vistos = set()
        for item in valor:
            protegido, achados = proteger_inteiros_grandes(item, f"{_caminho}[]")
            lista.append(protegido)
            for a in achados:
                if a not in vistos:
                    vistos.add(a)
                    convertidos.append(a)
        return lista, convertidos
    return valor, convertidos


#: Anexado aos avisos quando a rede de segurança age. Nomeia os campos, porque
#: cada um deles é uma conversão explícita que falta fazer na tool.
def aviso_rede_de_seguranca(campos: list[str]) -> str:
    return (
        f"Inteiro(s) acima do limite seguro de precisão convertido(s) para "
        f"texto em: {', '.join(campos)}. Acima de {MAX_INTEIRO_SEGURO} um "
        "inteiro não sobrevive à camada de transporte sem arredondar, e um "
        "identificador arredondado continua parecendo válido. Estes campos "
        "deveriam sair como texto já na tool — o tipo não pode depender da "
        "magnitude do valor."
    )
