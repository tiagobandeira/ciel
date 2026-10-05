"""Envia uma mensagem de texto pelo WhatsApp via bridge local."""

import json
from pathlib import Path
import sys

# garante que mcp/whatsapp/channels.py seja encontrado mesmo quando a tool
# é chamada de dentro do loop do agente (cwd pode variar)
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import requests

OUTPUT = "internal"


def run(chat_id: str, text: str) -> str:
    """
    chat_id : JID do destinatário (ex: "5511999999999@s.whatsapp.net")
              ou número normalizado (ex: "+55 11 99999-9999") — o bridge resolve
    text    : mensagem a enviar (texto simples, sem markdown)
    """
    try:
        from mcp.whatsapp.channels import bridge_url
        url = bridge_url().rstrip("/") + "/send"
    except Exception as e:
        return f"Erro ao carregar config do WhatsApp: {e}"

    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        if resp.ok:
            return f"Mensagem enviada para {chat_id}."
        return f"Bridge retornou erro {resp.status_code}: {resp.text[:200]}"
    except requests.ConnectionError:
        return (
            "Bridge não acessível. Verifique se o bridge está rodando "
            f"e se bridge_url em whatsapp_channels.json está correto."
        )
    except Exception as e:
        return f"Erro ao enviar mensagem: {e}"
