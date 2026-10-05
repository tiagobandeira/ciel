"""
mcp/whatsapp/bot.py
===================
Loop principal do Modo Bot WhatsApp.

Fica escutando um webhook HTTP local onde o bridge deposita eventos de
mensagens recebidas. Cada mensagem válida (não from_me, dentro da allowlist)
dispara um run_agent com o agente configurado em whatsapp_channels.json.

Não é chamado diretamente — o entry point é bot.py na raiz do projeto
(ou `ciel bot`), que inicializa o ambiente e chama run_bot() daqui.

Contrato mínimo esperado do bridge (POST para /webhook do Ciel):
  {
    "chat_id": "5511999999999@s.whatsapp.net",
    "sender":  "+55 11 99999-9999",
    "text":    "mensagem do usuário",
    "type":    "direct" | "group",
    "mentions": [],
    "from_me": false
  }

O bridge também deve expor:
  GET  /status          → {"status": "connected"|"waiting_qr"|"disconnected"}
  POST /send            → {"chat_id": "...", "text": "..."}
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable

import requests

# ── caminhos — bot.py está em mcp/whatsapp/, raiz é 2 níveis acima ───────────
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from mcp.whatsapp import channels as ch
from agent_loader import load_agent, filter_tools
from tool_dispatch import filter_unsafe
from tools_registry import load_tools, tools_schema
from agent_loop import run_agent, AgentResult
from mcp.manager import MCPManager

# ── porta do webhook (o bridge envia eventos aqui) ───────────────────────────
WEBHOOK_PORT = 8766   # bridge_url é a URL do bridge; esta é a porta do Ciel

# ── histórico por chat_id (em memória, reseta ao reiniciar) ──────────────────
# Cada entrada: lista de {"role": "user"|"assistant", "content": "..."}
_histories: dict[str, list[dict]] = {}
_histories_lock = threading.Lock()


# ── callbacks de log (injetados pelo entry point) ─────────────────────────────

OnEvent  = Callable[[str, str, str], None]   # chat_id, sender, text
OnStep   = Callable[[int, str, str, str], None]
OnDone   = Callable[[str, int, int, int], None]
OnError  = Callable[[str, str], None]


# ── envio de resposta pro bridge ──────────────────────────────────────────────

def _send_reply(chat_id: str, text: str) -> bool:
    """Envia texto de volta ao bridge via POST /send. Retorna True se ok."""
    url = ch.bridge_url().rstrip("/") + "/send"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
        return resp.ok
    except Exception:
        return False


# ── processamento de uma mensagem ─────────────────────────────────────────────
def _handle_message(event, model, safe, on_event=None, on_step=None, on_done=None, on_error=None):
    try:
        _handle_message_inner(event, model, safe, on_event, on_step, on_done, on_error)
    except Exception as e:
        if on_error:
            on_error("exception", f"{type(e).__name__}: {e}")

def _handle_message_inner(
    event: dict,
    model: str,
    safe: bool,
    on_event:  OnEvent | None = None,
    on_step:   OnStep  | None = None,
    on_done:   OnDone  | None = None,
    on_error:  OnError | None = None,
) -> None:
    """
    Processa uma mensagem recebida do bridge em thread separada.
    Valida, despacha pro run_agent e envia a resposta de volta.
    """
    chat_id   = event.get("chat_id", "")
    sender    = event.get("sender", "")
    text      = event.get("text", "").strip()
    chat_type = event.get("type", "direct")

    if event.get("from_me"):
        if on_error:
            on_error("ignorado", "mensagem from_me")
        return

    if not ch.is_allowed(sender, chat_type):
        if on_error:
            on_error("ignorado", f"remetente {sender!r} ({chat_type}) fora da allowlist | chat_id={chat_id}")
        return

    # ── 3. ignora mensagens vazias ────────────────────────────────────────────
    if not text:
        return

    if on_event:
        on_event(chat_id, sender, text)

    # ── 4. carrega agente e tools ─────────────────────────────────────────────
    agent_name = ch.bot_agent()
    try:
        agent_info = load_agent(agent_name)
    except FileNotFoundError as e:
        if on_error:
            on_error("agent", str(e))
        _send_reply(chat_id, f"[Erro de configuração: agente '{agent_name}' não encontrado]")
        return

    all_tools = load_tools()
    tools     = filter_tools(all_tools, agent_info["allowed_tools"])
    tools     = filter_unsafe(tools, safe)

    # MCP: conecta servidores declarados no agente
    mcp_manager = MCPManager()
    allowed_servers = agent_info.get("allowed_mcp_servers")
    if allowed_servers is None:
        mcp_manager.connect_all()
    elif allowed_servers:
        mcp_manager.connect_servers(allowed_servers)
    from agent_loader import filter_mcp_tools
    mcp_tools = filter_mcp_tools(mcp_manager.all_tools(), allowed_servers)
    tools.update(mcp_tools)

    schema = tools_schema(tools)

    # ── 5. recupera histórico do chat ─────────────────────────────────────────
    with _histories_lock:
        history = list(_histories.get(chat_id, []))

    # ── 6. roda o loop agêntico ───────────────────────────────────────────────
    result: AgentResult = run_agent(
        user_input  = text,
        tools       = tools,
        schema      = schema,
        model       = model,
        agent_info  = agent_info,
        history     = history,
        session_id  = f"wa_{chat_id}",
        on_step     = on_step,
        on_done     = on_done,
        on_error    = on_error,
    )

    # ── 7. atualiza histórico ─────────────────────────────────────────────────
    with _histories_lock:
        h = _histories.setdefault(chat_id, [])
        h.append({"role": "user",      "content": text})
        h.append({"role": "assistant", "content": result.message})
        # mantém janela deslizante de 20 turnos (40 mensagens)
        if len(h) > 40:
            _histories[chat_id] = h[-40:]

    # ── 8. envia resposta ─────────────────────────────────────────────────────
    reply = result.message or "(sem resposta)"
    _send_reply(chat_id, reply)


# ── servidor de webhook ───────────────────────────────────────────────────────

def _make_handler(
    model: str,
    safe: bool,
    on_event:  OnEvent | None,
    on_step:   OnStep  | None,
    on_done:   OnDone  | None,
    on_error:  OnError | None,
):
    """Fabrica o handler HTTP com as dependências injetadas via closure."""

    class _Handler(BaseHTTPRequestHandler):

        def do_POST(self):
            if self.path != "/webhook":
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)

            try:
                event = json.loads(body)
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

            # processa em thread separada pra não bloquear o servidor
            t = threading.Thread(
                target=_handle_message_inner,
                args=(event, model, safe, on_event, on_step, on_done, on_error),
                daemon=True,
            )
            t.start()

        def log_message(self, fmt, *args):  # silencia logs padrão do BaseHTTP
            pass

    return _Handler


# ── status do bridge ──────────────────────────────────────────────────────────

def bridge_status() -> str:
    """Consulta o bridge e retorna o status da conexão."""
    url = ch.bridge_url().rstrip("/") + "/status"
    try:
        resp = requests.get(url, timeout=5)
        if resp.ok:
            return resp.json().get("status", "unknown")
        return "error"
    except requests.ConnectionError:
        return "disconnected"
    except Exception:
        return "error"


# ── entry point principal ─────────────────────────────────────────────────────

def run_bot(
    model: str,
    safe: bool = False,
    on_event:  OnEvent | None = None,
    on_step:   OnStep  | None = None,
    on_done:   OnDone  | None = None,
    on_error:  OnError | None = None,
    on_ready:  Callable[[], None] | None = None,
) -> None:
    """
    Inicia o loop do modo bot. Bloqueia até Ctrl+C.

    model     : nome do modelo Ollama a usar
    safe      : se True, desabilita tools de execução arbitrária
    on_*      : callbacks de log/display (injetados pelo bot.py da raiz)
    on_ready  : chamado após o servidor subir e o bridge estar acessível
    """
    if not ch.bot_enabled():
        print(
            "[whatsapp] Modo bot não está habilitado.\n"
            "  Configure com: /canal whatsapp  (ou edite whatsapp_channels.json)",
            file=sys.stderr,
        )
        sys.exit(1)

    handler_cls = _make_handler(model, safe, on_event, on_step, on_done, on_error)
    server      = HTTPServer(("127.0.0.1", WEBHOOK_PORT), handler_cls)

    if on_ready:
        on_ready()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
