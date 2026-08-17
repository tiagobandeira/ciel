"""
history_ui.py — Interface interativa de seleção de sessões salvas.

Usa prompt_toolkit para navegação com ↑↓ + Enter.
Retorna a sessão escolhida ou None se cancelado.
"""

from __future__ import annotations

import sqlite3
from typing import Callable

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style


# ── seletor interativo ↑↓ ────────────────────────────────────────────────────

class SessionPicker:
    """
    TUI minimalista para selecionar uma sessão com ↑↓ + Enter.

    Parâmetros
    ----------
    sessions : list[sqlite3.Row]
        Linhas retornadas por HistoryStore.list_sessions()
    title : str
        Cabeçalho exibido acima da lista.
    """

    STYLE = Style.from_dict({
        "header":   "bold ansicyan",
        "selected": "bold ansiwhite bg:ansiblue",
        "normal":   "ansiwhite",
        "footer":   "ansidarkgray",
        "star":     "ansiyellow",
        "branch":   "ansicyan",
    })

    def __init__(self, sessions: list[sqlite3.Row], title: str = "Histórico de conversas"):
        self._sessions = sessions
        self._title    = title
        self._cursor   = 0
        self._result: sqlite3.Row | None = None
        self._cancelled = False

    def _make_text(self) -> list:
        """Gera o conteúdo formatado da lista."""
        lines = [("class:header", f" {self._title}\n")]
        lines.append(("class:footer", f" {'─' * 60}\n"))

        for i, row in enumerate(self._sessions):
            selected = i == self._cursor
            prefix   = " ▶ " if selected else "   "
            style    = "class:selected" if selected else "class:normal"

            has_sum  = ("class:star", "★ ") if row["summary"] else ("class:normal", "  ")
            date     = row["updated_at"][:16]
            agent    = row["agent_id"]
            turns    = row["turn_count"]
            title    = (row["title"] or "(sem título)")[:46]

            branch_marker = ""
            if row["parent_session_id"]:
                branch_marker = " ↪"

            line = f"{prefix}[{date}] {agent:<14} {turns:>3}t  {title}{branch_marker}\n"

            lines.append((style, prefix))
            lines.append(has_sum)
            lines.append((style, f"[{date}] {agent:<14} {turns:>3}t  {title}{branch_marker}\n"))

        lines.append(("class:footer", f"\n ↑↓ navegar   Enter selecionar   q cancelar\n"))
        return lines

    def run(self) -> sqlite3.Row | None:
        """Executa o picker e retorna a sessão selecionada, ou None."""
        if not self._sessions:
            return None

        kb = KeyBindings()

        @kb.add("up")
        def _up(event):
            self._cursor = max(0, self._cursor - 1)

        @kb.add("down")
        def _down(event):
            self._cursor = min(len(self._sessions) - 1, self._cursor + 1)

        @kb.add("enter")
        def _enter(event):
            self._result = self._sessions[self._cursor]
            event.app.exit()

        @kb.add("q")
        @kb.add("c-c")
        @kb.add("escape")
        def _cancel(event):
            self._cancelled = True
            event.app.exit()

        control = FormattedTextControl(self._make_text, focusable=True)

        def _refresh_text():
            control.text = self._make_text

        # reconstrói o texto a cada tecla
        @kb.add("<any>")
        def _any(event):
            pass  # prompt_toolkit re-renderiza automaticamente

        layout = Layout(
            HSplit([
                Window(
                    content=FormattedTextControl(lambda: self._make_text()),
                    wrap_lines=False,
                )
            ])
        )

        app: Application = Application(
            layout=layout,
            key_bindings=kb,
            style=self.STYLE,
            full_screen=False,
            mouse_support=False,
        )

        app.run()
        return self._result if not self._cancelled else None


# ── display de conversa carregada ─────────────────────────────────────────────

MAX_LINES_PREVIEW = 60   # máximo de linhas Q&A exibidas no terminal

def format_conversation_preview(
    turns: list[sqlite3.Row],
    session_title: str = "",
    max_lines: int = MAX_LINES_PREVIEW,
) -> str:
    """
    Formata a conversa como texto Q&A para exibição no terminal.
    Trunca no meio se for muito grande, indicando o corte.
    """
    lines: list[str] = []

    if session_title:
        lines.append(f"══ {session_title} ══")
        lines.append("")

    all_lines: list[str] = []
    for turn in turns:
        label   = "você" if turn["role"] == "user" else "agente"
        ts_part = f"  {turn['ts']}" if turn["ts"] else ""
        all_lines.append(f"[{label}{ts_part}]")
        # quebra conteúdo longo em sub-linhas
        for ln in turn["content"].splitlines():
            all_lines.append(f"  {ln}" if ln.strip() else "")
        all_lines.append("")

    total = len(all_lines)
    if total <= max_lines:
        lines.extend(all_lines)
    else:
        half     = max_lines // 2
        kept_top = all_lines[:half]
        kept_bot = all_lines[total - half:]
        skipped  = total - max_lines
        lines.extend(kept_top)
        lines.append(f"  … [{skipped} linhas omitidas — use /history exportar para ver tudo] …")
        lines.append("")
        lines.extend(kept_bot)

    return "\n".join(lines)


def build_context_injection(summary: str, session_title: str, agent_id: str) -> str:
    """
    Monta o bloco de texto que será injetado no system prompt
    ao ramificar uma sessão anterior.
    """
    return (
        f"## Contexto de sessão anterior\n"
        f"Sessão: {session_title!r}  |  Agente: {agent_id}\n\n"
        f"{summary}\n\n"
        f"---\n"
        f"Esta é uma nova sessão. Considere o contexto acima para retomar o trabalho "
        f"de onde parou, mas não repita o que já foi feito a menos que seja solicitado."
    )
