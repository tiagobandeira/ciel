"""
mcp/telegram/server.py
======================
Servidor MCP para Telegram via Bot API.
Implementa JSON-RPC 2.0 sobre stdio — sem dependências além de `requests`.

Uso (teste manual):
    TELEGRAM_BOT_TOKEN="seu_token" python mcp/telegram/server.py

Adicionando ao Ciel:
    mcp_add_server(
        name="telegram",
        type="stdio",
        command="python",
        args="mcp/telegram/server.py",
        env="TELEGRAM_BOT_TOKEN=seu_token"
    )

Dependências:
    pip install requests
"""

import json
import os
import sys
from pathlib import Path

import requests

# channels.py — cache de canais na raiz do projeto
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from mcp.telegram import channels as ch_cache

# ── Configuração ───────────────────────────────────────────────────────────────

TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""


# ── Bot API helper ─────────────────────────────────────────────────────────────

def _api(method: str, payload: dict) -> dict:
    resp = requests.post(f"{API_URL}/{method}", json=payload, timeout=15)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Erro desconhecido da API"))
    return data["result"]


def _save_chat(chat: dict) -> None:
    """Salva um chat do Telegram no cache de canais."""
    if not chat.get("id"):
        return
    ch_cache.upsert({
        "title":    chat.get("title", ""),
        "id":       str(chat["id"]),
        "username": f"@{chat['username']}" if chat.get("username") else "",
    })


# ── Tools ──────────────────────────────────────────────────────────────────────

def get_channel(name: str) -> str:
    """
    Resolve um canal pelo nome, título, @username ou id numérico.
    Busca no cache primeiro; se não achar, consulta get_updates e salva.
    """
    found = ch_cache.find(name)
    if found:
        return json.dumps(found, ensure_ascii=False)

    # tenta descobrir via get_updates
    try:
        updates = _api("getUpdates", {})
        for upd in updates:
            for key in ("message", "channel_post", "edited_channel_post"):
                if key in upd:
                    _save_chat(upd[key].get("chat", {}))
    except RuntimeError as e:
        return f"Erro ao consultar Telegram: {e}"

    found = ch_cache.find(name)
    if found:
        return json.dumps(found, ensure_ascii=False)

    return (
        f"Canal '{name}' não encontrado. "
        "Se for privado, envie uma mensagem nele e tente novamente. "
        "Se for público, use get_channel_info com o @username diretamente."
    )


def list_channels() -> str:
    """Lista todos os canais salvos no cache local."""
    all_ch = ch_cache.list_all()
    if not all_ch:
        return "Cache vazio. Use get_channel ou get_updates para descobrir canais."
    return json.dumps(all_ch, ensure_ascii=False, indent=2)


def send_message(channel_id: str, text: str, parse_mode: str = "Markdown",
                 disable_notification: bool = False) -> str:
    payload = {"chat_id": channel_id, "text": text,
               "disable_notification": disable_notification}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    r = _api("sendMessage", payload)
    # salva o canal no cache — a resposta do sendMessage inclui o chat completo
    _save_chat(r.get("chat", {}))
    return f"Mensagem enviada. message_id: {r['message_id']}"


def send_photo(channel_id: str, photo: str, caption: str = "",
               parse_mode: str = "Markdown") -> str:
    payload = {"chat_id": channel_id, "photo": photo}
    if caption:
        payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
    r = _api("sendPhoto", payload)
    _save_chat(r.get("chat", {}))
    return f"Foto enviada. message_id: {r['message_id']}"


def edit_message(channel_id: str, message_id: int, new_text: str,
                 parse_mode: str = "Markdown") -> str:
    payload = {"chat_id": channel_id, "message_id": message_id, "text": new_text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    r = _api("editMessageText", payload)
    _save_chat(r.get("chat", {}))
    return f"Mensagem {message_id} editada."


def delete_message(channel_id: str, message_id: int) -> str:
    _api("deleteMessage", {"chat_id": channel_id, "message_id": message_id})
    return f"Mensagem {message_id} deletada."


def get_channel_info(channel_id: str) -> str:
    r = _api("getChat", {"chat_id": channel_id})
    info = {k: r.get(k, "") for k in ("id", "title", "username", "type", "description")}
    try:
        info["member_count"] = _api("getChatMemberCount", {"chat_id": channel_id})
    except RuntimeError:
        pass
    _save_chat(r)
    return json.dumps(info, ensure_ascii=False, indent=2)


def get_updates() -> str:
    """Retorna atualizações recentes e salva canais novos no cache."""
    result = _api("getUpdates", {})
    if not result:
        return "Nenhuma atualização. Envie uma mensagem no canal e tente de novo."
    chats = []
    for upd in result:
        for key in ("message", "channel_post", "edited_channel_post"):
            if key in upd:
                chat = upd[key].get("chat", {})
                _save_chat(chat)
                if chat.get("id"):
                    chats.append({
                        "chat_id":  chat.get("id"),
                        "title":    chat.get("title", ""),
                        "username": f"@{chat['username']}" if chat.get("username") else "",
                        "type":     chat.get("type", ""),
                    })
    return json.dumps(chats, ensure_ascii=False, indent=2)


# ── Schema MCP ─────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_channel",
        "description": (
            "Resolve o canal pelo nome/título/@username/id e retorna {title, id, username}. "
            "Usa cache local — se não encontrar, consulta o servidor e salva automaticamente. "
            "Use SEMPRE antes de send_message quando não souber o channel_id exato."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Título parcial, @username ou id numérico do canal"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_channels",
        "description": "Lista todos os canais salvos no cache local (title, id, username).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "send_message",
        "description": "Envia uma mensagem de texto. Salva o canal no cache automaticamente.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id":           {"type": "string",  "description": "@username ou chat_id numérico"},
                "text":                 {"type": "string",  "description": "Texto da mensagem"},
                "parse_mode":           {"type": "string",  "description": "Markdown, HTML ou vazio (padrão: Markdown)"},
                "disable_notification": {"type": "boolean", "description": "Enviar silenciosamente (padrão: false)"},
            },
            "required": ["channel_id", "text"],
        },
    },
    {
        "name": "send_photo",
        "description": "Envia uma foto para um canal do Telegram.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "@username ou chat_id numérico"},
                "photo":      {"type": "string", "description": "URL pública ou file_id do Telegram"},
                "caption":    {"type": "string", "description": "Legenda (opcional)"},
                "parse_mode": {"type": "string", "description": "Markdown, HTML ou vazio"},
            },
            "required": ["channel_id", "photo"],
        },
    },
    {
        "name": "edit_message",
        "description": "Edita uma mensagem existente enviada pelo bot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string",  "description": "@username ou chat_id numérico"},
                "message_id": {"type": "integer", "description": "ID da mensagem"},
                "new_text":   {"type": "string",  "description": "Novo texto"},
                "parse_mode": {"type": "string",  "description": "Markdown, HTML ou vazio"},
            },
            "required": ["channel_id", "message_id", "new_text"],
        },
    },
    {
        "name": "delete_message",
        "description": "Deleta uma mensagem (bot precisa ser admin com permissão de deletar).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string",  "description": "@username ou chat_id numérico"},
                "message_id": {"type": "integer", "description": "ID da mensagem"},
            },
            "required": ["channel_id", "message_id"],
        },
    },
    {
        "name": "get_channel_info",
        "description": "Retorna info do canal (título, tipo, membros) e salva no cache.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "@username ou chat_id numérico"},
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "get_updates",
        "description": "Retorna atualizações recentes e salva canais novos no cache. Útil para descobrir chat_ids privados.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]

TOOL_MAP = {
    "get_channel":      get_channel,
    "list_channels":    list_channels,
    "send_message":     send_message,
    "send_photo":       send_photo,
    "edit_message":     edit_message,
    "delete_message":   delete_message,
    "get_channel_info": get_channel_info,
    "get_updates":      get_updates,
}


# ── Loop JSON-RPC 2.0 ──────────────────────────────────────────────────────────

def _respond(req_id, result):
    print(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}), flush=True)


def _error(req_id, code, message):
    print(json.dumps({"jsonrpc": "2.0", "id": req_id,
                      "error": {"code": code, "message": message}}), flush=True)


def _handle(req: dict) -> None:
    method = req.get("method", "")
    params = req.get("params", {})
    req_id = req.get("id")

    if method == "initialize":
        resp = {
            "protocolVersion": "2024-11-05",
            "capabilities":    {"tools": {}},
            "serverInfo":      {"name": "telegram", "version": "1.1.0"},
        }
        if not TOKEN:
            resp["_warning"] = "TELEGRAM_BOT_TOKEN não definido — tools retornarão erro"
        _respond(req_id, resp)

    elif method == "notifications/initialized":
        pass

    elif method == "tools/list":
        _respond(req_id, {"tools": TOOLS})

    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        if not TOKEN:
            _respond(req_id, {"content": [{"type": "text", "text":
                "Erro: TELEGRAM_BOT_TOKEN não definido. "
                "Remova e adicione novamente com env='TELEGRAM_BOT_TOKEN=seu_token'."}]})
            return
        fn = TOOL_MAP.get(name)
        if fn is None:
            _error(req_id, -32601, f"Tool desconhecida: '{name}'")
            return
        try:
            text = fn(**args)
        except TypeError as e:
            text = f"Parâmetros inválidos: {e}"
        except RuntimeError as e:
            text = f"Erro da API Telegram: {e}"
        except Exception as e:
            text = f"Erro inesperado: {e}"
        _respond(req_id, {"content": [{"type": "text", "text": text}]})

    else:
        _error(req_id, -32601, f"Método desconhecido: '{method}'")


def main() -> None:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()