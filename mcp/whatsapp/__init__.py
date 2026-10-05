"""
mcp/whatsapp/
=============
Integração WhatsApp para o Ciel — dois modos independentes:

  Modo Bot   — o Ciel fica escutando mensagens recebidas via webhook do bridge
               e despacha cada uma pro run_agent do agente configurado.
               Ativado com: python bot.py (ou ciel bot)

  MCP        — tools pontuais (whatsapp_send, whatsapp_history) que o modelo
               pode chamar durante qualquer execução, como qualquer outro MCP.
               Ativado declarando o servidor no agente (.md) e rodando o bridge.

Ambos reaproveitam o mesmo bridge e a mesma sessão pareada.
Config compartilhada em whatsapp_channels.json na raiz do projeto.
"""

from . import channels  # noqa: F401

__all__ = ["channels"]
