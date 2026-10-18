"""Abre um painel lateral de ações genéricas (botões seguros do front)."""
import json
import re
import unicodedata

_ACOES = {"copiar", "abrir", "focar", "fechar"}


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "acoes"


def _normaliza(valor) -> list:
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except Exception:
            return []
    if not isinstance(valor, (list, tuple)):
        return []
    acoes = []
    for n, item in enumerate(valor[:8], 1):
        if not isinstance(item, dict):
            continue
        acao = str(item.get("acao") or "").strip()
        if acao not in _ACOES:
            continue
        rotulo = " ".join(str(item.get("rotulo") or item.get("id") or acao).split())[:40]
        nova = {"id": f"acao-{n}", "rotulo": rotulo, "tipo": "front", "acao": acao}
        if acao == "abrir":
            url = str(item.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            nova["url"] = url[:500]
        if acao == "copiar":
            texto = str(item.get("texto") or "").strip()[:2000]
            if not texto:
                continue
            nova["texto"] = texto
        acoes.append(nova)
    return acoes


def run(titulo: str, acoes: list) -> str:
    """
    titulo: título do painel
    acoes: lista de ações; cada uma com rotulo, acao (abrir/copiar/focar/fechar) e,
            quando abrir: url; quando copiar: texto
    """
    titulo = " ".join(str(titulo or "").split())[:80] or "Ações"
    lista = _normaliza(acoes)
    if not lista:
        return "Nenhuma ação de front válida foi informada."
    painel = {
        "id": "acoes-" + _slug(titulo),
        "tipo": "acoes",
        "titulo": titulo,
        "nomes": [titulo, "ações", "acoes", "atalhos"],
        "slot": "bottom-left",
        "fala": "nunca",
        "resumo": f"{len(lista)} ações rápidas.",
        "acoes": lista,
        "dados": {},
    }
    import ui_bus
    ui_bus.publish("painel", acao="abrir", painel=painel, focar=True)
    return f"Painel de ações '{titulo}' aberto ({len(lista)} botões, id: {painel['id']})."
