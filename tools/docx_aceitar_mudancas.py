"""Aceita todas as alterações rastreadas (tracked changes) de um .docx, gerando versão limpa."""

REQUIREMENTS = ['defusedxml']
EXTRA = True

import shutil
import zipfile
from pathlib import Path

import defusedxml.minidom

CHANGE_TAGS = ['w:rPrChange', 'w:pPrChange', 'w:tblPrChange', 'w:trPrChange', 'w:tcPrChange', 'w:sectPrChange']


def _tag(no) -> str:
    return (no.localName or no.tagName) if no.nodeType == no.ELEMENT_NODE else ''


def run(caminho: str, saida: str = '') -> str:
    """
    caminho: caminho do arquivo .docx com alterações rastreadas
    saida: caminho do .docx limpo resultante (padrão: sobrescreve o original)
    """
    try:
        destino = Path(saida) if saida else Path(caminho)
        with zipfile.ZipFile(caminho) as zf:
            dados = {n: zf.read(n) for n in zf.namelist()}
        if 'word/document.xml' not in dados:
            return 'Erro: word/document.xml ausente — o arquivo não é um .docx válido.'
        dom = defusedxml.minidom.parseString(dados['word/document.xml'])
        marcacoes = 0

        for el in list(dom.getElementsByTagName('w:del')):
            pai = el.parentNode
            if pai is None:
                continue
            if _tag(pai) == 'rPr':
                continue
            pai.removeChild(el)
            marcacoes += 1

        for el in list(dom.getElementsByTagName('w:ins')):
            pai = el.parentNode
            if pai is None:
                continue
            if _tag(pai) == 'rPr':
                pai.removeChild(el)
                marcacoes += 1
                continue
            while el.firstChild:
                pai.insertBefore(el.firstChild, el)
            pai.removeChild(el)
            marcacoes += 1

        for tag in CHANGE_TAGS:
            for el in list(dom.getElementsByTagName(tag)):
                if el.parentNode is not None:
                    el.parentNode.removeChild(el)

        def marca_del(p) -> bool:
            for filho in p.childNodes:
                if _tag(filho) != 'pPr':
                    continue
                for sub in filho.childNodes:
                    if _tag(sub) != 'rPr':
                        continue
                    for d in sub.childNodes:
                        if _tag(d) == 'del':
                            return True
            return False

        unidos = 0
        while True:
            alvos = [p for p in dom.getElementsByTagName('w:p') if marca_del(p)]
            if not alvos:
                break
            for p in alvos:
                pai = p.parentNode
                if pai is None:
                    continue
                proximo = p.nextSibling
                while proximo is not None and _tag(proximo) != 'p':
                    proximo = proximo.nextSibling
                if proximo is not None:
                    for filho in list(p.childNodes):
                        if _tag(filho) == 'pPr':
                            p.removeChild(filho)
                            continue
                        if proximo.firstChild is not None:
                            proximo.insertBefore(filho, proximo.firstChild)
                        else:
                            proximo.appendChild(filho)
                    pai.removeChild(p)
                else:
                    for filho in p.childNodes:
                        if _tag(filho) != 'pPr':
                            continue
                        for sub in list(filho.childNodes):
                            if _tag(sub) != 'rPr':
                                continue
                            for d in list(sub.childNodes):
                                if _tag(d) == 'del':
                                    sub.removeChild(d)
                unidos += 1

        dados['word/document.xml'] = dom.toxml(encoding='UTF-8')
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(destino.name + '.tmp')
        with zipfile.ZipFile(temporario, 'w', zipfile.ZIP_DEFLATED) as zout:
            if '[Content_Types].xml' in dados:
                zout.writestr('[Content_Types].xml', dados['[Content_Types].xml'])
            for n, conteudo in dados.items():
                if n != '[Content_Types].xml':
                    zout.writestr(n, conteudo)
        shutil.move(str(temporario), str(destino))
        return (f'{marcacoes} marcação(ões) processada(s), {unidos} parágrafo(s) unido(s). '
                f'Arquivo salvo em: {destino}')
    except Exception as e:
        return f'Erro: {e}'
