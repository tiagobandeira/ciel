"""
token_tracker.py — Contador thread-safe de tokens do modelo secundário.

Canal simples entre secondary_model.py (que acumula) e a TUI (que lê e exibe).

Uso em secondary_model.py:
    import token_tracker
    token_tracker.add(tok_in, tok_out)

Uso na TUI (_agent_turn):
    token_tracker.reset()          # início do turno
    ...
    t2_in, t2_out = token_tracker.get()   # após run_agent
"""

import threading

_lock    = threading.Lock()
_tok_in  = 0
_tok_out = 0


def add(tok_in: int, tok_out: int) -> None:
    """Chamado pelo secondary_model após cada chamada à API."""
    global _tok_in, _tok_out
    with _lock:
        _tok_in  += tok_in
        _tok_out += tok_out


def reset() -> None:
    """Chamado pela TUI no início de cada turno do agente."""
    global _tok_in, _tok_out
    with _lock:
        _tok_in  = 0
        _tok_out = 0


def get() -> tuple[int, int]:
    """Retorna (tok_in, tok_out) acumulados desde o último reset."""
    with _lock:
        return _tok_in, _tok_out
