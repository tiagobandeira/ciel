"""Barramento de eventos da interface visual do Ciel (pub/sub em memória, thread-safe).

Vale para o processo do server.py (Flask). CLI/TUI/bot rodam em outros processos
e não enxergam este barramento.
"""
import json
import queue
import threading

_subs: set = set()
_lock = threading.Lock()


def publish(tipo: str, **dados) -> None:
    """Envia um evento {"tipo": tipo, ...dados} para todas as abas conectadas."""
    msg = json.dumps({"tipo": tipo, **dados}, ensure_ascii=False)
    with _lock:
        for q in list(_subs):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


def stream():
    """Gerador SSE: um por aba conectada."""
    q = queue.Queue(maxsize=200)
    with _lock:
        _subs.add(q)
    try:
        yield 'data: {"tipo":"estado","valor":"repouso"}\n\n'
        while True:
            try:
                yield f"data: {q.get(timeout=15)}\n\n"
            except queue.Empty:
                yield ": ping\n\n"
    finally:
        with _lock:
            _subs.discard(q)


def callbacks() -> dict:
    """Callbacks prontos para run_agent(..., **ui_bus.callbacks())."""
    def on_model_start(step):
        publish("estado", valor="pensando", step=step)

    def on_step(step, label, content, status):
        if status == "tool":
            publish("tool", nome=label.split("›")[-1].strip(), step=step, args=content)
        elif status in ("error", "parse_error"):
            publish("passo_erro", step=step, texto=str(content)[:120])

    def on_done(msg, steps, tok_in, tok_out):
        publish("fala", texto=msg, steps=steps)

    def on_limit(steps, tok_in, tok_out):
        publish("erro", texto=f"limite de {steps} steps atingido")

    def on_error(kind, message):
        publish("erro", texto=str(message)[:200])

    return dict(on_model_start=on_model_start, on_step=on_step, on_done=on_done,
                on_limit=on_limit, on_error=on_error)
