"""Abre um painel de vídeo no palco central (YouTube/Vimeo/direto ou Wikimedia Commons)."""
import re
import unicodedata
from urllib.parse import parse_qs, quote, urlparse

import requests

_UA = {"User-Agent": "Ciel/1.0 (projeto local)"}
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "video"


def _nome_arquivo(titulo: str) -> str:
    t = re.sub(r"^(Ficheiro|File):", "", str(titulo or ""), flags=re.I)
    t = re.sub(r"\.[a-z0-9]{2,5}$", "", t, flags=re.I)
    return " ".join(t.replace("_", " ").split())[:100]


def _https(url: str) -> str:
    url = str(url or "").strip()
    return "https:" + url if url.startswith("//") else url


def _youtube_id(url: str) -> str:
    u = urlparse(url)
    host = (u.netloc or "").lower()
    if host == "youtu.be":
        candidato = u.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        q = parse_qs(u.query)
        candidato = (q.get("v") or [""])[0]
        partes = [p for p in u.path.strip("/").split("/") if p]
        if not candidato and len(partes) >= 2 and partes[0] in {"embed", "shorts", "live"}:
            candidato = partes[1]
    else:
        candidato = ""
    return candidato if _YT_ID.match(candidato or "") else ""


def _parse_url(url: str) -> dict:
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("A URL do vídeo precisa ser http/https.")
    host = (u.netloc or "").lower()
    yt = _youtube_id(url)
    if yt:
        return {
            "provedor": "youtube", "embed": f"https://www.youtube-nocookie.com/embed/{yt}?rel=0",
            "url": url, "poster": f"https://i.ytimg.com/vi/{yt}/hqdefault.jpg",
            "link": url, "titulo": "", "fonte": "YouTube",
        }
    if host == "vimeo.com" or host.endswith(".vimeo.com"):
        m = re.search(r"/(\d+)", u.path)
        if m:
            vid = m.group(1)
            return {
                "provedor": "vimeo", "embed": f"https://player.vimeo.com/video/{vid}",
                "url": url, "poster": "", "link": url, "titulo": "", "fonte": "Vimeo",
            }
    if u.path.lower().endswith((".mp4", ".webm", ".ogv", ".ogg")):
        return {
            "provedor": "direto", "embed": url, "url": url, "poster": "",
            "link": url, "titulo": "", "fonte": "Vídeo",
        }
    raise ValueError("Provedor de vídeo não suportado (YouTube, Vimeo ou vídeo direto).")


def _commons_video(tema: str) -> dict:
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{tema} filetype:video", "gsrnamespace": 6, "gsrlimit": 6,
        "prop": "videoinfo|imageinfo", "viprop": "url|derivatives",
        "iiprop": "url|mime", "iiurlwidth": 960,
    }
    dados = requests.get("https://commons.wikimedia.org/w/api.php",
                         params=params, headers=_UA, timeout=20).json()
    paginas = sorted(((dados.get("query") or {}).get("pages") or {}).values(),
                     key=lambda p: p.get("index", 99))
    for pagina in paginas:
        titulo = pagina.get("title", "")
        info = (pagina.get("videoinfo") or [{}])[0]
        imagem = (pagina.get("imageinfo") or [{}])[0]
        if not str(imagem.get("mime", "")).startswith("video/"):
            continue
        candidatos = [d for d in (info.get("derivatives") or []) if d.get("src")]
        web = [d for d in candidatos
               if str(d.get("type", "")).startswith(("video/webm", "video/ogg"))]
        web.sort(key=lambda d: int(d.get("width") or 0))
        escolhido = None
        for d in reversed(web):
            if 0 < int(d.get("width") or 0) <= 720:
                escolhido = d
                break
        if not escolhido:
            escolhido = web[0] if web else (candidatos[0] if candidatos else None)
        src = _https((escolhido or {}).get("src") or info.get("url") or "")
        if not src:
            continue
        link = imagem.get("descriptionurl") or (
            "https://commons.wikimedia.org/wiki/" + quote(titulo, safe=""))
        return {
            "provedor": "commons", "embed": src, "url": src,
            "poster": _https(imagem.get("thumburl") or ""), "link": link,
            "titulo": _nome_arquivo(titulo), "fonte": "Wikimedia Commons",
        }
    return {}


def run(tema: str, url: str = "", titulo: str = "") -> str:
    """
    tema: assunto do vídeo (ex.: dinossauros, Lua)
    url: URL opcional de YouTube/Vimeo ou vídeo direto
    titulo: título opcional do painel
    """
    tema = " ".join(str(tema or "").split())[:80]
    url = str(url or "").strip()[:500]
    titulo = " ".join(str(titulo or "").split())[:80]
    try:
        if url:
            video = _parse_url(url)
        else:
            if not tema:
                return "Informe um tema ou uma URL para o vídeo."
            video = _commons_video(tema)
            if not video:
                return f"Não encontrei vídeos sobre '{tema}' no Wikimedia Commons."
        if not titulo:
            titulo = video.get("titulo") or ("Vídeo: " + tema if tema else "Vídeo")
        painel = {
            "id": "video-" + _slug(tema or titulo),
            "tipo": "video",
            "titulo": titulo,
            "nomes": [tema, titulo, "vídeo", "video"],
            "apresentacao": "central",
            "slot": "bottom-left",
            "fala": "nunca",
            "resumo": f"Vídeo sobre {tema or titulo} ({video.get('fonte', 'vídeo')}).",
            "acoes": [],
            "dados": video,
        }
        import ui_bus
        ui_bus.publish("painel", acao="abrir", painel=painel, focar=True, palco=True)
        return f"Painel de vídeo '{titulo}' aberto no palco central (id: {painel['id']})."
    except Exception as e:
        return f"Erro ao abrir vídeo: {str(e)[:140]}"
