"""Extrai o texto de um documento .docx como markdown estruturado."""

EXTRA = True

import zipfile
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _texto(el) -> str:
    partes = []
    for no in el.iter():
        if no.tag == W + 't' and no.text:
            partes.append(no.text)
        elif no.tag == W + 'tab':
            partes.append('\t')
        elif no.tag == W + 'br':
            partes.append('\n')
    return ''.join(partes)


def run(caminho: str, max_caracteres: int = 20000) -> str:
    """
    caminho: caminho do arquivo .docx a ler
    max_caracteres: número máximo de caracteres retornados (padrão: 20000)
    """
    try:
        with zipfile.ZipFile(caminho) as zf:
            xml = zf.read('word/document.xml')
        root = ET.fromstring(xml)
        body = root.find(W + 'body')
        if body is None:
            return 'Erro: documento sem corpo (word/document.xml inválido).'
        linhas = []
        for el in list(body):
            if el.tag == W + 'p':
                texto = _texto(el).strip()
                if not texto:
                    continue
                estilo = el.find(W + 'pPr/' + W + 'pStyle')
                nome = estilo.get(W + 'val', '') if estilo is not None else ''
                if nome == 'Title':
                    linhas.append('# ' + texto)
                elif nome.startswith('Heading'):
                    sufixo = nome[len('Heading'):]
                    nivel = int(sufixo) if sufixo.isdigit() else 1
                    linhas.append('#' * min(nivel, 6) + ' ' + texto)
                elif el.find(W + 'pPr/' + W + 'numPr') is not None:
                    linhas.append('- ' + texto)
                else:
                    linhas.append(texto)
            elif el.tag == W + 'tbl':
                for tr in el.iter(W + 'tr'):
                    celulas = [_texto(tc).strip() for tc in tr.findall(W + 'tc')]
                    linhas.append('| ' + ' | '.join(celulas) + ' |')
        saida = '\n'.join(linhas)
        if not saida:
            return '(documento sem texto no corpo)'
        if len(saida) > max_caracteres:
            saida = saida[:max_caracteres] + '\n...[texto truncado]'
        return saida
    except FileNotFoundError:
        return f'Erro: arquivo não encontrado: {caminho}'
    except KeyError:
        return 'Erro: o arquivo não contém word/document.xml — não parece um .docx válido.'
    except Exception as e:
        return f'Erro ao ler documento: {e}'
