"""Abre o feed de pesquisa no palco central, usando notícias, Bluesky e Wikimedia."""
from feed_builder import build_painel

OUTPUT = "external"


def run(tema: str = "", limite: int = 4) -> str:
    """
    tema: assunto que está sendo pesquisado (ex.: Lua, Artemis, dinossauros). Se vazio, usa um tema neutro.
    limite: quantidade inicial de itens (4 a 12; padrão 4). O restante vem pelo botão Carregar mais.
    """
    tema = " ".join(str(tema or "").split())[:80]
    try:
        n = max(4, min(int(limite or 4), 12))
    except (TypeError, ValueError):
        n = 4
    try:
        painel = build_painel(tema, n)
        itens = (painel.get("dados") or {}).get("itens") or []
        if not itens:
            return f"Não encontrei conteúdo aberto para montar o feed sobre '{tema or 'astronomia'}'."
        import ui_bus
        ui_bus.publish("painel", acao="abrir", painel=painel, focar=True, palco=True)
        return (f"Feed sobre '{painel['dados']['tema']}' aberto no palco central "
                f"({len(itens)} itens; notícias, Bluesky e Wikimedia; id: {painel['id']}).")
    except Exception as e:
        return f"Erro ao montar o feed de '{tema or 'astronomia'}': {str(e)[:140]}"
