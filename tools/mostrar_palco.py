"""Abre no card central (palco) um painel que já está aberto na lateral da tela de pesquisa."""
def run(id: str) -> str:
    """
    id: id do painel (ex.: imagens-lua)
    """
    pid = " ".join(str(id or "").split())[:60]
    if not pid:
        return "Informe o id do painel que deve ir para o palco."
    import ui_bus
    ui_bus.publish("painel", acao="palco", id=pid)
    return f"Painel '{pid}' aberto no palco central."
