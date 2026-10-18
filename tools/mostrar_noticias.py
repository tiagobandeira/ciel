"""Abre um painel de notícias recentes sobre um tema (Google Notícias RSS)."""
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape

import requests

_UA = {"User-Agent": "Mozilla/5.0 (Ciel/1.0; projeto local)"}


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "noticias"


def _limpa(texto) -> str:
    t = re.sub(r"<[^>]+>", " ", str(texto or ""))
    return " ".join(unescape(t).split())


def run(tema: str, limite: int = 5) -> str:
    """
    tema: assunto das notícias (ex.: dinossauros, Artemis, inteligência artificial)
    limite: quantidade de notícias (3 a 8; padrão 5)
    """
    tema = " ".join(str(tema or "").split())[:80]
    if not tema:
        return "Informe um tema para buscar notícias."
    try:
        n = max(3, min(int(limite or 5), 8))
    except (TypeError, ValueError):
        n = 5
    try:
        resposta = requests.get(
            "https://news.google.com/rss/search",
            params={"q": tema, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"},
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
            pub = item.findtext("pubDate") or ""
            data = pub
            try:
                data = parsedate_to_datetime(pub).astimezone().strftime("%d/%m %H:%M")
            except Exception:
                pass
            itens.append({
                "titulo": titulo[:180], "link": link, "fonte": fonte[:60],
                "data": data[:40],
            })
            if len(itens) >= n:
                break
        if not itens:
            return f"Não encontrei notícias recentes sobre '{tema}'."
        painel = {
            "id": "noticias-" + _slug(tema),
            "tipo": "noticias",
            "titulo": "Notícias: " + tema,
            "nomes": [tema, "notícias", "noticias", "news"],
            "slot": "bottom-left",
            "fala": "resumo",
            "resumo": f"{len(itens)} notícias recentes sobre {tema}.",
            "acoes": [],
            "dados": {
                "itens": itens,
                "fonte": "Google Notícias",
                "atualizado": datetime.now().strftime("%d/%m %H:%M"),
            },
        }
        import ui_bus
        ui_bus.publish("painel", acao="abrir", painel=painel, focar=True)
        return f"Painel de notícias sobre '{tema}' aberto ({len(itens)} itens, id: {painel['id']})."
    except Exception as e:
        return f"Erro ao buscar notícias de '{tema}': {str(e)[:140]}"
