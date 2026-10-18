"""Fecha um painel da tela de pesquisa."""
def run(id: str) -> str:
    """
    id: id do painel (ex.: imagens-lua)
    """
    pid = " ".join(str(id or "").split())[:60]
    if not pid:
        return "Informe o id do painel."
    import ui_bus
    ui_bus.publish("painel", acao="fechar", id=pid)
    return f"Painel '{pid}' fechado."
