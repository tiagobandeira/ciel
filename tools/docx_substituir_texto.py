"""Substitui texto dentro de um .docx existente, mesmo com trecho fragmentado entre runs."""

REQUIREMENTS = ['defusedxml']
EXTRA = True
PERMISSIONS = {"caminho": "write", "saida": "write"}

import shutil
import zipfile
from pathlib import Path

import defusedxml.minidom

WS = ' \t\r\n'


def _texto_do(t) -> str:
    return ''.join(c.data for c in t.childNodes if c.nodeType in (c.TEXT_NODE, c.CDATA_SECTION_NODE))


def _definir_texto(t, novo: str) -> None:
    for c in list(t.childNodes):
        t.removeChild(c)
    if novo:
        t.appendChild(t.ownerDocument.createTextNode(novo))
    if novo != novo.strip(WS):
        t.setAttribute('xml:space', 'preserve')


def _aplicar(paragrafo, busca: str, substituicao: str) -> int:
    count = 0
    min_offset = 0
    while True:
        ts = paragrafo.getElementsByTagName('w:t')
        textos = [_texto_do(t) for t in ts]
        completo = ''.join(textos)
        a = completo.find(busca, min_offset)
        if a == -1:
            break
        b = a + len(busca)
        pos = 0
        primeiro = True
        for t, txt in zip(ts, textos):
            fim = pos + len(txt)
            if fim <= a or pos >= b:
                pos = fim
                continue
            la = max(a - pos, 0)
            lb = min(b - pos, len(txt))
            if primeiro:
                _definir_texto(t, txt[:la] + substituicao + txt[lb:])
                primeiro = False
            else:
                _definir_texto(t, txt[:la] + txt[lb:])
            pos = fim
        count += 1
        min_offset = a + len(substituicao)
    return count


def run(caminho: str, busca: str, substituicao: str, saida: str = '') -> str:
    """
    caminho: caminho do arquivo .docx a modificar
    busca: texto exato a localizar (sem regex; o trecho pode estar fragmentado entre runs do Word)
    substituicao: texto que substituirá cada ocorrência de busca (string vazia remove o texto)
    saida: caminho do .docx resultante (padrão: sobrescreve o arquivo original)
    """
    try:
        if not busca:
            return 'Erro: busca não pode ser vazia.'
        destino = Path(saida) if saida else Path(caminho)
        with zipfile.ZipFile(caminho) as zf:
            dados = {n: zf.read(n) for n in zf.namelist()}
        if 'word/document.xml' not in dados:
            return 'Erro: word/document.xml ausente — o arquivo não é um .docx válido.'
        dom = defusedxml.minidom.parseString(dados['word/document.xml'])
        total = 0
        for p in dom.getElementsByTagName('w:p'):
            total += _aplicar(p, busca, substituicao)
        if total == 0:
            return f'Nenhuma ocorrência de {busca!r} encontrada em {caminho}.'
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
        return (f'{total} ocorrência(s) de {busca!r} substituída(s) por {substituicao!r}. '
                f'Arquivo salvo em: {destino}')
    except Exception as e:
        return f'Erro: {e}'
