"""Abre um painel de tarefas/checklist na lateral da tela de pesquisa."""
import re
import unicodedata


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "tarefas"


def _lista(valor) -> list:
    if isinstance(valor, str):
        linhas = valor.splitlines()
    elif isinstance(valor, (list, tuple)):
        linhas = valor
    else:
        linhas = []
    itens = []
    for linha in linhas:
        texto = " ".join(str(linha or "").split())[:160]
        if texto:
            itens.append({"texto": texto, "feito": False})
        if len(itens) >= 20:
            break
    return itens


def run(titulo: str, itens: str) -> str:
    """
    titulo: título do painel (ex.: Tarefas da pesquisa)
    itens: tarefas separadas por linha
    """
    titulo = " ".join(str(titulo or "").split())[:80] or "Tarefas"
    lista = _lista(itens)
    if not lista:
        return "Informe pelo menos uma tarefa."
    painel = {
        "id": "tarefas-" + _slug(titulo),
        "tipo": "tarefas",
        "titulo": titulo,
        "nomes": [titulo, "tarefas", "checklist", "lista"],
        "slot": "bottom-left",
        "fala": "nunca",
        "resumo": f"{len(lista)} tarefas.",
        "acoes": [{"id": "limpar", "rotulo": "Limpar concluídas",
                   "tipo": "front", "acao": "limpar_concluidas"}],
        "dados": {"itens": lista},
    }
    import ui_bus
    ui_bus.publish("painel", acao="abrir", painel=painel, focar=True)
    return f"Painel de tarefas '{titulo}' aberto ({len(lista)} itens, id: {painel['id']})."
