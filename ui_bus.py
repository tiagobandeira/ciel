"""Barramento de eventos da interface visual do Ciel (pub/sub em memória, thread-safe).

Vale para o processo do server.py (Flask). CLI/TUI/bot rodam em outros processos
e não enxergam este barramento.
"""
import itertools
import json
import queue
import threading
import time

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


def callbacks(turn_id: str | None = None, coletor: list | None = None) -> dict:
    """Callbacks prontos para run_agent(..., **ui_bus.callbacks()).

    `turn_id` etiqueta os eventos do turno: a interface web monta o "fio de
    pensamento" só do turno atual e ignora o que vier de outra aba. O /ui não
    usa o campo — continua lendo os eventos antigos (estado/tool/erro/fala),
    que são publicados junto para não regredir aquela tela.

    `coletor`, se passado, recebe os mesmos eventos de `passo` para o server
    persistir no histórico (o acordeão reaparece ao reabrir a sessão).

    Eventos por turno (consumidos pelo site):
      pensando   {turn_id, step, ativo, ms}  começo/fim de cada chamada ao modelo
      passo      {turn_id, seq, step, label, texto, status, ms}
    O fim do turno (`turno_fim`) é publicado pelo server, que tem o resultado
    completo (status, steps e tokens).
    """
    seq = itertools.count(1)
    t0  = time.monotonic()

    def _ms() -> int:
        return int((time.monotonic() - t0) * 1000)

    def _emit(evento: dict) -> None:
        publish(**evento)
        if coletor is not None:
            coletor.append(evento)

    def on_model_start(step):
        publish("estado", valor="pensando", step=step)
        publish("pensando", turn_id=turn_id, step=step, ativo=True, ms=_ms())

    def on_model_end(step):
        publish("pensando", turn_id=turn_id, step=step, ativo=False, ms=_ms())

    def on_step(step, label, content, status):
        # eventos antigos — o /ui lê daqui e não pode regredir
        if status == "tool":
            publish("tool", nome=label.split("›")[-1].strip(), step=step, args=content)
        elif status in ("error", "parse_error"):
            publish("passo_erro", step=step, texto=str(content)[:120])
        # evento estruturado — consumido pelo site
        _emit({
            "tipo": "passo",
            "turn_id": turn_id,
            "seq": int(next(seq)),
            "step": step,
            "label": str(label),
            "texto": str(content)[:400],
            "status": status,
            "ms": _ms(),
        })

    def on_done(msg, steps, tok_in, tok_out):
        publish("fala", texto=msg, steps=steps)

    def on_limit(steps, tok_in, tok_out):
        publish("erro", texto=f"limite de {steps} steps atingido")

    def on_error(kind, message):
        publish("erro", texto=str(message)[:200])

    return dict(on_model_start=on_model_start, on_model_end=on_model_end,
                on_step=on_step, on_done=on_done,
                on_limit=on_limit, on_error=on_error)
