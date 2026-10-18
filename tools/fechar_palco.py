"""Fecha o card central (palco) da tela de pesquisa."""
def run() -> str:
    import ui_bus
    ui_bus.publish("painel", acao="fechar_palco")
    return "Palco central fechado."
