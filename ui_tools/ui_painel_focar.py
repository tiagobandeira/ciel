"""Destaca na tela de pesquisa um painel que já está aberto."""
def run(id: str) -> str:
    """
    id: id do painel (ex.: imagens-lua)
    """
    pid = " ".join(str(id or "").split())[:60]
    if not pid:
        return "Informe o id do painel."
    import ui_bus
    ui_bus.publish("painel", acao="focar", id=pid)
    return f"Painel '{pid}' destacado na tela."
