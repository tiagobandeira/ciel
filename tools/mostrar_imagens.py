"""Abre um painel de imagens na tela de pesquisa sobre um tema (busca na Wikipédia/Wikimedia). Use no modo pesquisa para complementar a resposta com imagens concretas."""
import re
import unicodedata

import requests

_API = "https://pt.wikipedia.org/w/api.php"
_REST = "https://pt.wikipedia.org/api/rest_v1/page/media-list/"
_UA = {"User-Agent": "Ciel/1.0 (projeto local)"}
_MAX = 4


def _get(url: str, **kwargs):
    resposta = requests.get(url, headers=_UA, timeout=15, **kwargs)
    resposta.raise_for_status()
    return resposta.json()


def _url(src: str) -> str:
    if not src:
        return ""
    return "https:" + src if src.startswith("//") else src


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "tema"


def _norm(texto: str) -> str:
    return _slug(texto).replace("-", " ")


def _nome_arquivo(titulo: str) -> str:
    t = re.sub(r"^(Ficheiro|File):", "", str(titulo or ""), flags=re.I)
    t = re.sub(r"\.[a-z0-9]{2,5}$", "", t, flags=re.I)
    return " ".join(t.replace("_", " ").split())[:90]


def _srcset(item: dict) -> tuple:
    """Devolve (url_menor, url_maior) do srcset do media-list."""
    ss = item.get("srcset") or []
    if not ss:
        return "", ""
    ss = sorted(ss, key=lambda x: 2 if str(x.get("scale", "1x")).startswith("2") else 1)
    return _url(ss[0].get("src", "")), _url(ss[-1].get("src", ""))


def _pagina(tema: str):
    """Melhor página da Wikipédia para o tema: título exato, senão a primeira com imagem."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": tema, "gsrnamespace": 0, "gsrlimit": 8,
        "prop": "pageimages|extracts|info|pageprops",
        "piprop": "thumbnail", "pithumbsize": 600,
        "exintro": 1, "explaintext": 1, "exlimit": "max", "inprop": "url",
    }
    dados = _get(_API, params=params)
    paginas = sorted(((dados.get("query") or {}).get("pages") or {}).values(),
                     key=lambda p: p.get("index", 99))
    paginas = [p for p in paginas if not (p.get("pageprops") or {}).get("disambiguation")]
    if not paginas:
        return None
    alvo = _norm(tema)
    exatas = [p for p in paginas if _norm(p.get("title", "")) == alvo]
    if exatas:
        return exatas[0]
    com_imagem = [p for p in paginas if p.get("thumbnail")]
    return (com_imagem or paginas)[0]


def _midia(titulo: str) -> list:
    """Imagens da galeria do artigo (media-list), até _MAX."""
    dados = _get(_REST + requests.utils.quote(titulo, safe=""))
    itens = []
    for item in dados.get("items") or []:
        if item.get("type") != "image" or not item.get("showInGallery"):
            continue
        url, url_grande = _srcset(item)
        nome = _nome_arquivo(item.get("title") or "")
        if not url or not nome:
            continue
        itens.append({
            "titulo": nome, "url": url, "urlGrande": url_grande or url,
            "link": "", "credito": "Wikipédia / Wikimedia Commons",
        })
        if len(itens) >= _MAX:
            break
    return itens


def _fallback(paginas: list) -> list:
    itens = []
    for p in paginas:
        url = (p.get("thumbnail") or {}).get("source")
        if not url:
            continue
        itens.append({
            "titulo": p.get("title", ""), "url": url, "urlGrande": url,
            "link": p.get("fullurl", ""), "credito": "Wikipédia / Wikimedia Commons",
        })
        if len(itens) >= _MAX:
            break
    return itens


def _commons(tema: str) -> list:
    """Fallback: busca arquivos de imagem no Wikimedia Commons."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{tema} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 6,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 900,
    }
    dados = _get("https://commons.wikimedia.org/w/api.php", params=params)
    paginas = sorted(((dados.get("query") or {}).get("pages") or {}).values(),
                     key=lambda p: p.get("index", 99))
    itens = []
    for p in paginas:
        info = (p.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url") or ""
        if not url:
            continue
        itens.append({
            "titulo": _nome_arquivo(p.get("title", "")),
            "url": url, "urlGrande": url,
            "link": info.get("descriptionurl", ""),
            "credito": "Wikimedia Commons",
        })
        if len(itens) >= _MAX:
            break
    return itens


def run(tema: str, titulo: str = "") -> str:
    """
    tema: assunto das imagens (ex.: Lua, foguetes, Programa Artemis)
    titulo: título opcional do painel
    """
    tema = " ".join(str(tema or "").split())[:80]
    if not tema:
        return "Informe um tema para buscar imagens."
    try:
        pagina = _pagina(tema)
        if not pagina:
            return f"Não encontrei uma página da Wikipédia para '{tema}'."
        titulo_pagina = pagina.get("title", tema)
        link = pagina.get("fullurl", "")
        resumo = " ".join(str(pagina.get("extract") or "").split())[:220]
        try:
            itens = _midia(titulo_pagina)
        except Exception:
            itens = []
        for item in itens:
            item["link"] = link
        if len(itens) < _MAX:
            vistos = {item["url"] for item in itens}
            try:
                extras = _commons(tema)
            except Exception:
                extras = []
            for item in extras:
                if item["url"] in vistos:
                    continue
                itens.append(item)
                vistos.add(item["url"])
                if len(itens) >= _MAX:
                    break
        if len(itens) < 2:
            itens = _fallback([pagina]) or itens
        if not itens:
            return f"Não encontrei imagens para '{tema}'."

        slug = _slug(tema)
        painel = {
            "id": "imagens-" + slug,
            "tipo": "imagens",
            "titulo": (" ".join(str(titulo).split())[:80] or f"Imagens: {titulo_pagina}"),
            "nomes": [tema, titulo_pagina, "imagens", "fotos"],
            "apresentacao": "central",
            "slot": "bottom-left",
            "tamanho": "grande",
            "fala": "nunca",
            "resumo": resumo or f"Imagens sobre {tema}.",
            "acoes": [],
            "dados": {"itens": itens[:_MAX]},
        }
        import ui_bus
        ui_bus.publish("painel", acao="abrir", painel=painel, focar=True)
        return (f"Painel de imagens sobre '{tema}' aberto com "
                f"{len(painel['dados']['itens'])} imagens (id: {painel['id']}).")
    except Exception as e:
        return f"Erro ao buscar imagens de '{tema}': {str(e)[:140]}"
