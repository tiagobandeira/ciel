"""Adiciona um comentário a um documento .docx, ancorado num trecho de texto."""

REQUIREMENTS = ['defusedxml']

import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import defusedxml.minidom
from xml.sax.saxutils import escape

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
COMMENTS_REL_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments'


def _tag(no) -> str:
    return (no.localName or no.tagName) if no.nodeType == no.ELEMENT_NODE else ''


def _texto_de(el) -> str:
    partes = []
    for t in el.getElementsByTagName('w:t'):
        for c in t.childNodes:
            if c.nodeType in (c.TEXT_NODE, c.CDATA_SECTION_NODE):
                partes.append(c.data)
    return ''.join(partes)


def run(caminho: str, texto_comentario: str, trecho: str = '', autor: str = 'Ciel', saida: str = '') -> str:
    """
    caminho: caminho do arquivo .docx a anotar
    texto_comentario: conteúdo do comentário
    trecho: texto do documento ao qual ancorar o comentário — usa o parágrafo que o contém; vazio usa o primeiro parágrafo
    autor: nome do autor do comentário (padrão: Ciel)
    saida: caminho do .docx resultante (padrão: sobrescreve o original)
    """
    try:
        destino = Path(saida) if saida else Path(caminho)
        with zipfile.ZipFile(caminho) as zf:
            dados = {n: zf.read(n) for n in zf.namelist()}
        if 'word/document.xml' not in dados:
            return 'Erro: word/document.xml ausente — o arquivo não é um .docx válido.'
        dom = defusedxml.minidom.parseString(dados['word/document.xml'])

        if 'word/comments.xml' in dados:
            dom_c = defusedxml.minidom.parseString(dados['word/comments.xml'])
        else:
            dom_c = defusedxml.minidom.parseString(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:comments xmlns:w="' + W_NS + '"/>')

        ids = []
        for c in dom_c.getElementsByTagName('w:comment'):
            if c.getAttribute('w:id').isdigit():
                ids.append(int(c.getAttribute('w:id')))
        for r in dom.getElementsByTagName('w:commentReference'):
            if r.getAttribute('w:id').isdigit():
                ids.append(int(r.getAttribute('w:id')))
        cid = (max(ids) + 1) if ids else 0

        alvo = None
        if trecho:
            for p in dom.getElementsByTagName('w:p'):
                if trecho in _texto_de(p):
                    alvo = p
                    break
            if alvo is None:
                return f'Erro: trecho não encontrado no documento: {trecho}'
        else:
            ps = dom.getElementsByTagName('w:p')
            if not ps:
                return 'Erro: o documento não possui parágrafos.'
            alvo = ps[0]

        iniciais = ''.join(p[0] for p in autor.split()[:3]).upper() or 'C'
        data = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        autor_xml = escape(autor.replace(chr(34), chr(39)))
        snippet = (
            '<w:comment xmlns:w="' + W_NS + '" w:id="' + str(cid) + '" w:author="' + autor_xml
            + '" w:date="' + data + '" w:initials="' + iniciais + '">'
            '<w:p><w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:annotationRef/></w:r>'
            '<w:r><w:t xml:space="preserve">' + escape(texto_comentario) + '</w:t></w:r></w:p>'
            '</w:comment>')
        frag = defusedxml.minidom.parseString(snippet)
        dom_c.documentElement.appendChild(dom_c.importNode(frag.documentElement, True))
        dados['word/comments.xml'] = dom_c.toxml(encoding='UTF-8')

        start = dom.createElement('w:commentRangeStart')
        start.setAttribute('w:id', str(cid))
        end = dom.createElement('w:commentRangeEnd')
        end.setAttribute('w:id', str(cid))
        ref_run = dom.createElement('w:r')
        rpr = dom.createElement('w:rPr')
        st = dom.createElement('w:rStyle')
        st.setAttribute('w:val', 'CommentReference')
        rpr.appendChild(st)
        ref_run.appendChild(rpr)
        ref = dom.createElement('w:commentReference')
        ref.setAttribute('w:id', str(cid))
        ref_run.appendChild(ref)

        primeiro_run = None
        for filho in alvo.childNodes:
            if _tag(filho) == 'r':
                primeiro_run = filho
                break
        if primeiro_run is not None:
            alvo.insertBefore(start, primeiro_run)
        else:
            alvo.appendChild(start)
        alvo.appendChild(end)
        alvo.appendChild(ref_run)
        dados['word/document.xml'] = dom.toxml(encoding='UTF-8')

        rels_nome = 'word/_rels/document.xml.rels'
        rel = '<Relationship Id="rIdX" Type="' + COMMENTS_REL_TYPE + '" Target="comments.xml"/>'
        if rels_nome in dados:
            dom_r = defusedxml.minidom.parseString(dados[rels_nome])
            nums = []
            for r in dom_r.getElementsByTagName('Relationship'):
                rid = r.getAttribute('Id')
                if rid.startswith('rId') and rid[3:].isdigit():
                    nums.append(int(rid[3:]))
            rel = rel.replace('rIdX', 'rId' + str((max(nums) + 1) if nums else 1))
            frag_r = defusedxml.minidom.parseString(rel)
            dom_r.documentElement.appendChild(dom_r.importNode(frag_r.documentElement, True))
            dados[rels_nome] = dom_r.toxml(encoding='UTF-8')
        else:
            dados[rels_nome] = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + rel.replace('rIdX', 'rId1') + '</Relationships>').encode('utf-8')

        ct_nome = '[Content_Types].xml'
        if ct_nome in dados:
            dom_ct = defusedxml.minidom.parseString(dados[ct_nome])
            ja_tem = any(o.getAttribute('PartName') == '/word/comments.xml'
                         for o in dom_ct.getElementsByTagName('Override'))
            if not ja_tem:
                ov = dom_ct.createElement('Override')
                ov.setAttribute('PartName', '/word/comments.xml')
                ov.setAttribute('ContentType', 'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml')
                dom_ct.documentElement.appendChild(ov)
                dados[ct_nome] = dom_ct.toxml(encoding='UTF-8')

        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(destino.name + '.tmp')
        with zipfile.ZipFile(temporario, 'w', zipfile.ZIP_DEFLATED) as zout:
            if ct_nome in dados:
                zout.writestr(ct_nome, dados[ct_nome])
            for n, conteudo in dados.items():
                if n != ct_nome:
                    zout.writestr(n, conteudo)
        shutil.move(str(temporario), str(destino))
        return (f'Comentário #{cid} de {autor} adicionado e ancorado no documento. '
                f'Arquivo salvo em: {destino}')
    except Exception as e:
        return f'Erro: {e}'
