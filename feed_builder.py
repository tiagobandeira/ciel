"""Monta o feed de pesquisa a partir de fontes abertas, sem API paga.

Fontes: Google News RSS, Bluesky (API pública) e Wikimedia Commons.
O resultado é o mesmo formato de painel consumido pelo front (tipo="feed").
"""
from __future__ import annotations

import html
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

_UA = {"User-Agent": "Mozilla/5.0 (Ciel/1.0; projeto local)"}
NEUTRAL = "astronomia"
_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_CACHE_TTL = 600
_CONTEXTO_CIENCIA = {
    "lua", "sol", "terra", "marte", "venus", "jupiter", "saturno", "urano", "netuno",
    "espaco", "universo", "artemis", "nasa", "estrela", "galaxia", "telescopio",
    "buraco-negro", "sistema-solar", "via-lactea", "cosmologia", "astronomia",
}


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:48] or "feed"


def _limpa(texto) -> str:
    t = re.sub(r"<[^>]+>", " ", str(texto or ""))
    return " ".join(html.unescape(t).split())


def _tema_limpo(tema) -> str:
    t = " ".join(str(tema or "").split())[:80]
    t = re.sub(r"^(?:a|o|as|os|um|uma)\s+", "", t, flags=re.I)
    return t or NEUTRAL


def _tags(tema: str, *extras: str) -> list[str]:
    base = _slug(tema).replace("-", " ")
    tags = [base, *[str(e).strip().lower() for e in extras if e]]
    return list(dict.fromkeys(t for t in tags if t))


def _quando(dt) -> str:
    if not isinstance(dt, datetime):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seg = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if seg < 60:
        return "agora"
    if seg < 3600:
        return f"{seg // 60} min"
    if seg < 86400:
        return f"{seg // 3600} h"
    if seg < 172800:
        return "ontem"
    return f"{seg // 86400} d"


def _dt_iso(valor: str):
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except Exception:
        return None


def _noticias(tema: str, limite: int = 5) -> list[dict]:
    consulta = tema + " ciência" if _slug(tema) in _CONTEXTO_CIENCIA else tema
    resposta = requests.get(
        "https://news.google.com/rss/search",
        params={"q": consulta, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"},
        headers=_UA, timeout=15,
    )
    resposta.raise_for_status()
    root = ET.fromstring(resposta.content)
    itens = []
    for item in root.findall("channel/item"):
        titulo = _limpa(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if not titulo or not link.startswith(("http://", "https://")):
            continue
        fonte = _limpa(item.findtext("source")) or "Google Notícias"
        if fonte and titulo.endswith(" - " + fonte):
            titulo = titulo[:-len(fonte) - 3].strip()
        desc = _limpa(item.findtext("description"))
        resumo = desc[:260]
        imagem = ""
        media = item.find("{http://search.yahoo.com/mrss/}content")
        if media is not None:
            imagem = (media.get("url") or "").strip()
        pub = item.findtext("pubDate") or ""
        try:
            data = parsedate_to_datetime(pub)
            quando = _quando(data)
        except Exception:
            quando = ""
        itens.append({
            "tipo": "ARTIGO", "titulo": titulo[:180], "fonte": fonte[:60],
            "quando": quando, "link": link, "resumo": resumo,
            "imagem": imagem, "tags": _tags(tema, "notícias", "google news"),
        })
        if len(itens) >= limite:
            break
    return itens


_STOP = set("""
a o as os um uma uns umas de da do das dos para por com sem em no na nos nas
que se ao aos à às e ou mas como quando onde qual quais quem cujo cuja
seu sua seus suas este esta estes estas esse essa esses essas isso isto
mais menos muito pouco também já ainda sobre entre após antes até desde
foi são ser está estão era eram tem têm tinha havia pode podem poderia
hoje ontem amanhã agora novo nova novos novas primeiro primeira último última
dia dias ano anos semana mês meses hora horas vez vezes parte forma caso
segundo terça quarta quinta sexta sábado domingo janeiro fevereiro
março abril maio junho julho agosto setembro outubro novembro dezembro
confira veja saiba entenda pesquisa pesquisadores estudo estudos
""".split())


def _palavra_contexto(tema: str, noticias: list[dict]) -> str:
    """Escolhe uma palavra das manchetes para aproximar a busca social do assunto."""
    tema_tokens = {p for p in re.findall(r"[a-zà-ÿ0-9]{3,}", tema.lower())}
    contagem: dict[str, int] = {}
    for noticia in noticias[:5]:
        texto = (noticia.get("titulo", "") + " " + noticia.get("resumo", "")).lower()
        for palavra in re.findall(r"[a-zà-ÿ]{4,}", texto):
            if palavra in _STOP or palavra in tema_tokens:
                continue
            contagem[palavra] = contagem.get(palavra, 0) + 1
    if not contagem:
        return ""
    return max(contagem, key=contagem.get)


def _bluesky(tema: str, limite: int = 2, contexto: str = "") -> list[dict]:
    def buscar(q: str):
        return requests.get(
            "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",
            params={"q": q, "limit": max(8, limite * 4), "sort": "top", "lang": "pt"},
            headers=_UA, timeout=15,
        )
    consulta = (tema + " " + contexto).strip() if contexto else tema
    resposta = buscar(consulta)
    resposta.raise_for_status()
    posts = resposta.json().get("posts") or []
    if not posts and contexto:
        posts = buscar(tema).json().get("posts") or []
    itens = []
    for post in posts:
        texto = " ".join(str((post.get("record") or {}).get("text") or "").split())
        if len(texto) < 50 or int(post.get("likeCount") or 0) < 1:
            continue
        autor = (post.get("author") or {}).get("handle") or ""
        uri = str(post.get("uri") or "")
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        link = f"https://bsky.app/profile/{quote(autor)}/post/{rkey}" if autor and rkey else ""
        if not link:
            continue
        itens.append({
            "tipo": "POST", "titulo": texto[:86], "fonte": ("Bluesky · @" + autor)[:60],
            "quando": _quando(_dt_iso(post.get("indexedAt"))), "link": link,
            "resumo": texto[:260], "tags": _tags(tema, "bluesky", "social"),
        })
        if len(itens) >= limite:
            break
    return itens


def _commons_imagens(tema: str, limite: int = 3) -> list[dict]:
    resposta = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{tema} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": limite * 2,
            "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 900,
        },
        headers=_UA, timeout=15,
    )
    resposta.raise_for_status()
    paginas = sorted(((resposta.json().get("query") or {}).get("pages") or {}).values(),
                     key=lambda p: p.get("index", 99))
    itens = []
    for pagina in paginas:
        info = (pagina.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url") or ""
        link = info.get("descriptionurl") or ""
        titulo = re.sub(r"^(Ficheiro|File):", "", pagina.get("title", ""), flags=re.I)
        titulo = re.sub(r"\.[a-z0-9]{2,5}$", "", titulo, flags=re.I)
        if not url or not link:
            continue
        itens.append({
            "tipo": "IMAGEM", "titulo": " ".join(titulo.replace("_", " ").split())[:100],
            "fonte": "Wikimedia Commons", "quando": "", "link": link,
            "imagem": url, "resumo": "Imagem relacionada a " + tema + ".",
            "tags": _tags(tema, "wikimedia", "imagem"),
        })
        if len(itens) >= limite:
            break
    return itens


def _https(url: str) -> str:
    url = str(url or "").strip()
    return "https:" + url if url.startswith("//") else url


def _commons_videos(tema: str, limite: int = 2) -> list[dict]:
    resposta = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{tema} filetype:video", "gsrnamespace": 6,
            "gsrlimit": max(6, limite * 3),
            "prop": "videoinfo|imageinfo", "viprop": "url|derivatives",
            "iiprop": "url|mime", "iiurlwidth": 960,
        },
        headers=_UA, timeout=20,
    )
    resposta.raise_for_status()
    paginas = sorted(((resposta.json().get("query") or {}).get("pages") or {}).values(),
                     key=lambda p: p.get("index", 99))
    itens, vistos = [], set()
    for pagina in paginas:
        info = (pagina.get("videoinfo") or [{}])[0]
        imagem = (pagina.get("imageinfo") or [{}])[0]
        if not str(imagem.get("mime", "")).startswith("video/"):
            continue
        candidatos = [d for d in (info.get("derivatives") or []) if d.get("src")]
        web = [d for d in candidatos
               if str(d.get("type", "")).startswith(("video/webm", "video/ogg"))]
        web.sort(key=lambda d: int(d.get("width") or 0))
        escolhido = next((d for d in reversed(web) if 0 < int(d.get("width") or 0) <= 720), None)
        src = _https((escolhido or (web[0] if web else (candidatos[0] if candidatos else {}))).get("src", ""))
        titulo = re.sub(r"^(Ficheiro|File):", "", pagina.get("title", ""), flags=re.I)
        titulo = re.sub(r"\.[a-z0-9]{2,5}$", "", titulo, flags=re.I)
        titulo = " ".join(titulo.replace("_", " ").split())[:100]
        if not src or not titulo or titulo.lower() in vistos:
            continue
        vistos.add(titulo.lower())
        itens.append({
            "titulo": titulo, "embed": src,
            "poster": _https(imagem.get("thumburl") or ""),
            "link": imagem.get("descriptionurl") or "",
            "fonte": "Wikimedia Commons",
        })
        if len(itens) >= limite:
            break
    return itens


def _videos(tema: str, limite: int = 2) -> list[dict]:
    try:
        videos = _commons_videos(tema, limite)
    except Exception:
        return []
    itens = []
    for video in videos:
        if not video.get("embed"):
            continue
        itens.append({
            "tipo": "VÍDEO", "titulo": video.get("titulo") or ("Vídeo: " + tema),
            "fonte": video.get("fonte") or "Wikimedia Commons", "quando": "",
            "link": video.get("link") or "", "imagem": video.get("poster") or "",
            "video": {"provedor": "commons", "embed": video["embed"]},
            "resumo": "Vídeo relacionado a " + tema + ".",
            "tags": _tags(tema, "wikimedia", "vídeo"),
        })
    return itens


def build_feed(tema: str = "", limite: int = 4, forcar: bool = False) -> dict:
    """Busca e mistura notícias, posts e mídia sobre o tema."""
    tema = _tema_limpo(tema)
    try:
        n = max(4, min(int(limite or 4), 12))
    except (TypeError, ValueError):
        n = 4
    chave = (tema.lower(), n)
    agora = time.time()
    cache = _CACHE.get(chave)
    if cache and not forcar and agora - cache[0] < _CACHE_TTL:
        return cache[1]

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_news = executor.submit(_noticias, tema, min(5, n))
        f_imgs = executor.submit(_commons_imagens, tema, min(3, n))
        f_video = executor.submit(_videos, tema, min(2, n))
        def seguro(f, padrao):
            try:
                return f.result()
            except Exception:
                return padrao
        news = seguro(f_news, [])
        imgs = seguro(f_imgs, [])
        videos = seguro(f_video, [])

    contexto = _palavra_contexto(tema, news)
    try:
        posts = _bluesky(tema, min(1, n), contexto)
    except Exception:
        posts = []

    pools = [news, videos, videos, imgs, posts]
    itens = []
    vistos = set()
    indice = 0
    while len(itens) < n and any(pools):
        pool = pools[indice % len(pools)]
        if pool:
            item = pool.pop(0)
            chave_item = (item.get("link") or "").strip().lower() or item.get("titulo", "").lower()
            if chave_item and chave_item not in vistos:
                vistos.add(chave_item)
                itens.append(item)
        indice += 1

    dados = {
        "tema": tema,
        "itens": itens[:n],
        "fontes": sorted({i.get("fonte", "") for i in itens if i.get("fonte")}),
        "limite": n,
        "atualizado": datetime.now().strftime("%d/%m %H:%M"),
    }
    _CACHE[chave] = (agora, dados)
    return dados


def build_mais(tema: str = "", limite: int = 4, excluir=None) -> dict:
    """Busca uma nova página de candidatos, ignorando o que o front já mostrou."""
    tema = _tema_limpo(tema)
    try:
        n = max(1, min(int(limite or 4), 6))
    except (TypeError, ValueError):
        n = 4
    vistos = {str(x).strip().lower() for x in (excluir or []) if str(x).strip()}

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_news = executor.submit(_noticias, tema, 30)
        f_imgs = executor.submit(_commons_imagens, tema, 12)
        f_video = executor.submit(_videos, tema, 6)
        def seguro(f, padrao):
            try:
                return f.result()
            except Exception:
                return padrao
        news = seguro(f_news, [])
        imgs = seguro(f_imgs, [])
        videos = seguro(f_video, [])

    contexto = _palavra_contexto(tema, news)
    try:
        posts = _bluesky(tema, 10, contexto)
    except Exception:
        posts = []

    pools = [news, videos, imgs, posts]
    itens = []
    indice = 0
    while len(itens) < n and any(pools):
        pool = pools[indice % len(pools)]
        if pool:
            item = pool.pop(0)
            chave = (item.get("link") or item.get("titulo") or "").strip().lower()
            if chave and chave not in vistos:
                vistos.add(chave)
                itens.append(item)
        indice += 1

    return {
        "tema": tema,
        "itens": itens,
        "fontes": sorted({i.get("fonte", "") for i in itens if i.get("fonte")}),
        "limite": n,
    }


def build_painel(tema: str = "", limite: int = 4, forcar: bool = False) -> dict:
    """Monta o manifesto de painel do feed (o front o abre no palco)."""
    dados = build_feed(tema, limite, forcar)
    tema = dados["tema"]
    return {
        "id": "feed-" + _slug(tema),
        "tipo": "feed",
        "titulo": "Feed: " + tema,
        "nomes": [tema, "feed", "pesquisa", "notícias", "fontes"],
        "apresentacao": "central",
        "slot": "bottom-left",
        "fala": "nunca",
        "resumo": f"Feed de pesquisa sobre {tema} com notícias, posts e mídia de fontes abertas.",
        "acoes": [],
        "dados": dados,
    }
