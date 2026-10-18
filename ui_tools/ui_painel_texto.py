"""Abre um painel de texto/resumo na tela de pesquisa."""
import re
import unicodedata


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "texto"


def _link(valor: str) -> str:
    v = str(valor or "").strip()
    return v if v.startswith(("http://", "https://")) else ""


def run(titulo: str, texto: str, fonte: str = "", link: str = "") -> str:
    """
    titulo: título curto do painel
    texto: conteúdo em texto simples; parágrafos e listas com "- "
    fonte: fonte opcional (ex.: Wikipédia)
    link: link opcional (http/https)
    """
    titulo = " ".join(str(titulo or "").split())[:80] or "Anotações"
    texto = str(texto or "").replace("\r\n", "\n").replace("\r", "\n").strip()[:8000]
    if not texto:
        return "O painel de texto precisa de um conteúdo."
    fonte = " ".join(str(fonte or "").split())[:80]
    link = _link(link)
    fala_texto = re.sub(r"(?m)^\s*[-*]\s+", "", texto)
    fala_texto = re.sub(r"[#*_`>|~]+", " ", fala_texto)
    fala_texto = " ".join(fala_texto.split())[:800]
    acoes = [{"id": "copiar", "rotulo": "Copiar", "tipo": "front", "acao": "copiar"}]
    if link:
        acoes.append({"id": "abrir_fonte", "rotulo": "Abrir fonte", "tipo": "front", "acao": "abrir"})
    painel = {
        "id": "texto-" + _slug(titulo),
        "tipo": "texto",
        "titulo": titulo,
        "nomes": [titulo, "texto", "resumo", "anotações"],
        "slot": "bottom-left",
        "fala": "resumo",
        "fala_texto": fala_texto,
        "resumo": " ".join(texto.split())[:180],
        "acoes": acoes,
        "dados": {"texto": texto, "fonte": fonte, "link": link},
    }
    import ui_bus
    ui_bus.publish("painel", acao="abrir", painel=painel, focar=True)
    return f"Painel de texto '{titulo}' aberto (id: {painel['id']})."
