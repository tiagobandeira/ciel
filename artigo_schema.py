"""Schema e validação do artefato 'artigo' do modo interativo.

O modelo monta blocos declarativos; nenhum HTML/JS arbitrário passa por aqui.
SVG é aceito apenas como ilustração, com um filtro conservador no servidor; o
front ainda aplica a allowlist final (svgSeguro) antes de inserir no DOM.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata

MAX_BLOCOS = 24
MAX_TITULO = 120
MAX_TEXTO = 4000
MAX_FORMULA = 1200
MAX_SVG = 20000
MAX_TABELA_LINHAS = 50
MAX_TABELA_COLUNAS = 8
MAX_GRAFICO_ITENS = 12

_TIPOS = {"texto", "formula", "animacao", "grafico", "tabela", "imagem"}

_SVG_TAG_PROIBIDA = re.compile(
    r"<\s*(?:script|foreignObject|iframe|object|embed|style|link|meta)\b", re.I
)
_SVG_ATRIBUTO_PERIGOSO = re.compile(
    r"\s(?:on[a-z]+|style|href|xlink:href)\s*=", re.I
)
_SVG_URL = re.compile(r"url\s*\(|javascript\s*:", re.I)
_SVG_ROOT = re.compile(r"<\s*svg\b", re.I)


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "artigo"


def _texto(valor, campo: str, limite: int, obrigatorio: bool = False) -> str:
    texto = str(valor or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if obrigatorio and not texto:
        raise ValueError(f"{campo} é obrigatório")
    if len(texto) > limite:
        raise ValueError(f"{campo} excede {limite} caracteres")
    return texto


def _numero(valor, campo: str) -> float:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{campo} precisa ser numérico")
    if not math.isfinite(n):
        raise ValueError(f"{campo} precisa ser finito")
    if n < 0:
        raise ValueError(f"{campo} não pode ser negativo")
    return n


def _svg(valor) -> str:
    svg = str(valor or "").strip()
    if not svg:
        raise ValueError("animacao.svg é obrigatório")
    if len(svg) > MAX_SVG:
        raise ValueError(f"animacao.svg excede {MAX_SVG} caracteres")
    if not _SVG_ROOT.search(svg):
        raise ValueError("animacao.svg precisa começar por <svg>")
    if _SVG_TAG_PROIBIDA.search(svg):
        raise ValueError("animacao.svg contém tag não permitida")
    if _SVG_ATRIBUTO_PERIGOSO.search(svg):
        raise ValueError("animacao.svg contém atributo não permitido")
    if _SVG_URL.search(svg):
        raise ValueError("animacao.svg não pode referenciar URL/javascript")
    return svg


def _bloco(bruto) -> dict:
    if not isinstance(bruto, dict):
        raise ValueError("cada bloco precisa ser um objeto")
    tipo = str(bruto.get("tipo") or "").strip().lower()
    if tipo not in _TIPOS:
        raise ValueError(f"tipo de bloco desconhecido: {tipo or '(vazio)'}")

    bloco = {"tipo": tipo}
    titulo = _texto(bruto.get("titulo"), "titulo", MAX_TITULO)
    if titulo:
        bloco["titulo"] = titulo
    fala = _texto(bruto.get("fala"), "fala", MAX_TEXTO)
    if fala:
        bloco["fala"] = fala

    if tipo == "texto":
        bloco["corpo"] = _texto(bruto.get("corpo"), "texto.corpo", MAX_TEXTO, True)
    elif tipo == "formula":
        bloco["tex"] = _texto(bruto.get("tex"), "formula.tex", MAX_FORMULA, True)
    elif tipo == "animacao":
        bloco["svg"] = _svg(bruto.get("svg"))
    elif tipo == "imagem":
        bloco["nome"] = _texto(bruto.get("nome"), "imagem.nome", MAX_TITULO, True)
        bloco["bio"] = _texto(bruto.get("bio"), "imagem.bio", MAX_TEXTO, True)
    elif tipo == "grafico":
        dados = bruto.get("dados")
        if not isinstance(dados, list) or not dados:
            raise ValueError("grafico.dados precisa ser uma lista não vazia")
        if len(dados) > MAX_GRAFICO_ITENS:
            raise ValueError(f"grafico.dados aceita no máximo {MAX_GRAFICO_ITENS} itens")
        itens = []
        for i, item in enumerate(dados, 1):
            if not isinstance(item, dict):
                raise ValueError(f"grafico.dados[{i}] precisa ser um objeto")
            itens.append({
                "rotulo": _texto(item.get("rotulo"), f"grafico.dados[{i}].rotulo", 40, True),
                "a2b2": _numero(item.get("a2b2"), f"grafico.dados[{i}].a2b2"),
                "c2": _numero(item.get("c2"), f"grafico.dados[{i}].c2"),
            })
        bloco["dados"] = itens
    elif tipo == "tabela":
        colunas = bruto.get("colunas")
        linhas = bruto.get("linhas")
        if not isinstance(colunas, list) or not colunas:
            raise ValueError("tabela.colunas precisa ser uma lista não vazia")
        if len(colunas) > MAX_TABELA_COLUNAS:
            raise ValueError(f"tabela.colunas aceita no máximo {MAX_TABELA_COLUNAS} colunas")
        if not isinstance(linhas, list) or not linhas:
            raise ValueError("tabela.linhas precisa ser uma lista não vazia")
        if len(linhas) > MAX_TABELA_LINHAS:
            raise ValueError(f"tabela.linhas aceita no máximo {MAX_TABELA_LINHAS} linhas")
        cols = [_texto(c, "tabela.colunas", 60, True) for c in colunas]
        rows = []
        for i, linha in enumerate(linhas, 1):
            if not isinstance(linha, list) or len(linha) != len(cols):
                raise ValueError(f"tabela.linhas[{i}] precisa ter {len(cols)} células")
            rows.append([_texto(v, f"tabela.linhas[{i}]", 200) for v in linha])
        bloco["colunas"] = cols
        bloco["linhas"] = rows
    return bloco


def validar_artigo(titulo, blocos) -> dict:
    """Valida e normaliza um artigo. Levanta ValueError com mensagem curta."""
    titulo = _texto(titulo, "titulo", MAX_TITULO, True)
    if isinstance(blocos, str):
        try:
            blocos = json.loads(blocos)
        except Exception as e:
            raise ValueError(f"blocos não é um JSON válido: {e}")
    if not isinstance(blocos, list) or not blocos:
        raise ValueError("blocos precisa ser uma lista não vazia")
    if len(blocos) > MAX_BLOCOS:
        raise ValueError(f"o artigo aceita no máximo {MAX_BLOCOS} blocos")
    validos = [_bloco(b) for b in blocos]
    return {
        "id": "artigo-" + _slug(titulo),
        "titulo": titulo,
        "blocos": validos,
    }
