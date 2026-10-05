"""
mcp/whatsapp/router.py
======================
Roteador de comandos para o Modo Bot WhatsApp.

Interceta mensagens que começam com '/' e as trata como comandos diretos,
sem passar pelo run_agent. O texto sem '/' segue o fluxo normal.

Comandos disponíveis:
  /help            — lista os comandos disponíveis
  /task            — lista as tasks em tasks/
  /task <nome>     — executa a task pelo nome
  /novo            — reseta o histórico da sessão atual (sem derrubar o servidor)

Integração:
  router.handle(text, chat_id, context) → str | None
    Retorna a resposta como string se for um comando reconhecido,
    ou None se o texto não for um comando (fluxo normal).

  context é um dict com:
    histories       : dict[str, list[dict]]  — histórico global por chat_id
    histories_lock  : threading.Lock
    run_agent_fn    : callable               — run_agent com kwargs já parcialmente preenchidos
    send_reply_fn   : callable(chat_id, text)
    on_step         : callback opcional
    on_done         : callback opcional
    on_error        : callback opcional
    model           : str
    safe            : bool
    agent_info      : dict
    tools           : dict
    schema          : list
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

# ── raiz do projeto ───────────────────────────────────────────────────────────
_ROOT      = Path(__file__).parent.parent.parent
TASKS_DIR  = _ROOT / "tasks"

# ── timeout de sessão (minutos sem mensagem → reseta histórico) ───────────────
SESSION_TIMEOUT_MINUTES = 30


# ── formatação de texto simples (sem Rich, vai pro WhatsApp) ─────────────────

def _fmt_task_list(tasks: list[Path]) -> str:
    if not tasks:
        return "Nenhuma task disponível em tasks/."
    lines = ["📋 *Tasks disponíveis:*\n"]
    for t in tasks:
        lines.append(f"  • {t.stem}")
    lines.append("\nUse */task <nome>* para executar.")
    return "\n".join(lines)


def _fmt_help() -> str:
    return (
        "🤖 *Comandos disponíveis:*\n\n"
        "  */help*           este menu\n"
        "  */task*           lista tasks disponíveis\n"
        "  */task <nome>*    executa uma task\n"
        "  */novo*           reseta o histórico da conversa\n\n"
        "Qualquer mensagem sem '/' é tratada normalmente pelo agente."
    )


# ── handlers individuais ──────────────────────────────────────────────────────

def _cmd_help(**_) -> str:
    return _fmt_help()


def _cmd_novo(chat_id: str, histories: dict, histories_lock: threading.Lock, **_) -> str:
    with histories_lock:
        if chat_id in histories:
            del histories[chat_id]
    return "✅ Histórico resetado. Nova sessão iniciada."


def _cmd_task_list(**_) -> str:
    if not TASKS_DIR.exists():
        return "Pasta tasks/ não encontrada."
    tasks = sorted(TASKS_DIR.glob("*.md"))
    return _fmt_task_list(tasks)


def _cmd_task_run(
    task_name: str,
    chat_id: str,
    histories: dict,
    histories_lock: threading.Lock,
    run_agent_fn: Callable,
    send_reply_fn: Callable,
    on_step,
    on_done,
    on_error,
    model: str,
    safe: bool,
    agent_info: dict,
    tools: dict,
    schema: list,
    **_,
) -> str:
    """Carrega e executa uma task, despachando pro run_agent."""
    # importa aqui pra não criar dependência circular na inicialização
    from cli import load_task, find_tasks

    # tenta pelo nome exato primeiro
    task_path = TASKS_DIR / f"{task_name}.md"
    if not task_path.exists():
        candidates = find_tasks(task_name, TASKS_DIR)
        if not candidates:
            return f"❌ Task '{task_name}' não encontrada. Use */task* para ver as disponíveis."
        if len(candidates) > 1:
            nomes = "\n".join(f"  • {c.stem}" for c in candidates)
            return f"Encontrei mais de uma task com esse nome:\n{nomes}\n\nSeja mais específico."
        task_path = candidates[0]

    task = load_task(task_path)
    if not task:
        return f"❌ Arquivo '{task_path.name}' não segue o formato de task."

    # monta o prompt como se o usuário tivesse digitado o objetivo
    task_prompt = (
        f"Execute a task '{task_path.stem}'.\n\n"
        f"Objetivo: {task['objetivo']}\n\n"
        f"Ações:\n" + "\n".join(f"- {a}" for a in task.get("acoes", []))
    )

    # recupera histórico
    with histories_lock:
        history = list(histories.get(chat_id, []))

    result = run_agent_fn(
        user_input = task_prompt,
        tools      = tools,
        schema     = schema,
        model      = model,
        agent_info = agent_info,
        history    = history,
        session_id = f"wa_{chat_id}_task_{task_path.stem}",
        on_step    = on_step,
        on_done    = on_done,
        on_error   = on_error,
    )

    # atualiza histórico
    with histories_lock:
        h = histories.setdefault(chat_id, [])
        h.append({"role": "user",      "content": task_prompt})
        h.append({"role": "assistant", "content": result.message})
        if len(h) > 40:
            histories[chat_id] = h[-40:]

    return result.message or "(task concluída sem resposta)"


# ── timeout automático de sessão ──────────────────────────────────────────────

# last_seen[chat_id] = timestamp da última mensagem
_last_seen: dict[str, float] = {}
_last_seen_lock = threading.Lock()


def record_activity(chat_id: str) -> None:
    """Registra atividade recente de um chat_id."""
    import time
    with _last_seen_lock:
        _last_seen[chat_id] = time.monotonic()


def expire_idle_sessions(histories: dict, histories_lock: threading.Lock) -> None:
    """
    Reseta histórico de chats inativos há mais de SESSION_TIMEOUT_MINUTES.
    Deve ser chamado periodicamente (ex: a cada minuto num thread daemon).
    """
    import time
    cutoff = time.monotonic() - SESSION_TIMEOUT_MINUTES * 60
    with _last_seen_lock:
        expired = [cid for cid, ts in _last_seen.items() if ts < cutoff]
        for cid in expired:
            del _last_seen[cid]
    if expired:
        with histories_lock:
            for cid in expired:
                histories.pop(cid, None)


def start_session_gc(histories: dict, histories_lock: threading.Lock) -> None:
    """Inicia thread daemon que expira sessões ociosas a cada minuto."""
    import time

    def _loop():
        while True:
            time.sleep(60)
            expire_idle_sessions(histories, histories_lock)

    t = threading.Thread(target=_loop, daemon=True, name="session-gc")
    t.start()


# ── entry point principal ─────────────────────────────────────────────────────

def handle(text: str, chat_id: str, context: dict) -> str | None:
    """
    Verifica se 'text' é um comando '/'.
    Retorna a resposta (str) se for comando reconhecido, ou None caso contrário.
    """
    if not text.startswith("/"):
        return None

    # registra atividade (usado pelo GC de sessão)
    record_activity(chat_id)

    parts     = text.strip().split(None, 1)
    cmd       = parts[0].lower()
    arg       = parts[1].strip() if len(parts) > 1 else ""

    ctx = {**context, "chat_id": chat_id}

    if cmd == "/help":
        return _cmd_help(**ctx)

    if cmd == "/novo":
        return _cmd_novo(**ctx)

    if cmd == "/task":
        if not arg:
            return _cmd_task_list(**ctx)
        return _cmd_task_run(task_name=arg, **ctx)

    # comando não reconhecido — sugere /help
    return f"Comando '{cmd}' não reconhecido. Use */help* para ver os disponíveis."
